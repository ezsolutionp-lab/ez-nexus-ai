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

## MO authority (permission-first execution)

`POST /api/mo/authority/...` adds the missing execution controls on top of the existing approval engine:

1. `capabilities/request` raises a normal MO approval (two-party, MFA for HIGH/CRITICAL, expiry) that records
   the tool, action, resource and the hash of the arguments. The tier is at least what the tool's own risk needs.
2. After it is approved, the requester collects a one-time grant (`grants`). Only the token's hash is stored.
3. `execute` spends the grant atomically. It fails if the arguments, resource, action, tenant or approval tier differ.
4. Forbidden actions (`withdraw_funds`, `disable_audit`, `mint_admin`, ...) are refused in code with or without a grant.
5. Every outcome writes a receipt (success, failure or refusal). An idempotency key replays the stored receipt instead
   of running the tool again; a refusal does not burn the key.
6. Agents (`agents`) hold only an allow-list and a risk ceiling; the gateway enforces both.
7. Releases move BUILD, SCAN, EVAL, approval, canary check, PROMOTE, with rollback to a previously promoted version.
   A candidate that touches MO's authority code is stopped at SCAN.
8. Dependencies are recorded with licence class; unknown, copyleft and proprietary ones are quarantined until reviewed.
9. The vault issues leases instead of secrets.

Not built: exchange connectors, a real desktop driver, production SSO, a container sandbox, canary traffic
measurement, vulnerability scanning. The manifest lists each with its status.

## Security hardening and remaining capabilities

- **Authentication on the original routes.** `app/legacy_gate.py` is an application-level dependency: every route outside
  `/api/mo` needs a bearer token except a short allow-list (`/`, login, register, SSO exchange, public lead forms,
  emailed approval links, media links). Twilio webhooks need a valid signature; patient routes are admin-only and audited;
  `/ws` needs `?token=`. The frontend attaches the stored token to every call and reopens sign-in on a 401.
- **No committed credentials.** The admin password comes from `DEFAULT_ADMIN_PASSWORD` or is generated to a `0600` file.
  Five failed sign-ins lock an account for 15 minutes. `python-jose` was replaced by PyJWT.
- **SSO.** `POST /auth/sso` verifies an OpenID Connect ID token (asymmetric algorithms only; issuer, audience, expiry and a
  verified email are required). Configure `MO_OIDC_ISSUER` / `MO_OIDC_AUDIENCE`.
- **Address pinning.** Every outbound call resolves the host once, validates every address and connects to that IP, so DNS
  rebinding cannot redirect it. TLS still verifies the original name.
- **Workflow engine.** All 17 node types execute. API/Webhook calls that change anything need a granted approval; the
  Database node is a tenant-scoped key-value store; Parallel branches are isolated but run one after another.
- **Background runs.** `POST /runs/{id}/execute` with `{"background": true}` queues the run on a worker pool. A restart marks
  in-flight runs FAILED so they can be resumed.
- **Deployment.** Off by default. `MO_DEPLOY_ADAPTER=export-bundle` writes a checksummed ZIP; `deploy-hook` triggers your host's
  deploy hook. Both report PARTIAL, never SUCCESS, because MO cannot confirm a launch.
- **Sandbox.** `MO_SANDBOX_MODE=container` runs builds under `docker run` (no network, all capabilities dropped, read-only
  root, non-root) and fails closed if no runtime is reachable.
- **Browser.** `browser.read_page` and the approval-gated `browser.submit_form` drive an isolated Chromium (optional
  `playwright` package); every sub-request goes through the SSRF guard.
- **Provider adapters** (Whisper, Deepgram, ElevenLabs, embeddings, LLM-as-judge, market data) fail with
  `CREDENTIAL_REQUIRED` until configured and are tested against mock transports only.
- **Vertical engines.** Telecom cell health, capacity breach and root cause; hospitality KPIs and overbooking; deal and
  renewal risk and revenue leakage; CVSS 3.1 scoring and incident triage; 12 business-in-a-box blueprints.

Still not built (needs hardware, an OS driver, a trained model or an external account): desktop/device control, acoustic
wake word, speaker verification, object recognition, exchange account connectors. Legacy tables are still not tenant-scoped.

## Governance you will notice

- **The default run needs approval.** At autonomy level 1 even a LOW-risk step waits (`202 PENDING_APPROVAL`).
  Raise the policy for the tool (`PUT /autonomy`, admin) to let it run unattended. This is intended.
- Autonomy for a step is decided by the **tool name** (e.g. `domain.forecast`); the run's recorded level comes from the plan name.
- Metrics are admin-only because the registry is process-global; traces are tenant-scoped.
- Tenants in safe mode get `423` on every write.

## Limitations (also reflected in the manifest)

- A step handler that ignores its timeout keeps its worker thread until it returns (Python cannot kill a thread).
- A2A inbound needs a tenant token in addition to the HMAC, and reaches only scope-free tools on the peer's allow-list.
- LLM-as-judge and neural embeddings are built but need a provider credential (they fail closed without one).
- Planned or future, not built: device/desktop control, exchange account connectors, object recognition, "quantum-ready".
- Wake word is transcript keyword matching, not an acoustic model.
- Sandbox execution is process-level unless container mode is enabled and a runtime is present.

## Remaining production blockers

`pip-audit` still reports a `click` advisory (PYSEC-2026-2132): the fix needs click 8.3+, but `gTTS` requires `click<8.2`. Replacing or dropping gTTS clears it.

Legacy tables have no tenant column, so authenticated users share the legacy data. Third-party adapters have not been
exercised against the live services.

## Running the tests

Tests that need a secret-shaped value (to prove guards refuse it) build it at runtime, because CI scans each commit for credential-shaped literals.

```
cd backend && python3 -m pytest ../tests -q
```
