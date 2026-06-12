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


# ── Commander Chat ────────────────────────────────────────────────────────────

async def chat_with_commander(message: str, db: Session) -> str:
    """Natural-language chat with the Commander AI."""
    claude = _get_claude()

    # Build live context
    try:
        total_biz    = db.query(models.Business).filter(models.Business.is_active == True).count()
        total_appts  = db.query(models.Appointment).count()
        pending_appr = db.query(models.Appointment).filter(models.Appointment.status == "pending_approval").count()
        unread_alerts = db.query(models.AdminAlert).filter(models.AdminAlert.is_read == False).count()
        week_ago = datetime.utcnow() - timedelta(days=7)
        weekly   = db.query(models.Appointment).filter(models.Appointment.created_at >= week_ago).count()
    except Exception:
        total_biz = total_appts = pending_appr = unread_alerts = weekly = 0

    active_agents  = [a["name"] for a in AGENT_ROSTER if a["status"] == "active"]
    pending_agents = [a["name"] for a in AGENT_ROSTER if a["status"] == "coming_soon"]

    system_ctx = f"""You are EZ-NEXUS COMMANDER AI — the master intelligence brain of the EZ-NEXUS AI platform.
You are the central nervous system that supervises all agents, monitors health, and advises the admin.

CURRENT SYSTEM STATE (live):
• Active businesses: {total_biz}
• Total appointments: {total_appts}
• Weekly appointments: {weekly}
• Pending approvals: {pending_appr}
• Unread alerts: {unread_alerts}
• Twilio AI Calls: {"✅ ACTIVE" if settings.twilio_configured else "⚠️ NOT CONFIGURED"}
• Email confirmations: {"✅ ACTIVE" if settings.smtp_configured else "⚠️ NOT CONFIGURED"}
• AI Engine (Claude): {"✅ ACTIVE" if settings.anthropic_api_key else "⚠️ NOT CONFIGURED"}

ACTIVE AGENTS ({len(active_agents)}): {", ".join(active_agents)}
COMING SOON ({len(pending_agents)}): {", ".join(pending_agents)}

YOUR RULES:
1. You NEVER change production systems without admin approval
2. Always: Detect issue → Suggest fix → Wait for admin approval → System applies
3. Be concise, direct, and actionable
4. Always end with a specific next-step recommendation

You can: monitor health, suggest fixes, generate new agent specs, explain the platform,
analyze performance, recommend upgrades, and answer any admin question."""

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
