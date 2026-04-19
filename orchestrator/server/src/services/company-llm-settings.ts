import { eq } from "drizzle-orm";
import type { Db } from "@paperclipai/db";
import { companyLlmSettings } from "@paperclipai/db";
import {
  DEFAULT_COMPANY_LLM_SETTINGS,
  LLM_PROVIDER_IDS,
  llmProviderIdSchema,
  type CompanyLlmSettings,
  type LlmProviderId,
} from "@paperclipai/shared";
import {
  encryptCompanyLlmSettingsForStorage,
  hydrateCompanyLlmSettingsFromStorage,
  validateCompanyLlmSettings,
  REDACTED_API_KEY,
  type CompanyLlmSettingsStorageRecord,
} from "./company-llm-settings-storage.js";
import { notFound, unprocessable } from "../errors.js";

type LlmProviderDescriptor = {
  id: LlmProviderId;
  label: string;
  requiresBaseUrl: boolean;
  supportsModelListProbe: boolean;
};

type TestInput = {
  provider?: string;
  model?: string;
  base_url?: string;
  api_key?: string;
  timeout_seconds?: number;
};

const PROVIDER_DESCRIPTORS: Record<LlmProviderId, LlmProviderDescriptor> = {
  vllm_openai_compatible: {
    id: "vllm_openai_compatible",
    label: "vLLM (OpenAI-compatible)",
    requiresBaseUrl: true,
    supportsModelListProbe: true,
  },
  openai: {
    id: "openai",
    label: "OpenAI",
    requiresBaseUrl: false,
    supportsModelListProbe: true,
  },
  anthropic: {
    id: "anthropic",
    label: "Anthropic",
    requiresBaseUrl: false,
    supportsModelListProbe: false,
  },
  openrouter: {
    id: "openrouter",
    label: "OpenRouter",
    requiresBaseUrl: false,
    supportsModelListProbe: true,
  },
  nvidia_nim: {
    id: "nvidia_nim",
    label: "NVIDIA NIM",
    requiresBaseUrl: true,
    supportsModelListProbe: true,
  },
};

function normalizeSettingsForStorage(input: unknown): CompanyLlmSettings {
  return validateCompanyLlmSettings(input);
}

function normalizeStoredRecord(row: typeof companyLlmSettings.$inferSelect): CompanyLlmSettingsStorageRecord {
  return {
    settingsJson: row.settingsJson as Record<string, unknown>,
    apiKeyMaterial: row.apiKeyMaterial as Record<string, { material: Record<string, unknown>; valueSha256: string; externalRef: string | null }>,
    encryptionProvider: row.encryptionProvider as CompanyLlmSettingsStorageRecord["encryptionProvider"],
  };
}

function withPreservedApiKeys(
  input: unknown,
  existing: CompanyLlmSettingsStorageRecord,
): unknown {
  if (!input || typeof input !== "object" || Array.isArray(input)) return input;
  const draft = JSON.parse(JSON.stringify(input)) as Record<string, unknown>;
  const llm = draft.llm;
  if (!llm || typeof llm !== "object" || Array.isArray(llm)) return input;
  const providers = (llm as Record<string, unknown>).providers;
  if (!providers || typeof providers !== "object" || Array.isArray(providers)) return input;

  for (const providerId of LLM_PROVIDER_IDS) {
    const providerConfig = (providers as Record<string, unknown>)[providerId];
    if (!providerConfig || typeof providerConfig !== "object" || Array.isArray(providerConfig)) continue;
    const cfg = providerConfig as Record<string, unknown>;
    const incomingApiKey = typeof cfg.api_key === "string" ? cfg.api_key.trim() : "";
    const hasExistingMaterial = Boolean(existing.apiKeyMaterial[providerId]);
    if (!hasExistingMaterial) {
      if (incomingApiKey === REDACTED_API_KEY) {
        throw unprocessable(`Cannot preserve API key for provider '${providerId}' because no stored key exists`);
      }
      continue;
    }
    if (!incomingApiKey || incomingApiKey === REDACTED_API_KEY) {
      cfg.api_key = REDACTED_API_KEY;
    }
  }

  return draft;
}

function inferModelListEndpoint(providerId: LlmProviderId, baseUrl?: string): { url: string; authHeader?: string } {
  const trimmedBase = baseUrl?.trim();
  if (providerId === "vllm_openai_compatible" || providerId === "nvidia_nim") {
    if (!trimmedBase) throw unprocessable(`${providerId} requires base_url`);
    const normalized = trimmedBase.replace(/\/+$/, "");
    return { url: `${normalized}/models` };
  }
  if (providerId === "openrouter") {
    return { url: "https://openrouter.ai/api/v1/models" };
  }
  if (providerId === "openai") {
    return { url: "https://api.openai.com/v1/models" };
  }
  throw unprocessable(`Model listing probe is not supported for provider: ${providerId}`);
}

async function fetchModelList(
  providerId: LlmProviderId,
  opts: { baseUrl?: string; apiKey?: string; timeoutSeconds?: number },
) {
  const descriptor = PROVIDER_DESCRIPTORS[providerId];
  if (!descriptor.supportsModelListProbe) {
    return {
      provider: providerId,
      models: [] as string[],
      status: "unsupported" as const,
      message: "Provider does not support model list probe via this endpoint",
    };
  }

  const endpoint = inferModelListEndpoint(providerId, opts.baseUrl);
  const timeoutMs = Math.max(1, (opts.timeoutSeconds ?? 15)) * 1000;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers: Record<string, string> = {
      Accept: "application/json",
    };
    if (opts.apiKey) {
      headers.Authorization = `Bearer ${opts.apiKey}`;
    }
    const response = await fetch(endpoint.url, {
      method: "GET",
      headers,
      signal: controller.signal,
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      return {
        provider: providerId,
        models: [] as string[],
        status: "failed" as const,
        message: `Probe failed (${response.status})`,
        details: body,
      };
    }

    const rows = Array.isArray((body as { data?: unknown })?.data)
      ? ((body as { data: Array<{ id?: unknown }> }).data)
      : [];
    const models = rows
      .map((row) => (typeof row.id === "string" ? row.id : null))
      .filter((id): id is string => Boolean(id));
    return {
      provider: providerId,
      models,
      status: "ok" as const,
      message: `Fetched ${models.length} model(s)`,
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function maskSecretsForResponse(stored: CompanyLlmSettingsStorageRecord): Promise<CompanyLlmSettings> {
  // Hydrate first so encrypted provider keys are available for runtime logic, then redact for API responses.
  const settings = await hydrateCompanyLlmSettingsFromStorage(stored);
  const cloned: CompanyLlmSettings = JSON.parse(JSON.stringify(settings)) as CompanyLlmSettings;
  for (const providerId of LLM_PROVIDER_IDS) {
    const providerConfig = cloned.llm.providers[providerId];
    if (!providerConfig) continue;
    if (stored.apiKeyMaterial[providerId]) {
      providerConfig.api_key = REDACTED_API_KEY;
    } else {
      delete providerConfig.api_key;
    }
  }
  return cloned;
}

export function companyLlmSettingsService(db: Db) {
  async function getRow(companyId: string) {
    return db
      .select()
      .from(companyLlmSettings)
      .where(eq(companyLlmSettings.companyId, companyId))
      .then((rows) => rows[0] ?? null);
  }

  async function createDefaultRow(companyId: string) {
    const encrypted = await encryptCompanyLlmSettingsForStorage(DEFAULT_COMPANY_LLM_SETTINGS);
    const [created] = await db
      .insert(companyLlmSettings)
      .values({
        companyId,
        settingsJson: encrypted.settingsJson,
        apiKeyMaterial: encrypted.apiKeyMaterial,
        encryptionProvider: encrypted.encryptionProvider,
      })
      .onConflictDoNothing()
      .returning();
    if (created) return created;
    const fallback = await getRow(companyId);
    if (!fallback) throw notFound("Company LLM settings could not be initialized");
    return fallback;
  }

  async function getOrCreate(companyId: string) {
    const existing = await getRow(companyId);
    if (existing) return existing;
    return createDefaultRow(companyId);
  }

  return {
    listProviders: () => Object.values(PROVIDER_DESCRIPTORS),

    getForCompany: async (companyId: string) => {
      const row = await getOrCreate(companyId);
      const stored = normalizeStoredRecord(row);
      return {
        companyId,
        settings: await maskSecretsForResponse(stored),
        updatedAt: row.updatedAt,
      };
    },

    updateForCompany: async (companyId: string, input: unknown) => {
      const existing = normalizeStoredRecord(await getOrCreate(companyId));
      const normalizedInput = withPreservedApiKeys(input, existing);
      const normalized = normalizeSettingsForStorage(normalizedInput);
      const encrypted = await encryptCompanyLlmSettingsForStorage(normalized);
      encrypted.apiKeyMaterial = {
        ...existing.apiKeyMaterial,
        ...encrypted.apiKeyMaterial,
      };
      const [updated] = await db
        .update(companyLlmSettings)
        .set({
          settingsJson: encrypted.settingsJson,
          apiKeyMaterial: encrypted.apiKeyMaterial,
          encryptionProvider: encrypted.encryptionProvider,
          updatedAt: new Date(),
        })
        .where(eq(companyLlmSettings.companyId, companyId))
        .returning();

      if (!updated) throw notFound("Company LLM settings not found");

      const stored = normalizeStoredRecord(updated);
      return {
        companyId,
        settings: await maskSecretsForResponse(stored),
        updatedAt: updated.updatedAt,
      };
    },

    testConfig: async (companyId: string, input: TestInput) => {
      const current = await getOrCreate(companyId);
      const currentStored = normalizeStoredRecord(current);
      const currentSettings = await hydrateCompanyLlmSettingsFromStorage(currentStored);
      const providerId = llmProviderIdSchema.parse(input.provider ?? currentSettings.llm.default_provider);
      const model = (input.model ?? currentSettings.llm.default_model).trim();
      if (!model) throw unprocessable("model is required");

      const providerConfig = (currentSettings.llm.providers[providerId] ?? {}) as {
        base_url?: string;
        api_key?: string;
        timeout_seconds?: number;
      };
      const baseUrl = input.base_url ?? providerConfig.base_url;
      const apiKey = input.api_key ?? providerConfig.api_key;
      const timeoutSeconds = input.timeout_seconds ?? providerConfig.timeout_seconds ?? 15;

      const probe = await fetchModelList(providerId, {
        baseUrl,
        apiKey,
        timeoutSeconds,
      });

      const modelAvailable = probe.models.length === 0
        ? null
        : probe.models.includes(model);

      return {
        provider: providerId,
        model,
        probe,
        modelAvailable,
      };
    },

    listModels: async (input: { provider: string; base_url?: string; api_key?: string; timeout_seconds?: number }) => {
      const provider = llmProviderIdSchema.parse(input.provider);
      const probe = await fetchModelList(provider, {
        baseUrl: input.base_url,
        apiKey: input.api_key,
        timeoutSeconds: input.timeout_seconds,
      });
      return probe;
    },
  };
}

