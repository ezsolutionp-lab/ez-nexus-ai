"""
Business-in-a-box: a vertical blueprint that feeds the existing Universal Builder.

`blueprint(vertical)` returns the modules, staff roles, industry agents, KPIs, compliance notes and integration slots for
one of twelve verticals, plus a ready-to-run Builder prompt. It generates nothing itself: the prompt goes to the Builder
(which compiles, tests and never deploys without approval). Compliance notes are prompts for a professional review,
not legal advice, and no integration listed here is live — each one needs the operator's own account and credential.
"""

from __future__ import annotations

from typing import Any

COMMON_MODULES = ["website / landing page", "AI receptionist", "CRM", "lead capture", "appointment booking", "quotes",
                  "follow-up automation", "reviews", "marketing", "social content", "email / SMS", "payments / invoicing adapters",
                  "analytics", "SOPs", "knowledge base", "staff workflows"]

_V: dict[str, dict[str, Any]] = {
    "dental": {"services": ["cleanings", "fillings", "whitening", "implants", "emergency visits"], "roles": ["dentist", "hygienist", "front desk"],
               "agents": ["recall reminder agent", "insurance eligibility helper", "treatment-plan explainer"],
               "kpis": ["chair utilisation", "no-show rate", "treatment acceptance rate", "recall rate"],
               "compliance": ["HIPAA: patient records need access control, audit and a BAA with vendors", "consent for SMS reminders (TCPA)"],
               "integrations": ["practice-management system", "insurance clearinghouse", "SMS gateway"]},
    "med spa": {"services": ["injectables", "laser treatments", "facials", "memberships"], "roles": ["medical director", "aesthetician", "front desk"],
                "agents": ["consultation intake agent", "membership renewal agent", "before/after consent tracker"],
                "kpis": ["membership churn", "rebooking rate", "revenue per treatment room", "package redemption"],
                "compliance": ["HIPAA for health history", "medical-director supervision rules vary by state", "advertising claims need review"],
                "integrations": ["booking system", "payment processor", "email/SMS"]},
    "HVAC": {"services": ["repair", "maintenance plans", "installation", "emergency callout"], "roles": ["dispatcher", "technician", "estimator"],
             "agents": ["dispatch optimiser", "maintenance-plan reminder agent", "quote builder"],
             "kpis": ["first-time fix rate", "technician utilisation", "average ticket", "plan renewal rate"],
             "compliance": ["contractor licensing", "refrigerant handling certification (EPA 608)"],
             "integrations": ["field-service system", "payment processor", "maps/routing"]},
    "plumbing": {"services": ["leak repair", "drain clearing", "water heaters", "emergency callout"], "roles": ["dispatcher", "plumber", "estimator"],
                 "agents": ["emergency triage agent", "quote builder", "review-request agent"],
                 "kpis": ["response time", "first-time fix rate", "average ticket", "review score"],
                 "compliance": ["contractor licensing and permits vary by jurisdiction"],
                 "integrations": ["field-service system", "payment processor", "SMS gateway"]},
    "roofing": {"services": ["inspections", "repairs", "replacement", "storm damage claims"], "roles": ["estimator", "crew lead", "project manager"],
                "agents": ["inspection scheduler", "insurance-claim documenter", "proposal builder"],
                "kpis": ["lead-to-quote rate", "close rate", "job margin", "days to completion"],
                "compliance": ["contractor licensing", "state rules on insurance-claim advice"],
                "integrations": ["estimating tool", "payment processor", "e-signature"]},
    "auto repair": {"services": ["diagnostics", "brakes", "oil and fluids", "tyres", "inspections"], "roles": ["service advisor", "technician", "parts manager"],
                    "agents": ["estimate explainer", "service-due reminder agent", "parts-order helper"],
                    "kpis": ["effective labour rate", "car count", "average repair order", "comeback rate"],
                    "compliance": ["written estimate and authorisation rules vary by state", "hazardous waste handling"],
                    "integrations": ["shop-management system", "parts catalogue", "payment processor"]},
    "law": {"services": ["consultations", "case intake", "document drafting", "matter tracking"], "roles": ["attorney", "paralegal", "intake coordinator"],
            "agents": ["conflict-check helper", "deadline tracker", "client-update drafter"],
            "kpis": ["intake-to-retainer rate", "billable utilisation", "collections rate", "days to first response"],
            "compliance": ["attorney-client confidentiality", "conflict checks", "advertising and solicitation rules", "trust-account rules"],
            "integrations": ["practice-management system", "e-signature", "payment processor with trust accounting"]},
    "property management": {"services": ["tenant screening", "rent collection", "maintenance requests", "inspections"],
                            "roles": ["property manager", "maintenance coordinator", "leasing agent"],
                            "agents": ["maintenance triage agent", "rent-reminder agent", "lease-renewal agent"],
                            "kpis": ["occupancy", "days vacant", "on-time rent rate", "work-order turnaround"],
                            "compliance": ["fair-housing rules for screening and advertising", "security-deposit handling", "local landlord-tenant law"],
                            "integrations": ["accounting system", "payment processor", "screening provider"]},
    "home healthcare": {"services": ["personal care", "skilled nursing", "companionship", "care-plan reviews"],
                        "roles": ["care coordinator", "caregiver", "clinical supervisor"],
                        "agents": ["shift-fill agent", "care-plan reminder agent", "family update drafter"],
                        "kpis": ["shift fill rate", "caregiver retention", "missed-visit rate", "client satisfaction"],
                        "compliance": ["HIPAA", "state licensing", "caregiver background checks", "wage-and-hour rules"],
                        "integrations": ["scheduling/EVV system", "payroll", "SMS gateway"]},
    "insurance": {"services": ["quotes", "policy servicing", "claims support", "renewals"], "roles": ["agent", "account manager", "claims liaison"],
                  "agents": ["quote comparison helper", "renewal reminder agent", "document collector"],
                  "kpis": ["quote-to-bind rate", "retention rate", "cross-sell rate", "time to first response"],
                  "compliance": ["state producer licensing", "disclosure and suitability rules", "privacy of nonpublic personal information"],
                  "integrations": ["agency-management system", "carrier portals", "e-signature"]},
    "restaurants": {"services": ["dine-in reservations", "online ordering", "catering", "loyalty"], "roles": ["manager", "host", "kitchen lead"],
                    "agents": ["reservation agent", "menu Q&A agent", "review-response drafter"],
                    "kpis": ["table turn time", "food cost %", "labour cost %", "average check"],
                    "compliance": ["food-safety inspections", "allergen disclosure", "PCI DSS if handling cards directly (use a hosted processor)"],
                    "integrations": ["POS", "delivery platforms", "payment processor"]},
    "accounting": {"services": ["bookkeeping", "payroll", "tax preparation", "advisory"], "roles": ["accountant", "bookkeeper", "client manager"],
                   "agents": ["document collection agent", "deadline reminder agent", "reconciliation helper"],
                   "kpis": ["realisation rate", "on-time filing rate", "revenue per client", "turnaround time"],
                   "compliance": ["professional licensing", "client-data confidentiality", "IRS e-file security requirements"],
                   "integrations": ["accounting software", "document portal", "payment processor"]},
}
_ALIASES = {"hvac": "HVAC", "med-spa": "med spa", "medspa": "med spa", "auto": "auto repair", "car repair": "auto repair",
            "lawyer": "law", "legal": "law", "real estate management": "property management", "home care": "home healthcare",
            "restaurant": "restaurants", "accountant": "accounting", "dentist": "dental"}


def verticals() -> list[str]:
    return sorted(_V, key=str.lower)


def blueprint(vertical: Any, business_name: str = "") -> dict[str, Any]:
    if not isinstance(vertical, str) or not vertical.strip():
        raise ValueError("vertical must be a non-empty string")
    if not isinstance(business_name, str) or len(business_name) > 120:
        raise ValueError("business_name must be a string of at most 120 characters")
    key = vertical.strip().lower()
    key = _ALIASES.get(key, key)
    match = next((k for k in _V if k.lower() == key.lower()), None)
    if match is None:
        raise ValueError(f"unknown vertical '{vertical}'. Available: {', '.join(verticals())}")
    v = _V[match]
    who = business_name.strip() or f"a {match} business"
    prompt = (f"Build a complete platform for {who} ({match}). Include: " + ", ".join(COMMON_MODULES) + ". "
              f"Services: {', '.join(v['services'])}. Staff roles: {', '.join(v['roles'])}. "
              f"Industry agents: {', '.join(v['agents'])}. Track: {', '.join(v['kpis'])}. "
              "Integrations must be adapters that report CREDENTIAL_REQUIRED until the operator configures them. Do not deploy.")
    return {"vertical": match, "business": who, "modules": COMMON_MODULES + [f"industry: {s}" for s in v["services"]], **{k: v[k] for k in
            ("services", "roles", "agents", "kpis", "compliance", "integrations")}, "builder_prompt": prompt,
            "notes": ["Compliance items are prompts for professional review, not legal advice.",
                      "Nothing here is deployed or connected; integrations need the operator's own accounts and credentials."]}
