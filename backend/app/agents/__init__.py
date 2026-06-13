"""EZ-NEXUS AI — Agent Registry (18 agents total)"""
from .base import BaseAgent
from .specialized import (
    AppointmentAgent,
    CallCenterAgent,
    SalesAgent,
    BillingSupportAgent,
    MarketingAgent,
    WebsiteBuilderAgent,
    ContentVideoAgent,
    PatientOutreachAgent,
    IntakeAgent,
    InsuranceVerificationAgent,
    DMEProductMatchingAgent,
    SupplierMarketplaceAgent,
    ComplianceAgent,
)
from .data_entry import (
    MedicalDataEntryAgent,
    DocumentReaderAgent,
    ExcelAutomationAgent,
    BookkeepingEntryAgent,
    DataVerificationAgent,
)

AGENT_REGISTRY: dict[str, BaseAgent] = {
    # ── Original 13 agents ──────────────────────────────────
    "appointment":            AppointmentAgent(),
    "call_center":            CallCenterAgent(),
    "sales":                  SalesAgent(),
    "billing_support":        BillingSupportAgent(),
    "marketing":              MarketingAgent(),
    "website_builder":        WebsiteBuilderAgent(),
    "content_video":          ContentVideoAgent(),
    "patient_outreach":       PatientOutreachAgent(),
    "intake":                 IntakeAgent(),
    "insurance_verification": InsuranceVerificationAgent(),
    "dme_product_matching":   DMEProductMatchingAgent(),
    "supplier_marketplace":   SupplierMarketplaceAgent(),
    "compliance":             ComplianceAgent(),
    # ── Data Entry 5 agents ──────────────────────────────────
    "medical_data_entry":     MedicalDataEntryAgent(),
    "document_reader":        DocumentReaderAgent(),
    "excel_automation":       ExcelAutomationAgent(),
    "bookkeeping_entry":      BookkeepingEntryAgent(),
    "data_verification":      DataVerificationAgent(),
}

__all__ = ["BaseAgent", "AGENT_REGISTRY"]
