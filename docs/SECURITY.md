# MO NEXUS OMEGA — Security model

## Zero Trust on the MO surface

Two mechanisms, not one convention:

1. **`mo_router()`** returns an `APIRouter` whose every route already depends on
   an authenticated, tenant-resolved `RequestContext`. A new MO endpoint is
   protected because of how the router was constructed.
2. **`audit_route_coverage()`** walks the live app — descending into FastAPI's
   nested included routers — and reports any MO route reachable anonymously.
   `tests/security/test_zero_trust_coverage.py` fails the build if the list is
   non-empty.

Current coverage: **33 MO routes mounted, 31 protected, 2 on the public
allowlist** (`/api/mo/health`, `/api/mo/openapi.json`), **0 unprotected**.

### Known gap — the legacy surface

The 165 pre-existing EZ-NEXUS routes are **not** covered by this. 151 of them
still accept unauthenticated requests, including create/read/update on patient
records. That is tracked as production blocker **BLOCK-01** from the gap
analysis and is not fixed by this change. Closing them is a separate migration
because it breaks existing clients.

## Tenant isolation

`RequestContext.tenant_id` comes from the verified token, never from a request
body or header. `BuildIntent.from_request()` ignores a client-supplied
`tenant_id` entirely. Every `builder_*` and `mo_*` row carries `tenant_id`, and
`require_same_tenant()` raises `POLICY_DENIED` on a mismatch.

Cross-tenant attack tests live in `tests/security/test_tenant_isolation.py`.

## Derived contexts never escalate

`RequestContext.child()` builds the context an agent or workflow step runs
under. It pins the tenant, carries the trace id, and **always sets
`is_admin=False`** — a derived actor cannot inherit administrator authority.

## Tool governance

Every tool call passes, in order: scope → MFA → approval → credential → rate
limit → input schema → execute. Risk level is structural, not advisory:

- `HIGH` and `CRITICAL` tools are approval-gated by construction (`__post_init__`)
- `CRITICAL` tools additionally require an MFA-verified session
- A tool with an unsatisfied `credential_env_var` returns `CREDENTIAL_REQUIRED`
  **before the handler runs**
- A handler exception becomes `FAILED`; a handler returning a non-`MoResult`
  becomes `FAILED`

## Approvals

| Tier | Approvals | MFA | TTL |
|---|---|---|---|
| LOW | 0 | no | 60m |
| MEDIUM | 1 | no | 240m |
| HIGH | 1 | yes | 120m |
| CRITICAL | 2 | yes | 60m |

The requester cannot approve their own request. Expired, rejected and revoked
approvals grant nothing.

## Audit chain

`mo_audit_events` is hash-chained per tenant: each row hashes its content
together with the previous row's `entry_hash`. Editing or deleting any row
breaks every hash after it, and `verify_chain()` reports the exact sequence
number where the chain breaks.

Secrets are redacted at every nesting depth before the payload is hashed or
stored (`api_key`, `password`, `token`, `secret`, `ssn`, and 20 more).

`GET /api/mo/audit/verify` runs the verification live.

## Model fabric and data classification

No MO code instantiates a provider SDK directly. `ModelRouter` enforces:

- `CREDENTIAL_REQUIRED` when no provider is configured — never a fabricated completion
- Fallback across providers, with a circuit breaker after 3 consecutive failures
- Budget ceilings that `BLOCK` rather than warn
- `RESTRICTED` data is `POLICY_DENIED` unless the adapter declares
  `allows_restricted_data`

## Sandbox

See `docs/BUILDERS.md` § Build sandbox for what the sandbox does and does not
guarantee. In short: process-level isolation with rlimits and an env allowlist;
**not** a container, **not** network isolation.

## Secrets

The generated application's `app/security.py` reads `SECRET_KEY` from the
environment with **no default** and raises at import if it is missing. There is
no placeholder key a deployment can accidentally run on.

The MO platform's own `config.py` still carries a committed default admin
password — production blocker **BLOCK-03** from the gap analysis, unresolved.
