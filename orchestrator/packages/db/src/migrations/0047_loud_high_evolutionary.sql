CREATE TABLE IF NOT EXISTS "company_llm_settings" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"company_id" uuid NOT NULL,
	"settings_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"api_key_material" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"encryption_provider" text DEFAULT 'local_encrypted' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "company_llm_settings" ADD CONSTRAINT "company_llm_settings_company_id_companies_id_fk" FOREIGN KEY ("company_id") REFERENCES "public"."companies"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "company_llm_settings_company_idx" ON "company_llm_settings" USING btree ("company_id");
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "company_llm_settings_company_uq" ON "company_llm_settings" USING btree ("company_id");
--> statement-breakpoint
INSERT INTO "company_llm_settings" ("company_id", "settings_json", "api_key_material", "encryption_provider")
SELECT
  c."id",
  '{
    "llm": {
      "default_provider": "vllm_openai_compatible",
      "default_model": "meta-llama/Meta-Llama-3.1-8B-Instruct",
      "providers": {
        "vllm_openai_compatible": {
          "base_url": "http://vllm:8000/v1",
          "enabled": true
        }
      },
      "role_models": {}
    }
  }'::jsonb,
  '{}'::jsonb,
  'local_encrypted'
FROM "companies" c
ON CONFLICT ("company_id") DO NOTHING;

