CREATE TABLE IF NOT EXISTS "notification_channel_mappings" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"company_id" uuid NOT NULL,
	"channel_id" uuid NOT NULL,
	"event_type" text NOT NULL,
	"severity" text NOT NULL,
	"is_enabled" boolean DEFAULT true NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "notification_channel_mappings" ADD CONSTRAINT "notification_channel_mappings_company_id_companies_id_fk" FOREIGN KEY ("company_id") REFERENCES "public"."companies"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "notification_channel_mappings" ADD CONSTRAINT "notification_channel_mappings_channel_id_notification_channels_id_fk" FOREIGN KEY ("channel_id") REFERENCES "public"."notification_channels"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "notification_channel_mappings_company_idx" ON "notification_channel_mappings" USING btree ("company_id");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "notification_channel_mappings_channel_idx" ON "notification_channel_mappings" USING btree ("channel_id");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "notification_channel_mappings_event_idx" ON "notification_channel_mappings" USING btree ("event_type","severity");
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "notification_channel_mappings_unique_rule_idx" ON "notification_channel_mappings" USING btree ("channel_id","event_type","severity");
