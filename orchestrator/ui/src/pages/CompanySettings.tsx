import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CompanySecret, EnvBinding } from "@paperclipai/shared";
import { useCompany } from "../context/CompanyContext";
import { useBreadcrumbs } from "../context/BreadcrumbContext";
import { useToast } from "../context/ToastContext";
import { companiesApi } from "../api/companies";
import { accessApi } from "../api/access";
import { assetsApi } from "../api/assets";
import { agentsApi } from "../api/agents";
import { secretsApi } from "../api/secrets";
import { queryKeys } from "../lib/queryKeys";
import { Button } from "@/components/ui/button";
import { Settings, Check, Download, Upload } from "lucide-react";
import { CompanyPatternIcon } from "../components/CompanyPatternIcon";
import {
  Field,
  ToggleField,
  HintIcon
} from "../components/agent-config-primitives";

type AgentSnippetInput = {
  onboardingTextUrl: string;
  connectionCandidates?: string[] | null;
  testResolutionUrl?: string | null;
};

const SIMPLE_ENV_FIELDS = [
  {
    key: "OPENAI_API_KEY",
    label: "OpenAI API Key",
    hint: "Your OpenAI API key (starts with sk-). Used by all AI agents.",
    placeholder: "sk-proj-...",
    sensitive: true,
  },
  {
    key: "GITHUB_TOKEN",
    label: "GitHub Token (GITHUB_TOKEN)",
    hint: "Personal access token for the GitHub account that owns the repo. Needs 'repo' scope to clone, push, and create PRs.",
    placeholder: "ghp_...",
    sensitive: true,
  },
  {
    key: "GH_TOKEN",
    label: "GitHub Token (GH_TOKEN)",
    hint: "Same token as above — set both fields to the same value so the gh CLI and git both authenticate correctly.",
    placeholder: "ghp_...",
    sensitive: true,
  },
  {
    key: "MODEL",
    label: "AI Model",
    hint: "Model used by agents, e.g. openai/gpt-4o or openai/gpt-5.4. Leave blank to use the default.",
    placeholder: "openai/gpt-4o",
    sensitive: false,
  },
  {
    key: "REPO_LINK",
    label: "Repository URL",
    hint: "Full GitHub URL of the repo agents should work in (e.g. https://github.com/your-org/your-repo). Agents clone this repo, make changes, and open PRs here.",
    placeholder: "https://github.com/your-org/your-repo",
    sensitive: false,
  },
] as const;

type ManagedEnvKey = (typeof SIMPLE_ENV_FIELDS)[number]["key"];

function createManagedEnvState<T>(value: T): Record<ManagedEnvKey, T> {
  return {
    OPENAI_API_KEY: value,
    GITHUB_TOKEN: value,
    GH_TOKEN: value,
    MODEL: value,
    REPO_LINK: value,
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function normalizeSecretName(value: string): string {
  return value.trim().toUpperCase();
}

export function CompanySettings() {
  const {
    companies,
    selectedCompany,
    selectedCompanyId,
    setSelectedCompanyId
  } = useCompany();
  const { setBreadcrumbs } = useBreadcrumbs();
  const { pushToast } = useToast();
  const queryClient = useQueryClient();
  // General settings local state
  const [companyName, setCompanyName] = useState("");
  const [description, setDescription] = useState("");
  const [brandColor, setBrandColor] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [logoUploadError, setLogoUploadError] = useState<string | null>(null);

  // Sync local state from selected company
  useEffect(() => {
    if (!selectedCompany) return;
    setCompanyName(selectedCompany.name);
    setDescription(selectedCompany.description ?? "");
    setBrandColor(selectedCompany.brandColor ?? "");
    setLogoUrl(selectedCompany.logoUrl ?? "");
  }, [selectedCompany]);

  const [inviteError, setInviteError] = useState<string | null>(null);
  const [inviteSnippet, setInviteSnippet] = useState<string | null>(null);
  const [snippetCopied, setSnippetCopied] = useState(false);
  const [snippetCopyDelightId, setSnippetCopyDelightId] = useState(0);
  const [envValues, setEnvValues] = useState<Record<ManagedEnvKey, string>>(
    () => createManagedEnvState(""),
  );
  const [envClearFlags, setEnvClearFlags] = useState<Record<ManagedEnvKey, boolean>>(
    () => createManagedEnvState(false),
  );
  const [syncEnvToAgents, setSyncEnvToAgents] = useState(true);

  const secretsQuery = useQuery({
    queryKey: selectedCompanyId ? queryKeys.secrets.list(selectedCompanyId) : ["secrets", "none"],
    queryFn: () => secretsApi.list(selectedCompanyId!),
    enabled: Boolean(selectedCompanyId),
  });

  const managedSecretsByName = useMemo(() => {
    const map = new Map<ManagedEnvKey, CompanySecret>();
    const keySet = new Set<ManagedEnvKey>(SIMPLE_ENV_FIELDS.map((field) => field.key));
    for (const field of SIMPLE_ENV_FIELDS) {
      const existing = (secretsQuery.data ?? []).find(
        (secret) => normalizeSecretName(secret.name) === field.key,
      );
      if (existing) {
        map.set(field.key, existing);
      }
    }
    for (const secret of secretsQuery.data ?? []) {
      const normalized = normalizeSecretName(secret.name);
      if (!keySet.has(normalized as ManagedEnvKey)) continue;
      const mappedKey = normalized as ManagedEnvKey;
      if (!map.has(mappedKey)) {
        map.set(mappedKey, secret);
      }
    }
    return map;
  }, [secretsQuery.data]);

  const generalDirty =
    !!selectedCompany &&
    (companyName !== selectedCompany.name ||
      description !== (selectedCompany.description ?? "") ||
      brandColor !== (selectedCompany.brandColor ?? ""));

  const generalMutation = useMutation({
    mutationFn: (data: {
      name: string;
      description: string | null;
      brandColor: string | null;
    }) => companiesApi.update(selectedCompanyId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.companies.all });
    }
  });

  const settingsMutation = useMutation({
    mutationFn: (requireApproval: boolean) =>
      companiesApi.update(selectedCompanyId!, {
        requireBoardApprovalForNewAgents: requireApproval
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.companies.all });
    }
  });

  const inviteMutation = useMutation({
    mutationFn: () =>
      accessApi.createOpenClawInvitePrompt(selectedCompanyId!),
    onSuccess: async (invite) => {
      setInviteError(null);
      const base = window.location.origin.replace(/\/+$/, "");
      const onboardingTextLink =
        invite.onboardingTextUrl ??
        invite.onboardingTextPath ??
        `/api/invites/${invite.token}/onboarding.txt`;
      const absoluteUrl = onboardingTextLink.startsWith("http")
        ? onboardingTextLink
        : `${base}${onboardingTextLink}`;
      setSnippetCopied(false);
      setSnippetCopyDelightId(0);
      let snippet: string;
      try {
        const manifest = await accessApi.getInviteOnboarding(invite.token);
        snippet = buildAgentSnippet({
          onboardingTextUrl: absoluteUrl,
          connectionCandidates:
            manifest.onboarding.connectivity?.connectionCandidates ?? null,
          testResolutionUrl:
            manifest.onboarding.connectivity?.testResolutionEndpoint?.url ??
            null
        });
      } catch {
        snippet = buildAgentSnippet({
          onboardingTextUrl: absoluteUrl,
          connectionCandidates: null,
          testResolutionUrl: null
        });
      }
      setInviteSnippet(snippet);
      try {
        await navigator.clipboard.writeText(snippet);
        setSnippetCopied(true);
        setSnippetCopyDelightId((prev) => prev + 1);
        setTimeout(() => setSnippetCopied(false), 2000);
      } catch {
        /* clipboard may not be available */
      }
      queryClient.invalidateQueries({
        queryKey: queryKeys.sidebarBadges(selectedCompanyId!)
      });
    },
    onError: (err) => {
      setInviteError(
        err instanceof Error ? err.message : "Failed to create invite"
      );
    }
  });

  const syncLogoState = (nextLogoUrl: string | null) => {
    setLogoUrl(nextLogoUrl ?? "");
    void queryClient.invalidateQueries({ queryKey: queryKeys.companies.all });
  };

  const logoUploadMutation = useMutation({
    mutationFn: (file: File) =>
      assetsApi
        .uploadCompanyLogo(selectedCompanyId!, file)
        .then((asset) => companiesApi.update(selectedCompanyId!, { logoAssetId: asset.assetId })),
    onSuccess: (company) => {
      syncLogoState(company.logoUrl);
      setLogoUploadError(null);
    }
  });

  const clearLogoMutation = useMutation({
    mutationFn: () => companiesApi.update(selectedCompanyId!, { logoAssetId: null }),
    onSuccess: (company) => {
      setLogoUploadError(null);
      syncLogoState(company.logoUrl);
    }
  });

  function handleLogoFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    event.currentTarget.value = "";
    if (!file) return;
    setLogoUploadError(null);
    logoUploadMutation.mutate(file);
  }

  function handleClearLogo() {
    clearLogoMutation.mutate();
  }

  useEffect(() => {
    setInviteError(null);
    setInviteSnippet(null);
    setSnippetCopied(false);
    setSnippetCopyDelightId(0);
    setEnvValues(createManagedEnvState(""));
    setEnvClearFlags(createManagedEnvState(false));
  }, [selectedCompanyId]);

  const envMutation = useMutation({
    mutationFn: async () => {
      if (!selectedCompanyId) throw new Error("Select a company first.");

      const latestSecrets = await secretsApi.list(selectedCompanyId);
      const managedSecrets = new Map<ManagedEnvKey, CompanySecret>();
      for (const field of SIMPLE_ENV_FIELDS) {
        const existing = latestSecrets.find(
          (secret) => normalizeSecretName(secret.name) === field.key,
        );
        if (existing) managedSecrets.set(field.key, existing);
      }
      const deletedKeys = new Set<ManagedEnvKey>();
      let upsertedCount = 0;
      let clearedCount = 0;

      for (const field of SIMPLE_ENV_FIELDS) {
        const key = field.key;
        const enteredValue = envValues[key].trim();
        const shouldClear = envClearFlags[key];
        const existing = managedSecrets.get(key);

        if (enteredValue.length > 0) {
          let nextSecret: CompanySecret;
          if (existing) {
            nextSecret = await secretsApi.rotate(existing.id, { value: enteredValue });
          } else {
            try {
              nextSecret = await secretsApi.create(selectedCompanyId, {
                name: key,
                value: enteredValue,
                description: `Managed from Company Settings (${key})`,
              });
            } catch (err) {
              const latest = await secretsApi.list(selectedCompanyId);
              const matched = latest.find(
                (secret) => normalizeSecretName(secret.name) === key,
              );
              if (!matched) throw err;
              nextSecret = await secretsApi.rotate(matched.id, { value: enteredValue });
            }
          }
          managedSecrets.set(key, nextSecret);
          deletedKeys.delete(key);
          upsertedCount += 1;
          continue;
        }

        if (shouldClear && existing) {
          await secretsApi.remove(existing.id);
          managedSecrets.delete(key);
          deletedKeys.add(key);
          clearedCount += 1;
        }
      }

      let syncedAgents = 0;
      let skippedAgents = 0;
      let syncWarning: string | null = null;
      if (syncEnvToAgents) {
        try {
          const agents = await agentsApi.list(selectedCompanyId);

          for (const agent of agents) {
            if (agent.status === "terminated") continue;
            const adapterConfig = asRecord(agent.adapterConfig) ?? {};
            const rawEnv = asRecord(adapterConfig.env);
            const nextEnv: Record<string, EnvBinding> = { ...(rawEnv as Record<string, EnvBinding> | null ?? {}) };
            let changed = false;

            for (const field of SIMPLE_ENV_FIELDS) {
              const key = field.key;
              const secret = managedSecrets.get(key);
              if (secret) {
                const existingBinding = nextEnv[key];
                const existingRef =
                  typeof existingBinding === "object" &&
                  existingBinding !== null &&
                  "type" in existingBinding &&
                  "secretId" in existingBinding
                    ? existingBinding
                    : null;
                if (
                  !existingRef ||
                  existingRef.type !== "secret_ref" ||
                  existingRef.secretId !== secret.id
                ) {
                  nextEnv[key] = { type: "secret_ref", secretId: secret.id, version: "latest" };
                  changed = true;
                }
                continue;
              }

              if (deletedKeys.has(key) && Object.prototype.hasOwnProperty.call(nextEnv, key)) {
                delete nextEnv[key];
                changed = true;
              }
            }

            if (changed) {
              try {
                await agentsApi.update(
                  agent.id,
                  {
                    adapterConfig: {
                      ...adapterConfig,
                      env: nextEnv,
                    },
                  },
                  selectedCompanyId,
                );
                syncedAgents += 1;
              } catch {
                skippedAgents += 1;
              }
            }
          }
        } catch (err) {
          syncWarning = err instanceof Error ? err.message : "Agent sync unavailable";
        }
      }

      return { upsertedCount, clearedCount, syncedAgents, skippedAgents, syncWarning };
    },
    onSuccess: async ({ upsertedCount, clearedCount, syncedAgents, skippedAgents, syncWarning }) => {
      setEnvValues(createManagedEnvState(""));
      setEnvClearFlags(createManagedEnvState(false));
      await queryClient.invalidateQueries({ queryKey: queryKeys.secrets.list(selectedCompanyId!) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.agents.list(selectedCompanyId!) });
      pushToast({
        tone: "success",
        title: "Environment settings saved",
        body:
          `Updated ${upsertedCount} value(s)` +
          (clearedCount > 0 ? `, cleared ${clearedCount}` : "") +
          (syncEnvToAgents
            ? `, synced ${syncedAgents} agent(s)` +
              (skippedAgents > 0 ? `, skipped ${skippedAgents} missing agent(s).` : ".")
            : "."),
      });
      if (syncWarning) {
        pushToast({
          tone: "warn",
          title: "Environment saved, but agent sync was skipped",
          body: syncWarning,
        });
      }
    },
    onError: (err) => {
      pushToast({
        tone: "error",
        title: "Failed to save environment settings",
        body: err instanceof Error ? err.message : "Unknown error",
      });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: ({
      companyId,
      nextCompanyId
    }: {
      companyId: string;
      nextCompanyId: string | null;
    }) => companiesApi.archive(companyId).then(() => ({ nextCompanyId })),
    onSuccess: async ({ nextCompanyId }) => {
      if (nextCompanyId) {
        setSelectedCompanyId(nextCompanyId);
      }
      await queryClient.invalidateQueries({
        queryKey: queryKeys.companies.all
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.companies.stats
      });
    }
  });

  useEffect(() => {
    setBreadcrumbs([
      { label: selectedCompany?.name ?? "Company", href: "/dashboard" },
      { label: "Settings" }
    ]);
  }, [setBreadcrumbs, selectedCompany?.name]);

  if (!selectedCompany) {
    return (
      <div className="text-sm text-muted-foreground">
        No company selected. Select a company from the switcher above.
      </div>
    );
  }

  function handleSaveGeneral() {
    generalMutation.mutate({
      name: companyName.trim(),
      description: description.trim() || null,
      brandColor: brandColor || null
    });
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div className="flex items-center gap-2">
        <Settings className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-lg font-semibold">Company Settings</h1>
      </div>

      {/* General */}
      <div className="space-y-4">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          General
        </div>
        <div className="space-y-3 rounded-md border border-border px-4 py-4">
          <Field label="Company name" hint="The display name for your company.">
            <input
              className="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-sm outline-none"
              type="text"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
            />
          </Field>
          <Field
            label="Description"
            hint="Optional description shown in the company profile."
          >
            <input
              className="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-sm outline-none"
              type="text"
              value={description}
              placeholder="Optional company description"
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
        </div>
      </div>

      {/* Appearance */}
      <div className="space-y-4">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Appearance
        </div>
        <div className="space-y-3 rounded-md border border-border px-4 py-4">
          <div className="flex items-start gap-4">
            <div className="shrink-0">
              <CompanyPatternIcon
                companyName={companyName || selectedCompany.name}
                logoUrl={logoUrl || null}
                brandColor={brandColor || null}
                className="rounded-[14px]"
              />
            </div>
            <div className="flex-1 space-y-3">
              <Field
                label="Logo"
                hint="Upload a PNG, JPEG, WEBP, GIF, or SVG logo image."
              >
                <div className="space-y-2">
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
                    onChange={handleLogoFileChange}
                    className="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-sm outline-none file:mr-4 file:rounded-md file:border-0 file:bg-muted file:px-2.5 file:py-1 file:text-xs"
                  />
                  {logoUrl && (
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={handleClearLogo}
                        disabled={clearLogoMutation.isPending}
                      >
                        {clearLogoMutation.isPending ? "Removing..." : "Remove logo"}
                      </Button>
                    </div>
                  )}
                  {(logoUploadMutation.isError || logoUploadError) && (
                    <span className="text-xs text-destructive">
                      {logoUploadError ??
                        (logoUploadMutation.error instanceof Error
                          ? logoUploadMutation.error.message
                          : "Logo upload failed")}
                    </span>
                  )}
                  {clearLogoMutation.isError && (
                    <span className="text-xs text-destructive">
                      {clearLogoMutation.error.message}
                    </span>
                  )}
                  {logoUploadMutation.isPending && (
                    <span className="text-xs text-muted-foreground">Uploading logo...</span>
                  )}
                </div>
              </Field>
              <Field
                label="Brand color"
                hint="Sets the hue for the company icon. Leave empty for auto-generated color."
              >
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={brandColor || "#6366f1"}
                    onChange={(e) => setBrandColor(e.target.value)}
                    className="h-8 w-8 cursor-pointer rounded border border-border bg-transparent p-0"
                  />
                  <input
                    type="text"
                    value={brandColor}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === "" || /^#[0-9a-fA-F]{0,6}$/.test(v)) {
                        setBrandColor(v);
                      }
                    }}
                    placeholder="Auto"
                    className="w-28 rounded-md border border-border bg-transparent px-2.5 py-1.5 text-sm font-mono outline-none"
                  />
                  {brandColor && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setBrandColor("")}
                      className="text-xs text-muted-foreground"
                    >
                      Clear
                    </Button>
                  )}
                </div>
              </Field>
            </div>
          </div>
        </div>
      </div>

      {/* Save button for General + Appearance */}
      {generalDirty && (
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={handleSaveGeneral}
            disabled={generalMutation.isPending || !companyName.trim()}
          >
            {generalMutation.isPending ? "Saving..." : "Save changes"}
          </Button>
          {generalMutation.isSuccess && (
            <span className="text-xs text-muted-foreground">Saved</span>
          )}
          {generalMutation.isError && (
            <span className="text-xs text-destructive">
              {generalMutation.error instanceof Error
                  ? generalMutation.error.message
                  : "Failed to save"}
            </span>
          )}
        </div>
      )}

      {/* Hiring */}
      <div className="space-y-4">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Hiring
        </div>
        <div className="rounded-md border border-border px-4 py-3">
          <ToggleField
            label="Require board approval for new hires"
            hint="New agent hires stay pending until approved by board."
            checked={!!selectedCompany.requireBoardApprovalForNewAgents}
            onChange={(v) => settingsMutation.mutate(v)}
          />
        </div>
      </div>

      {/* Invites */}
      <div className="space-y-4">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Invites
        </div>
        <div className="space-y-3 rounded-md border border-border px-4 py-4">
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">
              Generate an OpenClaw agent invite snippet.
            </span>
            <HintIcon text="Creates a short-lived OpenClaw agent invite and renders a copy-ready prompt." />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              onClick={() => inviteMutation.mutate()}
              disabled={inviteMutation.isPending}
            >
              {inviteMutation.isPending
                ? "Generating..."
                : "Generate OpenClaw Invite Prompt"}
            </Button>
          </div>
          {inviteError && (
            <p className="text-sm text-destructive">{inviteError}</p>
          )}
          {inviteSnippet && (
            <div className="rounded-md border border-border bg-muted/30 p-2">
              <div className="flex items-center justify-between gap-2">
                <div className="text-xs text-muted-foreground">
                  OpenClaw Invite Prompt
                </div>
                {snippetCopied && (
                  <span
                    key={snippetCopyDelightId}
                    className="flex items-center gap-1 text-xs text-green-600 animate-pulse"
                  >
                    <Check className="h-3 w-3" />
                    Copied
                  </span>
                )}
              </div>
              <div className="mt-1 space-y-1.5">
                <textarea
                  className="h-[28rem] w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs outline-none"
                  value={inviteSnippet}
                  readOnly
                />
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(inviteSnippet);
                        setSnippetCopied(true);
                        setSnippetCopyDelightId((prev) => prev + 1);
                        setTimeout(() => setSnippetCopied(false), 2000);
                      } catch {
                        /* clipboard may not be available */
                      }
                    }}
                  >
                    {snippetCopied ? "Copied snippet" : "Copy snippet"}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Environment Setup */}
      <div className="space-y-4">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Environment Setup
        </div>
        <div className="space-y-3 rounded-md border border-border px-4 py-4">
          <p className="text-sm text-muted-foreground">
            Fill in your API keys and repository URL here — no backend access needed.
            Agents will automatically clone your repo, complete the task, and open a PR using these values.
            All values are stored as encrypted company secrets.
          </p>
          {secretsQuery.error && (
            <p className="text-xs text-destructive">
              {secretsQuery.error instanceof Error
                ? secretsQuery.error.message
                : "Failed to load existing environment settings."}
            </p>
          )}
          <div className="space-y-3">
            {SIMPLE_ENV_FIELDS.map((field) => {
              const configured = managedSecretsByName.get(field.key) ?? null;
              return (
                <Field key={field.key} label={field.label} hint={field.hint}>
                  <div className="space-y-1.5">
                    <input
                      className="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-sm font-mono outline-none"
                      type={field.sensitive ? "password" : "text"}
                      value={envValues[field.key]}
                      placeholder={
                        configured
                          ? "Leave blank to keep current value"
                          : field.placeholder
                      }
                      onChange={(e) => {
                        const value = e.target.value;
                        setEnvValues((prev) => ({ ...prev, [field.key]: value }));
                        if (value.length > 0) {
                          setEnvClearFlags((prev) => ({ ...prev, [field.key]: false }));
                        }
                      }}
                    />
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-muted-foreground">
                        {configured
                          ? `Configured (version ${configured.latestVersion})`
                          : "Not configured yet"}
                      </span>
                      {configured && (
                        <label className="inline-flex items-center gap-1 text-muted-foreground">
                          <input
                            type="checkbox"
                            checked={envClearFlags[field.key]}
                            onChange={(e) =>
                              setEnvClearFlags((prev) => ({
                                ...prev,
                                [field.key]: e.target.checked,
                              }))
                            }
                          />
                          Clear on save
                        </label>
                      )}
                    </div>
                  </div>
                </Field>
              );
            })}
          </div>
          <div className="rounded-md border border-border bg-muted/20 px-3 py-2">
            <ToggleField
              label="Sync these environment keys to existing agents"
              hint="When enabled, agents in this company automatically receive secret refs for these keys."
              checked={syncEnvToAgents}
              onChange={setSyncEnvToAgents}
            />
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => envMutation.mutate()}
              disabled={envMutation.isPending || secretsQuery.isLoading}
            >
              {envMutation.isPending ? "Saving..." : "Save environment settings"}
            </Button>
            {envMutation.isError && (
              <span className="text-xs text-destructive">
                {envMutation.error instanceof Error
                  ? envMutation.error.message
                  : "Failed to save settings"}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Import / Export */}
      <div className="space-y-4">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Company Packages
        </div>
        <div className="rounded-md border border-border px-4 py-4">
          <p className="text-sm text-muted-foreground">
            Import and export have moved to dedicated pages accessible from the{" "}
            <a href="/org" className="underline hover:text-foreground">Org Chart</a> header.
          </p>
          <div className="mt-3 flex items-center gap-2">
            <Button size="sm" variant="outline" asChild>
              <a href="/company/export">
                <Download className="mr-1.5 h-3.5 w-3.5" />
                Export
              </a>
            </Button>
            <Button size="sm" variant="outline" asChild>
              <a href="/company/import">
                <Upload className="mr-1.5 h-3.5 w-3.5" />
                Import
              </a>
            </Button>
          </div>
        </div>
      </div>

      {/* Danger Zone */}
      <div className="space-y-4">
        <div className="text-xs font-medium text-destructive uppercase tracking-wide">
          Danger Zone
        </div>
        <div className="space-y-3 rounded-md border border-destructive/40 bg-destructive/5 px-4 py-4">
          <p className="text-sm text-muted-foreground">
            Archive this company to hide it from the sidebar. This persists in
            the database.
          </p>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="destructive"
              disabled={
                archiveMutation.isPending ||
                selectedCompany.status === "archived"
              }
              onClick={() => {
                if (!selectedCompanyId) return;
                const confirmed = window.confirm(
                  `Archive company "${selectedCompany.name}"? It will be hidden from the sidebar.`
                );
                if (!confirmed) return;
                const nextCompanyId =
                  companies.find(
                    (company) =>
                      company.id !== selectedCompanyId &&
                      company.status !== "archived"
                  )?.id ?? null;
                archiveMutation.mutate({
                  companyId: selectedCompanyId,
                  nextCompanyId
                });
              }}
            >
              {archiveMutation.isPending
                ? "Archiving..."
                : selectedCompany.status === "archived"
                ? "Already archived"
                : "Archive company"}
            </Button>
            {archiveMutation.isError && (
              <span className="text-xs text-destructive">
                {archiveMutation.error instanceof Error
                  ? archiveMutation.error.message
                  : "Failed to archive company"}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function buildAgentSnippet(input: AgentSnippetInput) {
  const candidateUrls = buildCandidateOnboardingUrls(input);
  const resolutionTestUrl = buildResolutionTestUrl(input);

  const candidateList =
    candidateUrls.length > 0
      ? candidateUrls.map((u) => `- ${u}`).join("\n")
      : "- (No candidate URLs available yet.)";

  const connectivityBlock =
    candidateUrls.length === 0
      ? `No candidate URLs are available. Ask your user to configure a reachable hostname in Paperclip, then retry.
Suggested steps:
- choose a hostname that resolves to the Paperclip host from your runtime
- run: pnpm paperclipai allowed-hostname <host>
- restart Paperclip
- verify with: curl -fsS http://<host>:3100/api/health
- regenerate this invite snippet`
      : `If none are reachable, ask your user to add a reachable hostname in Paperclip, restart, and retry.
Suggested command:
- pnpm paperclipai allowed-hostname <host>
Then verify with: curl -fsS <base-url>/api/health`;

  const resolutionLine = resolutionTestUrl
    ? `\nYou MUST test Paperclip-to-gateway reachability, call: ${resolutionTestUrl}?url=<urlencoded-gateway-url> (using the hostname that worked above). Do not assume your 172.x is necessarily reachable from Paperclip. Test it. `
    : "";

  return `You're invited to join a Paperclip organization.

The URLs you should try are:
${candidateList}

Connectivity guidance:
If you are running on a different machine than Paperclip, Paperclip must be reachable at one of the hostnames used above.
Verify the hostname works from your runtime with: GET <base-url>/api/health

${connectivityBlock}

For your "agentName", just use your own agent name (OpenClaw or whatever your name is) and send it directly.
You also need to send a gateway URL that Paperclip can access. Check your config and include that URL.${resolutionLine}

---

This onboarding flow is for OpenClaw Gateway.
When you submit the join request, use:
- \`adapterType: "openclaw_gateway"\`
- \`agentDefaultsPayload.url\` as your \`ws://\` or \`wss://\` gateway URL
- \`agentDefaultsPayload.headers["x-openclaw-token"]\` with your gateway token
- (legacy accepted) \`agentDefaultsPayload.headers["x-openclaw-auth"]\`
- Keep device auth enabled (recommended). If \`devicePrivateKeyPem\` is omitted, Paperclip will generate and persist one during join so pairing approvals remain stable.
- Only use \`disableDeviceAuth=true\` for special environments where pairing cannot be completed.

Do NOT use \`/v1/responses\` or \`/hooks/*\` in this join flow.

Before you do anything, please respond to your user that you understand the instructions and you're going to work on them. Then do the step above in another session called "paperclip-onboarding" and then tell your user when you're done. Update your user in intermediate steps along the way so they know what's going on.

Then after you've connected to Paperclip (exchanged keys etc.) you MUST review and follow the onboarding instructions in onboarding.txt they give you.

`;
}

function buildCandidateOnboardingUrls(input: AgentSnippetInput): string[] {
  const candidates = (input.connectionCandidates ?? [])
    .map((candidate) => candidate.trim())
    .filter(Boolean);
  const urls = new Set<string>();
  let onboardingUrl: URL | null = null;

  try {
    onboardingUrl = new URL(input.onboardingTextUrl);
    urls.add(onboardingUrl.toString());
  } catch {
    const trimmed = input.onboardingTextUrl.trim();
    if (trimmed) {
      urls.add(trimmed);
    }
  }

  if (!onboardingUrl) {
    for (const candidate of candidates) {
      urls.add(candidate);
    }
    return Array.from(urls);
  }

  const onboardingPath = `${onboardingUrl.pathname}${onboardingUrl.search}`;
  for (const candidate of candidates) {
    try {
      const base = new URL(candidate);
      urls.add(`${base.origin}${onboardingPath}`);
    } catch {
      urls.add(candidate);
    }
  }

  return Array.from(urls);
}

function buildResolutionTestUrl(input: AgentSnippetInput): string | null {
  const explicit = input.testResolutionUrl?.trim();
  if (explicit) return explicit;

  try {
    const onboardingUrl = new URL(input.onboardingTextUrl);
    const testPath = onboardingUrl.pathname.replace(
      /\/onboarding\.txt$/,
      "/test-resolution"
    );
    return `${onboardingUrl.origin}${testPath}`;
  } catch {
    return null;
  }
}
