CREATE TABLE IF NOT EXISTS "notification_delivery_logs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"company_id" uuid NOT NULL,
	"channel_id" uuid,
	"provider" text NOT NULL,
	"message_type" text NOT NULL,
	"status" text NOT NULL,
	"request_payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"response_payload" jsonb DEFAULT '{}'::jsonb,
	"error_message" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "notification_delivery_logs" ADD CONSTRAINT "notification_delivery_logs_company_id_companies_id_fk" FOREIGN KEY ("company_id") REFERENCES "public"."companies"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "notification_delivery_logs" ADD CONSTRAINT "notification_delivery_logs_channel_id_notification_channels_id_fk" FOREIGN KEY ("channel_id") REFERENCES "public"."notification_channels"("id") ON DELETE set null ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "notification_delivery_logs_company_idx" ON "notification_delivery_logs" USING btree ("company_id");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "notification_delivery_logs_channel_idx" ON "notification_delivery_logs" USING btree ("channel_id");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "notification_delivery_logs_provider_idx" ON "notification_delivery_logs" USING btree ("provider");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "notification_delivery_logs_status_idx" ON "notification_delivery_logs" USING btree ("status");
