"""
EZ-NEXUS AI — SQLAlchemy Models
Defines Business and Appointment tables with a one-to-many relationship.
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
import uuid


class Business(Base):
    __tablename__ = "businesses"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(200), nullable=False, index=True)
    industry    = Column(String(100), nullable=False)
    email       = Column(String(200), unique=True, nullable=False, index=True)
    phone       = Column(String(30), nullable=True)
    address     = Column(String(300), nullable=True)
    website     = Column(String(200), nullable=True)
    description         = Column(Text, nullable=True)
    revenue             = Column(Float, default=0.0)
    employees           = Column(Integer, default=1)
    is_active           = Column(Boolean, default=True)
    # Phase 2: staff notifications + AI phone config
    staff_email         = Column(String(200), nullable=True)
    twilio_phone_number = Column(String(30), nullable=True)
    ai_greeting         = Column(Text, nullable=True)
    require_approval    = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    # One-to-many: one business → many appointments
    appointments = relationship("Appointment", back_populates="business", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Business id={self.id} name='{self.name}'>"


class Appointment(Base):
    __tablename__ = "appointments"

    id             = Column(Integer, primary_key=True, index=True)
    business_id    = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    client_name    = Column(String(200), nullable=False)
    client_email   = Column(String(200), nullable=True)
    client_phone   = Column(String(30), nullable=True)
    service        = Column(String(200), nullable=False)
    notes          = Column(Text, nullable=True)
    call_summary   = Column(Text, nullable=True)      # AI-generated summary
    triage_result  = Column(String(50), nullable=True) # urgent | normal | low
    scheduled_at   = Column(DateTime(timezone=True), nullable=False)
    duration_mins  = Column(Integer, default=60)
    status         = Column(String(30), default="scheduled")  # scheduled | confirmed | completed | cancelled
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    # Many-to-one back-reference
    business = relationship("Business", back_populates="appointments")
    approval_token = relationship("ApprovalToken", back_populates="appointment", uselist=False)

    def __repr__(self):
        return f"<Appointment id={self.id} client='{self.client_name}' status='{self.status}'>"


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    email           = Column(String(200), unique=True, nullable=False, index=True)
    full_name       = Column(String(200), nullable=False, default="Admin")
    hashed_password = Column(String(300), nullable=False)
    is_admin        = Column(Boolean, default=False)
    is_active       = Column(Boolean, default=True)
    plan            = Column(String(50), default="starter")   # starter|professional|enterprise
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    last_login      = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<User id={self.id} email='{self.email}' admin={self.is_admin}>"


class AdminAlert(Base):
    __tablename__ = "admin_alerts"

    id         = Column(Integer, primary_key=True, index=True)
    severity   = Column(String(20), nullable=False)  # critical|warning|info
    module     = Column(String(50), nullable=False)
    message    = Column(Text, nullable=False)
    is_read    = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"

    id           = Column(Integer, primary_key=True, index=True)
    name         = Column(String(200), nullable=False)
    purpose      = Column(Text, nullable=False)
    spec_json    = Column(Text, nullable=True)   # Full JSON spec from Commander AI
    status       = Column(String(30), default="draft")  # draft|approved|active|archived
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    approved_at  = Column(DateTime(timezone=True), nullable=True)


class ApprovalToken(Base):
    """One-time token for staff to approve/reject an appointment via email link."""
    __tablename__ = "approval_tokens"

    id             = Column(Integer, primary_key=True, index=True)
    token          = Column(String(64), unique=True, index=True, default=lambda: uuid.uuid4().hex)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, unique=True)
    used           = Column(Boolean, default=False)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    appointment = relationship("Appointment", back_populates="approval_token")


# ── Healthcare / DME / Multi-tenant Models ───────────────────────────────────

class Contact(Base):
    """Patient or lead contact record (multi-tenant, linked to a business)."""
    __tablename__ = "contacts"

    id                 = Column(Integer, primary_key=True, index=True)
    business_id        = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name         = Column(String(100), nullable=False)
    last_name          = Column(String(100), nullable=False)
    email              = Column(String(200), nullable=True, index=True)
    phone              = Column(String(30), nullable=True)
    preferred_language = Column(String(20), default="en")
    consent_date       = Column(DateTime(timezone=True), nullable=True)
    consent_given      = Column(Boolean, default=False)
    tags               = Column(String(300), nullable=True)
    notes              = Column(Text, nullable=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())

    business       = relationship("Business")
    patient_intake = relationship("PatientIntake", back_populates="contact", uselist=False)


class PatientIntake(Base):
    """Healthcare / DME patient intake form."""
    __tablename__ = "patient_intakes"

    id                  = Column(Integer, primary_key=True, index=True)
    contact_id          = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, unique=True)
    date_of_birth       = Column(String(20), nullable=True)
    gender              = Column(String(20), nullable=True)
    address             = Column(String(300), nullable=True)
    insurance_name      = Column(String(200), nullable=True)
    insurance_member_id = Column(String(100), nullable=True)
    insurance_group_no  = Column(String(100), nullable=True)
    secondary_insurance = Column(String(200), nullable=True)
    diagnosis_codes     = Column(String(300), nullable=True)
    equipment_needed    = Column(String(300), nullable=True)
    prescribing_doctor  = Column(String(200), nullable=True)
    npi_number          = Column(String(20), nullable=True)
    status              = Column(String(30), default="pending")
    ai_notes            = Column(Text, nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())

    contact = relationship("Contact", back_populates="patient_intake")


class SupplierProduct(Base):
    """DME product listed by a supplier in the marketplace."""
    __tablename__ = "supplier_products"

    id              = Column(Integer, primary_key=True, index=True)
    supplier_name   = Column(String(200), nullable=False)
    supplier_email  = Column(String(200), nullable=True)
    name            = Column(String(300), nullable=False, index=True)
    category        = Column(String(100), nullable=False)
    hcpcs_code      = Column(String(20), nullable=True)
    description     = Column(Text, nullable=True)
    unit_price      = Column(Float, nullable=True)
    is_available    = Column(Boolean, default=True)
    lead_time_days  = Column(Integer, default=1)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class AgentTask(Base):
    """Persisted log of every task dispatched to a specialized agent."""
    __tablename__ = "agent_tasks"

    id           = Column(Integer, primary_key=True, index=True)
    agent_name   = Column(String(100), nullable=False, index=True)
    task_type    = Column(String(100), nullable=False)
    status       = Column(String(20), default="pending")
    input_data   = Column(Text, nullable=True)
    output_data  = Column(Text, nullable=True)
    error_msg    = Column(Text, nullable=True)
    duration_ms  = Column(Integer, nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class CallLog(Base):
    """Inbound/outbound call record."""
    __tablename__ = "call_logs"

    id             = Column(Integer, primary_key=True, index=True)
    business_id    = Column(Integer, ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True)
    call_sid       = Column(String(64), unique=True, nullable=True, index=True)
    direction      = Column(String(10), default="inbound")
    caller_phone   = Column(String(30), nullable=True)
    called_phone   = Column(String(30), nullable=True)
    duration_secs  = Column(Integer, nullable=True)
    status         = Column(String(20), default="in-progress")
    ai_summary     = Column(Text, nullable=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())


# ── Data Entry / Document Automation Models ───────────────────────────────────

class Patient(Base):
    """Detailed patient record for healthcare / DME workflows."""
    __tablename__ = "patients"

    id                = Column(Integer, primary_key=True, index=True)
    business_id       = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name        = Column(String(120), nullable=False)
    last_name         = Column(String(120), nullable=False)
    date_of_birth     = Column(String(40), nullable=True)
    phone             = Column(String(40), nullable=True)
    email             = Column(String(255), nullable=True)
    address           = Column(Text, nullable=True)
    city              = Column(String(100), nullable=True)
    state             = Column(String(50), nullable=True)
    zip_code          = Column(String(20), nullable=True)
    emergency_contact = Column(String(255), nullable=True)
    preferred_language = Column(String(20), default="en")
    notes             = Column(Text, nullable=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())

    insurance_profiles = relationship("InsuranceProfile", back_populates="patient", cascade="all, delete-orphan")
    equipment_requests  = relationship("EquipmentRequest", back_populates="patient", cascade="all, delete-orphan")


class InsuranceProfile(Base):
    """Insurance card / eligibility record linked to a patient."""
    __tablename__ = "insurance_profiles"

    id                       = Column(Integer, primary_key=True, index=True)
    patient_id               = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    payer_name               = Column(String(255), nullable=True)
    plan_type                = Column(String(100), nullable=True)
    member_id                = Column(String(120), nullable=True)
    group_number             = Column(String(120), nullable=True)
    policy_holder            = Column(String(255), nullable=True)
    relationship_to_patient  = Column(String(80), nullable=True)
    phone_number             = Column(String(40), nullable=True)
    eligibility_status       = Column(String(80), default="unknown")  # unknown|eligible|ineligible|pending
    raw_payload              = Column(Text, nullable=True)  # JSON string of OCR/extracted data
    created_at               = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", back_populates="insurance_profiles")


class UploadedDocument(Base):
    """Tracks every document uploaded for data entry processing."""
    __tablename__ = "uploaded_documents"

    id                = Column(Integer, primary_key=True, index=True)
    business_id       = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id        = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)
    filename          = Column(String(255), nullable=False)
    content_type      = Column(String(120), nullable=True)
    storage_path      = Column(Text, nullable=False)
    document_type     = Column(String(80), default="unknown")   # pdf|scanned_pdf|image|word|spreadsheet|unknown
    extracted_text    = Column(Text, nullable=True)
    extraction_status = Column(String(80), default="pending")   # pending|completed|needs_review|failed
    confidence_score  = Column(Float, default=0.0)
    file_size_kb      = Column(Integer, nullable=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())

    data_entry_jobs = relationship("DataEntryJob", back_populates="document", cascade="all, delete-orphan")


class DataEntryJob(Base):
    """One AI data-extraction + admin-approval cycle."""
    __tablename__ = "data_entry_jobs"

    id                = Column(Integer, primary_key=True, index=True)
    business_id       = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id       = Column(Integer, ForeignKey("uploaded_documents.id", ondelete="SET NULL"), nullable=True)
    job_type          = Column(String(100), nullable=False)   # medical|bookkeeping|insurance|equipment
    status            = Column(String(80), default="draft")   # draft|pending_admin_approval|approved_ready_to_post|declined_needs_revision|posted
    extracted_fields  = Column(Text, nullable=True)   # JSON string
    missing_fields    = Column(Text, nullable=True)   # JSON array string
    validation_errors = Column(Text, nullable=True)   # JSON array string
    commander_recommendations = Column(Text, nullable=True)   # JSON array string
    admin_approved    = Column(Boolean, default=False)
    approval_notes    = Column(Text, nullable=True)
    created_by_agent  = Column(String(120), default="medical_data_entry_agent")
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), onupdate=func.now())

    document = relationship("UploadedDocument", back_populates="data_entry_jobs")


class EquipmentRequest(Base):
    """DME / medical equipment request linked to a patient."""
    __tablename__ = "equipment_requests"

    id                   = Column(Integer, primary_key=True, index=True)
    business_id          = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id           = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)
    equipment_type       = Column(String(180), nullable=False)
    diagnosis_or_reason  = Column(Text, nullable=True)
    prescribing_provider = Column(String(255), nullable=True)
    insurance_required   = Column(Boolean, default=True)
    prior_auth_required  = Column(Boolean, default=False)
    hcpcs_codes          = Column(String(200), nullable=True)   # comma-separated
    status               = Column(String(80), default="intake")  # intake|pending_auth|approved|denied|fulfilled
    notes                = Column(Text, nullable=True)
    created_at           = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", back_populates="equipment_requests")


class BookkeepingEntry(Base):
    """Receipt, invoice, expense, or revenue record extracted by AI."""
    __tablename__ = "bookkeeping_entries"

    id                  = Column(Integer, primary_key=True, index=True)
    business_id         = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    source_document_id  = Column(Integer, ForeignKey("uploaded_documents.id", ondelete="SET NULL"), nullable=True)
    entry_type          = Column(String(80), nullable=True)   # expense|revenue|invoice|receipt
    vendor_or_customer  = Column(String(255), nullable=True)
    transaction_date    = Column(String(40), nullable=True)
    amount              = Column(Float, default=0.0)
    category            = Column(String(120), nullable=True)
    memo                = Column(Text, nullable=True)
    tax_flag            = Column(Boolean, default=False)
    status              = Column(String(80), default="draft")   # draft|pending_admin_approval|approved|posted
    admin_approved      = Column(Boolean, default=False)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())


class MasterRecommendation(Base):
    """Commander AI-generated recommendation requiring admin review."""
    __tablename__ = "master_recommendations"

    id                   = Column(Integer, primary_key=True, index=True)
    business_id          = Column(Integer, ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True)
    module               = Column(String(120), nullable=False)
    severity             = Column(String(40), default="info")   # critical|warning|info
    title                = Column(String(255), nullable=False)
    detail               = Column(Text, nullable=True)
    recommended_action   = Column(Text, nullable=True)
    auto_fix_available   = Column(Boolean, default=False)
    admin_approved       = Column(Boolean, default=False)
    status               = Column(String(80), default="pending_admin_review")
    created_at           = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Immutable audit trail for all significant system actions."""
    __tablename__ = "audit_logs"

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True)
    actor       = Column(String(120), nullable=False)   # admin|agent_name|system
    action      = Column(String(180), nullable=False)
    entity_type = Column(String(120), nullable=True)
    entity_id   = Column(String(120), nullable=True)
    before_data = Column(Text, nullable=True)   # JSON string
    after_data  = Column(Text, nullable=True)   # JSON string
    ip_address  = Column(String(45), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


# ── CRM & Sales Module ────────────────────────────────────────────────────────

class Lead(Base):
    __tablename__ = "leads"

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name  = Column(String(120), nullable=False)
    last_name   = Column(String(120), nullable=True)
    email       = Column(String(200), nullable=True, index=True)
    phone       = Column(String(40), nullable=True)
    company     = Column(String(200), nullable=True)
    source      = Column(String(80), nullable=True)   # web|call|referral|social|campaign
    status      = Column(String(80), default="new")   # new|contacted|qualified|unqualified|converted
    score       = Column(Integer, default=0)           # AI lead score 0–100
    assigned_to = Column(String(120), nullable=True)
    notes       = Column(Text, nullable=True)
    ai_notes    = Column(Text, nullable=True)
    tags        = Column(String(300), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    deals = relationship("Deal", back_populates="lead", cascade="all, delete-orphan")


class Pipeline(Base):
    __tablename__ = "pipelines"

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name        = Column(String(200), nullable=False)
    stages      = Column(Text, nullable=True)   # JSON array of stage names
    is_default  = Column(Boolean, default=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    deals = relationship("Deal", back_populates="pipeline")


class Deal(Base):
    __tablename__ = "deals"

    id             = Column(Integer, primary_key=True, index=True)
    business_id    = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_id    = Column(Integer, ForeignKey("pipelines.id", ondelete="SET NULL"), nullable=True)
    lead_id        = Column(Integer, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    title          = Column(String(300), nullable=False)
    stage          = Column(String(120), default="prospecting")
    value          = Column(Float, default=0.0)
    probability    = Column(Integer, default=20)    # 0–100
    expected_close = Column(String(40), nullable=True)
    assigned_to    = Column(String(120), nullable=True)
    status         = Column(String(80), default="open")   # open|won|lost
    notes          = Column(Text, nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())

    lead     = relationship("Lead", back_populates="deals")
    pipeline = relationship("Pipeline", back_populates="deals")


class Quote(Base):
    __tablename__ = "quotes"

    id           = Column(Integer, primary_key=True, index=True)
    business_id  = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    deal_id      = Column(Integer, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    quote_number = Column(String(50), nullable=True, index=True)
    title        = Column(String(300), nullable=False)
    client_name  = Column(String(200), nullable=True)
    client_email = Column(String(200), nullable=True)
    line_items   = Column(Text, nullable=True)   # JSON array [{desc, qty, unit_price, total}]
    subtotal     = Column(Float, default=0.0)
    tax_rate     = Column(Float, default=0.0)
    total        = Column(Float, default=0.0)
    status       = Column(String(80), default="draft")   # draft|sent|accepted|declined|expired
    notes        = Column(Text, nullable=True)
    valid_until  = Column(String(40), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


# ── Recruitment & Staffing Module ──────────────────────────────────────────────

class JobPosting(Base):
    __tablename__ = "job_postings"

    id              = Column(Integer, primary_key=True, index=True)
    business_id     = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    title           = Column(String(300), nullable=False, index=True)
    department      = Column(String(120), nullable=True)
    location        = Column(String(200), nullable=True)
    job_type        = Column(String(80), default="full_time")   # full_time|part_time|contract|temporary|internship
    remote_option   = Column(String(80), default="on_site")     # on_site|remote|hybrid
    description     = Column(Text, nullable=True)
    requirements    = Column(Text, nullable=True)
    salary_min      = Column(Float, nullable=True)
    salary_max      = Column(Float, nullable=True)
    salary_currency = Column(String(10), default="USD")
    status          = Column(String(80), default="draft")   # draft|active|paused|closed|filled
    posted_boards   = Column(String(300), nullable=True)    # comma-sep: indeed,linkedin,ziprecruiter
    ai_description  = Column(Text, nullable=True)           # AI-optimized job description
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())

    applications = relationship("JobApplication", back_populates="job_posting", cascade="all, delete-orphan")


class Candidate(Base):
    __tablename__ = "candidates"

    id               = Column(Integer, primary_key=True, index=True)
    business_id      = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name       = Column(String(120), nullable=False)
    last_name        = Column(String(120), nullable=False)
    email            = Column(String(200), nullable=True, index=True)
    phone            = Column(String(40), nullable=True)
    location         = Column(String(200), nullable=True)
    linkedin_url     = Column(String(300), nullable=True)
    resume_path      = Column(Text, nullable=True)
    resume_text      = Column(Text, nullable=True)   # extracted for AI matching
    skills           = Column(Text, nullable=True)   # JSON array
    experience_years = Column(Integer, nullable=True)
    education        = Column(String(300), nullable=True)
    ai_summary       = Column(Text, nullable=True)
    ai_score         = Column(Float, default=0.0)
    status           = Column(String(80), default="active")   # active|inactive|hired|blacklisted
    notes            = Column(Text, nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    applications = relationship("JobApplication", back_populates="candidate", cascade="all, delete-orphan")


class JobApplication(Base):
    __tablename__ = "job_applications"

    id             = Column(Integer, primary_key=True, index=True)
    business_id    = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)
    candidate_id   = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    stage          = Column(String(80), default="applied")   # applied|screening|interview|offer|hired|rejected
    ai_match_score = Column(Float, default=0.0)
    ai_feedback    = Column(Text, nullable=True)
    recruiter_notes = Column(Text, nullable=True)
    interview_date = Column(String(40), nullable=True)
    offer_amount   = Column(Float, nullable=True)
    status         = Column(String(80), default="active")   # active|withdrawn|rejected|hired
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())

    job_posting = relationship("JobPosting", back_populates="applications")
    candidate   = relationship("Candidate", back_populates="applications")


# ── Marketing Suite Module ─────────────────────────────────────────────────────

class Campaign(Base):
    __tablename__ = "campaigns"

    id                 = Column(Integer, primary_key=True, index=True)
    business_id        = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name               = Column(String(300), nullable=False, index=True)
    campaign_type      = Column(String(80), default="email")   # email|sms|voice|social|multi_channel
    status             = Column(String(80), default="draft")   # draft|scheduled|active|paused|completed|cancelled
    subject            = Column(String(500), nullable=True)
    body               = Column(Text, nullable=True)
    ai_generated_body  = Column(Text, nullable=True)
    target_segment     = Column(String(200), nullable=True)    # all|leads|customers|inactive
    scheduled_at       = Column(DateTime(timezone=True), nullable=True)
    sent_count         = Column(Integer, default=0)
    open_count         = Column(Integer, default=0)
    click_count        = Column(Integer, default=0)
    conversion_count   = Column(Integer, default=0)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
    updated_at         = Column(DateTime(timezone=True), onupdate=func.now())


class MarketingForm(Base):
    __tablename__ = "marketing_forms"

    id               = Column(Integer, primary_key=True, index=True)
    business_id      = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name             = Column(String(300), nullable=False)
    form_type        = Column(String(80), default="lead_capture")   # lead_capture|survey|contact|appointment
    fields_json      = Column(Text, nullable=True)    # JSON array of field definitions
    thank_you_message = Column(Text, nullable=True)
    is_active        = Column(Boolean, default=True)
    submission_count = Column(Integer, default=0)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    submissions = relationship("FormSubmission", back_populates="form", cascade="all, delete-orphan")


class FormSubmission(Base):
    __tablename__ = "form_submissions"

    id          = Column(Integer, primary_key=True, index=True)
    form_id     = Column(Integer, ForeignKey("marketing_forms.id", ondelete="CASCADE"), nullable=False)
    business_id = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    data_json   = Column(Text, nullable=True)    # JSON object with form responses
    ip_address  = Column(String(45), nullable=True)
    source_url  = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    form = relationship("MarketingForm", back_populates="submissions")


# ── Communication Hub Module ───────────────────────────────────────────────────

class IVRConfig(Base):
    __tablename__ = "ivr_configs"

    id              = Column(Integer, primary_key=True, index=True)
    business_id     = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name            = Column(String(200), nullable=False)
    greeting_text   = Column(Text, nullable=True)
    menu_options    = Column(Text, nullable=True)   # JSON: [{key:"1", action:"transfer", target:"sales"}]
    fallback_action = Column(String(80), default="voicemail")   # voicemail|transfer|ai_agent
    ai_enabled      = Column(Boolean, default=True)
    ai_voice        = Column(String(80), default="nova")
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class PhoneNumber(Base):
    __tablename__ = "phone_numbers"

    id             = Column(Integer, primary_key=True, index=True)
    business_id    = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    number         = Column(String(30), nullable=False, index=True)
    number_type    = Column(String(40), default="local")    # local|toll_free|did|international
    provider       = Column(String(80), default="twilio")   # twilio|vonage|bandwidth
    is_active      = Column(Boolean, default=True)
    purpose        = Column(String(120), nullable=True)     # tracking|main|support|sales
    ivr_config_id  = Column(Integer, ForeignKey("ivr_configs.id", ondelete="SET NULL"), nullable=True)
    monthly_cost   = Column(Float, default=1.0)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())


# ── CallTrack AI Module ────────────────────────────────────────────────────────

class CallTrackingNumber(Base):
    __tablename__ = "call_tracking_numbers"

    id             = Column(Integer, primary_key=True, index=True)
    business_id    = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    phone_number_id = Column(Integer, ForeignKey("phone_numbers.id", ondelete="SET NULL"), nullable=True)
    campaign_name  = Column(String(200), nullable=False)
    source         = Column(String(120), nullable=True)    # google|facebook|email|direct
    medium         = Column(String(120), nullable=True)    # cpc|organic|email|referral
    utm_campaign   = Column(String(200), nullable=True)
    total_calls    = Column(Integer, default=0)
    conversions    = Column(Integer, default=0)
    is_active      = Column(Boolean, default=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())


class CallTrackingEvent(Base):
    __tablename__ = "call_tracking_events"

    id                  = Column(Integer, primary_key=True, index=True)
    tracking_number_id  = Column(Integer, ForeignKey("call_tracking_numbers.id", ondelete="SET NULL"), nullable=True)
    business_id         = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    caller_phone        = Column(String(40), nullable=True)
    call_duration_secs  = Column(Integer, default=0)
    is_conversion       = Column(Boolean, default=False)
    sentiment           = Column(String(40), nullable=True)    # positive|neutral|negative
    ai_summary          = Column(Text, nullable=True)
    revenue_attributed  = Column(Float, default=0.0)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())


# ── Contact Center Module ──────────────────────────────────────────────────────

class AgentQueue(Base):
    __tablename__ = "agent_queues"

    id               = Column(Integer, primary_key=True, index=True)
    business_id      = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name             = Column(String(200), nullable=False)
    queue_type       = Column(String(80), default="inbound")   # inbound|outbound|blended
    max_wait_secs    = Column(Integer, default=120)
    greeting_message = Column(Text, nullable=True)
    agents_assigned  = Column(Text, nullable=True)   # JSON array of agent emails/names
    is_active        = Column(Boolean, default=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())


# ── Automation & Workflow Engine ───────────────────────────────────────────────

class Workflow(Base):
    __tablename__ = "workflows"

    id             = Column(Integer, primary_key=True, index=True)
    business_id    = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name           = Column(String(300), nullable=False, index=True)
    description    = Column(Text, nullable=True)
    trigger_type   = Column(String(80), nullable=False)   # new_lead|appointment|form_submit|schedule|webhook|manual
    trigger_config = Column(Text, nullable=True)          # JSON config
    steps          = Column(Text, nullable=True)          # JSON array of step definitions
    is_active      = Column(Boolean, default=False)
    run_count      = Column(Integer, default=0)
    last_run_at    = Column(DateTime(timezone=True), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())

    executions = relationship("WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan")


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id              = Column(Integer, primary_key=True, index=True)
    workflow_id     = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    business_id     = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    status          = Column(String(80), default="running")   # running|completed|failed|cancelled
    trigger_data    = Column(Text, nullable=True)             # JSON
    steps_completed = Column(Integer, default=0)
    error_message   = Column(Text, nullable=True)
    started_at      = Column(DateTime(timezone=True), server_default=func.now())
    completed_at    = Column(DateTime(timezone=True), nullable=True)

    workflow = relationship("Workflow", back_populates="executions")


class WebhookConfig(Base):
    __tablename__ = "webhook_configs"

    id                = Column(Integer, primary_key=True, index=True)
    business_id       = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name              = Column(String(200), nullable=False)
    url               = Column(Text, nullable=False)
    events            = Column(String(300), nullable=True)   # comma-separated event types
    secret_key        = Column(String(64), nullable=True)
    is_active         = Column(Boolean, default=True)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    fail_count        = Column(Integer, default=0)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())


# ── SmartBoss AI — Analytics Snapshots ────────────────────────────────────────

class SmartBossInsight(Base):
    __tablename__ = "smartboss_insights"

    id              = Column(Integer, primary_key=True, index=True)
    business_id     = Column(Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=True, index=True)
    insight_type    = Column(String(80), nullable=False)   # revenue|lead|campaign|recruitment|operations
    title           = Column(String(300), nullable=False)
    summary         = Column(Text, nullable=True)
    data_json       = Column(Text, nullable=True)    # JSON payload for charts
    recommendation  = Column(Text, nullable=True)
    priority        = Column(String(40), default="medium")   # high|medium|low
    is_read         = Column(Boolean, default=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
