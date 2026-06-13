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
