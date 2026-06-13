"""
EZ-NEXUS AI — Data Entry Specialized Agents
Five agents that handle the full document → data extraction → validation pipeline.

Rule: ALL agents operate in DRAFT/REVIEW mode.
Medical, insurance, bookkeeping, billing, claims, and official records
REQUIRE admin approval before posting to production.
"""

from __future__ import annotations
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseAgent

logger = logging.getLogger(__name__)

# Known insurance payer names for fuzzy matching
KNOWN_PAYERS = [
    "Aetna", "Blue Cross Blue Shield", "BCBS", "Cigna", "UnitedHealthcare", "United Healthcare",
    "Humana", "Kaiser Permanente", "Molina Healthcare", "Centene", "WellCare",
    "Medicare", "Medicaid", "Tricare", "CVS Health", "Anthem", "Elevance Health",
    "Oscar Health", "Bright Health", "Health Net",
]

KNOWN_EQUIPMENT = [
    "wheelchair", "power wheelchair", "manual wheelchair", "transport wheelchair",
    "walker", "rollator", "crutches", "cane",
    "hospital bed", "adjustable bed", "semi-electric bed",
    "cpap", "bipap", "oxygen concentrator", "portable oxygen",
    "nebulizer", "suction machine", "ventilator",
    "diabetic supplies", "glucose monitor", "insulin pump",
    "knee brace", "ankle brace", "wrist splint", "cervical collar",
    "shower chair", "grab bar", "toilet riser", "bedside commode",
    "compression stockings", "lymphedema pump",
    "scooter", "power scooter",
]


def _claude_extract(prompt: str) -> str:
    """Call Claude Haiku for AI-assisted extraction. Returns empty string on failure."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=(
                "You are a medical data extraction specialist. "
                "Extract data accurately and return only the requested information. "
                "If a field is not found, return null. "
                "Never fabricate patient information."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.debug("Claude extraction unavailable: %s", e)
        return ""


# ── 1. Medical Data Entry Agent ───────────────────────────────────────────────

class MedicalDataEntryAgent(BaseAgent):
    name = "Medical Data Entry Agent"
    description = "Extracts patient demographics, insurance IDs, DME needs, and provider/referral data from documents"
    category = "healthcare"
    status = "active"
    icon = "🏥"

    async def handle(self, task_type: str, payload: Dict[str, Any], db: Any = None) -> Dict[str, Any]:
        text = payload.get("text", "")
        use_ai = payload.get("use_ai", True)

        # Regex-based extraction
        fields = {
            "patient_first_name":   self._name_part(text, 0),
            "patient_last_name":    self._name_part(text, 1),
            "date_of_birth":        self._find_dob(text),
            "phone":                self._find_phone(text),
            "email":                self._find_email(text),
            "address":              self._find_address(text),
            "insurance_member_id":  self._find_after_labels(text, ["member id", "member #", "subscriber id", "policy id", "id#", "id #"]),
            "group_number":         self._find_after_labels(text, ["group", "group #", "group number", "grp"]),
            "payer_name":           self._find_payer(text),
            "policy_holder":        self._find_after_labels(text, ["policy holder", "subscriber", "insured"]),
            "equipment_requested":  self._find_equipment(text),
            "diagnosis_codes":      self._find_icd_codes(text),
            "prescribing_doctor":   self._find_after_labels(text, ["doctor", "physician", "dr.", "provider", "ordered by", "prescribed by"]),
            "npi_number":           self._find_npi(text),
        }

        # AI-assisted fill-in for missing fields
        if use_ai:
            missing_keys = [k for k, v in fields.items() if not v]
            if missing_keys and text.strip():
                ai_prompt = (
                    f"From the following document text, extract these fields as JSON: "
                    f"{missing_keys}\n\nDocument:\n{text[:3000]}\n\n"
                    f"Return ONLY a JSON object like {{\"field_name\": \"value_or_null\"}}"
                )
                ai_raw = _claude_extract(ai_prompt)
                if ai_raw:
                    try:
                        import json
                        ai_data = json.loads(ai_raw)
                        for k, v in ai_data.items():
                            if k in fields and not fields[k] and v and v != "null":
                                fields[k] = v
                    except Exception:
                        pass

        missing = [k for k, v in fields.items() if not v]
        return {
            "fields":        fields,
            "missing_fields": missing,
            "completeness_pct": round((len(fields) - len(missing)) / len(fields) * 100, 1),
            "requires_admin_approval": True,
            "warning": "Human/admin approval required before updating official medical or insurance records.",
        }

    # ── Regex helpers ────────────────────────────────────────────────────────

    def _find_phone(self, text: str) -> Optional[str]:
        m = re.search(r"(\+?1?[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text)
        return m.group(0).strip() if m else None

    def _find_email(self, text: str) -> Optional[str]:
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        return m.group(0) if m else None

    def _find_dob(self, text: str) -> Optional[str]:
        m = re.search(
            r"(?:DOB|Date\s+of\s+Birth|Birth\s+Date|Birthdate)[:\s]*"
            r"([0-9]{1,2}[/\-\.][0-9]{1,2}[/\-\.][0-9]{2,4})",
            text, re.IGNORECASE,
        )
        return m.group(1) if m else None

    def _find_address(self, text: str) -> Optional[str]:
        m = re.search(
            r"\d+\s+[A-Za-z\s]+(?:Street|St|Avenue|Ave|Drive|Dr|Road|Rd|Lane|Ln|Blvd|Boulevard|Way|Court|Ct|Place|Pl)[.,]?\s*"
            r"[A-Za-z\s]*,?\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?",
            text, re.IGNORECASE,
        )
        return m.group(0).strip() if m else None

    def _find_after_labels(self, text: str, labels: List[str]) -> Optional[str]:
        for label in labels:
            pattern = re.escape(label) + r"[:\s#\-]*([A-Za-z0-9\-]{3,30})"
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def _find_payer(self, text: str) -> Optional[str]:
        t_lower = text.lower()
        for payer in KNOWN_PAYERS:
            if payer.lower() in t_lower:
                return payer
        return self._find_after_labels(text, ["insurance", "payer", "plan name", "carrier"])

    def _find_equipment(self, text: str) -> Optional[str]:
        t_lower = text.lower()
        found = [item for item in KNOWN_EQUIPMENT if item in t_lower]
        return ", ".join(found) if found else None

    def _find_icd_codes(self, text: str) -> Optional[str]:
        codes = re.findall(r"\b[A-Z]\d{2}(?:\.\d{1,4})?\b", text)
        return ", ".join(codes) if codes else None

    def _find_npi(self, text: str) -> Optional[str]:
        m = re.search(r"\bNPI[:\s#]*(\d{10})\b", text, re.IGNORECASE)
        return m.group(1) if m else None

    def _name_part(self, text: str, index: int) -> Optional[str]:
        patterns = [
            r"(?:Patient\s+Name|Patient|Name)[:\s]*([A-Za-z]+)\s+([A-Za-z]+)",
            r"(?:First\s+Name)[:\s]*([A-Za-z]+)\s+(?:Last\s+Name)[:\s]*([A-Za-z]+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(index + 1)
        return None


# ── 2. Document Reader Agent ──────────────────────────────────────────────────

class DocumentReaderAgent(BaseAgent):
    name = "Document Reader Agent"
    description = "Reads and classifies PDF, scanned PDF, image OCR, Word, Excel, and CSV documents"
    category = "operations"
    status = "active"
    icon = "📄"

    async def handle(self, task_type: str, payload: Dict[str, Any], db: Any = None) -> Dict[str, Any]:
        filename     = payload.get("filename", "")
        text         = payload.get("text", "")
        confidence   = payload.get("confidence", 0.0)
        file_path    = payload.get("file_path", "")

        # Classify document type
        from ..services.document_processor import DocumentProcessor
        doc_type = DocumentProcessor.classify_document_type(filename, text)

        # Quality assessment
        quality = self._assess_quality(text, confidence)
        needs_review = confidence < 0.60 or quality["word_count"] < 10

        return {
            "document_type":   doc_type,
            "confidence_score": confidence,
            "quality":          quality,
            "needs_human_review": needs_review,
            "text_preview":    text[:500] if text else "",
            "flagged_reason":  "Low confidence score — manual review recommended" if needs_review else None,
        }

    def _assess_quality(self, text: str, confidence: float) -> Dict[str, Any]:
        words = text.split() if text else []
        lines = text.splitlines() if text else []
        return {
            "word_count":  len(words),
            "line_count":  len(lines),
            "char_count":  len(text),
            "has_numbers": bool(re.search(r"\d", text)),
            "has_dates":   bool(re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", text)),
            "has_phone":   bool(re.search(r"\d{3}[\s.-]\d{3}[\s.-]\d{4}", text)),
            "quality_grade": "high" if confidence >= 0.80 else "medium" if confidence >= 0.55 else "low",
        }


# ── 3. Excel Automation Agent ─────────────────────────────────────────────────

class ExcelAutomationAgent(BaseAgent):
    name = "Excel Automation Agent"
    description = "Creates, edits, formats, validates, and exports Excel workbooks and CSV templates"
    category = "operations"
    status = "active"
    icon = "📊"

    async def handle(self, task_type: str, payload: Dict[str, Any], db: Any = None) -> Dict[str, Any]:
        from ..services.spreadsheet_service import SpreadsheetService, PATIENT_COLUMNS, BOOKKEEPING_COLUMNS

        svc = SpreadsheetService()

        if task_type == "create_patient_workbook":
            rows       = payload.get("rows", [])
            output_path = payload.get("output_path", "/tmp/patient_data.xlsx")
            path = svc.create_patient_workbook(rows, output_path)
            return {"output_path": path, "row_count": len(rows), "columns": PATIENT_COLUMNS}

        if task_type == "create_bookkeeping_workbook":
            rows        = payload.get("rows", [])
            output_path = payload.get("output_path", "/tmp/bookkeeping.xlsx")
            path = svc.create_bookkeeping_workbook(rows, output_path)
            return {"output_path": path, "row_count": len(rows), "columns": BOOKKEEPING_COLUMNS}

        if task_type == "get_template_columns":
            template = payload.get("template", "patient")
            mapping = {
                "patient":     PATIENT_COLUMNS,
                "bookkeeping": BOOKKEEPING_COLUMNS,
            }
            return {"template": template, "columns": mapping.get(template, PATIENT_COLUMNS)}

        if task_type == "validate_rows":
            rows      = payload.get("rows", [])
            required  = payload.get("required_columns", [])
            errors = []
            for i, row in enumerate(rows):
                for col in required:
                    if not row.get(col):
                        errors.append(f"Row {i+1}: missing '{col}'")
            return {"valid": len(errors) == 0, "errors": errors, "row_count": len(rows)}

        return {"detail": "Excel automation task received", "task_type": task_type}


# ── 4. Bookkeeping Entry Agent ────────────────────────────────────────────────

class BookkeepingEntryAgent(BaseAgent):
    name = "Bookkeeping Entry Agent"
    description = "Extracts receipts, invoices, expenses, vendor/customer records, and prepares bookkeeping entries"
    category = "finance"
    status = "active"
    icon = "📒"

    async def handle(self, task_type: str, payload: Dict[str, Any], db: Any = None) -> Dict[str, Any]:
        text = payload.get("text", "")
        use_ai = payload.get("use_ai", True)

        # Regex-based extraction
        amount        = self._find_amount(text)
        vendor        = self._find_vendor(text)
        date          = self._find_date(text)
        invoice_no    = self._find_invoice_no(text)
        tax_amount    = self._find_tax(text)
        entry_type    = self._guess_entry_type(text)
        category      = self._guess_category(text)

        entry = {
            "vendor_or_customer": vendor,
            "transaction_date":   date,
            "entry_type":         entry_type,
            "amount":             amount,
            "tax_amount":         tax_amount,
            "tax_flag":           tax_amount is not None,
            "category":           category,
            "invoice_number":     invoice_no,
            "memo":               text[:250].strip(),
            "status":             "draft_pending_admin_approval",
        }

        # AI fill-in for missing critical fields
        if use_ai and (not amount or not vendor):
            ai_prompt = (
                f"Extract bookkeeping data from this document as JSON with keys: "
                f"vendor_or_customer, transaction_date, amount (number), invoice_number, category, entry_type.\n\n"
                f"Document:\n{text[:2000]}\n\n"
                f"Return ONLY valid JSON."
            )
            ai_raw = _claude_extract(ai_prompt)
            if ai_raw:
                try:
                    import json
                    ai_data = json.loads(ai_raw)
                    for k, v in ai_data.items():
                        if k in entry and not entry[k] and v and v != "null":
                            entry[k] = v
                except Exception:
                    pass

        missing = [k for k, v in entry.items() if v in (None, "", 0.0)]
        return {
            "entry":         entry,
            "missing_fields": missing,
            "requires_admin_approval": True,
            "warning": "Bookkeeping entry is a DRAFT. Admin must approve before posting to official records.",
        }

    def _find_amount(self, text: str) -> Optional[float]:
        # Look for "Total", "Amount Due", "Balance" first
        for pattern in [
            r"(?:total|amount\s+due|balance\s+due|grand\s+total)[:\s]*\$?\s*([0-9,]+(?:\.[0-9]{2})?)",
            r"\$\s*([0-9,]+(?:\.[0-9]{2})?)",
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(",", ""))
                except ValueError:
                    pass
        return None

    def _find_tax(self, text: str) -> Optional[float]:
        m = re.search(r"(?:tax|sales\s+tax|HST|GST|VAT)[:\s]*\$?\s*([0-9,]+(?:\.[0-9]{2})?)", text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
        return None

    def _find_vendor(self, text: str) -> Optional[str]:
        lines = [x.strip() for x in text.splitlines() if x.strip() and len(x.strip()) > 3]
        return lines[0][:120] if lines else None

    def _find_date(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:Date|Invoice\s+Date|Transaction\s+Date)[:\s]*([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            r"(?:Date|Invoice\s+Date|Transaction\s+Date)[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
            r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    def _find_invoice_no(self, text: str) -> Optional[str]:
        m = re.search(r"(?:Invoice|Inv|Receipt)[:\s#]*([A-Za-z0-9\-]{4,20})", text, re.IGNORECASE)
        return m.group(1) if m else None

    def _guess_entry_type(self, text: str) -> str:
        t = text.lower()
        if any(x in t for x in ["receipt", "paid", "payment received"]):
            return "receipt"
        if any(x in t for x in ["invoice", "bill", "amount due", "balance due"]):
            return "invoice"
        if any(x in t for x in ["expense", "reimbursement"]):
            return "expense"
        if any(x in t for x in ["revenue", "income", "sales"]):
            return "revenue"
        return "invoice"

    def _guess_category(self, text: str) -> str:
        t = text.lower()
        if any(x in t for x in ["medical", "clinic", "pharmacy", "hospital", "drug"]):
            return "Medical Supplies"
        if any(x in t for x in ["office", "paper", "printer", "staple"]):
            return "Office Supplies"
        if any(x in t for x in ["fuel", "gas", "petrol"]):
            return "Fuel & Travel"
        if any(x in t for x in ["internet", "phone", "software", "subscription"]):
            return "Utilities/Software"
        if any(x in t for x in ["rent", "lease"]):
            return "Rent/Lease"
        if any(x in t for x in ["payroll", "salary", "wage"]):
            return "Payroll"
        if any(x in t for x in ["marketing", "advertising", "social media"]):
            return "Marketing"
        return "Uncategorized"


# ── 5. Data Verification Agent ────────────────────────────────────────────────

class DataVerificationAgent(BaseAgent):
    name = "Data Verification Agent"
    description = "Checks missing fields, duplicate detection, data format validation, and quality scoring"
    category = "operations"
    status = "active"
    icon = "✅"

    async def handle(self, task_type: str, payload: Dict[str, Any], db: Any = None) -> Dict[str, Any]:
        fields  = payload.get("fields", {})
        job_type = payload.get("job_type", "medical")

        errors   = []
        warnings = []

        # Format validation
        email = fields.get("email") or fields.get("patient_email", "")
        if email and "@" not in email:
            errors.append("Invalid email format")

        phone = fields.get("phone") or fields.get("patient_phone", "")
        if phone and len(re.sub(r"\D", "", phone)) < 10:
            errors.append("Phone number appears incomplete (less than 10 digits)")

        dob = fields.get("date_of_birth", "")
        if dob and not re.search(r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}", dob):
            warnings.append("Date of birth format may be incorrect — expected MM/DD/YYYY")

        member_id = fields.get("insurance_member_id", "")
        if member_id and len(member_id) < 4:
            warnings.append("Insurance member ID seems too short")

        amount = fields.get("amount")
        if job_type == "bookkeeping" and amount:
            try:
                amt = float(amount)
                if amt <= 0:
                    errors.append("Amount must be greater than zero")
                if amt > 1_000_000:
                    warnings.append("Amount exceeds $1,000,000 — verify this is correct")
            except (ValueError, TypeError):
                errors.append("Amount is not a valid number")

        # Completeness scoring
        required_fields = {
            "medical":     ["patient_first_name", "patient_last_name", "date_of_birth", "insurance_member_id"],
            "bookkeeping": ["vendor_or_customer", "amount", "transaction_date"],
            "insurance":   ["payer_name", "member_id", "group_number"],
            "equipment":   ["equipment_type", "prescribing_doctor"],
        }
        required = required_fields.get(job_type, [])
        missing_required = [f for f in required if not fields.get(f)]
        missing_optional = [k for k, v in fields.items() if v in (None, "", []) and k not in required]

        completeness_pct = round(
            (len(required) - len(missing_required)) / len(required) * 100 if required else 100.0, 1
        )

        # Overall pass/fail
        can_proceed = len(errors) == 0 and len(missing_required) == 0

        return {
            "validation_errors":   errors,
            "warnings":            warnings,
            "missing_required":    missing_required,
            "missing_optional":    missing_optional[:10],
            "completeness_pct":    completeness_pct,
            "can_proceed_to_admin": can_proceed,
            "requires_admin_approval": True,
        }
