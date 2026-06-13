"""EZ-NEXUS AI — 13 Specialized Agents"""

from __future__ import annotations
import os
from typing import Any
from .base import BaseAgent


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _claude(prompt: str, system: str = "") -> str:
    """Thin wrapper around Anthropic Haiku for agent tasks."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system or "You are an EZ-NEXUS AI specialist agent. Be concise and helpful.",
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        return f"[AI unavailable: {e}]"


# ── 1. Appointment Agent ──────────────────────────────────────────────────────

class AppointmentAgent(BaseAgent):
    name = "Appointment Agent"
    description = "Books, reschedules, and manages appointments via AI phone + web"
    category = "operations"
    status = "active"
    icon = "📅"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "suggest_slot":
            prompt = f"Suggest 3 appointment time slots for: {payload}"
            return {"suggestion": await _claude(prompt)}
        if task_type == "summarize":
            prompt = f"Summarize this appointment request: {payload.get('notes', '')}"
            return {"summary": await _claude(prompt)}
        return {"detail": "Appointment task received", "payload": payload}


# ── 2. Call Center Agent ──────────────────────────────────────────────────────

class CallCenterAgent(BaseAgent):
    name = "Call Center Agent"
    description = "Handles inbound/outbound AI voice calls and transcribes conversations"
    category = "communication"
    status = "active"
    icon = "📞"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "triage":
            prompt = (
                f"Triage this call transcript as urgent/normal/low and provide a 2-sentence summary.\n"
                f"Transcript: {payload.get('transcript', '')}"
            )
            return {"triage": await _claude(prompt)}
        return {"detail": "Call center task received"}


# ── 3. Sales Agent ────────────────────────────────────────────────────────────

class SalesAgent(BaseAgent):
    name = "Sales Agent"
    description = "Qualifies leads, sends follow-ups, and tracks pipeline stages"
    category = "sales"
    status = "active"
    icon = "💼"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "qualify_lead":
            prompt = (
                f"Score this lead 1-10 and provide 3 bullet points on next steps.\n"
                f"Lead info: {payload}"
            )
            return {"qualification": await _claude(prompt)}
        return {"detail": "Sales task received"}


# ── 4. Billing Support Agent ──────────────────────────────────────────────────

class BillingSupportAgent(BaseAgent):
    name = "Billing Support Agent"
    description = "Handles billing inquiries, invoice disputes, and payment plans"
    category = "finance"
    status = "active"
    icon = "💳"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "draft_response":
            prompt = (
                f"Draft a professional billing support response for: {payload.get('issue', '')}"
            )
            return {"response": await _claude(prompt)}
        return {"detail": "Billing support task received"}


# ── 5. Marketing Agent ────────────────────────────────────────────────────────

class MarketingAgent(BaseAgent):
    name = "Marketing Agent"
    description = "Creates campaigns, SMS blasts, and social media content"
    category = "marketing"
    status = "active"
    icon = "📢"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "generate_copy":
            prompt = (
                f"Write a short marketing message (under 160 chars for SMS) for: "
                f"{payload.get('product', '')} targeting {payload.get('audience', 'general audience')}"
            )
            return {"copy": await _claude(prompt)}
        return {"detail": "Marketing task received"}


# ── 6. Website Builder Agent ──────────────────────────────────────────────────

class WebsiteBuilderAgent(BaseAgent):
    name = "Website Builder Agent"
    description = "Generates landing pages, booking widgets, and micro-sites"
    category = "technology"
    status = "coming_soon"
    icon = "🌐"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        return {"detail": "Website Builder Agent — coming soon", "task_type": task_type}


# ── 7. Content & Video Agent ──────────────────────────────────────────────────

class ContentVideoAgent(BaseAgent):
    name = "Content & Video Agent"
    description = "Scripts, produces, and distributes short-form video content"
    category = "media"
    status = "coming_soon"
    icon = "🎬"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "write_script":
            prompt = (
                f"Write a 30-second video script for: {payload.get('topic', 'our business')}"
            )
            return {"script": await _claude(prompt)}
        return {"detail": "Content & Video Agent — coming soon"}


# ── 8. Patient Outreach Agent ─────────────────────────────────────────────────

class PatientOutreachAgent(BaseAgent):
    name = "Patient Outreach Agent"
    description = "Contacts patients for recalls, follow-ups, and referrals"
    category = "healthcare"
    status = "active"
    icon = "🏥"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "draft_outreach":
            prompt = (
                f"Write a HIPAA-compliant patient outreach message for: "
                f"{payload.get('reason', 'follow-up appointment')}. Patient: {payload.get('patient_name', 'Patient')}"
            )
            return {"message": await _claude(prompt)}
        return {"detail": "Patient outreach task received"}


# ── 9. Intake Agent ───────────────────────────────────────────────────────────

class IntakeAgent(BaseAgent):
    name = "Intake Agent"
    description = "Collects patient demographics, consent, and insurance information"
    category = "healthcare"
    status = "active"
    icon = "📋"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "extract_intake":
            prompt = (
                f"Extract structured intake data (name, DOB, insurance, medications) from: "
                f"{payload.get('raw_text', '')}"
            )
            return {"extracted": await _claude(prompt)}
        return {"detail": "Intake task received"}


# ── 10. Insurance Verification Agent ─────────────────────────────────────────

class InsuranceVerificationAgent(BaseAgent):
    name = "Insurance Verification Agent"
    description = "Verifies insurance eligibility, benefits, and prior authorizations"
    category = "healthcare"
    status = "active"
    icon = "🔒"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "check_eligibility":
            prompt = (
                f"Summarize insurance verification steps for: "
                f"Insurance: {payload.get('insurance_name', 'unknown')}, "
                f"Member ID: {payload.get('member_id', 'N/A')}, "
                f"Service: {payload.get('service', 'DME')}"
            )
            return {"verification_steps": await _claude(prompt)}
        return {"detail": "Insurance verification task received"}


# ── 11. DME Product Matching Agent ───────────────────────────────────────────

class DMEProductMatchingAgent(BaseAgent):
    name = "DME Product Matching Agent"
    description = "Matches patient needs to covered DME products and suppliers"
    category = "healthcare"
    status = "active"
    icon = "🦽"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "match_products":
            prompt = (
                f"Recommend DME products and relevant HCPCS codes for: "
                f"Diagnosis: {payload.get('diagnosis', 'unknown')}, "
                f"Need: {payload.get('equipment_needed', 'unknown')}"
            )
            return {"recommendations": await _claude(prompt)}
        return {"detail": "DME product matching task received"}


# ── 12. Supplier Marketplace Agent ───────────────────────────────────────────

class SupplierMarketplaceAgent(BaseAgent):
    name = "Supplier Marketplace Agent"
    description = "Connects DME providers with verified equipment suppliers"
    category = "marketplace"
    status = "active"
    icon = "🏪"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "find_supplier":
            prompt = (
                f"Describe how to find a qualified DME supplier for: "
                f"{payload.get('product_category', 'general DME')}"
            )
            return {"guidance": await _claude(prompt)}
        return {"detail": "Supplier marketplace task received"}


# ── 13. Compliance Agent ──────────────────────────────────────────────────────

class ComplianceAgent(BaseAgent):
    name = "Compliance Agent"
    description = "Monitors HIPAA, Medicare, and state regulatory compliance"
    category = "compliance"
    status = "active"
    icon = "⚖️"

    async def handle(self, task_type: str, payload: dict, db: Any = None) -> dict:
        if task_type == "audit":
            prompt = (
                f"Provide a HIPAA compliance checklist for: {payload.get('process', 'patient data handling')}"
            )
            return {"checklist": await _claude(prompt)}
        return {"detail": "Compliance task received"}
