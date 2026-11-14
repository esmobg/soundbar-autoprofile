"""Pick a profile from the current activity, and avoid flapping between profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

from .detect import Activity

_FIELDS = set(Activity.__dataclass_fields__)
# true/false conditions; every other field is text (or a list of text, like mic_apps)
_BOOL_FIELDS = {k for k, f in Activity.__dataclass_fields__.items() if isinstance(f.default, bool)}

# A compiled condition: a bool to compare with, or the case-insensitive patterns of which any must match.
Condition = bool | tuple[re.Pattern[str], ...]


@dataclass
class Rule:
    """``when``: every condition must hold. ``unless``: any condition that holds excludes the rule.

    Conditions are validated and their regular expressions compiled when the rule is created, so a config mistake
    fails at load time (``gs5 config check``) instead of in the daemon.

    * true/false fields (``media_playing``, ``fullscreen``, ``mic_in_use``) need a real YAML boolean.
    * text fields take a pattern or a non-empty list of patterns (any of them may match). Patterns are
      case-insensitive regular expressions searched in the value. The value is matched even when it is empty, so
      ``"^$"`` means "empty" (e.g. ``media_type: "^$"``: the player does not say). A list value such as ``mic_apps``
      matches when any item matches; an empty list is matched as one empty value.
    """

    profile: str
    when: dict[str, Any] = field(default_factory=dict)
    unless: dict[str, Any] = field(default_factory=dict)
    name: str = ""

    def __post_init__(self) -> None:
        self._when = self._compile("when", self.when)
        self._unless = self._compile("unless", self.unless)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Rule:
        if not isinstance(d, dict):
            raise ValueError(f"a rule must be a mapping with profile/when/unless, got {d!r}")
        if "profile" not in d:
            raise ValueError(f"rule without a profile: {d}")
        label = d.get("name") or d["profile"]
        if not isinstance(d["profile"], str) or not d["profile"]:
            raise ValueError(f"rule {label!r}: profile must be a profile name, got {d['profile']!r}")
        if not isinstance(d.get("name", ""), str):
            raise ValueError(f"rule {label!r}: name must be text, got {d['name']!r}")
        unknown = set(d) - {"profile", "when", "unless", "name"}
        if unknown:
            raise ValueError(f"rule {label!r}: unknown key(s) {', '.join(sorted(map(str, unknown)))}; "
                             "valid: name, profile, when, unless")
        for key in ("when", "unless"):
            value = d.get(key)
            if value is not None and not isinstance(value, dict):
                raise ValueError(f"rule {label!r}: {key} must be a mapping of conditions, got {value!r}")
        if not d.get("when"):
            raise ValueError(f"rule {label!r} has no 'when' conditions, so it can never match")
        return cls(profile=d["profile"], when=dict(d["when"]), unless=dict(d.get("unless") or {}),
                   name=d.get("name") or "")

    def _compile(self, section: str, conds: dict[str, Any]) -> dict[str, Condition]:
        label = self.name or self.profile
        bad = set(conds) - _FIELDS
        if bad:
            raise ValueError(f"rule {label!r}: unknown condition(s) {', '.join(sorted(map(str, bad)))}; "
                             f"valid: {', '.join(sorted(_FIELDS))}")
        out: dict[str, Condition] = {}
        for key, value in conds.items():
            where = f"rule {label!r}, {section}.{key}"
            if key in _BOOL_FIELDS:
                if not isinstance(value, bool):
                    raise ValueError(f"{where}: needs true or false, got {value!r}")
                out[key] = value
                continue
            patterns = value if isinstance(value, list) else [value]
            if not patterns or not all(isinstance(p, str) for p in patterns):
                raise ValueError(f"{where}: needs a text pattern or a non-empty list of them, got {value!r} "
                                 "(quote values YAML would read otherwise, e.g. \"no\", \"on\", \"2048\")")
            compiled = []
            for p in patterns:
                try:
                    compiled.append(re.compile(p, re.IGNORECASE))
                except re.error as e:
                    raise ValueError(f"{where}: invalid regular expression {p!r}: {e}") from None
            out[key] = tuple(compiled)
        return out

    def matches(self, a: Activity) -> bool:
        if not self._when:
            return False
        if not all(_cond(getattr(a, k), v) for k, v in self._when.items()):
            return False
        return not any(_cond(getattr(a, k), v) for k, v in self._unless.items())

    def label(self) -> str:
        return self.name or f"-> {self.profile}"


def _cond(actual: Any, expected: Condition) -> bool:
    """bool: equality. Patterns: any pattern found in the value (or in any item of a list value)."""
    if isinstance(expected, bool):
        return bool(actual) is expected
    values = actual if isinstance(actual, list) else [actual]
    texts = ["" if v is None else str(v) for v in values] or [""]
    return any(p.search(t) for p in expected for t in texts)


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
