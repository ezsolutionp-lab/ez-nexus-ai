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

import json
import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
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


# ── Contacts ──────────────────────────────────────────────────────────────────

@app.post("/contacts", response_model=schemas.ContactOut, status_code=201, tags=["contacts"])
def create_contact(payload: schemas.ContactCreate, db: Session = Depends(get_db)):
    if not db.get(models.Business, payload.business_id):
        raise HTTPException(status_code=404, detail="Business not found.")
    contact = models.Contact(**payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@app.get("/contacts", response_model=List[schemas.ContactOut], tags=["contacts"])
def list_contacts(
    business_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(models.Contact)
    if business_id:
        q = q.filter(models.Contact.business_id == business_id)
    return q.order_by(models.Contact.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/contacts/{contact_id}", response_model=schemas.ContactOut, tags=["contacts"])
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    c = db.get(models.Contact, contact_id)
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found.")
    return c


@app.put("/contacts/{contact_id}", response_model=schemas.ContactOut, tags=["contacts"])
def update_contact(contact_id: int, payload: schemas.ContactUpdate, db: Session = Depends(get_db)):
    c = db.get(models.Contact, contact_id)
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    db.commit()
    db.refresh(c)
    return c


@app.delete("/contacts/{contact_id}", tags=["contacts"])
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    c = db.get(models.Contact, contact_id)
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found.")
    db.delete(c)
    db.commit()
    return {"detail": f"Contact {contact_id} deleted."}


# ── Patient Intake ────────────────────────────────────────────────────────────

@app.post("/patient-intake", response_model=schemas.PatientIntakeOut, status_code=201, tags=["healthcare"])
def create_patient_intake(payload: schemas.PatientIntakeCreate, db: Session = Depends(get_db)):
    if not db.get(models.Contact, payload.contact_id):
        raise HTTPException(status_code=404, detail="Contact not found.")
    existing = db.query(models.PatientIntake).filter(
        models.PatientIntake.contact_id == payload.contact_id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Intake form already exists for this contact.")
    intake = models.PatientIntake(**payload.model_dump())
    db.add(intake)
    db.commit()
    db.refresh(intake)
    return intake


@app.get("/patient-intake", response_model=List[schemas.PatientIntakeOut], tags=["healthcare"])
def list_patient_intakes(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(models.PatientIntake)
    if status:
        q = q.filter(models.PatientIntake.status == status)
    return q.order_by(models.PatientIntake.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/patient-intake/{intake_id}", response_model=schemas.PatientIntakeOut, tags=["healthcare"])
def get_patient_intake(intake_id: int, db: Session = Depends(get_db)):
    intake = db.get(models.PatientIntake, intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="Intake not found.")
    return intake


@app.put("/patient-intake/{intake_id}", response_model=schemas.PatientIntakeOut, tags=["healthcare"])
def update_patient_intake(intake_id: int, payload: schemas.PatientIntakeUpdate, db: Session = Depends(get_db)):
    intake = db.get(models.PatientIntake, intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="Intake not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(intake, field, value)
    db.commit()
    db.refresh(intake)
    return intake


# ── Supplier Marketplace ──────────────────────────────────────────────────────

@app.post("/supplier/products", response_model=schemas.SupplierProductOut, status_code=201, tags=["marketplace"])
def create_supplier_product(payload: schemas.SupplierProductCreate, db: Session = Depends(get_db)):
    product = models.SupplierProduct(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.get("/supplier/products", response_model=List[schemas.SupplierProductOut], tags=["marketplace"])
def list_supplier_products(
    category: Optional[str] = None,
    available_only: bool = True,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(models.SupplierProduct)
    if category:
        q = q.filter(models.SupplierProduct.category == category)
    if available_only:
        q = q.filter(models.SupplierProduct.is_available == True)
    return q.order_by(models.SupplierProduct.name).offset(skip).limit(limit).all()


@app.put("/supplier/products/{product_id}", response_model=schemas.SupplierProductOut, tags=["marketplace"])
def update_supplier_product(product_id: int, payload: schemas.SupplierProductUpdate, db: Session = Depends(get_db)):
    product = db.get(models.SupplierProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


@app.delete("/supplier/products/{product_id}", tags=["marketplace"])
def delete_supplier_product(product_id: int, db: Session = Depends(get_db)):
    product = db.get(models.SupplierProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    db.delete(product)
    db.commit()
    return {"detail": f"Product {product_id} deleted."}


# ── Agent Dispatch ────────────────────────────────────────────────────────────

@app.get("/agents/roster", tags=["agents"])
def get_agent_roster():
    """List all 13 specialized agents with their status."""
    from .agents import AGENT_REGISTRY
    return [agent.to_dict() for agent in AGENT_REGISTRY.values()]


@app.post("/agents/run", tags=["agents"])
async def run_agent_task(payload: schemas.AgentRunRequest, db: Session = Depends(get_db)):
    """Dispatch a task to a specialized agent and persist the result."""
    from .agents import AGENT_REGISTRY
    import json

    agent = AGENT_REGISTRY.get(payload.agent_key)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{payload.agent_key}' not found. Available: {list(AGENT_REGISTRY.keys())}"
        )

    task_record = models.AgentTask(
        agent_name=agent.name,
        task_type=payload.task_type,
        status="running",
        input_data=json.dumps(payload.payload),
    )
    db.add(task_record)
    db.commit()
    db.refresh(task_record)

    result = await agent.run(payload.task_type, payload.payload, db)

    task_record.status = result["status"]
    task_record.output_data = json.dumps(result.get("result", {}))
    task_record.error_msg = result.get("error")
    task_record.duration_ms = result.get("duration_ms")
    task_record.completed_at = datetime.utcnow()
    db.commit()

    return {**result, "task_id": task_record.id}


@app.get("/agents/tasks", response_model=List[schemas.AgentTaskOut], tags=["agents"])
def list_agent_tasks(
    agent_name: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(models.AgentTask)
    if agent_name:
        q = q.filter(models.AgentTask.agent_name == agent_name)
    return q.order_by(models.AgentTask.created_at.desc()).offset(skip).limit(limit).all()


# ── Call Logs ─────────────────────────────────────────────────────────────────

@app.get("/call-logs", response_model=List[schemas.CallLogOut], tags=["call_logs"])
def list_call_logs(
    business_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(models.CallLog)
    if business_id:
        q = q.filter(models.CallLog.business_id == business_id)
    return q.order_by(models.CallLog.created_at.desc()).offset(skip).limit(limit).all()


# ─────────────────────────────────────────────────────────────────────────────
# DATA ENTRY AI MODULE
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_upload_dir() -> Path:
    p = Path(settings.upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_audit(db: Session, actor: str, action: str, entity_type: str,
                entity_id: str, after: dict, before: dict = None, business_id: int = None):
    if not settings.audit_log_enabled:
        return
    try:
        db.add(models.AuditLog(
            business_id=business_id,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            before_data=json.dumps(before) if before else None,
            after_data=json.dumps(after) if after else None,
        ))
    except Exception as e:
        logger.error("Audit log save failed: %s", e)


# ── Document Upload & AI Processing ──────────────────────────────────────────

@app.post("/data-entry/upload", tags=["data_entry"])
async def upload_document_for_data_entry(
    business_id: int = Form(...),
    patient_id:  Optional[int] = Form(None),
    workflow_type: str = Form("medical"),   # medical | bookkeeping | insurance | equipment
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload a document (PDF, scan, Word, Excel, CSV, image) for AI data extraction.
    Commander AI supervises the full pipeline and returns an admin-approval package.
    RULE: No data is posted to production records without admin approval.
    """
    if not db.get(models.Business, business_id):
        raise HTTPException(status_code=404, detail="Business not found.")

    # Validate file size
    file.file.seek(0, 2)
    size_bytes = file.file.tell()
    file.file.seek(0)
    if size_bytes > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb}MB limit.")

    # Save file to disk
    upload_dir = _ensure_upload_dir()
    suffix = Path(file.filename or "upload").suffix or ".bin"
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    storage_path = upload_dir / safe_name

    with storage_path.open("wb") as buf:
        shutil.copyfileobj(file.file, buf)

    # Extract text
    from .services.document_processor import DocumentProcessor
    processor = DocumentProcessor()
    text, confidence = processor.extract_text(str(storage_path), file.content_type)
    doc_type = DocumentProcessor.classify_document_type(file.filename or "", text)

    # Save document record
    doc = models.UploadedDocument(
        business_id=business_id,
        patient_id=patient_id,
        filename=file.filename or safe_name,
        content_type=file.content_type,
        storage_path=str(storage_path),
        document_type=doc_type,
        extracted_text=text,
        confidence_score=confidence,
        extraction_status="completed" if text else "needs_review",
        file_size_kb=size_bytes // 1024,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Commander AI pipeline
    from .commander import process_document_data_entry
    result = await process_document_data_entry(
        text=text,
        filename=file.filename or safe_name,
        workflow_type=workflow_type,
        db=db,
        business_id=business_id,
    )

    # Save data entry job
    job = models.DataEntryJob(
        business_id=business_id,
        document_id=doc.id,
        job_type=workflow_type,
        status="pending_admin_approval",
        extracted_fields=json.dumps(result.get("extraction", {}).get("fields") or result.get("extraction", {}).get("entry") or {}),
        missing_fields=json.dumps(result.get("verification", {}).get("missing_required", [])),
        validation_errors=json.dumps(result.get("verification", {}).get("validation_errors", [])),
        commander_recommendations=json.dumps(result.get("commander_recommendations", [])),
        created_by_agent="ez_nexus_commander_ai",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    _save_audit(db, "commander_ai", "data_entry_job_created", "DataEntryJob",
                job.id, result, business_id=business_id)
    db.commit()

    return {
        "document_id": doc.id,
        "job_id":      job.id,
        "document_type": doc_type,
        "confidence_score": confidence,
        "commander_result": result,
        "requires_admin_approval": True,
        "message": "Document processed. Awaiting admin approval before data is posted.",
    }


# ── Data Entry Job Management ─────────────────────────────────────────────────

@app.get("/data-entry/jobs", response_model=List[schemas.DataEntryJobOut], tags=["data_entry"])
def list_data_entry_jobs(
    business_id:  Optional[int] = None,
    status:       Optional[str] = None,
    job_type:     Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(models.DataEntryJob)
    if business_id:
        q = q.filter(models.DataEntryJob.business_id == business_id)
    if status:
        q = q.filter(models.DataEntryJob.status == status)
    if job_type:
        q = q.filter(models.DataEntryJob.job_type == job_type)
    return q.order_by(models.DataEntryJob.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/data-entry/jobs/{job_id}", tags=["data_entry"])
def get_data_entry_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(models.DataEntryJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        **schemas.DataEntryJobOut.model_validate(job).model_dump(),
        "extracted_fields_parsed":  json.loads(job.extracted_fields or "{}"),
        "missing_fields_parsed":    json.loads(job.missing_fields or "[]"),
        "validation_errors_parsed": json.loads(job.validation_errors or "[]"),
        "recommendations_parsed":   json.loads(job.commander_recommendations or "[]"),
    }


@app.post("/data-entry/jobs/{job_id}/approve", tags=["data_entry"])
def approve_data_entry_job(
    job_id: int,
    payload: schemas.DataEntryApproveRequest,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    """Admin approves a data entry job — marks it ready to post to production."""
    job = db.get(models.DataEntryJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    before = {"status": job.status, "admin_approved": job.admin_approved}
    job.admin_approved = True
    job.status = "approved_ready_to_post"
    job.approval_notes = payload.admin_notes
    _save_audit(db, admin.email, "data_entry_job_approved", "DataEntryJob",
                job_id, {"status": job.status}, before, job.business_id)
    db.commit()
    return {"status": "approved", "job_id": job.id, "message": "Job approved and ready to post."}


@app.post("/data-entry/jobs/{job_id}/decline", tags=["data_entry"])
def decline_data_entry_job(
    job_id: int,
    payload: schemas.DataEntryDeclineRequest,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    """Admin declines — sends job back for revision."""
    job = db.get(models.DataEntryJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    before = {"status": job.status}
    job.status = "declined_needs_revision"
    job.approval_notes = payload.reason
    job.admin_approved = False
    _save_audit(db, admin.email, "data_entry_job_declined", "DataEntryJob",
                job_id, {"status": job.status, "reason": payload.reason}, before, job.business_id)
    db.commit()
    return {"status": "declined", "job_id": job.id, "reason": payload.reason}


# ── Document listing ──────────────────────────────────────────────────────────

@app.get("/data-entry/documents", response_model=List[schemas.UploadedDocumentOut], tags=["data_entry"])
def list_documents(
    business_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(models.UploadedDocument)
    if business_id:
        q = q.filter(models.UploadedDocument.business_id == business_id)
    return q.order_by(models.UploadedDocument.created_at.desc()).offset(skip).limit(limit).all()


# ── Excel / CSV Export ────────────────────────────────────────────────────────

@app.post("/data-entry/export/patient-excel", tags=["data_entry"])
def export_patient_excel(
    business_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    """Export all approved patient data entry jobs to Excel workbook."""
    jobs = db.query(models.DataEntryJob).filter(
        models.DataEntryJob.business_id == business_id,
        models.DataEntryJob.admin_approved == True,
        models.DataEntryJob.job_type.in_(["medical", "insurance"]),
    ).all()

    rows = []
    for job in jobs:
        try:
            fields = json.loads(job.extracted_fields or "{}")
            rows.append({**fields, "status": job.status, "notes": job.approval_notes or ""})
        except Exception:
            pass

    upload_dir = _ensure_upload_dir()
    output = str(upload_dir / f"patient_export_{business_id}_{uuid.uuid4().hex[:6]}.xlsx")

    from .services.spreadsheet_service import SpreadsheetService
    SpreadsheetService().create_patient_workbook(rows, output)
    _save_audit(db, admin.email, "patient_excel_exported", "DataEntryJob",
                business_id, {"rows": len(rows)}, business_id=business_id)
    db.commit()
    return FileResponse(output, filename=Path(output).name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/data-entry/export/bookkeeping-excel", tags=["data_entry"])
def export_bookkeeping_excel(
    business_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    """Export all approved bookkeeping entries to Excel workbook."""
    entries = db.query(models.BookkeepingEntry).filter(
        models.BookkeepingEntry.business_id == business_id,
        models.BookkeepingEntry.admin_approved == True,
    ).all()

    rows = [schemas.BookkeepingEntryOut.model_validate(e).model_dump() for e in entries]
    upload_dir = _ensure_upload_dir()
    output = str(upload_dir / f"bookkeeping_{business_id}_{uuid.uuid4().hex[:6]}.xlsx")

    from .services.spreadsheet_service import SpreadsheetService
    SpreadsheetService().create_bookkeeping_workbook(rows, output)
    _save_audit(db, admin.email, "bookkeeping_excel_exported", "BookkeepingEntry",
                business_id, {"rows": len(rows)}, business_id=business_id)
    db.commit()
    return FileResponse(output, filename=Path(output).name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/data-entry/export/quickbooks-csv", tags=["data_entry"])
def export_quickbooks_csv(business_id: int, db: Session = Depends(get_db)):
    """Export approved bookkeeping entries as QuickBooks-compatible CSV."""
    entries = db.query(models.BookkeepingEntry).filter(
        models.BookkeepingEntry.business_id == business_id,
        models.BookkeepingEntry.admin_approved == True,
    ).all()
    rows = [schemas.BookkeepingEntryOut.model_validate(e).model_dump() for e in entries]
    upload_dir = _ensure_upload_dir()
    output = str(upload_dir / f"quickbooks_{business_id}.csv")

    from .services.spreadsheet_service import SpreadsheetService
    SpreadsheetService().create_quickbooks_template(rows, output)
    return FileResponse(output, filename=Path(output).name, media_type="text/csv")


# ── Patients ──────────────────────────────────────────────────────────────────

@app.post("/patients", response_model=schemas.PatientOut, status_code=201, tags=["patients"])
def create_patient(payload: schemas.PatientCreate, db: Session = Depends(get_db)):
    if not db.get(models.Business, payload.business_id):
        raise HTTPException(status_code=404, detail="Business not found.")
    patient = models.Patient(**payload.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@app.get("/patients", response_model=List[schemas.PatientOut], tags=["patients"])
def list_patients(
    business_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(models.Patient)
    if business_id:
        q = q.filter(models.Patient.business_id == business_id)
    return q.order_by(models.Patient.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/patients/{patient_id}", response_model=schemas.PatientOut, tags=["patients"])
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    p = db.get(models.Patient, patient_id)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return p


@app.put("/patients/{patient_id}", response_model=schemas.PatientOut, tags=["patients"])
def update_patient(patient_id: int, payload: schemas.PatientUpdate, db: Session = Depends(get_db)):
    p = db.get(models.Patient, patient_id)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(p, field, value)
    db.commit()
    db.refresh(p)
    return p


@app.delete("/patients/{patient_id}", tags=["patients"])
def delete_patient(patient_id: int, db: Session = Depends(get_db),
                   admin: models.User = Depends(get_admin_user)):
    p = db.get(models.Patient, patient_id)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found.")
    db.delete(p)
    db.commit()
    return {"detail": f"Patient {patient_id} deleted."}


# ── Insurance Profiles ────────────────────────────────────────────────────────

@app.post("/patients/{patient_id}/insurance", response_model=schemas.InsuranceProfileOut,
          status_code=201, tags=["patients"])
def create_insurance_profile(
    patient_id: int,
    payload: schemas.InsuranceProfileCreate,
    db: Session = Depends(get_db),
):
    if not db.get(models.Patient, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found.")
    profile = models.InsuranceProfile(**{**payload.model_dump(), "patient_id": patient_id})
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@app.get("/patients/{patient_id}/insurance", response_model=List[schemas.InsuranceProfileOut],
         tags=["patients"])
def list_insurance_profiles(patient_id: int, db: Session = Depends(get_db)):
    if not db.get(models.Patient, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found.")
    return db.query(models.InsuranceProfile).filter(
        models.InsuranceProfile.patient_id == patient_id
    ).all()


@app.put("/patients/{patient_id}/insurance/{profile_id}",
         response_model=schemas.InsuranceProfileOut, tags=["patients"])
def update_insurance_profile(
    patient_id: int,
    profile_id: int,
    payload: schemas.InsuranceProfileUpdate,
    db: Session = Depends(get_db),
):
    profile = db.query(models.InsuranceProfile).filter(
        models.InsuranceProfile.id == profile_id,
        models.InsuranceProfile.patient_id == patient_id,
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Insurance profile not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


# ── Equipment Requests ────────────────────────────────────────────────────────

@app.post("/equipment-requests", response_model=schemas.EquipmentRequestOut,
          status_code=201, tags=["equipment"])
def create_equipment_request(payload: schemas.EquipmentRequestCreate, db: Session = Depends(get_db)):
    if not db.get(models.Business, payload.business_id):
        raise HTTPException(status_code=404, detail="Business not found.")
    req = models.EquipmentRequest(**payload.model_dump())
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


@app.get("/equipment-requests", response_model=List[schemas.EquipmentRequestOut], tags=["equipment"])
def list_equipment_requests(
    business_id:  Optional[int] = None,
    patient_id:   Optional[int] = None,
    status:       Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(models.EquipmentRequest)
    if business_id:
        q = q.filter(models.EquipmentRequest.business_id == business_id)
    if patient_id:
        q = q.filter(models.EquipmentRequest.patient_id == patient_id)
    if status:
        q = q.filter(models.EquipmentRequest.status == status)
    return q.order_by(models.EquipmentRequest.created_at.desc()).offset(skip).limit(limit).all()


@app.put("/equipment-requests/{req_id}", response_model=schemas.EquipmentRequestOut, tags=["equipment"])
def update_equipment_request(req_id: int, payload: schemas.EquipmentRequestUpdate,
                              db: Session = Depends(get_db)):
    req = db.get(models.EquipmentRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Equipment request not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(req, field, value)
    db.commit()
    db.refresh(req)
    return req


# ── Bookkeeping Entries ───────────────────────────────────────────────────────

@app.post("/bookkeeping", response_model=schemas.BookkeepingEntryOut,
          status_code=201, tags=["bookkeeping"])
def create_bookkeeping_entry(payload: schemas.BookkeepingEntryCreate, db: Session = Depends(get_db)):
    if not db.get(models.Business, payload.business_id):
        raise HTTPException(status_code=404, detail="Business not found.")
    entry = models.BookkeepingEntry(**payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@app.get("/bookkeeping", response_model=List[schemas.BookkeepingEntryOut], tags=["bookkeeping"])
def list_bookkeeping_entries(
    business_id: Optional[int] = None,
    status:      Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(models.BookkeepingEntry)
    if business_id:
        q = q.filter(models.BookkeepingEntry.business_id == business_id)
    if status:
        q = q.filter(models.BookkeepingEntry.status == status)
    return q.order_by(models.BookkeepingEntry.created_at.desc()).offset(skip).limit(limit).all()


@app.put("/bookkeeping/{entry_id}", response_model=schemas.BookkeepingEntryOut, tags=["bookkeeping"])
def update_bookkeeping_entry(entry_id: int, payload: schemas.BookkeepingEntryUpdate,
                              db: Session = Depends(get_db)):
    entry = db.get(models.BookkeepingEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return entry


@app.post("/bookkeeping/{entry_id}/approve", tags=["bookkeeping"])
def approve_bookkeeping_entry(entry_id: int, db: Session = Depends(get_db),
                               admin: models.User = Depends(get_admin_user)):
    entry = db.get(models.BookkeepingEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    entry.admin_approved = True
    entry.status = "approved"
    _save_audit(db, admin.email, "bookkeeping_entry_approved", "BookkeepingEntry",
                entry_id, {"status": "approved"}, business_id=entry.business_id)
    db.commit()
    return {"status": "approved", "entry_id": entry_id}


# ── Master Recommendations ────────────────────────────────────────────────────

@app.get("/master-recommendations", response_model=List[schemas.MasterRecommendationOut],
         tags=["commander"])
def list_master_recommendations(
    status:   Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(models.MasterRecommendation)
    if status:
        q = q.filter(models.MasterRecommendation.status == status)
    if severity:
        q = q.filter(models.MasterRecommendation.severity == severity)
    return q.order_by(models.MasterRecommendation.created_at.desc()).limit(limit).all()


@app.put("/master-recommendations/{rec_id}/approve", tags=["commander"])
def approve_master_recommendation(rec_id: int, db: Session = Depends(get_db),
                                   admin: models.User = Depends(get_admin_user)):
    rec = db.get(models.MasterRecommendation, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    rec.admin_approved = True
    rec.status = "admin_approved"
    db.commit()
    return {"status": "approved", "rec_id": rec_id}


# ── Audit Logs ────────────────────────────────────────────────────────────────

@app.get("/audit-logs", response_model=List[schemas.AuditLogOut], tags=["audit"])
def list_audit_logs(
    business_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    q = db.query(models.AuditLog)
    if business_id:
        q = q.filter(models.AuditLog.business_id == business_id)
    if entity_type:
        q = q.filter(models.AuditLog.entity_type == entity_type)
    return q.order_by(models.AuditLog.created_at.desc()).offset(skip).limit(limit).all()


# ── Commander Future Agent Blueprint ─────────────────────────────────────────

@app.post("/commander/future-agent-blueprint", tags=["commander"])
async def future_agent_blueprint(
    payload: schemas.FutureAgentBlueprintRequest,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    """Generate a detailed future agent blueprint using Commander AI."""
    from .commander import create_future_agent_blueprint
    return await create_future_agent_blueprint(
        requested_agent=payload.requested_agent,
        purpose=payload.purpose,
        required_tools=payload.required_tools or [],
        data_inputs=payload.data_inputs or [],
        data_outputs=payload.data_outputs or [],
        db=db,
        requested_by_id=admin.id,
    )


# ── Data Entry Stats ──────────────────────────────────────────────────────────

@app.get("/data-entry/stats", tags=["data_entry"])
def data_entry_stats(db: Session = Depends(get_db)):
    """Dashboard stats for the Data Entry AI module."""
    try:
        return {
            "total_documents":        db.query(models.UploadedDocument).count(),
            "pending_jobs":           db.query(models.DataEntryJob).filter(
                                          models.DataEntryJob.status == "pending_admin_approval").count(),
            "approved_jobs":          db.query(models.DataEntryJob).filter(
                                          models.DataEntryJob.admin_approved == True).count(),
            "declined_jobs":          db.query(models.DataEntryJob).filter(
                                          models.DataEntryJob.status == "declined_needs_revision").count(),
            "total_patients":         db.query(models.Patient).count(),
            "total_equipment_requests": db.query(models.EquipmentRequest).count(),
            "pending_bookkeeping":    db.query(models.BookkeepingEntry).filter(
                                          models.BookkeepingEntry.status == "draft").count(),
            "approved_bookkeeping":   db.query(models.BookkeepingEntry).filter(
                                          models.BookkeepingEntry.admin_approved == True).count(),
            "master_recommendations": db.query(models.MasterRecommendation).filter(
                                          models.MasterRecommendation.status == "pending_admin_review").count(),
        }
    except Exception as e:
        return {"error": str(e)}
