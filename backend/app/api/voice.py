"""
MO NEXUS OMEGA — Conversational voice API (the JARVIS console's backend).

    POST /api/mo/voice/sessions                 start a conversation
    POST /api/mo/voice/sessions/{id}/turns      send what the user said, get MO's reply
    GET  /api/mo/voice/sessions/{id}            the conversation transcript
    POST /api/mo/voice/sessions/{id}/end        end it
    GET  /api/mo/voice/capabilities             what voice can and cannot do, truthfully
    GET  /api/mo/voice/commands                 things you can say

Recognition and synthesis run in the browser; this API receives transcripts and
returns text plus a `speak` directive. Raw microphone audio never reaches it.

The older stateless endpoint, POST /api/mo/voice/command, is unchanged and still
served from mo_core.py — it is a published interface with its own callers.

Every route is authenticated by construction through mo_router(), and every
utterance is evaluated under the caller's own RequestContext with the channel
stamped VOICE — voice never has more authority than the token behind it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..mo.context import RequestContext
from ..mo.db import VoiceSession, VoiceTurn
from ..mo.errors import HTTP_STATUS_FOR_STATE, MoError
from ..mo.security.zero_trust import mo_router, resolve_context
from ..mo.voice import persona as personas
from ..mo.voice.engine import VoiceEngine
from ..mo.voice.intents import help_examples
from ..mo.voice.providers import WakeWordConfig, get_voice_router

WORKSPACE_ROOT = Path(os.getenv("MO_BUILDER_WORKSPACE", "./mo_workspaces")).resolve()

# A live conversation sends one request per utterance (ambient speech included), so
# turns sit on the write bucket. The expensive part, sandboxed builds, is throttled
# separately inside the engine on the strict "build" bucket.
router = mo_router("/api/mo/voice", ["mo-voice-conversation"], bucket="write")
read_router = mo_router("/api/mo/voice", ["mo-voice-conversation"], bucket="read")

MAX_TRANSCRIPT_CHARS = 2000


def _engine(db: Session, ctx: RequestContext) -> VoiceEngine:
    return VoiceEngine(db, ctx, workspace_root=WORKSPACE_ROOT)


def _http(exc: MoError) -> HTTPException:
    # A session in another tenant reads as not-found: never confirm it exists.
    status = 404 if exc.state.value == "POLICY_DENIED" and "another tenant" in exc.detail \
        else HTTP_STATUS_FOR_STATE.get(exc.state, 400)
    return HTTPException(status_code=status,
                         detail={"state": exc.state.value, "detail": exc.detail})


@read_router.get("/capabilities")
def voice_capabilities() -> dict[str, Any]:
    """The truthful capability matrix, including what is missing and why."""
    return get_voice_router().capabilities()


@read_router.get("/commands")
def voice_commands() -> dict[str, Any]:
    wake = WakeWordConfig()
    return {
        "wake_phrases": list(wake.phrases),
        "follow_up_window_seconds": wake.follow_up_window_seconds,
        "examples": help_examples(),
    }


@router.post("/sessions", status_code=201)
def start_session(
    payload: dict = Body(default={}),
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ctx.require_scope("builder:read")
    engine = _engine(db, ctx)
    session = engine.start_session(language=str(payload.get("language", "en-US"))[:16],
                                   address=payload.get("address"), timezone=payload.get("timezone"))
    db.commit()
    wake = WakeWordConfig()
    persona = json.loads(session.persona_json or "{}")
    return {
        "session_id": session.id,
        "language": session.language,
        "persona": {"address": persona.get("address"), "timezone": persona.get("timezone"),
                    "address_presets": [a for a in personas.PRESET_ADDRESSES]},
        "wake_phrases": list(wake.phrases),
        "follow_up_window_seconds": wake.follow_up_window_seconds,
        "wake_word_mode": wake.mode,
    }


@router.post("/sessions/{session_id}/turns")
def send_turn(
    session_id: str,
    payload: dict = Body(...),
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """One utterance in, one spoken reply out."""
    transcript = payload.get("transcript")
    if not isinstance(transcript, str):
        raise HTTPException(status_code=422, detail="transcript must be a string.")
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        raise HTTPException(status_code=413,
                            detail=f"transcript exceeds {MAX_TRANSCRIPT_CHARS} characters.")
    engine = _engine(db, ctx)
    try:
        session = engine.load_session(session_id)
        result = engine.handle(session, transcript)
    except MoError as exc:
        db.rollback()
        raise _http(exc) from exc
    db.commit()
    return result


@read_router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    session = db.get(VoiceSession, session_id)
    if session is None or session.tenant_id != ctx.tenant_id or session.actor_id != ctx.actor_id:
        raise HTTPException(status_code=404, detail="Voice session not found.")
    turns = (db.query(VoiceTurn).filter(VoiceTurn.session_id == session.id)
             .order_by(VoiceTurn.seq.asc()).all())
    return {
        "session_id": session.id, "status": session.status, "language": session.language,
        "turn_count": session.turn_count,
        "awake_until": session.awake_until.isoformat() + "Z" if session.awake_until else None,
        "turns": [
            {"seq": t.seq, "you": t.transcript, "mo": t.reply, "intent": t.intent,
             "confidence": t.confidence, "slots": json.loads(t.slots_json or "{}"),
             "state": t.result_state, "wake_detected": t.wake_detected,
             "latency_ms": t.latency_ms}
            for t in turns
        ],
    }


@router.post("/sessions/{session_id}/end")
def end_session(
    session_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    engine = _engine(db, ctx)
    try:
        session = engine.load_session(session_id)
    except MoError as exc:
        raise _http(exc) from exc
    engine.end_session(session)
    db.commit()
    return {"session_id": session.id, "status": session.status,
            "turn_count": session.turn_count}


@router.post("/transcribe")
def transcribe_audio(payload: dict[str, Any] = Body(...), ctx: RequestContext = Depends(resolve_context)):
    """Server-side transcription of one uploaded clip (base64). Needs a configured provider; audio is not stored."""
    import base64
    import binascii
    from fastapi.responses import JSONResponse
    from fastapi.encoders import jsonable_encoder
    try:
        ctx.require_scope("builder:write")
        raw = base64.b64decode(str(payload.get("audio_b64", "")), validate=True)
    except MoError as exc:
        raise _http(exc)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="audio_b64 is not valid base64.")
    language = str(payload.get("language", "en-US"))[:12]
    res = get_voice_router().transcribe(raw, language=language)
    status = 200 if res.state.is_success else HTTP_STATUS_FOR_STATE.get(res.state, 422)
    return JSONResponse(status_code=status, content=jsonable_encoder(res.to_dict()))


@router.post("/synthesize")
def synthesize_speech(payload: dict[str, Any] = Body(...), ctx: RequestContext = Depends(resolve_context)):
    """Server-side speech synthesis. Needs a configured provider; the browser console speaks locally without one."""
    from fastapi.responses import JSONResponse
    from fastapi.encoders import jsonable_encoder
    try:
        ctx.require_scope("builder:write")
    except MoError as exc:
        raise _http(exc)
    res = get_voice_router().synthesize_audio(str(payload.get("text", "")), voice=str(payload.get("voice", "default"))[:64],
                                        language=str(payload.get("language", "en-US"))[:12])
    status = 200 if res.state.is_success else HTTP_STATUS_FOR_STATE.get(res.state, 422)
    return JSONResponse(status_code=status, content=jsonable_encoder(res.to_dict()))


ALL_ROUTERS = [read_router, router]
