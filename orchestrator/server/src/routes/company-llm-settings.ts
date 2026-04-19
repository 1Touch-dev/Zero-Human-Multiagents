import { Router } from "express";
import type { Db } from "@paperclipai/db";
import {
  listLlmModelsQuerySchema,
  testCompanyLlmSettingsSchema,
  updateCompanyLlmSettingsSchema,
} from "@paperclipai/shared";
import { validate } from "../middleware/validate.js";
import { assertBoard, assertCompanyAccess, getActorInfo } from "./authz.js";
import { companyLlmSettingsService, logActivity } from "../services/index.js";

export function companyLlmSettingsRoutes(db: Db) {
  const router = Router();
  const svc = companyLlmSettingsService(db);

  router.get("/companies/:companyId/llm-settings", async (req, res) => {
    const companyId = req.params.companyId as string;
    assertCompanyAccess(req, companyId);
    const data = await svc.getForCompany(companyId);
    res.json(data);
  });

  router.put("/companies/:companyId/llm-settings", validate(updateCompanyLlmSettingsSchema), async (req, res) => {
    assertBoard(req);
    const companyId = req.params.companyId as string;
    assertCompanyAccess(req, companyId);
    const updated = await svc.updateForCompany(companyId, req.body);
    const actor = getActorInfo(req);
    await logActivity(db, {
      companyId,
      actorType: actor.actorType,
      actorId: actor.actorId,
      agentId: actor.agentId,
      runId: actor.runId,
      action: "company.llm_settings_updated",
      entityType: "company",
      entityId: companyId,
      details: {
        defaultProvider: updated.settings.llm.default_provider,
        defaultModel: updated.settings.llm.default_model,
        changedAt: updated.updatedAt,
      },
    });
    res.json(updated);
  });

  router.post("/companies/:companyId/llm-settings/test", validate(testCompanyLlmSettingsSchema), async (req, res) => {
    assertBoard(req);
    const companyId = req.params.companyId as string;
    assertCompanyAccess(req, companyId);
    const result = await svc.testConfig(companyId, req.body);
    res.json(result);
  });

  router.get("/llm/providers", async (req, res) => {
    assertBoard(req);
    res.json(svc.listProviders());
  });

  router.get("/llm/models", async (req, res) => {
    assertBoard(req);
    const parsed = listLlmModelsQuerySchema.parse(req.query);
    const models = await svc.listModels(parsed);
    res.json(models);
  });

  return router;
}

