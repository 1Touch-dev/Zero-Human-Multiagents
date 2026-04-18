CREATE TABLE IF NOT EXISTS "notification_channels" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"company_id" uuid NOT NULL,
	"name" text NOT NULL,
	"provider" text NOT NULL,
	"is_enabled" boolean DEFAULT true NOT NULL,
	"settings" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"token_secret_id" uuid,
	"last_tested_at" timestamp with time zone,
	"last_test_status" text,
	"last_test_message" text,
	"created_by_user_id" text,
	"updated_by_user_id" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "notification_channels" ADD CONSTRAINT "notification_channels_company_id_companies_id_fk" FOREIGN KEY ("company_id") REFERENCES "public"."companies"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "notification_channels" ADD CONSTRAINT "notification_channels_token_secret_id_company_secrets_id_fk" FOREIGN KEY ("token_secret_id") REFERENCES "public"."company_secrets"("id") ON DELETE set null ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "notification_channels_company_idx" ON "notification_channels" USING btree ("company_id");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "notification_channels_company_provider_idx" ON "notification_channels" USING btree ("company_id","provider");
