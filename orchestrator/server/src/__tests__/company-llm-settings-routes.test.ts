import express from "express";
import request from "supertest";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { errorHandler } from "../middleware/index.js";
import { companyLlmSettingsRoutes } from "../routes/company-llm-settings.js";

const mockCompanyLlmSettingsService = vi.hoisted(() => ({
  getForCompany: vi.fn(),
  updateForCompany: vi.fn(),
  testConfig: vi.fn(),
  listProviders: vi.fn(),
  listModels: vi.fn(),
}));
const mockLogActivity = vi.hoisted(() => vi.fn());

vi.mock("../services/index.js", () => ({
  companyLlmSettingsService: () => mockCompanyLlmSettingsService,
  logActivity: mockLogActivity,
}));

function createApp(actor: any) {
  const app = express();
  app.use(express.json());
  app.use((req, _res, next) => {
    req.actor = actor;
    next();
  });
  app.use("/api", companyLlmSettingsRoutes({} as any));
  app.use(errorHandler);
  return app;
}

describe("company llm settings routes", () => {
  let storedSettings: any;

  beforeEach(() => {
    vi.clearAllMocks();
    storedSettings = {
      llm: {
        default_provider: "vllm_openai_compatible",
        default_model: "meta-llama/Meta-Llama-3.1-8B-Instruct",
        providers: {
          vllm_openai_compatible: {
            base_url: "http://vllm:8000/v1",
            enabled: true,
          },
          openai: {
            enabled: true,
            api_key: "***REDACTED***",
          },
        },
        role_models: {},
        guardrails: {
          allowed_models: [],
          max_timeout_seconds: 120,
          role_retries: {},
        },
      },
      execution_gate: {
        mode: "always_proceed",
        scope: "major_only",
      },
    };
    mockCompanyLlmSettingsService.getForCompany.mockResolvedValue({
      companyId: "company-1",
      settings: storedSettings,
      updatedAt: new Date().toISOString(),
    });
    mockCompanyLlmSettingsService.updateForCompany.mockImplementation(async (_companyId, body) => {
      storedSettings = body;
      return {
        companyId: "company-1",
        settings: body,
        updatedAt: new Date().toISOString(),
      };
    });
    mockCompanyLlmSettingsService.testConfig.mockResolvedValue({
      provider: "vllm_openai_compatible",
      model: "meta-llama/Meta-Llama-3.1-8B-Instruct",
      probe: { status: "ok", models: ["meta-llama/Meta-Llama-3.1-8B-Instruct"] },
      modelAvailable: true,
    });
    mockCompanyLlmSettingsService.listProviders.mockReturnValue([
      { id: "vllm_openai_compatible", label: "vLLM (OpenAI-compatible)", requiresBaseUrl: true },
    ]);
    mockCompanyLlmSettingsService.listModels.mockResolvedValue({
      provider: "vllm_openai_compatible",
      status: "ok",
      models: ["meta-llama/Meta-Llama-3.1-8B-Instruct"],
    });
  });

  it("returns company llm settings with masked secrets", async () => {
    const app = createApp({
      type: "board",
      userId: "board-1",
      source: "session",
      isInstanceAdmin: false,
      companyIds: ["company-1"],
    });

    const res = await request(app).get("/api/companies/company-1/llm-settings");
    expect(res.status).toBe(200);
    expect(mockCompanyLlmSettingsService.getForCompany).toHaveBeenCalledWith("company-1");
    expect(res.body.settings.llm.providers.openai.api_key).toBe("***REDACTED***");
  });

  it("updates llm settings and writes audit activity", async () => {
    const app = createApp({
      type: "board",
      userId: "board-1",
      source: "session",
      isInstanceAdmin: false,
      companyIds: ["company-1"],
    });

    const payload = {
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
        role_models: {},
        guardrails: {
          allowed_models: [],
          max_timeout_seconds: 120,
          role_retries: {},
        },
      },
    };

    const res = await request(app).put("/api/companies/company-1/llm-settings").send(payload);
    expect(res.status).toBe(200);
    expect(mockCompanyLlmSettingsService.updateForCompany).toHaveBeenCalledWith("company-1", payload);
    expect(mockLogActivity).toHaveBeenCalledTimes(1);
  });

  it("returns validation error for malformed payload", async () => {
    const app = createApp({
      type: "board",
      userId: "board-1",
      source: "session",
      isInstanceAdmin: false,
      companyIds: ["company-1"],
    });

    const invalidPayload = {
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
            base_url: "not-a-url",
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

    const res = await request(app).put("/api/companies/company-1/llm-settings").send(invalidPayload);
    expect(res.status).toBe(400);
    expect(mockCompanyLlmSettingsService.updateForCompany).not.toHaveBeenCalled();
  });

  it("supports settings test probe endpoint", async () => {
    const app = createApp({
      type: "board",
      userId: "board-1",
      source: "session",
      isInstanceAdmin: false,
      companyIds: ["company-1"],
    });

    const res = await request(app)
      .post("/api/companies/company-1/llm-settings/test")
      .send({ provider: "vllm_openai_compatible", model: "meta-llama/Meta-Llama-3.1-8B-Instruct" });

    expect(res.status).toBe(200);
    expect(mockCompanyLlmSettingsService.testConfig).toHaveBeenCalledWith("company-1", {
      provider: "vllm_openai_compatible",
      model: "meta-llama/Meta-Llama-3.1-8B-Instruct",
    });
  });

  it("allows agent callers for their own company", async () => {
    const app = createApp({
      type: "agent",
      agentId: "agent-1",
      companyId: "company-1",
      source: "agent_key",
    });

    const res = await request(app).get("/api/companies/company-1/llm-settings");
    expect(res.status).toBe(200);
    expect(mockCompanyLlmSettingsService.getForCompany).toHaveBeenCalledWith("company-1");
  });

  it("rejects agent callers for other companies", async () => {
    const app = createApp({
      type: "agent",
      agentId: "agent-1",
      companyId: "company-1",
      source: "agent_key",
    });

    const res = await request(app).get("/api/companies/company-2/llm-settings");
    expect(res.status).toBe(403);
    expect(mockCompanyLlmSettingsService.getForCompany).not.toHaveBeenCalled();
  });

  it("supports save then fetch flow while preserving masked API keys", async () => {
    const app = createApp({
      type: "board",
      userId: "board-1",
      source: "session",
      isInstanceAdmin: false,
      companyIds: ["company-1"],
    });
    const payload = {
      execution_gate: {
        mode: "ask_before_proceed",
        scope: "every_issue",
      },
      llm: {
        default_provider: "openai",
        default_model: "gpt-4o-mini",
        providers: {
          openai: {
            enabled: true,
            api_key: "***REDACTED***",
          },
        },
        role_models: {
          scribe: {
            provider: "openai",
            model: "gpt-4.1-mini",
          },
        },
        guardrails: {
          allowed_models: ["gpt-4o-mini", "gpt-4.1-mini"],
          max_timeout_seconds: 60,
          max_tokens_per_request: 32000,
          role_retries: {
            scribe: 1,
          },
        },
      },
    };
    await request(app).put("/api/companies/company-1/llm-settings").send(payload).expect(200);
    mockCompanyLlmSettingsService.getForCompany.mockResolvedValueOnce({
      companyId: "company-1",
      settings: storedSettings,
      updatedAt: new Date().toISOString(),
    });
    const fetched = await request(app).get("/api/companies/company-1/llm-settings");
    expect(fetched.status).toBe(200);
    expect(fetched.body.settings.llm.default_provider).toBe("openai");
    expect(fetched.body.settings.llm.role_models.scribe.model).toBe("gpt-4.1-mini");
    expect(fetched.body.settings.llm.providers.openai.api_key).toBe("***REDACTED***");
    expect(JSON.stringify(fetched.body)).not.toContain("sk-");
  });
});

