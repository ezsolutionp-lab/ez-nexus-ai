"""
MO NEXUS OMEGA — Module catalog.

The catalog is how plain English becomes structure. Each module declares the
signals that imply it, the requirements it brings, the data it needs, the pages
and agents it implies, and the third-party providers it depends on.

This is deliberately rule-based and deterministic: it produces the same spec for
the same prompt, runs with no model provider configured, and can be unit-tested.
The model-assisted path in `requirements.py` *enriches* this; it never replaces
it, so a missing API key degrades detail rather than breaking the build.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str                      # string|text|integer|float|boolean|datetime|date|json|enum
    required: bool = False
    unique: bool = False
    indexed: bool = False
    default: Any = None
    enum_values: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "type": self.type, "required": self.required,
            "unique": self.unique, "indexed": self.indexed, "default": self.default,
            "enum_values": list(self.enum_values), "description": self.description,
        }


@dataclass(frozen=True)
class ModelSpec:
    name: str                      # PascalCase entity
    table: str
    description: str
    fields: tuple[FieldSpec, ...]
    relations: tuple[dict[str, str], ...] = ()
    tenant_scoped: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "table": self.table, "description": self.description,
            "fields": [f.to_dict() for f in self.fields],
            "relations": [dict(r) for r in self.relations],
            "tenant_scoped": self.tenant_scoped,
        }


@dataclass(frozen=True)
class PageSpec:
    name: str
    route: str
    title: str
    kind: str = "public"           # public | portal | admin
    requires_auth: bool = False
    sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentSpec:
    name: str
    role: str
    purpose: str
    instructions: str
    tools: tuple[str, ...] = ()
    autonomy: str = "SUPERVISED"
    approval_gates: tuple[str, ...] = ()
    capability: str = "general"


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    trigger_type: str
    nodes: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class IntegrationSpec:
    provider: str
    capability: str
    auth_kind: str
    credential_env_var: str


@dataclass(frozen=True)
class RequirementSpec:
    category: str
    key: str
    statement: str
    acceptance: str
    priority: str = "SHOULD"


@dataclass(frozen=True)
class Module:
    """One coherent capability a project can include."""

    key: str
    label: str
    signals: tuple[str, ...]
    requirements: tuple[RequirementSpec, ...] = ()
    models: tuple[ModelSpec, ...] = ()
    pages: tuple[PageSpec, ...] = ()
    agents: tuple[AgentSpec, ...] = ()
    workflows: tuple[WorkflowSpec, ...] = ()
    integrations: tuple[IntegrationSpec, ...] = ()
    implied_by_domain: tuple[str, ...] = ()


# ── Reusable field groups ────────────────────────────────────────────────────

def _contact_fields() -> tuple[FieldSpec, ...]:
    return (
        FieldSpec("full_name", "string", required=True, indexed=True),
        FieldSpec("email", "string", indexed=True),
        FieldSpec("phone", "string", indexed=True),
    )


def _address_fields() -> tuple[FieldSpec, ...]:
    return (
        FieldSpec("address_line1", "string"),
        FieldSpec("city", "string"),
        FieldSpec("state", "string"),
        FieldSpec("postal_code", "string", indexed=True),
    )


# ── Modules ──────────────────────────────────────────────────────────────────

MODULES: tuple[Module, ...] = (
    Module(
        key="website",
        label="Public website",
        signals=("website", "site", "landing page", "web page", "homepage", "marketing site"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "site.pages",
                            "The public site presents home, services, about and contact pages.",
                            "Each page returns HTTP 200 and renders its heading.", "MUST"),
            RequirementSpec("NONFUNCTIONAL", "site.responsive",
                            "Pages are responsive from 320px upward.",
                            "No horizontal body scroll at 320px width.", "MUST"),
            RequirementSpec("NONFUNCTIONAL", "site.seo",
                            "Every page carries a title, meta description and canonical URL.",
                            "Generated HTML contains title and meta[name=description].", "SHOULD"),
        ),
        pages=(
            PageSpec("Home", "/", "Home", sections=("hero", "services", "testimonials", "cta")),
            PageSpec("Services", "/services", "Our Services", sections=("service-grid", "cta")),
            PageSpec("About", "/about", "About Us", sections=("story", "team")),
            PageSpec("Contact", "/contact", "Contact Us", sections=("contact-form", "map")),
        ),
    ),
    Module(
        key="contact_form",
        label="Contact form",
        signals=("contact form", "enquiry", "inquiry", "get in touch", "contact us"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "contact.submit",
                            "Visitors submit an enquiry that is stored and acknowledged.",
                            "POST /api/enquiries returns 201 and persists the row.", "MUST"),
            RequirementSpec("SECURITY", "contact.validation",
                            "Enquiry input is validated and rate limited.",
                            "Oversized or malformed payloads are rejected with 422.", "MUST"),
        ),
        models=(
            ModelSpec("Enquiry", "enquiries", "A message submitted from the public site.",
                      _contact_fields() + (
                          FieldSpec("subject", "string"),
                          FieldSpec("message", "text", required=True),
                          FieldSpec("status", "enum", default="new",
                                    enum_values=("new", "in_progress", "closed"), indexed=True),
                      )),
        ),
    ),
    Module(
        key="crm",
        label="CRM and lead pipeline",
        signals=("crm", "customer record", "customer management", "lead", "pipeline",
                 "sales pipeline", "contacts", "customer database"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "crm.customers",
                            "Staff create, read, update and archive customer records.",
                            "Full CRUD available on /api/customers with auth.", "MUST"),
            RequirementSpec("FUNCTIONAL", "crm.pipeline",
                            "Leads move through named pipeline stages.",
                            "Stage transitions are persisted and auditable.", "MUST"),
        ),
        models=(
            ModelSpec("Customer", "customers", "A person or company the business serves.",
                      _contact_fields() + _address_fields() + (
                          FieldSpec("company", "string"),
                          FieldSpec("notes", "text"),
                          FieldSpec("is_active", "boolean", default=True, indexed=True),
                      )),
            ModelSpec("Lead", "leads", "An unqualified or in-progress sales opportunity.",
                      _contact_fields() + (
                          FieldSpec("source", "string", indexed=True),
                          FieldSpec("stage", "enum", default="new", indexed=True,
                                    enum_values=("new", "contacted", "qualified", "quoted", "won", "lost")),
                          FieldSpec("estimated_value", "float", default=0.0),
                          FieldSpec("notes", "text"),
                      )),
        ),
        pages=(PageSpec("CRM", "/app/crm", "Customers & Leads", kind="admin", requires_auth=True,
                        sections=("customer-table", "lead-pipeline")),),
        agents=(
            AgentSpec(
                name="Lead Qualification Agent", role="qualifier",
                purpose="Score inbound leads and recommend the next action.",
                instructions=(
                    "You qualify inbound leads for a service business. Given the lead's details, "
                    "return a score from 1 to 10, the single most likely service required, and one "
                    "concrete next action. If the lead lacks contact details, say so plainly and "
                    "score it 1 — never invent contact information."
                ),
                tools=("core.echo",), capability="reasoning",
            ),
        ),
    ),
    Module(
        key="booking",
        label="Online booking",
        signals=("booking", "book online", "appointment", "scheduling", "schedule a",
                 "reservation", "calendar"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "booking.create",
                            "Customers book an appointment slot online.",
                            "POST /api/bookings persists the booking and returns 201.", "MUST"),
            RequirementSpec("FUNCTIONAL", "booking.conflict",
                            "Double-booking a technician for the same slot is rejected.",
                            "A conflicting booking returns 409.", "MUST"),
        ),
        models=(
            ModelSpec("Booking", "bookings", "A scheduled visit or appointment.",
                      (
                          FieldSpec("customer_id", "integer", required=True, indexed=True),
                          FieldSpec("service", "string", required=True),
                          FieldSpec("scheduled_for", "datetime", required=True, indexed=True),
                          FieldSpec("duration_minutes", "integer", default=60),
                          FieldSpec("status", "enum", default="requested", indexed=True,
                                    enum_values=("requested", "confirmed", "completed", "cancelled")),
                          FieldSpec("notes", "text"),
                      ),
                      relations=({"field": "customer_id", "references": "customers", "kind": "many_to_one"},)),
        ),
        pages=(PageSpec("Book", "/book", "Book a Visit", sections=("booking-form",)),),
        agents=(
            AgentSpec(
                name="Booking Agent", role="scheduler",
                purpose="Turn a free-text booking request into a structured slot proposal.",
                instructions=(
                    "You schedule service visits. From the customer's message, extract the service "
                    "needed, the urgency, and up to three candidate time windows. Return strict JSON "
                    "with keys service, urgency, windows. If the message does not state a time "
                    "preference, return an empty windows list rather than guessing."
                ),
                tools=("core.echo",), capability="extraction",
                approval_gates=("booking.confirm",),
            ),
        ),
        workflows=(
            WorkflowSpec("Booking confirmation", "event", (
                {"id": "trigger", "type": "Trigger", "event": "booking.created"},
                {"id": "notify_customer", "type": "Tool", "tool": "comms.send_email"},
                {"id": "notify_dispatch", "type": "Event", "topic": "dispatch.queue"},
                {"id": "done", "type": "Output"},
            )),
        ),
    ),
    Module(
        key="dispatch",
        label="Dispatch and work orders",
        signals=("dispatch", "work order", "job assignment", "dispatcher", "field service"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "dispatch.assign",
                            "A dispatcher assigns a work order to an available technician.",
                            "Assignment writes technician_id and emits dispatch.assigned.", "MUST"),
        ),
        models=(
            ModelSpec("WorkOrder", "work_orders", "A unit of field work derived from a booking.",
                      (
                          FieldSpec("booking_id", "integer", indexed=True),
                          FieldSpec("customer_id", "integer", required=True, indexed=True),
                          FieldSpec("technician_id", "integer", indexed=True),
                          FieldSpec("summary", "string", required=True),
                          FieldSpec("details", "text"),
                          FieldSpec("priority", "enum", default="normal",
                                    enum_values=("low", "normal", "urgent")),
                          FieldSpec("status", "enum", default="unassigned", indexed=True,
                                    enum_values=("unassigned", "assigned", "en_route", "on_site",
                                                 "completed", "cancelled")),
                          FieldSpec("scheduled_for", "datetime", indexed=True),
                      ),
                      relations=(
                          {"field": "customer_id", "references": "customers", "kind": "many_to_one"},
                          {"field": "technician_id", "references": "technicians", "kind": "many_to_one"},
                      )),
            ModelSpec("Technician", "technicians", "A field engineer who completes work orders.",
                      _contact_fields() + (
                          FieldSpec("skills", "string"),
                          FieldSpec("is_available", "boolean", default=True, indexed=True),
                      )),
        ),
        pages=(PageSpec("Dispatch", "/app/dispatch", "Dispatch Board", kind="admin",
                        requires_auth=True, sections=("job-queue", "technician-status", "map")),),
        agents=(
            AgentSpec(
                name="Dispatch Agent", role="dispatcher",
                purpose="Recommend which technician should take a work order.",
                instructions=(
                    "You assign field work. Given a work order and a list of technicians with their "
                    "skills and availability, recommend one technician and give a one-sentence reason. "
                    "If no technician has the required skill or is available, say so explicitly and "
                    "recommend none — do not assign an unqualified technician."
                ),
                tools=("core.echo",), capability="reasoning",
                approval_gates=("dispatch.assign",),
            ),
        ),
    ),
    Module(
        key="technician_workflow",
        label="Technician mobile workflow",
        signals=("technician workflow", "technician mobile", "field app", "mobile dashboard",
                 "technician dashboard", "engineer app"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "tech.status",
                            "A technician updates job status from a mobile-first view.",
                            "PATCH /api/work-orders/{id} accepts a status transition.", "MUST"),
            RequirementSpec("NONFUNCTIONAL", "tech.mobile",
                            "The technician view is usable one-handed on a 360px screen.",
                            "Controls have a 44px minimum touch target.", "SHOULD"),
        ),
        pages=(PageSpec("Technician", "/app/technician", "My Jobs", kind="portal",
                        requires_auth=True, sections=("job-list", "status-actions")),),
    ),
    Module(
        key="customer_portal",
        label="Customer portal",
        signals=("customer portal", "client portal", "self-service", "my account", "customer login"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "portal.history",
                            "Customers sign in and view their bookings and invoices.",
                            "Portal endpoints return only the signed-in customer's rows.", "MUST"),
            RequirementSpec("SECURITY", "portal.isolation",
                            "A customer can never read another customer's records.",
                            "Cross-customer access returns 403 and is covered by a test.", "MUST"),
        ),
        pages=(PageSpec("Portal", "/portal", "My Account", kind="portal", requires_auth=True,
                        sections=("my-bookings", "my-invoices")),),
    ),
    Module(
        key="invoicing",
        label="Invoicing",
        signals=("invoice", "invoicing", "billing", "quote", "estimate"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "invoice.issue",
                            "Staff issue an invoice against a completed work order.",
                            "POST /api/invoices returns 201 with a unique invoice number.", "MUST"),
            RequirementSpec("FUNCTIONAL", "invoice.totals",
                            "Invoice totals are computed server-side from line items.",
                            "A tampered client total is ignored.", "MUST"),
        ),
        models=(
            ModelSpec("Invoice", "invoices", "A billing document issued to a customer.",
                      (
                          FieldSpec("invoice_number", "string", required=True, unique=True, indexed=True),
                          FieldSpec("customer_id", "integer", required=True, indexed=True),
                          FieldSpec("work_order_id", "integer", indexed=True),
                          FieldSpec("subtotal", "float", default=0.0),
                          FieldSpec("tax", "float", default=0.0),
                          FieldSpec("total", "float", default=0.0),
                          FieldSpec("currency", "string", default="USD"),
                          FieldSpec("status", "enum", default="draft", indexed=True,
                                    enum_values=("draft", "sent", "paid", "void")),
                          FieldSpec("issued_at", "datetime"),
                          FieldSpec("due_at", "datetime"),
                      ),
                      relations=({"field": "customer_id", "references": "customers", "kind": "many_to_one"},)),
        ),
        pages=(PageSpec("Invoices", "/app/invoices", "Invoices", kind="admin", requires_auth=True,
                        sections=("invoice-table",)),),
    ),
    Module(
        key="payments",
        label="Payments",
        signals=("payment", "pay online", "card payment", "checkout", "stripe", "take payment"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "payments.capture",
                            "Customers pay an invoice through a payment provider.",
                            "Payment capture is attempted only against a configured provider.", "MUST"),
            RequirementSpec("SECURITY", "payments.no_card_storage",
                            "Card details never touch application storage.",
                            "No model or log field holds a PAN or CVV.", "MUST"),
        ),
        integrations=(IntegrationSpec("payments", "charge", "api_key", "PAYMENTS_API_KEY"),),
    ),
    Module(
        key="notifications",
        label="Email and SMS notifications",
        signals=("notification", "email confirmation", "sms", "text message", "reminder", "alert"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "notify.booking",
                            "A booking confirmation is sent to the customer.",
                            "Send is attempted only when the provider is configured; "
                            "otherwise the job records CREDENTIAL_REQUIRED.", "MUST"),
        ),
        integrations=(
            IntegrationSpec("smtp", "send_email", "password", "SMTP_PASSWORD"),
            IntegrationSpec("twilio", "send_sms", "auth_token", "TWILIO_AUTH_TOKEN"),
        ),
        agents=(
            AgentSpec(
                name="Follow-Up Agent", role="retention",
                purpose="Draft a follow-up message after a completed job.",
                instructions=(
                    "You write short post-visit follow-up messages for a service business. "
                    "Keep it under 300 characters, reference the service performed, and invite a "
                    "review. Never promise a discount, refund, or timeline the input does not state."
                ),
                tools=("comms.send_email",), capability="general",
                approval_gates=("comms.mass_send",),
            ),
        ),
    ),
    Module(
        key="maps",
        label="Maps and routing",
        signals=("map", "maps", "routing", "directions", "geolocation", "service area"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "maps.route",
                            "Technician routes are shown on a map.",
                            "Route rendering is attempted only with a configured maps provider.", "SHOULD"),
        ),
        integrations=(IntegrationSpec("maps", "geocode_and_route", "api_key", "MAPS_API_KEY"),),
    ),
    Module(
        key="voice_receptionist",
        label="AI voice receptionist",
        signals=("voice receptionist", "ai receptionist", "answer the phone", "phone agent",
                 "virtual receptionist", "call answering"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "voice.intake",
                            "Inbound calls are answered and turned into a booking or callback.",
                            "The call flow records a transcript and a structured outcome.", "MUST"),
            RequirementSpec("SECURITY", "voice.governance",
                            "Voice requests pass the same auth, policy and approval layers as HTTP.",
                            "A voice-initiated high-risk action still requires approval.", "MUST"),
        ),
        integrations=(IntegrationSpec("twilio", "voice", "auth_token", "TWILIO_AUTH_TOKEN"),),
        agents=(
            AgentSpec(
                name="Voice Receptionist Agent", role="receptionist",
                purpose="Handle an inbound call and capture the caller's intent.",
                instructions=(
                    "You answer the phone for a service business. Greet the caller, establish the "
                    "problem, the address, and a callback number. Return strict JSON with keys "
                    "caller_name, problem, address, callback, urgency. Leave a field empty rather "
                    "than guessing it. Never quote a price."
                ),
                tools=("core.echo",), capability="extraction",
                approval_gates=("booking.confirm",),
            ),
        ),
    ),
    Module(
        key="reporting",
        label="Reporting and analytics",
        signals=("report", "reporting", "analytics", "dashboard", "kpi", "metrics", "insights"),
        requirements=(
            RequirementSpec("FUNCTIONAL", "reporting.summary",
                            "An operations dashboard summarises jobs, revenue and pipeline.",
                            "GET /api/reports/summary returns counts computed from live rows.", "SHOULD"),
        ),
        pages=(PageSpec("Reports", "/app/reports", "Reports", kind="admin", requires_auth=True,
                        sections=("kpi-row", "charts")),),
    ),
    Module(
        key="auth",
        label="Authentication and roles",
        signals=("login", "sign in", "authentication", "user account", "roles", "permissions", "portal"),
        requirements=(
            RequirementSpec("SECURITY", "auth.password_hashing",
                            "Passwords are stored only as bcrypt hashes.",
                            "No plaintext password appears in storage or logs.", "MUST"),
            RequirementSpec("SECURITY", "auth.server_side_authz",
                            "Authorization is enforced server-side on every protected route.",
                            "An unauthenticated call to a protected route returns 401.", "MUST"),
            RequirementSpec("SECURITY", "auth.tenant_scope",
                            "Every query is scoped to the caller's tenant.",
                            "A cross-tenant read returns 403 or an empty set, never another tenant's row.", "MUST"),
        ),
        models=(
            ModelSpec("AppUser", "app_users", "An authenticated user of the generated application.",
                      (
                          FieldSpec("email", "string", required=True, unique=True, indexed=True),
                          FieldSpec("full_name", "string", required=True),
                          FieldSpec("hashed_password", "string", required=True),
                          FieldSpec("role", "enum", default="staff", indexed=True,
                                    enum_values=("owner", "dispatcher", "technician", "staff", "customer")),
                          FieldSpec("is_active", "boolean", default=True),
                      )),
        ),
    ),
)


MODULES_BY_KEY: dict[str, Module] = {m.key: m for m in MODULES}


# Domains imply a baseline set of modules even when the prompt omits them.
# Each inference is recorded as an assumption so it is never mistaken for a request.
DOMAIN_PROFILES: dict[str, dict[str, Any]] = {
    "field_service": {
        "signals": ("plumbing", "plumber", "hvac", "electrician", "electrical", "roofing",
                    "locksmith", "pest control", "landscaping", "cleaning service",
                    "field service", "home service", "trades"),
        "modules": ("website", "contact_form", "auth", "crm", "booking", "dispatch",
                    "technician_workflow", "customer_portal", "invoicing", "notifications", "reporting"),
        "rationale": "Field-service businesses need lead capture, scheduling, dispatch and billing "
                     "to operate; omitting any one leaves the workflow broken.",
    },
    "ecommerce": {
        "signals": ("online store", "storefront", "e-commerce", "ecommerce", "sell products", "shop"),
        "modules": ("website", "auth", "crm", "payments", "notifications", "reporting"),
        "rationale": "A storefront needs catalogue, accounts, payment and order notification.",
    },
    "professional_services": {
        "signals": ("consultancy", "law firm", "accounting firm", "agency", "clinic", "practice"),
        "modules": ("website", "contact_form", "auth", "crm", "booking", "invoicing", "notifications"),
        "rationale": "Professional practices need enquiry capture, scheduling and billing.",
    },
}
