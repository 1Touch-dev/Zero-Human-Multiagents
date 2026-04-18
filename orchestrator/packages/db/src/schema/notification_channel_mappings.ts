import {
  boolean,
  index,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";
import { companies } from "./companies.js";
import { notificationChannels } from "./notification_channels.js";

export const notificationChannelMappings = pgTable(
  "notification_channel_mappings",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    companyId: uuid("company_id").notNull().references(() => companies.id, { onDelete: "cascade" }),
    channelId: uuid("channel_id").notNull().references(() => notificationChannels.id, { onDelete: "cascade" }),
    eventType: text("event_type").notNull(),
    severity: text("severity").notNull(),
    isEnabled: boolean("is_enabled").notNull().default(true),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    companyIdx: index("notification_channel_mappings_company_idx").on(table.companyId),
    channelIdx: index("notification_channel_mappings_channel_idx").on(table.channelId),
    eventIdx: index("notification_channel_mappings_event_idx").on(table.eventType, table.severity),
    uniqueRuleIdx: uniqueIndex("notification_channel_mappings_unique_rule_idx").on(
      table.channelId,
      table.eventType,
      table.severity,
    ),
  }),
);
