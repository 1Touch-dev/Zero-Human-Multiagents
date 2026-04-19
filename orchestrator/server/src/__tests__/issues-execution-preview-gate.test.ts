import express from "express";
import request from "supertest";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { issueRoutes } from "../routes/issues.js";
import { errorHandler } from "../middleware/index.js";

const mockIssueService = vi.hoisted(() => ({
  create: vi.fn(),
  update: vi.fn(),
  getById: vi.fn(),
  getByIdentifier: vi.fn(),
}));
const mockApprovalService = vi.hoisted(() => ({
  create: vi.fn(),
  approve: vi.fn(),
  reject: vi.fn(),
  requestRevision: vi.fn(),
}));
const mockIssueApprovalService = vi.hoisted(() => ({
  link: vi.fn(),
  listApprovalsForIssue: vi.fn(),
}));
const mockCompanyLlmSettingsService = vi.hoisted(() => ({
  getForCompany: vi.fn(),
}));
const mockHeartbeatService = vi.hoisted(() => ({
  wakeup: vi.fn(),
}));
const mockLogActivity = vi.hoisted(() => vi.fn(async () => undefined));
const mockQueueIssueAssignmentWakeup = vi.hoisted(() => vi.fn());
const mockWakeAgentsAfterHumanGateClears = vi.hoisted(() => vi.fn());

vi.mock("../services/issue-assignment-wakeup.js", () => ({
  queueIssueAssignmentWakeup: mockQueueIssueAssignmentWakeup,
  wakeAgentsAfterHumanGateClears: mockWakeAgentsAfterHumanGateClears,
}));

vi.mock("../services/index.js", () => ({
  accessService: () => ({ canUser: vi.fn(), hasPermission: vi.fn() }),
  agentService: () => ({ getById: vi.fn(), list: vi.fn().mockResolvedValue([]) }),
  approvalService: () => mockApprovalService,
  companyLlmSettingsService: () => mockCompanyLlmSettingsService,
  documentService: () => ({}),
  executionWorkspaceService: () => ({}),
  goalService: () => ({}),
  heartbeatService: () => mockHeartbeatService,
  issueApprovalService: () => mockIssueApprovalService,
  issueService: () => mockIssueService,
  logActivity: mockLogActivity,
  projectService: () => ({}),
  routineService: () => ({ syncRunStatusForIssue: vi.fn(async () => undefined) }),
  workProductService: () => ({}),
}));

function createApp() {
  const app = express();
  app.use(express.json());
  app.use((req, _res, next) => {
    (req as any).actor = {
      type: "board",
      userId: "board-1",
      source: "session",
      companyIds: ["company-1"],
      isInstanceAdmin: false,
    };
    next();
  });
  app.use("/api", issueRoutes({} as any, {} as any));
  app.use(errorHandler);
  return app;
}

describe("issues execution preview gate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIssueService.create.mockResolvedValue({
      id: "issue-1",
      companyId: "company-1",
      identifier: "PAP-100",
      title: "Deploy production feature",
      description: "Deploy config to production",
      status: "todo",
    });
    mockIssueService.update.mockImplementation(async (_id: string, patch: Record<string, unknown>) => ({
      id: "issue-1",
      companyId: "company-1",
      identifier: "PAP-100",
      title: "Deploy production feature",
      description: "Deploy config to production",
      assigneeAgentId: null,
      status: (patch.status as string) ?? "todo",
    }));
    mockIssueService.getById.mockResolvedValue({
      id: "issue-1",
      companyId: "company-1",
      identifier: "PAP-100",
      title: "Deploy production feature",
      description: "Deploy config to production",
      status: "awaiting_human_approval",
    });
    mockIssueService.getByIdentifier.mockResolvedValue(null);
    mockApprovalService.create.mockResolvedValue({
      id: "approval-1",
      status: "pending",
    });
    mockApprovalService.approve.mockResolvedValue({
      applied: true,
      approval: {
        id: "approval-1",
        status: "approved",
        requestedByAgentId: null,
      },
    });
    mockIssueApprovalService.listApprovalsForIssue.mockResolvedValue([
      {
        id: "approval-1",
        type: "ask_before_proceed_execution",
        status: "pending",
        payload: {
          execution_preview: {
            rolePlan: [],
            plannedActions: [],
            majorCategories: ["deploy_prod_config_change"],
          },
        },
      },
    ]);
    mockCompanyLlmSettingsService.getForCompany.mockResolvedValue({
      companyId: "company-1",
      settings: {
        execution_gate: {
          mode: "ask_before_proceed",
          scope: "every_issue",
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
      },
      updatedAt: new Date().toISOString(),
    });
  });

  it("blocks execution at issue creation in ask-before-proceed mode", async () => {
    const app = createApp();
    const res = await request(app)
      .post("/api/companies/company-1/issues")
      .send({ title: "Deploy production feature", description: "Deploy config to production" });
    expect(res.status).toBe(201);
    expect(mockApprovalService.create).toHaveBeenCalledTimes(1);
    expect(mockIssueApprovalService.link).toHaveBeenCalledWith(
      "issue-1",
      "approval-1",
      expect.any(Object),
    );
    expect(mockIssueService.update).toHaveBeenCalledWith("issue-1", { status: "awaiting_human_approval" });
    expect(mockQueueIssueAssignmentWakeup).not.toHaveBeenCalled();
  });

  it("resumes execution only after approval decision", async () => {
    const app = createApp();
    const res = await request(app)
      .post("/api/issues/issue-1/execution-preview/decision")
      .send({ decision: "approve", note: "Looks good" });
    expect(res.status).toBe(200);
    expect(mockApprovalService.approve).toHaveBeenCalledWith("approval-1", "board-1", "Looks good");
    expect(mockIssueService.update).toHaveBeenCalledWith("issue-1", { status: "todo" });
    expect(mockWakeAgentsAfterHumanGateClears).toHaveBeenCalledTimes(1);
  });
});
