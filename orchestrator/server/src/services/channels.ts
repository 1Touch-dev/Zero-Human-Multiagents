import { randomUUID } from "node:crypto";
import { and, desc, eq } from "drizzle-orm";
import type { Db } from "@paperclipai/db";
import { notificationChannelMappings, notificationChannels, notificationDeliveryLogs } from "@paperclipai/db";
import type {
  CreateNotificationChannel,
  NotificationChannel,
  NotificationDeliveryLog,
  NotificationChannelMapping,
  NotificationChannelProvider,
  NotificationEventType,
  NotificationSeverity,
  NotificationChannelTestResult,
  SaveNotificationChannelMappings,
  TestDraftNotificationChannel,
  UpdateNotificationChannel,
} from "@paperclipai/shared";
import { conflict, notFound, unprocessable } from "../errors.js";
import { secretService } from "./secrets.js";
import { notificationService } from "./notifications.js";

type ChannelRow = typeof notificationChannels.$inferSelect;
type ChannelMappingRow = typeof notificationChannelMappings.$inferSelect;

function asObject(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function normalizeName(name: string) {
  return name.trim();
}

function normalizeChatId(chatId: string) {
  return chatId.trim();
}

function toNotificationChannel(row: ChannelRow): NotificationChannel {
  const hasToken = Boolean(row.tokenSecretId);
  return {
    id: row.id,
    companyId: row.companyId,
    name: row.name,
    provider: row.provider as NotificationChannelProvider,
    isEnabled: row.isEnabled,
    settings: asObject(row.settings),
    hasToken,
    tokenMasked: hasToken ? "********" : null,
    lastTestedAt: row.lastTestedAt,
    lastTestStatus:
      row.lastTestStatus === "success" || row.lastTestStatus === "failed"
        ? row.lastTestStatus
        : null,
    lastTestMessage: row.lastTestMessage ?? null,
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
  };
}

function toNotificationChannelMapping(row: ChannelMappingRow): NotificationChannelMapping {
  return {
    id: row.id,
    companyId: row.companyId,
    channelId: row.channelId,
    eventType: row.eventType as NotificationEventType,
    severity: row.severity as NotificationSeverity,
    isEnabled: row.isEnabled,
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
  };
}

function toNotificationDeliveryLog(row: typeof notificationDeliveryLogs.$inferSelect): NotificationDeliveryLog {
  return {
    id: row.id,
    companyId: row.companyId,
    channelId: row.channelId,
    provider: row.provider as NotificationChannelProvider,
    messageType: row.messageType as "test_message" | "agent_alert",
    status: row.status as "sent" | "failed",
    requestPayload: asObject(row.requestPayload),
    responsePayload: row.responsePayload ? asObject(row.responsePayload) : null,
    errorMessage: row.errorMessage ?? null,
    createdAt: row.createdAt,
  };
}

const DEFAULT_CHANNEL_MAPPINGS: Array<{
  eventType: NotificationEventType;
  severity: NotificationSeverity;
  isEnabled: boolean;
}> = [
  { eventType: "agent_failed", severity: "critical", isEnabled: true },
  { eventType: "agent_timed_out", severity: "warning", isEnabled: true },
  { eventType: "agent_recovered", severity: "info", isEnabled: true },
  { eventType: "agent_succeeded", severity: "info", isEnabled: false },
];

export function channelService(db: Db) {
  const secrets = secretService(db);
  const notifications = notificationService(db);

  async function getRowById(companyId: string, channelId: string) {
    return db
      .select()
      .from(notificationChannels)
      .where(and(eq(notificationChannels.id, channelId), eq(notificationChannels.companyId, companyId)))
      .then((rows) => rows[0] ?? null);
  }

  async function assertUniqueName(companyId: string, name: string, excludeChannelId?: string) {
    const existing = await db
      .select()
      .from(notificationChannels)
      .where(eq(notificationChannels.companyId, companyId));
    const duplicate = existing.find((row) => {
      if (excludeChannelId && row.id === excludeChannelId) return false;
      return row.name.trim().toLowerCase() === name.trim().toLowerCase();
    });
    if (duplicate) {
      throw conflict(`A channel named "${name}" already exists.`);
    }
  }

  async function createDefaultMappings(companyId: string, channelId: string) {
    const now = new Date();
    await db.insert(notificationChannelMappings).values(
      DEFAULT_CHANNEL_MAPPINGS.map((mapping) => ({
        id: randomUUID(),
        companyId,
        channelId,
        eventType: mapping.eventType,
        severity: mapping.severity,
        isEnabled: mapping.isEnabled,
        createdAt: now,
        updatedAt: now,
      })),
    );
  }

  return {
    list: async (companyId: string): Promise<NotificationChannel[]> => {
      const rows = await db
        .select()
        .from(notificationChannels)
        .where(eq(notificationChannels.companyId, companyId))
        .orderBy(desc(notificationChannels.updatedAt));
      return rows.map(toNotificationChannel);
    },

    getById: async (companyId: string, channelId: string): Promise<NotificationChannel | null> => {
      const row = await getRowById(companyId, channelId);
      return row ? toNotificationChannel(row) : null;
    },

    create: async (
      companyId: string,
      input: CreateNotificationChannel,
      actor: { userId?: string | null },
    ): Promise<NotificationChannel> => {
      const name = normalizeName(input.name);
      await assertUniqueName(companyId, name);
      const channelId = randomUUID();
      const now = new Date();

      let tokenSecretId: string | null = null;
      let settings: Record<string, unknown> = {};

      if (input.config.provider === "telegram") {
        const createdSecret = await secrets.create(
          companyId,
          {
            name: `notification_channel_${channelId}_telegram_bot_token`,
            provider: "local_encrypted",
            value: input.config.botToken.trim(),
            description: `Encrypted Telegram bot token for channel ${name}`,
          },
          { userId: actor.userId ?? null, agentId: null },
        );
        tokenSecretId = createdSecret.id;
        settings = { chatId: normalizeChatId(input.config.chatId) };
      }

      const inserted = await db
        .insert(notificationChannels)
        .values({
          id: channelId,
          companyId,
          name,
          provider: input.provider,
          isEnabled: input.isEnabled ?? true,
          settings,
          tokenSecretId,
          createdByUserId: actor.userId ?? null,
          updatedByUserId: actor.userId ?? null,
          createdAt: now,
          updatedAt: now,
        })
        .returning()
        .then((rows) => rows[0] ?? null);

      if (!inserted) {
        throw unprocessable("Failed to create notification channel.");
      }
      await createDefaultMappings(companyId, inserted.id);
      return toNotificationChannel(inserted);
    },

    update: async (
      companyId: string,
      channelId: string,
      patch: UpdateNotificationChannel,
      actor: { userId?: string | null },
    ): Promise<NotificationChannel> => {
      const existing = await getRowById(companyId, channelId);
      if (!existing) throw notFound("Channel not found");

      const nextName = patch.name ? normalizeName(patch.name) : existing.name;
      if (nextName !== existing.name) {
        await assertUniqueName(companyId, nextName, existing.id);
      }

      let nextTokenSecretId = existing.tokenSecretId;
      let nextSettings = asObject(existing.settings);
      const nextEnabled = patch.isEnabled ?? existing.isEnabled;

      if (patch.config?.provider && patch.config.provider !== existing.provider) {
        throw unprocessable("Changing channel provider is not supported.");
      }

      if (patch.config?.provider === "telegram") {
        if (patch.config.chatId) {
          nextSettings = {
            ...nextSettings,
            chatId: normalizeChatId(patch.config.chatId),
          };
        }
        if (patch.config.botToken) {
          if (nextTokenSecretId) {
            await secrets.rotate(
              nextTokenSecretId,
              { value: patch.config.botToken.trim() },
              { userId: actor.userId ?? null, agentId: null },
            );
          } else {
            const createdSecret = await secrets.create(
              companyId,
              {
                name: `notification_channel_${existing.id}_telegram_bot_token`,
                provider: "local_encrypted",
                value: patch.config.botToken.trim(),
                description: `Encrypted Telegram bot token for channel ${nextName}`,
              },
              { userId: actor.userId ?? null, agentId: null },
            );
            nextTokenSecretId = createdSecret.id;
          }
        }
      }

      const updated = await db
        .update(notificationChannels)
        .set({
          name: nextName,
          isEnabled: nextEnabled,
          settings: nextSettings,
          tokenSecretId: nextTokenSecretId,
          updatedByUserId: actor.userId ?? null,
          updatedAt: new Date(),
        })
        .where(eq(notificationChannels.id, existing.id))
        .returning()
        .then((rows) => rows[0] ?? null);

      if (!updated) throw notFound("Channel not found");
      return toNotificationChannel(updated);
    },

    remove: async (companyId: string, channelId: string): Promise<NotificationChannel | null> => {
      const existing = await getRowById(companyId, channelId);
      if (!existing) return null;

      const removed = await db
        .delete(notificationChannels)
        .where(eq(notificationChannels.id, existing.id))
        .returning()
        .then((rows) => rows[0] ?? null);

      if (existing.tokenSecretId) {
        await secrets.remove(existing.tokenSecretId).catch(() => null);
      }

      return removed ? toNotificationChannel(removed) : null;
    },

    setEnabled: async (companyId: string, channelId: string, isEnabled: boolean): Promise<NotificationChannel> => {
      const existing = await getRowById(companyId, channelId);
      if (!existing) throw notFound("Channel not found");
      const updated = await db
        .update(notificationChannels)
        .set({
          isEnabled,
          updatedAt: new Date(),
        })
        .where(eq(notificationChannels.id, existing.id))
        .returning()
        .then((rows) => rows[0] ?? null);

      if (!updated) throw notFound("Channel not found");
      return toNotificationChannel(updated);
    },

    testDraft: async (
      companyId: string,
      input: TestDraftNotificationChannel,
      actor?: { userId?: string | null },
    ): Promise<NotificationChannelTestResult> => {
      if (input.provider === "telegram") {
        return notifications.sendDraftTelegramTest(
          companyId,
          { botToken: input.config.botToken, chatId: input.config.chatId },
          { message: input.message },
          { actorUserId: actor?.userId ?? null },
        );
      }
      if (input.provider === "slack") {
        throw unprocessable("Slack provider is not implemented yet.");
      }
      if (input.provider === "whatsapp") {
        throw unprocessable("WhatsApp provider is not implemented yet.");
      }
      throw unprocessable(`Provider "${input.provider}" is not supported.`);
    },

    testSaved: async (
      companyId: string,
      channelId: string,
      opts?: { message?: string },
      actor?: { userId?: string | null },
    ): Promise<NotificationChannelTestResult> => {
      return notifications.sendSavedChannelTest(companyId, channelId, opts, { actorUserId: actor?.userId ?? null });
    },

    listMappings: async (companyId: string, channelId: string): Promise<NotificationChannelMapping[]> => {
      const existing = await getRowById(companyId, channelId);
      if (!existing) throw notFound("Channel not found");
      const rows = await db
        .select()
        .from(notificationChannelMappings)
        .where(
          and(
            eq(notificationChannelMappings.companyId, companyId),
            eq(notificationChannelMappings.channelId, channelId),
          ),
        );
      return rows.map(toNotificationChannelMapping);
    },

    saveMappings: async (
      companyId: string,
      channelId: string,
      input: SaveNotificationChannelMappings,
    ): Promise<NotificationChannelMapping[]> => {
      const existing = await getRowById(companyId, channelId);
      if (!existing) throw notFound("Channel not found");

      const uniqueByRule = new Map<string, SaveNotificationChannelMappings["mappings"][number]>();
      for (const mapping of input.mappings) {
        uniqueByRule.set(`${mapping.eventType}:${mapping.severity}`, mapping);
      }

      await db
        .delete(notificationChannelMappings)
        .where(
          and(
            eq(notificationChannelMappings.companyId, companyId),
            eq(notificationChannelMappings.channelId, channelId),
          ),
        );

      const now = new Date();
      const nextRows = [...uniqueByRule.values()];
      if (nextRows.length > 0) {
        await db.insert(notificationChannelMappings).values(
          nextRows.map((mapping) => ({
            id: randomUUID(),
            companyId,
            channelId,
            eventType: mapping.eventType,
            severity: mapping.severity,
            isEnabled: mapping.isEnabled,
            createdAt: now,
            updatedAt: now,
          })),
        );
      }

      return db
        .select()
        .from(notificationChannelMappings)
        .where(
          and(
            eq(notificationChannelMappings.companyId, companyId),
            eq(notificationChannelMappings.channelId, channelId),
          ),
        )
        .then((rows) => rows.map(toNotificationChannelMapping));
    },

    listRecentDeliveries: async (
      companyId: string,
      channelId: string,
      limit = 8,
    ): Promise<NotificationDeliveryLog[]> => {
      const existing = await getRowById(companyId, channelId);
      if (!existing) throw notFound("Channel not found");
      const safeLimit = Number.isFinite(limit) ? Math.min(Math.max(Math.floor(limit), 1), 50) : 8;
      const rows = await db
        .select()
        .from(notificationDeliveryLogs)
        .where(
          and(
            eq(notificationDeliveryLogs.companyId, companyId),
            eq(notificationDeliveryLogs.channelId, channelId),
          ),
        )
        .orderBy(desc(notificationDeliveryLogs.createdAt))
        .limit(safeLimit);
      return rows.map(toNotificationDeliveryLog);
    },
  };
}
