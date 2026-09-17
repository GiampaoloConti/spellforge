"""Host side of the sandbox: runs one plugin in a separate, restricted process.

`PluginSandbox.start(plugin_id, source)` returns a `Plugin` whose hooks are proxies. When the
engine calls a hook, the proxy sends the call to the worker process and serves the worker's
`ctx` requests against the real game context until the hook returns.

Defense in depth, in order:
1. static validation (`validator.py`) before the process even receives the source;
2. the restricted plugin namespace (no imports, safe builtins only);
3. a separate process started in isolated mode with an empty environment (no API keys),
   in a temporary working directory;
4. a memory cap and no child processes (Job Object on Windows; rlimits on POSIX, plus no
   file writes and, where the kernel allows unprivileged namespaces, no network: see
   `hardening.py`);
5. per-message timeouts: a hook that stops talking is killed and reported as an error.

Not covered: reading files the server's OS user can read. The worker runs as the same user,
so a deployment should keep secrets in the environment (the server process is made
non-dumpable, so its environment cannot be read through /proc), not in files.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from typing import Any

from spellforge.engine.api import Ctx, PluginError
from spellforge.engine.plugins import Plugin, PluginLoadError, make_namespace
from spellforge.sandbox.codec import decode, encode
from spellforge.sandbox.validator import validate_source

CTX_METHODS = frozenset(Ctx.__abstractmethods__)
DEFAULT_CALL_TIMEOUT = 1.0
DEFAULT_LOAD_TIMEOUT = 10.0
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024


def sandbox_environment() -> dict[str, str]:
    """An almost empty environment: no API keys or other secrets reach plugin code.

    Windows needs SYSTEMROOT for Python to start (sockets, random); nothing else is passed.
    """
    return {"SYSTEMROOT": os.environ["SYSTEMROOT"]} if "SYSTEMROOT" in os.environ else {}


class SandboxProcess:
    """The worker subprocess plus a reader thread (pipes can't be polled on Windows)."""

    def __init__(self) -> None:
        self._workdir = tempfile.TemporaryDirectory(
            prefix="spellforge-sandbox-", ignore_cleanup_errors=True
        )
        self.process = subprocess.Popen(
            [sys.executable, "-I", "-B", "-m", "spellforge.sandbox.worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=self._workdir.name,
            env=sandbox_environment(),
        )
        self._job = _limit_windows_process(self.process) if sys.platform == "win32" else None
        self._messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            try:
                self._messages.put(json.loads(line))
            except ValueError:
                break
        self._messages.put(None)

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(json.dumps(message).encode() + b"\n")
            self.process.stdin.flush()
        except OSError as exc:
            raise PluginError("the plugin's sandbox process has stopped") from exc

    def receive(self, timeout: float) -> dict[str, Any]:
        try:
            message = self._messages.get(timeout=timeout)
        except queue.Empty:
            self.kill()
            raise PluginError(
                f"plugin did not respond within {timeout:g}s and was stopped"
            ) from None
        if message is None:
            code = self.process.wait()
            raise PluginError(f"the plugin's sandbox process exited (code {code})")
        return message

    def kill(self) -> None:
        if self.alive:
            self.process.kill()
            self.process.wait()
        if self._job is not None:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._job)
            self._job = None
        self._workdir.cleanup()


class PluginSandbox:
    def __init__(
        self,
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
        load_timeout: float = DEFAULT_LOAD_TIMEOUT,
    ) -> None:
        self.call_timeout = call_timeout
        self.load_timeout = load_timeout
        self._process: SandboxProcess | None = None

    @classmethod
    def start(cls, plugin_id: str, source: str, **options: float) -> tuple[PluginSandbox, Plugin]:
        """Validate, launch and load a plugin. Raises PluginLoadError with a helpful message."""
        problems = validate_source(source)
        if problems:
            raise PluginLoadError("; ".join(map(str, problems)))
        sandbox = cls(**options)
        try:
            return sandbox, sandbox._load(plugin_id, source)
        except BaseException:
            sandbox.close()
            raise

    def close(self) -> None:
        if self._process is not None:
            if self._process.alive:
                try:
                    self._process.send({"op": "exit"})
                except PluginError:
                    pass
            self._process.kill()
            self._process = None

    # ---- loading ---------------------------------------------------------------

    def _load(self, plugin_id: str, source: str) -> Plugin:
        self._process = SandboxProcess()
        self._process.send({"op": "load", "plugin_id": plugin_id, "source": source})
        try:
            reply = self._process.receive(self.load_timeout)
        except PluginError as exc:
            raise PluginLoadError(str(exc)) from exc
        if reply.get("op") == "load_error":
            raise PluginLoadError(str(reply.get("message")))
        if reply.get("op") != "loaded":
            raise PluginLoadError("the sandbox sent an unexpected reply")
        return self._rebuild(plugin_id, source, reply)

    def _rebuild(self, plugin_id: str, source: str, description: dict[str, Any]) -> Plugin:
        """Recreate the definitions host-side, with proxy hooks.

        The metadata goes back through the same `define_*` functions plugins use, so a
        misbehaving worker cannot hand the engine invalid definitions.
        """
        plugin = Plugin(id=plugin_id, source=source)
        api = make_namespace(plugin)
        try:
            for sprite in description["sprites"]:
                api["define_sprite"](**sprite)
            for spell in description["spells"]:
                api["define_spell"](**spell, on_cast=self._hook(f"spell:{spell['id']}:on_cast"))
            for status in description["statuses"]:
                fields = {k: v for k, v in status.items() if k != "hooks"}
                hooks = {
                    name: self._hook(f"status:{status['id']}:{name}") for name in status["hooks"]
                }
                api["define_status"](**fields, **hooks)
            for monster in description["monsters"]:
                fields = {k: v for k, v in monster.items() if k != "has_act"}
                act = self._hook(f"monster:{monster['id']}:act") if monster["has_act"] else None
                api["define_monster"](**fields, act=act)
        except (KeyError, TypeError) as exc:
            raise PluginLoadError(f"the sandbox described the plugin incorrectly: {exc}") from exc
        return plugin

    def _hook(self, key: str) -> Callable[..., None]:
        def hook(ctx: Ctx, *args: Any) -> None:
            self.call(ctx, key, args)

        hook.__qualname__ = f"sandboxed:{key}"
        return hook

    # ---- running hooks -----------------------------------------------------------

    def call(self, ctx: Ctx, key: str, args: tuple[Any, ...]) -> None:
        """Run a hook in the worker, serving its ctx requests, until it returns."""
        process = self._process
        if process is None or not process.alive:
            raise PluginError("the plugin's sandbox is not running")
        process.send({"op": "call", "key": key, "args": encode(args)})
        # Errors raised by the real ctx are remembered: even if the plugin catches them,
        # misusing the API still counts as a failure (same rule as in-process plugins).
        ctx_error: Exception | None = None
        while True:
            message = process.receive(self.call_timeout)
            op = message.get("op")
            if op == "ctx":
                try:
                    value = self._serve_ctx(ctx, message)
                except Exception as exc:  # noqa: BLE001 - forwarded to the plugin
                    ctx_error = ctx_error or exc
                    process.send({"op": "ctx_error", "message": f"{type(exc).__name__}: {exc}"})
                else:
                    process.send({"op": "result", "value": value})
            elif op == "return":
                if ctx_error is not None:
                    raise ctx_error
                return
            elif op == "error":
                if ctx_error is not None:
                    raise ctx_error
                error = PluginError(str(message.get("message")))
                error.reason = error.args[0]  # e.g. "ZeroDivisionError: division by zero"
                raise error
            else:
                process.kill()
                raise PluginError("the plugin's sandbox sent an invalid message")

    def _serve_ctx(self, ctx: Ctx, message: dict[str, Any]) -> Any:
        method = message.get("method")
        if method not in CTX_METHODS:
            raise PluginError(f"ctx has no method {method!r}")
        args = decode(message.get("args", []))
        kwargs = {str(k): decode(v) for k, v in dict(message.get("kwargs", {})).items()}
        return encode(getattr(ctx, method)(*args, **kwargs))


def _limit_windows_process(process: subprocess.Popen[bytes]) -> int:
    """Put the process in a Job Object: memory cap, no child processes, killed with the job."""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in ("Read", "Write", "Other", "ReadBytes", "WriteBytes", "OtherBytes")
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job_object_extended_limit_information = 9
    limit_active_process = 0x0008
    limit_process_memory = 0x0100
    limit_kill_on_job_close = 0x2000

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = (
        limit_active_process | limit_process_memory | limit_kill_on_job_close
    )
    limits.BasicLimitInformation.ActiveProcessLimit = 1
    limits.ProcessMemoryLimit = MEMORY_LIMIT_BYTES
    ok = kernel32.SetInformationJobObject(
        wintypes.HANDLE(job),
        job_object_extended_limit_information,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    )
    handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
    if not ok or not kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), handle):
        error = ctypes.get_last_error()
        process.kill()
        kernel32.CloseHandle(wintypes.HANDLE(job))
        raise OSError(error, "could not apply sandbox limits to the plugin process")
    return job
