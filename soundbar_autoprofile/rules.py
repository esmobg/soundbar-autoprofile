"""Pick a profile from the current activity, and avoid flapping between profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

from .detect import Activity

_FIELDS = set(Activity.__dataclass_fields__)


@dataclass
class Rule:
    profile: str
    when: dict[str, Any] = field(default_factory=dict)
    unless: dict[str, Any] = field(default_factory=dict)
    name: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Rule:
        if "profile" not in d:
            raise ValueError(f"rule without a profile: {d}")
        for key in ("when", "unless"):
            bad = set(d.get(key) or {}) - _FIELDS
            if bad:
                raise ValueError(f"rule {d.get('name') or d['profile']!r}: unknown condition(s) "
                                 f"{', '.join(sorted(bad))}; valid: {', '.join(sorted(_FIELDS))}")
        return cls(profile=d["profile"], when=dict(d.get("when") or {}), unless=dict(d.get("unless") or {}),
                   name=d.get("name", ""))

    def matches(self, a: Activity) -> bool:
        if not self.when:
            return False
        if not all(_cond(getattr(a, k), v) for k, v in self.when.items()):
            return False
        return not (self.unless and any(_cond(getattr(a, k), v) for k, v in self.unless.items()))

    def label(self) -> str:
        return self.name or f"-> {self.profile}"


def _cond(actual: Any, expected: Any) -> bool:
    """bool: equality. str: case-insensitive regex search. list of str: any pattern matches."""
    if isinstance(expected, bool):
        return bool(actual) is expected
    patterns = expected if isinstance(expected, list) else [expected]
    values = actual if isinstance(actual, list) else [actual]
    return any(re.search(str(p), str(v), re.IGNORECASE) for p in patterns for v in values if v)


def choose(a: Activity, rules: list[Rule], default: str) -> tuple[str, str]:
    """First matching rule wins. Returns (profile, reason)."""
    for r in rules:
        if r.matches(a):
            return r.profile, r.label()
    return default, "no rule matched"


@dataclass
class Decision:
    candidate: str
    reason: str
    switch_to: str | None   # set when the profile should be applied now


class Engine:
    """Turns a stream of activities into profile switches.

    * ``hold``: a new profile must be chosen for this many seconds before switching (no flapping when you
      alt-tab for a second).
    * ``media_grace``: after media stops, it still counts as playing for this many seconds (pausing a song
      or skipping a track does not switch away).
    """

    def __init__(self, rules: list[Rule], default: str, hold: float = 3.0, media_grace: float = 15.0):
        self.rules, self.default, self.hold, self.media_grace = rules, default, hold, media_grace
        self.current: str | None = None
        self._pending: str | None = None
        self._pending_since = 0.0
        self._last_media: Activity | None = None
        self._last_media_at = float("-inf")

    def _with_grace(self, a: Activity, now: float) -> Activity:
        if a.media_playing:
            self._last_media, self._last_media_at = a, now
            return a
        if self._last_media is not None and now - self._last_media_at <= self.media_grace:
            m = self._last_media
            return replace(a, media_playing=True, media_app=m.media_app, media_title=m.media_title,
                           media_artist=m.media_artist, media_type=m.media_type)
        return a

    def step(self, a: Activity, now: float) -> Decision:
        profile, reason = choose(self._with_grace(a, now), self.rules, self.default)
        if self.current is None:                     # first decision: apply right away
            self.current = profile
            return Decision(profile, reason, profile)
        if profile == self.current:
            self._pending = None
            return Decision(profile, reason, None)
        if profile != self._pending:
            self._pending, self._pending_since = profile, now
        if now - self._pending_since >= self.hold:
            self.current, self._pending = profile, None
            return Decision(profile, reason, profile)
        return Decision(profile, reason, None)

    def force(self, profile: str | None) -> None:
        """Forget the applied profile (e.g. after the device reconnects) so the next step re-applies it."""
        self.current = profile
        self._pending = None
