"""EZ-NEXUS AI — Agent Registry"""
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

AGENT_REGISTRY: dict[str, BaseAgent] = {
    "appointment":           AppointmentAgent(),
    "call_center":           CallCenterAgent(),
    "sales":                 SalesAgent(),
    "billing_support":       BillingSupportAgent(),
    "marketing":             MarketingAgent(),
    "website_builder":       WebsiteBuilderAgent(),
    "content_video":         ContentVideoAgent(),
    "patient_outreach":      PatientOutreachAgent(),
    "intake":                IntakeAgent(),
    "insurance_verification": InsuranceVerificationAgent(),
    "dme_product_matching":  DMEProductMatchingAgent(),
    "supplier_marketplace":  SupplierMarketplaceAgent(),
    "compliance":            ComplianceAgent(),
}

__all__ = ["BaseAgent", "AGENT_REGISTRY"]
