import { z } from "zod";

export const LLM_PROVIDER_IDS = [
  "vllm_openai_compatible",
  "openai",
  "anthropic",
  "openrouter",
  "nvidia_nim",
] as const;

export type LlmProviderId = (typeof LLM_PROVIDER_IDS)[number];

export const llmProviderIdSchema = z.enum(LLM_PROVIDER_IDS);

export const llmRoleKeySchema = z.enum(["architect", "grunt", "pedant", "scribe"]);
export const executionApprovalModeSchema = z.enum(["always_proceed", "ask_before_proceed"]);
export const executionApprovalScopeSchema = z.enum(["major_only", "every_issue"]);

const llmProviderConfigSchema = z.object({
  enabled: z.boolean().optional().default(true),
  base_url: z.string().url().optional(),
  api_key: z.string().min(1).optional(),
  timeout_seconds: z.number().int().positive().max(600).optional(),
  headers: z.record(z.string()).optional(),
});

const llmRoleModelSchema = z.object({
  provider: llmProviderIdSchema,
  model: z.string().min(1),
});

const llmRoleRetryPolicySchema = z
  .object({
    architect: z.number().int().min(0).max(5).optional(),
    grunt: z.number().int().min(0).max(5).optional(),
    pedant: z.number().int().min(0).max(5).optional(),
    scribe: z.number().int().min(0).max(5).optional(),
  })
  .default({});

const llmGuardrailsSchema = z
  .object({
    allowed_models: z.array(z.string().min(1)).default([]),
    max_timeout_seconds: z.number().int().positive().max(600).default(120),
    max_tokens_per_request: z.number().int().positive().max(1_000_000).optional(),
    role_retries: llmRoleRetryPolicySchema,
  })
  .default({
    allowed_models: [],
    max_timeout_seconds: 120,
    role_retries: {},
  });

export const companyLlmSettingsSchema = z
  .object({
    execution_gate: z
      .object({
        mode: executionApprovalModeSchema.default("always_proceed"),
        scope: executionApprovalScopeSchema.default("major_only"),
      })
      .default({
        mode: "always_proceed",
        scope: "major_only",
      }),
    llm: z
      .object({
        default_provider: llmProviderIdSchema,
        default_model: z.string().min(1),
        providers: z
          .object({
            vllm_openai_compatible: llmProviderConfigSchema.optional(),
            openai: llmProviderConfigSchema.optional(),
            anthropic: llmProviderConfigSchema.optional(),
            openrouter: llmProviderConfigSchema.optional(),
            nvidia_nim: llmProviderConfigSchema.optional(),
          })
          .default({}),
        role_models: z
          .object({
            architect: llmRoleModelSchema.optional(),
            grunt: llmRoleModelSchema.optional(),
            pedant: llmRoleModelSchema.optional(),
            scribe: llmRoleModelSchema.optional(),
          })
          .default({}),
        guardrails: llmGuardrailsSchema,
      })
      .superRefine((value, ctx) => {
        const defaultProvider = value.providers[value.default_provider];
        if (!defaultProvider || defaultProvider.enabled === false) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: `default_provider '${value.default_provider}' must be present and enabled`,
            path: ["providers", value.default_provider],
          });
        }

        const providerEntries = Object.entries(value.providers) as Array<[LlmProviderId, z.infer<typeof llmProviderConfigSchema>]>;
        for (const [providerId, providerConfig] of providerEntries) {
          if (!providerConfig || providerConfig.enabled === false) continue;
          if (providerId === "vllm_openai_compatible" && !providerConfig.base_url) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              message: "vllm_openai_compatible requires base_url when enabled",
              path: ["providers", providerId, "base_url"],
            });
          }
          if (providerId !== "vllm_openai_compatible" && !providerConfig.api_key) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              message: `${providerId} requires api_key when enabled`,
              path: ["providers", providerId, "api_key"],
            });
          }
        }

        if (value.guardrails.allowed_models.length > 0 && !value.guardrails.allowed_models.includes(value.default_model)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: "default_model must be included in guardrails.allowed_models when allowlist is configured",
            path: ["guardrails", "allowed_models"],
          });
        }

        const roleEntries = Object.entries(value.role_models) as Array<[string, z.infer<typeof llmRoleModelSchema> | undefined]>;
        for (const [roleKey, roleEntry] of roleEntries) {
          if (!roleEntry) continue;
          if (value.guardrails.allowed_models.length > 0 && !value.guardrails.allowed_models.includes(roleEntry.model)) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              message: `${roleKey} model must be included in guardrails.allowed_models when allowlist is configured`,
              path: ["role_models", roleKey, "model"],
            });
          }
        }
      }),
  })
  .strict();

export type CompanyLlmSettings = z.infer<typeof companyLlmSettingsSchema>;

export const updateCompanyLlmSettingsSchema = companyLlmSettingsSchema;
export type UpdateCompanyLlmSettings = z.infer<typeof updateCompanyLlmSettingsSchema>;

export const testCompanyLlmSettingsSchema = z.object({
  provider: llmProviderIdSchema.optional(),
  model: z.string().min(1).optional(),
  base_url: z.string().url().optional(),
  api_key: z.string().min(1).optional(),
  timeout_seconds: z.number().int().positive().max(600).optional(),
});
export type TestCompanyLlmSettings = z.infer<typeof testCompanyLlmSettingsSchema>;

export const listLlmModelsQuerySchema = z.object({
  provider: llmProviderIdSchema,
  base_url: z.string().url().optional(),
  api_key: z.string().min(1).optional(),
  timeout_seconds: z.coerce.number().int().positive().max(600).optional(),
});
export type ListLlmModelsQuery = z.infer<typeof listLlmModelsQuerySchema>;

export const issueExecutionPreviewDecisionSchema = z.object({
  decision: z.enum(["approve", "reject", "request_changes"]),
  note: z.string().max(5000).optional().nullable(),
});
export type IssueExecutionPreviewDecision = z.infer<typeof issueExecutionPreviewDecisionSchema>;

/**
 * Safe baseline used for migrations and new-company initialization.
 */
export const DEFAULT_COMPANY_LLM_SETTINGS: CompanyLlmSettings = {
  execution_gate: {
    mode: "always_proceed",
    scope: "major_only",
  },
  llm: {
    default_provider: "vllm_openai_compatible",
    default_model: "meta-llama/Meta-Llama-3.1-8B-Instruct",
    providers: {
      vllm_openai_compatible: {
        enabled: true,
        base_url: "http://vllm:8000/v1",
      },
    },
    role_models: {},
    guardrails: {
      allowed_models: [],
      max_timeout_seconds: 120,
      role_retries: {},
    },
  },
};

