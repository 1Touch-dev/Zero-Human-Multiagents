import { api } from "./client";

export type ChannelProvider = "telegram";
export type NotificationEventType = "agent_failed" | "agent_timed_out" | "agent_recovered" | "agent_succeeded";
export type NotificationSeverity = "critical" | "warning" | "info";

export interface NotificationChannel {
  id: string;
  companyId: string;
  provider: ChannelProvider;
  name: string;
  botTokenMasked: string;
  chatId: string;
  isEnabled: boolean;
  createdAt: string;
  updatedAt: string;
  lastTestedAt: string | null;
  lastTestStatus: "success" | "error" | null;
  lastTestMessage: string | null;
}

export interface NotificationChannelMapping {
  id: string;
  companyId: string;
  channelId: string;
  eventType: NotificationEventType;
  severity: NotificationSeverity;
  isEnabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface NotificationDeliveryLog {
  id: string;
  companyId: string;
  channelId: string | null;
  provider: ChannelProvider;
  messageType: "test_message" | "agent_alert";
  status: "sent" | "failed";
  errorMessage: string | null;
  createdAt: string;
}

export interface TelegramChannelInput {
  name: string;
  botToken: string;
  chatId: string;
  isEnabled: boolean;
}

interface RawNotificationChannel {
  id: string;
  companyId: string;
  provider: string;
  name: string;
  isEnabled: boolean;
  settings: Record<string, unknown>;
  tokenMasked: string | null;
  lastTestedAt: string | null;
  lastTestStatus: "success" | "failed" | null;
  lastTestMessage: string | null;
  createdAt: string;
  updatedAt: string;
}

interface TestResponse {
  success: boolean;
  message: string;
}

interface RawNotificationChannelMapping {
  id: string;
  companyId: string;
  channelId: string;
  eventType: NotificationEventType;
  severity: NotificationSeverity;
  isEnabled: boolean;
  createdAt: string;
  updatedAt: string;
}

interface RawNotificationDeliveryLog {
  id: string;
  companyId: string;
  channelId: string | null;
  provider: string;
  messageType: "test_message" | "agent_alert";
  status: "sent" | "failed";
  errorMessage: string | null;
  createdAt: string;
}

function toNotificationChannel(raw: RawNotificationChannel): NotificationChannel {
  const settings = raw.settings ?? {};
  const chatId = typeof settings.chatId === "string" ? settings.chatId : "";
  return {
    id: raw.id,
    companyId: raw.companyId,
    provider: "telegram",
    name: raw.name,
    botTokenMasked: raw.tokenMasked ?? "Not configured",
    chatId,
    isEnabled: raw.isEnabled,
    createdAt: raw.createdAt,
    updatedAt: raw.updatedAt,
    lastTestedAt: raw.lastTestedAt,
    lastTestStatus: raw.lastTestStatus === "failed" ? "error" : raw.lastTestStatus,
    lastTestMessage: raw.lastTestMessage,
  };
}

export const channelsApi = {
  async list(companyId: string): Promise<NotificationChannel[]> {
    const rows = await api.get<RawNotificationChannel[]>(`/companies/${companyId}/channels`);
    return rows.map(toNotificationChannel);
  },

  async createTelegram(companyId: string, input: TelegramChannelInput): Promise<NotificationChannel> {
    const created = await api.post<RawNotificationChannel>(`/companies/${companyId}/channels`, {
      name: input.name,
      provider: "telegram",
      isEnabled: input.isEnabled,
      config: {
        provider: "telegram",
        chatId: input.chatId,
        botToken: input.botToken,
      },
    });
    return toNotificationChannel(created);
  },

  async setEnabled(companyId: string, channelId: string, isEnabled: boolean): Promise<NotificationChannel> {
    const updated = await api.post<RawNotificationChannel>(
      `/companies/${companyId}/channels/${channelId}/${isEnabled ? "enable" : "disable"}`,
      {},
    );
    return toNotificationChannel(updated);
  },

  async testTelegramConnection(
    companyId: string,
    input: { botToken: string; chatId: string },
  ): Promise<TestResponse> {
    return api.post<TestResponse>(`/companies/${companyId}/channels/test`, {
      provider: "telegram",
      config: {
        chatId: input.chatId,
        botToken: input.botToken,
      },
    });
  },

  async testSavedChannel(companyId: string, channelId: string): Promise<NotificationChannel> {
    await api.post<TestResponse>(`/companies/${companyId}/channels/${channelId}/test`, {});
    const latest = await api.get<RawNotificationChannel>(`/companies/${companyId}/channels/${channelId}`);
    return toNotificationChannel(latest);
  },

  async listMappings(companyId: string, channelId: string): Promise<NotificationChannelMapping[]> {
    return api.get<RawNotificationChannelMapping[]>(`/companies/${companyId}/channels/${channelId}/mappings`);
  },

  async saveMappings(
    companyId: string,
    channelId: string,
    mappings: Array<{
      eventType: NotificationEventType;
      severity: NotificationSeverity;
      isEnabled: boolean;
    }>,
  ): Promise<NotificationChannelMapping[]> {
    return api.put<RawNotificationChannelMapping[]>(`/companies/${companyId}/channels/${channelId}/mappings`, {
      mappings,
    });
  },

  async listRecentDeliveries(companyId: string, channelId: string, limit = 8): Promise<NotificationDeliveryLog[]> {
    return api.get<RawNotificationDeliveryLog[]>(
      `/companies/${companyId}/channels/${channelId}/deliveries?limit=${encodeURIComponent(String(limit))}`,
    ).then((rows) =>
      rows.map((row) => ({
        id: row.id,
        companyId: row.companyId,
        channelId: row.channelId,
        provider: "telegram",
        messageType: row.messageType,
        status: row.status,
        errorMessage: row.errorMessage,
        createdAt: row.createdAt,
      })),
    );
  },
};
