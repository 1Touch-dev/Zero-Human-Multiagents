# Notification System Terminology

This glossary explains key terms used in the Paperclip multi-agent monitoring and notification setup.

## Core Terms

- **Agent**: A service/process that performs a task (crawler, worker, bridge, orchestrator unit).
- **Agent State**: Current condition of an agent (`running`, `failed`, `stopped`, etc.).
- **Event**: A timestamped update emitted by an agent.
- **Status**: The event type (`started`, `heartbeat`, `warning`, `failed`, `recovered`).
- **Payload**: The JSON data body sent with an event.
- **Metadata**: Extra contextual fields in an event (host, region, task id).

## Integration Terms

- **Webhook**: HTTP endpoint that receives real-time event POST requests.
- **Webhook Receiver**: Service/API route that validates and ingests webhook events.
- **Dispatcher**: Component that sends formatted notifications to external channels.
- **Channel Adapter**: Provider-specific sender function (Slack, Telegram, WhatsApp).
- **Bot Token**: Secret key used by Telegram/Slack bots for API access.

## Alerting Terms

- **Severity**: Alert priority level (`P1`, `P2`, `P3`).
- **P1**: Critical outage/failure; immediate action needed.
- **P2**: Important but less urgent; attention needed soon.
- **P3**: Informational/non-urgent update.
- **Rule Engine**: Logic that decides when and where to notify.
- **Threshold**: Numeric trigger point (e.g., 3 failures in 5 minutes).

## Noise Control Terms

- **Deduplication (Dedup)**: Blocking repeated equivalent alerts from flooding channels.
- **Dedup Key**: Unique grouping key like `agent_id + status + error_code`.
- **Cooldown**: Waiting window before sending the same alert again.
- **Alert Fatigue**: Team desensitization caused by too many noisy alerts.
- **Digest**: Periodic summary message instead of many individual alerts.

## Reliability Terms

- **Retry**: Re-attempting failed notification delivery.
- **Backoff**: Increasing delay between retries.
- **DLQ (Dead Letter Queue)**: Storage for messages that failed after max retries.
- **Idempotency**: Safe repeated processing without duplicate side effects.
- **ACK (Acknowledgement)**: API confirmation that event was accepted (often `202`).
- **Heartbeat**: Periodic "I am alive" signal from an agent.
- **Missing Heartbeat**: No heartbeat in allowed time window; possible outage signal.

## Ops and Governance Terms

- **Runbook**: Step-by-step operational recovery instructions.
- **Observability**: Ability to inspect behavior through logs, metrics, and traces.
- **SLO (Service Level Objective)**: Internal reliability target.
- **SLA (Service Level Agreement)**: External/customer-facing reliability commitment.
- **MTTR (Mean Time To Recovery)**: Average time to restore service after failure.
- **Incident**: A production issue impacting reliability or business outcomes.

## Delivery Lifecycle Terms

- **Ingestion**: Receiving events from agents into the backend.
- **Persistence**: Storing events in database for history/auditing.
- **Fan-out**: Sending one event to multiple channels.
- **Escalation**: Increasing alert visibility when unresolved.
- **Production Hardening**: Reliability/security improvements before full rollout.
