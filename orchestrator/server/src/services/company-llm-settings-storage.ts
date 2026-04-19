import type { SecretProvider } from "@paperclipai/shared";
import {
  companyLlmSettingsSchema,
  LLM_PROVIDER_IDS,
  type CompanyLlmSettings,
  type LlmProviderId,
} from "@paperclipai/shared";
import { unprocessable } from "../errors.js";
import { getSecretProvider } from "../secrets/provider-registry.js";

export const REDACTED_API_KEY = "***REDACTED***";

type StoredApiKeyMaterial = {
  material: Record<string, unknown>;
  valueSha256: string;
  externalRef: string | null;
};

export type CompanyLlmSettingsStorageRecord = {
  settingsJson: Record<string, unknown>;
  apiKeyMaterial: Record<string, StoredApiKeyMaterial>;
  encryptionProvider: SecretProvider;
};

function cloneSettings(input: CompanyLlmSettings): CompanyLlmSettings {
  return JSON.parse(JSON.stringify(input)) as CompanyLlmSettings;
}

export function validateCompanyLlmSettings(input: unknown): CompanyLlmSettings {
  const parsed = companyLlmSettingsSchema.safeParse(input);
  if (!parsed.success) {
    throw unprocessable(parsed.error.issues.map((issue) => issue.message).join("; "));
  }
  return parsed.data;
}

export async function encryptCompanyLlmSettingsForStorage(
  input: unknown,
  encryptionProvider: SecretProvider = "local_encrypted",
): Promise<CompanyLlmSettingsStorageRecord> {
  const validated = validateCompanyLlmSettings(input);
  const provider = getSecretProvider(encryptionProvider);
  const settings = cloneSettings(validated);
  const apiKeyMaterial: Record<string, StoredApiKeyMaterial> = {};

  for (const providerId of LLM_PROVIDER_IDS) {
    const providerConfig = settings.llm.providers[providerId];
    if (!providerConfig?.api_key) continue;
    if (providerConfig.api_key.trim() === REDACTED_API_KEY) {
      delete providerConfig.api_key;
      continue;
    }
    const prepared = await provider.createVersion({
      value: providerConfig.api_key,
      externalRef: null,
    });
    apiKeyMaterial[providerId] = {
      material: prepared.material,
      valueSha256: prepared.valueSha256,
      externalRef: prepared.externalRef,
    };
    delete providerConfig.api_key;
  }

  return {
    settingsJson: settings as unknown as Record<string, unknown>,
    apiKeyMaterial,
    encryptionProvider,
  };
}

export async function hydrateCompanyLlmSettingsFromStorage(
  stored: CompanyLlmSettingsStorageRecord,
): Promise<CompanyLlmSettings> {
  const provider = getSecretProvider(stored.encryptionProvider);
  const candidate = JSON.parse(JSON.stringify(stored.settingsJson)) as Record<string, unknown>;
  const llm = (candidate.llm ?? {}) as Record<string, unknown>;
  const providers = (llm.providers ?? {}) as Record<string, unknown>;
  llm.providers = providers;
  candidate.llm = llm;

  // Stored settings omit encrypted key values by design. Add redacted placeholders
  // for providers that have persisted key material so schema validation can pass.
  for (const providerId of LLM_PROVIDER_IDS) {
    const material = stored.apiKeyMaterial[providerId];
    if (!material) continue;
    const existingCfg = providers[providerId];
    const cfg =
      existingCfg && typeof existingCfg === "object" && !Array.isArray(existingCfg)
        ? (existingCfg as Record<string, unknown>)
        : {};
    if (typeof cfg.api_key !== "string" || cfg.api_key.trim().length === 0) {
      cfg.api_key = REDACTED_API_KEY;
    }
    providers[providerId] = cfg;
  }

  const settings = validateCompanyLlmSettings(candidate);
  const hydrated = cloneSettings(settings);

  for (const providerId of LLM_PROVIDER_IDS) {
    const providerConfig = hydrated.llm.providers[providerId];
    const material = stored.apiKeyMaterial[providerId];
    if (!providerConfig || !material) continue;
    providerConfig.api_key = await provider.resolveVersion({
      material: material.material,
      externalRef: material.externalRef,
    });
  }

  return hydrated;
}

export function llmProviderIdFromUnknown(value: string): LlmProviderId {
  if ((LLM_PROVIDER_IDS as readonly string[]).includes(value)) return value as LlmProviderId;
  throw unprocessable(`Unsupported LLM provider: ${value}`);
}

