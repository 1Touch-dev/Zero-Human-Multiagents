import {
  index,
  jsonb,
  pgTable,
  text,
  timestamp,
  uuid,
} from "drizzle-orm/pg-core";
import { companies } from "./companies.js";
import { notificationChannels } from "./notification_channels.js";

export const notificationDeliveryLogs = pgTable(
  "notification_delivery_logs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    companyId: uuid("company_id").notNull().references(() => companies.id, { onDelete: "cascade" }),
    channelId: uuid("channel_id").references(() => notificationChannels.id, { onDelete: "set null" }),
    provider: text("provider").notNull(),
    messageType: text("message_type").notNull(),
    status: text("status").notNull(),
    requestPayload: jsonb("request_payload").$type<Record<string, unknown>>().notNull().default({}),
    responsePayload: jsonb("response_payload").$type<Record<string, unknown>>().default({}),
    errorMessage: text("error_message"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    companyIdx: index("notification_delivery_logs_company_idx").on(table.companyId),
    channelIdx: index("notification_delivery_logs_channel_idx").on(table.channelId),
    providerIdx: index("notification_delivery_logs_provider_idx").on(table.provider),
    statusIdx: index("notification_delivery_logs_status_idx").on(table.status),
  }),
);
