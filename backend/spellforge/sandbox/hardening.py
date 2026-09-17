"""Operating-system restrictions for the server and the plugin worker processes (POSIX).

Generated plugins are already confined by the AST validator and the restricted namespace:
they cannot import, open files or reach dunders. These measures assume that confinement has
failed and limit what an escaped plugin could do on a Linux host such as a Hugging Face
Space. Every step is best effort: when the kernel or container refuses one, the rest still
apply. On Windows the host uses a Job Object instead (see `host.py`).

Server process:
- not dumpable, so other processes of the same user cannot read `/proc/<pid>/environ`
  (where the ANTHROPIC_API_KEY lives) or attach a debugger.

Worker process (applied before it receives any plugin source):
- a memory cap (RLIMIT_AS);
- no new processes (RLIMIT_NPROC 0) and no core dumps;
- no writing to files (RLIMIT_FSIZE 0, with SIGXFSZ ignored so writes just fail);
- a fresh, empty network namespace when unprivileged user namespaces are allowed: no network.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import signal
import sys

logger = logging.getLogger(__name__)

PR_SET_DUMPABLE = 4
CLONE_NEWUSER = 0x10000000
CLONE_NEWNET = 0x40000000


def _libc() -> ctypes.CDLL | None:
    name = ctypes.util.find_library("c")
    return ctypes.CDLL(name, use_errno=True) if name else None


def protect_server_process() -> bool:
    """Make the server process non-dumpable (Linux). Returns True if applied."""
    if not sys.platform.startswith("linux"):
        return False
    libc = _libc()
    applied = libc is not None and libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
    logger.info("server process non-dumpable: %s", applied)
    return applied


def restrict_worker(memory_bytes: int) -> list[str]:
    """Apply the worker restrictions this platform allows; returns the names applied."""
    applied: list[str] = []
    if sys.platform.startswith("linux") and _isolate_network():
        applied.append("no network")
    try:
        import resource
    except ImportError:  # Windows: the host's Job Object covers memory and processes
        return applied

    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    limits = [
        ("memory cap", resource.RLIMIT_AS, memory_bytes),
        ("no core dumps", resource.RLIMIT_CORE, 0),
        ("no file writes", resource.RLIMIT_FSIZE, 0),
        ("no new processes", getattr(resource, "RLIMIT_NPROC", None), 0),
    ]
    for name, which, value in limits:
        if which is None:
            continue
        try:
            resource.setrlimit(which, (value, value))
            applied.append(name)
        except (OSError, ValueError):
            pass
    return applied


def _isolate_network() -> bool:
    """Move into new user + network namespaces: only a downed loopback interface remains."""
    libc = _libc()
    return libc is not None and libc.unshare(CLONE_NEWUSER | CLONE_NEWNET) == 0
