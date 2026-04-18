# Telegram Channels Feature Plan

## Objective

Add a complete Telegram notification feature to Paperclip so users can:
- Connect Telegram bots from the UI
- Manage Telegram channels from a dedicated `Channels` section
- Send agent alerts and updates to Telegram smoothly
- Test, enable, disable, and monitor Telegram delivery

This document includes:
- Product scope
- Technical plan
- UI flow
- Step-by-step implementation phases
- Checkpoints
- Developer prompts for each phase

---

## 1. Product Goal

The goal is to let a user open Paperclip, go to `Channels`, add a Telegram bot configuration, verify it, and start receiving agent notifications without manual backend setup each time.

Expected user experience:
1. Open `Channels`
2. Click `Add Channel`
3. Select `Telegram`
4. Enter bot token and target chat ID
5. Test connection
6. Save channel
7. Assign events or alert types
8. Start receiving notifications

---

## 2. Feature Scope

### In Scope

- Telegram bot integration
- UI for creating and managing Telegram channels
- Backend APIs for channel CRUD
- Test-message flow
- Per-channel enable/disable
- Event-to-channel mapping
- Basic delivery logging

### Out of Scope (Initial Version)

- Multi-step approval workflows
- Rich templating UI
- End-user self-service permissions model
- Scheduled digests
- Escalation chains

---

## 3. Terminology

- **Channel**: A configured destination for notifications, such as Telegram.
- **Telegram Bot**: A bot account created in Telegram via BotFather.
- **Bot Token**: Secret token used by backend to call Telegram Bot API.
- **Chat ID**: Target Telegram destination identifier where messages are sent.
- **Channel Config**: Saved user configuration for a notification destination.
- **Test Send**: A validation message sent before saving or enabling a channel.
- **Delivery Log**: Stored result of a notification send attempt.
- **Event Mapping**: Rules that define which agent events go to which channel.

---

## 4. User Story

### Primary User Story

As a Paperclip user, I want to add a Telegram bot from the `Channels` UI so I can receive live agent notifications without keeping the dashboard open.

### Supporting User Stories

- As a user, I want to test my Telegram channel before saving.
- As a user, I want to enable or disable Telegram notifications anytime.
- As a user, I want to choose which events go to Telegram.
- As a user, I want to see whether messages are delivering successfully.

---

## 5. UI Plan

## 5.1 Channels Section

Add or extend a `Channels` section in the UI with:
- Channel list
- `Add Channel` button
- Provider selection (`Telegram` initially)
- Status badges (`Active`, `Disabled`, `Error`, `Testing`)
- Last delivery result
- Edit and delete actions

## 5.2 Add Telegram Channel Modal/Form

Fields:
- `Channel Name`
- `Bot Token`
- `Chat ID`
- `Environment` or scope selector (optional)
- `Enabled` toggle

Actions:
- `Test Connection`
- `Save Channel`
- `Cancel`

Validation:
- Bot token required
- Chat ID required
- Channel name required
- Prevent duplicate active Telegram channel config if that is a business rule

## 5.3 Channel Detail View

After saving, show:
- Provider: Telegram
- Status
- Created date
- Last tested time
- Last message delivery result
- Assigned event types
- Enable/disable toggle
- `Send Test Message` button

---

## 6. Backend Plan

## 6.1 Data Model

Suggested `notification_channels` table:

- `id`
- `user_id` or `workspace_id`
- `name`
- `provider` (`telegram`)
- `is_enabled`
- `bot_token_encrypted`
- `chat_id`
- `settings_json`
- `created_at`
- `updated_at`
- `last_tested_at`
- `last_delivery_status`
- `last_delivery_error`

Suggested `channel_event_mappings` table:

- `id`
- `channel_id`
- `event_type`
- `severity`
- `is_enabled`

Suggested `notification_delivery_logs` table:

- `id`
- `channel_id`
- `event_id`
- `provider`
- `status`
- `request_payload`
- `response_payload`
- `error_message`
- `created_at`

## 6.2 API Endpoints

Recommended endpoints:

- `POST /api/channels`
- `GET /api/channels`
- `GET /api/channels/:id`
- `PATCH /api/channels/:id`
- `DELETE /api/channels/:id`
- `POST /api/channels/:id/test`
- `POST /api/channels/:id/enable`
- `POST /api/channels/:id/disable`
- `PUT /api/channels/:id/mappings`

## 6.3 Telegram Service Layer

Create a Telegram service that:
- Validates bot token format
- Sends test messages
- Sends event notifications
- Handles API errors gracefully
- Writes delivery logs

Core functions:
- `validateTelegramConfig()`
- `sendTelegramTestMessage()`
- `sendTelegramNotification()`
- `formatTelegramMessage()`

---

## 7. Notification Flow

1. User saves Telegram channel from UI
2. Backend stores encrypted bot token and channel metadata
3. User clicks `Test Connection`
4. Backend sends test message through Telegram Bot API
5. Backend returns success/failure to UI
6. Event engine later selects enabled Telegram channels
7. Notification dispatcher sends relevant event message
8. Delivery result is stored and surfaced in UI

---

## 8. Step-by-Step Implementation Plan

## Phase 1 - UI and Backend Foundation

Goal: create basic channel management for Telegram.

Steps:
1. Add `Channels` navigation entry if not already present
2. Build channel list page
3. Add `Add Channel` modal/form
4. Build backend `POST /api/channels`
5. Build backend `GET /api/channels`
6. Store Telegram config securely

Checkpoint:
- User can create and view Telegram channel entries from UI

## Phase 2 - Test Connection Flow

Goal: verify Telegram setup before live usage.

Steps:
1. Add `Test Connection` button in form and detail page
2. Build `POST /api/channels/:id/test`
3. Integrate Telegram Bot API send message call
4. Return structured success/error response
5. Show UI toast/status indicator

Checkpoint:
- User can test Telegram delivery from UI and see result immediately

## Phase 3 - Event Mapping and Live Notifications

Goal: connect agents/events to Telegram channels.

Steps:
1. Build mapping UI for event types and severities
2. Add mapping APIs
3. Connect dispatcher to enabled Telegram channels
4. Format agent messages clearly
5. Log delivery success/failure

Checkpoint:
- Live agent alerts reach configured Telegram channels

## Phase 4 - Reliability and Polish

Goal: make the feature production-ready.

Steps:
1. Encrypt bot tokens at rest
2. Add retry and backoff for failed sends
3. Add last delivery status in UI
4. Add disable/enable controls
5. Add loading states and empty states
6. Add audit logging

Checkpoint:
- Telegram channel management is stable, safe, and easy to operate

---

## 9. UI Checklist

- [ ] `Channels` page exists
- [ ] User can add Telegram channel
- [ ] Form validation works
- [ ] `Test Connection` button works
- [ ] Success and error toasts are clear
- [ ] Saved channels appear in list
- [ ] Channel details page works
- [ ] Enable/disable toggle works
- [ ] Event mapping UI works
- [ ] Delivery status is visible

---

## 10. Backend Checklist

- [ ] Channel schema/model created
- [ ] Bot token stored securely
- [ ] CRUD APIs implemented
- [ ] Test endpoint implemented
- [ ] Telegram API integration implemented
- [ ] Delivery logging implemented
- [ ] Event mapping support implemented
- [ ] Dispatcher integrated
- [ ] Retry/backoff implemented

---

## 11. QA Checklist

- [ ] Save valid Telegram config
- [ ] Reject missing bot token
- [ ] Reject missing chat ID
- [ ] Test message sends successfully
- [ ] Invalid token shows useful error
- [ ] Disabled channel does not receive notifications
- [ ] Enabled mapped channel receives matching events
- [ ] Delivery failure is logged and visible
- [ ] Edit existing channel works
- [ ] Delete channel works safely

---

## 12. UX Recommendations

- Keep the flow short and obvious
- Use plain labels like `Telegram Bot Token` and `Telegram Chat ID`
- Show example formats near fields
- Provide inline help for finding chat ID
- Allow `Send Test Message` at any time
- Show latest status without forcing page refresh

---

## 13. Security Requirements

- Never expose raw bot token after save
- Encrypt token at rest
- Mask token in logs and API responses
- Restrict channel management by auth scope
- Validate outbound message requests
- Rate limit test sends to prevent abuse

---

## 14. Suggested API Contracts

## Create Channel Request

```json
{
  "name": "Ops Telegram",
  "provider": "telegram",
  "botToken": "123456:ABCDEF",
  "chatId": "-1001234567890",
  "isEnabled": true
}
```

## Create Channel Response

```json
{
  "id": "channel_001",
  "name": "Ops Telegram",
  "provider": "telegram",
  "isEnabled": true,
  "lastDeliveryStatus": null
}
```

## Test Response Success

```json
{
  "success": true,
  "message": "Telegram test message sent successfully."
}
```

## Test Response Error

```json
{
  "success": false,
  "message": "Telegram API rejected the bot token."
}
```

---

## 15. Message Format Recommendation

Example Telegram alert:

```text
Paperclip Alert

Agent: crawler-agent
Status: failed
Severity: P1
Environment: production
Reason: Connection timeout to upstream API
Time: 2026-04-16T10:15:30Z
```

Keep messages:
- Short
- Scannable
- Consistent
- Focused on actionability

---

## 16. Developer Prompts

Use these prompts phase by phase when implementing with an AI coding assistant.

## Prompt 1 - Build Channels UI Foundation

```text
Implement a Channels management section for the Paperclip UI. Add a page that lists notification channels and includes an "Add Channel" action. Create a Telegram channel form with fields for channel name, bot token, chat ID, enabled toggle, and buttons for Save and Test Connection. Keep the UI clean and production-oriented, with validation and loading states.
```

## Prompt 2 - Build Backend Channel APIs

```text
Implement backend APIs for Telegram channel management. Add endpoints to create, list, update, delete, enable, disable, and test Telegram channels. Store bot tokens securely, validate required fields, and return clean error messages. Structure the code so more providers like Slack and WhatsApp can be added later.
```

## Prompt 3 - Add Telegram Service Integration

```text
Implement a Telegram notification service that sends test messages and live agent alerts through the Telegram Bot API. Add functions for formatting messages, sending notifications, handling API failures, and logging delivery results. Keep the integration reusable and provider-agnostic where reasonable.
```

## Prompt 4 - Add Event Mapping

```text
Extend the Channels feature so users can map event types and severities to Telegram channels. Add backend support for saving event mappings and update the UI to let users choose which agent updates should be sent to Telegram. Only enabled mappings should trigger notifications.
```

## Prompt 5 - Add Reliability and Polish

```text
Harden the Telegram channels feature for production. Add encrypted token storage, retry with backoff for delivery failures, delivery status indicators in the UI, and audit logs for test sends and live notifications. Improve UX with clear success and error states.
```

---

## 17. Final Delivery Milestones

### Milestone 1
- Telegram channel can be created from UI

### Milestone 2
- User can send test message successfully

### Milestone 3
- Live agent events can be routed to Telegram

### Milestone 4
- Delivery logs and UI status are visible

### Milestone 5
- Feature is secure and production-ready

---

## 18. Definition of Done

This feature is done when:
- A user can add Telegram from the `Channels` UI
- Telegram config can be tested before activation
- Live agent events can be delivered to configured Telegram channels
- Delivery outcomes are visible in the UI
- Secrets are protected properly
- The feature is stable enough for daily operational use
