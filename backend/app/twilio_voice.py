"""
EZ-NEXUS AI — Twilio Inbound Call Handler
AI answers the phone, collects caller info, and books appointments automatically.

Call flow:
  1. Caller dials Twilio number
  2. Twilio POSTs to /twilio/inbound
  3. AI greets caller, gathers: name, service needed, preferred date/time
  4. AI books appointment in DB
  5. SMS + email confirmations sent
  6. Staff notified for approval
  7. Call transcript saved
"""

import logging
import re
import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Request
from fastapi.responses import Response

from .config import settings
from .ai_agent import analyze_transcript

logger = logging.getLogger(__name__)


# ── TwiML helpers ─────────────────────────────────────────────────────────────

def twiml_gather(say_text: str, action_url: str, hints: str = "") -> str:
    hints_attr = f' hints="{hints}"' if hints else ''
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather input="speech" action="{action_url}" method="POST" speechTimeout="3" language="en-US"{hints_attr}>
    <Say voice="Polly.Joanna">{say_text}</Say>
  </Gather>
  <Say voice="Polly.Joanna">I didn't catch that. Please call back and we'll be happy to help.</Say>
</Response>"""


def twiml_say(text: str, then_hangup: bool = True) -> str:
    hangup = "<Hangup/>" if then_hangup else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">{text}</Say>
  {hangup}
</Response>"""


def twiml_response(xml: str) -> Response:
    return Response(content=xml, media_type="application/xml")


# ── Conversation state (in-memory per call — use Redis for multi-instance) ───

_call_sessions: dict[str, dict] = {}


def get_session(call_sid: str) -> dict:
    if call_sid not in _call_sessions:
        _call_sessions[call_sid] = {
            "step": "greet",
            "caller_name": "",
            "service": "",
            "preferred_time": "",
            "transcript": [],
            "business_id": None,
            "business_name": "",
            "caller_phone": "",
        }
    return _call_sessions[call_sid]


def clear_session(call_sid: str):
    _call_sessions.pop(call_sid, None)


# ── AI conversation parser ────────────────────────────────────────────────────

async def ai_parse_response(user_speech: str, step: str, session: dict, claude_client=None) -> dict:
    """Use Claude to extract structured data from natural speech."""
    prompt = f"""You are an AI receptionist for {session['business_name']}.
The caller said: "{user_speech}"
Current step: {step}

Extract information from what they said. Return ONLY valid JSON:
{{
  "name": "extracted name or empty string",
  "service": "what service they want or empty string",
  "date": "extracted date like 'tomorrow', 'Monday', 'June 20' or empty string",
  "time": "extracted time like '2pm', '10:30am' or empty string",
  "understood": true or false
}}"""

    try:
        if claude_client:
            msg = claude_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = msg.content[0].text.strip()
            # Strip markdown code blocks if present
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            return json.loads(raw)
    except Exception as e:
        logger.error(f"AI parse error: {e}")

    # Fallback: just use raw speech
    return {"name": user_speech, "service": user_speech, "date": "", "time": "", "understood": True}


# ── Main call handler ─────────────────────────────────────────────────────────

async def handle_inbound_call(request: Request, db, business_id: Optional[int] = None) -> Response:
    """Entry point — called when Twilio receives an inbound call."""
    form = await request.form()
    call_sid   = form.get("CallSid", "unknown")
    from_phone = form.get("From", "")

    # Find which business this number belongs to
    from . import models
    business = None
    if business_id:
        business = db.query(models.Business).filter(models.Business.id == business_id).first()
    if not business:
        business = db.query(models.Business).filter(models.Business.is_active == True).first()
    if not business:
        return twiml_response(twiml_say(
            "Thank you for calling. We're not available right now. Please call back later."
        ))

    session = get_session(call_sid)
    session["business_id"]   = business.id
    session["business_name"] = business.name
    session["caller_phone"]  = from_phone

    greeting = (
        f"Hello and thank you for calling {business.name}! "
        f"I'm your AI assistant. "
        f"May I get your name please?"
    )
    session["step"] = "get_name"

    base = str(request.base_url).rstrip("/")
    return twiml_response(twiml_gather(
        say_text=greeting,
        action_url=f"{base}/twilio/conversation/{call_sid}",
        hints="my name is, I am, call me",
    ))


async def handle_conversation(request: Request, call_sid: str, db) -> Response:
    """Handles each speech input from the caller — step-by-step conversation."""
    form        = await request.form()
    speech      = form.get("SpeechResult", "").strip()
    session     = get_session(call_sid)
    base        = str(request.base_url).rstrip("/")
    action_url  = f"{base}/twilio/conversation/{call_sid}"

    # Log transcript
    if speech:
        session["transcript"].append(f"Caller: {speech}")

    # Init Claude client
    claude = None
    try:
        import anthropic
        if settings.anthropic_api_key:
            claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    except Exception:
        pass

    step = session.get("step", "get_name")

    # ── STEP: get caller name
    if step == "get_name":
        parsed = await ai_parse_response(speech, step, session, claude)
        name = parsed.get("name", speech).strip()
        if not name or len(name) < 2:
            return twiml_response(twiml_gather(
                "I'm sorry, I didn't catch your name. Could you please tell me your name?",
                action_url,
            ))
        session["caller_name"] = name
        session["step"] = "get_service"
        biz = session["business_name"]
        return twiml_response(twiml_gather(
            f"Great, thank you {name}! What service can I help you with today at {biz}?",
            action_url,
            hints="appointment, checkup, cleaning, consultation, booking",
        ))

    # ── STEP: get service
    elif step == "get_service":
        parsed = await ai_parse_response(speech, step, session, claude)
        service = parsed.get("service", speech).strip() or speech
        session["service"] = service
        session["step"] = "get_time"
        return twiml_response(twiml_gather(
            f"Perfect. When would you like to schedule your {service}? "
            f"You can say something like tomorrow at 2 PM, or Monday morning.",
            action_url,
            hints="tomorrow, monday, tuesday, morning, afternoon, am, pm",
        ))

    # ── STEP: get preferred time
    elif step == "get_time":
        session["preferred_time"] = speech
        session["step"] = "confirm"
        name    = session["caller_name"]
        service = session["service"]
        return twiml_response(twiml_gather(
            f"Let me confirm: {name}, {service}, {speech}. "
            f"Is that correct? Please say yes to confirm or no to change.",
            action_url,
            hints="yes, correct, that's right, no, change",
        ))

    # ── STEP: confirm booking
    elif step == "confirm":
        is_yes = any(w in speech.lower() for w in ["yes", "correct", "right", "yep", "sure", "confirm", "ok"])
        if not is_yes:
            session["step"] = "get_service"
            return twiml_response(twiml_gather(
                "No problem. Let's try again. What service do you need?",
                action_url,
            ))

        # Book the appointment
        try:
            appt = await _book_appointment(session, db)
            session["step"] = "done"

            # Send confirmations
            try:
                from .sms_email import send_appointment_sms, send_appointment_email
                if session["caller_phone"]:
                    send_appointment_sms(
                        session["caller_phone"], session["caller_name"],
                        session["business_name"], session["service"], appt.scheduled_at
                    )
                if appt.client_email:
                    send_appointment_email(
                        appt.client_email, session["caller_name"],
                        session["business_name"], session["service"], appt.scheduled_at
                    )
            except Exception as e:
                logger.error(f"Confirmation send error: {e}")

            # Save transcript to appointment
            full_transcript = "\n".join(session["transcript"])
            appt.notes = (appt.notes or "") + f"\n\n[AI Call Transcript]\n{full_transcript}"
            db.commit()
            clear_session(call_sid)

            dt_str = appt.scheduled_at.strftime("%A %B %d at %I:%M %p")
            return twiml_response(twiml_say(
                f"Wonderful! Your appointment for {session['service']} has been booked for {dt_str} "
                f"at {session['business_name']}. "
                f"You will receive a confirmation text shortly. "
                f"Thank you for calling and have a great day! Goodbye."
            ))
        except Exception as e:
            logger.error(f"Booking error: {e}")
            return twiml_response(twiml_say(
                "I'm sorry, I had trouble booking your appointment. "
                "Please call back and a team member will assist you. Thank you and goodbye."
            ))

    # Fallback
    clear_session(call_sid)
    return twiml_response(twiml_say(
        f"Thank you for calling {session.get('business_name', 'us')}. Goodbye!"
    ))


async def _book_appointment(session: dict, db) -> object:
    """Parse preferred time string and create appointment in DB."""
    from . import models, schemas
    from dateutil import parser as date_parser
    import re

    # Try to parse natural language date/time
    time_str = session["preferred_time"]
    now = datetime.now()

    scheduled = None
    try:
        # Handle relative words
        lower = time_str.lower()
        if "tomorrow" in lower:
            base_date = now + timedelta(days=1)
            time_match = re.search(r'(\d{1,2}(?::\d{2})?\s*(?:am|pm))', lower)
            if time_match:
                scheduled = date_parser.parse(f"{base_date.strftime('%Y-%m-%d')} {time_match.group(1)}")
            else:
                scheduled = base_date.replace(hour=10, minute=0, second=0, microsecond=0)
        else:
            scheduled = date_parser.parse(time_str, fuzzy=True, default=now + timedelta(days=1))
    except Exception:
        # Default: next day at 10am
        scheduled = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

    # Create appointment
    appt = models.Appointment(
        business_id  = session["business_id"],
        client_name  = session["caller_name"],
        client_phone = session["caller_phone"],
        service      = session["service"],
        scheduled_at = scheduled,
        status       = "pending_approval",
        notes        = f"Booked via AI phone call. Requested time: {session['preferred_time']}",
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt
