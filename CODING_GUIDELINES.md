# CODING GUIDELINES

# 1. PRD Superiority

- The PRD is the source of truth. If code conflicts with the PRD, fix the code, not the PRD.
- Do not change user-facing behavior unless the PRD requires it or the user asks for it.
- **Bug fixes must preserve intended behavior.**

> PRD template: `prd/_template.md`. Quality bar lives there.

## PRD Amendment Process
If implementation appears to require behavior different from the PRD:
1. Stop. Explain the conflict.
2. Propose: code change to match PRD, or PRD amendment.
3. Don't amend the PRD without explicit approval.
4. If approved: update PRD first, then code.

---

# 2. Reuse & Dead Code

## Search Before Creating
Before creating a new component/function/hook/service/route/helper, search first. Only create new when nothing fits.

## One Thing, One Place
- No duplicate/parallel systems for the same responsibility (auth, API client, error handler, tenant resolver, etc.).
- If something doesn't fit, extend it — don't fork it.
- Reuse existing UI components, states, design tokens, i18n.

## Dead Code
"If it's not wired in, it's dead code."
- Frontend: reachable from the active app entry path.
- Backend: registered in active router/service/job path.
- Workers/jobs: registered in active queue/worker startup.
- Config: loaded by active settings system.

Dead code is deleted. **Notify the user before deletion** — confirm it isn't actually live. Retired code is explicitly commented as retired.

---

# 3. Work Process

Before editing:
1. Read the relevant PRD section.
2. Search for existing implementation.
3. Identify the active entry path.
4. Identify reusable code.
5. State intended files to change.
6. Edit.

One-line fixes can be brief. Multi-file changes: mandatory.

## New Feature / Module
1. Confirm PRD allows it.
2. Search for adjacent patterns.
3. Reuse existing architecture.
4. Define wire-in point.
5. Define the public API first — deep module, simple interface (§18). Callers must not need internals.
6. Build smallest unit needed behind that interface.
7. Add tests if a pattern exists — against the public API.
8. Report why new code was necessary.

## Architecture Change Gate
Allowed only when: PRD requires it, current architecture can't support behavior safely, change removes a duplicated system, or user explicitly asks.

Before changing: explain why current is insufficient, propose change, list affected files, list migration risks, confirm PRD amendment need, implement minimal approved change.

---
# 3a. Folder Structure

**Feature-first, not layer-first.** Organize code by domain (`auth/`, `billing/`, `projects/`), not by layer (`routes/`, `services/`, `models/`). A domain keeps its routes, service, models, schemas, and tests together.

## Rules
- **Module = domain.** One folder, one responsibility.
- **Module public API** via `__init__.py` / `index.ts`. Other modules import only from it, never deep into internals. Keep it small — modules should be *deep*, not *shallow* (§18).
- **`shared/` is for infrastructure only** (DB client, logger, config, error types). It must not import from domain modules. Code moves here only once it has ≥2 callers (§18).
- **Minimize cross-module dependencies.** When `billing` needs `users`, it goes through its public API — not through internal files.
- **File over ~500 lines** = candidate for splitting.
- **Max 3 levels deep** inside a module. Deeper = wrong cut.

## Examples: Submodules inside a domain

When a module accumulates several files with the same prefix or theme, turn them into a submodule.

**Bad** — flat module, grows forever:
```
projects/
  routes.py
  service.py
  agent_tools.py
  agent_runner.py
  agent_prompts.py
  agent_memory.py
  export_pdf.py
  export_csv.py
```

**Good** — thematic submodules:
```
projects/
  __init__.py
  routes.py
  service.py
  agent/
    __init__.py         # submodule public API
    tools.py
    runner.py
    prompts.py
    memory.py
  export/
    __init__.py
    pdf.py
    csv.py
```

**Rule:** 3+ files with the same prefix (`agent_*`, `export_*`) → submodule. Drop the prefix; it's now in the folder name (`agent/tools.py`, not `agent/agent_tools.py`).

A submodule follows the same rules as a module: public API via `__init__.py`, other parts of the domain import only from it.

---

# 4. Frontend

- Reuse existing UI components, states, styling, i18n.
- Forms handle loading/disabled/success/validation/error states.
- User-facing errors are clear and actionable.

## 4.1 State Sync After Mutations
Stale UI is a bug. Frontend must reflect backend state immediately after create/update/delete.

- After mutation: invalidate or refetch — don't trust local state alone.
- Prefer cache invalidation (React Query `invalidateQueries`, SWR `mutate`) over manual list-splicing.
- **Optimistic updates** allowed when: mutation is fast and usually succeeds, rollback on failure is implemented and visible (toast + revert).
- **Delete**: remove from all visible lists, close detail views pointing to it, invalidate related queries (counts, parents).
- **Create**: new item appears without manual refresh.
- **Update**: all surfaces reflect change (list, detail, breadcrumb).
- Cross-entity effects refresh (deleting a project refreshes dashboard count).

## 4.2 Polling
Use only when streaming isn't available/justified.
- Clear stop condition (done, max attempts, navigation).
- Exponential backoff or sensible fixed intervals — never tight loops.
- Pause when tab hidden (`document.visibilityState`).
- Stop on unmount; don't leak intervals.
- Show progress, not just spinner ("Processing… attempt 3").
- Respect backend rate limits.

## 4.3 Streaming (SSE / WebSocket / Chunked)
For long/progressive ops (AI responses, imports, exports, builds):
- Show **incremental output** as it arrives — never buffer until complete.
- Clear streaming indicator (typing dots, animated cursor, "Generating…").
- **Stage labels** when backend exposes them ("Fetching → Processing → Saving").
- **Cancel/stop** action when supported.
- On disconnect: reconnect with backoff; tell user if it fails.
- On mid-flight error: keep what arrived, show error inline, offer retry.
- Mark completion explicitly — don't leave the user wondering.

## 4.4 Loading & Progress Feedback
Tell the user **what is happening**, not just *that* something is.
- **Skeletons** for predictable layouts.
- **Spinners** only for short indeterminate waits (<1s).
- **Progress bars** when measurable.
- **Stage messages** for multi-step flows.
- Ops >2s show a message explaining the wait.
- Never blank screen while loading.
- Mutation buttons show in-button loading state, disabled during request.
- Long ops remain cancellable when safe.

## 4.5 Accessibility
- Buttons/inputs have labels or accessible names.
- Loading states don't trap keyboard focus.
- Streaming/polling regions use `aria-live="polite"`.
- Error messages near the relevant input, announced to AT.
- Don't communicate state by color alone — icon + text + color.

---

# 5. Tests

Add or update tests when a pattern exists. If skipped, explain why. Run lint/typecheck/tests on changed files before final response.

| Change type | Required tests |
|---|---|
| Backend logic | unit, API endpoint, permission/tenant if access involved |
| Frontend | component, loading/empty/error/success states, user-facing behavior |
| Jobs/workers | retry behavior, idempotency, failure logging |
| Bug fix | regression test that fails before fix, when practical |

---

# 6. Concurrency, Idempotency & Race Conditions

Assume always: 100+ users hit the same flow concurrently, multiple workers process the same job, providers are slow/down/junk, requests retry, users double-click, tenants run many actions in parallel.

## Rules
- Identify shared mutable state before changing concurrent code.
- Never block the event loop with sync work; use async I/O.
- Timeouts on all external calls.
- Move slow work to jobs/queues; don't run inside request handlers.

## Read-Modify-Write
Use one of: atomic SQL update, transaction with row-level lock, optimistic locking / version column, idempotency key.

## DB-Level Invariants
- Unique constraints enforce uniqueness — never rely only on app-level checks.
- Transactions for multi-step state changes.

## Jobs / Queues
- Prevent duplicate processing.
- Make retries safe (idempotent).
- Store job state clearly.
- Handle partial failure.
- **DLQ** for jobs past retry budget; has an owner and review cadence.
- Scheduled jobs: single-run guarantee (locking) across workers.
- Graceful shutdown: stop accepting, drain in-flight, exit.
- Priority queues separate user-blocking from background work.

## External Side Effects
- Create local intent/state before calling provider.
- Record provider response/id.
- Never send the same email/payment/API action twice.

Tests should cover duplicate calls and concurrent execution when practical.

## Rate Limiting & Abuse (incoming)
- Per-IP/user/tenant limits on auth, writes, expensive endpoints.
- Auth: progressive backoff + lockout + anomaly alert.
- Enforce at edge where possible, app as fallback.
- 429s include `Retry-After`; clients respect it.

---

# 7. Performance & Cost

Before implementing, identify whether the change affects: latency, DB queries, job duration, bundle size, memory, throughput, external API usage, or token/$ cost.

## Performance
- No unnecessary sequential awaits when calls can run in parallel.
- Don't fetch more than needed; paginate; never load entire tables.
- Batch external/DB ops when safe.
- Add indexes for new filters/joins/orderings; avoid N+1.
- Respect DB connection pool limits.
- Avoid frontend re-renders from unstable state, oversized components, unnecessary global state.
- Log duration for expensive ops.

## Cost (esp. AI features)
- Token/usage budgets per tenant; hard cap + soft warn.
- Cache deterministic LLM/API responses before re-calling.
- Log cost-per-request for expensive ops.
- Expensive features behind a flag with kill switch.

## Money, Time, Locale
- **Money**: integer minor units or decimal. Never float. Store currency code. Document rounding rule per use case.
- **Time**: store UTC; render in user/tenant TZ. Persist TZ where scheduling matters. ISO 8601 in APIs.
- **Locale**: all user-facing strings via i18n keys. Use locale-aware formatting libs.

---

# 8. Caching

- Cache only when it solves a measured problem (latency, cost, load).
- Define for every cache: key shape, TTL, invalidation trigger, scope (per-tenant/user/global).
- Tenant-scoped data → tenant-scoped keys.
- Never cache secrets or PII unless explicitly required and encrypted.
- Stale cache must never violate an invariant — invalidate on write, not read.

---

# 9. Database & Migrations

- Every schema change includes a migration.
- Backward-compatible when possible.
- No destructive migrations without explicit approval.
- Confirm a recent valid backup before destructive migrations.
- Explain rollback risk for every migration.

## Column Removal
1. Stop writing to the column.
2. Deploy.
3. Confirm no reads/writes remain.
4. Confirm fresh backup.
5. Remove in a later migration.

## Data Migrations
- Idempotent where possible.
- Log records affected.
- Migrate large tables in batches.
- Avoid long locks on production tables.

## Backups
- Production DBs: automated, encrypted, integrity-verified backups.
- Success/failure monitored.
- Retention lives in `ops/backup-policy.md` — code doesn't assume retention windows.
- A backup isn't trusted until a restore test has succeeded.
- Never run destructive production data ops without explicit approval.

---

# 10. Destructive Action Safety

No destructive commands without explicit approval (deleting files, dropping tables/columns, force-pushing, wiping migrations, clearing prod queues, deleting user data).

If destruction seems necessary: explain why, show exact command, explain risk, ask for approval.

---

# 11. Errors, Logging & Observability

## User-Facing Errors
- Safe, friendly errors in toasters/UI.
- Specific about what failed and what to do — not "Something went wrong".
- Show underlying status as smaller secondary line.

> ⓘ **Access Denied**
> You do not have permission to do this.
> *401 — missing role `workspace.admin`*

## Error Taxonomy
- **Operational** (retryable: timeout, 5xx, rate limit) vs **programmer** (bug, assertion) vs **user** (4xx, validation).
- Retry only operational; surface user errors directly; alert on programmer errors.
- Cancellation propagates through async; long ops check between stages.

## Internal Logs
Include when applicable: action, tenant_id, user_id, request/job id, provider, status, failure reason, duration.

Background jobs: log start, major steps, retries, final state, with `job_id` in all related lines.

## Log Levels
- **DEBUG** — developer detail (payload shapes, branch decisions); off in production.
- **INFO** — every state transition, job start/finish, external call outcome; the production default level.
- **WARNING** — retryable/operational failures (timeout, 429, transient 5xx), degraded fallbacks, retries.
- **ERROR** — failures needing human attention: programmer errors, exhausted retries, invariant violations. ERROR lines are what alerting counts — never log expected conditions at ERROR.
- Production runs at INFO. Operational logs are retained **30 days** (policy home: `prd/architecture/60-infrastructure-and-ops.html`).

## Error Codes
Every error envelope's machine-readable `code` follows `domain.reason` (e.g. `accounts.auth_failed`, `campaigns.suppressed`, `ai.budget_exceeded`) — lowercase snake, domain = owning feature module. The catalog lives in the API contract (see `prd/architecture/10-backend-and-api.html`); new codes are added there, never invented ad hoc per call site.

## Redaction
- Never log secrets, tokens, cookies, sessions, passwords, full PII, or raw sensitive payloads.
- Never expose stack traces, SQL errors, or infra details to users.

## Alerting
- Distinguish "log it" from "page someone".
- Alert on: invariant violations, repeated job failures, provider outages, error spikes.
- Every alert points to a runbook or owner.

## Audit Log
Separate from operational logs. Immutable record of who did what to which entity: tenant, actor, timestamp, before/after where relevant. Required for admin actions and impersonation.

---

# 12. Security

- Validate all external input at the boundary.
- Enforce authorization server-side. Never trust `tenant_id`/`user_id`/role/permissions from client.
- File uploads validate type, size, path, content.
- Env vars load through existing config system; new ones documented.
- Never hardcode secrets, API keys, URLs, tenant/user IDs.

## Authentication
- Sessions/tokens: short-lived access + rotating refresh. Revocable server-side.
- Logout invalidates server-side, not just client.
- MFA for admin and tenant-owner roles.
- Password hashing via vetted algo (argon2/bcrypt). No custom crypto.
- Lockout/backoff on repeated failed logins.

## Web Vulnerabilities
- **XSS**: escape on output; no `innerHTML` with untrusted data; enforce CSP.
- **CSRF**: state-changing endpoints require CSRF token or same-site cookie + origin check.
- **SQLi**: parameterized queries only.
- **SSRF**: outbound fetches use allowlist; block private IP ranges.
- **Open redirect**: validate targets against allowlist.
- **Clickjacking**: set frame-ancestors / X-Frame-Options.

## Webhooks (incoming)
- Verify signature before any side effect.
- Reject stale timestamps (replay window).
- Idempotent by provider event id.

## File Storage
- Uploads via presigned URLs; validate type, size, content after upload.
- Virus/content scan before exposing to other users.
- Buckets deny public access by default; sharing via short-lived signed URLs.
- Retention and deletion path per file category.

## Secrets Lifecycle
- Secrets live in the secret manager — not code, git, or config files.
- Rotation procedure for every long-lived secret.
- Compromised secrets revocable without a deploy.

## PII & Data Retention
- Identify PII fields explicitly in the data model.
- Retention period per PII category.
- Deletion path for user-initiated removal.
- No PII in logs, analytics, or third-party tools unless required and documented.

## Compliance
- **Data subject rights**: export and deletion paths; deletion cascades or anonymizes per spec.
- **Consent**: record events (marketing, cookies, ToS version) with timestamp.
- **Data residency**: if region constraints apply, document storage region per data class.

---

# 12a. Multi-Tenancy

> Applies if the app is multi-tenant. If not, adapt these rules to the app's actual scoping model (e.g. user-scoped rights).

Tenant isolation is the highest-priority invariant.

- Every tenant-scoped table has `tenant_id`, indexed, included in every query.
- Prefer DB-level enforcement (RLS, scoped views) over app-level filters.
- `tenant_id` resolved server-side from session — never from request body/query.
- Background jobs carry `tenant_id` in payload; workers re-assert before any read/write.
- Cache keys, file paths, queue names, log fields, metrics: tenant-scoped.
- Cross-tenant leak tests mandatory for any new list/detail/search endpoint.
- Admin/impersonation paths logged to audit log with actor + target tenant.

---

# 13. Dependencies

- No new production dependencies without explicit approval.
- Check if existing dependencies solve it first.
- Prefer stdlib or existing project utilities.
- Research alternatives (web search if needed); explain why chosen one is best.
- Justify on add: why needed, why existing tools insufficient, bundle/runtime/security impact.

---

# 14. API Contracts

- Don't change request/response shapes unless PRD requires it.
- If API changes, update all callers.
- Keep frontend types, backend schemas, tests in sync.
- Don't silently add optional fields without checking consumers.
- Don't hide backend errors behind vague frontend messages.
- Preserve status codes unless there's a clear reason.

---

# 15. External Integrations

All external calls handle: timeout, rate limit, auth failure, malformed response, downtime, retry rules.

- Never assume provider responses are valid.
- Log provider, endpoint, status, safe error details.
- Don't leak provider raw errors — translate to next-step guidance.

## Email & Notifications
- Transactional and marketing pipelines separated (different senders/keys).
- Idempotency key per (recipient, event) — never send twice.
- Honor suppression lists (bounces, complaints, unsubscribes) before send.
- Unsubscribe/preferences link on every marketing email.

---

# 16. Invariants

Identify invariants that must never break before changing logic. Examples:
- A user can only access data from their tenant.
- A job must not send the same email twice.
- A campaign can't be both archived and actively sending.
- A payment must not be marked successful without provider confirmation.
- A deleted entity must not appear in active user flows.
- Frontend state matches backend after mutation.
- Audit log entries are immutable.

If a change touches an invariant, add or update a test for it.

---

# 17. Feature Flags & Rollout

- Risky/large changes ship behind a flag.
- Flags have an owner and removal date — old flags are dead code.
- Document rollout (% ramp, tenant allowlist) and rollback steps before merging.
- Flags default to safe value if flag service is unreachable.

## Deploy & Rollback
- Migration ordering: additive migration → deploy code → backfill → remove old path.
- Rollback plan stated in PR for any migration or risky change.
- Environment parity: staging mirrors prod config shape; differences documented.
- Health checks gate rollout; failed health rolls back automatically.

---

# 18. Code Quality

## Naming
- snake_case (Python), camelCase (JS/TS), PascalCase (components/types).
- Names describe intent, not implementation.

## Comments & Docs
- Comment *why*, not *what*.
- Public functions, complex flows, non-obvious decisions get docstrings.
- Outdated comments are worse than missing ones — update them with the code.

## Linting / Formatting
- Repo configs are authoritative.
- CI fails on lint/format/type errors.
- Don't disable rules locally without a comment.

## Coverage
- Targets in CI config. Don't lower silently.

## Design Principles
- Single responsibility per module/function.
- Validation at boundary (request schema), business rules in service layer, persistence rules at DB.
- Dependency direction: UI → service → data. No upward imports.
- Extract a module when a second caller appears, not before.

## Deep Modules over Shallow
**Prefer deep modules.** Value of a module = functionality provided − interface complexity.
A "module" is **any boundary**: class, service, package, API route, component, hook, repository, agent skill.

- **Deep module**: lots of functionality behind a simple interface. Hides complexity — callers know little, get a lot.
- **Shallow module**: little functionality behind a complex interface. Surfaces complexity — callers must understand nearly as much as the implementation itself. Indirection without abstraction.

> A good module makes the outside world simple, even if the inside is complex.

### Example
**Deep** — caller sees one business concept:
```ts
await billing.applyUsageCharge({ customerId, metric: "ai_tokens", quantity, sourceEventId });
```
Hidden inside: pricing tiers, free limits, idempotency, rounding, VAT, invoice lines, audit log, Stripe sync, error handling.

**Shallow** — every caller must know the workflow, its order, and its edge cases:
```ts
const tier = getTier(customer);
const price = calculatePrice(tier, quantity);
const rounded = roundPrice(price, currency);
const invoice = await createInvoice(customer, rounded);
await syncStripe(invoice);
await writeAuditLog(customer, price, invoice);
await updateUsageLimit(customer, quantity);
```

### Rules
- Design the interface around the **caller's mental model** (business concept), not the implementation's structure.
- Wrap related helpers behind a **domain-level service**: callers use `billing.applyUsageCharge()`, never `calculateTierPrice()` + `syncStripe()` + `writeAuditLog()` directly.
- **Interface first, internals second.** Define the public API and what callers must *not* know, write tests against the public API, then implement behind it.
- Make the **common case the default**; expose options only where callers genuinely diverge. Don't push internal decisions out as config/params.
- **Enforce invariants inside** the module, once — never in every caller.
- Single responsibility means one *purpose*, not one tiny task. A deep module has one responsibility and substantial functionality behind it.
- Don't split a module just to shrink files. If the pieces share internals across the new boundary, the split made two shallow modules out of one deep one.

### Module Contract
Important modules get a short contract (README or doc comment): purpose, public API, invariants, "do not" list.

```md
# Billing Module
Purpose: all customer billing logic for usage-based charges.
Public API: applyUsageCharge(input), previewUsageCharge(input), reverseUsageCharge(input)
Invariants:
- Charges idempotent by sourceEventId.
- Stripe sync only after invoice line creation.
- Amounts stored in cents. Audit log on every charge mutation.
Do not:
- Call Stripe directly from API routes.
- Recalculate prices outside this module.
```

### Shallow-module red flags
- Pass-through functions that only forward to another layer; wrappers that add no behavior, only renaming.
- Signature longer or harder to understand than the body.
- Callers pass many flags/options, or must call 3+ functions in the right order for one logical operation.
- The same workflow copy-pasted across call sites.
- Understanding one change requires opening many files; tests mock many internals.
- Small feature changes touch unrelated layers.
- Business rules living in API routes or UI components.
- Leaky options: parameters that exist only because the module refused to decide.

### Deep-module signs
- Caller code is boring; public API is small.
- Invariants enforced inside; most changes land in one folder/module.
- Tests describe behavior, not internal steps.

### Why this matters for AI-assisted work
Deep modules are **context engineering in code form**. An agent calling `billing.applyUsageCharge(...)` operates on one stable concept; a shallow workflow forces it to infer ordering and edge cases across many files — and invent the rest. Deep modules cut: hallucinated business logic, duplicated logic, missed invariants, over-broad multi-file refactors.

When delegating implementation (to AI or subagents): **design the interface yourself, let the agent implement behind it.**
- ❌ "Add billing for token usage."
- ✅ "Extend the billing module. Public API: `applyUsageCharge(input)`. Callers must not know about Stripe, VAT, tiers, invoice lines, or audit logs. Tests against the public API first, then internals."

> Litmus test: can a caller use the module correctly from its public interface alone, without reading its implementation? Yes → deep enough. No → shallow.

## Code Review
- Every change reviewed before merge.
- Reviewer checks: PRD alignment, reuse, tenant boundary, migration safety, tests, log/PII hygiene.
- Security or migration changes require a second approver.
- PRs small enough to review in one sitting; split otherwise.

## ADRs
Non-trivial design decisions get an ADR in `docs/adr/NNNN-title.md`: context, decision, alternatives, consequences. Linked from PRD when relevant.

---

# 19. Definition of Done

A task is complete only when:
- PRD checked.
- Implementation matches intended behavior.
- New code wired into active app path.
- Existing reusable code searched first.
- No duplicate/parallel system created.
- Relevant tests/checks run, or skipping explained.
- Error handling safe and useful.
- Tenant/security boundaries preserved.
- Performance impact considered; query patterns checked for indexing/N+1.
- Change works under concurrent production usage.
- Final report provided.

---

# 20. Reporting

End every task with:

```md
[Implementation/plan name] - Report
### Files changed
- ...
### What changed
- ...
### What was wired in
- ...
### What was reused
- ...
### Tests/checks run
- ...
### Dead code
- Found / not found
- Deleted only with approval
### PRD
- Relevant section:
- Conflicts:
- Assumptions:
### Simple summary
- Plain-English summary.
```

## Communication
- Use AskUserQuestion for questions.
- Reports: concise, plain language, bullets over prose.

---

# 21. Subagents

- Code exploration in parallel via the built-in `Explore` subagent (this project has no `explorer` agent). Read files directly only before edits or when full context is needed in main thread.
- Use subagents (parallel) when task is >~10 lines OR touches: unfamiliar areas, multi-file changes, architecture, tenant/auth/security, bugs with unclear root cause, PRD/code conflicts.
- If plans are attached or mentioned, **subagents must always read them fully** for good context supplementation
- Skip subagents for: typo fixes, obvious one-file changes, simple config edits.
- Findings summarized before implementation.

> A 12-line fix may not need subagents. A 3-line auth change absolutely does.

## Workflow Parallelism
When orchestrating work across subagents (Workflow tool, or any multi-agent fan-out): **parallelise as much as the dependency graph allows, but never more.**

- **Default to parallel.** Independent units of work run concurrently — never serialize steps that don't depend on each other.
- **Respect dependency order.** A step runs only once everything it depends on has finished. Model this as **dependency waves**: every step whose deps are satisfied runs together in one parallel wave; the next wave starts when the prior one completes.
- **Serialize only on real conflict.** Two steps that edit the *same file* are serialized even if otherwise independent (no two agents mutate one file at once). Everything else fans out.
- **Prefer pipelines over barriers.** Don't make a fast item wait on a slow sibling unless a later stage genuinely needs *all* prior results together (e.g. dedup/merge across the full set). When in doubt, pipeline.
- **Example — implementing a multi-file feature:** the migration + shared schema land first (everyone depends on them); then the backend route, the service, the frontend hook, and the widget change all run in parallel; the integration test waits for the wave it verifies. Don't run those four middle steps one after another — that's wasted wall-clock.

> Sequential when dependent, parallel when not. The dependency graph — not convenience — decides what waits.

## Recursive Subagent Orchestration

Subagents may spawn their own subagents (depth cap **5 hard, 3 soft**: main → orchestrator → workers). Binding for every agent holding the `Agent` tool. **Writers** (executors + orchestrating planners) may spawn writers or `Explore`; **read-only agents** (reviewers + the read-only `architecture-reviewer`) may spawn read-only children only. The built-in `Explore` agent is the sole pure leaf and never spawns.

**Model, effort & who-can-spawn:** the single authoritative statement (pins, roster, spawn topology, audit greps) is **`CLAUDE.md` at the repo root, §9 + §9a** — no recap here; a restated copy is drift and a bug. Root `AGENTS.md` is a symlink to that same file; there is no `.claude/AGENTS.md`. Never pass a `model` param when spawning; the agent file's pin is authoritative.

**FLAT-WAVE FIRST (owner directive 2026-07-25):** recursion is available, not automatic. The default shape is the dispatcher (usually main) launching **LEAF executors directly** from the plan, wave by wave, keeping the aggregating files and the wire-in for itself. This roster is leaf-only — an intermediate orchestrating parent appears only on the three triggers in `CLAUDE.md` §9a (decomposition unknowable up front · ≥5 tasks in one domain in a wave · tasks sharing a file or a new shared module that must be designed during the work). An extra hop that only re-splits an already-split plan is a defect, not diligence.

**Review routing:** normal work routes through the reviewer set per §18 *Code Review*. The single exception is `/quickfix`, where the main session **is** the gate and there is exactly ONE review round — see `CLAUDE.md` §9b.

**WHEN TO FAN OUT (heaviness gate):** re-run the complexity assessment on YOUR OWN task. Minimal/Moderate → do it yourself. Substantial → fan out ONLY if it splits into N independent, disjoint siblings (each owning a non-overlapping file/path set, no shared mutable state). Dependent/sequential work stays in one agent.

**DISJOINTNESS IS AN INVARIANT:** give each child exactly one path set + "touch nothing else — you own these files only". N children → N non-overlapping path sets → no collision, no merge. If you can't carve disjoint sets, it's not a fan-out task. Directory-ownership rules bind at every hop — never spawn two children into the same directory; delegate directory X's work only to X's owner type.

**ORDER AROUND THE FAN-OUT:**
1. **Shared dependencies FIRST, sequentially (barrier)** — a shared type/contract all siblings import is created and awaited before the fan-out. A barrier is justified ONLY by a real input dependency: the sibling must *read* the output. Nothing else earns one.
2. **Independent siblings in parallel** — all `Agent` calls in ONE message, foreground. **Parallel is the DEFAULT; sequential must be EARNED** (owner directive 2026-07-13). Map the dependency graph before dispatching and launch every chunk whose inputs are ready, together. **If only PART of a chunk is blocked, SPLIT it** — dispatch the unblocked part now, the dependent part after; never queue independent work behind a dependency it doesn't have. Re-evaluate on every completion: whatever just became unblocked launches immediately, batched with any other ready work.
3. **Shared aggregating files LAST, single writer** — barrels, route tables, the page importing all children are RESERVED, never handed to children; **the dispatcher** writes them after all children land (main itself in flat-wave mode, the orchestrator when one is in play).
4. **Verify the assembled tree** (build/tests) before reporting up. Report only a terse summary upward, never the children's file dumps. Independent, disjoint tracks may be verified/reviewed in parallel — a reviewer for track A does not wait on track B.

**ISOLATION & NOT LOSING WORK:** default is the SAME working tree, no isolation — disjoint children writing distinct paths can't corrupt each other; commit once at the end; nothing to lose. Use `isolation:"worktree"` ONLY when children must commit independently (own PRs) or disjointness can't be guaranteed. A worktree auto-removes when unchanged → uncommitted work is LOST. Then, non-negotiable: each child's last action is `git add -A && git commit` to its branch (no SHA reported → re-dispatch); the orchestrator merges every child branch and verifies each merge (children count == merges count); disjoint ownership keeps merges conflict-free; re-verify the merged tree before reporting up.

**OBLIGATIONS THAT TRAVEL WITH EVERY CHILD PROMPT (every level):** any prompt you compose for a child MUST carry (1) the "read `CODING_GUIDELINES.md` in full first" instruction, (2) the model/effort policy per `CLAUDE.md` §9 (never pass a `model` override at spawn), (3) the subagent output contract (lead with conclusion, bullets, files by `path:line`, no preamble). Nesting makes each orchestrating agent own these, exactly as the main thread does.

## Orientation
Read `NAVIGATION.md` at repo root before exploring code. Maps paths, secrets, commands, common tasks.

If missing/stale/wrong — flag and fix before continuing.

Doc hierarchy: PRD → CODING_GUIDELINES → CLAUDE.md (`AGENTS.md` symlink) → NAVIGATION.md.

## End-of-Session: Update NAVIGATION.md
Update in the **same commit** as any change that affects it:
- Moved/renamed/added directory or entry point → §3, §4
- Added/changed env var → §5 (+ `.env.example`)
- New dev command, environment, external service → §6, §7, §8
- New common task pattern or project term → §10, §11

Before reporting done, state one of:
> NAVIGATION.md: updated (§X)
> NAVIGATION.md: no update required.

Stale navigation is a bug.

## MEMORY
- Always use memory to see earlier mistakes or relevant info
---

# CLAUDE.md (project root)
Place this section on top of the file before other instructions:

Must contain:
- **What the app is** — eg. multi-tenant SaaS, one-line description.
- **Stack** — every library, framework, service.
- **Architecture** — layering, tenant isolation, call hierarchy, auth flow, state, streaming.
- **Non-negotiable rules** — concurrency, async-only I/O, tokens, tenant isolation, layer discipline, PRD authority.
- **Naming and quality standards** — pointer to §18.
- **Operational constraints** — workers, DB pool, Redis, job locking.
- **PRD governance** — PRDs are source of truth; amendment per §1.
- **Subagent guide** — short table of which agent when.
- **Coding guidelines** — link to this file.

PRD layout:
prd/
backend/...
frontend/...
_template.md

Style: bullets with keywords over full sentences. Always reference the PRD as the overseer.
