---
title: vLLM Deployment
summary: OpenAI-compatible self-hosted model serving for role routing
---

This guide adds a runnable vLLM service to the existing Docker deployment and shows how to connect it to Company LLM Settings.

## What This Provides

- OpenAI-compatible inference endpoint at `/v1`
- Health/readiness checks for startup orchestration
- Optional warmup command to reduce first-token latency
- Failover runbook: role model -> company default -> optional external provider

## 1) Start Paperclip + vLLM via Compose

From the `orchestrator` directory:

```sh
docker compose \
  -f docker-compose.yml \
  -f docker-compose.vllm.yml \
  up --build
```

Set model and optional Hugging Face token as needed:

```sh
VLLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct \
HUGGING_FACE_HUB_TOKEN=hf_xxx \
docker compose -f docker-compose.yml -f docker-compose.vllm.yml up --build
```

### Internal base URL for Company Settings

When Paperclip and vLLM run in the same compose network, set provider `base_url` to:

```txt
http://vllm:8000/v1
```

If testing from host tools directly, use:

```txt
http://localhost:8000/v1
```

## 2) Health / Readiness

The compose override defines a health check against:

```txt
http://127.0.0.1:8000/health
```

`server` depends on `vllm` with `condition: service_healthy`, so the app waits for readiness before startup.

Quick verification from host:

```sh
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/v1/models
```

## 3) Optional Warmup

After startup, run one tiny completion to warm kernels/model caches:

```sh
VLLM_BASE_URL=http://localhost:8000/v1 \
VLLM_WARMUP_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct \
python3 scripts/vllm/warmup.py
```

You can also exec inside the server/vLLM container if preferred.

## 4) Company Settings Mapping

In **Company Settings -> AI/Models**:

- Provider: `vllm_openai_compatible`
- Base URL: `http://vllm:8000/v1`
- Default model: your served model id
- Role models: optional per-role overrides

This aligns with the dynamic LLM config used by the bridge resolver.

## 5) Failover Behavior (Operational)

Recommended failover chain:

1. Role-specific model (for the current role)
2. Company default model (same provider)
3. Optional external provider/model (OpenAI/OpenRouter/etc.) if configured

### Practical fallback runbook

- If a role model fails repeatedly (not found/oom/timeout), set that role to company default model.
- If vLLM itself is unavailable, switch default provider to configured external provider.
- Keep external provider key pre-configured but disabled until needed for controlled cutover.

## 6) Notes

- vLLM GPU sizing and quantization choices determine whether larger models fit reliably.
- Keep model ids in Company Settings exactly matching vLLM-served ids.
- Use `GET /api/companies/:companyId/llm-settings/test` and `GET /api/llm/models` to validate connectivity/model availability before production cutover.

## 7) Observability and Alert Thresholds

Dashboard summary now includes `llmObservability` (24h request/error/latency metrics, provider-model-role breakdown, and approval funnel metrics for the last 30 days).

Recommended alert thresholds:

- `vllm_unavailable` (critical): default provider is `vllm_openai_compatible` and vLLM requests in 24h are `0` while total requests > `0`.
- `error_spike` (warning): 24h error rate exceeds `15%` by default.
- `fallback_activated_repeatedly` (warning): non-default provider requests in 24h exceed `5` by default.

Threshold env overrides (server process):

```txt
LLM_ALERT_ERROR_SPIKE_PERCENT=15
LLM_ALERT_FALLBACK_REPEAT_COUNT=5
```

Guardrails available in Company Settings -> AI/Models:

- Allowed model allowlist (`guardrails.allowed_models`)
- Max timeout cap (`guardrails.max_timeout_seconds`)
- Max tokens/request (`guardrails.max_tokens_per_request`)
- Per-role retry budget (`guardrails.role_retries`)

## 8) Rollout Plan (Flag-Gated)

Dynamic LLM routing is gated behind:

```txt
ZERO_HUMAN_DYNAMIC_LLM_ENABLED=true
```

Default rollout posture: keep this flag `false` in production until pilot validation is complete.

### Pilot enablement (one company)

1. Enable `ZERO_HUMAN_DYNAMIC_LLM_ENABLED=true` on the runtime host.
2. Configure only the pilot company in Company Settings -> AI/Models.
3. Leave non-pilot companies on legacy env-driven model values (`OPENCLAW_MODEL`/`MODEL`).

This works because enabled routing still falls back to env defaults where company-level role mappings are not set.

### What to monitor during pilot

- `llmObservability.requests24h`, `errors24h`, `errorRatePercent24h`
- `llmObservability.p50LatencyMs24h`, `p95LatencyMs24h`
- `llmObservability.byProviderModelRole24h` (cost/tokens split)
- `llmObservability.approvalFunnel30d` for approval throughput
- `llmObservability.alerts` (`vllm_unavailable`, `error_spike`, `fallback_activated_repeatedly`)

### Expansion

1. Add 1-2 more companies after pilot reaches stable error/latency.
2. Expand allowlists and role mappings gradually.
3. Keep alert thresholds unchanged until enough baseline data exists.

### Rollback

Set `ZERO_HUMAN_DYNAMIC_LLM_ENABLED=false` and restart runtime processes.

- Runtime immediately returns to legacy env resolution path.
- Stored company settings remain in DB and are not deleted.
- Re-enabling later resumes dynamic routing without data loss.

