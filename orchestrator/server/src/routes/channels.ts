import { Router } from "express";
import type { Db } from "@paperclipai/db";
import {
  createNotificationChannelSchema,
  saveNotificationChannelMappingsSchema,
  testDraftNotificationChannelSchema,
  testNotificationChannelSchema,
  updateNotificationChannelSchema,
} from "@paperclipai/shared";
import { validate } from "../middleware/validate.js";
import { channelService, logActivity } from "../services/index.js";
import { assertBoard, assertCompanyAccess, getActorInfo } from "./authz.js";

export function channelRoutes(db: Db) {
  const router = Router();
  const svc = channelService(db);

  router.get("/companies/:companyId/channels", async (req, res) => {
    assertBoard(req);
    const companyId = req.params.companyId as string;
    assertCompanyAccess(req, companyId);
    const channels = await svc.list(companyId);
    res.json(channels);
  });

  router.get("/companies/:companyId/channels/:channelId", async (req, res) => {
    assertBoard(req);
    const companyId = req.params.companyId as string;
    const channelId = req.params.channelId as string;
    assertCompanyAccess(req, companyId);
    const channel = await svc.getById(companyId, channelId);
    if (!channel) {
      res.status(404).json({ error: "Channel not found" });
      return;
    }
    res.json(channel);
  });

  router.post("/companies/:companyId/channels", validate(createNotificationChannelSchema), async (req, res) => {
    assertBoard(req);
    const companyId = req.params.companyId as string;
    assertCompanyAccess(req, companyId);
    const channel = await svc.create(companyId, req.body, {
      userId: req.actor.userId ?? "board",
    });
    const actor = getActorInfo(req);
    await logActivity(db, {
      companyId,
      actorType: actor.actorType,
      actorId: actor.actorId,
      agentId: actor.agentId,
      runId: actor.runId,
      action: "channel.created",
      entityType: "notification_channel",
      entityId: channel.id,
      details: {
        provider: channel.provider,
        name: channel.name,
      },
    });
    res.status(201).json(channel);
  });

  router.patch(
    "/companies/:companyId/channels/:channelId",
    validate(updateNotificationChannelSchema),
    async (req, res) => {
      assertBoard(req);
      const companyId = req.params.companyId as string;
      const channelId = req.params.channelId as string;
      assertCompanyAccess(req, companyId);
      const channel = await svc.update(companyId, channelId, req.body, {
        userId: req.actor.userId ?? "board",
      });
      const actor = getActorInfo(req);
      await logActivity(db, {
        companyId,
        actorType: actor.actorType,
        actorId: actor.actorId,
        agentId: actor.agentId,
        runId: actor.runId,
        action: "channel.updated",
        entityType: "notification_channel",
        entityId: channel.id,
        details: {
          provider: channel.provider,
          name: channel.name,
          isEnabled: channel.isEnabled,
        },
      });
      res.json(channel);
    },
  );

  router.delete("/companies/:companyId/channels/:channelId", async (req, res) => {
    assertBoard(req);
    const companyId = req.params.companyId as string;
    const channelId = req.params.channelId as string;
    assertCompanyAccess(req, companyId);
    const removed = await svc.remove(companyId, channelId);
    if (!removed) {
      res.status(404).json({ error: "Channel not found" });
      return;
    }
    const actor = getActorInfo(req);
    await logActivity(db, {
      companyId,
      actorType: actor.actorType,
      actorId: actor.actorId,
      agentId: actor.agentId,
      runId: actor.runId,
      action: "channel.deleted",
      entityType: "notification_channel",
      entityId: removed.id,
      details: {
        provider: removed.provider,
        name: removed.name,
      },
    });
    res.json({ ok: true });
  });

  router.post("/companies/:companyId/channels/:channelId/enable", async (req, res) => {
    assertBoard(req);
    const companyId = req.params.companyId as string;
    const channelId = req.params.channelId as string;
    assertCompanyAccess(req, companyId);
    const updated = await svc.setEnabled(companyId, channelId, true);
    res.json(updated);
  });

  router.post("/companies/:companyId/channels/:channelId/disable", async (req, res) => {
    assertBoard(req);
    const companyId = req.params.companyId as string;
    const channelId = req.params.channelId as string;
    assertCompanyAccess(req, companyId);
    const updated = await svc.setEnabled(companyId, channelId, false);
    res.json(updated);
  });

  router.post(
    "/companies/:companyId/channels/:channelId/test",
    validate(testNotificationChannelSchema),
    async (req, res) => {
      assertBoard(req);
      const companyId = req.params.companyId as string;
      const channelId = req.params.channelId as string;
      assertCompanyAccess(req, companyId);
      const result = await svc.testSaved(companyId, channelId, {
        message: req.body.message,
      }, { userId: req.actor.userId ?? "board" });
      res.json(result);
    },
  );

  router.post(
    "/companies/:companyId/channels/test",
    validate(testDraftNotificationChannelSchema),
    async (req, res) => {
      assertBoard(req);
      const companyId = req.params.companyId as string;
      assertCompanyAccess(req, companyId);
      const result = await svc.testDraft(companyId, req.body, { userId: req.actor.userId ?? "board" });
      res.json(result);
    },
  );

  router.get("/companies/:companyId/channels/:channelId/mappings", async (req, res) => {
    assertBoard(req);
    const companyId = req.params.companyId as string;
    const channelId = req.params.channelId as string;
    assertCompanyAccess(req, companyId);
    const mappings = await svc.listMappings(companyId, channelId);
    res.json(mappings);
  });

  router.put(
    "/companies/:companyId/channels/:channelId/mappings",
    validate(saveNotificationChannelMappingsSchema),
    async (req, res) => {
      assertBoard(req);
      const companyId = req.params.companyId as string;
      const channelId = req.params.channelId as string;
      assertCompanyAccess(req, companyId);
      const mappings = await svc.saveMappings(companyId, channelId, req.body);
      const actor = getActorInfo(req);
      await logActivity(db, {
        companyId,
        actorType: actor.actorType,
        actorId: actor.actorId,
        agentId: actor.agentId,
        runId: actor.runId,
        action: "channel.mappings.updated",
        entityType: "notification_channel",
        entityId: channelId,
        details: {
          mappingsCount: mappings.length,
          enabledCount: mappings.filter((mapping) => mapping.isEnabled).length,
        },
      });
      res.json(mappings);
    },
  );

  router.get("/companies/:companyId/channels/:channelId/deliveries", async (req, res) => {
    assertBoard(req);
    const companyId = req.params.companyId as string;
    const channelId = req.params.channelId as string;
    assertCompanyAccess(req, companyId);
    const limitRaw = req.query.limit;
    const limit = typeof limitRaw === "string" ? Number.parseInt(limitRaw, 10) : undefined;
    const deliveries = await svc.listRecentDeliveries(companyId, channelId, limit);
    res.json(deliveries);
  });

  return router;
}
