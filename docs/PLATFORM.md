# MO NEXUS OMEGA — Platform services

The platform layer sits on the existing MO primitives (`MoResult`, `RequestContext`, hash-chained audit,
`ToolRegistry`, approvals, guards). It adds nothing parallel: every capability below is invoked through
those, tenant-scoped, and audited. The API lives under `/api/mo/platform` and the UI is the
**MO Command Center** tab. The authoritative status of each capability is `GET /api/mo/platform/manifest`;
`tests/mo_platform/test_manifest.py` fails if a claim names a module or test that does not exist.

## What is built

| Area | Module | Notes |
|---|---|---|
| Knowledge / RAG | `app/mo/knowledge` | BM25 + hashed n-gram + entity graph, RRF fusion. Answers cite sources or refuse. |
| Layered memory | `app/mo/memory` | Working, short, long, semantic, episodic, procedural. Private by default; secrets refused; erase needs `confirm`. |
| Autonomy | `app/mo/control/autonomy.py` | Levels 0-5, default 1 (suggest), ceiling 3. Level 4+ / raised ceiling need an MFA admin. Promotion needs >=20 shadow samples and >=95% agreement. Repeated failures demote. |
| Dry-run / rollback | `app/mo/control/reversible.py` | Rollback never self-approves. |
| Orchestrator | `app/mo/orchestration` | DAG of tool / gate steps with retries, budgets, checkpoints, resume. |
| Domain intelligence | `app/mo/intelligence` | Forecast (Holt + seasonal), anomalies, critical path, Monte Carlo, pricing, lead score, pipeline forecast, NPV/IRR/runway, recommender, keywords, action items, briefing. Classical statistics, not neural models. |
| Truth verification | `app/mo/truth` | Claim splitting, evidence linking with citations, contradiction (changed figures / flipped polarity), source quality, freshness, abstention and a human-review flag. Extends `guards.grounding`. Lexical and numeric only: it can miss paraphrase, and support is not proof. |
| Domain router | `app/mo/intelligence/router.py` | 10 domains, weighted keywords and phrases, confidence, ambiguity and alternatives. Unknown vocabulary routes to `general`. |
| Context and cache | `app/mo/modelfabric/context.py` | Extractive context compression and a per-tenant semantic cache that refuses secrets and PII. **Not yet wired into `ModelRouter` calls**; token counts are estimates. |
| Evaluation | `app/mo/evaluation` | Deterministic graders, persisted and audited runs. |
| Protocols | `app/mo/protocols` | MCP client + server (JSON-RPC 2.0), A2A (HMAC-SHA256, 300 s replay window), SSRF egress guard. |
| Observability | `app/mo/observability` | Prometheus metrics, per-tenant traces. |
| Guards | `app/mo/guards` | Prompt-injection screening and PII redaction on model input/output. |

## Governance you will notice

- **The default run needs approval.** At autonomy level 1 even a LOW-risk step waits (`202 PENDING_APPROVAL`).
  Raise the policy for the tool (`PUT /autonomy`, admin) to let it run unattended. This is intended.
- Autonomy for a step is decided by the **tool name** (e.g. `domain.forecast`); the run's recorded level comes from the plan name.
- Metrics are admin-only because the registry is process-global; traces are tenant-scoped.
- Tenants in safe mode get `423` on every write.

## Limitations (also reflected in the manifest)

- Runs are **synchronous**; a handler that times out leaves its worker thread abandoned until it returns.
- The A2A replay-nonce cache is **per process**; multi-worker deployments need a shared store.
- A2A inbound needs a tenant token in addition to the HMAC, and reaches only scope-free tools on the peer's allow-list.
- The egress guard cannot fully close the DNS-rebinding window.
- No LLM-as-judge evaluation (needs a provider credential). No neural embeddings.
- Planned or future, not built: computer vision, device/desktop control, deployment adapters, server-side STT/TTS, "quantum-ready".
- Wake word is transcript keyword matching, not an acoustic model.
- Sandbox execution is process-level, not a container.

## Standing production blockers (unchanged)

151 legacy routes outside `/api/mo` are anonymous (some handle PHI); a default admin password is committed;
10 workflow node types have no executor; `python-jose` still pulls in the `ecdsa` advisory (swap to PyJWT).

## Running the tests

Tests that need a secret-shaped value (to prove guards refuse it) build it at runtime, because CI scans each commit for credential-shaped literals.

```
cd backend && python3 -m pytest ../tests -q
```
