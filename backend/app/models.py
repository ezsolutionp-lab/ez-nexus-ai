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
