import {
  boolean,
  index,
  jsonb,
  pgTable,
  text,
  timestamp,
  uuid,
} from "drizzle-orm/pg-core";
import { companies } from "./companies.js";
import { companySecrets } from "./company_secrets.js";

export const notificationChannels = pgTable(
  "notification_channels",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    companyId: uuid("company_id").notNull().references(() => companies.id, { onDelete: "cascade" }),
    name: text("name").notNull(),
    provider: text("provider").notNull(),
    isEnabled: boolean("is_enabled").notNull().default(true),
    settings: jsonb("settings").$type<Record<string, unknown>>().notNull().default({}),
    tokenSecretId: uuid("token_secret_id").references(() => companySecrets.id, { onDelete: "set null" }),
    lastTestedAt: timestamp("last_tested_at", { withTimezone: true }),
    lastTestStatus: text("last_test_status"),
    lastTestMessage: text("last_test_message"),
    createdByUserId: text("created_by_user_id"),
    updatedByUserId: text("updated_by_user_id"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    companyIdx: index("notification_channels_company_idx").on(table.companyId),
    companyProviderIdx: index("notification_channels_company_provider_idx").on(table.companyId, table.provider),
  }),
);
