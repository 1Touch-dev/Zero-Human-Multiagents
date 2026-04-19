import { and, eq, gte, sql } from "drizzle-orm";
import type { Db } from "@paperclipai/db";
import { agents, approvals, companies, companyLlmSettings, costEvents, heartbeatRuns, issues } from "@paperclipai/db";
import { notFound } from "../errors.js";
import { budgetService } from "./budgets.js";

export function dashboardService(db: Db) {
  const budgets = budgetService(db);
  return {
    summary: async (companyId: string) => {
      const company = await db
        .select()
        .from(companies)
        .where(eq(companies.id, companyId))
        .then((rows) => rows[0] ?? null);

      if (!company) throw notFound("Company not found");

      const agentRows = await db
        .select({ status: agents.status, count: sql<number>`count(*)` })
        .from(agents)
        .where(eq(agents.companyId, companyId))
        .groupBy(agents.status);

      const taskRows = await db
        .select({ status: issues.status, count: sql<number>`count(*)` })
        .from(issues)
        .where(eq(issues.companyId, companyId))
        .groupBy(issues.status);

      const pendingApprovals = await db
        .select({ count: sql<number>`count(*)` })
        .from(approvals)
        .where(and(eq(approvals.companyId, companyId), eq(approvals.status, "pending")))
        .then((rows) => Number(rows[0]?.count ?? 0));

      const agentCounts: Record<string, number> = {
        active: 0,
        running: 0,
        paused: 0,
        error: 0,
      };
      for (const row of agentRows) {
        const count = Number(row.count);
        // "idle" agents are operational — count them as active
        const bucket = row.status === "idle" ? "active" : row.status;
        agentCounts[bucket] = (agentCounts[bucket] ?? 0) + count;
      }

      const taskCounts: Record<string, number> = {
        open: 0,
        inProgress: 0,
        blocked: 0,
        done: 0,
      };
      for (const row of taskRows) {
        const count = Number(row.count);
        if (row.status === "in_progress") taskCounts.inProgress += count;
        if (row.status === "blocked") taskCounts.blocked += count;
        if (row.status === "done") taskCounts.done += count;
        if (row.status !== "done" && row.status !== "cancelled") taskCounts.open += count;
      }

      const now = new Date();
      const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
      const [{ monthSpend }] = await db
        .select({
          monthSpend: sql<number>`coalesce(sum(${costEvents.costCents}), 0)::int`,
        })
        .from(costEvents)
        .where(
          and(
            eq(costEvents.companyId, companyId),
            gte(costEvents.occurredAt, monthStart),
          ),
        );

      const monthSpendCents = Number(monthSpend);
      const utilization =
        company.budgetMonthlyCents > 0
          ? (monthSpendCents / company.budgetMonthlyCents) * 100
          : 0;
      const budgetOverview = await budgets.overview(companyId);

      const window24h = new Date(Date.now() - 24 * 60 * 60 * 1000);
      const window30d = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
      const llmRunAggregateRows = await db
        .select({
          requests: sql<number>`count(*)::int`,
          errors: sql<number>`count(*) filter (where ${heartbeatRuns.status} in ('failed', 'timed_out', 'cancelled'))::int`,
          p50_latency_ms: sql<number | null>`percentile_cont(0.5) within group (
            order by greatest(
              0,
              extract(epoch from (
                coalesce(${heartbeatRuns.finishedAt}, ${heartbeatRuns.updatedAt}, now()) - coalesce(${heartbeatRuns.startedAt}, ${heartbeatRuns.createdAt})
              )) * 1000
            )
          )::int`,
          p95_latency_ms: sql<number | null>`percentile_cont(0.95) within group (
            order by greatest(
              0,
              extract(epoch from (
                coalesce(${heartbeatRuns.finishedAt}, ${heartbeatRuns.updatedAt}, now()) - coalesce(${heartbeatRuns.startedAt}, ${heartbeatRuns.createdAt})
              )) * 1000
            )
          )::int`,
        })
        .from(heartbeatRuns)
        .where(and(eq(heartbeatRuns.companyId, companyId), gte(heartbeatRuns.createdAt, window24h)));
      const llmRunAggregateRow = llmRunAggregateRows[0] ?? null;
      const requests24h = Number(llmRunAggregateRow?.requests ?? 0);
      const errors24h = Number(llmRunAggregateRow?.errors ?? 0);
      const errorRatePercent24h = requests24h > 0 ? Number(((errors24h / requests24h) * 100).toFixed(2)) : 0;
      const p50LatencyMs24h = Number(llmRunAggregateRow?.p50_latency_ms ?? 0);
      const p95LatencyMs24h = Number(llmRunAggregateRow?.p95_latency_ms ?? 0);

      const byProviderModelRoleRows = await db
        .select({
          provider: sql<string>`coalesce(${costEvents.provider}, 'unknown')::text`,
          model: sql<string>`coalesce(${costEvents.model}, 'unknown')::text`,
          role: sql<string>`coalesce(${agents.role}, 'unknown')::text`,
          requests: sql<number>`count(distinct ${costEvents.heartbeatRunId})::int`,
          errors: sql<number>`count(distinct ${heartbeatRuns.id}) filter (where ${heartbeatRuns.status} in ('failed', 'timed_out', 'cancelled'))::int`,
          p50_latency_ms: sql<number | null>`percentile_cont(0.5) within group (
            order by greatest(
              0,
              extract(epoch from (
                coalesce(${heartbeatRuns.finishedAt}, ${heartbeatRuns.updatedAt}, now()) - coalesce(${heartbeatRuns.startedAt}, ${heartbeatRuns.createdAt})
              )) * 1000
            )
          )::int`,
          p95_latency_ms: sql<number | null>`percentile_cont(0.95) within group (
            order by greatest(
              0,
              extract(epoch from (
                coalesce(${heartbeatRuns.finishedAt}, ${heartbeatRuns.updatedAt}, now()) - coalesce(${heartbeatRuns.startedAt}, ${heartbeatRuns.createdAt})
              )) * 1000
            )
          )::int`,
          input_tokens: sql<number>`coalesce(sum(${costEvents.inputTokens}), 0)::int`,
          cached_input_tokens: sql<number>`coalesce(sum(${costEvents.cachedInputTokens}), 0)::int`,
          output_tokens: sql<number>`coalesce(sum(${costEvents.outputTokens}), 0)::int`,
          cost_cents: sql<number>`coalesce(sum(${costEvents.costCents}), 0)::int`,
        })
        .from(costEvents)
        .leftJoin(agents, eq(agents.id, costEvents.agentId))
        .leftJoin(heartbeatRuns, eq(heartbeatRuns.id, costEvents.heartbeatRunId))
        .where(and(eq(costEvents.companyId, companyId), gte(costEvents.occurredAt, window24h)))
        .groupBy(
          sql`coalesce(${costEvents.provider}, 'unknown')::text`,
          sql`coalesce(${costEvents.model}, 'unknown')::text`,
          sql`coalesce(${agents.role}, 'unknown')::text`,
        )
        .orderBy(sql`coalesce(sum(${costEvents.costCents}), 0)::int desc`)
        .limit(50);

      const approvalFunnelRows = await db
        .select({
          status: approvals.status,
          count: sql<number>`count(*)::int`,
        })
        .from(approvals)
        .where(and(eq(approvals.companyId, companyId), gte(approvals.createdAt, window30d)))
        .groupBy(approvals.status);

      const approvalFunnel = {
        requested: 0,
        approved: 0,
        rejected: 0,
        revisionRequested: 0,
        pending: 0,
      };
      for (const row of approvalFunnelRows) {
        const count = Number(row.count ?? 0);
        if (row.status === "approved") approvalFunnel.approved += count;
        else if (row.status === "rejected") approvalFunnel.rejected += count;
        else if (row.status === "revision_requested") approvalFunnel.revisionRequested += count;
        else if (row.status === "pending") approvalFunnel.pending += count;
      }
      approvalFunnel.requested =
        approvalFunnel.approved + approvalFunnel.rejected + approvalFunnel.revisionRequested + approvalFunnel.pending;

      const settingsRow = await db
        .select({ settingsJson: companyLlmSettings.settingsJson })
        .from(companyLlmSettings)
        .where(eq(companyLlmSettings.companyId, companyId))
        .then((rows) => rows[0] ?? null);
      const defaultProviderRaw = ((settingsRow?.settingsJson as Record<string, unknown> | null)?.llm as Record<string, unknown> | undefined)?.default_provider;
      const defaultProvider = typeof defaultProviderRaw === "string" ? defaultProviderRaw : "vllm_openai_compatible";
      const vllmRows = byProviderModelRoleRows.filter((row) => row.provider === "vllm_openai_compatible");
      const vllmRequests = vllmRows.reduce((sum, row) => sum + Number(row.requests ?? 0), 0);
      const nonDefaultRequests = byProviderModelRoleRows
        .filter((row) => row.provider !== defaultProvider)
        .reduce((sum, row) => sum + Number(row.requests ?? 0), 0);
      const fallbackActivations24h = nonDefaultRequests;
      const vllmUnavailableTriggered = defaultProvider === "vllm_openai_compatible" && requests24h > 0 && vllmRequests === 0;
      const errorSpikeTriggered = errorRatePercent24h >= Number(process.env.LLM_ALERT_ERROR_SPIKE_PERCENT ?? 15);
      const fallbackRepeatedTriggered = fallbackActivations24h >= Number(process.env.LLM_ALERT_FALLBACK_REPEAT_COUNT ?? 5);

      return {
        companyId,
        agents: {
          active: agentCounts.active,
          running: agentCounts.running,
          paused: agentCounts.paused,
          error: agentCounts.error,
        },
        tasks: taskCounts,
        costs: {
          monthSpendCents,
          monthBudgetCents: company.budgetMonthlyCents,
          monthUtilizationPercent: Number(utilization.toFixed(2)),
        },
        pendingApprovals,
        budgets: {
          activeIncidents: budgetOverview.activeIncidents.length,
          pendingApprovals: budgetOverview.pendingApprovalCount,
          pausedAgents: budgetOverview.pausedAgentCount,
          pausedProjects: budgetOverview.pausedProjectCount,
        },
        llmObservability: {
          requests24h,
          errors24h,
          errorRatePercent24h,
          p50LatencyMs24h,
          p95LatencyMs24h,
          fallbackActivations24h,
          byProviderModelRole24h: byProviderModelRoleRows.map((row) => ({
            provider: row.provider ?? "unknown",
            model: row.model ?? "unknown",
            role: row.role ?? "unknown",
            requests: Number(row.requests ?? 0),
            errors: Number(row.errors ?? 0),
            p50LatencyMs: Number(row.p50_latency_ms ?? 0),
            p95LatencyMs: Number(row.p95_latency_ms ?? 0),
            inputTokens: Number(row.input_tokens ?? 0),
            cachedInputTokens: Number(row.cached_input_tokens ?? 0),
            outputTokens: Number(row.output_tokens ?? 0),
            costCents: Number(row.cost_cents ?? 0),
          })),
          approvalFunnel30d: approvalFunnel,
          alerts: [
            {
              key: "vllm_unavailable" as const,
              triggered: vllmUnavailableTriggered,
              severity: "critical" as const,
              threshold: "default_provider=vllm and vllm requests in 24h = 0",
              value: `default_provider=${defaultProvider}, vllm_requests=${vllmRequests}, total_requests=${requests24h}`,
            },
            {
              key: "error_spike" as const,
              triggered: errorSpikeTriggered,
              severity: "warning" as const,
              threshold: `error_rate_percent >= ${process.env.LLM_ALERT_ERROR_SPIKE_PERCENT ?? 15}`,
              value: `${errorRatePercent24h}%`,
            },
            {
              key: "fallback_activated_repeatedly" as const,
              triggered: fallbackRepeatedTriggered,
              severity: "warning" as const,
              threshold: `fallback_count_24h >= ${process.env.LLM_ALERT_FALLBACK_REPEAT_COUNT ?? 5}`,
              value: String(fallbackActivations24h),
            },
          ],
        },
      };
    },
  };
}
