# MO Universal Builder Runtime

How a plain-English prompt becomes a built, tested project — and exactly where
the Builder stops and asks a human.

## The pipeline

```
BuildIntent
  → RequirementEngine      requirements, assumptions, blocking questions
  → ArchitecturePlanner    recommendation + scored alternatives
  → ProjectGraph           models, APIs, pages, agents, tools, workflows
  → CodeGenerator          real source + runtime scaffold + generated tests
  → BUILD_SANDBOX          compile → static analysis → generated tests
  → PreviewManager         labelled PREVIEW, never production
  → ApprovalEngine         deployment always needs a second party
```

Each stage writes a versioned row (`builder_*` tables) and an audit record.

## Compiler stages

`CompilerStage` defines fifteen ordered stages, from `INTENT` to
`DEPLOYMENT_MODEL`. Every stage reports a `ResultState`; a stage that fails
stops the pipeline and sets the project's status to that failure. There is no
path that reports `COMPLETE` when a required stage failed.

## Requirement engine: rule-based first

The engine has two paths, and the output always says which one ran:

| Provenance | When | What it needs |
|---|---|---|
| `RULE_BASED` | always | nothing — deterministic catalogue matching |
| `MODEL_ASSISTED` | a model provider is configured | `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` |

With no provider configured the engine still produces a complete specification
and records `model_enrichment.state = CREDENTIAL_REQUIRED`. It does not claim a
model shaped the requirements when none did.

The catalogue (`mo/builder/catalog.py`) holds 14 modules. Domain profiles infer
a baseline set of modules from a signal like "plumbing" — and **every inference
is written to `builder_assumptions`**, so an inferred module is never mistaken
for something the user asked for.

## Stacks

Only stacks with a real generator may be requested:

- **Implemented:** `fastapi_react`
- **Planned (rejected with `BLOCKED`):** `nextjs_fastapi`, `django_react`,
  `nestjs_react`, `flutter_fastapi`, `spring_react`

Requesting a planned stack raises `BLOCKED` at the door rather than generating
something that does not work. `GET /api/mo/builder/stacks` reports both lists.

## What gets generated

For a project with 8 data models the `fastapi_react` generator emits 51 files:

- `app/models/*.py` — SQLAlchemy models with `tenant_id`, soft delete, timestamps
- `app/schemas/*.py` — Pydantic v2 Base/Create/Update/Out
- `app/routers/*.py` — CRUD through `secure_router()`, tenant-filtered, soft delete
- `app/security.py` — the secure auth template; refuses to start without `SECRET_KEY`
- `app/database.py`, `app/observability.py`, `app/main.py` — runtime scaffold
- `tests/test_models.py`, `test_schemas.py`, `test_security.py`, `test_app.py`
- `requirements.txt`, `.env.example`, `.gitignore`, `README.md`

Generated Python is syntax-checked with `ast.parse` before it is accepted.

## Generated security properties

The generated project's own tests assert these, so a generator regression fails
the build:

- Every router is built through `secure_router()` — no bare `APIRouter`
- Every query filters on `tenant_id == ctx.tenant_id`
- No hard deletes; `is_deleted` soft delete only
- No hardcoded secrets, no string-built SQL (static analysis, exits non-zero)
- Anonymous requests to `/api/*` return 401

## Build sandbox

`BUILD_SANDBOX` runs each stage as a separate process with an environment
allowlist (no `ANTHROPIC_API_KEY`, no `DATABASE_URL`), CPU/memory/file-size/
process rlimits, its own process group, and a wall-clock timeout.

**Honest limitation:** this is process-level isolation, not a container. It has
no kernel namespaces, no seccomp, and no true network isolation.
`SandboxProfile.isolation_level` reports `PROCESS_RLIMIT` so callers cannot
mistake it for something stronger. Running genuinely untrusted third-party code
at scale needs a container runtime with network policy.

## AI Agent Builder

`compile_manifest()` → `run_agent_tests()` → `deploy_agent()`.

Status lifecycle: `DRAFT → BUILDING → TESTING → FAILED | READY → DEPLOYED →
DISABLED | DEPRECATED`.

`run_agent_tests` runs six checks: tool permission, tool execution, approval
gate, tenant isolation, structured-output policy, **and a real model call**. An
agent only reaches `READY` when all six pass. With no model provider configured
the model-call check fails with `CREDENTIAL_REQUIRED` — it is never skipped, and
the agent is never marked ready.

Manifests are versioned per tenant: a second project needing a "Booking Agent"
gets `1.0.1`, leaving the first manifest and its test report intact.

## Workflow builder

Nodes compile to an executable definition and actually run: `Tool` nodes go
through `ToolRegistry` governance, `Event` nodes through the durable Event
Fabric, `Approval` nodes block until a real approval is granted.

Node types with no executor wired yet (`Agent`, `API`, `Database`, `Webhook`,
`Subworkflow`, `Human Task`, `Switch`, `Loop`, `Parallel`, `Transform`) return
`BLOCKED` naming the gap. The workflow does not claim they ran.

## Deployment

`compile()` never deploys. `request_deployment()` always returns
`APPROVAL_REQUIRED`:

| Environment | Risk tier | Approvals | MFA |
|---|---|---|---|
| staging | HIGH | 1 | yes |
| production | CRITICAL | 2 | yes |

The requester cannot approve their own request. `execute_deployment()` verifies
a granted, unexpired approval — then reports `CREDENTIAL_REQUIRED` because **no
deployment provider adapter is implemented**. It does not claim a deploy.

## Voice

`POST /api/mo/voice/command` resolves the same `RequestContext` through the same
dependency, marks it `source_channel=VOICE`, and calls the same
`BuilderCompiler`. A spoken deploy request hits the identical approval gate.
Voice commands are audited with `source_channel=VOICE`.

## Export

`GET /api/mo/builder/projects/{id}/export` returns a ZIP of the complete source
plus `MO_BUILD_MANIFEST.json` with per-file SHA-256. No builder lock-in.
