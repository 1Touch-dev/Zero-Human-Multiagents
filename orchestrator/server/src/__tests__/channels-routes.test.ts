import express from "express";
import request from "supertest";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { channelRoutes } from "../routes/channels.js";
import { errorHandler } from "../middleware/index.js";

const mockChannelService = vi.hoisted(() => ({
  list: vi.fn(),
  getById: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  setEnabled: vi.fn(),
  testSaved: vi.fn(),
  testDraft: vi.fn(),
}));

const mockLogActivity = vi.hoisted(() => vi.fn());

vi.mock("../services/index.js", () => ({
  channelService: () => mockChannelService,
  logActivity: mockLogActivity,
}));

function createApp(actor: Record<string, unknown>) {
  const app = express();
  app.use(express.json());
  app.use((req, _res, next) => {
    (req as any).actor = actor;
    next();
  });
  app.use("/api", channelRoutes({} as any));
  app.use(errorHandler);
  return app;
}

describe("channel routes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockChannelService.list.mockResolvedValue([]);
  });

  it("lists channels for board users", async () => {
    const app = createApp({
      type: "board",
      userId: "user-1",
      source: "local_implicit",
      isInstanceAdmin: true,
      companyIds: ["company-1"],
    });

    const res = await request(app).get("/api/companies/company-1/channels");

    expect(res.status).toBe(200);
    expect(res.body).toEqual([]);
    expect(mockChannelService.list).toHaveBeenCalledWith("company-1");
  });

  it("validates channel creation payload", async () => {
    const app = createApp({
      type: "board",
      userId: "user-1",
      source: "local_implicit",
      isInstanceAdmin: true,
      companyIds: ["company-1"],
    });

    const res = await request(app)
      .post("/api/companies/company-1/channels")
      .send({
        name: "Ops",
        provider: "telegram",
        config: {
          provider: "telegram",
          chatId: "abc",
          botToken: "bad",
        },
      });

    expect(res.status).toBe(400);
    expect(res.body.error).toBe("Validation error");
    expect(mockChannelService.create).not.toHaveBeenCalled();
  });

  it("creates channels with valid payload", async () => {
    mockChannelService.create.mockResolvedValue({
      id: "channel-1",
      companyId: "company-1",
      name: "Ops Alerts",
      provider: "telegram",
      isEnabled: true,
      settings: { chatId: "-1001234567890" },
      hasToken: true,
      tokenMasked: "********",
      lastTestedAt: null,
      lastTestStatus: null,
      lastTestMessage: null,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });

    const app = createApp({
      type: "board",
      userId: "user-1",
      source: "local_implicit",
      isInstanceAdmin: true,
      companyIds: ["company-1"],
    });

    const payload = {
      name: "Ops Alerts",
      provider: "telegram",
      config: {
        provider: "telegram",
        chatId: "-1001234567890",
        botToken: "123456789:abcdefghijklmnopqrstuvwxyz12345",
      },
      isEnabled: true,
    };

    const res = await request(app)
      .post("/api/companies/company-1/channels")
      .send(payload);

    expect(res.status).toBe(201);
    expect(mockChannelService.create).toHaveBeenCalledWith(
      "company-1",
      payload,
      { userId: "user-1" },
    );
    expect(mockLogActivity).toHaveBeenCalledTimes(1);
  });
});
