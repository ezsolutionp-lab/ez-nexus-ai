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
from .ai_agent import analyze_transcript, generate_content, build_website_html, hunt_products, build_listing
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

# Seed dropship directory on first run
with SessionLocal() as _seed_db:
    from .dropship_seed import seed_dropship_directory
    _n = seed_dropship_directory(_seed_db)
    if _n:
        logger.info("Seeded %d dropship directory entries", _n)

app = FastAPI(
    title="EZ-NEXUS AI Platform",
    description="Your AI Workforce for Business Growth™",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow all origins (JWT in headers, no cookies needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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


# ── AI Content Generation ────────────────────────────────────────────────────

@app.post("/ai/generate-content", response_model=schemas.ContentResponse, tags=["ai"])
def ai_generate_content(payload: schemas.ContentRequest):
    result = generate_content(
        content_type=payload.content_type,
        topic=payload.topic,
        brand_voice=payload.brand_voice,
        target_audience=payload.target_audience,
        keywords=payload.keywords,
    )
    return schemas.ContentResponse(**result)


# ── AI Website Builder ────────────────────────────────────────────────────────

@app.post("/ai/build-website", response_model=schemas.WebsiteResponse, tags=["ai"])
def ai_build_website(payload: schemas.WebsiteRequest):
    html = build_website_html(
        business_name=payload.business_name,
        industry=payload.industry,
        tagline=payload.tagline,
        description=payload.description,
        services=payload.services,
        phone=payload.phone,
        email=payload.email,
        address=payload.address,
        color_theme=payload.color_theme,
    )
    return schemas.WebsiteResponse(html=html)


# ── Invoice Endpoints ────────────────────────────────────────────────────────

@app.post("/invoices", response_model=schemas.InvoiceOut, status_code=201, tags=["invoices"])
def create_invoice(payload: schemas.InvoiceCreate, db: Session = Depends(get_db)):
    import json as _json
    count = db.query(models.Invoice).count() + 1
    invoice_number = f"INV-{datetime.utcnow().year}-{count:04d}"
    items = payload.items or []
    subtotal   = sum(it.quantity * it.unit_price for it in items)
    tax_amount = subtotal * (payload.tax_rate / 100)
    total      = subtotal + tax_amount
    inv = models.Invoice(
        business_id    = payload.business_id,
        invoice_number = invoice_number,
        client_name    = payload.client_name,
        client_email   = payload.client_email,
        client_phone   = payload.client_phone,
        client_address = payload.client_address,
        due_date       = payload.due_date,
        items          = _json.dumps([it.model_dump() for it in items]),
        subtotal       = subtotal,
        tax_rate       = payload.tax_rate,
        tax_amount     = tax_amount,
        total          = total,
        notes          = payload.notes,
    )
    db.add(inv); db.commit(); db.refresh(inv)
    return inv


@app.get("/invoices", response_model=List[schemas.InvoiceOut], tags=["invoices"])
def list_invoices(
    business_id: Optional[int] = None,
    status:      Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.Invoice)
    if business_id:
        q = q.filter(models.Invoice.business_id == business_id)
    if status:
        q = q.filter(models.Invoice.status == status)
    return q.order_by(models.Invoice.created_at.desc()).all()


@app.put("/invoices/{invoice_id}", response_model=schemas.InvoiceOut, tags=["invoices"])
def update_invoice(invoice_id: int, payload: schemas.InvoiceUpdate, db: Session = Depends(get_db)):
    inv = db.get(models.Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(inv, field, value)
    db.commit(); db.refresh(inv)
    return inv


@app.delete("/invoices/{invoice_id}", tags=["invoices"])
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    inv = db.get(models.Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    db.delete(inv); db.commit()
    return {"detail": f"Invoice {invoice_id} deleted."}


# ═══════════════════════════════════════════════════════════════════════════════
# E-COMMERCE / PRODUCT HUNTING MODULE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/ecom/hunt", response_model=schemas.ProductHuntResponse, tags=["ecommerce"])
def ecom_hunt_products(payload: schemas.ProductHuntRequest):
    """AI hunts for winning product opportunities in the specified category."""
    result = hunt_products(
        category=payload.category,
        marketplace=payload.marketplace,
        keywords=payload.keywords,
        budget=payload.budget,
    )
    return schemas.ProductHuntResponse(**result)


@app.post("/ecom/products", response_model=schemas.EcomProductOut, status_code=201, tags=["ecommerce"])
def create_ecom_product(payload: schemas.EcomProductCreate, db: Session = Depends(get_db)):
    product = models.EcomProduct(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.get("/ecom/products", response_model=List[schemas.EcomProductOut], tags=["ecommerce"])
def list_ecom_products(
    business_id: Optional[int] = None,
    status:      Optional[str] = None,
    marketplace: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(models.EcomProduct)
    if business_id:
        q = q.filter(models.EcomProduct.business_id == business_id)
    if status:
        q = q.filter(models.EcomProduct.status == status)
    if marketplace:
        q = q.filter(models.EcomProduct.marketplace == marketplace)
    return q.order_by(models.EcomProduct.ai_score.desc()).offset(skip).limit(limit).all()


@app.put("/ecom/products/{product_id}", response_model=schemas.EcomProductOut, tags=["ecommerce"])
def update_ecom_product(product_id: int, payload: schemas.EcomProductUpdate, db: Session = Depends(get_db)):
    p = db.get(models.EcomProduct, product_id)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@app.delete("/ecom/products/{product_id}", tags=["ecommerce"])
def delete_ecom_product(product_id: int, db: Session = Depends(get_db)):
    p = db.get(models.EcomProduct, product_id)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")
    db.delete(p)
    db.commit()
    return {"detail": f"Product {product_id} deleted."}


@app.post("/ecom/suppliers", response_model=schemas.EcomSupplierOut, status_code=201, tags=["ecommerce"])
def create_ecom_supplier(payload: schemas.EcomSupplierCreate, db: Session = Depends(get_db)):
    s = models.EcomSupplier(**payload.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@app.get("/ecom/suppliers", response_model=List[schemas.EcomSupplierOut], tags=["ecommerce"])
def list_ecom_suppliers(product_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.EcomSupplier)
    if product_id:
        q = q.filter(models.EcomSupplier.product_id == product_id)
    return q.order_by(models.EcomSupplier.rating.desc()).all()


@app.post("/ecom/listings/build", response_model=schemas.ListingBuildResponse, tags=["ecommerce"])
def ecom_build_listing(payload: schemas.ListingBuildRequest):
    result = build_listing(
        marketplace=payload.marketplace,
        product_name=payload.product_name,
        features=payload.features,
        target_audience=payload.target_audience,
        keywords=payload.keywords,
        brand_voice=payload.brand_voice,
    )
    return schemas.ListingBuildResponse(**result)


@app.post("/ecom/listings", response_model=schemas.EcomListingOut, status_code=201, tags=["ecommerce"])
def create_ecom_listing(payload: schemas.EcomListingCreate, db: Session = Depends(get_db)):
    listing = models.EcomListing(**payload.model_dump())
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


@app.get("/ecom/listings", response_model=List[schemas.EcomListingOut], tags=["ecommerce"])
def list_ecom_listings(
    business_id: Optional[int] = None,
    status:      Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.EcomListing)
    if business_id:
        q = q.filter(models.EcomListing.business_id == business_id)
    if status:
        q = q.filter(models.EcomListing.status == status)
    return q.order_by(models.EcomListing.created_at.desc()).all()


@app.put("/ecom/listings/{listing_id}", tags=["ecommerce"])
def update_ecom_listing_status(listing_id: int, status: str, db: Session = Depends(get_db)):
    listing = db.get(models.EcomListing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")
    listing.status = status
    db.commit()
    return {"detail": "Updated.", "status": status}


@app.post("/ecom/profit-calc", response_model=schemas.ProfitCalcResponse, tags=["ecommerce"])
def ecom_profit_calc(payload: schemas.ProfitCalcRequest):
    total_cost = (
        payload.product_cost + payload.marketplace_fee + payload.shipping_cost +
        payload.packaging_cost + payload.advertising_cost + payload.return_allowance + payload.other_costs
    )
    net_profit = payload.selling_price - total_cost
    roi = (net_profit / payload.product_cost * 100) if payload.product_cost > 0 else 0.0
    margin = (net_profit / payload.selling_price * 100) if payload.selling_price > 0 else 0.0
    break_even = total_cost
    return schemas.ProfitCalcResponse(
        selling_price=round(payload.selling_price, 2),
        total_cost=round(total_cost, 2),
        net_profit=round(net_profit, 2),
        roi_percent=round(roi, 1),
        margin_percent=round(margin, 1),
        break_even=round(break_even, 2),
    )


@app.get("/ecom/dropship-directory", response_model=List[schemas.DropshipDirectoryOut], tags=["ecommerce"])
def list_dropship_directory(
    region:        Optional[str] = None,
    platform_type: Optional[str] = None,
    has_usa_warehouse: Optional[bool] = None,
    dropship_ready:    Optional[bool] = None,
    search:        Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Browse the pre-seeded dropship/wholesale supplier directory."""
    q = db.query(models.DropshipDirectory).filter(models.DropshipDirectory.is_active == True)
    if region:
        q = q.filter(models.DropshipDirectory.region.ilike(region))
    if platform_type:
        q = q.filter(models.DropshipDirectory.platform_type.ilike(platform_type))
    if has_usa_warehouse is not None:
        q = q.filter(models.DropshipDirectory.has_usa_warehouse == has_usa_warehouse)
    if dropship_ready is not None:
        q = q.filter(models.DropshipDirectory.dropship_ready == dropship_ready)
    if search:
        like = f"%{search}%"
        q = q.filter(
            models.DropshipDirectory.name.ilike(like) |
            models.DropshipDirectory.categories.ilike(like) |
            models.DropshipDirectory.description.ilike(like)
        )
    return q.order_by(models.DropshipDirectory.rating.desc()).offset(skip).limit(limit).all()


@app.get("/ecom/dropship-directory/{supplier_id}", response_model=schemas.DropshipDirectoryOut, tags=["ecommerce"])
def get_dropship_supplier(supplier_id: int, db: Session = Depends(get_db)):
    s = db.get(models.DropshipDirectory, supplier_id)
    if not s:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    return s


@app.get("/ecom/stats", tags=["ecommerce"])
def ecom_stats(db: Session = Depends(get_db)):
    from sqlalchemy import func as sqlfunc
    return {
        "total_products":  db.query(models.EcomProduct).count(),
        "approved":        db.query(models.EcomProduct).filter(models.EcomProduct.status == "approved").count(),
        "listed":          db.query(models.EcomProduct).filter(models.EcomProduct.status == "listed").count(),
        "total_listings":  db.query(models.EcomListing).count(),
        "total_suppliers": db.query(models.EcomSupplier).count(),
        "avg_ai_score":    round(float(db.query(sqlfunc.avg(models.EcomProduct.ai_score)).scalar() or 0), 1),
    }


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


# ── Video Ad Generator ────────────────────────────────────────────────────────

@app.post("/video/generate", tags=["video"])
async def generate_video(
    brand_name: str = Form(...),
    script: str = Form(...),
    palette: str = Form("dark_blue"),
    topic: str = Form(""),
):
    """Generate a full MP4 video ad from a script using AI scene planning."""
    import json, asyncio
    from .services.video_generator import generate_video_ad

    # Use Claude to break the script into video scenes
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        prompt = (
            f"Break this ad script into exactly 5 video scenes for brand '{brand_name}'. Topic: {topic or script[:100]}\n\n"
            f"Script: {script}\n\n"
            f"Return ONLY a JSON array of 5 objects, each with:\n"
            f"- tag: string (Hook/Problem/Solution/Proof/CTA)\n"
            f"- headline: string (max 8 words, punchy)\n"
            f"- subtext: string (max 15 words supporting text)\n"
            f"- narration: string (what AI voice will say, 1-2 sentences)\n"
            f"- duration: number (3-5 seconds)\n"
            f"- is_cta: boolean (true only for last scene)\n"
            f"- cta_text: string (e.g. 'Shop Now', 'Learn More', only for last scene)\n"
            f"Return ONLY the JSON array, no other text."
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        scenes_text = msg.content[0].text.strip()
        # Extract JSON array from response
        start = scenes_text.find('[')
        end = scenes_text.rfind(']') + 1
        scenes = json.loads(scenes_text[start:end])
    except Exception as e:
        logger.warning("Claude scene planning failed, using default scenes: %s", e)
        # Fallback scenes
        words = script.split()
        scenes = [
            {"tag": "Hook",     "headline": " ".join(words[:6]) if len(words) >= 6 else script[:40], "subtext": "Get ready to transform your business", "narration": script[:120], "duration": 4, "is_cta": False},
            {"tag": "Problem",  "headline": "Struggling to grow?", "subtext": "You're not alone — we've been there", "narration": "Many businesses face the same challenges every day.", "duration": 3, "is_cta": False},
            {"tag": "Solution", "headline": f"{brand_name} has the answer", "subtext": "AI-powered tools built for your success", "narration": f"{brand_name} provides everything you need to succeed.", "duration": 4, "is_cta": False},
            {"tag": "Proof",    "headline": "Results that speak", "subtext": "Trusted by thousands of businesses", "narration": "Our customers see real results from day one.", "duration": 3, "is_cta": False},
            {"tag": "CTA",      "headline": "Start today", "subtext": "Join thousands of successful businesses", "narration": f"Visit {brand_name} now and start your free trial.", "duration": 4, "is_cta": True, "cta_text": "Get Started Free"},
        ]

    # Generate the video
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: __import__('asyncio').get_event_loop().run_until_complete(
                generate_video_ad(scenes, brand_name, palette)
            )
        )
    except Exception:
        import asyncio as _asyncio
        result = await _asyncio.to_thread(
            lambda: None
        )
        # Direct async call
        result = await generate_video_ad(scenes, brand_name, palette)

    return {
        "video_id": result["video_id"],
        "download_url": f"/video/download/{result['video_id']}",
        "scenes": result["scenes"],
        "status": result["status"],
        "message": f"Video ad generated with {result['scenes']} scenes!",
    }


@app.get("/video/download/{video_id}", tags=["video"])
def download_video(video_id: str):
    """Stream the generated MP4 video."""
    from pathlib import Path
    video_path = Path("generated_videos") / f"{video_id}.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found or expired.")
    return FileResponse(
        str(video_path),
        media_type="video/mp4",
        filename=f"ez_nexus_ad_{video_id}.mp4",
        headers={"Content-Disposition": f"attachment; filename=ez_nexus_ad_{video_id}.mp4"}
    )


@app.get("/video/stream/{video_id}", tags=["video"])
def stream_video(video_id: str):
    """Stream video for in-browser playback."""
    from pathlib import Path
    video_path = Path("generated_videos") / f"{video_id}.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found.")
    return FileResponse(str(video_path), media_type="video/mp4")


# ── Agent Dispatch ────────────────────────────────────────────────────────────

@app.get("/agents/roster", tags=["agents"])
def get_agent_roster():
    """List all agents with their registry key included."""
    from .agents import AGENT_REGISTRY
    return [{"key": key, **agent.to_dict()} for key, agent in AGENT_REGISTRY.items()]


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


# ═══════════════════════════════════════════════════════════════════════════════
# CRM & SALES MODULE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/crm/leads", response_model=schemas.LeadOut, status_code=201, tags=["crm"])
async def create_lead(payload: schemas.LeadCreate, db: Session = Depends(get_db)):
    from .agents import AGENT_REGISTRY
    lead = models.Lead(**payload.model_dump())
    db.add(lead)
    db.commit()
    db.refresh(lead)
    # AI lead scoring
    try:
        result = await AGENT_REGISTRY["sales"].run("score_lead", {
            "company": lead.company, "source": lead.source, "notes": lead.notes
        }, db)
        score_text = result.get("result", {}).get("score", "")
        import re
        nums = re.findall(r'\b(\d{1,3})\b', str(score_text))
        if nums:
            lead.score = min(100, int(nums[0]))
        lead.ai_notes = str(result.get("result", {}).get("notes", ""))
        db.commit()
        db.refresh(lead)
    except Exception:
        pass
    return lead


@app.get("/crm/leads", response_model=List[schemas.LeadOut], tags=["crm"])
def list_leads(business_id: Optional[int] = None, status: Optional[str] = None,
               skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(models.Lead)
    if business_id:
        q = q.filter(models.Lead.business_id == business_id)
    if status:
        q = q.filter(models.Lead.status == status)
    return q.order_by(models.Lead.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/crm/leads/{lead_id}", response_model=schemas.LeadOut, tags=["crm"])
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    return lead


@app.put("/crm/leads/{lead_id}", response_model=schemas.LeadOut, tags=["crm"])
def update_lead(lead_id: int, payload: schemas.LeadUpdate, db: Session = Depends(get_db)):
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(lead, k, v)
    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)
    return lead


@app.delete("/crm/leads/{lead_id}", tags=["crm"])
def delete_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    db.delete(lead)
    db.commit()
    return {"detail": f"Lead {lead_id} deleted."}


@app.post("/crm/pipelines", response_model=schemas.PipelineOut, status_code=201, tags=["crm"])
def create_pipeline(payload: schemas.PipelineCreate, db: Session = Depends(get_db)):
    pipeline = models.Pipeline(**payload.model_dump())
    db.add(pipeline)
    db.commit()
    db.refresh(pipeline)
    return pipeline


@app.get("/crm/pipelines", response_model=List[schemas.PipelineOut], tags=["crm"])
def list_pipelines(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.Pipeline)
    if business_id:
        q = q.filter(models.Pipeline.business_id == business_id)
    return q.all()


@app.post("/crm/deals", response_model=schemas.DealOut, status_code=201, tags=["crm"])
def create_deal(payload: schemas.DealCreate, db: Session = Depends(get_db)):
    deal = models.Deal(**payload.model_dump())
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal


@app.get("/crm/deals", response_model=List[schemas.DealOut], tags=["crm"])
def list_deals(business_id: Optional[int] = None, status: Optional[str] = None,
               skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(models.Deal)
    if business_id:
        q = q.filter(models.Deal.business_id == business_id)
    if status:
        q = q.filter(models.Deal.status == status)
    return q.order_by(models.Deal.created_at.desc()).offset(skip).limit(limit).all()


@app.put("/crm/deals/{deal_id}", response_model=schemas.DealOut, tags=["crm"])
def update_deal(deal_id: int, payload: schemas.DealUpdate, db: Session = Depends(get_db)):
    deal = db.get(models.Deal, deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(deal, k, v)
    deal.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(deal)
    return deal


@app.post("/crm/quotes", response_model=schemas.QuoteOut, status_code=201, tags=["crm"])
def create_quote(payload: schemas.QuoteCreate, db: Session = Depends(get_db)):
    import random
    quote = models.Quote(**payload.model_dump())
    quote.quote_number = f"QT-{datetime.utcnow().strftime('%Y%m')}-{random.randint(1000,9999)}"
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return quote


@app.get("/crm/quotes", response_model=List[schemas.QuoteOut], tags=["crm"])
def list_quotes(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.Quote)
    if business_id:
        q = q.filter(models.Quote.business_id == business_id)
    return q.order_by(models.Quote.created_at.desc()).limit(100).all()


@app.get("/crm/stats", tags=["crm"])
def crm_stats(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    q_leads = db.query(models.Lead)
    q_deals = db.query(models.Deal)
    q_quotes = db.query(models.Quote)
    if business_id:
        q_leads  = q_leads.filter(models.Lead.business_id == business_id)
        q_deals  = q_deals.filter(models.Deal.business_id == business_id)
        q_quotes = q_quotes.filter(models.Quote.business_id == business_id)

    from sqlalchemy import func as sqlfunc
    total_pipeline_value = db.query(sqlfunc.sum(models.Deal.value)).filter(
        models.Deal.status == "open").scalar() or 0.0
    won_value = db.query(sqlfunc.sum(models.Deal.value)).filter(
        models.Deal.status == "won").scalar() or 0.0

    return {
        "total_leads":      q_leads.count(),
        "new_leads":        q_leads.filter(models.Lead.status == "new").count(),
        "qualified_leads":  q_leads.filter(models.Lead.status == "qualified").count(),
        "converted_leads":  q_leads.filter(models.Lead.status == "converted").count(),
        "total_deals":      q_deals.count(),
        "open_deals":       q_deals.filter(models.Deal.status == "open").count(),
        "won_deals":        q_deals.filter(models.Deal.status == "won").count(),
        "pipeline_value":   round(float(total_pipeline_value), 2),
        "won_value":        round(float(won_value), 2),
        "total_quotes":     q_quotes.count(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RECRUITMENT & STAFFING MODULE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/recruitment/jobs", response_model=schemas.JobPostingOut, status_code=201, tags=["recruitment"])
async def create_job_posting(payload: schemas.JobPostingCreate, db: Session = Depends(get_db)):
    from .agents import AGENT_REGISTRY
    job = models.JobPosting(**payload.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    # AI-generate optimized job description
    try:
        result = await AGENT_REGISTRY["recruitment"].run("generate_job_description", {
            "title": job.title,
            "department": job.department or "",
            "requirements": job.requirements or "",
            "salary": f"{job.salary_currency} {job.salary_min}-{job.salary_max}" if job.salary_min else "Competitive",
        }, db)
        job.ai_description = result.get("result", {}).get("job_description", "")
        db.commit()
        db.refresh(job)
    except Exception:
        pass
    return job


@app.get("/recruitment/jobs", response_model=List[schemas.JobPostingOut], tags=["recruitment"])
def list_job_postings(business_id: Optional[int] = None, status: Optional[str] = None,
                      skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(models.JobPosting)
    if business_id:
        q = q.filter(models.JobPosting.business_id == business_id)
    if status:
        q = q.filter(models.JobPosting.status == status)
    return q.order_by(models.JobPosting.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/recruitment/jobs/{job_id}", response_model=schemas.JobPostingOut, tags=["recruitment"])
def get_job_posting(job_id: int, db: Session = Depends(get_db)):
    job = db.get(models.JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found.")
    return job


@app.put("/recruitment/jobs/{job_id}", response_model=schemas.JobPostingOut, tags=["recruitment"])
def update_job_posting(job_id: int, payload: schemas.JobPostingUpdate, db: Session = Depends(get_db)):
    job = db.get(models.JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(job, k, v)
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job


@app.post("/recruitment/candidates", response_model=schemas.CandidateOut, status_code=201, tags=["recruitment"])
def create_candidate(payload: schemas.CandidateCreate, db: Session = Depends(get_db)):
    candidate = models.Candidate(**payload.model_dump())
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


@app.get("/recruitment/candidates", response_model=List[schemas.CandidateOut], tags=["recruitment"])
def list_candidates(business_id: Optional[int] = None, status: Optional[str] = None,
                    skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(models.Candidate)
    if business_id:
        q = q.filter(models.Candidate.business_id == business_id)
    if status:
        q = q.filter(models.Candidate.status == status)
    return q.order_by(models.Candidate.created_at.desc()).offset(skip).limit(limit).all()


@app.post("/recruitment/applications", response_model=schemas.JobApplicationOut, status_code=201, tags=["recruitment"])
async def create_application(payload: schemas.JobApplicationCreate, db: Session = Depends(get_db)):
    from .agents import AGENT_REGISTRY
    job = db.get(models.JobPosting, payload.job_posting_id)
    candidate = db.get(models.Candidate, payload.candidate_id)
    if not job or not candidate:
        raise HTTPException(status_code=404, detail="Job or candidate not found.")
    app_obj = models.JobApplication(**payload.model_dump())
    db.add(app_obj)
    db.commit()
    db.refresh(app_obj)
    # AI match scoring
    try:
        result = await AGENT_REGISTRY["recruitment"].run("screen_resume", {
            "job_title": job.title,
            "requirements": job.requirements or "",
            "resume_text": candidate.resume_text or f"Skills: {candidate.skills or ''}, Experience: {candidate.experience_years or 0} years",
        }, db)
        screening = result.get("result", {}).get("screening", "")
        import re
        scores = re.findall(r'(\d{1,3})/100|\bscore[:\s]+(\d{1,3})\b', screening, re.IGNORECASE)
        if scores:
            s = next((x for x in scores[0] if x), None)
            if s:
                app_obj.ai_match_score = min(100.0, float(s))
        app_obj.ai_feedback = screening
        db.commit()
        db.refresh(app_obj)
    except Exception:
        pass
    return app_obj


@app.get("/recruitment/applications", response_model=List[schemas.JobApplicationOut], tags=["recruitment"])
def list_applications(business_id: Optional[int] = None, job_posting_id: Optional[int] = None,
                      skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(models.JobApplication)
    if business_id:
        q = q.filter(models.JobApplication.business_id == business_id)
    if job_posting_id:
        q = q.filter(models.JobApplication.job_posting_id == job_posting_id)
    return q.order_by(models.JobApplication.ai_match_score.desc()).offset(skip).limit(limit).all()


@app.put("/recruitment/applications/{app_id}", response_model=schemas.JobApplicationOut, tags=["recruitment"])
def update_application(app_id: int, payload: schemas.JobApplicationUpdate, db: Session = Depends(get_db)):
    app_obj = db.get(models.JobApplication, app_id)
    if not app_obj:
        raise HTTPException(status_code=404, detail="Application not found.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(app_obj, k, v)
    app_obj.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(app_obj)
    return app_obj


@app.get("/recruitment/stats", tags=["recruitment"])
def recruitment_stats(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    qj = db.query(models.JobPosting)
    qc = db.query(models.Candidate)
    qa = db.query(models.JobApplication)
    if business_id:
        qj = qj.filter(models.JobPosting.business_id == business_id)
        qc = qc.filter(models.Candidate.business_id == business_id)
        qa = qa.filter(models.JobApplication.business_id == business_id)
    return {
        "total_jobs":         qj.count(),
        "active_jobs":        qj.filter(models.JobPosting.status == "active").count(),
        "total_candidates":   qc.count(),
        "total_applications": qa.count(),
        "in_interview":       qa.filter(models.JobApplication.stage == "interview").count(),
        "offers_sent":        qa.filter(models.JobApplication.stage == "offer").count(),
        "hired":              qa.filter(models.JobApplication.stage == "hired").count(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MARKETING SUITE MODULE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/marketing/campaigns", response_model=schemas.CampaignOut, status_code=201, tags=["marketing"])
async def create_campaign(payload: schemas.CampaignCreate, db: Session = Depends(get_db)):
    from .agents import AGENT_REGISTRY
    campaign = models.Campaign(**payload.model_dump())
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    # AI-generate body if not provided
    if not campaign.body:
        try:
            result = await AGENT_REGISTRY["marketing"].run("create_content", {
                "campaign_name": campaign.name,
                "campaign_type": campaign.campaign_type,
                "subject": campaign.subject or "",
                "target": campaign.target_segment or "customers",
            }, db)
            campaign.ai_generated_body = result.get("result", {}).get("content", "")
            db.commit()
            db.refresh(campaign)
        except Exception:
            pass
    return campaign


@app.get("/marketing/campaigns", response_model=List[schemas.CampaignOut], tags=["marketing"])
def list_campaigns(business_id: Optional[int] = None, status: Optional[str] = None,
                   skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(models.Campaign)
    if business_id:
        q = q.filter(models.Campaign.business_id == business_id)
    if status:
        q = q.filter(models.Campaign.status == status)
    return q.order_by(models.Campaign.created_at.desc()).offset(skip).limit(limit).all()


@app.put("/marketing/campaigns/{campaign_id}", response_model=schemas.CampaignOut, tags=["marketing"])
def update_campaign(campaign_id: int, payload: schemas.CampaignUpdate, db: Session = Depends(get_db)):
    campaign = db.get(models.Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(campaign, k, v)
    campaign.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(campaign)
    return campaign


@app.post("/marketing/campaigns/{campaign_id}/launch", tags=["marketing"])
def launch_campaign(campaign_id: int, db: Session = Depends(get_db),
                    admin: models.User = Depends(get_admin_user)):
    campaign = db.get(models.Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    campaign.status = "active"
    campaign.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "launched", "campaign_id": campaign_id}


@app.post("/marketing/forms", response_model=schemas.MarketingFormOut, status_code=201, tags=["marketing"])
def create_marketing_form(payload: schemas.MarketingFormCreate, db: Session = Depends(get_db)):
    form = models.MarketingForm(**payload.model_dump())
    db.add(form)
    db.commit()
    db.refresh(form)
    return form


@app.get("/marketing/forms", response_model=List[schemas.MarketingFormOut], tags=["marketing"])
def list_marketing_forms(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.MarketingForm)
    if business_id:
        q = q.filter(models.MarketingForm.business_id == business_id)
    return q.order_by(models.MarketingForm.created_at.desc()).all()


@app.post("/marketing/forms/{form_id}/submit", response_model=schemas.FormSubmissionOut, status_code=201, tags=["marketing"])
def submit_form(form_id: int, payload: schemas.FormSubmissionCreate,
                request: Request, db: Session = Depends(get_db)):
    form = db.get(models.MarketingForm, form_id)
    if not form or not form.is_active:
        raise HTTPException(status_code=404, detail="Form not found or inactive.")
    sub = models.FormSubmission(
        form_id=form_id,
        business_id=payload.business_id,
        data_json=payload.data_json,
        ip_address=request.client.host if request.client else None,
        source_url=payload.source_url,
    )
    db.add(sub)
    form.submission_count = (form.submission_count or 0) + 1
    db.commit()
    db.refresh(sub)
    return sub


@app.get("/marketing/forms/{form_id}/submissions", response_model=List[schemas.FormSubmissionOut], tags=["marketing"])
def list_form_submissions(form_id: int, db: Session = Depends(get_db)):
    return db.query(models.FormSubmission).filter(
        models.FormSubmission.form_id == form_id
    ).order_by(models.FormSubmission.created_at.desc()).limit(200).all()


@app.get("/marketing/stats", tags=["marketing"])
def marketing_stats(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    qc = db.query(models.Campaign)
    qf = db.query(models.MarketingForm)
    if business_id:
        qc = qc.filter(models.Campaign.business_id == business_id)
        qf = qf.filter(models.MarketingForm.business_id == business_id)
    from sqlalchemy import func as sqlfunc
    sent = db.query(sqlfunc.sum(models.Campaign.sent_count)).scalar() or 0
    opens = db.query(sqlfunc.sum(models.Campaign.open_count)).scalar() or 0
    return {
        "total_campaigns":  qc.count(),
        "active_campaigns": qc.filter(models.Campaign.status == "active").count(),
        "total_sent":       int(sent),
        "total_opens":      int(opens),
        "open_rate_pct":    round(100 * opens / sent, 1) if sent > 0 else 0.0,
        "total_forms":      qf.count(),
        "total_submissions": db.query(models.FormSubmission).count(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# COMMUNICATION HUB MODULE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/comm-hub/ivr", response_model=schemas.IVRConfigOut, status_code=201, tags=["comm_hub"])
async def create_ivr_config(payload: schemas.IVRConfigCreate, db: Session = Depends(get_db)):
    from .agents import AGENT_REGISTRY
    ivr = models.IVRConfig(**payload.model_dump())
    db.add(ivr)
    db.commit()
    db.refresh(ivr)
    # AI-generate greeting if not provided
    if not ivr.greeting_text:
        try:
            biz = db.query(models.Business).filter(
                models.Business.id == ivr.business_id).first()
            result = await AGENT_REGISTRY["voice"].run("generate_greeting", {
                "business_name": biz.name if biz else "our company",
                "tone": "professional and friendly",
            }, db)
            ivr.greeting_text = result.get("result", {}).get("greeting_script", "")
            db.commit()
            db.refresh(ivr)
        except Exception:
            pass
    return ivr


@app.get("/comm-hub/ivr", response_model=List[schemas.IVRConfigOut], tags=["comm_hub"])
def list_ivr_configs(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.IVRConfig)
    if business_id:
        q = q.filter(models.IVRConfig.business_id == business_id)
    return q.all()


@app.put("/comm-hub/ivr/{ivr_id}", response_model=schemas.IVRConfigOut, tags=["comm_hub"])
def update_ivr_config(ivr_id: int, payload: schemas.IVRConfigCreate, db: Session = Depends(get_db)):
    ivr = db.get(models.IVRConfig, ivr_id)
    if not ivr:
        raise HTTPException(status_code=404, detail="IVR config not found.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(ivr, k, v)
    db.commit()
    db.refresh(ivr)
    return ivr


@app.post("/comm-hub/phone-numbers", response_model=schemas.PhoneNumberOut, status_code=201, tags=["comm_hub"])
def create_phone_number(payload: schemas.PhoneNumberCreate, db: Session = Depends(get_db)):
    pn = models.PhoneNumber(**payload.model_dump())
    db.add(pn)
    db.commit()
    db.refresh(pn)
    return pn


@app.get("/comm-hub/phone-numbers", response_model=List[schemas.PhoneNumberOut], tags=["comm_hub"])
def list_phone_numbers(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.PhoneNumber)
    if business_id:
        q = q.filter(models.PhoneNumber.business_id == business_id)
    return q.filter(models.PhoneNumber.is_active == True).all()


@app.post("/comm-hub/generate-ivr-menu", tags=["comm_hub"])
async def generate_ivr_menu(payload: dict, db: Session = Depends(get_db)):
    from .agents import AGENT_REGISTRY
    result = await AGENT_REGISTRY["voice"].run("generate_ivr_menu", payload, db)
    return result.get("result", result)


# ═══════════════════════════════════════════════════════════════════════════════
# CALLTRACK AI MODULE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/calltrack/numbers", response_model=schemas.CallTrackingNumberOut, status_code=201, tags=["calltrack"])
def create_tracking_number(payload: schemas.CallTrackingNumberCreate, db: Session = Depends(get_db)):
    tn = models.CallTrackingNumber(**payload.model_dump())
    db.add(tn)
    db.commit()
    db.refresh(tn)
    return tn


@app.get("/calltrack/numbers", response_model=List[schemas.CallTrackingNumberOut], tags=["calltrack"])
def list_tracking_numbers(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.CallTrackingNumber)
    if business_id:
        q = q.filter(models.CallTrackingNumber.business_id == business_id)
    return q.filter(models.CallTrackingNumber.is_active == True).all()


@app.post("/calltrack/events", response_model=schemas.CallTrackingEventOut, status_code=201, tags=["calltrack"])
async def log_tracking_event(payload: schemas.CallTrackingEventCreate, db: Session = Depends(get_db)):
    from .agents import AGENT_REGISTRY
    event = models.CallTrackingEvent(**payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    # Update tracking number counts
    if event.tracking_number_id:
        tn = db.get(models.CallTrackingNumber, event.tracking_number_id)
        if tn:
            tn.total_calls = (tn.total_calls or 0) + 1
            if event.is_conversion:
                tn.conversions = (tn.conversions or 0) + 1
            db.commit()
    return event


@app.get("/calltrack/events", response_model=List[schemas.CallTrackingEventOut], tags=["calltrack"])
def list_tracking_events(business_id: Optional[int] = None, skip: int = 0,
                         limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(models.CallTrackingEvent)
    if business_id:
        q = q.filter(models.CallTrackingEvent.business_id == business_id)
    return q.order_by(models.CallTrackingEvent.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/calltrack/analytics", tags=["calltrack"])
def calltrack_analytics(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    qn = db.query(models.CallTrackingNumber)
    qe = db.query(models.CallTrackingEvent)
    if business_id:
        qn = qn.filter(models.CallTrackingNumber.business_id == business_id)
        qe = qe.filter(models.CallTrackingEvent.business_id == business_id)
    from sqlalchemy import func as sqlfunc
    total_calls = qe.count()
    conversions = qe.filter(models.CallTrackingEvent.is_conversion == True).count()
    avg_duration = db.query(sqlfunc.avg(models.CallTrackingEvent.call_duration_secs)).scalar() or 0
    revenue = db.query(sqlfunc.sum(models.CallTrackingEvent.revenue_attributed)).scalar() or 0
    return {
        "total_tracking_numbers": qn.count(),
        "total_calls":            total_calls,
        "total_conversions":      conversions,
        "conversion_rate_pct":    round(100 * conversions / total_calls, 1) if total_calls > 0 else 0.0,
        "avg_call_duration_secs": round(float(avg_duration), 1),
        "total_revenue_attributed": round(float(revenue), 2),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CONTACT CENTER MODULE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/contact-center/queues", response_model=schemas.AgentQueueOut, status_code=201, tags=["contact_center"])
def create_queue(payload: schemas.AgentQueueCreate, db: Session = Depends(get_db)):
    queue = models.AgentQueue(**payload.model_dump())
    db.add(queue)
    db.commit()
    db.refresh(queue)
    return queue


@app.get("/contact-center/queues", response_model=List[schemas.AgentQueueOut], tags=["contact_center"])
def list_queues(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.AgentQueue)
    if business_id:
        q = q.filter(models.AgentQueue.business_id == business_id)
    return q.filter(models.AgentQueue.is_active == True).all()


@app.put("/contact-center/queues/{queue_id}", tags=["contact_center"])
def update_queue(queue_id: int, payload: schemas.AgentQueueCreate, db: Session = Depends(get_db)):
    queue = db.get(models.AgentQueue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(queue, k, v)
    db.commit()
    return {"detail": "Queue updated."}


@app.post("/contact-center/support-ticket", tags=["contact_center"])
async def resolve_support_ticket(payload: dict, db: Session = Depends(get_db)):
    from .agents import AGENT_REGISTRY
    result = await AGENT_REGISTRY["support"].run("resolve_ticket", payload, db)
    return result.get("result", result)


# ═══════════════════════════════════════════════════════════════════════════════
# AUTOMATION & WORKFLOW ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/automation/workflows", response_model=schemas.WorkflowOut, status_code=201, tags=["automation"])
def create_workflow(payload: schemas.WorkflowCreate, db: Session = Depends(get_db)):
    wf = models.Workflow(**payload.model_dump())
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@app.get("/automation/workflows", response_model=List[schemas.WorkflowOut], tags=["automation"])
def list_workflows(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.Workflow)
    if business_id:
        q = q.filter(models.Workflow.business_id == business_id)
    return q.order_by(models.Workflow.created_at.desc()).all()


@app.put("/automation/workflows/{wf_id}", response_model=schemas.WorkflowOut, tags=["automation"])
def update_workflow(wf_id: int, payload: schemas.WorkflowUpdate, db: Session = Depends(get_db)):
    wf = db.get(models.Workflow, wf_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(wf, k, v)
    wf.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(wf)
    return wf


@app.post("/automation/workflows/{wf_id}/run", tags=["automation"])
async def run_workflow(wf_id: int, trigger_data: Optional[dict] = None,
                       db: Session = Depends(get_db)):
    wf = db.get(models.Workflow, wf_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    if not wf.is_active:
        raise HTTPException(status_code=400, detail="Workflow is not active.")
    execution = models.WorkflowExecution(
        workflow_id=wf_id,
        business_id=wf.business_id,
        status="running",
        trigger_data=json.dumps(trigger_data or {}),
    )
    db.add(execution)
    wf.run_count = (wf.run_count or 0) + 1
    wf.last_run_at = datetime.utcnow()
    db.commit()
    db.refresh(execution)
    # Simulate step execution
    steps = json.loads(wf.steps or "[]")
    execution.steps_completed = len(steps)
    execution.status = "completed"
    execution.completed_at = datetime.utcnow()
    db.commit()
    return {"execution_id": execution.id, "status": "completed", "steps_run": len(steps)}


@app.get("/automation/executions", response_model=List[schemas.WorkflowExecutionOut], tags=["automation"])
def list_executions(business_id: Optional[int] = None, workflow_id: Optional[int] = None,
                    skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(models.WorkflowExecution)
    if business_id:
        q = q.filter(models.WorkflowExecution.business_id == business_id)
    if workflow_id:
        q = q.filter(models.WorkflowExecution.workflow_id == workflow_id)
    return q.order_by(models.WorkflowExecution.started_at.desc()).offset(skip).limit(limit).all()


@app.post("/automation/webhooks", response_model=schemas.WebhookConfigOut, status_code=201, tags=["automation"])
def create_webhook(payload: schemas.WebhookConfigCreate, db: Session = Depends(get_db)):
    wh = models.WebhookConfig(**payload.model_dump())
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


@app.get("/automation/webhooks", response_model=List[schemas.WebhookConfigOut], tags=["automation"])
def list_webhooks(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.WebhookConfig)
    if business_id:
        q = q.filter(models.WebhookConfig.business_id == business_id)
    return q.filter(models.WebhookConfig.is_active == True).all()


# ═══════════════════════════════════════════════════════════════════════════════
# SMARTBOSS AI — EXECUTIVE INTELLIGENCE DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/smartboss/overview", tags=["smartboss"])
def smartboss_overview(business_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Master business intelligence snapshot across all modules."""
    from sqlalchemy import func as sqlfunc

    def _filt(q, model):
        if business_id:
            return q.filter(getattr(model, "business_id", None) == business_id)
        return q

    total_revenue = db.query(sqlfunc.sum(models.Business.revenue)).scalar() or 0
    pipeline_val  = db.query(sqlfunc.sum(models.Deal.value)).filter(
        models.Deal.status == "open").scalar() or 0
    won_val       = db.query(sqlfunc.sum(models.Deal.value)).filter(
        models.Deal.status == "won").scalar() or 0

    return {
        "module": "SmartBoss AI Overview",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "crm": {
            "total_leads":      db.query(models.Lead).count(),
            "new_leads":        db.query(models.Lead).filter(models.Lead.status == "new").count(),
            "pipeline_value":   round(float(pipeline_val), 2),
            "won_value":        round(float(won_val), 2),
            "total_deals":      db.query(models.Deal).count(),
        },
        "recruitment": {
            "active_jobs":      db.query(models.JobPosting).filter(models.JobPosting.status == "active").count(),
            "total_candidates": db.query(models.Candidate).count(),
            "applications":     db.query(models.JobApplication).count(),
            "hired":            db.query(models.JobApplication).filter(models.JobApplication.stage == "hired").count(),
        },
        "marketing": {
            "active_campaigns": db.query(models.Campaign).filter(models.Campaign.status == "active").count(),
            "total_forms":      db.query(models.MarketingForm).count(),
            "form_submissions": db.query(models.FormSubmission).count(),
        },
        "operations": {
            "total_businesses":    db.query(models.Business).filter(models.Business.is_active == True).count(),
            "total_appointments":  db.query(models.Appointment).count(),
            "pending_approvals":   db.query(models.DataEntryJob).filter(
                                       models.DataEntryJob.status == "pending_admin_approval").count(),
            "total_patients":      db.query(models.Patient).count(),
            "total_calls":         db.query(models.CallLog).count(),
        },
        "revenue": {
            "total_business_revenue": round(float(total_revenue), 2),
            "bookkeeping_pending":    db.query(models.BookkeepingEntry).filter(
                                          models.BookkeepingEntry.status == "draft").count(),
        },
        "calltrack": {
            "tracking_numbers": db.query(models.CallTrackingNumber).count(),
            "tracked_calls":    db.query(models.CallTrackingEvent).count(),
            "conversions":      db.query(models.CallTrackingEvent).filter(
                                    models.CallTrackingEvent.is_conversion == True).count(),
        },
        "automation": {
            "workflows":        db.query(models.Workflow).count(),
            "active_workflows": db.query(models.Workflow).filter(models.Workflow.is_active == True).count(),
            "total_runs":       db.query(models.WorkflowExecution).count(),
        },
    }


@app.post("/smartboss/query", tags=["smartboss"])
async def smartboss_nl_query(payload: schemas.SmartBossQueryRequest, db: Session = Depends(get_db)):
    """Natural language Q&A powered by SmartBoss AI."""
    try:
        import anthropic, os
        overview = smartboss_overview(payload.business_id, db)
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=(
                "You are SmartBoss AI, an intelligent business analytics assistant for EZ-NEXUS AI Platform. "
                "Analyze the provided business data and answer the question with actionable insights. "
                "Be concise, data-driven, and recommend specific next steps."
            ),
            messages=[{
                "role": "user",
                "content": f"Business Data:\n{json.dumps(overview, indent=2)}\n\nQuestion: {payload.question}"
            }],
        )
        answer = msg.content[0].text
    except Exception as e:
        answer = f"SmartBoss AI is analyzing your data. (AI unavailable: {e})"
    return {"question": payload.question, "answer": answer, "data_snapshot": overview}


@app.get("/smartboss/insights", response_model=List[schemas.SmartBossInsightOut], tags=["smartboss"])
def list_smartboss_insights(business_id: Optional[int] = None, is_read: Optional[bool] = None,
                             limit: int = 20, db: Session = Depends(get_db)):
    q = db.query(models.SmartBossInsight)
    if business_id:
        q = q.filter(models.SmartBossInsight.business_id == business_id)
    if is_read is not None:
        q = q.filter(models.SmartBossInsight.is_read == is_read)
    return q.order_by(models.SmartBossInsight.created_at.desc()).limit(limit).all()


@app.post("/smartboss/insights/generate", tags=["smartboss"])
async def generate_smartboss_insights(business_id: Optional[int] = None,
                                       db: Session = Depends(get_db),
                                       admin: models.User = Depends(get_admin_user)):
    """AI-generate fresh SmartBoss insights based on current platform data."""
    overview = smartboss_overview(business_id, db)
    insights_created = []
    try:
        import anthropic, os
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system="You are SmartBoss AI. Generate 3-5 business insights as JSON array. Each: {type, title, summary, recommendation, priority}",
            messages=[{"role": "user", "content": f"Data: {json.dumps(overview)}"}],
        )
        import re
        raw = msg.content[0].text
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            items = json.loads(match.group())
            for item in items[:5]:
                insight = models.SmartBossInsight(
                    business_id=business_id,
                    insight_type=item.get("type", "operations"),
                    title=item.get("title", "Insight"),
                    summary=item.get("summary", ""),
                    recommendation=item.get("recommendation", ""),
                    priority=item.get("priority", "medium"),
                )
                db.add(insight)
                insights_created.append(item.get("title", ""))
        db.commit()
    except Exception as e:
        return {"error": str(e), "insights_created": 0}
    return {"insights_created": len(insights_created), "titles": insights_created}


@app.put("/smartboss/insights/{insight_id}/read", tags=["smartboss"])
def mark_insight_read(insight_id: int, db: Session = Depends(get_db)):
    insight = db.get(models.SmartBossInsight, insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found.")
    insight.is_read = True
    db.commit()
    return {"status": "read", "insight_id": insight_id}
