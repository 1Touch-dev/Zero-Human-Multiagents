# Paperclip Multi-Agent Notification System
## Implementation Plan (Slack + Telegram + WhatsApp + Dashboard)

## 1) Objective

Build a centralized event and notification pipeline so you do not need to keep the dashboard open continuously to monitor agent health.

Expected outcomes:
- Real-time agent visibility
- Fast failure/stopped detection
- Actionable alerts in communication channels
- Historical audit trail of all events
- Reduced notification noise via policy controls

---

## 2) Scope

### In Scope (Phase 1)
- Standardized agent event publishing
- Central webhook/API ingestion endpoint
- Event persistence in database
- Rule-based alert triggering
- Slack and Telegram notifications
- Notification center panel in dashboard

### Deferred (Phase 2+)
- WhatsApp integration (policy and setup overhead)
- Escalation ladders and on-call schedules
- AI anomaly detection

---

## 3) Architecture

1. Agent emits event (`started`, `heartbeat`, `warning`, `failed`, `stopped`, `recovered`)
2. Webhook receiver validates and stores event
3. Rule engine maps severity and applies anti-spam logic
4. Dispatcher sends to Slack/Telegram/WhatsApp
5. Dashboard reads same data source for live + history

---

## 4) Event Contract

Use one schema for all producers.

```json
{
  "event_id": "uuid",
  "agent_id": "agent-42",
  "agent_name": "crawler-agent",
  "status": "failed",
  "severity": "P1",
  "timestamp": "2026-04-16T10:15:30Z",
  "environment": "prod",
  "message": "Connection timeout to upstream API",
  "error_code": "UPSTREAM_TIMEOUT",
  "metadata": {
    "host": "node-a1",
    "region": "ap-south-1",
    "task_id": "task-9931"
  }
}
```

Required fields:
- `event_id`
- `agent_id`
- `status`
- `timestamp`
- `environment`

---

## 5) Notification Policy

Severity mapping:
- `P1`: `failed`, unexpected `stopped` -> immediate alert
- `P2`: `recovered`, repeated warning trends -> medium urgency
- `P3`: regular `heartbeat` and non-critical events -> dashboard only or digest

Anti-spam controls:
- Dedup key: `agent_id + status + error_code`
- Cooldown windows:
  - P1: 5 minutes
  - P2: 15 minutes
  - P3: no direct push
- Batch repeat failures into periodic summaries

---

## 6) Step-by-Step Delivery Plan

### Phase A - Foundation (Day 1)
1. Freeze event schema version (`v1`)
2. Create `/events` endpoint
3. Add webhook auth/signature validation (token or HMAC)
4. Persist incoming events in `events` table
5. Return fast ACK (`202 Accepted`)

Deliverable: events received and queryable from DB.

### Phase B - Rule Engine + Dispatcher (Day 2)
1. Implement severity mapping logic
2. Add dedup + cooldown checks
3. Build channel adapters:
   - `sendSlack()`
   - `sendTelegram()`
4. Add retries with exponential backoff
5. Add failed-send tracking (DLQ or persistent retry queue)

Deliverable: reliable Slack + Telegram notifications.

### Phase C - Dashboard Notification Center (Day 3)
1. Add "Agent Notifications" view
2. Filters: status, severity, agent, timeframe
3. Add per-agent timeline
4. Show current state + last heartbeat

Deliverable: one-screen operational visibility.

### Phase D - Hardening (Day 4+)
1. Add metrics and alerts:
   - Event ingest rate
   - Dispatch success rate
   - End-to-end latency
2. Add "missing heartbeat" detector
3. Create incident runbook
4. Run failure drills and integration tests

Deliverable: production readiness with operational confidence.

---

## 7) Channel Rollout

### Slack (First)
- Lowest setup friction
- Rich formatting and team workflow fit

### Telegram (Second)
- Fast bot setup and direct push alerts

### WhatsApp (Third)
- Use Twilio WhatsApp or Meta Business API
- Requires template and policy compliance

---

## 8) Minimal Data Model

### `events`
- `id` (pk)
- `event_id` (unique)
- `agent_id`
- `status`
- `severity`
- `timestamp`
- `environment`
- `message`
- `error_code`
- `metadata` (json/jsonb)

### `notifications`
- `id` (pk)
- `event_id` (fk)
- `channel` (`slack`, `telegram`, `whatsapp`)
- `delivery_status` (`sent`, `failed`, `retrying`)
- `attempt_count`
- `sent_at`
- `error_message`

---

## 9) Security and Reliability Checklist

- Webhook authentication required
- Rate limiting on ingestion endpoint
- Schema validation on every payload
- Secrets stored in env/secret manager only
- Retries + backoff for channel delivery
- DLQ/persistent logging for failed notifications
- Idempotent processing for duplicate events

---

## 10) Definition of Done

Done means:
- All agents emit standardized events
- P1 failures are notified within target latency
- Duplicate alert noise is controlled
- Team can monitor state/history without always watching dashboard
- Runbook is written and validated by at least one drill
