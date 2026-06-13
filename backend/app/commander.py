"""
EZ-NEXUS COMMANDER AI
Central intelligence layer — supervises all agents, monitors health,
generates new agent specs, and advises the admin.

Rule: Commander NEVER changes production systems without admin approval.
Flow: Detect → Suggest → Admin Approves → System Applies
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from . import models
from .config import settings

logger = logging.getLogger(__name__)


# ── Agent Roster ──────────────────────────────────────────────────────────────

AGENT_ROSTER = [
    {"id": "call-center",  "name": "Call Center Agent",     "icon": "🎧", "status": "active",      "tab": "call-center"},
    {"id": "appointment",  "name": "Appointment Agent",     "icon": "📅", "status": "active",      "tab": "appointments"},
    {"id": "sales",        "name": "Sales Agent",           "icon": "💼", "status": "active",      "tab": None},
    {"id": "billing",      "name": "Billing Support Agent", "icon": "💳", "status": "active",      "tab": None},
    {"id": "crm",          "name": "CRM Agent",             "icon": "👥", "status": "active",      "tab": "businesses"},
    {"id": "analytics",    "name": "Analytics Agent",       "icon": "📈", "status": "active",      "tab": "dashboard"},
    {"id": "website",      "name": "Website Builder Agent", "icon": "🖥️", "status": "coming_soon", "tab": None},
    {"id": "seo",          "name": "SEO Agent",             "icon": "🔍", "status": "coming_soon", "tab": None},
    {"id": "marketing",    "name": "Marketing Agent",       "icon": "📣", "status": "coming_soon", "tab": None},
    {"id": "video",        "name": "Video/Reel Agent",      "icon": "🎬", "status": "coming_soon", "tab": None},
    {"id": "content",      "name": "Content Writer Agent",  "icon": "✍️", "status": "coming_soon", "tab": None},
    {"id": "compliance",   "name": "Compliance Agent",      "icon": "⚖️", "status": "coming_soon", "tab": None},
    {"id": "qa",           "name": "QA Agent",              "icon": "🧪", "status": "coming_soon", "tab": None},
]


# ── System Health Check ───────────────────────────────────────────────────────

def run_health_check(db: Session) -> dict:
    """Run all system health checks. Returns status dict + list of alerts."""
    checks = {}
    alerts = []

    # ── Database
    try:
        biz_count  = db.query(models.Business).filter(models.Business.is_active == True).count()
        appt_count = db.query(models.Appointment).count()
        checks["database"] = {"status": "ok", "businesses": biz_count, "appointments": appt_count}
    except Exception as e:
        checks["database"] = {"status": "error", "message": str(e)}
        alerts.append({"severity": "critical", "module": "database",
                        "message": f"Database error: {e}"})

    # ── Pending approvals
    try:
        pending = db.query(models.Appointment).filter(
            models.Appointment.status == "pending_approval"
        ).count()
        checks["pending_approvals"] = {"status": "ok", "count": pending}
        if pending >= 5:
            alerts.append({"severity": "warning", "module": "appointments",
                            "message": f"{pending} appointments waiting for staff approval. Consider enabling auto-approval for faster service."})
    except Exception:
        checks["pending_approvals"] = {"status": "unknown", "count": 0}

    # ── Activity this week
    try:
        week_ago     = datetime.utcnow() - timedelta(days=7)
        recent_appts = db.query(models.Appointment).filter(
            models.Appointment.created_at >= week_ago
        ).count()
        checks["weekly_activity"] = {"status": "ok", "appointments_7d": recent_appts}
        if recent_appts > 50:
            alerts.append({"severity": "info", "module": "capacity",
                            "message": f"High activity: {recent_appts} appointments this week. You may want to upgrade your Twilio voice capacity."})
    except Exception:
        checks["weekly_activity"] = {"status": "unknown"}

    # ── Twilio
    if settings.twilio_configured:
        checks["twilio"] = {"status": "configured", "phone": settings.twilio_phone_number}
    else:
        checks["twilio"] = {"status": "not_configured"}
        alerts.append({"severity": "warning", "module": "twilio",
                        "message": "Twilio not configured. AI phone answering is disabled. Add TWILIO_* keys in .env to activate."})

    # ── SMTP email
    if settings.smtp_configured:
        checks["smtp_email"] = {"status": "configured"}
    else:
        checks["smtp_email"] = {"status": "not_configured"}
        alerts.append({"severity": "info", "module": "smtp",
                        "message": "SMTP email not configured. Appointment confirmation emails are disabled. Add SMTP_* keys in .env."})

    # ── AI (Claude)
    if settings.anthropic_api_key:
        checks["ai_engine"] = {"status": "configured", "model": "claude-haiku-4-5"}
    else:
        checks["ai_engine"] = {"status": "not_configured"}
        alerts.append({"severity": "warning", "module": "ai",
                        "message": "Anthropic API key missing. AI call analysis, Commander intelligence, and agent generation are disabled."})

    # ── Data entry queue
    try:
        pending_jobs  = db.query(models.DataEntryJob).filter(
            models.DataEntryJob.status == "pending_admin_approval"
        ).count()
        total_docs    = db.query(models.UploadedDocument).count()
        low_confidence = db.query(models.UploadedDocument).filter(
            models.UploadedDocument.confidence_score < 0.60
        ).count()
        checks["data_entry"] = {
            "status": "ok",
            "pending_approval_jobs": pending_jobs,
            "total_documents": total_docs,
            "low_confidence_docs": low_confidence,
        }
        if pending_jobs >= 10:
            alerts.append({"severity": "warning", "module": "data_entry",
                            "message": f"{pending_jobs} data entry jobs awaiting admin approval."})
        if low_confidence >= 5:
            alerts.append({"severity": "info", "module": "data_entry",
                            "message": f"{low_confidence} uploaded documents have low OCR confidence — manual review recommended."})
    except Exception:
        checks["data_entry"] = {"status": "unavailable"}

    # ── Unread alerts in DB
    try:
        unread = db.query(models.AdminAlert).filter(models.AdminAlert.is_read == False).count()
        checks["unread_alerts"] = {"count": unread}
    except Exception:
        checks["unread_alerts"] = {"count": 0}

    # Persist new alerts to DB
    for alert in alerts:
        try:
            db.add(models.AdminAlert(
                severity=alert["severity"],
                module=alert["module"],
                message=alert["message"],
            ))
        except Exception:
            pass
    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "checks": checks,
        "alerts": alerts,
        "agent_roster": AGENT_ROSTER,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


# ── Agent Spec Generator ──────────────────────────────────────────────────────

async def generate_agent_spec(description: str, db: Session, requested_by_id: Optional[int] = None) -> dict:
    """Use Claude Haiku to generate a complete new AI agent specification."""
    claude = _get_claude()
    spec = await _build_spec(description, claude)

    # Save to DB as draft
    try:
        record = models.AgentDefinition(
            name=spec.get("name", f"Custom Agent — {description[:40]}"),
            purpose=spec.get("purpose", description),
            spec_json=json.dumps(spec),
            status="draft",
            requested_by=requested_by_id,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        spec["agent_definition_id"] = record.id
    except Exception as e:
        logger.error(f"Failed to save agent definition: {e}")

    return spec


async def _build_spec(description: str, claude) -> dict:
    if not claude:
        return _fallback_spec(description)

    prompt = f"""You are EZ-NEXUS COMMANDER AI, generating a new AI agent specification for the admin.

Admin request: "{description}"

Generate a professional, complete agent specification. Return ONLY valid JSON (no markdown):
{{
  "name": "Agent name (e.g. 'Dental Insurance Verifier Agent')",
  "purpose": "2-3 sentence description of what this agent does and the business value it provides",
  "workflow": [
    "Step 1: ...",
    "Step 2: ...",
    "Step 3: ...",
    "Step 4: ...",
    "Step 5: ..."
  ],
  "required_tools": ["Tool name — what it does", "..."],
  "required_apis": ["API name (provider) — purpose", "..."],
  "database_fields": ["field_name: DataType — description", "..."],
  "call_script": "Complete greeting and conversation script the agent uses",
  "dashboard_widgets": ["Widget name — what data it shows", "..."],
  "approval_rules": ["Rule — when/how approvals are needed", "..."],
  "testing_checklist": ["Test scenario — expected outcome", "..."],
  "estimated_dev_days": 5,
  "complexity": "low|medium|high",
  "monthly_api_cost_estimate": "$X-$Y/month"
}}"""

    try:
        msg = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1800,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Agent spec generation error: {e}")
        return _fallback_spec(description)


def _fallback_spec(description: str) -> dict:
    return {
        "name": f"Custom Agent — {description[:50]}",
        "purpose": f"AI agent to handle: {description}. Configure ANTHROPIC_API_KEY for full AI generation.",
        "workflow": [
            "Step 1: Receive request via call or form",
            "Step 2: Validate and classify the request with AI",
            "Step 3: Process request using connected APIs",
            "Step 4: Update database and notify relevant parties",
            "Step 5: Log outcome and flag for review if needed",
        ],
        "required_tools": ["API Integration Layer", "Database Access", "Notification System (SMS/Email)"],
        "required_apis": ["Define specific third-party APIs needed for this use case"],
        "database_fields": [
            "request_type: String — category of the request",
            "request_data: Text — full request details",
            "status: String — processing status",
            "processed_at: DateTime — when request was handled",
        ],
        "call_script": "Hello! Thank you for calling. I'm your AI assistant. How can I help you today?",
        "dashboard_widgets": ["Request Queue — pending items", "Daily Volume Chart", "Success Rate Gauge"],
        "approval_rules": ["All automated actions require admin approval before going to production"],
        "testing_checklist": [
            "Test basic request intake — agent responds correctly",
            "Test edge cases — invalid or incomplete requests",
            "Test notification delivery — SMS/email sent successfully",
            "Test dashboard updates — data appears in real time",
        ],
        "estimated_dev_days": 7,
        "complexity": "medium",
        "monthly_api_cost_estimate": "$10-$50/month",
    }


# ── Data Entry Workflow ───────────────────────────────────────────────────────

async def process_document_data_entry(
    text: str,
    filename: str,
    workflow_type: str,
    db: Session,
    business_id: int = 0,
) -> dict:
    """
    Full Commander-supervised data entry pipeline:
    1. Document classification
    2. Medical or bookkeeping extraction
    3. Verification
    4. Recommendations
    Returns package ready for admin approval.
    """
    from .agents.data_entry import (
        DocumentReaderAgent, MedicalDataEntryAgent,
        BookkeepingEntryAgent, DataVerificationAgent,
    )

    reader_agent  = DocumentReaderAgent()
    verify_agent  = DataVerificationAgent()

    # Step 1 — classify document
    reader_result = await reader_agent.run("classify", {"filename": filename, "text": text})
    doc_info = reader_result.get("result", {})

    # Step 2 — extract
    if workflow_type == "bookkeeping":
        extractor = BookkeepingEntryAgent()
        extract_result = await extractor.run("extract", {"text": text, "use_ai": True})
        raw_fields = extract_result.get("result", {}).get("entry", {})
    else:
        extractor = MedicalDataEntryAgent()
        extract_result = await extractor.run("extract", {"text": text, "use_ai": True})
        raw_fields = extract_result.get("result", {}).get("fields", {})

    # Step 3 — verify
    verify_result = await verify_agent.run(
        "verify",
        {"fields": raw_fields, "job_type": workflow_type},
    )
    verify_data = verify_result.get("result", {})

    # Step 4 — Commander recommendations
    recommendations = _build_data_entry_recommendations(doc_info, extract_result, verify_data)

    # Persist Commander recommendation to DB if issues found
    if verify_data.get("validation_errors") or verify_data.get("missing_required"):
        try:
            severity = "warning" if verify_data.get("validation_errors") else "info"
            db.add(models.MasterRecommendation(
                business_id=business_id if business_id else None,
                module="data_entry",
                severity=severity,
                title=f"Data entry review needed — {filename}",
                detail=json.dumps({
                    "missing_required": verify_data.get("missing_required", []),
                    "errors": verify_data.get("validation_errors", []),
                }),
                recommended_action="; ".join(recommendations),
                auto_fix_available=False,
                status="pending_admin_review",
            ))
            db.commit()
        except Exception as e:
            logger.error("Failed to save Commander recommendation: %s", e)

    return {
        "document_reader":          doc_info,
        "extraction":               extract_result.get("result", {}),
        "verification":             verify_data,
        "commander_recommendations": recommendations,
        "completeness_pct":         verify_data.get("completeness_pct", 0),
        "can_proceed_to_admin":     verify_data.get("can_proceed_to_admin", False),
        "next_step":                "Admin must review and approve before data is posted to production records.",
        "phi_notice":               "HIPAA/PHI: No patient data is stored or transmitted without admin approval.",
    }


def _build_data_entry_recommendations(doc_info: dict, extract_result: dict, verify_data: dict) -> list:
    recs = []
    missing_required = verify_data.get("missing_required", [])
    errors           = verify_data.get("validation_errors", [])
    warnings         = verify_data.get("warnings", [])

    if doc_info.get("needs_human_review"):
        recs.append(f"Document quality is LOW (confidence: {doc_info.get('confidence_score', 0):.0%}). Request clearer scan or re-upload.")

    if missing_required:
        recs.append(f"Request missing required fields from patient/client: {', '.join(missing_required)}")

    if errors:
        recs.append(f"Fix validation errors before admin approval: {'; '.join(errors)}")

    if warnings:
        recs.append(f"Review field warnings: {'; '.join(warnings)}")

    if not recs:
        recs.append("Data appears complete and valid. Admin can review and approve for production posting.")

    recs.append("RULE: Commander AI cannot post to production without admin approval.")
    return recs


# ── Future Agent Blueprint ────────────────────────────────────────────────────

async def create_future_agent_blueprint(
    requested_agent: str,
    purpose: str,
    required_tools: list,
    data_inputs: list,
    data_outputs: list,
    db: Session,
    requested_by_id: int | None = None,
) -> dict:
    """Generate a future agent blueprint and save as draft for admin approval."""
    claude = _get_claude()

    if claude:
        prompt = f"""You are EZ-NEXUS COMMANDER AI. Generate a detailed future agent blueprint.

Agent Name: {requested_agent}
Purpose: {purpose}
Required Tools: {required_tools}
Data Inputs: {data_inputs}
Data Outputs: {data_outputs}

Return ONLY valid JSON:
{{
  "agent_name": "{requested_agent}",
  "purpose": "2-3 sentence description",
  "category": "healthcare|operations|finance|marketing|...",
  "required_tools": ["tool — description"],
  "data_inputs": ["input description"],
  "data_outputs": ["output description"],
  "workflow_steps": ["Step 1...", "Step 2...", "Step 3...", "Step 4...", "Step 5..."],
  "database_fields": ["field_name: Type — description"],
  "api_integrations": ["API name — purpose"],
  "approval_rules": ["Rule"],
  "testing_checklist": ["Test scenario — expected outcome"],
  "estimated_dev_days": 5,
  "complexity": "low|medium|high",
  "monthly_cost_estimate": "$X–$Y/month",
  "hipaa_considerations": ["consideration if applicable"]
}}"""
        try:
            msg = claude.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1400,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            blueprint = json.loads(raw)
        except Exception as e:
            logger.error("Blueprint generation error: %s", e)
            blueprint = _fallback_blueprint(requested_agent, purpose, required_tools)
    else:
        blueprint = _fallback_blueprint(requested_agent, purpose, required_tools)

    # Save as draft agent definition
    try:
        record = models.AgentDefinition(
            name=blueprint.get("agent_name", requested_agent),
            purpose=blueprint.get("purpose", purpose),
            spec_json=json.dumps(blueprint),
            status="draft",
            requested_by=requested_by_id,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        blueprint["agent_definition_id"] = record.id
    except Exception as e:
        logger.error("Failed to save blueprint: %s", e)

    blueprint["requires_admin_approval"] = True
    blueprint["note"] = "Commander AI cannot deploy agents to production without admin approval."
    return blueprint


def _fallback_blueprint(name: str, purpose: str, tools: list) -> dict:
    return {
        "agent_name": name,
        "purpose": purpose,
        "category": "general",
        "required_tools": tools or ["database", "audit_log", "admin_approval"],
        "data_inputs": ["document_upload", "manual_form_entry"],
        "data_outputs": ["structured_json", "excel_export", "audit_log"],
        "workflow_steps": [
            "Step 1: Receive document or form input",
            "Step 2: Classify and extract data using AI",
            "Step 3: Validate extracted fields",
            "Step 4: Prepare admin approval package",
            "Step 5: Admin reviews and approves before production posting",
        ],
        "database_fields": ["id: Integer", "status: String", "created_at: DateTime"],
        "api_integrations": ["Anthropic Claude — AI extraction"],
        "approval_rules": [
            "Agent can draft, extract, and recommend",
            "Agent cannot post to production without admin approval",
        ],
        "testing_checklist": [
            "Upload test document — verify extraction",
            "Verify missing field detection",
            "Verify admin approval workflow",
            "Verify audit log creation",
        ],
        "estimated_dev_days": 7,
        "complexity": "medium",
        "monthly_cost_estimate": "$10–$50/month",
    }


# ── Commander Chat ────────────────────────────────────────────────────────────

async def chat_with_commander(message: str, db: Session) -> str:
    """Natural-language chat with the Commander AI."""
    claude = _get_claude()

    # Build live context
    try:
        total_biz     = db.query(models.Business).filter(models.Business.is_active == True).count()
        total_appts   = db.query(models.Appointment).count()
        pending_appr  = db.query(models.Appointment).filter(models.Appointment.status == "pending_approval").count()
        unread_alerts = db.query(models.AdminAlert).filter(models.AdminAlert.is_read == False).count()
        week_ago      = datetime.utcnow() - timedelta(days=7)
        weekly        = db.query(models.Appointment).filter(models.Appointment.created_at >= week_ago).count()
    except Exception:
        total_biz = total_appts = pending_appr = unread_alerts = weekly = 0

    try:
        pending_de_jobs = db.query(models.DataEntryJob).filter(
            models.DataEntryJob.status == "pending_admin_approval"
        ).count()
        total_docs = db.query(models.UploadedDocument).count()
        total_patients = db.query(models.Patient).count()
    except Exception:
        pending_de_jobs = total_docs = total_patients = 0

    active_agents  = [a["name"] for a in AGENT_ROSTER if a["status"] == "active"]
    pending_agents = [a["name"] for a in AGENT_ROSTER if a["status"] == "coming_soon"]

    system_ctx = f"""You are EZ-NEXUS COMMANDER AI — the master intelligence brain of the EZ-NEXUS AI platform.
You supervise 18 specialized agents, monitor system health, analyze data quality, and advise the admin.

CURRENT SYSTEM STATE (live):
• Active businesses: {total_biz}
• Total appointments: {total_appts}  |  Weekly: {weekly}
• Pending appointment approvals: {pending_appr}
• Unread alerts: {unread_alerts}
• Data entry jobs pending approval: {pending_de_jobs}
• Total documents processed: {total_docs}
• Total patients in system: {total_patients}
• Twilio AI Calls: {"✅ ACTIVE" if settings.twilio_configured else "⚠️ NOT CONFIGURED"}
• Email: {"✅ ACTIVE" if settings.smtp_configured else "⚠️ NOT CONFIGURED"}
• AI Engine (Claude): {"✅ ACTIVE" if settings.anthropic_api_key else "⚠️ NOT CONFIGURED"}
• OCR: {"✅ ENABLED" if settings.enable_ocr else "⚠️ DISABLED"}
• PHI Mode (HIPAA): {"✅ ON" if settings.phi_mode else "⚠️ OFF"}
• Admin Approval Required: {"✅ YES" if settings.require_admin_approval else "⚠️ DISABLED"}

ACTIVE AGENTS (18 total): {", ".join(active_agents)}
MODULES: Call Center | Appointments | Healthcare | DME Marketplace | Data Entry | Bookkeeping | Compliance

YOUR RULES (NEVER BREAK):
1. NEVER change production systems, medical records, insurance data, or bookkeeping without admin approval
2. Flow: Detect → Suggest → Admin Approves → System Applies
3. PHI/HIPAA: Patient data stays private. Never expose raw records.
4. Be concise, direct, and actionable. End with a specific next-step.

You can: monitor health, analyze data quality, review missing fields, suggest fixes,
generate agent blueprints, explain workflows, and answer any admin question."""

    if not claude:
        return (
            f"**EZ-NEXUS COMMANDER AI** — Running in limited mode (no API key).\n\n"
            f"**System Status:**\n"
            f"• Businesses: {total_biz} | Appointments: {total_appts} | Weekly: {weekly}\n"
            f"• Pending Approvals: {pending_appr} | Unread Alerts: {unread_alerts}\n"
            f"• Twilio: {'✅' if settings.twilio_configured else '⚠️ Not configured'} | "
            f"Email: {'✅' if settings.smtp_configured else '⚠️ Not configured'}\n\n"
            f"**To activate full Commander intelligence**, add ANTHROPIC_API_KEY to your .env file.\n\n"
            f"*Your message:* \"{message}\""
        )

    try:
        msg = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=700,
            system=system_ctx,
            messages=[{"role": "user", "content": message}]
        )
        return msg.content[0].text
    except Exception as e:
        logger.error(f"Commander chat error: {e}")
        return f"Commander AI encountered an error: {str(e)}"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_claude():
    if not settings.anthropic_api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=settings.anthropic_api_key)
    except Exception:
        return None
