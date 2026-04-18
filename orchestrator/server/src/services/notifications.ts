import { and, eq } from "drizzle-orm";
import type { Db } from "@paperclipai/db";
import { notificationChannelMappings, notificationChannels, notificationDeliveryLogs } from "@paperclipai/db";
import type {
  NotificationChannelProvider,
  NotificationEventType,
  NotificationSeverity,
  NotificationChannelTestResult,
  NotificationChannelTestStatus,
} from "@paperclipai/shared";
import { notFound, unprocessable } from "../errors.js";
import { logger } from "../middleware/logger.js";
import { secretService } from "./secrets.js";
import { logActivity } from "./activity-log.js";

type ChannelRow = typeof notificationChannels.$inferSelect;

type TelegramDraftConfig = {
  botToken: string;
  chatId: string;
};

type AgentAlertInput = {
  agentId: string;
  agentName: string;
  status: string;
  outcome: "succeeded" | "failed" | "cancelled" | "timed_out";
  eventType: NotificationEventType;
  severity: NotificationSeverity;
  runId?: string | null;
  errorMessage?: string | null;
  trigger?: string | null;
};

type DeliveryStatus = "sent" | "failed";

type DeliveryLogInput = {
  companyId: string;
  channelId?: string | null;
  provider: NotificationChannelProvider;
  messageType: "test_message" | "agent_alert";
  status: DeliveryStatus;
  requestPayload: Record<string, unknown>;
  responsePayload?: Record<string, unknown> | null;
  errorMessage?: string | null;
};

type ProviderSendInput = {
  channel: ChannelRow | null;
  companyId: string;
  messageType: "test_message" | "agent_alert";
  text: string;
  token: string;
  settings: Record<string, unknown>;
};

type ProviderSendResult = {
  message: string;
  providerPayload: Record<string, unknown> | null;
  attempts: number;
};

type ProviderAdapter = {
  send: (input: ProviderSendInput) => Promise<ProviderSendResult>;
};

const DEFAULT_TEST_MESSAGE = "Paperclip test notification: Telegram channel is connected.";
const RETRY_BASE_DELAY_MS = 500;
const RETRY_MAX_ATTEMPTS = 3;

class DeliveryError extends Error {
  retryable: boolean;
  statusCode: number | null;

  constructor(message: string, opts?: { retryable?: boolean; statusCode?: number | null }) {
    super(message);
    this.name = "DeliveryError";
    this.retryable = opts?.retryable ?? false;
    this.statusCode = opts?.statusCode ?? null;
  }
}

function asObject(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function normalizeChatId(chatId: string) {
  return chatId.trim();
}

function getTelegramSettings(settings: unknown): { chatId: string } {
  const record = asObject(settings);
  const chatId = typeof record.chatId === "string" ? normalizeChatId(record.chatId) : "";
  if (!chatId) {
    throw unprocessable("Channel is missing a Telegram chat ID.");
  }
  return { chatId };
}

function normalizeTestMessage(message?: string) {
  const normalized = message?.trim();
  return normalized && normalized.length > 0 ? normalized : DEFAULT_TEST_MESSAGE;
}

function asApiDescription(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  if (!("description" in payload)) return "";
  return String((payload as Record<string, unknown>).description ?? "").trim();
}

function asApiOk(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return true;
  if (!("ok" in payload)) return true;
  return Boolean((payload as Record<string, unknown>).ok);
}

function buildTestMessage(text: string) {
  return ["[Paperclip Test]", "", text].join("\n");
}

function buildAgentAlertMessage(input: AgentAlertInput) {
  const lines = [
    "[Paperclip Agent Alert]",
    "",
    `Agent: ${input.agentName} (${input.agentId})`,
    `Status: ${input.status}`,
    `Outcome: ${input.outcome}`,
    `Event: ${input.eventType}`,
    `Severity: ${input.severity}`,
    `Time: ${new Date().toISOString()}`,
  ];

  if (input.runId) {
    lines.push(`Run: ${input.runId}`);
  }
  if (input.trigger) {
    lines.push(`Trigger: ${input.trigger}`);
  }
  if (input.errorMessage) {
    lines.push(`Error: ${input.errorMessage}`);
  }
  return lines.join("\n");
}

async function sendTelegramMessage(input: {
  botToken: string;
  chatId: string;
  text: string;
}): Promise<ProviderSendResult> {
  const endpoint = `https://api.telegram.org/bot${input.botToken}/sendMessage`;
  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: input.chatId,
        text: input.text,
        disable_web_page_preview: true,
      }),
    });
  } catch {
    throw new DeliveryError("Unable to reach Telegram API.", { retryable: true });
  }

  const payload = await response.json().catch(() => null);
  const apiDescription = asApiDescription(payload);
  if (!response.ok) {
    const retryable = response.status === 429 || response.status >= 500;
    throw new DeliveryError(apiDescription || "Telegram API rejected the request.", {
      retryable,
      statusCode: response.status,
    });
  }
  if (!asApiOk(payload)) {
    throw new DeliveryError(apiDescription || "Telegram API returned a failed response.", { retryable: false });
  }

  return {
    message: "Telegram message sent successfully.",
    providerPayload: asObject(payload),
    attempts: 1,
  };
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toRetryDelayMs(attempt: number) {
  const expDelay = RETRY_BASE_DELAY_MS * 2 ** (attempt - 1);
  return expDelay + Math.floor(Math.random() * 100);
}

const providerAdapters: Record<NotificationChannelProvider, ProviderAdapter> = {
  telegram: {
    send: async (input) => {
      const settings = getTelegramSettings(input.settings);
      return sendTelegramMessage({
        botToken: input.token.trim(),
        chatId: settings.chatId,
        text: input.text,
      });
    },
  },
  slack: {
    send: async () => {
      throw unprocessable("Slack provider is not implemented yet.");
    },
  },
  whatsapp: {
    send: async () => {
      throw unprocessable("WhatsApp provider is not implemented yet.");
    },
  },
};

export function notificationService(db: Db) {
  const secrets = secretService(db);

  async function updateChannelTestStatus(channelId: string, status: NotificationChannelTestStatus, message: string) {
    await db
      .update(notificationChannels)
      .set({
        lastTestStatus: status,
        lastTestMessage: message,
        lastTestedAt: new Date(),
        updatedAt: new Date(),
      })
      .where(eq(notificationChannels.id, channelId));
  }

  async function logDelivery(input: DeliveryLogInput) {
    await db.insert(notificationDeliveryLogs).values({
      companyId: input.companyId,
      channelId: input.channelId ?? null,
      provider: input.provider,
      messageType: input.messageType,
      status: input.status,
      requestPayload: input.requestPayload,
      responsePayload: input.responsePayload ?? {},
      errorMessage: input.errorMessage ?? null,
      createdAt: new Date(),
    });
  }

  async function sendThroughProvider(input: {
    channel: ChannelRow | null;
    companyId: string;
    provider: NotificationChannelProvider;
    token: string;
    settings: Record<string, unknown>;
    text: string;
    messageType: "test_message" | "agent_alert";
  }): Promise<ProviderSendResult> {
    const adapter = providerAdapters[input.provider];
    if (!adapter) {
      throw unprocessable(`Provider "${input.provider}" is not supported.`);
    }

    let lastError: unknown = null;
    for (let attempt = 1; attempt <= RETRY_MAX_ATTEMPTS; attempt += 1) {
      try {
        const result = await adapter.send({
          channel: input.channel,
          companyId: input.companyId,
          messageType: input.messageType,
          text: input.text,
          token: input.token,
          settings: input.settings,
        });
        const withAttempts = {
          ...result,
          attempts: attempt,
        };
        await logDelivery({
          companyId: input.companyId,
          channelId: input.channel?.id ?? null,
          provider: input.provider,
          messageType: input.messageType,
          status: "sent",
          requestPayload: {
            channelId: input.channel?.id ?? null,
            textLength: input.text.length,
            settings: input.settings,
            attempts: attempt,
          },
          responsePayload: withAttempts.providerPayload,
        });
        return withAttempts;
      } catch (error) {
        lastError = error;
        const retryable = error instanceof DeliveryError ? error.retryable : false;
        const canRetry = retryable && attempt < RETRY_MAX_ATTEMPTS;
        if (canRetry) {
          const delayMs = toRetryDelayMs(attempt);
          logger.warn(
            {
              err: error,
              companyId: input.companyId,
              channelId: input.channel?.id ?? null,
              provider: input.provider,
              messageType: input.messageType,
              attempt,
              delayMs,
            },
            "notification delivery failed, retrying",
          );
          await wait(delayMs);
          continue;
        }

        const message = error instanceof Error ? error.message : "Notification delivery failed.";
        await logDelivery({
          companyId: input.companyId,
          channelId: input.channel?.id ?? null,
          provider: input.provider,
          messageType: input.messageType,
          status: "failed",
          requestPayload: {
            channelId: input.channel?.id ?? null,
            textLength: input.text.length,
            settings: input.settings,
            attempts: attempt,
          },
          responsePayload: null,
          errorMessage: message,
        });

        if (error instanceof DeliveryError) {
          throw unprocessable(message);
        }
        throw error;
      }
    }

    const message = lastError instanceof Error ? lastError.message : "Notification delivery failed.";
    throw unprocessable(message);
  }

  async function getChannel(companyId: string, channelId: string) {
    return db
      .select()
      .from(notificationChannels)
      .where(and(eq(notificationChannels.companyId, companyId), eq(notificationChannels.id, channelId)))
      .then((rows) => rows[0] ?? null);
  }

  return {
    formatTestMessage: buildTestMessage,
    formatAgentAlertMessage: buildAgentAlertMessage,

    sendDraftTelegramTest: async (
      companyId: string,
      config: TelegramDraftConfig,
      opts?: { message?: string },
      audit?: { actorUserId?: string | null },
    ): Promise<NotificationChannelTestResult> => {
      const message = buildTestMessage(normalizeTestMessage(opts?.message));
      const settings = { chatId: normalizeChatId(config.chatId) };
      try {
        const result = await sendThroughProvider({
          channel: null,
          companyId,
          provider: "telegram",
          token: config.botToken.trim(),
          settings,
          text: message,
          messageType: "test_message",
        });
        await logActivity(db, {
          companyId,
          actorType: "user",
          actorId: audit?.actorUserId ?? "board",
          action: "channel.test.sent",
          entityType: "notification_channel",
          entityId: "draft_telegram_channel",
          details: {
            provider: "telegram",
            status: "sent",
            attempts: result.attempts,
            messageType: "test_message",
            channelId: null,
          },
        });
        return {
          success: true,
          message: result.attempts > 1 ? `${result.message} (delivered after ${result.attempts} attempts).` : result.message,
        };
      } catch (error) {
        const reason = error instanceof Error ? error.message : "Channel test failed.";
        await logActivity(db, {
          companyId,
          actorType: "user",
          actorId: audit?.actorUserId ?? "board",
          action: "channel.test.failed",
          entityType: "notification_channel",
          entityId: "draft_telegram_channel",
          details: {
            provider: "telegram",
            status: "failed",
            messageType: "test_message",
            channelId: null,
            error: reason,
          },
        });
        throw error;
      }
    },

    sendSavedChannelTest: async (
      companyId: string,
      channelId: string,
      opts?: { message?: string },
      audit?: { actorUserId?: string | null },
    ): Promise<NotificationChannelTestResult> => {
      const channel = await getChannel(companyId, channelId);
      if (!channel) throw notFound("Channel not found");
      if (!channel.tokenSecretId) {
        const missingTokenMessage = "Channel is missing a configured bot token.";
        await updateChannelTestStatus(channel.id, "failed", missingTokenMessage);
        throw unprocessable(missingTokenMessage);
      }

      const token = await secrets.resolveSecretValue(companyId, channel.tokenSecretId, "latest");
      try {
        const result = await sendThroughProvider({
          channel,
          companyId,
          provider: channel.provider as NotificationChannelProvider,
          token,
          settings: asObject(channel.settings),
          text: buildTestMessage(normalizeTestMessage(opts?.message)),
          messageType: "test_message",
        });
        await logActivity(db, {
          companyId,
          actorType: "user",
          actorId: audit?.actorUserId ?? "board",
          action: "channel.test.sent",
          entityType: "notification_channel",
          entityId: channel.id,
          details: {
            provider: channel.provider,
            status: "sent",
            attempts: result.attempts,
            messageType: "test_message",
            channelId: channel.id,
          },
        });
        await updateChannelTestStatus(channel.id, "success", result.message);
        return {
          success: true,
          message: result.attempts > 1 ? `${result.message} (delivered after ${result.attempts} attempts).` : result.message,
        };
      } catch (error) {
        const message = error instanceof Error ? error.message : "Channel test failed.";
        await logActivity(db, {
          companyId,
          actorType: "user",
          actorId: audit?.actorUserId ?? "board",
          action: "channel.test.failed",
          entityType: "notification_channel",
          entityId: channel.id,
          details: {
            provider: channel.provider,
            status: "failed",
            messageType: "test_message",
            channelId: channel.id,
            error: message,
          },
        });
        await updateChannelTestStatus(channel.id, "failed", message);
        throw error;
      }
    },

    dispatchAgentAlert: async (
      companyId: string,
      input: AgentAlertInput,
    ): Promise<Array<{ channelId: string; status: DeliveryStatus; message: string }>> => {
      const channels = await db
        .select()
        .from(notificationChannels)
        .where(
          and(
            eq(notificationChannels.companyId, companyId),
            eq(notificationChannels.provider, "telegram"),
            eq(notificationChannels.isEnabled, true),
          ),
        );
      if (channels.length === 0) return [];

      const eligibleMappings = await db
        .select({
          channelId: notificationChannelMappings.channelId,
        })
        .from(notificationChannelMappings)
        .where(
          and(
            eq(notificationChannelMappings.companyId, companyId),
            eq(notificationChannelMappings.eventType, input.eventType),
            eq(notificationChannelMappings.severity, input.severity),
            eq(notificationChannelMappings.isEnabled, true),
          ),
        );
      const enabledChannelIds = new Set(eligibleMappings.map((row) => row.channelId));
      const eligibleChannels = channels.filter((channel) => enabledChannelIds.has(channel.id));
      if (eligibleChannels.length === 0) return [];

      const text = buildAgentAlertMessage(input);
      const deliveries: Array<{ channelId: string; status: DeliveryStatus; message: string }> = [];
      for (const channel of eligibleChannels) {
        if (!channel.tokenSecretId) {
          const message = "Channel is missing a configured bot token.";
          await logDelivery({
            companyId,
            channelId: channel.id,
            provider: channel.provider as NotificationChannelProvider,
            messageType: "agent_alert",
            status: "failed",
            requestPayload: {
              channelId: channel.id,
              textLength: text.length,
              settings: asObject(channel.settings),
            },
            errorMessage: message,
          });
          deliveries.push({ channelId: channel.id, status: "failed", message });
          continue;
        }

        try {
          const token = await secrets.resolveSecretValue(companyId, channel.tokenSecretId, "latest");
          const result = await sendThroughProvider({
            channel,
            companyId,
            provider: channel.provider as NotificationChannelProvider,
            token,
            settings: asObject(channel.settings),
            text,
            messageType: "agent_alert",
          });
          await logActivity(db, {
            companyId,
            actorType: "system",
            actorId: "notification_dispatcher",
            action: "notification.live.sent",
            entityType: "notification_channel",
            entityId: channel.id,
            details: {
              provider: channel.provider,
              messageType: "agent_alert",
              status: "sent",
              attempts: result.attempts,
              eventType: input.eventType,
              severity: input.severity,
              agentId: input.agentId,
            },
          });
          deliveries.push({ channelId: channel.id, status: "sent", message: result.message });
        } catch (error) {
          const message = error instanceof Error ? error.message : "Notification delivery failed.";
          await logActivity(db, {
            companyId,
            actorType: "system",
            actorId: "notification_dispatcher",
            action: "notification.live.failed",
            entityType: "notification_channel",
            entityId: channel.id,
            details: {
              provider: channel.provider,
              messageType: "agent_alert",
              status: "failed",
              eventType: input.eventType,
              severity: input.severity,
              agentId: input.agentId,
              error: message,
            },
          });
          logger.warn(
            { err: error, companyId, channelId: channel.id, provider: channel.provider },
            "agent alert notification delivery failed",
          );
          deliveries.push({ channelId: channel.id, status: "failed", message });
        }
      }
      return deliveries;
    },
  };
}
