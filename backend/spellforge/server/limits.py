"""Guards for a public deployment that spends the owner's Anthropic credit.

- `AccessGate`: an invite code checked before a websocket connection gets a game.
- `SpendingCap`: a daily budget in USD shared by every player's forge and Dungeon Master.
- `SessionSlots`: a cap on concurrent players (each game runs its own plugin processes).

All are configured from the environment (see `docs/deploy.md`) and off when unset, so local
development works exactly as before.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

MAX_UNLOCK_ATTEMPTS = 5
"""Wrong codes allowed per connection before it is closed (each also costs a 1s delay)."""
FORGE_COST_ESTIMATE_USD = 0.15
"""Reserved when a forge or Dungeon Master run starts; replaced by the real cost at the end."""


class AccessGate:
    def __init__(self, code: str | None) -> None:
        self._code = (code or "").strip()

    @classmethod
    def from_env(cls) -> AccessGate:
        return cls(os.environ.get("SPELLFORGE_ACCESS_CODE"))

    @property
    def required(self) -> bool:
        return bool(self._code)

    def check(self, attempt: str) -> bool:
        if not self.required:
            return True
        # Constant-time comparison, so response timing leaks nothing about the code.
        return hmac.compare_digest(attempt.strip().encode(), self._code.encode())


@dataclass
class Reservation:
    day: date
    amount: float


class SpendingCap:
    """A daily USD budget (UTC days). In memory: a server restart starts the day afresh, so
    also set a spend limit in the Anthropic console as the hard backstop."""

    def __init__(
        self,
        daily_usd: float | None,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self.daily_usd = daily_usd
        self._today = today
        self._day = today()
        self._spent = 0.0

    @classmethod
    def from_env(cls) -> SpendingCap:
        raw = os.environ.get("SPELLFORGE_DAILY_BUDGET_USD", "").strip()
        return cls(float(raw) if raw else None)

    @property
    def spent_today(self) -> float:
        self._roll()
        return self._spent

    def available(self) -> bool:
        return self.daily_usd is None or self.spent_today < self.daily_usd

    def reserve(self, estimate: float = FORGE_COST_ESTIMATE_USD) -> Reservation | None:
        """Hold an estimate before an agent run; None if today's budget is used up."""
        if not self.available():
            return None
        self._spent += estimate
        return Reservation(self._day, estimate)

    def settle(self, reservation: Reservation, actual: float | None) -> None:
        """Swap the estimate for the real cost. `None` (unknown, e.g. cancelled) keeps it."""
        self._roll()
        if actual is None or reservation.day != self._day:
            return
        self._spent += actual - reservation.amount
        reservation.amount = actual

    def _roll(self) -> None:
        today = self._today()
        if today != self._day:
            self._day, self._spent = today, 0.0


class SessionSlots:
    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.active = 0

    @classmethod
    def from_env(cls) -> SessionSlots:
        raw = os.environ.get("SPELLFORGE_MAX_SESSIONS", "").strip()
        return cls(int(raw) if raw else None)

    def acquire(self) -> bool:
        if self.limit is not None and self.active >= self.limit:
            return False
        self.active += 1
        return True

    def release(self) -> None:
        self.active = max(0, self.active - 1)
