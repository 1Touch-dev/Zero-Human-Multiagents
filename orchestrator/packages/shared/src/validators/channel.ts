import { z } from "zod";
import { NOTIFICATION_EVENT_TYPES, NOTIFICATION_SEVERITIES } from "../constants.js";

const botTokenSchema = z.string().trim().min(1).regex(/^\d{5,}:[A-Za-z0-9_-]{20,}$/, {
  message: "Telegram bot token format is invalid.",
});

const chatIdSchema = z.string().trim().min(1).regex(/^-?\d{5,}$/, {
  message: "Telegram chat ID format is invalid.",
});

export const telegramChannelConfigSchema = z.object({
  chatId: chatIdSchema,
  botToken: botTokenSchema,
});

export const createNotificationChannelSchema = z.object({
  name: z.string().trim().min(1).max(120),
  provider: z.literal("telegram"),
  isEnabled: z.boolean().optional(),
  config: z.object({
    provider: z.literal("telegram"),
    chatId: chatIdSchema,
    botToken: botTokenSchema,
  }),
});

export type CreateNotificationChannel = z.infer<typeof createNotificationChannelSchema>;

export const updateNotificationChannelSchema = z.object({
  name: z.string().trim().min(1).max(120).optional(),
  isEnabled: z.boolean().optional(),
  config: z.object({
    provider: z.literal("telegram"),
    chatId: chatIdSchema.optional(),
    botToken: botTokenSchema.optional(),
  }).optional(),
});

export type UpdateNotificationChannel = z.infer<typeof updateNotificationChannelSchema>;

export const testNotificationChannelSchema = z.object({
  message: z.string().trim().min(1).max(512).optional(),
});

export type TestNotificationChannel = z.infer<typeof testNotificationChannelSchema>;

export const testDraftNotificationChannelSchema = z.object({
  provider: z.literal("telegram"),
  config: z.object({
    chatId: chatIdSchema,
    botToken: botTokenSchema,
  }),
  message: z.string().trim().min(1).max(512).optional(),
});

export type TestDraftNotificationChannel = z.infer<typeof testDraftNotificationChannelSchema>;

export const notificationChannelMappingSchema = z.object({
  eventType: z.enum(NOTIFICATION_EVENT_TYPES),
  severity: z.enum(NOTIFICATION_SEVERITIES),
  isEnabled: z.boolean(),
});

export const saveNotificationChannelMappingsSchema = z.object({
  mappings: z.array(notificationChannelMappingSchema).max(64),
});

export type SaveNotificationChannelMappings = z.infer<typeof saveNotificationChannelMappingsSchema>;
