"""
MO NEXUS OMEGA — capability manifest.

One place that says, feature by feature, what is real. Every entry that claims
`implemented` names the module that implements it and a test module that covers it, and
tests/mo_platform/test_manifest.py imports both. A claim with no code behind it fails the
build, so this list cannot drift into marketing.

Statuses
  implemented          built, tested, works without external credentials
  partial              works, with a stated limit
  credential_required  built, but needs a provider credential to do real work
  planned              not built; listed so the gap is visible
  future               research direction only
"""

from __future__ import annotations

import os
from typing import Any

STATUSES = ("implemented", "partial", "credential_required", "planned", "future")


def _f(area, feature, status, module=None, test=None, note=""):
    return {"area": area, "feature": feature, "status": status, "module": module, "test": test, "note": note}


CAPABILITIES: list[dict[str, Any]] = [
    # ── governance ──
    _f("governance", "Zero-trust request context, RBAC scopes, tenant isolation", "implemented",
       "app.mo.security.zero_trust", "tests/security"),
    _f("governance", "Hash-chained tamper-evident audit log", "implemented", "app.mo.audit.chain", "tests"),
    _f("governance", "Approval engine (tiered, MFA for CRITICAL)", "implemented", "app.mo.approvals.engine", "tests"),
    _f("governance", "Tool registry with risk levels, scopes, rate limits, schema validation", "implemented",
       "app.mo.tools.spec", "tests"),
    _f("governance", "Tenant kill switch (safe mode)", "implemented", "app.mo.security.zero_trust", "tests"),
    _f("governance", "Autonomy levels 0-5 with evidence-gated promotion and auto-demotion", "implemented",
       "app.mo.control.autonomy", "tests/mo_platform/test_control.py",
       "A restriction layer only; it can never approve anything."),
    _f("governance", "Shadow learning (propose, human decides, agreement tracked)", "implemented",
       "app.mo.control.autonomy", "tests/mo_platform/test_control.py"),
    _f("governance", "Dry-run and rollback through the tool registry", "implemented",
       "app.mo.control.reversible", "tests/mo_platform/test_control.py",
       "Rollback works only for actions that recorded an undo tool."),
    _f("governance", "Prompt-injection screening and PII redaction guards", "implemented",
       "app.mo.guards.pipeline", "tests/mo_platform/test_knowledge.py",
       "Pattern and heuristic based; not a guarantee against novel attacks."),
    # ── intelligence ──
    _f("intelligence", "Model fabric router with fallback, budgets, circuit breaker", "credential_required",
       "app.mo.modelfabric.router", "tests",
       "Returns CREDENTIAL_REQUIRED until ANTHROPIC_API_KEY or OPENAI_API_KEY is set."),
    _f("intelligence", "Knowledge base / RAG (BM25 + hashed n-gram + entity graph, RRF fusion)", "implemented",
       "app.mo.knowledge.service", "tests/mo_platform/test_knowledge.py",
       "Vectors are local hashed n-grams, not a neural embedding model. Refuses to answer on weak evidence."),
    _f("intelligence", "Neural embeddings", "credential_required", "app.mo.knowledge.ranking",
       "tests/mo_platform/test_knowledge.py",
       "Provider adapter built (OpenAI-compatible /embeddings). Needs MO_EMBEDDINGS_PROVIDER=openai plus a key. "
       "Tested against a mock transport only; RESTRICTED text is never sent, and memory stays on the local embedder."),
    _f("intelligence", "Layered memory (working, short, long, semantic, episodic, procedural)", "implemented",
       "app.mo.memory.store", "tests/mo_platform/test_memory.py"),
    _f("intelligence", "Time-series forecasting (Holt + seasonal) and anomaly detection", "implemented",
       "app.mo.intelligence.timeseries", "tests/mo_platform/test_intelligence.py",
       "Classical statistics, not a neural model."),
    _f("intelligence", "PMO: critical path and Monte Carlo schedule risk", "implemented",
       "app.mo.intelligence.planning", "tests/mo_platform/test_intelligence.py"),
    _f("intelligence", "Sales / finance: pricing, lead score, pipeline forecast, NPV/IRR, runway", "implemented",
       "app.mo.intelligence.commercial", "tests/mo_platform/test_intelligence.py",
       "Transparent rule-based scoring, not a trained model. Missing inputs are reported, never invented."),
    _f("intelligence", "Recommender (co-occurrence)", "implemented", "app.mo.intelligence.commercial",
       "tests/mo_platform/test_intelligence.py"),
    _f("intelligence", "Text: keywords, action items, quiet-hours briefing", "implemented",
       "app.mo.intelligence.text", "tests/mo_platform/test_intelligence.py",
       "Frequency and explicit-pattern heuristics, not semantic understanding."),
    _f("intelligence", "Claim / truth verification (support, contradiction, staleness, source quality, abstention)",
       "implemented", "app.mo.truth.verifier", "tests/mo_platform/test_truth.py",
       "Lexical and numeric grounding, not an entailment model: it can miss paraphrase. Builds on guards.grounding."),
    _f("intelligence", "Domain router (10 domains, weighted keywords and phrases, confidence, ambiguity)",
       "implemented", "app.mo.intelligence.router", "tests/mo_platform/test_truth.py",
       "Rule-based vocabulary matching; unknown vocabulary routes to 'general'."),
    _f("intelligence", "Context compression and per-tenant semantic cache", "implemented", "app.mo.modelfabric.context",
       "tests/mo_platform/test_context.py",
       "Wired into ModelRouter (opt-in cache, complete_conversation). Extractive summary and a hashed n-gram cache; "
       "token counts are estimates."),
    _f("intelligence", "Evaluation harness with deterministic graders and persisted runs", "implemented",
       "app.mo.evaluation.harness", "tests/mo_platform/test_evaluation.py"),
    _f("intelligence", "LLM-as-judge evaluation", "credential_required", "app.mo.evaluation.harness",
       "tests/mo_platform/test_evaluation.py",
       "Built. A judged case FAILS (never skips) until a model provider is configured. Judged text is injection-screened "
       "and fenced. Tested with a stub grader."),
    # ── MO authority (permission-first execution) ──
    _f("authority", "Capability gateway: args-bound single-use grants, deny-list, finance guardrails, receipts, idempotency",
       "implemented", "app.mo.authority.gateway", "tests/mo_platform/test_authority.py",
       "Grants derive from a real two-party MO approval. The orchestrator's own tool steps still use the "
       "ToolRegistry approval flow rather than this gateway."),
    _f("authority", "Finance guardrails (withdrawals and credential export denied server-side)", "implemented",
       "app.mo.authority.policy", "tests/mo_platform/test_authority.py",
       "Policy only. There are no exchange or broker connectors in this repository."),
    _f("authority", "Agent registry with tool allow-lists and risk ceilings", "implemented",
       "app.mo.lifecycle.agents", "tests/mo_platform/test_authority.py",
       "A registry and enforcement point, not a dynamic worker factory: no agent runtime is spawned."),
    _f("authority", "Validation council (facts, code, security, quality, receipt) with risk-based mandatory sets",
       "partial", "app.mo.council.validators", "tests/mo_platform/test_lifecycle.py",
       "Code validation is a syntax check only; running tests needs a real sandbox provider."),
    _f("authority", "Release pipeline: scan, eval, approval, canary check, promote, rollback", "partial",
       "app.mo.lifecycle.releases", "tests/mo_platform/test_lifecycle.py",
       "Moves a registry pointer; it deploys nothing and does not measure canary traffic. Candidates cannot "
       "touch MO's own authority code."),
    _f("authority", "Dependency provenance, licence classification, SBOM ingest and quarantine", "implemented",
       "app.mo.compliance.provenance", "tests/mo_platform/test_lifecycle.py",
       "Licence data comes from the SBOM or installed package metadata; there is no vulnerability scanning."),
    _f("authority", "Secrets vault with short-lived leases", "partial", "app.mo.vault.leases",
       "tests/mo_platform/test_lifecycle.py",
       "Environment-backed and per process. No HSM/KMS or cloud secrets-manager integration."),
    _f("authority", "Desktop action contract and gated tool", "partial", "app.mo.authority.desktop",
       "tests/mo_platform/test_lifecycle.py",
       "Contract and approval gate only. No OS driver exists, so real actions answer PROVIDER_UNAVAILABLE."),
    _f("authority", "Exchange / broker connectors", "planned", None,
       note="Not built. Would need exchange credentials and a security review."),
    _f("authority", "OpenID Connect SSO", "credential_required", "app.mo.security.oidc",
       "tests/security/test_sso_and_lockout.py",
       "Built (asymmetric algorithms only, iss/aud/exp/verified-email enforced). Needs MO_OIDC_ISSUER and MO_OIDC_AUDIENCE. "
       "Tested with locally generated keys, not a live identity provider."),
    _f("authority", "Container / micro-VM sandbox provider and browser adapter", "planned", None,
       note="Not built yet."),
    _f("governance", "Authentication gate on all original EZ-NEXUS routes; patient routes admin-only and audited",
       "implemented", "app.legacy_gate", "tests/security/test_legacy_gate.py",
       "Legacy tables have no tenant column, so authenticated users share legacy data."),
    _f("governance", "No committed admin password; password lockout after repeated failures", "implemented", "app.auth",
       "tests/security/test_legacy_gate.py"),
    # ── orchestration & protocols ──
    _f("orchestration", "Multi-step orchestrator (DAG, retries, approvals, budgets, resume)", "partial",
       "app.mo.orchestration.runner", "tests/mo_platform/test_orchestration.py",
       "Executes synchronously in the request; a timed-out handler thread is abandoned, not killed."),
    _f("orchestration", "Event fabric", "implemented", "app.mo.events.fabric", "tests"),
    _f("protocols", "MCP client (remote tools become governed local tools)", "implemented",
       "app.mo.protocols.mcp_client", "tests/mo_platform/test_protocols.py",
       "Remote output is untrusted and injection-screened."),
    _f("protocols", "MCP server (JSON-RPC 2.0)", "implemented", "app.mo.protocols.mcp_server",
       "tests/mo_platform/test_protocols.py"),
    _f("protocols", "A2A agent-to-agent (HMAC-SHA256, replay window, shared nonce store)", "implemented", "app.mo.protocols.a2a",
       "tests/mo_platform/test_protocols.py",
       "Replay nonces live in the database so every worker sees them. Inbound tasks also need a tenant token and reach "
       "only scope-free tools on a peer's allow-list."),
    _f("protocols", "Egress guard (SSRF / private-range blocking)", "partial", "app.mo.protocols.netguard",
       "tests/mo_platform/test_protocols.py", "Cannot fully close the DNS-rebinding window."),
    # ── build & voice ──
    _f("builder", "Universal builder runtime and reference build", "implemented", "app.mo.builder",
       "tests/integration/test_builder_api.py"),
    _f("builder", "Workflow engine: all 17 node types executable (API, Webhook, Agent, Database, Transform, Switch, Loop, "
       "Parallel, Subworkflow, Human Task, ...)", "implemented", "app.mo.builder.workflow_nodes",
       "tests/builder/test_workflow_nodes.py",
       "Parallel branches are isolated but run one after another. API/Webhook side effects need a granted approval."),
    _f("builder", "Sandbox execution", "partial", "app.mo.builder",
       note="Process-level isolation, not a container."),
    _f("builder", "Deployment adapters", "planned", None, note="No deploy adapter exists; deploys are not faked."),
    _f("voice", "Conversational voice assistant (wake phrase, follow-ups, governed commands)", "partial",
       "app.mo.voice.engine", "tests",
       "Recognition and synthesis run in the browser; the wake word is a transcript keyword, not acoustic."),
    _f("voice", "Server-side speech-to-text / text-to-speech", "credential_required", "app.mo.voice.providers",
       "tests/voice/test_voice_core.py",
       "Whisper, Deepgram and ElevenLabs REST adapters built; each needs its key. Tested against mock transports only, "
       "not the live services. Streaming transcription and speaker verification are not implemented."),
    # ── observability ──
    _f("observability", "Prometheus metrics and per-tenant tracing", "implemented",
       "app.mo.observability.metrics", "tests/mo_platform"),
    # ── not built ──
    _f("perception", "Computer vision", "planned", None, note="No vision pipeline exists."),
    _f("perception", "Device / desktop control", "planned", None, note="No device-control layer exists."),
    _f("research", "Quantum-ready architecture", "future", None,
       note="A direction only; nothing in this codebase uses quantum computing."),
]

KNOWN_BLOCKERS = [
    "Legacy tables have no tenant column: authenticated users share the legacy data. Patient routes are admin-only and audited; true tenant isolation needs a schema migration.",
    "Orchestrator runs are synchronous; there is no background worker.",
]


def summary() -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    for c in CAPABILITIES:
        out[c["status"]] += 1
    return out


def live_overlay() -> dict[str, Any]:
    """Facts that depend on this deployment right now, so the manifest reflects the running system."""
    from .modelfabric.router import get_router
    from .tools.spec import get_tool_registry
    router = get_router()
    tools = get_tool_registry().list()
    return {
        "model_provider_configured": router.is_configured,
        "tools_registered": len(tools),
        "domain_tools": sum(1 for t in tools if t.name.startswith("domain.")),
        "peer_tools": sum(1 for t in tools if t.kind in ("mcp", "a2a")),
        "wake_word_mode": "transcript-keyword",
        "environment": os.getenv("MO_ENV", "unspecified"),
    }


def manifest() -> dict[str, Any]:
    return {"summary": summary(), "capabilities": CAPABILITIES, "known_blockers": KNOWN_BLOCKERS,
            "live": live_overlay()}
