"""The leaderboard: each player's best run, kept in a small JSON file.

Players are identified by a random id their browser generates and keeps (not by IP address:
housemates share one, phones change theirs, and the host's proxy hides it). Names are
optional and can be set after a run. Runs are recorded by the server when the game ends, so
scores cannot be forged by the client; runs that used dev tools are not recorded.

Storage: the directory named by `SPELLFORGE_DATA_DIR`, or else a writable volume mounted at
`/data` (on Hugging Face, a Storage Bucket). Without either, the leaderboard lives in memory
and resets when the server restarts.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FILE_NAME = "leaderboard.json"
MAX_NAME_LENGTH = 20
MAX_PLAYERS = 5000
TOP_SIZE = 10
MOUNTED_VOLUME = Path("/data")
"""Where a Hugging Face Storage Bucket is mounted; used automatically when present."""


class InvalidName(ValueError):
    pass


def clean_name(raw: str) -> str:
    """Collapse whitespace and check length and characters. Raises InvalidName."""
    name = " ".join(raw.split())
    if not name:
        raise InvalidName("the name is empty")
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidName(f"names can have at most {MAX_NAME_LENGTH} characters")
    if not name.isprintable():
        raise InvalidName("the name has characters that cannot be shown")
    return name


@dataclass
class Run:
    depth: int
    kills: int
    turns: int
    spells: list[str]
    """Names of the spells the player forged in this run."""
    finished_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    def sort_key(self) -> tuple[int, int, int, str]:
        """Deeper is better, then more kills, then fewer turns, then earlier."""
        return (-self.depth, -self.kills, self.turns, self.finished_at)


@dataclass
class Player:
    name: str | None = None
    runs: int = 0
    best: Run | None = None


class Leaderboard:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.path = data_dir / FILE_NAME if data_dir is not None else None
        self.players: dict[str, Player] = {}
        self._load()

    @classmethod
    def from_env(cls, mounted_volume: Path = MOUNTED_VOLUME) -> Leaderboard:
        """SPELLFORGE_DATA_DIR if set, else a volume mounted at /data, else memory only."""
        raw = os.environ.get("SPELLFORGE_DATA_DIR", "").strip()
        if raw:
            data_dir: Path | None = Path(raw)
        elif mounted_volume.is_dir() and os.access(mounted_volume, os.W_OK):
            data_dir = mounted_volume
        else:
            data_dir = None
            logger.warning("no data directory: the leaderboard resets when the server restarts")
        if data_dir is not None:
            logger.info("leaderboard saved in %s", data_dir / FILE_NAME)
        return cls(data_dir)

    # ---- updates -----------------------------------------------------------------

    def record(self, player_id: str, run: Run) -> bool:
        """Count a finished run; keep it if it is the player's best. Returns True if best."""
        player = self.players.get(player_id)
        if player is None:
            if len(self.players) >= MAX_PLAYERS:
                return False
            player = self.players[player_id] = Player()
        player.runs += 1
        improved = player.best is None or run.sort_key() < player.best.sort_key()
        if improved:
            player.best = run
        self._save()
        return improved

    def rename(self, player_id: str, raw_name: str) -> str:
        """Set the player's name (on all their runs). Raises InvalidName."""
        name = clean_name(raw_name)
        player = self.players.get(player_id)
        if player is None:
            if len(self.players) >= MAX_PLAYERS:
                raise InvalidName("the leaderboard is full")
            player = self.players[player_id] = Player()
        player.name = name
        self._save()
        return name

    def name_of(self, player_id: str) -> str | None:
        player = self.players.get(player_id)
        return player.name if player else None

    # ---- views ---------------------------------------------------------------------

    def ranking(self) -> list[tuple[str, Player]]:
        ranked = [(pid, p) for pid, p in self.players.items() if p.best is not None]
        ranked.sort(key=lambda item: item[1].best.sort_key())  # type: ignore[union-attr]
        return ranked

    def view(self, viewer_id: str | None, limit: int = TOP_SIZE) -> dict[str, Any]:
        """JSON-ready standings for one viewer: the top entries, and the viewer's own entry
        when it is not among them. Other players' ids are never included."""
        ranked = self.ranking()
        entries = [
            self._entry(rank, pid, player, viewer_id)
            for rank, (pid, player) in enumerate(ranked, start=1)
        ]
        you = next((entry for entry in entries if entry["is_you"]), None)
        return {
            "entries": entries[:limit],
            "you": you if you is not None and you["rank"] > limit else None,
            "players": len(ranked),
        }

    @staticmethod
    def _entry(rank: int, pid: str, player: Player, viewer_id: str | None) -> dict[str, Any]:
        assert player.best is not None
        return {
            "rank": rank,
            "name": player.name,
            "is_you": pid == viewer_id,
            "runs": player.runs,
            **asdict(player.best),
        }

    # ---- storage -------------------------------------------------------------------

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for pid, raw in data.get("players", {}).items():
                best = Run(**raw["best"]) if raw.get("best") else None
                self.players[pid] = Player(raw.get("name"), raw.get("runs", 0), best)
        except (OSError, ValueError, TypeError, KeyError):
            # Keep the unreadable file for inspection instead of overwriting it on next save.
            backup = self.path.with_suffix(".unreadable.json")
            logger.exception("could not read %s; kept a copy at %s", self.path, backup)
            try:
                shutil.copyfile(self.path, backup)
            except OSError:
                pass
            self.players = {}

    def _save(self) -> None:
        if self.path is None:
            return
        data = {
            "version": 1,
            "players": {
                pid: {
                    "name": p.name,
                    "runs": p.runs,
                    "best": asdict(p.best) if p.best else None,
                }
                for pid, p in self.players.items()
            },
        }
        text = json.dumps(data, ensure_ascii=False, indent=1)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(text, encoding="utf-8")
            try:
                os.replace(temporary, self.path)
            except OSError:
                # Some mounted volumes do not support rename: write in place instead.
                self.path.write_text(text, encoding="utf-8")
                temporary.unlink(missing_ok=True)
        except OSError:
            logger.exception("could not save the leaderboard to %s", self.path)
