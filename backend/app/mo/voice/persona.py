"""
MO NEXUS OMEGA — voice persona.

The register is a calm, precise, faintly dry assistant in the mould of the film character everyone means by "Jarvis":
formal without being stiff, brief, quietly confident, and never gushing. Concretely that means:

  * a chosen form of address (boss / sir / ma'am / a name / none), never assumed from anything about the user
  * greetings that know the time of day and, on a fresh wake, give a short status so the user starts informed
  * bad news delivered plainly and first ("I'm afraid ..."), never softened into something that sounds like success
  * a little dry wit, sparingly and only where it costs nothing in clarity

Everything here is text templates over facts computed elsewhere. The persona changes how MO SAYS things, not what it does
or what it is allowed to do, and it never claims a capability or a result the platform did not produce.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

PRESET_ADDRESSES = ("boss", "sir", "ma'am", "chief", "")
_CUSTOM = re.compile(r"^[A-Za-z][A-Za-z .'\-]{0,23}$")
DEFAULT_ADDRESS = "boss"
BRIEF_AFTER_IDLE_SECONDS = 30 * 60


def clean_address(value: Any) -> str:
    """Accept a preset or a plain name; anything else falls back to the default rather than reaching speech output."""
    if value is None:
        return DEFAULT_ADDRESS
    if not isinstance(value, str):
        return DEFAULT_ADDRESS
    v = value.strip()
    if v in PRESET_ADDRESSES:
        return v
    return v if _CUSTOM.match(v) else DEFAULT_ADDRESS


def clean_timezone(value: Any) -> str:
    if isinstance(value, str) and value and len(value) <= 64:
        try:
            ZoneInfo(value)
            return value
        except Exception:
            pass
    return "UTC"


@dataclass(frozen=True)
class Persona:
    address: str = DEFAULT_ADDRESS
    tz: str = "UTC"

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Persona":
        d = d or {}
        return cls(address=clean_address(d.get("address")), tz=clean_timezone(d.get("timezone")))

    @property
    def a(self) -> str:
        """', boss' — or nothing when the user chose no form of address."""
        return f", {self.address}" if self.address else ""

    def local(self, now_utc: datetime) -> datetime:
        aware = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
        return aware.astimezone(ZoneInfo(self.tz))

    def part_of_day(self, now_utc: datetime) -> str:
        h = self.local(now_utc).hour
        return "morning" if 5 <= h < 12 else "afternoon" if 12 <= h < 17 else "evening" if 17 <= h < 22 else "night"

    def salutation(self, now_utc: datetime) -> str:
        part = self.part_of_day(now_utc)
        return f"Good {'evening' if part == 'night' else part}{self.a}."

    def spoken_time(self, now_utc: datetime) -> str:
        t = self.local(now_utc)
        h12 = t.hour % 12 or 12
        core = f"{h12}:{t.minute:02d}" if t.minute else f"{h12} o'clock"
        ampm = "in the morning" if t.hour < 12 else "in the afternoon" if t.hour < 17 else "in the evening" if t.hour < 22 else "at night"
        return f"{core} {ampm}"

    def spoken_date(self, now_utc: datetime) -> str:
        t = self.local(now_utc)
        return t.strftime("%A, %B ") + str(t.day)


# ── phrase banks (deterministic variety via the turn number) ──────────────────

def _pick(options: tuple[str, ...], seed: int) -> str:
    return options[seed % len(options)]


def wake_short(p: Persona, seed: int) -> str:
    return _pick((f"Yes{p.a}?", f"At your service{p.a}.", f"I'm here{p.a}.", f"Go ahead{p.a}."), seed)


def acknowledge(p: Persona, seed: int) -> str:
    return _pick((f"Right away{p.a}.", f"As you wish{p.a}.", f"On it{p.a}.", f"Working on it{p.a}."), seed)


def did_not_catch(p: Persona, seed: int) -> str:
    return _pick((f"I'm afraid I didn't catch that{p.a}. Could you rephrase it?",
                  f"Forgive me{p.a}, I didn't follow. You can say help for examples.",
                  f"I'm not sure what you'd like me to do there{p.a}. Try it another way?"), seed)


def goodbye(p: Persona, seed: int) -> str:
    return _pick((f"Very well{p.a}. Just say my name when you need me.", f"Standing by{p.a}.",
                  f"Understood{p.a}. I'll be here."), seed)


def cancelled(p: Persona, seed: int) -> str:
    return _pick((f"Very well{p.a}, disregarded.", f"Consider it dropped{p.a}.", f"Understood{p.a}. Setting that aside."), seed)


def thanks(p: Persona, seed: int) -> str:
    return _pick((f"You're welcome{p.a}.", f"Happy to help{p.a}.", f"Of course{p.a}.", f"Any time{p.a}."), seed)


def sorry_bad_news(p: Persona, detail: str) -> str:
    """Bad news first and plainly. `detail` is a fact from the platform, never softened."""
    d = detail.strip().rstrip(".")
    return f"I'm afraid {d[:1].lower() + d[1:]}{p.a}." if d else f"I'm afraid that didn't work{p.a}."


def offer(p: Persona, what: str) -> str:
    return f"Shall I {what}{p.a}?"


def declined(p: Persona, seed: int) -> str:
    return _pick((f"Very well{p.a}.", f"As you prefer{p.a}.", f"Understood{p.a}."), seed)


def identity(p: Persona) -> str:
    return (f"I'm MO, the assistant for this platform{p.a}. You can call me Jarvis if you like. I'm software, so I can build and "
            "manage projects, check on systems, run analyses and answer questions, but I only report what the platform actually did. "
            "Say help for examples.")


def status_line(p: Persona, *, failed: int, pending: int, safe_mode: bool, audit_valid: bool, running: int = 0) -> str:
    """One honest sentence about how things stand. Only claims 'nominal' when every input says so."""
    if not audit_valid:
        return f"Warning{p.a}: the audit trail failed verification."
    issues = []
    if safe_mode:
        issues.append("safe mode is on, so writes are suspended")
    if failed:
        issues.append(f"{_n(failed)} build{'s have' if failed != 1 else ' has'} failed")
    if pending:
        issues.append(f"{_n(pending)} approval{'s are' if pending != 1 else ' is'} waiting on you")
    if running:
        issues.append(f"{_n(running)} run{'s are' if running != 1 else ' is'} in progress")
    if not issues:
        return "All systems are running normally. Nothing needs your attention."
    joined = issues[0] if len(issues) == 1 else ", ".join(issues[:-1]) + " and " + issues[-1]
    return "Systems are up. " + joined[:1].upper() + joined[1:] + "."


def _n(n: int) -> str:
    words = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
    return words[n] if 0 <= n < len(words) else str(n)


def late_night_note(p: Persona, now_utc: datetime) -> str:
    return f" It's rather late{p.a}." if p.part_of_day(now_utc) == "night" and 0 <= p.local(now_utc).hour < 5 else ""
