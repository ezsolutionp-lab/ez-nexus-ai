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
