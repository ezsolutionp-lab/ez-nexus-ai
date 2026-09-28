"""
MO NEXUS OMEGA — Foundation + Builder ORM models.

Shares the existing SQLAlchemy Base so MO tables live in the same database and
the same migration stream as the legacy EZ-NEXUS tables. Nothing here modifies
or replaces an existing table.

Every tenant-scoped row carries `tenant_id`. That column is not decoration: the
repository layer refuses to query these tables without a RequestContext.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ..database import Base


def _uid() -> str:
    return uuid.uuid4().hex


class TenantMixin:
    """Tenant + provenance columns carried by every MO record."""

    tenant_id = Column(String(64), nullable=False, index=True)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ─────────────────────────────────────────────────────────────────────────────
# Foundation
# ─────────────────────────────────────────────────────────────────────────────

class Tenant(Base):
    """An isolation boundary. Every MO row belongs to exactly one."""

    __tablename__ = "mo_tenants"

    id = Column(String(64), primary_key=True, default=_uid)
    slug = Column(String(80), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    plan = Column(String(40), default="starter", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    safe_mode = Column(Boolean, default=False, nullable=False)   # kill switch
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditEvent(Base):
    """
    Hash-chained audit record.

    `prev_hash` + `entry_hash` make the chain tamper-evident: altering any row
    breaks every hash after it. Verified by mo.audit.chain.verify_chain().
    """

    __tablename__ = "mo_audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    actor_id = Column(String(64), nullable=False)
    actor_type = Column(String(32), nullable=False, default="user")
    actor_label = Column(String(160), nullable=True)
    source_channel = Column(String(32), nullable=False, default="API")
    action = Column(String(160), nullable=False, index=True)
    resource_type = Column(String(80), nullable=True)
    resource_id = Column(String(120), nullable=True)
    result_state = Column(String(40), nullable=False)
    detail = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=True)      # redacted
    trace_id = Column(String(64), nullable=True, index=True)
    cost_usd = Column(Float, nullable=True)
    prev_hash = Column(String(64), nullable=False)
    entry_hash = Column(String(64), nullable=False, unique=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "seq", name="uq_mo_audit_tenant_seq"),
        Index("ix_mo_audit_tenant_occurred", "tenant_id", "occurred_at"),
    )


class ToolRecord(Base, TenantMixin):
    """Registered tool. Permissions and risk are data, not code comments."""

    __tablename__ = "mo_tools"

    id = Column(String(64), primary_key=True, default=_uid)
    name = Column(String(120), nullable=False, index=True)
    version = Column(String(32), nullable=False, default="1.0.0")
    description = Column(Text, nullable=True)
    kind = Column(String(32), nullable=False, default="builtin")   # builtin | http | mcp | a2a
    risk_level = Column(String(16), nullable=False, default="LOW")  # LOW|MEDIUM|HIGH|CRITICAL
    required_scopes = Column(Text, nullable=False, default="[]")
    input_schema = Column(Text, nullable=False, default="{}")
    output_schema = Column(Text, nullable=False, default="{}")
    timeout_seconds = Column(Integer, nullable=False, default=30)
    rate_limit_per_minute = Column(Integer, nullable=False, default=60)
    requires_approval = Column(Boolean, nullable=False, default=False)
    credential_env_var = Column(String(120), nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "name", "version", name="uq_mo_tool_ident"),)


class AgentManifestRecord(Base, TenantMixin):
    """A registered, versioned agent definition (Instruction #3 §14)."""

    __tablename__ = "mo_agent_manifests"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), nullable=True, index=True)
    name = Column(String(160), nullable=False)
    version = Column(String(32), nullable=False, default="1.0.0")
    purpose = Column(Text, nullable=True)
    instructions = Column(Text, nullable=True)
    model_policy_json = Column(Text, nullable=False, default="{}")
    tools_json = Column(Text, nullable=False, default="[]")
    permissions_json = Column(Text, nullable=False, default="{}")
    memory_policy_json = Column(Text, nullable=False, default="{}")
    knowledge_json = Column(Text, nullable=False, default="{}")
    autonomy_level = Column(String(24), nullable=False, default="SUPERVISED")
    budget_usd = Column(Float, nullable=False, default=1.0)
    max_retries = Column(Integer, nullable=False, default=2)
    timeout_seconds = Column(Integer, nullable=False, default=60)
    approval_gates_json = Column(Text, nullable=False, default="[]")
    evaluation_json = Column(Text, nullable=False, default="{}")
    status = Column(String(24), nullable=False, default="DRAFT")
    # DRAFT|BUILDING|TESTING|FAILED|READY|DEPLOYED|DISABLED|DEPRECATED
    kill_switch = Column(Boolean, nullable=False, default=False)
    test_report_json = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "name", "version", name="uq_mo_agent_ident"),)


class EventRecord(Base, TenantMixin):
    """Durable event fabric row. Survives restart; replayable by sequence."""

    __tablename__ = "mo_events"

    id = Column(String(64), primary_key=True, default=_uid)
    topic = Column(String(120), nullable=False, index=True)
    payload_json = Column(Text, nullable=False, default="{}")
    source = Column(String(120), nullable=True)
    trace_id = Column(String(64), nullable=True, index=True)
    delivered = Column(Boolean, nullable=False, default=False)
    delivery_attempts = Column(Integer, nullable=False, default=0)
    dead_lettered = Column(Boolean, nullable=False, default=False)
    last_error = Column(Text, nullable=True)


class ApprovalRequest(Base, TenantMixin):
    """A gate an operation must pass before it may proceed."""

    __tablename__ = "mo_approvals"

    id = Column(String(64), primary_key=True, default=_uid)
    action = Column(String(160), nullable=False)
    risk_tier = Column(String(16), nullable=False, default="MEDIUM")
    resource_type = Column(String(80), nullable=True)
    resource_id = Column(String(120), nullable=True)
    requested_by = Column(String(64), nullable=False)
    reason = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=True)
    required_approvals = Column(Integer, nullable=False, default=1)
    approvals_json = Column(Text, nullable=False, default="[]")
    status = Column(String(24), nullable=False, default="PENDING")
    # PENDING | APPROVED | REJECTED | EXPIRED | REVOKED
    expires_at = Column(DateTime, nullable=True)
    decided_at = Column(DateTime, nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# Builder (Instruction #3 §40)
# ─────────────────────────────────────────────────────────────────────────────

class BuilderProject(Base, TenantMixin):
    __tablename__ = "builder_projects"

    id = Column(String(64), primary_key=True, default=_uid)
    name = Column(String(200), nullable=False)
    slug = Column(String(200), nullable=False)
    prompt = Column(Text, nullable=False)
    build_mode = Column(String(16), nullable=False, default="FULL_CODE")
    target_type = Column(String(32), nullable=False, default="WEB_APP")
    target_platform = Column(String(40), nullable=False, default="web")
    preferred_stack = Column(String(80), nullable=False, default="fastapi_react")
    source_channel = Column(String(32), nullable=False, default="API")
    security_level = Column(String(24), nullable=False, default="STANDARD")
    data_classification = Column(String(24), nullable=False, default="INTERNAL")
    deployment_target = Column(String(40), nullable=False, default="preview")
    budget_usd = Column(Float, nullable=True)
    constraints_json = Column(Text, nullable=False, default="{}")
    status = Column(String(32), nullable=False, default="DRAFT")
    current_version = Column(Integer, nullable=False, default=0)
    workspace_path = Column(String(500), nullable=True)
    cost_model_usd = Column(Float, nullable=False, default=0.0)
    cost_tokens = Column(Integer, nullable=False, default=0)
    sandbox_seconds = Column(Float, nullable=False, default=0.0)

    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_builder_project_slug"),)


class BuilderRequirement(Base, TenantMixin):
    __tablename__ = "builder_requirements"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(40), nullable=False)   # BUSINESS|FUNCTIONAL|NONFUNCTIONAL|DATA|...
    key = Column(String(120), nullable=False)
    statement = Column(Text, nullable=False)
    acceptance_criteria = Column(Text, nullable=True)
    priority = Column(String(16), nullable=False, default="SHOULD")   # MUST|SHOULD|COULD
    source = Column(String(40), nullable=False, default="inferred")   # explicit|inferred|asked
    module = Column(String(80), nullable=True)


class BuilderAssumption(Base, TenantMixin):
    """Recorded explicitly (§3) so an inference is never mistaken for a request."""

    __tablename__ = "builder_assumptions"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    statement = Column(Text, nullable=False)
    rationale = Column(Text, nullable=True)
    impact = Column(String(16), nullable=False, default="LOW")
    confirmed_by = Column(String(64), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)


class BuilderArchitecture(Base, TenantMixin):
    __tablename__ = "builder_architectures"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    recommended = Column(String(40), nullable=False)
    rationale = Column(Text, nullable=True)
    alternatives_json = Column(Text, nullable=False, default="[]")
    tradeoffs_json = Column(Text, nullable=False, default="[]")
    scores_json = Column(Text, nullable=False, default="{}")
    infrastructure_json = Column(Text, nullable=False, default="{}")
    complexity = Column(String(16), nullable=False, default="MEDIUM")
    approved_by = Column(String(64), nullable=True)


class BuilderComponent(Base, TenantMixin):
    __tablename__ = "builder_components"

    id = Column(String(64), primary_key=True, default=_uid)
    name = Column(String(160), nullable=False)
    category = Column(String(40), nullable=False)
    version = Column(String(32), nullable=False, default="1.0.0")
    stack = Column(String(80), nullable=True)
    provenance = Column(String(200), nullable=True)
    license = Column(String(80), nullable=True)
    security_status = Column(String(32), nullable=False, default="UNSCANNED")
    dependencies_json = Column(Text, nullable=False, default="[]")
    body = Column(Text, nullable=True)
    is_global = Column(Boolean, nullable=False, default=False)


class BuilderGraphNode(Base, TenantMixin):
    __tablename__ = "builder_project_graph"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    node_key = Column(String(160), nullable=False)
    node_type = Column(String(40), nullable=False)
    label = Column(String(200), nullable=True)
    attributes_json = Column(Text, nullable=False, default="{}")
    depends_on_json = Column(Text, nullable=False, default="[]")

    __table_args__ = (Index("ix_builder_graph_project_version", "project_id", "version"),)


class BuilderPage(Base, TenantMixin):
    __tablename__ = "builder_pages"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    route = Column(String(200), nullable=False)
    title = Column(String(200), nullable=True)
    kind = Column(String(40), nullable=False, default="public")   # public|portal|admin
    requires_auth = Column(Boolean, nullable=False, default=False)
    sections_json = Column(Text, nullable=False, default="[]")
    seo_json = Column(Text, nullable=False, default="{}")


class BuilderDataModel(Base, TenantMixin):
    __tablename__ = "builder_data_models"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    table_name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    fields_json = Column(Text, nullable=False, default="[]")
    relations_json = Column(Text, nullable=False, default="[]")
    indexes_json = Column(Text, nullable=False, default="[]")
    tenant_scoped = Column(Boolean, nullable=False, default=True)
    soft_delete = Column(Boolean, nullable=False, default=True)


class BuilderApi(Base, TenantMixin):
    __tablename__ = "builder_apis"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    protocol = Column(String(24), nullable=False, default="REST")
    method = Column(String(10), nullable=False, default="GET")
    path = Column(String(240), nullable=False)
    description = Column(Text, nullable=True)
    data_model = Column(String(120), nullable=True)
    operation = Column(String(40), nullable=True)   # list|create|read|update|delete|custom
    input_schema_json = Column(Text, nullable=False, default="{}")
    output_schema_json = Column(Text, nullable=False, default="{}")
    requires_auth = Column(Boolean, nullable=False, default=True)
    required_scopes_json = Column(Text, nullable=False, default="[]")
    rate_limit_per_minute = Column(Integer, nullable=False, default=60)
    idempotent = Column(Boolean, nullable=False, default=False)
    timeout_seconds = Column(Integer, nullable=False, default=30)
    version = Column(String(16), nullable=False, default="v1")


class BuilderAgent(Base, TenantMixin):
    __tablename__ = "builder_agents"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    manifest_id = Column(String(64), nullable=True, index=True)
    name = Column(String(160), nullable=False)
    role = Column(String(80), nullable=True)
    purpose = Column(Text, nullable=True)
    canvas_json = Column(Text, nullable=False, default="{}")
    status = Column(String(24), nullable=False, default="DRAFT")


class BuilderWorkflow(Base, TenantMixin):
    __tablename__ = "builder_workflows"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    trigger_type = Column(String(40), nullable=False, default="manual")
    nodes_json = Column(Text, nullable=False, default="[]")
    edges_json = Column(Text, nullable=False, default="[]")
    compiled_json = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, default="DRAFT")


class BuilderIntegration(Base, TenantMixin):
    __tablename__ = "builder_integrations"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(80), nullable=False)
    capability = Column(String(120), nullable=False)
    auth_kind = Column(String(40), nullable=False, default="api_key")
    credential_env_var = Column(String(120), nullable=True)
    status = Column(String(32), nullable=False, default="CREDENTIAL_REQUIRED")
    config_json = Column(Text, nullable=False, default="{}")
    last_checked_at = Column(DateTime, nullable=True)


class BuilderFile(Base, TenantMixin):
    __tablename__ = "builder_files"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    path = Column(String(500), nullable=False)
    language = Column(String(40), nullable=True)
    content = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False, default=0)
    generator = Column(String(120), nullable=True)
    is_custom_code = Column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_builder_files_project_version", "project_id", "version"),)


class BuilderBuild(Base, TenantMixin):
    __tablename__ = "builder_builds"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    state = Column(String(32), nullable=False, default="FAILED")
    stages_json = Column(Text, nullable=False, default="[]")
    stdout = Column(Text, nullable=True)
    stderr = Column(Text, nullable=True)
    exit_code = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=False, default=0)
    peak_rss_kb = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)


class BuilderTestRun(Base, TenantMixin):
    __tablename__ = "builder_tests"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    build_id = Column(String(64), nullable=True, index=True)
    suite = Column(String(80), nullable=False, default="unit")
    state = Column(String(32), nullable=False, default="TEST_FAILED")
    total = Column(Integer, nullable=False, default=0)
    passed = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    report = Column(Text, nullable=True)


class BuilderPreview(Base, TenantMixin):
    __tablename__ = "builder_previews"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    build_id = Column(String(64), nullable=True)
    state = Column(String(32), nullable=False, default="FAILED")
    label = Column(String(40), nullable=False, default="PREVIEW")
    url = Column(String(500), nullable=True)
    entry_path = Column(String(500), nullable=True)
    expires_at = Column(DateTime, nullable=True)


class BuilderDeployment(Base, TenantMixin):
    __tablename__ = "builder_deployments"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    environment = Column(String(40), nullable=False, default="staging")
    state = Column(String(32), nullable=False, default="APPROVAL_REQUIRED")
    approval_id = Column(String(64), nullable=True)
    requested_by = Column(String(64), nullable=True)
    approved_by = Column(String(64), nullable=True)
    detail = Column(Text, nullable=True)
    deployed_at = Column(DateTime, nullable=True)


class BuilderVersion(Base, TenantMixin):
    __tablename__ = "builder_versions"

    id = Column(String(64), primary_key=True, default=_uid)
    project_id = Column(String(64), ForeignKey("builder_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    label = Column(String(120), nullable=True)
    summary = Column(Text, nullable=True)
    file_count = Column(Integer, nullable=False, default=0)
    tree_sha256 = Column(String(64), nullable=True)
    graph_snapshot = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_builder_version"),)


BUILDER_TABLES = [
    "builder_projects", "builder_requirements", "builder_assumptions", "builder_architectures",
    "builder_components", "builder_project_graph", "builder_pages", "builder_data_models",
    "builder_apis", "builder_agents", "builder_workflows", "builder_integrations",
    "builder_files", "builder_builds", "builder_tests", "builder_previews",
    "builder_deployments", "builder_versions",
]

MO_FOUNDATION_TABLES = [
    "mo_tenants", "mo_audit_events", "mo_tools", "mo_agent_manifests",
    "mo_events", "mo_approvals",
]


# ─────────────────────────────────────────────────────────────────────────────
# Voice (JARVIS console) — durable conversation state
# ─────────────────────────────────────────────────────────────────────────────

class VoiceSession(Base, TenantMixin):
    """
    One continuous conversation with MO.

    Durable, unlike the legacy Twilio flow's in-process dict: a restart or a
    second worker does not lose the conversation, and `awake_until` lets a user
    keep talking without repeating the wake phrase inside the follow-up window.
    """

    __tablename__ = "mo_voice_sessions"

    id = Column(String(64), primary_key=True, default=_uid)
    actor_id = Column(String(64), nullable=False, index=True)
    channel = Column(String(24), nullable=False, default="BROWSER")   # BROWSER | PHONE
    language = Column(String(16), nullable=False, default="en-US")
    status = Column(String(16), nullable=False, default="ACTIVE")     # ACTIVE | ENDED
    awake_until = Column(DateTime, nullable=True)
    # Conversational context carried between turns.
    focus_project_id = Column(String(64), nullable=True)
    pending_intent = Column(String(80), nullable=True)
    pending_slots_json = Column(Text, nullable=False, default="{}")
    last_response = Column(Text, nullable=True)
    turn_count = Column(Integer, nullable=False, default=0)
    ended_at = Column(DateTime, nullable=True)


class VoiceTurn(Base, TenantMixin):
    """One utterance and MO's reply — the conversation transcript."""

    __tablename__ = "mo_voice_turns"

    id = Column(String(64), primary_key=True, default=_uid)
    session_id = Column(String(64), ForeignKey("mo_voice_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    transcript = Column(Text, nullable=False)
    wake_detected = Column(Boolean, nullable=False, default=False)
    intent = Column(String(80), nullable=True)
    confidence = Column(Float, nullable=True)
    slots_json = Column(Text, nullable=False, default="{}")
    result_state = Column(String(40), nullable=False)
    reply = Column(Text, nullable=False)
    latency_ms = Column(Integer, nullable=True)

    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_voice_turn_seq"),)


VOICE_TABLES = ["mo_voice_sessions", "mo_voice_turns"]
