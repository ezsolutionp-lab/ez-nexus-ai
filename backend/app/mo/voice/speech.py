"""
MO NEXUS OMEGA — Conversational reply composer.

What makes MO sound like a person rather than a status endpoint:

  * Replies are written to be *heard*, not read: no markdown, no symbols, no
    hex identifiers, no raw state enums. "APPROVAL_REQUIRED" becomes "that needs
    sign-off first".
  * Phrasing varies between turns, so the same action does not produce the same
    sentence every time. Variety is seeded by the turn number, which keeps it
    deterministic and therefore testable.
  * A reply acknowledges, reports what actually happened, and — when there is an
    obvious next step — offers it, the way a colleague would.
  * Bad news is delivered plainly. A blocked action is never softened into
    something that sounds like it worked.

When a model provider is configured the engine may ask it to rephrase a reply
more naturally, but the facts always come from here; the model only restyles.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional


def pick(options: tuple[str, ...], seed: int) -> str:
    """Deterministic variety: same seed, same choice; next turn, next phrasing."""
    return options[seed % len(options)] if options else ""


def number_words(n: int) -> str:
    """Speak small counts as words; larger ones stay numeric (TTS reads them fine)."""
    words = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
             "nine", "ten", "eleven", "twelve")
    return words[n] if 0 <= n < len(words) else str(n)


def plural(n: int, singular: str, plural_form: Optional[str] = None) -> str:
    return f"{number_words(n)} {singular if n == 1 else (plural_form or singular + 's')}"


def spoken_list(items: Iterable[str], *, limit: int = 4, conjunction: str = "and") -> str:
    """'a, b and c' — and '… and 3 more' past the limit, so a list is never read endlessly."""
    items = [i for i in items if i]
    if not items:
        return ""
    shown, rest = items[:limit], len(items) - limit
    if rest > 0:
        return ", ".join(shown) + f", {conjunction} {number_words(rest)} more"
    if len(shown) == 1:
        return shown[0]
    return ", ".join(shown[:-1]) + f" {conjunction} {shown[-1]}"


_ID_PATTERN = re.compile(r"\b[0-9a-f]{12,}\b")
_ENUM_PATTERN = re.compile(r"\b[A-Z]{2,}(?:_[A-Z]+)+\b")


_STATE_PHRASES = {
    "APPROVAL_REQUIRED": "that needs sign-off first",
    "PENDING_APPROVAL": "that's waiting on sign-off",
    "CREDENTIAL_REQUIRED": "that needs a credential that isn't set up yet",
    "POLICY_DENIED": "that isn't allowed",
    "RATE_LIMITED": "we're being rate limited",
    "BUILD_FAILED": "the build failed",
    "TEST_FAILED": "the tests failed",
    "SECURITY_FAILED": "the security checks failed",
    "PROVIDER_UNAVAILABLE": "the provider is unavailable right now",
}


def speakable(text: str) -> str:
    """
    Strip what a speech synthesiser would read badly or pointlessly aloud.

    Removes markdown, long hex identifiers and backticks, and turns state enums
    into words. Idempotent.
    """
    if not text:
        return ""
    # Enums first: the markdown pass below strips underscores, and an enum with
    # its underscores removed ("APPROVALREQUIRED") no longer matches anything.
    out = _ENUM_PATTERN.sub(
        lambda m: _STATE_PHRASES.get(m.group(), m.group().replace("_", " ").lower()), text)
    out = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", out)          # markdown links -> label
    out = re.sub(r"[`*_#>]+", "", out)
    out = _ID_PATTERN.sub("", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"\s+([,.!?])", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip()


# ── Phrase banks ─────────────────────────────────────────────────────────────

GREETINGS = (
    "Yes? I'm listening.",
    "I'm here. What do you need?",
    "Go ahead, I'm listening.",
    "Hi. What can I do for you?",
)

ACKNOWLEDGE_WORK = (
    "On it.",
    "Sure, working on that now.",
    "Okay, give me a moment.",
    "Right away.",
)

DID_NOT_CATCH = (
    "Sorry, I didn't catch that. Could you say it another way?",
    "I'm not sure what you'd like me to do there. Try rephrasing it?",
    "I didn't understand that one. You can say help for some examples.",
)

GOODBYES = (
    "Okay. Just say my name when you need me.",
    "No problem. I'll be here.",
    "Alright, standing by.",
)

CANCELLED = (
    "Okay, never mind.",
    "No problem, I've dropped that.",
    "Sure, forget it.",
)


def greeting(seed: int) -> str:
    return pick(GREETINGS, seed)


def acknowledge(seed: int) -> str:
    return pick(ACKNOWLEDGE_WORK, seed)


def did_not_catch(seed: int) -> str:
    return pick(DID_NOT_CATCH, seed)


def goodbye(seed: int) -> str:
    return pick(GOODBYES, seed)


def cancelled(seed: int) -> str:
    return pick(CANCELLED, seed)


def ask_for_slot(slot: str, intent_summary: str) -> str:
    """A natural follow-up question for a missing piece of information."""
    questions = {
        "description": "Sure. What would you like me to build? Tell me what it's for "
                       "and the main things it should do.",
        "environment": "Which environment, staging or production?",
        "project": "Which project do you mean?",
        "agent": "Which agent?",
        "approval_id": "Which approval?",
        "count": "How many would you like?",
    }
    return questions.get(slot, f"I need a bit more detail to {intent_summary.lower().rstrip('.')}.")


def refusal(reason: str) -> str:
    """Deliver a refusal plainly, without apologising it into ambiguity."""
    return speakable(f"I can't do that by voice. {reason}")


def blocked(detail: str) -> str:
    return speakable(detail)


def sentence_case(text: str) -> str:
    """Capitalise the first letter only. A lowercase opening reads flat in TTS."""
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def join(*parts: Optional[str]) -> str:
    return speakable(" ".join(sentence_case(p) for p in parts if p and p.strip()))


def duration(seconds: float) -> str:
    """Speak a duration naturally: 'one second', 'about 40 seconds', 'about 3 minutes'."""
    seconds = max(0, round(seconds))
    if seconds < 90:
        return plural(seconds, "second")
    return plural(round(seconds / 60), "minute")
