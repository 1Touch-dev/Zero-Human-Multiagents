# Multi-Agent Notification Rollout Checklist

Use this tracker to execute implementation in phases and keep rollout controlled.

## Legend

- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete

---

## Phase 0 - Planning and Alignment

- [ ] Confirm business goal and success metrics
- [ ] Freeze event schema (`v1`)
- [ ] Finalize severity policy (`P1`, `P2`, `P3`)
- [ ] Confirm initial channels: Slack + Telegram
- [ ] Assign owners for backend, dashboard, DevOps, QA
- [ ] Define rollout timeline and risk owner

Exit criteria:
- Signed-off architecture and policy
- Team owner map complete

---

## Phase A - Event Ingestion Foundation

- [ ] Create `/events` API endpoint
- [ ] Add authentication/signature validation
- [ ] Add payload schema validation
- [ ] Add idempotency handling for duplicate `event_id`
- [ ] Persist events in DB (`events` table)
- [ ] Return fast `202 Accepted` response
- [ ] Add structured logs for each ingest action

Exit criteria:
- Events from test agents are stored correctly
- Invalid payloads are rejected safely

---

## Phase B - Rule Engine and Alert Routing

- [ ] Implement severity mapper from status to priority
- [ ] Implement dedup key strategy
- [ ] Implement cooldown windows by severity
- [ ] Build Slack adapter
- [ ] Build Telegram adapter
- [ ] Add retry + exponential backoff
- [ ] Add failed-send persistence (DLQ/retry queue)
- [ ] Add audit record in `notifications` table

Exit criteria:
- P1 failures alert instantly in Slack and Telegram
- Duplicate spam is controlled under repeated failures

---

## Phase C - Dashboard Notification Center

- [ ] Add notifications page/panel
- [ ] Add filters (agent, status, severity, time range)
- [ ] Add current state badges per agent
- [ ] Show last heartbeat timestamp
- [ ] Add event timeline view per agent
- [ ] Add link from alert message to dashboard detail view

Exit criteria:
- Team can view health and history without tailing logs
- Dashboard and alerts are cross-linked

---

## Phase D - Hardening and Operations

- [ ] Add system metrics (ingest rate, dispatch success, latency)
- [ ] Add missing-heartbeat detector
- [ ] Add operational runbook
- [ ] Add unit tests for schema/rules/dedup
- [ ] Add integration tests for end-to-end flow
- [ ] Run failure drills (crash, timeout, channel outage)
- [ ] Document known limitations and mitigations

Exit criteria:
- Production reliability baseline established
- Runbook validated by at least one drill

---

## Phase E - WhatsApp Rollout (Optional after stabilization)

- [ ] Choose provider (Twilio or Meta WhatsApp Business API)
- [ ] Configure credentials and template approvals
- [ ] Implement WhatsApp adapter
- [ ] Validate policy/compliance constraints
- [ ] Add channel-specific fallback/retry logic
- [ ] Pilot with limited alert types

Exit criteria:
- WhatsApp alerts deliver reliably for selected severities
- Compliance and template requirements are satisfied

---

## QA and Validation Matrix

- [ ] Agent emits `started` -> stored, no high-priority alert
- [ ] Agent emits `failed` -> P1 alert sent once during cooldown
- [ ] Agent emits repeated `failed` -> dedup works
- [ ] Agent emits `recovered` -> P2 recovery alert sent
- [ ] No heartbeat in threshold -> missing-heartbeat alert sent
- [ ] Channel API timeout -> retry and DLQ behavior works

---

## Production Go-Live Readiness

- [ ] Secrets managed securely (no plaintext in repo)
- [ ] Alert routing verified with real channels
- [ ] On-call/owner list attached to alerts
- [ ] Dashboard panel validated with production-like load
- [ ] Rollback plan documented
- [ ] Final go-live signoff completed

---

## Post-Go-Live (Week 1)

- [ ] Review alert noise and tune cooldowns
- [ ] Measure MTTR improvement
- [ ] Track missed alerts and root causes
- [ ] Prioritize next improvements (escalations/digests/analytics)
