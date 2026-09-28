"""
MO NEXUS OMEGA — Text intelligence: keywords, meeting action items, proactive briefing.

These are heuristics over the text the caller supplies, and they say so. Action-item
extraction finds explicit commitments ("Action:", "TODO", "X will ...", "@x to ...");
it does not infer intent from tone, and it reports what it could not attribute.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

MAX_TEXT_CHARS = 200_000

STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers him his how
i if in into is it its just me more most my no nor not now of off on once only or other our out over own same she
should so some such than that the their them then there these they this those through to too under until up us very
was we were what when where which while who whom why will with would you your yours
""".split())

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]{1,}")


def _check_text(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"text exceeds {MAX_TEXT_CHARS} characters")
    return text


def extract_keywords(text: str, top_k: int = 10) -> dict[str, Any]:
    """Frequency keywords over unigrams and bigrams, stopwords removed. Bigrams need >=2 occurrences."""
    text = _check_text(text)
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    words = [w.lower().strip("'-") for w in _WORD.findall(text)]
    uni = Counter(w for w in words if w not in STOPWORDS and len(w) > 2)
    bi: Counter[str] = Counter()
    for a, b in zip(words, words[1:]):
        if a not in STOPWORDS and b not in STOPWORDS and len(a) > 2 and len(b) > 2:
            bi[f"{a} {b}"] += 1
    items = [(k, c) for k, c in uni.items()] + [(k, c) for k, c in bi.items() if c >= 2]
    # Bigrams weigh double: a repeated phrase is stronger evidence than one repeated word.
    ranked = sorted(items, key=lambda kv: (-(kv[1] * (2 if " " in kv[0] else 1)), kv[0]))[:top_k]
    return {"keywords": [{"term": k, "count": c, "kind": "phrase" if " " in k else "word"} for k, c in ranked],
            "words_analysed": len(words), "method": "frequency with stopword removal (not semantic)"}


_WEEKDAYS = {n: i for i, n in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
                                         "sunday"])}
_DUE = re.compile(r"\b(?:by|before|due|on)\s+(?:(?P<iso>\d{4}-\d{2}-\d{2})|(?P<rel>today|tomorrow|eod|"
                  r"(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)))", re.I)
_MARKER = re.compile(r"^\s*(?:[-*\d.)\s]*)(?:action(?:\s+item)?|todo|to-do|task)\s*[:\-]\s*(?P<body>.+)$", re.I)
_OWNER_AT = re.compile(r"@(?P<owner>[A-Za-z][\w.-]*)")
_OWNER_WILL = re.compile(r"^(?P<owner>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:will|to|should|needs to|must|is going to)\s+"
                         r"(?P<task>.+)$")


def _resolve_due(m: Optional[re.Match], today: date) -> tuple[Optional[str], Optional[str]]:
    if not m:
        return None, None
    if m.group("iso"):
        try:
            return date.fromisoformat(m.group("iso")).isoformat(), m.group(0)
        except ValueError:
            return None, m.group(0)
    rel = m.group("rel").lower()
    if rel in ("today", "eod"):
        return today.isoformat(), m.group(0)
    if rel == "tomorrow":
        return (today + timedelta(days=1)).isoformat(), m.group(0)
    target = _WEEKDAYS[rel.replace("next ", "")]
    delta = (target - today.weekday()) % 7 or 7          # the same weekday means a week from today
    return (today + timedelta(days=delta)).isoformat(), m.group(0)


def extract_action_items(text: str, *, today: Optional[date] = None) -> dict[str, Any]:
    """Explicit commitments only. `today` is injectable so relative dates are deterministic."""
    text = _check_text(text)
    today = today or date.today()
    items: list[dict[str, Any]] = []
    unattributed = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        body = None
        m = _MARKER.match(line)
        if m:
            body = m.group("body").strip()
        else:
            stripped = re.sub(r"^[-*\d.)\s]+", "", line)
            if _OWNER_WILL.match(stripped):
                body = stripped
        if body is None:
            continue
        owner = None
        mo = _OWNER_AT.search(body)
        if mo:
            owner = mo.group("owner")
        else:
            mw = _OWNER_WILL.match(body)
            if mw:
                owner = mw.group("owner")
        due, due_text = _resolve_due(_DUE.search(body), today)
        if owner is None:
            unattributed += 1
        items.append({"line": lineno, "task": body, "owner": owner, "due": due, "due_text": due_text})
    return {"action_items": items, "count": len(items), "without_owner": unattributed,
            "method": "explicit-pattern heuristics (Action:/TODO:/'Name will ...'/@owner); tone is not interpreted"}


# ── proactive briefing ──────────────────────────────────────────────────────

PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


def _parse_hhmm(value: str, name: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be HH:MM") from None


def in_quiet_hours(now: time, start: time, end: time) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end          # window wraps midnight


def build_briefing(items: list[dict[str, Any]], *, now: str, quiet_start: str = "22:00",
                   quiet_end: str = "07:00", max_items: int = 10) -> dict[str, Any]:
    """Order pending items and hold non-urgent ones during quiet hours.

    Urgent items always go out. Held items are returned, not dropped, so nothing is lost.
    """
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    if len(items) > 1000:
        raise ValueError("at most 1000 items")
    if not 1 <= max_items <= 100:
        raise ValueError("max_items must be between 1 and 100")
    now_t = _parse_hhmm(now, "now")
    quiet = in_quiet_hours(now_t, _parse_hhmm(quiet_start, "quiet_start"), _parse_hhmm(quiet_end, "quiet_end"))

    clean = []
    for i, it in enumerate(items):
        if not isinstance(it, dict) or not str(it.get("title", "")).strip():
            raise ValueError(f"items[{i}] needs a title")
        pr = str(it.get("priority", "normal")).lower()
        if pr not in PRIORITY_ORDER:
            raise ValueError(f"items[{i}].priority must be one of {sorted(PRIORITY_ORDER)}")
        clean.append({"title": str(it["title"]).strip(), "priority": pr, "due": it.get("due"),
                      "source": it.get("source")})
    clean.sort(key=lambda x: (PRIORITY_ORDER[x["priority"]], str(x["due"] or "9999"), x["title"]))

    deliver = [x for x in clean if not quiet or x["priority"] == "urgent"]
    held = [x for x in clean if quiet and x["priority"] != "urgent"]
    shown, overflow = deliver[:max_items], max(0, len(deliver) - max_items)
    if shown:
        lines = [f"{len(deliver)} item(s) need your attention:"] + \
                [f"{n}. [{x['priority']}] {x['title']}" + (f" (due {x['due']})" if x["due"] else "")
                 for n, x in enumerate(shown, 1)]
        if overflow:
            lines.append(f"...and {overflow} more.")
        spoken = " ".join(lines)
    else:
        spoken = "Nothing needs your attention right now." if not held else \
                 f"Quiet hours: {len(held)} non-urgent item(s) held until {quiet_end}."
    return {"quiet_hours_active": quiet, "deliver": shown, "overflow": overflow, "held": held,
            "text": spoken}
