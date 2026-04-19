import { describe, expect, it } from "vitest";
import { companyLlmSettingsSchema } from "@paperclipai/shared";

describe("llm settings validation", () => {
  it("accepts valid guardrails payload", () => {
    const parsed = companyLlmSettingsSchema.parse({
      execution_gate: {
        mode: "ask_before_proceed",
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
        role_models: {
          architect: {
            provider: "vllm_openai_compatible",
            model: "meta-llama/Meta-Llama-3.1-8B-Instruct",
          },
        },
        guardrails: {
          allowed_models: ["meta-llama/Meta-Llama-3.1-8B-Instruct"],
          max_timeout_seconds: 60,
          max_tokens_per_request: 64000,
          role_retries: {
            architect: 2,
            scribe: 1,
          },
        },
      },
    });
    expect(parsed.llm.guardrails.max_timeout_seconds).toBe(60);
    expect(parsed.llm.guardrails.role_retries.architect).toBe(2);
  });

  it("rejects models that violate allowlist", () => {
    const result = companyLlmSettingsSchema.safeParse({
      execution_gate: {
        mode: "always_proceed",
        scope: "major_only",
      },
      llm: {
        default_provider: "vllm_openai_compatible",
        default_model: "not-allowed",
        providers: {
          vllm_openai_compatible: {
            enabled: true,
            base_url: "http://vllm:8000/v1",
          },
        },
        role_models: {},
        guardrails: {
          allowed_models: ["allowed-a"],
          max_timeout_seconds: 120,
          role_retries: {},
        },
      },
    });
    expect(result.success).toBe(false);
  });
});
