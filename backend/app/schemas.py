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
