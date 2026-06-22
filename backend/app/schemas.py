"""
EZ-NEXUS AI — Pydantic Schemas
Request/response models for validation and serialisation.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, field_validator


# ─── Business Schemas ──────────────────────────────────────────────────────────

class BusinessCreate(BaseModel):
    name:                str
    industry:            str
    email:               EmailStr
    phone:               Optional[str] = None
    address:             Optional[str] = None
    website:             Optional[str] = None
    description:         Optional[str] = None
    revenue:             Optional[float] = 0.0
    employees:           Optional[int] = 1
    staff_email:         Optional[str] = None
    twilio_phone_number: Optional[str] = None
    ai_greeting:         Optional[str] = None
    require_approval:    Optional[bool] = True

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Business name cannot be empty")
        return v.strip()


class BusinessUpdate(BaseModel):
    name:                Optional[str] = None
    industry:            Optional[str] = None
    phone:               Optional[str] = None
    address:             Optional[str] = None
    website:             Optional[str] = None
    description:         Optional[str] = None
    revenue:             Optional[float] = None
    employees:           Optional[int] = None
    is_active:           Optional[bool] = None
    staff_email:         Optional[str] = None
    twilio_phone_number: Optional[str] = None
    ai_greeting:         Optional[str] = None
    require_approval:    Optional[bool] = None


class BusinessOut(BaseModel):
    id:                  int
    name:                str
    industry:            str
    email:               str
    phone:               Optional[str]
    address:             Optional[str]
    website:             Optional[str]
    description:         Optional[str]
    revenue:             float
    employees:           int
    is_active:           bool
    staff_email:         Optional[str]
    twilio_phone_number: Optional[str]
    ai_greeting:         Optional[str]
    require_approval:    bool
    created_at:          datetime

    model_config = {"from_attributes": True}


# ─── Appointment Schemas ───────────────────────────────────────────────────────

class AppointmentCreate(BaseModel):
    business_id:   int
    client_name:   str
    client_email:  Optional[str] = None
    client_phone:  Optional[str] = None
    service:       str
    notes:         Optional[str] = None
    scheduled_at:  datetime
    duration_mins: Optional[int] = 60

    @field_validator("client_name", "service")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()


class AppointmentUpdate(BaseModel):
    client_name:   Optional[str] = None
    client_email:  Optional[str] = None
    client_phone:  Optional[str] = None
    service:       Optional[str] = None
    notes:         Optional[str] = None
    scheduled_at:  Optional[datetime] = None
    duration_mins: Optional[int] = None
    status:        Optional[str] = None
    call_summary:  Optional[str] = None
    triage_result: Optional[str] = None


class AppointmentOut(BaseModel):
    id:             int
    business_id:    int
    client_name:    str
    client_email:   Optional[str]
    client_phone:   Optional[str]
    service:        str
    notes:          Optional[str]
    call_summary:   Optional[str]
    triage_result:  Optional[str]
    scheduled_at:   datetime
    duration_mins:  int
    status:         str
    created_at:     datetime

    model_config = {"from_attributes": True}


# ─── AI Schemas ────────────────────────────────────────────────────────────────

class CallSummaryRequest(BaseModel):
    transcript: str
    appointment_id: Optional[int] = None


class CallSummaryResponse(BaseModel):
    summary:      str
    triage:       str   # urgent | normal | low
    action_items: List[str]
    sentiment:    str   # positive | neutral | negative


# ─── Notification Schema ───────────────────────────────────────────────────────

class NotificationOut(BaseModel):
    type:    str
    message: str
    data:    Optional[dict] = None


# ─── Auth / User Schemas ──────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email:     EmailStr
    password:  str
    full_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("New password must be at least 8 characters")
        return v


class UserOut(BaseModel):
    id:         int
    email:      str
    full_name:  str
    is_admin:   bool
    is_active:  bool
    plan:       str
    created_at: datetime
    last_login: Optional[datetime]

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type:   str
    user:         UserOut


# ─── Commander AI Schemas ──────────────────────────────────────────────────────

class CommanderChatRequest(BaseModel):
    message: str


class CommanderChatResponse(BaseModel):
    reply:      str
    checked_at: str


class AgentGenRequest(BaseModel):
    description: str


class AgentGenResponse(BaseModel):
    agent_definition_id: Optional[int] = None
    name:                str
    purpose:             str
    workflow:            List[str]
    required_tools:      List[str]
    required_apis:       List[str]
    database_fields:     List[str]
    call_script:         str
    dashboard_widgets:   List[str]
    approval_rules:      List[str]
    testing_checklist:   List[str]
    estimated_dev_days:  int
    complexity:          str
    monthly_api_cost_estimate: Optional[str] = None


class AdminAlertOut(BaseModel):
    id:         int
    severity:   str
    module:     str
    message:    str
    is_read:    bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentDefinitionOut(BaseModel):
    id:          int
    name:        str
    purpose:     str
    status:      str
    created_at:  datetime
    approved_at: Optional[datetime]
    spec_json:   Optional[str]

    model_config = {"from_attributes": True}


# ─── Approval / Staff Schemas ─────────────────────────────────────────────────

class ApprovalAction(BaseModel):
    action: str  # "approve" | "reschedule" | "cancel"
    new_scheduled_at: Optional[datetime] = None
    note: Optional[str] = None


class ApprovalOut(BaseModel):
    appointment_id: int
    action: str
    message: str


# ─── Contact Schemas ──────────────────────────────────────────────────────────

class ContactCreate(BaseModel):
    business_id:        int
    first_name:         str
    last_name:          str
    email:              Optional[str] = None
    phone:              Optional[str] = None
    preferred_language: Optional[str] = "en"
    consent_given:      Optional[bool] = False
    tags:               Optional[str] = None
    notes:              Optional[str] = None


class ContactUpdate(BaseModel):
    first_name:         Optional[str] = None
    last_name:          Optional[str] = None
    email:              Optional[str] = None
    phone:              Optional[str] = None
    preferred_language: Optional[str] = None
    consent_given:      Optional[bool] = None
    tags:               Optional[str] = None
    notes:              Optional[str] = None


class ContactOut(BaseModel):
    id:                 int
    business_id:        int
    first_name:         str
    last_name:          str
    email:              Optional[str]
    phone:              Optional[str]
    preferred_language: str
    consent_given:      bool
    tags:               Optional[str]
    notes:              Optional[str]
    created_at:         datetime

    model_config = {"from_attributes": True}


# ─── Patient Intake Schemas ────────────────────────────────────────────────────

class PatientIntakeCreate(BaseModel):
    contact_id:          int
    date_of_birth:       Optional[str] = None
    gender:              Optional[str] = None
    address:             Optional[str] = None
    insurance_name:      Optional[str] = None
    insurance_member_id: Optional[str] = None
    insurance_group_no:  Optional[str] = None
    secondary_insurance: Optional[str] = None
    diagnosis_codes:     Optional[str] = None
    equipment_needed:    Optional[str] = None
    prescribing_doctor:  Optional[str] = None
    npi_number:          Optional[str] = None


class PatientIntakeUpdate(BaseModel):
    date_of_birth:       Optional[str] = None
    gender:              Optional[str] = None
    address:             Optional[str] = None
    insurance_name:      Optional[str] = None
    insurance_member_id: Optional[str] = None
    insurance_group_no:  Optional[str] = None
    secondary_insurance: Optional[str] = None
    diagnosis_codes:     Optional[str] = None
    equipment_needed:    Optional[str] = None
    prescribing_doctor:  Optional[str] = None
    npi_number:          Optional[str] = None
    status:              Optional[str] = None
    ai_notes:            Optional[str] = None


class PatientIntakeOut(BaseModel):
    id:                  int
    contact_id:          int
    date_of_birth:       Optional[str]
    gender:              Optional[str]
    address:             Optional[str]
    insurance_name:      Optional[str]
    insurance_member_id: Optional[str]
    insurance_group_no:  Optional[str]
    secondary_insurance: Optional[str]
    diagnosis_codes:     Optional[str]
    equipment_needed:    Optional[str]
    prescribing_doctor:  Optional[str]
    npi_number:          Optional[str]
    status:              str
    ai_notes:            Optional[str]
    created_at:          datetime

    model_config = {"from_attributes": True}


# ─── Supplier Product Schemas ──────────────────────────────────────────────────

class SupplierProductCreate(BaseModel):
    supplier_name:  str
    supplier_email: Optional[str] = None
    name:           str
    category:       str
    hcpcs_code:     Optional[str] = None
    description:    Optional[str] = None
    unit_price:     Optional[float] = None
    is_available:   Optional[bool] = True
    lead_time_days: Optional[int] = 1


class SupplierProductUpdate(BaseModel):
    supplier_name:  Optional[str] = None
    supplier_email: Optional[str] = None
    name:           Optional[str] = None
    category:       Optional[str] = None
    hcpcs_code:     Optional[str] = None
    description:    Optional[str] = None
    unit_price:     Optional[float] = None
    is_available:   Optional[bool] = None
    lead_time_days: Optional[int] = None


class SupplierProductOut(BaseModel):
    id:             int
    supplier_name:  str
    supplier_email: Optional[str]
    name:           str
    category:       str
    hcpcs_code:     Optional[str]
    description:    Optional[str]
    unit_price:     Optional[float]
    is_available:   bool
    lead_time_days: int
    created_at:     datetime

    model_config = {"from_attributes": True}


# ─── Agent Task Schemas ────────────────────────────────────────────────────────

class AgentRunRequest(BaseModel):
    agent_key:  str   # key from AGENT_REGISTRY, e.g. "intake"
    task_type:  str
    payload:    dict


class AgentTaskOut(BaseModel):
    id:           int
    agent_name:   str
    task_type:    str
    status:       str
    input_data:   Optional[str]
    output_data:  Optional[str]
    error_msg:    Optional[str]
    duration_ms:  Optional[int]
    created_at:   datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ─── Call Log Schemas ──────────────────────────────────────────────────────────

class CallLogOut(BaseModel):
    id:             int
    business_id:    Optional[int]
    call_sid:       Optional[str]
    direction:      str
    caller_phone:   Optional[str]
    called_phone:   Optional[str]
    duration_secs:  Optional[int]
    status:         str
    ai_summary:     Optional[str]
    appointment_id: Optional[int]
    created_at:     datetime

    model_config = {"from_attributes": True}


# ─── Patient Schemas ───────────────────────────────────────────────────────────

class PatientCreate(BaseModel):
    business_id:        int
    first_name:         str
    last_name:          str
    date_of_birth:      Optional[str] = None
    phone:              Optional[str] = None
    email:              Optional[str] = None
    address:            Optional[str] = None
    city:               Optional[str] = None
    state:              Optional[str] = None
    zip_code:           Optional[str] = None
    emergency_contact:  Optional[str] = None
    preferred_language: Optional[str] = "en"
    notes:              Optional[str] = None


class PatientUpdate(BaseModel):
    first_name:         Optional[str] = None
    last_name:          Optional[str] = None
    date_of_birth:      Optional[str] = None
    phone:              Optional[str] = None
    email:              Optional[str] = None
    address:            Optional[str] = None
    city:               Optional[str] = None
    state:              Optional[str] = None
    zip_code:           Optional[str] = None
    emergency_contact:  Optional[str] = None
    preferred_language: Optional[str] = None
    notes:              Optional[str] = None


class PatientOut(BaseModel):
    id:                 int
    business_id:        int
    first_name:         str
    last_name:          str
    date_of_birth:      Optional[str]
    phone:              Optional[str]
    email:              Optional[str]
    address:            Optional[str]
    city:               Optional[str]
    state:              Optional[str]
    zip_code:           Optional[str]
    emergency_contact:  Optional[str]
    preferred_language: str
    notes:              Optional[str]
    created_at:         datetime

    model_config = {"from_attributes": True}


# ─── Insurance Profile Schemas ─────────────────────────────────────────────────

class InsuranceProfileCreate(BaseModel):
    patient_id:              int
    payer_name:              Optional[str] = None
    plan_type:               Optional[str] = None
    member_id:               Optional[str] = None
    group_number:            Optional[str] = None
    policy_holder:           Optional[str] = None
    relationship_to_patient: Optional[str] = None
    phone_number:            Optional[str] = None
    eligibility_status:      Optional[str] = "unknown"
    raw_payload:             Optional[str] = None


class InsuranceProfileUpdate(BaseModel):
    payer_name:              Optional[str] = None
    plan_type:               Optional[str] = None
    member_id:               Optional[str] = None
    group_number:            Optional[str] = None
    policy_holder:           Optional[str] = None
    relationship_to_patient: Optional[str] = None
    phone_number:            Optional[str] = None
    eligibility_status:      Optional[str] = None
    raw_payload:             Optional[str] = None


class InsuranceProfileOut(BaseModel):
    id:                      int
    patient_id:              int
    payer_name:              Optional[str]
    plan_type:               Optional[str]
    member_id:               Optional[str]
    group_number:            Optional[str]
    policy_holder:           Optional[str]
    relationship_to_patient: Optional[str]
    phone_number:            Optional[str]
    eligibility_status:      str
    created_at:              datetime

    model_config = {"from_attributes": True}


# ─── Uploaded Document Schemas ─────────────────────────────────────────────────

class UploadedDocumentOut(BaseModel):
    id:                int
    business_id:       int
    patient_id:        Optional[int]
    filename:          str
    content_type:      Optional[str]
    document_type:     str
    extraction_status: str
    confidence_score:  float
    file_size_kb:      Optional[int]
    created_at:        datetime

    model_config = {"from_attributes": True}


# ─── Data Entry Job Schemas ────────────────────────────────────────────────────

class DataEntryJobOut(BaseModel):
    id:                       int
    business_id:              int
    document_id:              Optional[int]
    job_type:                 str
    status:                   str
    extracted_fields:         Optional[str]
    missing_fields:           Optional[str]
    validation_errors:        Optional[str]
    commander_recommendations: Optional[str]
    admin_approved:           bool
    approval_notes:           Optional[str]
    created_by_agent:         str
    created_at:               datetime

    model_config = {"from_attributes": True}


class DataEntryApproveRequest(BaseModel):
    admin_notes: Optional[str] = ""


class DataEntryDeclineRequest(BaseModel):
    reason: str


# ─── Equipment Request Schemas ─────────────────────────────────────────────────

class EquipmentRequestCreate(BaseModel):
    business_id:         int
    patient_id:          Optional[int] = None
    equipment_type:      str
    diagnosis_or_reason: Optional[str] = None
    prescribing_provider: Optional[str] = None
    insurance_required:  Optional[bool] = True
    prior_auth_required: Optional[bool] = False
    hcpcs_codes:         Optional[str] = None
    notes:               Optional[str] = None


class EquipmentRequestUpdate(BaseModel):
    equipment_type:       Optional[str] = None
    diagnosis_or_reason:  Optional[str] = None
    prescribing_provider: Optional[str] = None
    insurance_required:   Optional[bool] = None
    prior_auth_required:  Optional[bool] = None
    hcpcs_codes:          Optional[str] = None
    status:               Optional[str] = None
    notes:                Optional[str] = None


class EquipmentRequestOut(BaseModel):
    id:                   int
    business_id:          int
    patient_id:           Optional[int]
    equipment_type:       str
    diagnosis_or_reason:  Optional[str]
    prescribing_provider: Optional[str]
    insurance_required:   bool
    prior_auth_required:  bool
    hcpcs_codes:          Optional[str]
    status:               str
    notes:                Optional[str]
    created_at:           datetime

    model_config = {"from_attributes": True}


# ─── Bookkeeping Entry Schemas ─────────────────────────────────────────────────

class BookkeepingEntryCreate(BaseModel):
    business_id:        int
    source_document_id: Optional[int] = None
    entry_type:         Optional[str] = None
    vendor_or_customer: Optional[str] = None
    transaction_date:   Optional[str] = None
    amount:             Optional[float] = 0.0
    category:           Optional[str] = None
    memo:               Optional[str] = None
    tax_flag:           Optional[bool] = False


class BookkeepingEntryUpdate(BaseModel):
    entry_type:         Optional[str] = None
    vendor_or_customer: Optional[str] = None
    transaction_date:   Optional[str] = None
    amount:             Optional[float] = None
    category:           Optional[str] = None
    memo:               Optional[str] = None
    tax_flag:           Optional[bool] = None
    status:             Optional[str] = None
    admin_approved:     Optional[bool] = None


class BookkeepingEntryOut(BaseModel):
    id:                  int
    business_id:         int
    source_document_id:  Optional[int]
    entry_type:          Optional[str]
    vendor_or_customer:  Optional[str]
    transaction_date:    Optional[str]
    amount:              float
    category:            Optional[str]
    memo:                Optional[str]
    tax_flag:            bool
    status:              str
    admin_approved:      bool
    created_at:          datetime

    model_config = {"from_attributes": True}


# ─── Master Recommendation Schemas ────────────────────────────────────────────

class MasterRecommendationOut(BaseModel):
    id:                  int
    business_id:         Optional[int]
    module:              str
    severity:            str
    title:               str
    detail:              Optional[str]
    recommended_action:  Optional[str]
    auto_fix_available:  bool
    admin_approved:      bool
    status:              str
    created_at:          datetime

    model_config = {"from_attributes": True}


# ─── Audit Log Schemas ─────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    id:          int
    business_id: Optional[int]
    actor:       str
    action:      str
    entity_type: Optional[str]
    entity_id:   Optional[str]
    before_data: Optional[str]
    after_data:  Optional[str]
    created_at:  datetime

    model_config = {"from_attributes": True}


# ─── Data Entry Processing Schemas ────────────────────────────────────────────

class DataEntryProcessResult(BaseModel):
    document_id:              int
    job_id:                   int
    document_reader:          dict
    extraction:               dict
    verification:             dict
    commander_recommendations: List[str]
    completeness_pct:         float
    can_proceed_to_admin:     bool
    next_step:                str
    requires_admin_approval:  bool = True


class FutureAgentBlueprintRequest(BaseModel):
    requested_agent: str
    purpose:         str
    required_tools:  Optional[List[str]] = []
    data_inputs:     Optional[List[str]] = []
    data_outputs:    Optional[List[str]] = []


# ─── CRM & Sales Schemas ───────────────────────────────────────────────────────

class LeadCreate(BaseModel):
    business_id: int
    first_name:  str
    last_name:   Optional[str] = None
    email:       Optional[str] = None
    phone:       Optional[str] = None
    company:     Optional[str] = None
    source:      Optional[str] = None
    assigned_to: Optional[str] = None
    notes:       Optional[str] = None
    tags:        Optional[str] = None

class LeadUpdate(BaseModel):
    first_name:  Optional[str] = None
    last_name:   Optional[str] = None
    email:       Optional[str] = None
    phone:       Optional[str] = None
    company:     Optional[str] = None
    source:      Optional[str] = None
    status:      Optional[str] = None
    score:       Optional[int] = None
    assigned_to: Optional[str] = None
    notes:       Optional[str] = None
    tags:        Optional[str] = None

class LeadOut(BaseModel):
    id:          int
    business_id: int
    first_name:  str
    last_name:   Optional[str]
    email:       Optional[str]
    phone:       Optional[str]
    company:     Optional[str]
    source:      Optional[str]
    status:      str
    score:       int
    assigned_to: Optional[str]
    notes:       Optional[str]
    ai_notes:    Optional[str]
    tags:        Optional[str]
    created_at:  datetime
    model_config = {"from_attributes": True}


class PipelineCreate(BaseModel):
    business_id: int
    name:        str
    stages:      Optional[str] = None
    is_default:  Optional[bool] = False

class PipelineOut(BaseModel):
    id:          int
    business_id: int
    name:        str
    stages:      Optional[str]
    is_default:  bool
    created_at:  datetime
    model_config = {"from_attributes": True}


class DealCreate(BaseModel):
    business_id:    int
    pipeline_id:    Optional[int] = None
    lead_id:        Optional[int] = None
    title:          str
    stage:          Optional[str] = "prospecting"
    value:          Optional[float] = 0.0
    probability:    Optional[int] = 20
    expected_close: Optional[str] = None
    assigned_to:    Optional[str] = None
    notes:          Optional[str] = None

class DealUpdate(BaseModel):
    title:          Optional[str] = None
    stage:          Optional[str] = None
    value:          Optional[float] = None
    probability:    Optional[int] = None
    expected_close: Optional[str] = None
    assigned_to:    Optional[str] = None
    status:         Optional[str] = None
    notes:          Optional[str] = None

class DealOut(BaseModel):
    id:             int
    business_id:    int
    pipeline_id:    Optional[int]
    lead_id:        Optional[int]
    title:          str
    stage:          str
    value:          float
    probability:    int
    expected_close: Optional[str]
    assigned_to:    Optional[str]
    status:         str
    notes:          Optional[str]
    created_at:     datetime
    model_config = {"from_attributes": True}


class QuoteCreate(BaseModel):
    business_id:  int
    deal_id:      Optional[int] = None
    title:        str
    client_name:  Optional[str] = None
    client_email: Optional[str] = None
    line_items:   Optional[str] = None
    subtotal:     Optional[float] = 0.0
    tax_rate:     Optional[float] = 0.0
    total:        Optional[float] = 0.0
    notes:        Optional[str] = None
    valid_until:  Optional[str] = None

class QuoteOut(BaseModel):
    id:           int
    business_id:  int
    deal_id:      Optional[int]
    quote_number: Optional[str]
    title:        str
    client_name:  Optional[str]
    client_email: Optional[str]
    line_items:   Optional[str]
    subtotal:     float
    tax_rate:     float
    total:        float
    status:       str
    notes:        Optional[str]
    valid_until:  Optional[str]
    created_at:   datetime
    model_config = {"from_attributes": True}


# ─── Recruitment Schemas ───────────────────────────────────────────────────────

class JobPostingCreate(BaseModel):
    business_id:     int
    title:           str
    department:      Optional[str] = None
    location:        Optional[str] = None
    job_type:        Optional[str] = "full_time"
    remote_option:   Optional[str] = "on_site"
    description:     Optional[str] = None
    requirements:    Optional[str] = None
    salary_min:      Optional[float] = None
    salary_max:      Optional[float] = None
    salary_currency: Optional[str] = "USD"

class JobPostingUpdate(BaseModel):
    title:          Optional[str] = None
    department:     Optional[str] = None
    location:       Optional[str] = None
    job_type:       Optional[str] = None
    remote_option:  Optional[str] = None
    description:    Optional[str] = None
    requirements:   Optional[str] = None
    salary_min:     Optional[float] = None
    salary_max:     Optional[float] = None
    status:         Optional[str] = None
    posted_boards:  Optional[str] = None

class JobPostingOut(BaseModel):
    id:              int
    business_id:     int
    title:           str
    department:      Optional[str]
    location:        Optional[str]
    job_type:        str
    remote_option:   str
    description:     Optional[str]
    requirements:    Optional[str]
    salary_min:      Optional[float]
    salary_max:      Optional[float]
    salary_currency: str
    status:          str
    posted_boards:   Optional[str]
    ai_description:  Optional[str]
    created_at:      datetime
    model_config = {"from_attributes": True}


class CandidateCreate(BaseModel):
    business_id:      int
    first_name:       str
    last_name:        str
    email:            Optional[str] = None
    phone:            Optional[str] = None
    location:         Optional[str] = None
    linkedin_url:     Optional[str] = None
    skills:           Optional[str] = None
    experience_years: Optional[int] = None
    education:        Optional[str] = None
    notes:            Optional[str] = None

class CandidateOut(BaseModel):
    id:               int
    business_id:      int
    first_name:       str
    last_name:        str
    email:            Optional[str]
    phone:            Optional[str]
    location:         Optional[str]
    linkedin_url:     Optional[str]
    skills:           Optional[str]
    experience_years: Optional[int]
    education:        Optional[str]
    ai_summary:       Optional[str]
    ai_score:         float
    status:           str
    notes:            Optional[str]
    created_at:       datetime
    model_config = {"from_attributes": True}


class JobApplicationCreate(BaseModel):
    business_id:    int
    job_posting_id: int
    candidate_id:   int
    recruiter_notes: Optional[str] = None

class JobApplicationUpdate(BaseModel):
    stage:           Optional[str] = None
    recruiter_notes: Optional[str] = None
    interview_date:  Optional[str] = None
    offer_amount:    Optional[float] = None
    status:          Optional[str] = None

class JobApplicationOut(BaseModel):
    id:              int
    business_id:     int
    job_posting_id:  int
    candidate_id:    int
    stage:           str
    ai_match_score:  float
    ai_feedback:     Optional[str]
    recruiter_notes: Optional[str]
    interview_date:  Optional[str]
    offer_amount:    Optional[float]
    status:          str
    created_at:      datetime
    model_config = {"from_attributes": True}


# ─── Marketing Suite Schemas ───────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    business_id:    int
    name:           str
    campaign_type:  Optional[str] = "email"
    subject:        Optional[str] = None
    body:           Optional[str] = None
    target_segment: Optional[str] = "all"
    scheduled_at:   Optional[datetime] = None

class CampaignUpdate(BaseModel):
    name:           Optional[str] = None
    campaign_type:  Optional[str] = None
    subject:        Optional[str] = None
    body:           Optional[str] = None
    target_segment: Optional[str] = None
    status:         Optional[str] = None
    scheduled_at:   Optional[datetime] = None

class CampaignOut(BaseModel):
    id:                int
    business_id:       int
    name:              str
    campaign_type:     str
    status:            str
    subject:           Optional[str]
    body:              Optional[str]
    ai_generated_body: Optional[str]
    target_segment:    Optional[str]
    scheduled_at:      Optional[datetime]
    sent_count:        int
    open_count:        int
    click_count:       int
    conversion_count:  int
    created_at:        datetime
    model_config = {"from_attributes": True}


class MarketingFormCreate(BaseModel):
    business_id:       int
    name:              str
    form_type:         Optional[str] = "lead_capture"
    fields_json:       Optional[str] = None
    thank_you_message: Optional[str] = None

class MarketingFormOut(BaseModel):
    id:                int
    business_id:       int
    name:              str
    form_type:         str
    fields_json:       Optional[str]
    thank_you_message: Optional[str]
    is_active:         bool
    submission_count:  int
    created_at:        datetime
    model_config = {"from_attributes": True}


class FormSubmissionCreate(BaseModel):
    form_id:     int
    business_id: int
    data_json:   Optional[str] = None
    source_url:  Optional[str] = None

class FormSubmissionOut(BaseModel):
    id:          int
    form_id:     int
    business_id: int
    data_json:   Optional[str]
    ip_address:  Optional[str]
    source_url:  Optional[str]
    created_at:  datetime
    model_config = {"from_attributes": True}


# ─── Communication Hub Schemas ─────────────────────────────────────────────────

class IVRConfigCreate(BaseModel):
    business_id:     int
    name:            str
    greeting_text:   Optional[str] = None
    menu_options:    Optional[str] = None
    fallback_action: Optional[str] = "voicemail"
    ai_enabled:      Optional[bool] = True
    ai_voice:        Optional[str] = "nova"

class IVRConfigOut(BaseModel):
    id:              int
    business_id:     int
    name:            str
    greeting_text:   Optional[str]
    menu_options:    Optional[str]
    fallback_action: str
    ai_enabled:      bool
    ai_voice:        str
    is_active:       bool
    created_at:      datetime
    model_config = {"from_attributes": True}


class PhoneNumberCreate(BaseModel):
    business_id:  int
    number:       str
    number_type:  Optional[str] = "local"
    provider:     Optional[str] = "twilio"
    purpose:      Optional[str] = None
    ivr_config_id: Optional[int] = None
    monthly_cost: Optional[float] = 1.0

class PhoneNumberOut(BaseModel):
    id:            int
    business_id:   int
    number:        str
    number_type:   str
    provider:      str
    is_active:     bool
    purpose:       Optional[str]
    ivr_config_id: Optional[int]
    monthly_cost:  float
    created_at:    datetime
    model_config = {"from_attributes": True}


# ─── CallTrack AI Schemas ──────────────────────────────────────────────────────

class CallTrackingNumberCreate(BaseModel):
    business_id:    int
    campaign_name:  str
    phone_number_id: Optional[int] = None
    source:         Optional[str] = None
    medium:         Optional[str] = None
    utm_campaign:   Optional[str] = None

class CallTrackingNumberOut(BaseModel):
    id:              int
    business_id:     int
    phone_number_id: Optional[int]
    campaign_name:   str
    source:          Optional[str]
    medium:          Optional[str]
    utm_campaign:    Optional[str]
    total_calls:     int
    conversions:     int
    is_active:       bool
    created_at:      datetime
    model_config = {"from_attributes": True}


class CallTrackingEventCreate(BaseModel):
    tracking_number_id: Optional[int] = None
    business_id:        int
    caller_phone:       Optional[str] = None
    call_duration_secs: Optional[int] = 0
    is_conversion:      Optional[bool] = False

class CallTrackingEventOut(BaseModel):
    id:                 int
    tracking_number_id: Optional[int]
    business_id:        int
    caller_phone:       Optional[str]
    call_duration_secs: int
    is_conversion:      bool
    sentiment:          Optional[str]
    ai_summary:         Optional[str]
    revenue_attributed: float
    created_at:         datetime
    model_config = {"from_attributes": True}


# ─── Contact Center Schemas ────────────────────────────────────────────────────

class AgentQueueCreate(BaseModel):
    business_id:      int
    name:             str
    queue_type:       Optional[str] = "inbound"
    max_wait_secs:    Optional[int] = 120
    greeting_message: Optional[str] = None
    agents_assigned:  Optional[str] = None

class AgentQueueOut(BaseModel):
    id:               int
    business_id:      int
    name:             str
    queue_type:       str
    max_wait_secs:    int
    greeting_message: Optional[str]
    agents_assigned:  Optional[str]
    is_active:        bool
    created_at:       datetime
    model_config = {"from_attributes": True}


# ─── Automation & Workflow Schemas ─────────────────────────────────────────────

class WorkflowCreate(BaseModel):
    business_id:    int
    name:           str
    description:    Optional[str] = None
    trigger_type:   str
    trigger_config: Optional[str] = None
    steps:          Optional[str] = None

class WorkflowUpdate(BaseModel):
    name:           Optional[str] = None
    description:    Optional[str] = None
    trigger_type:   Optional[str] = None
    trigger_config: Optional[str] = None
    steps:          Optional[str] = None
    is_active:      Optional[bool] = None

class WorkflowOut(BaseModel):
    id:             int
    business_id:    int
    name:           str
    description:    Optional[str]
    trigger_type:   str
    trigger_config: Optional[str]
    steps:          Optional[str]
    is_active:      bool
    run_count:      int
    last_run_at:    Optional[datetime]
    created_at:     datetime
    model_config = {"from_attributes": True}


class WorkflowExecutionOut(BaseModel):
    id:              int
    workflow_id:     int
    business_id:     int
    status:          str
    trigger_data:    Optional[str]
    steps_completed: int
    error_message:   Optional[str]
    started_at:      datetime
    completed_at:    Optional[datetime]
    model_config = {"from_attributes": True}


class WebhookConfigCreate(BaseModel):
    business_id: int
    name:        str
    url:         str
    events:      Optional[str] = None
    secret_key:  Optional[str] = None

class WebhookConfigOut(BaseModel):
    id:                int
    business_id:       int
    name:              str
    url:               str
    events:            Optional[str]
    is_active:         bool
    last_triggered_at: Optional[datetime]
    fail_count:        int
    created_at:        datetime
    model_config = {"from_attributes": True}


# ─── SmartBoss AI Schemas ──────────────────────────────────────────────────────

class SmartBossInsightOut(BaseModel):
    id:             int
    business_id:    Optional[int]
    insight_type:   str
    title:          str
    summary:        Optional[str]
    data_json:      Optional[str]
    recommendation: Optional[str]
    priority:       str
    is_read:        bool
    created_at:     datetime
    model_config = {"from_attributes": True}


class SmartBossQueryRequest(BaseModel):
    question:    str
    business_id: Optional[int] = None
