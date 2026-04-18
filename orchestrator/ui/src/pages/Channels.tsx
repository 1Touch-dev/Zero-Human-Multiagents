import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, MessageCircle, Plus, Send } from "lucide-react";
import { useCompany } from "@/context/CompanyContext";
import { useBreadcrumbs } from "@/context/BreadcrumbContext";
import { useToast } from "@/context/ToastContext";
import {
  channelsApi,
  type NotificationChannel,
  type NotificationEventType,
  type NotificationSeverity,
} from "@/api/channels";
import { queryKeys } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

interface TelegramFormState {
  name: string;
  botToken: string;
  chatId: string;
  isEnabled: boolean;
}

interface TelegramFormErrors {
  name?: string;
  botToken?: string;
  chatId?: string;
}

const DEFAULT_FORM: TelegramFormState = {
  name: "",
  botToken: "",
  chatId: "",
  isEnabled: true,
};

const MAPPING_EVENT_OPTIONS: Array<{
  eventType: NotificationEventType;
  label: string;
  defaultSeverity: NotificationSeverity;
}> = [
  { eventType: "agent_failed", label: "Agent failed", defaultSeverity: "critical" },
  { eventType: "agent_timed_out", label: "Agent timed out", defaultSeverity: "warning" },
  { eventType: "agent_recovered", label: "Agent recovered", defaultSeverity: "info" },
  { eventType: "agent_succeeded", label: "Agent succeeded", defaultSeverity: "info" },
];

const SEVERITY_OPTIONS: Array<{ value: NotificationSeverity; label: string }> = [
  { value: "critical", label: "Critical" },
  { value: "warning", label: "Warning" },
  { value: "info", label: "Info" },
];

function formatRelativeTime(value: string | null): string {
  if (!value) return "Never tested";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "Unknown";
  const diffMs = Date.now() - parsed;
  const diffMinutes = Math.floor(diffMs / 60_000);
  if (diffMinutes < 1) return "Just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function validateForm(state: TelegramFormState): TelegramFormErrors {
  const errors: TelegramFormErrors = {};
  if (!state.name.trim()) {
    errors.name = "Channel name is required.";
  } else if (state.name.trim().length < 3) {
    errors.name = "Channel name must be at least 3 characters.";
  }

  if (!state.botToken.trim()) {
    errors.botToken = "Bot token is required.";
  } else if (!/^\d{5,}:[A-Za-z0-9_-]{20,}$/.test(state.botToken.trim())) {
    errors.botToken = "Enter a valid Telegram bot token.";
  }

  if (!state.chatId.trim()) {
    errors.chatId = "Chat ID is required.";
  } else if (!/^-?\d{5,}$/.test(state.chatId.trim())) {
    errors.chatId = "Enter a valid numeric Chat ID.";
  }

  return errors;
}

function FormError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="text-xs text-destructive">{message}</p>;
}

export function Channels() {
  const { selectedCompanyId, selectedCompany } = useCompany();
  const { setBreadcrumbs } = useBreadcrumbs();
  const { pushToast } = useToast();
  const queryClient = useQueryClient();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<TelegramFormState>(DEFAULT_FORM);
  const [errors, setErrors] = useState<TelegramFormErrors>({});

  useEffect(() => {
    setBreadcrumbs([
      { label: selectedCompany?.name ?? "Company", href: "/dashboard" },
      { label: "Channels" },
    ]);
  }, [selectedCompany?.name, setBreadcrumbs]);

  const channelsQuery = useQuery({
    queryKey: selectedCompanyId ? queryKeys.channels.list(selectedCompanyId) : ["channels", "none"],
    queryFn: () => channelsApi.list(selectedCompanyId!),
    enabled: Boolean(selectedCompanyId),
  });

  const resetForm = () => {
    setForm(DEFAULT_FORM);
    setErrors({});
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!selectedCompanyId) throw new Error("Select a company first.");
      return channelsApi.createTelegram(selectedCompanyId, {
        name: form.name,
        botToken: form.botToken,
        chatId: form.chatId,
        isEnabled: form.isEnabled,
      });
    },
    onSuccess: async () => {
      if (!selectedCompanyId) return;
      await queryClient.invalidateQueries({ queryKey: queryKeys.channels.list(selectedCompanyId) });
      pushToast({
        title: "Telegram channel saved",
        body: "Your Telegram channel is now available for notifications.",
        tone: "success",
      });
      setDialogOpen(false);
      resetForm();
    },
    onError: (error) => {
      pushToast({
        title: "Failed to save channel",
        body: error instanceof Error ? error.message : "Unknown error",
        tone: "error",
      });
    },
  });

  const testDraftMutation = useMutation({
    mutationFn: async () => {
      if (!selectedCompanyId) throw new Error("Select a company first.");
      return channelsApi.testTelegramConnection(selectedCompanyId, {
        botToken: form.botToken,
        chatId: form.chatId,
      });
    },
    onSuccess: ({ message }) => {
      pushToast({ title: "Connection successful", body: message, tone: "success" });
    },
    onError: (error) => {
      pushToast({
        title: "Connection test failed",
        body: error instanceof Error ? error.message : "Unable to test channel.",
        tone: "error",
      });
    },
  });

  const testSavedMutation = useMutation({
    mutationFn: async (channelId: string) => {
      if (!selectedCompanyId) throw new Error("Select a company first.");
      return channelsApi.testSavedChannel(selectedCompanyId, channelId);
    },
    onSuccess: async (channel) => {
      if (!selectedCompanyId) return;
      await queryClient.invalidateQueries({ queryKey: queryKeys.channels.list(selectedCompanyId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.channels.deliveries(selectedCompanyId, channel.id) });
      pushToast({
        title: "Test message sent",
        body: `${channel.name} delivered successfully.`,
        tone: "success",
      });
    },
    onError: async (error, channelId) => {
      if (selectedCompanyId) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.channels.list(selectedCompanyId) });
        await queryClient.invalidateQueries({ queryKey: queryKeys.channels.deliveries(selectedCompanyId, channelId) });
      }
      pushToast({
        title: "Test failed",
        body: error instanceof Error ? error.message : "Could not send test message.",
        tone: "error",
      });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: async (payload: { channelId: string; isEnabled: boolean }) => {
      if (!selectedCompanyId) throw new Error("Select a company first.");
      return channelsApi.setEnabled(selectedCompanyId, payload.channelId, payload.isEnabled);
    },
    onSuccess: async (channel) => {
      if (!selectedCompanyId) return;
      await queryClient.invalidateQueries({ queryKey: queryKeys.channels.list(selectedCompanyId) });
      pushToast({
        title: channel.isEnabled ? "Channel enabled" : "Channel disabled",
        body: `${channel.name} is now ${channel.isEnabled ? "active" : "inactive"}.`,
        tone: channel.isEnabled ? "success" : "info",
      });
    },
    onError: (error) => {
      pushToast({
        title: "Failed to update channel",
        body: error instanceof Error ? error.message : "Unknown error",
        tone: "error",
      });
    },
  });

  const sortedChannels = useMemo(() => channelsQuery.data ?? [], [channelsQuery.data]);

  const handleDraftTest = () => {
    const nextErrors = validateForm(form);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    testDraftMutation.mutate();
  };

  const handleSave = () => {
    const nextErrors = validateForm(form);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    saveMutation.mutate();
  };

  const pendingSavedTestId = testSavedMutation.isPending ? testSavedMutation.variables : null;
  const pendingToggleId = toggleMutation.isPending ? toggleMutation.variables?.channelId : null;

  if (!selectedCompanyId) {
    return <div className="text-sm text-muted-foreground">No company selected. Select a company first.</div>;
  }

  return (
    <div className="max-w-5xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Bell className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-lg font-semibold">Channels</h1>
        </div>

        <Dialog
          open={dialogOpen}
          onOpenChange={(open) => {
            setDialogOpen(open);
            if (!open) resetForm();
          }}
        >
          <DialogTrigger asChild>
            <Button className="gap-2">
              <Plus className="h-4 w-4" />
              Add Channel
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-xl">
            <DialogHeader>
              <DialogTitle>Add Telegram Channel</DialogTitle>
              <DialogDescription>
                Connect a Telegram bot to receive Paperclip notifications for this company.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="channel-name">Channel Name</Label>
                <Input
                  id="channel-name"
                  placeholder="Ops Alerts"
                  value={form.name}
                  onChange={(event) => {
                    setForm((prev) => ({ ...prev, name: event.target.value }));
                    setErrors((prev) => ({ ...prev, name: undefined }));
                  }}
                />
                <FormError message={errors.name} />
              </div>

              <div className="space-y-2">
                <Label htmlFor="bot-token">Telegram Bot Token</Label>
                <Input
                  id="bot-token"
                  type="password"
                  placeholder="123456789:AA..."
                  value={form.botToken}
                  onChange={(event) => {
                    setForm((prev) => ({ ...prev, botToken: event.target.value }));
                    setErrors((prev) => ({ ...prev, botToken: undefined }));
                  }}
                />
                <p className="text-xs text-muted-foreground">Create your bot token from Telegram BotFather.</p>
                <p className="text-xs text-muted-foreground">Tokens are stored encrypted and never returned in plaintext.</p>
                <FormError message={errors.botToken} />
              </div>

              <div className="space-y-2">
                <Label htmlFor="chat-id">Telegram Chat ID</Label>
                <Input
                  id="chat-id"
                  placeholder="-1001234567890"
                  value={form.chatId}
                  onChange={(event) => {
                    setForm((prev) => ({ ...prev, chatId: event.target.value }));
                    setErrors((prev) => ({ ...prev, chatId: undefined }));
                  }}
                />
                <p className="text-xs text-muted-foreground">Use the numeric chat id for your channel or group.</p>
                <FormError message={errors.chatId} />
              </div>

              <div className="rounded-md border border-border bg-muted/20 px-3 py-2">
                <label className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium">Enabled</p>
                    <p className="text-xs text-muted-foreground">
                      When enabled, this channel can receive notification events.
                    </p>
                  </div>
                  <button
                    type="button"
                    aria-label="Toggle channel enabled"
                    className={cn(
                      "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
                      form.isEnabled ? "bg-green-600" : "bg-muted",
                    )}
                    onClick={() => setForm((prev) => ({ ...prev, isEnabled: !prev.isEnabled }))}
                  >
                    <span
                      className={cn(
                        "inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform",
                        form.isEnabled ? "translate-x-4.5" : "translate-x-0.5",
                      )}
                    />
                  </button>
                </label>
              </div>
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={saveMutation.isPending}>
                Cancel
              </Button>
              <Button
                variant="outline"
                onClick={handleDraftTest}
                disabled={testDraftMutation.isPending || saveMutation.isPending}
              >
                {testDraftMutation.isPending ? "Testing..." : "Test Connection"}
              </Button>
              <Button onClick={handleSave} disabled={saveMutation.isPending || testDraftMutation.isPending}>
                {saveMutation.isPending ? "Saving..." : "Save Channel"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {channelsQuery.isLoading ? (
        <div className="text-sm text-muted-foreground">Loading channels...</div>
      ) : channelsQuery.error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {channelsQuery.error instanceof Error ? channelsQuery.error.message : "Failed to load channels."}
        </div>
      ) : sortedChannels.length === 0 ? (
        <Card className="bg-muted/30">
          <CardContent className="flex flex-col items-center justify-center gap-2 py-12 text-center">
            <MessageCircle className="h-10 w-10 text-muted-foreground" />
            <p className="text-sm font-medium">No channels configured yet</p>
            <p className="max-w-md text-sm text-muted-foreground">
              Add a Telegram channel to receive agent updates and incident alerts.
            </p>
          </CardContent>
        </Card>
      ) : (
        <ul className="space-y-3">
          {sortedChannels.map((channel) => (
            <li key={channel.id}>
              <ChannelCard
                companyId={selectedCompanyId}
                channel={channel}
                testing={pendingSavedTestId === channel.id}
                toggling={pendingToggleId === channel.id}
                onTest={() => testSavedMutation.mutate(channel.id)}
                onToggle={() =>
                  toggleMutation.mutate({
                    channelId: channel.id,
                    isEnabled: !channel.isEnabled,
                  })
                }
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ChannelCard({
  companyId,
  channel,
  testing,
  toggling,
  onTest,
  onToggle,
}: {
  companyId: string;
  channel: NotificationChannel;
  testing: boolean;
  toggling: boolean;
  onTest: () => void;
  onToggle: () => void;
}) {
  const { pushToast } = useToast();
  const queryClient = useQueryClient();
  const [rules, setRules] = useState<Record<NotificationEventType, { severity: NotificationSeverity; isEnabled: boolean }>>({
    agent_failed: { severity: "critical", isEnabled: true },
    agent_timed_out: { severity: "warning", isEnabled: true },
    agent_recovered: { severity: "info", isEnabled: true },
    agent_succeeded: { severity: "info", isEnabled: false },
  });

  const mappingsQuery = useQuery({
    queryKey: queryKeys.channels.mappings(companyId, channel.id),
    queryFn: () => channelsApi.listMappings(companyId, channel.id),
  });
  const deliveriesQuery = useQuery({
    queryKey: queryKeys.channels.deliveries(companyId, channel.id),
    queryFn: () => channelsApi.listRecentDeliveries(companyId, channel.id, 6),
  });

  useEffect(() => {
    if (!mappingsQuery.data) return;
    const nextRules: Record<NotificationEventType, { severity: NotificationSeverity; isEnabled: boolean }> = {
      agent_failed: { severity: "critical", isEnabled: true },
      agent_timed_out: { severity: "warning", isEnabled: true },
      agent_recovered: { severity: "info", isEnabled: true },
      agent_succeeded: { severity: "info", isEnabled: false },
    };

    for (const option of MAPPING_EVENT_OPTIONS) {
      const enabledMatch = mappingsQuery.data.find((row) => row.eventType === option.eventType && row.isEnabled);
      const fallback = mappingsQuery.data.find((row) => row.eventType === option.eventType);
      const selected = enabledMatch ?? fallback;
      if (selected) {
        nextRules[option.eventType] = {
          severity: selected.severity,
          isEnabled: selected.isEnabled,
        };
      }
    }
    setRules(nextRules);
  }, [mappingsQuery.data]);

  const saveMappingsMutation = useMutation({
    mutationFn: async () => {
      const payload = MAPPING_EVENT_OPTIONS.map((option) => ({
        eventType: option.eventType,
        severity: rules[option.eventType].severity,
        isEnabled: rules[option.eventType].isEnabled,
      }));
      return channelsApi.saveMappings(companyId, channel.id, payload);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.channels.mappings(companyId, channel.id) });
      pushToast({
        title: "Mappings saved",
        body: `${channel.name} event routing has been updated.`,
        tone: "success",
      });
    },
    onError: (error) => {
      pushToast({
        title: "Failed to save mappings",
        body: error instanceof Error ? error.message : "Unknown error",
        tone: "error",
      });
    },
  });

  const latestDelivery = deliveriesQuery.data?.[0] ?? null;
  const latestDeliveryTone =
    latestDelivery?.status === "sent"
      ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300"
      : latestDelivery?.status === "failed"
        ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300"
        : "bg-muted text-muted-foreground";
  const deliveryErrors = (deliveriesQuery.data ?? []).filter((entry) => entry.status === "failed");

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-semibold">{channel.name}</p>
            <Badge variant="outline">Telegram</Badge>
            <Badge variant={channel.isEnabled ? "default" : "secondary"} className={channel.isEnabled ? "bg-green-600 hover:bg-green-700" : ""}>
              {channel.isEnabled ? "Active" : "Disabled"}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">Bot: {channel.botTokenMasked}</p>
          <p className="text-xs text-muted-foreground">Chat ID: {channel.chatId}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={onTest} disabled={testing || toggling}>
            <Send className="h-3.5 w-3.5" />
            {testing ? "Testing..." : "Test"}
          </Button>
          <Button variant="outline" size="sm" onClick={onToggle} disabled={testing || toggling}>
            {toggling ? "Updating..." : channel.isEnabled ? "Disable" : "Enable"}
          </Button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>Last tested: {formatRelativeTime(channel.lastTestedAt)}</span>
        {channel.lastTestStatus && (
          <span
            className={cn(
              "rounded-full px-2 py-0.5",
              channel.lastTestStatus === "success"
                ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300"
                : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
            )}
          >
            {channel.lastTestStatus === "success" ? "Last test passed" : "Last test failed"}
          </span>
        )}
        {channel.lastTestMessage && <span className="truncate">{channel.lastTestMessage}</span>}
      </div>

      <div className="mt-3 rounded-md border border-border/70 bg-background/80 p-3">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-medium text-muted-foreground">Delivery status</span>
          {deliveriesQuery.isLoading ? (
            <span className="text-muted-foreground">Loading recent deliveries...</span>
          ) : deliveriesQuery.error ? (
            <span className="text-destructive">Could not load delivery history.</span>
          ) : latestDelivery ? (
            <>
              <span className={cn("rounded-full px-2 py-0.5", latestDeliveryTone)}>
                {latestDelivery.status === "sent" ? "Last delivery succeeded" : "Last delivery failed"}
              </span>
              <span className="text-muted-foreground">{formatRelativeTime(latestDelivery.createdAt)}</span>
              <span className="text-muted-foreground">
                Type: {latestDelivery.messageType === "agent_alert" ? "Live alert" : "Test"}
              </span>
            </>
          ) : (
            <span className="text-muted-foreground">No delivery events yet.</span>
          )}
        </div>
        {deliveryErrors.length > 0 && (
          <p className="mt-2 truncate text-xs text-destructive">
            Recent error: {deliveryErrors[0].errorMessage ?? "Unknown delivery error"}
          </p>
        )}
      </div>

      <div className="mt-4 rounded-md border border-border bg-muted/20 p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Agent Update Mappings</p>
          <Button
            size="sm"
            variant="outline"
            onClick={() => saveMappingsMutation.mutate()}
            disabled={saveMappingsMutation.isPending || mappingsQuery.isLoading}
          >
            {saveMappingsMutation.isPending ? "Saving..." : "Save Mappings"}
          </Button>
        </div>
        {mappingsQuery.isLoading ? (
          <p className="text-xs text-muted-foreground">Loading mapping rules...</p>
        ) : mappingsQuery.error ? (
          <p className="text-xs text-destructive">Failed to load mapping rules. Refresh and try again.</p>
        ) : (
          <div className="space-y-2">
            {MAPPING_EVENT_OPTIONS.map((option) => (
              <div key={option.eventType} className="grid gap-2 rounded-md border border-border/60 bg-background/70 p-2 md:grid-cols-[1fr_140px_120px] md:items-center">
                <p className="text-sm">{option.label}</p>
                <Select
                  value={rules[option.eventType].severity}
                  onValueChange={(value) =>
                    setRules((prev) => ({
                      ...prev,
                      [option.eventType]: {
                        ...prev[option.eventType],
                        severity: value as NotificationSeverity,
                      },
                    }))
                  }
                >
                  <SelectTrigger size="sm" className="w-full">
                    <SelectValue placeholder="Select severity" />
                  </SelectTrigger>
                  <SelectContent>
                    {SEVERITY_OPTIONS.map((severity) => (
                      <SelectItem key={severity.value} value={severity.value}>
                        {severity.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <label className="inline-flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={rules[option.eventType].isEnabled}
                    onCheckedChange={(checked) =>
                      setRules((prev) => ({
                        ...prev,
                        [option.eventType]: {
                          ...prev[option.eventType],
                          isEnabled: checked === true,
                        },
                      }))
                    }
                  />
                  Enabled
                </label>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
