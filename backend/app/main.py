"""
EZ-NEXUS AI — FastAPI Application Entry Point
Your AI Workforce for Business Growth™

Endpoints:
  GET  /                          Health check
  POST /businesses                Create a business
  GET  /businesses                List all businesses
  GET  /businesses/{id}           Get one business
  PUT  /businesses/{id}           Update a business
  DELETE /businesses/{id}         Soft-delete a business

  POST /appointments              Create an appointment
  GET  /appointments              List appointments (filter by business_id)
  GET  /appointments/{id}         Get one appointment
  PUT  /appointments/{id}         Update an appointment
  DELETE /appointments/{id}       Cancel an appointment

  POST /ai/summarize              Analyse a call transcript
  GET  /stats                     Dashboard aggregate stats

  WS   /ws/{client_id}            Real-time notification stream
"""

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import engine, get_db, SessionLocal
from . import models, schemas
from .ai_agent import analyze_transcript
from .notifications import hub
from .config import settings
from .auth import router as auth_router, seed_admin, get_current_user, get_admin_user

# ── Bootstrap ───────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# Create all tables (idempotent — skips existing tables)
models.Base.metadata.create_all(bind=engine)

# Seed default admin on startup
with SessionLocal() as _seed_db:
    seed_admin(_seed_db)

app = FastAPI(
    title="EZ-NEXUS AI Platform",
    description="Your AI Workforce for Business Growth™",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow the Vite dev server and any same-origin frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mount sub-routers
app.include_router(auth_router)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
def health():
    return {
        "status": "ok",
        "service": "EZ-NEXUS AI Platform",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "ws_clients": hub.connection_count,
    }


# ── Business Endpoints ───────────────────────────────────────────────────────

@app.post("/businesses", response_model=schemas.BusinessOut, status_code=201, tags=["businesses"])
def create_business(payload: schemas.BusinessCreate, db: Session = Depends(get_db)):
    if db.query(models.Business).filter(models.Business.email == payload.email).first():
        raise HTTPException(status_code=409, detail="A business with this email already exists.")
    biz = models.Business(**payload.model_dump())
    db.add(biz)
    db.commit()
    db.refresh(biz)
    logger.info("Created business id=%d name='%s'", biz.id, biz.name)
    return biz


@app.get("/businesses", response_model=List[schemas.BusinessOut], tags=["businesses"])
def list_businesses(
    skip: int = 0,
    limit: int = 50,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    q = db.query(models.Business)
    if active_only:
        q = q.filter(models.Business.is_active == True)
    return q.offset(skip).limit(limit).all()


@app.get("/businesses/{business_id}", response_model=schemas.BusinessOut, tags=["businesses"])
def get_business(business_id: int, db: Session = Depends(get_db)):
    biz = db.get(models.Business, business_id)
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found.")
    return biz


@app.put("/businesses/{business_id}", response_model=schemas.BusinessOut, tags=["businesses"])
def update_business(business_id: int, payload: schemas.BusinessUpdate, db: Session = Depends(get_db)):
    biz = db.get(models.Business, business_id)
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(biz, field, value)
    biz.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(biz)
    return biz


@app.delete("/businesses/{business_id}", tags=["businesses"])
def delete_business(business_id: int, db: Session = Depends(get_db)):
    biz = db.get(models.Business, business_id)
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found.")
    biz.is_active = False
    biz.updated_at = datetime.utcnow()
    db.commit()
    return {"detail": f"Business {business_id} deactivated."}


# ── Appointment Endpoints ────────────────────────────────────────────────────

@app.post("/appointments", response_model=schemas.AppointmentOut, status_code=201, tags=["appointments"])
async def create_appointment(payload: schemas.AppointmentCreate, db: Session = Depends(get_db)):
    # Verify business exists
    if not db.get(models.Business, payload.business_id):
        raise HTTPException(status_code=404, detail="Business not found.")

    appt = models.Appointment(**payload.model_dump())
    db.add(appt)
    db.commit()
    db.refresh(appt)
    logger.info("Created appointment id=%d client='%s'", appt.id, appt.client_name)

    # Broadcast via WebSocket
    await hub.notify_new_appointment({
        "id": appt.id,
        "client_name": appt.client_name,
        "service": appt.service,
        "scheduled_at": appt.scheduled_at.isoformat(),
    })

    return appt


@app.get("/appointments", response_model=List[schemas.AppointmentOut], tags=["appointments"])
def list_appointments(
    business_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(models.Appointment)
    if business_id:
        q = q.filter(models.Appointment.business_id == business_id)
    if status:
        q = q.filter(models.Appointment.status == status)
    return q.order_by(models.Appointment.scheduled_at).offset(skip).limit(limit).all()


@app.get("/appointments/{appointment_id}", response_model=schemas.AppointmentOut, tags=["appointments"])
def get_appointment(appointment_id: int, db: Session = Depends(get_db)):
    appt = db.get(models.Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    return appt


@app.put("/appointments/{appointment_id}", response_model=schemas.AppointmentOut, tags=["appointments"])
async def update_appointment(
    appointment_id: int,
    payload: schemas.AppointmentUpdate,
    db: Session = Depends(get_db),
):
    appt = db.get(models.Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")

    old_status = appt.status
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(appt, field, value)
    db.commit()
    db.refresh(appt)

    # Notify status changes
    if payload.status and payload.status != old_status:
        await hub.notify_status_change(appointment_id, old_status, payload.status)

    return appt


@app.delete("/appointments/{appointment_id}", tags=["appointments"])
async def cancel_appointment(appointment_id: int, db: Session = Depends(get_db)):
    appt = db.get(models.Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    old_status = appt.status
    appt.status = "cancelled"
    db.commit()
    await hub.notify_status_change(appointment_id, old_status, "cancelled")
    return {"detail": f"Appointment {appointment_id} cancelled."}


# ── AI Endpoint ──────────────────────────────────────────────────────────────

@app.post("/ai/summarize", response_model=schemas.CallSummaryResponse, tags=["ai"])
async def summarize_call(payload: schemas.CallSummaryRequest, db: Session = Depends(get_db)):
    result = analyze_transcript(payload.transcript)

    # Persist summary to appointment if ID provided
    if payload.appointment_id:
        appt = db.get(models.Appointment, payload.appointment_id)
        if appt:
            appt.call_summary = result["summary"]
            appt.triage_result = result["triage"]
            db.commit()
            await hub.notify_ai_summary(payload.appointment_id, result["summary"], result["triage"])

    return schemas.CallSummaryResponse(**result)


# ── Stats / Dashboard ────────────────────────────────────────────────────────

@app.get("/stats", tags=["dashboard"])
def get_stats(db: Session = Depends(get_db)):
    total_businesses  = db.query(models.Business).filter(models.Business.is_active == True).count()
    total_appointments = db.query(models.Appointment).count()
    urgent_open       = db.query(models.Appointment).filter(
        models.Appointment.triage_result == "urgent",
        models.Appointment.status.in_(["scheduled", "confirmed"]),
    ).count()
    completed_today   = db.query(models.Appointment).filter(
        models.Appointment.status == "completed",
        models.Appointment.scheduled_at >= datetime.utcnow().date(),
    ).count()

    return {
        "total_businesses":   total_businesses,
        "total_appointments": total_appointments,
        "urgent_open":        urgent_open,
        "completed_today":    completed_today,
        "ws_connections":     hub.connection_count,
    }


# ── Commander AI ─────────────────────────────────────────────────────────────

@app.get("/commander/health", tags=["commander"])
def commander_health(db: Session = Depends(get_db)):
    """System health check — no auth required so frontend can show status banner."""
    from .commander import run_health_check
    return run_health_check(db)


@app.post("/commander/chat", tags=["commander"])
async def commander_chat(payload: schemas.CommanderChatRequest, db: Session = Depends(get_db)):
    """Chat with EZ-NEXUS COMMANDER AI."""
    from .commander import chat_with_commander
    reply = await chat_with_commander(payload.message, db)
    return schemas.CommanderChatResponse(
        reply=reply,
        checked_at=datetime.utcnow().isoformat() + "Z",
    )


@app.post("/commander/generate-agent", tags=["commander"])
async def generate_agent(
    payload: schemas.AgentGenRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Generate a new AI agent specification from a plain-language description."""
    from .commander import generate_agent_spec
    spec = await generate_agent_spec(payload.description, db, requested_by_id=current_user.id)
    return spec


@app.get("/commander/agents", tags=["commander"])
def list_agent_definitions(db: Session = Depends(get_db)):
    """List all generated/saved agent definitions."""
    return db.query(models.AgentDefinition).order_by(models.AgentDefinition.created_at.desc()).all()


@app.put("/commander/agents/{agent_id}/approve", tags=["commander"])
def approve_agent_definition(
    agent_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    """Admin approves an agent definition to move it from draft → approved."""
    agent = db.get(models.AgentDefinition, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent definition not found.")
    agent.status = "approved"
    agent.approved_at = datetime.utcnow()
    db.commit()
    return {"detail": f"Agent '{agent.name}' approved.", "status": "approved"}


@app.get("/commander/alerts", tags=["commander"])
def list_alerts(
    unread_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(models.AdminAlert)
    if unread_only:
        q = q.filter(models.AdminAlert.is_read == False)
    return q.order_by(models.AdminAlert.created_at.desc()).limit(limit).all()


@app.put("/commander/alerts/{alert_id}/read", tags=["commander"])
def mark_alert_read(alert_id: int, db: Session = Depends(get_db)):
    alert = db.get(models.AdminAlert, alert_id)
    if alert:
        alert.is_read = True
        db.commit()
    return {"detail": "marked read"}


@app.put("/commander/alerts/read-all", tags=["commander"])
def mark_all_alerts_read(db: Session = Depends(get_db)):
    db.query(models.AdminAlert).filter(models.AdminAlert.is_read == False).update({"is_read": True})
    db.commit()
    return {"detail": "All alerts marked as read."}


# ── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await hub.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await hub.send_to(client_id, {"type": "pong"})
    except WebSocketDisconnect:
        hub.disconnect(client_id)
        logger.info("Client %s disconnected", client_id)


# ── Twilio Inbound Call Webhooks ─────────────────────────────────────────────

@app.post("/twilio/inbound", tags=["twilio"])
async def twilio_inbound(request: Request, db: Session = Depends(get_db)):
    """Twilio calls this when someone calls your Twilio number.
    Set this URL in your Twilio console under Phone Numbers → Voice Webhook."""
    from .twilio_voice import handle_inbound_call
    return await handle_inbound_call(request, db)


@app.post("/twilio/inbound/{business_id}", tags=["twilio"])
async def twilio_inbound_for_business(business_id: int, request: Request, db: Session = Depends(get_db)):
    """Route calls to a specific business (for multi-tenant deployments)."""
    from .twilio_voice import handle_inbound_call
    return await handle_inbound_call(request, db, business_id=business_id)


@app.post("/twilio/conversation/{call_sid}", tags=["twilio"])
async def twilio_conversation(call_sid: str, request: Request, db: Session = Depends(get_db)):
    """Twilio calls this after each speech input to continue the conversation."""
    from .twilio_voice import handle_conversation
    return await handle_conversation(request, call_sid, db)


# ── Staff Appointment Approval ────────────────────────────────────────────────

@app.get("/appointments/approve/{token}", tags=["appointments"])
async def approve_appointment_link(token: str, db: Session = Depends(get_db)):
    """One-click approve from staff email link (GET for email button clicks)."""
    tok = db.query(models.ApprovalToken).filter(models.ApprovalToken.token == token).first()
    if not tok:
        raise HTTPException(status_code=404, detail="Invalid or expired approval link.")
    if tok.used:
        return {"detail": "This appointment was already processed.", "appointment_id": tok.appointment_id}
    appt = db.get(models.Appointment, tok.appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")

    appt.status = "confirmed"
    tok.used = True
    db.commit()

    # Send client confirmation
    try:
        from .sms_email import send_appointment_sms, send_appointment_email
        if appt.client_phone:
            send_appointment_sms(appt.client_phone, appt.client_name,
                                 appt.business.name, appt.service, appt.scheduled_at)
        if appt.client_email:
            send_appointment_email(appt.client_email, appt.client_name,
                                   appt.business.name, appt.service, appt.scheduled_at)
    except Exception as e:
        logger.error(f"Confirmation after approval failed: {e}")

    await hub.notify_status_change(appt.id, "pending_approval", "confirmed")
    dt = appt.scheduled_at.strftime("%b %d at %I:%M %p")
    return {"detail": f"Appointment confirmed! {appt.client_name} — {appt.service} on {dt}",
            "appointment_id": appt.id}


@app.post("/appointments/{appointment_id}/send-confirmation", tags=["appointments"])
async def send_confirmation(appointment_id: int, db: Session = Depends(get_db)):
    """Manually trigger SMS + email confirmation for an appointment."""
    appt = db.get(models.Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    sms_sent = email_sent = False
    try:
        from .sms_email import send_appointment_sms, send_appointment_email
        if appt.client_phone:
            sms_sent = send_appointment_sms(appt.client_phone, appt.client_name,
                                            appt.business.name, appt.service, appt.scheduled_at)
        if appt.client_email:
            email_sent = send_appointment_email(appt.client_email, appt.client_name,
                                                appt.business.name, appt.service, appt.scheduled_at)
    except Exception as e:
        logger.error(f"Manual confirmation error: {e}")
    return {"sms_sent": sms_sent, "email_sent": email_sent}


@app.post("/appointments/{appointment_id}/notify-staff", tags=["appointments"])
async def notify_staff(appointment_id: int, db: Session = Depends(get_db)):
    """Send or resend staff approval notification email."""
    appt = db.get(models.Appointment, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")

    biz = appt.business
    staff_email = biz.staff_email or biz.email
    if not staff_email:
        raise HTTPException(status_code=400, detail="No staff email configured for this business.")

    # Create or reuse approval token
    tok = appt.approval_token
    if not tok:
        tok = models.ApprovalToken(appointment_id=appt.id)
        db.add(tok)
        db.commit()
        db.refresh(tok)

    try:
        from .sms_email import send_staff_notification_email
        sent = send_staff_notification_email(
            staff_email, biz.name, appt.client_name,
            appt.client_phone or "", appt.service, appt.scheduled_at,
            tok.token, settings.base_url
        )
    except Exception as e:
        logger.error(f"Staff notification error: {e}")
        sent = False

    return {"sent": sent, "staff_email": staff_email, "token": tok.token}


# ── Platform Config Endpoint ──────────────────────────────────────────────────

@app.get("/config/status", tags=["config"])
def config_status():
    """Returns which integrations are configured (no secrets exposed)."""
    return {
        "twilio_configured": settings.twilio_configured,
        "smtp_configured": settings.smtp_configured,
        "ai_configured": bool(settings.anthropic_api_key),
        "twilio_phone": settings.twilio_phone_number or None,
    }
