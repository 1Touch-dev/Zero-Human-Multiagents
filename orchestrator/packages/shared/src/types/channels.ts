import type {
  NotificationChannelProvider,
  NotificationChannelTestStatus,
  NotificationEventType,
  NotificationSeverity,
} from "../constants.js";

export interface TelegramChannelSettings {
  chatId: string;
}

export type NotificationChannelSettings = TelegramChannelSettings | Record<string, unknown>;

export interface NotificationChannel {
  id: string;
  companyId: string;
  name: string;
  provider: NotificationChannelProvider;
  isEnabled: boolean;
  settings: NotificationChannelSettings;
  hasToken: boolean;
  tokenMasked: string | null;
  lastTestedAt: Date | null;
  lastTestStatus: NotificationChannelTestStatus | null;
  lastTestMessage: string | null;
  createdAt: Date;
  updatedAt: Date;
}

export interface NotificationChannelTestResult {
  success: boolean;
  message: string;
}

export interface NotificationDeliveryLog {
  id: string;
  companyId: string;
  channelId: string | null;
  provider: NotificationChannelProvider;
  messageType: "test_message" | "agent_alert";
  status: "sent" | "failed";
  requestPayload: Record<string, unknown>;
  responsePayload: Record<string, unknown> | null;
  errorMessage: string | null;
  createdAt: Date;
}

export interface NotificationChannelMapping {
  id: string;
  companyId: string;
  channelId: string;
  eventType: NotificationEventType;
  severity: NotificationSeverity;
  isEnabled: boolean;
  createdAt: Date;
  updatedAt: Date;
}
