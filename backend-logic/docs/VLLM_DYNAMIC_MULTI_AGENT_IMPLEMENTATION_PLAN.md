# vLLM Dynamic Multi-Agent Implementation Plan

## Objective

Move from a single shared LLM to a role-aware, user-configurable model routing system where:
- Each agent role (Architect, Grunt, Pedant, Scribe) can use a different model/provider.
- vLLM is the default inference gateway for self-hosted models.
- Users can manage model/provider/API key settings from Company Settings (no manual server edits).
- Existing `.env` variables continue to work as global defaults/fallbacks.

Success means a non-technical user can change provider, model, and API key from UI and agents immediately use updated settings safely.

---

## Why vLLM for This Project

vLLM is a strong fit because it gives:
- OpenAI-compatible serving endpoints (easy integration with existing agent calls).
- High throughput for concurrent multi-agent workloads.
- Support for hosting multiple models and routing by role.
- Clear deployment path from one GPU to larger clustered serving.

References:
- [vLLM Documentation](https://docs.vllm.ai/en/latest/)
- [NVIDIA Nemotron Overview](https://www.nvidia.com/en-in/ai-data-science/foundation-models/nemotron/)

---

## Current State (Observed)

The bridge already supports partial dynamic behavior:
- `REPO_LINK` from Company Settings can override static repo URL.
- `MODEL` from Company Settings maps to `OPENCLAW_MODEL` when not already set.
- Runtime is `.env`-aware and keeps environment override semantics.

Gap:
- Model selection is still effectively global, not per role.
- Provider/API key management is not fully standardized per user/company.
- No explicit provider registry, endpoint templates, or key precedence policy.

---

## Target Architecture

1. **Provider Layer**
   - `vllm_openai_compatible` (default)
   - `openai`
   - `anthropic`
   - `openrouter` (optional)
   - Future: `nvidia_nim`

2. **Role Routing Layer**
   - Architect -> high reasoning model
   - Grunt -> strong coding model
   - Pedant -> medium/strong review model
   - Scribe -> efficient low/medium model

3. **Settings Resolution Layer**
   - Company Settings (highest priority)
   - User overrides (if feature enabled)
   - `.env` fallback defaults
   - Safe system default if nothing is set

4. **Credential Layer**
   - API keys encrypted at rest
   - Masked in UI/logs
   - Rotatable without restart (or with lightweight reload)

---

## Configuration Contract

Define one unified config payload persisted per company:

```json
{
  "llm": {
    "default_provider": "vllm_openai_compatible",
    "default_model": "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "providers": {
      "vllm_openai_compatible": {
        "base_url": "http://vllm:8000/v1",
        "api_key": "optional-or-internal-token",
        "enabled": true
      },
      "openai": {
        "api_key": "sk-...",
        "enabled": true
      }
    },
    "role_models": {
      "architect": {
        "provider": "vllm_openai_compatible",
        "model": "deepseek/deepseek-r1-distill-llama-70b"
      },
      "grunt": {
        "provider": "vllm_openai_compatible",
        "model": "qwen/qwen2.5-coder-32b-instruct"
      },
      "pedant": {
        "provider": "vllm_openai_compatible",
        "model": "meta-llama/Meta-Llama-3.1-8B-Instruct"
      },
      "scribe": {
        "provider": "vllm_openai_compatible",
        "model": "meta-llama/Meta-Llama-3.1-8B-Instruct"
      }
    }
  }
}
```

Notes:
- Keep model strings provider-native.
- Allow role override to be optional; fall back to company default model.
- Keep provider block extensible for custom headers and timeout settings.

---

## Role Prompt Structure (Smooth Runtime)

Per-role model routing only helps if the **prompt shape is stable**: same section order every run, clear boundaries, and machine-detectable lines where automation depends on them. The bridge builds the user message in a fixed sequence so OpenClaw and vLLM-backed models behave predictably.

### Principles

1. **Identity first** — Who is speaking, which ticket, which title (anchors the model to one phase of one issue).
2. **Scope and sandbox** — Single phase, work only in `/tmp/zero-human-sandbox/`, require explicit logs (reduces drift and wrong directories).
3. **Skill block** — Inject `skill_prompt` from the skill registry as a single coherent block (task-specific behavior).
4. **Delivery guardrails** — Non-negotiable rules (e.g. only Scribe creates PRs) before role-specific instructions.
5. **Role directive** — Architect / Grunt / Pedant / Scribe wording; Scribe text may differ when `ZERO_HUMAN_GITHUB_MODE` is `tool_first` vs legacy.
6. **Issue body last** — Full `description` as `Instructions:` so the model sees ticket context after role rules (smooth parsing; long bodies do not bury guardrails).

Keep sections **deterministic**: do not randomize order or interleave ad-hoc prose between guardrails and role directives. That keeps multi-provider and multi-model runs comparable and makes log/URL extraction reliable.

### Canonical assembly order

Use this order when extending `build_role_prompt` or any successor helper:

| Block | Purpose |
| --- | --- |
| Opening | `You are {role_name}. You are handling ticket {identifier} - {title}.` |
| Phase + logs + sandbox | One phase only; explicit terminal logs; `/tmp/zero-human-sandbox/` |
| Skill | `{skill_prompt}` (may include structured JSON from `Skill.execute()` when present) |
| Delivery guard | PR/push ownership rules (Scribe-only PR in default modes) |
| Role directive | Role-specific task; Scribe includes `PR_URL:` or `SCRIBE_DONE:` patterns for automation |
| Instructions | `Instructions: {description}` |

Reference implementation: `build_role_prompt()` in `backend-logic/scripts/Python_Bridges/openclaw_bridge_cascade.py`.

### Template (plain text)

Use the same labels in production prompts so minor model swaps (OpenAI, vLLM, OpenRouter) do not change behavior:

```
You are <RoleDisplayName>.
You are handling ticket <IDENTIFIER> - <TITLE>.
Execute only your role-specific phase now, leave clear artifacts for the next role,
and print explicit terminal logs for what you changed.
Work strictly in /tmp/zero-human-sandbox/.

<SKILL_PROMPT_BLOCK>

<DELIVERY_GUARDRAILS>

<ROLE_DIRECTIVE_BLOCK>

Instructions: <ISSUE_DESCRIPTION>
```

### vLLM / self-hosted notes

- Prefer **instruction-tuned** chat templates on the server; the bridge supplies a single user message string—no change to section order required.
- If context limits bite, trim **inside** `Instructions:` or summarize skill output—**do not** drop guardrails or role directives.
- After changing prompt shape, re-run acceptance tests: PR URL extraction, Scribe `tool_first` branch naming, and Pedant/Grunt handoff logs.

---

## Environment and Precedence Rules

Implement explicit precedence (highest to lowest):
1. Runtime heartbeat/company payload (`COMPANY_LLM_CONFIG_JSON` or mapped fields).
2. DB-stored company settings.
3. User-level override (if enabled by company policy).
4. `.env` variables (`OPENCLAW_MODEL`, provider keys).
5. Hardcoded safe defaults.

Recommended env variables:
- `ZERO_HUMAN_LLM_PROVIDER`
- `ZERO_HUMAN_LLM_MODEL`
- `ZERO_HUMAN_LLM_BASE_URL`
- `ZERO_HUMAN_LLM_API_KEY`
- `ZERO_HUMAN_LLM_TIMEOUT_SECONDS`
- `ZERO_HUMAN_ROLE_MODEL_ARCHITECT`
- `ZERO_HUMAN_ROLE_MODEL_GRUNT`
- `ZERO_HUMAN_ROLE_MODEL_PEDANT`
- `ZERO_HUMAN_ROLE_MODEL_SCRIBE`

Back-compat aliases:
- `MODEL` -> `OPENCLAW_MODEL` -> `ZERO_HUMAN_LLM_MODEL`
- Existing `OPENAI_API_KEY` retained as fallback for OpenAI-compatible calls.

---

## Backend Implementation Plan

## Phase 1 - Settings Schema and Storage

1. Add DB table or JSON column for `company_llm_settings`.
2. Encrypt API keys before persistence.
3. Add validation schema:
   - Required provider fields by type.
   - URL format checks for vLLM base URL.
   - Non-empty model names.
4. Add migration with default values for existing companies.

Deliverable: persisted, validated, encrypted LLM settings.

## Phase 2 - Company Settings API

Add/extend endpoints:
- `GET /api/companies/:id/llm-settings`
- `PUT /api/companies/:id/llm-settings`
- `POST /api/companies/:id/llm-settings/test` (probe selected provider/model)
- `GET /api/llm/providers` (capabilities metadata)
- `GET /api/llm/models?provider=vllm_openai_compatible` (optional model list)

Rules:
- Never return raw API keys after save; return masked values.
- Keep audit trail for who changed settings and when.

Deliverable: secure API for dynamic LLM config management.

## Phase 3 - Runtime Resolver in Bridge

1. Create `resolve_llm_config(role_key)` utility.
2. Resolve provider/model/key using precedence rules.
3. Inject resolved config into agent invocation environment.
4. Keep current flow compatible when no new settings exist.
5. Add structured logs:
   - Selected provider/model
   - Source of config (`company_settings`, `.env`, etc.)
   - No secrets in logs

Deliverable: role-aware dynamic model routing in live runs.

## Phase 4 - vLLM Gateway Deployment

1. Deploy vLLM service with one initial model.
2. Expose internal endpoint (example): `http://vllm:8000/v1`.
3. Add health checks and startup readiness probes.
4. Add model warmup script for first-token latency reduction.
5. Configure failover behavior:
   - If role model unavailable, fall back to company default model.
   - Optional second fallback to OpenAI/other external provider.

Deliverable: stable vLLM endpoint integrated with backend runtime.

## Phase 5 - UI/UX for Non-Technical Users

In Company Settings -> AI/Models section:
- Provider selector
- Base URL input (for vLLM/self-hosted)
- API key input with mask + replace behavior
- Default model selector/input
- Per-role model mapping UI (Architect/Grunt/Pedant/Scribe)
- "Test Connection" and "Test Role Config" actions
- Save with validation + success/error messaging

Optional power-user features:
- Per-user override toggle
- Model cost/latency hint labels
- Quick presets (Balanced, High Quality, Low Cost)

Deliverable: full dynamic control from dashboard without code edits.

## Phase 6 - Observability, Guardrails, and Cost Controls

1. Metrics:
   - Requests by provider/model/role
   - Latency (p50/p95)
   - Error rate
   - Token usage and estimated spend
2. Guardrails:
   - Allowed-model allowlist by company
   - Max timeout and max token limits
   - Per-role retry policy
3. Alerts:
   - vLLM unavailable
   - Error spike
   - Fallback activated repeatedly

Deliverable: production-safe operations with visibility.

---

## Suggested Role-to-Model Starting Profile

- Architect: high reasoning model (quality-first)
- Grunt: strong coding model (quality + speed)
- Pedant: medium/strong validator model
- Scribe: efficient model (cost-first, formatting/docs/git guidance)

Keep this as defaults users can edit in UI.

---

## Security Requirements

- Encrypt API keys at rest and mask in all API/UI responses.
- Never print secrets in logs, telemetry, or exception traces.
- Restrict who can edit company LLM settings (admin only).
- Add key rotation path (update without full redeploy).
- Keep `.env` as fallback only; prefer DB/secret manager in production.
- Enforce human approval for major or irreversible agent actions.

---

## Human Approval Guardrails (Major Decisions)

Agents must **not** execute major or irreversible actions without explicit human approval.

Major decisions requiring approval:
- Creating/merging PRs, pushing protected branches, or branch strategy changes.
- Deployments and production config/flag changes.
- Data-destructive actions (delete/reset/truncate/migrations with risk).
- Security-sensitive changes (auth/permissions/policy relaxations).
- High-cost model/provider switches above company threshold.
- Any action tagged `approval_required` by company policy.

Required runtime behavior:
1. Agent creates an **Execution Preview** (plan, touched areas, risk, expected output).
2. System sets issue/run to `awaiting_human_approval`.
3. Execution pauses until decision is recorded.
4. On approval, run resumes with `approval_id` audit trail.
5. On rejection, run is cancelled or sent back for revised plan.

Non-negotiable:
- No silent bypass.
- No auto-approval for major actions unless explicitly configured by admin policy.

---

## Ask Before Proceed Workflow (New Feature)

Goal: add a Cursor-like option where agents ask for permission before starting work.

### Company setting

Add in Company Settings:
- `always_proceed` (legacy/default behavior)
- `ask_before_proceed` (new behavior)
- Optional scope: `major_only` or `every_issue`

### UX flow

When an issue is created and mode is `ask_before_proceed`:
1. Open an approval box/modal before agent execution.
2. Show:
   - issue summary and expected outcome
   - planned steps by role (Architect/Grunt/Pedant/Scribe)
   - model/provider per role
   - risk flags and major-decision markers
3. User can choose:
   - `Approve and Proceed`
   - `Reject`
   - `Request Changes` (optional comment)
4. Agents start only after approval.

### API and persistence

Suggested endpoints:
- `GET /api/issues/:id/execution-preview`
- `POST /api/issues/:id/approval` with `{ decision: "approve" | "reject" | "request_changes", comment?: string }`
- `GET /api/issues/:id/approval-status`

Suggested storage:
- `issue_execution_approvals` (or equivalent):
  - `issue_id`, `run_id`, `approval_required`, `status`
  - `requested_by_agent_id`, `approved_by_user_id`
  - `decision_comment`, `created_at`, `decided_at`

Integration points:
- Planner/bridge emits preview before first role execution.
- Orchestrator blocks dispatch while approval is pending.
- Prompt/env includes approval context after approval.

---

## Testing Plan

1. Unit tests:
   - Config precedence resolution
   - Provider-specific validation
   - Role fallback behavior
2. Integration tests:
   - Save settings via API -> run issue -> role uses expected model
   - Invalid key/model handling surfaces clear user errors
3. E2E tests:
   - UI settings update by admin
   - Agent run executes with new config
   - Logs/metrics reflect correct provider and model

Acceptance checks:
- Changing model from UI affects next run without manual file edits.
- Different roles can run different models in the same issue flow.
- If primary model fails, fallback works and issue remains actionable.
- In `ask_before_proceed` mode, issue execution is blocked until human decision.
- Major decisions cannot execute without explicit approval and audit trail.

---

## Rollout Plan

### Step 1 - Feature Flag
- Add `ZERO_HUMAN_DYNAMIC_LLM_ENABLED=true` for staged rollout.

### Step 2 - Internal Pilot
- Enable for one company/workspace.
- Verify role routing, latency, and stability.

### Step 3 - Gradual Expansion
- Enable for selected customers.
- Monitor error/fallback rates daily.

### Step 4 - Default On
- Make dynamic routing default behavior after stable period.

---

## Step-by-Step Implementation (Plain)

Use this as the **linear build order**. It matches Phases 1–6 plus testing and rollout, but states the work in plain steps without phase names.

1. **Lock the contract** — Finalize the JSON shape under [Configuration Contract](#configuration-contract), precedence order under [Environment and Precedence Rules](#environment-and-precedence-rules), and recommended env names. Treat this as the source of truth before writing persistence or bridge code.

2. **Store company LLM settings** — Add `company_llm_settings` (or equivalent), encrypt API keys at rest, validate provider-specific fields and URLs, ship a migration with safe defaults for existing companies. (Phase 1.)

3. **Add the HTTP API** — Implement GET/PUT for LLM settings, a test/probe endpoint, optional provider/model metadata endpoints, masked key responses, and an audit trail for changes. (Phase 2.)

4. **Wire the bridge** — Implement `resolve_llm_config(role_key)` (or equivalent), apply precedence from heartbeat/DB/env, inject the resolved provider/model/base URL/key into the environment the agent runtime uses, keep legacy behavior when new settings are absent, and log provider/model and config source only (no secrets). (Phase 3.)

5. **Stand up vLLM** — Deploy OpenAI-compatible serving, expose `base_url`, add health/readiness probes, optional warmup, and defined fallback when a role model or endpoint fails (company default, then optional external provider). (Phase 4.)

6. **Build Company Settings UI** — Provider selector, base URL and API key fields (mask/replace), default model, per-role mappings (Architect/Grunt/Pedant/Scribe), and Test Connection actions with clear errors. (Phase 5.)

7. **Add human approval policy** — Implement major-decision classifications and approval-required enforcement with `awaiting_human_approval` state and audit trail. (See [Human Approval Guardrails (Major Decisions)](#human-approval-guardrails-major-decisions).)

8. **Build Ask Before Proceed flow** — Add `always_proceed`/`ask_before_proceed`, issue execution preview modal, approval API, and dispatch blocking until approved. (See [Ask Before Proceed Workflow (New Feature)](#ask-before-proceed-workflow-new-feature).)

9. **Add operations guardrails** — Metrics (requests, latency, errors, tokens/cost), allowlists and limits, retries per role, alerts for vLLM down or repeated fallback. (Phase 6.)

10. **Test end-to-end** — Unit tests for resolver and validation; integration tests for save-settings-then-run; E2E for admin UI change and next agent run; approval-gate tests for blocked-until-approved behavior. Fix gaps before wide rollout.

11. **Roll out safely** — Enable behind `ZERO_HUMAN_DYNAMIC_LLM_ENABLED`, pilot one company, expand gradually, then make dynamic routing the default when stable. ([Rollout Plan](#rollout-plan).)

---

## Definition of Done

Done means:
- Company Settings can fully configure provider/model/API key.
- Per-role model routing works for Architect/Grunt/Pedant/Scribe.
- vLLM endpoint is production-stable with monitoring and fallbacks.
- Existing `.env` users are not broken (backward compatible).
- Admins can update settings safely without engineering intervention.
- Ask-before-proceed can gate issue execution with approve/reject/request-changes.
- Major decisions are guarded by human approval policy.

---

## Step-by-Step Prompts (Copy-Paste One at a Time)

Run these **in order**. Each block is a standalone prompt for your coding agent. The spec for shapes, precedence, and acceptance criteria is always: `backend-logic/docs/VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md`.

**Shared rules for every step:** Match existing repo patterns; do not refactor unrelated code; never log or return raw API keys; preserve backward compatibility with current `.env` and `MODEL` / `OPENCLAW_MODEL` behavior until the new path is wired.

---

### Step 0 — Discovery and alignment

```
Before writing code: read backend-logic/docs/VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md end-to-end. Then open backend-logic/scripts/Python_Bridges/openclaw_bridge_cascade.py and summarize (a) how MODEL/OPENCLAW_MODEL is set today, (b) where openclaw agent is invoked, (c) how build_role_prompt orders sections. Output a short bullet plan that maps repo folders to Phases 1–6 from the doc. Do not implement yet.
```

---

### Step 1 — Phase 1: Settings schema and storage

```
Implement Phase 1 from VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md only.

Add persisted company LLM settings matching the Configuration Contract JSON (providers, default_provider, default_model, role_models). Store API keys encrypted at rest. Add validation (URLs for vLLM, non-empty models, required fields per provider type). Add a migration with safe defaults for existing companies.

Deliver: schema/migration + validation module + brief note of table/column names. No HTTP API yet unless already required by your storage layer tests.
```

---

### Step 2 — Phase 2: Company Settings API

```
Implement Phase 2 from VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md only, building on Step 1 storage.

Add GET/PUT for company LLM settings (paths as in the doc). Responses must mask secrets. Add POST .../llm-settings/test to probe a provider/model. Optionally add GET providers and GET models. Add audit fields for who changed settings and when.

Deliver: endpoints + tests that prove masked keys and validation errors. Wire authorization consistent with other company admin settings in this repo.
```

---

### Step 3 — Phase 3: Runtime resolver in the bridge

```
Implement Phase 3 from VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md only.

Add resolve_llm_config(role_key) (or equivalent) implementing precedence: heartbeat/company payload > DB > user override if enabled > .env > defaults. Inject resolved OPENAI-compatible settings into the environment before openclaw runs (provider, model, base_url, api_key, timeout as applicable). Log provider, model, and config source — never secrets.

Keep behavior identical when new settings are missing (fallback to current MODEL/OPENCLAW_MODEL flow). Do not change the section order in build_role_prompt except via the doc’s “Role Prompt Structure” rules.

Deliver: bridge changes + unit tests for precedence and fallbacks.
```

---

### Step 4 — Phase 4: vLLM gateway deployment (infra)

```
Implement Phase 4 from VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md for this repo’s deployment style.

Provide a runnable or documented vLLM setup exposing OpenAI-compatible /v1, health/readiness checks, optional warmup notes, and documented failover: role model fails → company default → optional external provider if configured.

Deliver: compose/k8s/helm/scripts or docs under the repo’s existing ops pattern; link the internal base_url expected by company settings.
```

---

### Step 5 — Phase 5: Company Settings UI

```
Implement Phase 5 from VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md only.

In Company Settings, add AI/Models: provider selector, base URL, masked API key with replace flow, default model, per-role model mapping (Architect/Grunt/Pedant/Scribe), Test Connection and Test Role actions, save with validation and clear errors. Follow existing UI components and auth.

Deliver: UI wired to Step 2 API + smoke path for a logged-in admin.
```

---

### Step 5A — Human approval guardrails

```
Implement the “Human Approval Guardrails (Major Decisions)” section from VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md.

Add a policy evaluator that marks major actions as approval-required and forces run state to awaiting_human_approval before such actions execute.

Include at minimum: PR/merge/protected push, deploy/prod config changes, destructive data actions, security-sensitive permission/policy changes, and high-cost model/provider switches.

Deliver: policy layer + approval persistence + runtime pause/resume hooks with audit fields.
```

---

### Step 5B — Ask Before Proceed workflow

```
Implement the “Ask Before Proceed Workflow (New Feature)” section from VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md.

Add company setting toggle (always_proceed vs ask_before_proceed, optional scope major_only/every_issue). On issue creation in ask mode, generate execution preview and block execution until user decision.

Add preview + approval APIs and UI modal (Approve / Reject / Request Changes). Agents must not proceed without approval in ask mode.

Deliver: end-to-end approval gate from issue creation to agent start.
```

---

### Step 6 — Phase 6: Observability and guardrails

```
Implement Phase 6 from VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md only.

Add metrics (requests, latency, errors, tokens/cost by provider/model/role where possible), approval funnel metrics (requested/approved/rejected), company allowlists / max tokens / timeouts, per-role retries, and alerts or dashboards consistent with this repo’s observability stack.

Deliver: metrics hooks + documented alert thresholds; avoid unrelated refactors.
```

---

### Step 7 — Testing and acceptance

```
Execute the Testing Plan in VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md.

Add or extend: unit tests for resolver and validation; integration test: save LLM settings via API then run agent path and assert effective model/provider (without leaking keys); E2E if the repo has a harness.

Verify acceptance checks: UI change affects next run; different roles can use different models; primary failure triggers fallback; ask-before-proceed blocks execution until approval; major decisions are blocked without approval. Fix gaps before rollout.
```

---

### Step 8 — Rollout

```
Implement the Rollout Plan in VLLM_DYNAMIC_MULTI_AGENT_IMPLEMENTATION_PLAN.md.

Gate dynamic LLM behind ZERO_HUMAN_DYNAMIC_LLM_ENABLED (default off in prod until ready). Document how to enable for one pilot company, what to monitor, and how to expand. Ensure rollback is turning the flag off without data loss.

Deliver: flag wiring + short operator notes (existing CHANGELOG or ops doc pattern).
```

