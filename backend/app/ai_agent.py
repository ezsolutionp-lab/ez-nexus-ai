"""
EZ-NEXUS AI — AI Agent
Provides call transcript summarization, urgency triage, sentiment analysis,
and action-item extraction. Works without an external LLM by applying robust
keyword/heuristic rules; optionally enhances results with OpenAI GPT when an
API key is configured.
"""

from __future__ import annotations

import os
import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ── Keyword sets for heuristic analysis ────────────────────────────────────

_URGENT_KEYWORDS = {
    "urgent", "emergency", "immediately", "asap", "critical", "crisis",
    "broken", "not working", "shut down", "down", "failure", "fail",
    "deadline", "today", "right now", "fire", "help", "sos",
}

_POSITIVE_KEYWORDS = {
    "great", "excellent", "amazing", "happy", "pleased", "satisfied",
    "fantastic", "good", "wonderful", "love", "appreciate", "thank",
    "perfect", "awesome", "helpful", "impressed",
}

_NEGATIVE_KEYWORDS = {
    "unhappy", "frustrated", "angry", "annoyed", "terrible", "horrible",
    "worst", "bad", "disappointed", "disgusted", "upset", "complaint",
    "refund", "cancel", "waste", "useless", "hate", "never again",
}

_ACTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bwill\s+(?:call|send|email|follow[- ]?up|schedule|book|check|update|fix|review)\b", re.I),
    re.compile(r"\bneeds?\s+to\s+\w+", re.I),
    re.compile(r"\bplease\s+\w+", re.I),
    re.compile(r"\bfollow[- ]?up\b", re.I),
    re.compile(r"\bschedule\s+(?:a|an)?\s*(?:meeting|call|appointment|demo)\b", re.I),
    re.compile(r"\bsend\s+(?:a|an|the)?\s*(?:email|proposal|quote|invoice|document|report)\b", re.I),
    re.compile(r"\bcall\s+(?:back|them|us|me)\b", re.I),
    re.compile(r"\bconfirm\s+\w+", re.I),
]


# ── Core analysis functions ─────────────────────────────────────────────────

def _triage(text: str) -> str:
    """Return 'urgent', 'normal', or 'low' based on keyword density."""
    lower = text.lower()
    tokens = set(re.findall(r"\b\w+\b", lower))
    urgent_hits = len(tokens & _URGENT_KEYWORDS)

    if urgent_hits >= 2 or any(p in lower for p in ("asap", "right now", "help me now")):
        return "urgent"
    if urgent_hits == 1:
        return "normal"
    return "low"


def _sentiment(text: str) -> str:
    """Return 'positive', 'neutral', or 'negative'."""
    lower = text.lower()
    tokens = set(re.findall(r"\b\w+\b", lower))
    pos = len(tokens & _POSITIVE_KEYWORDS)
    neg = len(tokens & _NEGATIVE_KEYWORDS)

    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"


def _extract_action_items(text: str) -> List[str]:
    """Extract sentences containing action-item signals."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    actions: List[str] = []
    for sentence in sentences:
        for pattern in _ACTION_PATTERNS:
            if pattern.search(sentence):
                cleaned = sentence.strip()
                if cleaned and cleaned not in actions:
                    actions.append(cleaned)
                break
    return actions[:10]  # Cap at 10


def _summarize_heuristic(transcript: str) -> str:
    """
    Build a human-readable summary from the transcript using sentence selection.
    Picks the first 2 and last 2 sentences, plus any sentence with action signals.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript.strip()) if s.strip()]

    if not sentences:
        return "No transcript content to summarize."
    if len(sentences) <= 4:
        return " ".join(sentences)

    selected = []
    # Opening context
    selected.extend(sentences[:2])
    # Action-heavy sentences (middle)
    for s in sentences[2:-2]:
        for pat in _ACTION_PATTERNS:
            if pat.search(s) and s not in selected:
                selected.append(s)
                break
    # Closing context
    for s in sentences[-2:]:
        if s not in selected:
            selected.append(s)

    return " ".join(selected)


# ── Claude AI integration ──────────────────────────────────────────────────

def _try_claude_analysis(transcript: str) -> dict | None:
    """Attempt Claude-powered analysis. Returns dict or None on failure."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
        import json

        client = anthropic.Anthropic(api_key=api_key)

        prompt = (
            "Analyze the following call transcript and respond with ONLY a JSON object "
            "(no markdown, no extra text) containing exactly these keys:\n"
            '  "summary": one-paragraph plain-English summary,\n'
            '  "triage": one of "urgent" | "normal" | "low",\n'
            '  "action_items": array of action-item strings (max 10),\n'
            '  "sentiment": one of "positive" | "neutral" | "negative"\n\n'
            f"Transcript:\n\n{transcript[:8000]}"
        )

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\n?", "", content)
            content = re.sub(r"\n?```$", "", content.strip())

        data = json.loads(content)
        return {
            "summary": data.get("summary", ""),
            "triage": data.get("triage", "normal"),
            "action_items": data.get("action_items", []),
            "sentiment": data.get("sentiment", "neutral"),
        }
    except Exception as exc:
        logger.warning("Claude analysis failed, falling back: %s", exc)
        return None


# ── Optional OpenAI fallback ───────────────────────────────────────────────

def _try_openai_analysis(transcript: str) -> dict | None:
    """
    Attempt GPT-powered analysis.  Returns a dict with keys
    {summary, triage, action_items, sentiment} or None on failure.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        import openai  # optional dep — only imported if key is present
        client = openai.OpenAI(api_key=api_key)

        system_prompt = (
            "You are an AI assistant for EZ-NEXUS AI, a business operations platform. "
            "Analyze the provided call transcript and respond with ONLY a JSON object "
            "(no markdown) containing:\n"
            '  "summary": one-paragraph plain-English summary,\n'
            '  "triage": one of "urgent" | "normal" | "low",\n'
            '  "action_items": array of action-item strings,\n'
            '  "sentiment": one of "positive" | "neutral" | "negative"'
        )

        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Transcript:\n\n{transcript[:6000]}"},
            ],
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        import json
        data = json.loads(resp.choices[0].message.content)
        # Normalise / fill any missing keys
        return {
            "summary": data.get("summary", ""),
            "triage": data.get("triage", "normal"),
            "action_items": data.get("action_items", []),
            "sentiment": data.get("sentiment", "neutral"),
        }

    except Exception as exc:
        logger.warning("OpenAI analysis failed, falling back to heuristics: %s", exc)
        return None


# ── Public interface ────────────────────────────────────────────────────────

def analyze_transcript(transcript: str) -> dict:
    """
    Full analysis pipeline.  Returns dict with:
        summary (str), triage (str), action_items (list[str]), sentiment (str)

    Tries OpenAI first; falls back to heuristics when no API key is set or
    when the OpenAI call fails.
    """
    if not transcript or not transcript.strip():
        return {
            "summary": "Empty transcript provided.",
            "triage": "low",
            "action_items": [],
            "sentiment": "neutral",
        }

    # Try Claude first
    claude_result = _try_claude_analysis(transcript)
    if claude_result:
        logger.info("Transcript analysed with Claude AI")
        return claude_result

    # Try OpenAI fallback
    openai_result = _try_openai_analysis(transcript)
    if openai_result:
        logger.info("Transcript analysed with OpenAI GPT")
        return openai_result

    # Heuristic fallback
    logger.info("Transcript analysed with heuristics (no API key)")
    return {
        "summary": _summarize_heuristic(transcript),
        "triage": _triage(transcript),
        "action_items": _extract_action_items(transcript),
        "sentiment": _sentiment(transcript),
    }
