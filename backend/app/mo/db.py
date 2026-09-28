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
    # Voice persona for this conversation: form of address, timezone, last-seen and last-briefed times.
    persona_json = Column(Text, nullable=False, default="{}")
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


# ─────────────────────────────────────────────────────────────────────────────
# Platform layer: knowledge, memory, orchestration, control, protocols, evaluation
# ─────────────────────────────────────────────────────────────────────────────

class KnowledgeDoc(Base, TenantMixin):
    """A source document. Classification and scopes are enforced before any ranking."""

    __tablename__ = "mo_knowledge_docs"

    id = Column(String(64), primary_key=True, default=_uid)
    title = Column(String(300), nullable=False)
    source = Column(String(500), nullable=True)
    classification = Column(String(16), nullable=False, default="INTERNAL")
    allowed_scopes_json = Column(Text, nullable=False, default="[]")     # empty = any tenant member
    content_hash = Column(String(64), nullable=False)
    chunk_count = Column(Integer, nullable=False, default=0)
    embedder = Column(String(60), nullable=False, default="local-hashed-ngram")

    __table_args__ = (UniqueConstraint("tenant_id", "content_hash", name="uq_mo_knowledge_doc_hash"),)


class KnowledgeChunk(Base, TenantMixin):
    __tablename__ = "mo_knowledge_chunks"

    id = Column(String(64), primary_key=True, default=_uid)
    doc_id = Column(String(64), ForeignKey("mo_knowledge_docs.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    terms_json = Column(Text, nullable=False, default="[]")
    vector_json = Column(Text, nullable=False, default="{}")
    entities_json = Column(Text, nullable=False, default="[]")


class MemoryRecord(Base, TenantMixin):
    """One remembered item. Private to `actor_id` unless `shared` is set."""

    __tablename__ = "mo_memories"

    id = Column(String(64), primary_key=True, default=_uid)
    actor_id = Column(String(64), nullable=False, index=True)
    kind = Column(String(16), nullable=False, index=True)
    # WORKING | SHORT_TERM | LONG_TERM | SEMANTIC | EPISODIC | PROCEDURAL
    key = Column(String(200), nullable=True)
    content = Column(Text, nullable=False)
    importance = Column(Float, nullable=False, default=0.5)
    shared = Column(Boolean, nullable=False, default=False)
    classification = Column(String(16), nullable=False, default="INTERNAL")
    tags_json = Column(Text, nullable=False, default="[]")
    terms_json = Column(Text, nullable=False, default="[]")
    vector_json = Column(Text, nullable=False, default="{}")
    access_count = Column(Integer, nullable=False, default=0)
    last_accessed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    redactions_json = Column(Text, nullable=False, default="[]")


class OrchestrationRun(Base, TenantMixin):
    """A supervised DAG run. Its steps are checkpointed so a run can resume."""

    __tablename__ = "mo_runs"

    id = Column(String(64), primary_key=True, default=_uid)
    name = Column(String(200), nullable=False)
    status = Column(String(24), nullable=False, default="PENDING")
    # PENDING | RUNNING | SUCCEEDED | FAILED | PARTIAL | AWAITING_APPROVAL | CANCELLED
    spec_json = Column(Text, nullable=False)
    budget_usd = Column(Float, nullable=False, default=1.0)
    spent_usd = Column(Float, nullable=False, default=0.0)
    autonomy_level = Column(Integer, nullable=False, default=1)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    detail = Column(Text, nullable=True)
    trace_id = Column(String(64), nullable=True)


class OrchestrationStep(Base, TenantMixin):
    __tablename__ = "mo_run_steps"

    id = Column(String(64), primary_key=True, default=_uid)
    run_id = Column(String(64), ForeignKey("mo_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_key = Column(String(80), nullable=False)
    kind = Column(String(24), nullable=False)          # tool | agent | domain | gate
    target = Column(String(160), nullable=False)
    depends_on_json = Column(Text, nullable=False, default="[]")
    status = Column(String(24), nullable=False, default="PENDING")
    # PENDING | RUNNING | SUCCEEDED | FAILED | SKIPPED | AWAITING_APPROVAL | CANCELLED
    attempts = Column(Integer, nullable=False, default=0)
    result_state = Column(String(40), nullable=True)
    output_json = Column(Text, nullable=True)
    detail = Column(Text, nullable=True)
    approval_id = Column(String(64), nullable=True)
    duration_ms = Column(Integer, nullable=True)

    __table_args__ = (UniqueConstraint("run_id", "step_key", name="uq_mo_run_step_key"),)


class AutonomyPolicy(Base, TenantMixin):
    """Autonomy level (0-5) for a subject: an agent, a domain or an action prefix."""

    __tablename__ = "mo_autonomy_policies"

    id = Column(String(64), primary_key=True, default=_uid)
    subject = Column(String(160), nullable=False)
    level = Column(Integer, nullable=False, default=1)
    reason = Column(Text, nullable=True)
    max_level = Column(Integer, nullable=False, default=3)

    __table_args__ = (UniqueConstraint("tenant_id", "subject", name="uq_mo_autonomy_subject"),)


class ShadowRecord(Base, TenantMixin):
    """What MO proposed versus what the human actually decided — the evidence for promotion."""

    __tablename__ = "mo_shadow_records"

    id = Column(String(64), primary_key=True, default=_uid)
    subject = Column(String(160), nullable=False, index=True)
    action = Column(String(160), nullable=False)
    proposal_json = Column(Text, nullable=False)
    human_json = Column(Text, nullable=True)
    agreed = Column(Boolean, nullable=True)
    decided_at = Column(DateTime, nullable=True)


class ReversibleAction(Base, TenantMixin):
    """An executed action with the instruction to undo it, so rollback is a real operation."""

    __tablename__ = "mo_reversible_actions"

    id = Column(String(64), primary_key=True, default=_uid)
    action = Column(String(160), nullable=False)
    resource = Column(String(200), nullable=True)
    undo_tool = Column(String(120), nullable=True)
    undo_payload_json = Column(Text, nullable=False, default="{}")
    status = Column(String(16), nullable=False, default="APPLIED")     # APPLIED | ROLLED_BACK | ROLLBACK_FAILED
    detail = Column(Text, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)


class ProtocolPeer(Base, TenantMixin):
    """A registered MCP server or A2A peer. Tools it exposes are allow-listed, never trusted wholesale."""

    __tablename__ = "mo_protocol_peers"

    id = Column(String(64), primary_key=True, default=_uid)
    name = Column(String(120), nullable=False)
    protocol = Column(String(8), nullable=False)          # MCP | A2A
    url = Column(String(500), nullable=False)
    credential_env_var = Column(String(120), nullable=True)
    allowed_tools_json = Column(Text, nullable=False, default="[]")
    risk_level = Column(String(16), nullable=False, default="MEDIUM")
    is_enabled = Column(Boolean, nullable=False, default=True)
    last_error = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_mo_peer_name"),)


class EvalRun(Base, TenantMixin):
    __tablename__ = "mo_eval_runs"

    id = Column(String(64), primary_key=True, default=_uid)
    suite = Column(String(160), nullable=False, index=True)
    target = Column(String(160), nullable=False)
    total = Column(Integer, nullable=False)
    passed_count = Column(Integer, nullable=False)
    score = Column(Float, nullable=False)
    threshold = Column(Float, nullable=False)
    passed = Column(Boolean, nullable=False)
    results_json = Column(Text, nullable=False)


PLATFORM_TABLES = [
    "mo_knowledge_docs", "mo_knowledge_chunks", "mo_memories", "mo_runs", "mo_run_steps",
    "mo_autonomy_policies", "mo_shadow_records", "mo_reversible_actions", "mo_protocol_peers",
    "mo_eval_runs",
]


class CapabilityGrant(Base, TenantMixin):
    """A one-time, argument-bound authorisation minted from a granted approval. Only the token's hash is stored."""

    __tablename__ = "mo_capability_grants"

    id = Column(String(64), primary_key=True, default=_uid)
    approval_id = Column(String(64), nullable=False, index=True)
    tool = Column(String(160), nullable=False)
    action = Column(String(160), nullable=False)
    resource = Column(String(500), nullable=False)
    args_hash = Column(String(64), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


class ExecutionReceipt(Base, TenantMixin):
    """Proof that a governed call ran (or was refused). Written for failures as well as successes."""

    __tablename__ = "mo_receipts"

    id = Column(String(64), primary_key=True, default=_uid)
    trace_id = Column(String(64), nullable=False, index=True)
    mission_id = Column(String(64), nullable=True, index=True)
    tool = Column(String(160), nullable=False)
    action = Column(String(160), nullable=False)
    resource = Column(String(500), nullable=False)
    request_hash = Column(String(64), nullable=False)
    idempotency_key = Column(String(200), nullable=True)
    grant_id = Column(String(64), nullable=True)
    state = Column(String(32), nullable=False)
    success = Column(Boolean, nullable=False)
    output_hash = Column(String(64), nullable=False)
    detail = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_mo_receipt_idem"),)


class AgentDefinition(Base, TenantMixin):
    """A registered agent and the only tools it may ask MO to run."""

    __tablename__ = "mo_agents"

    id = Column(String(64), primary_key=True, default=_uid)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    allowed_tools_json = Column(Text, nullable=False, default="[]")
    risk_ceiling = Column(String(16), nullable=False, default="WRITE")
    status = Column(String(16), nullable=False, default="ACTIVE")    # ACTIVE | DISABLED

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_mo_agent_name"),)


class AgentRelease(Base, TenantMixin):
    """One version of an agent moving BUILD -> SCAN -> EVAL -> APPROVAL -> CANARY -> VERIFY -> PROMOTE."""

    __tablename__ = "mo_agent_releases"

    id = Column(String(64), primary_key=True, default=_uid)
    agent_name = Column(String(120), nullable=False, index=True)
    version = Column(String(64), nullable=False)
    manifest_json = Column(Text, nullable=False)
    manifest_hash = Column(String(64), nullable=False)
    stage = Column(String(16), nullable=False, default="BUILD")
    status = Column(String(16), nullable=False, default="IN_PROGRESS")   # IN_PROGRESS | STOPPED | PROMOTED | ROLLED_BACK
    scan_json = Column(Text, nullable=True)
    eval_run_id = Column(String(64), nullable=True)
    eval_report_hash = Column(String(64), nullable=True)
    approval_id = Column(String(64), nullable=True)
    canary_json = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False)
    previous_release_id = Column(String(64), nullable=True)
    stop_reason = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "agent_name", "version", name="uq_mo_release_version"),)


class DependencyRecord(Base, TenantMixin):
    """Provenance and licence review for a third-party dependency. Unknown or restricted means quarantined."""

    __tablename__ = "mo_dependencies"

    id = Column(String(64), primary_key=True, default=_uid)
    name = Column(String(200), nullable=False)
    version = Column(String(80), nullable=False)
    source = Column(String(500), nullable=True)
    license = Column(String(200), nullable=True)
    license_class = Column(String(24), nullable=False, default="UNKNOWN")
    license_text_hash = Column(String(64), nullable=True)
    usage = Column(String(300), nullable=True)
    attribution_required = Column(Boolean, nullable=False, default=True)
    status = Column(String(16), nullable=False, default="QUARANTINED")   # QUARANTINED | APPROVED | REJECTED
    review_notes = Column(Text, nullable=True)
    reviewed_by = Column(String(64), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "name", "version", name="uq_mo_dependency"),)


AUTHORITY_TABLES = ["mo_capability_grants", "mo_receipts", "mo_agents", "mo_agent_releases", "mo_dependencies"]


class KeyValueEntry(Base, TenantMixin):
    """Tenant-scoped key/value store used by the workflow Database node."""

    __tablename__ = "mo_kv"

    id = Column(String(64), primary_key=True, default=_uid)
    namespace = Column(String(80), nullable=False)
    key = Column(String(200), nullable=False)
    value_json = Column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", "namespace", "key", name="uq_mo_kv"),)


class A2ANonce(Base):
    """Replay-protection nonces shared by every worker process."""

    __tablename__ = "mo_a2a_nonces"

    id = Column(String(64), primary_key=True, default=_uid)
    tenant_id = Column(String(64), nullable=False, index=True)
    peer = Column(String(64), nullable=False)
    nonce = Column(String(128), nullable=False)
    seen_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (UniqueConstraint("tenant_id", "peer", "nonce", name="uq_mo_a2a_nonce"),)


SHARED_STATE_TABLES = ["mo_kv", "mo_a2a_nonces"]
