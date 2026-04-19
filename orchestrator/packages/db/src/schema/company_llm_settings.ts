import { pgTable, uuid, timestamp, jsonb, index, uniqueIndex, text } from "drizzle-orm/pg-core";
import { companies } from "./companies.js";

export const companyLlmSettings = pgTable(
  "company_llm_settings",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    companyId: uuid("company_id")
      .notNull()
      .references(() => companies.id, { onDelete: "cascade" }),
    /**
     * Stores validated company-level LLM settings (provider/model/role routing).
     * API keys are never stored here in plain text.
     */
    settingsJson: jsonb("settings_json").$type<Record<string, unknown>>().notNull().default({}),
    /**
     * Encrypted key material grouped by provider.
     * Decryption is handled by the secrets provider layer in the server package.
     */
    apiKeyMaterial: jsonb("api_key_material").$type<Record<string, unknown>>().notNull().default({}),
    encryptionProvider: text("encryption_provider").notNull().default("local_encrypted"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    companyIdx: index("company_llm_settings_company_idx").on(table.companyId),
    companyUq: uniqueIndex("company_llm_settings_company_uq").on(table.companyId),
  }),
);

