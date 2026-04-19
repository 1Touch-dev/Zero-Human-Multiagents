export interface DashboardSummary {
  companyId: string;
  agents: {
    active: number;
    running: number;
    paused: number;
    error: number;
  };
  tasks: {
    open: number;
    inProgress: number;
    blocked: number;
    done: number;
  };
  costs: {
    monthSpendCents: number;
    monthBudgetCents: number;
    monthUtilizationPercent: number;
  };
  pendingApprovals: number;
  budgets: {
    activeIncidents: number;
    pendingApprovals: number;
    pausedAgents: number;
    pausedProjects: number;
  };
  llmObservability?: {
    requests24h: number;
    errors24h: number;
    errorRatePercent24h: number;
    p50LatencyMs24h: number;
    p95LatencyMs24h: number;
    fallbackActivations24h: number;
    byProviderModelRole24h: Array<{
      provider: string;
      model: string;
      role: string;
      requests: number;
      errors: number;
      p50LatencyMs: number;
      p95LatencyMs: number;
      inputTokens: number;
      cachedInputTokens: number;
      outputTokens: number;
      costCents: number;
    }>;
    approvalFunnel30d: {
      requested: number;
      approved: number;
      rejected: number;
      revisionRequested: number;
      pending: number;
    };
    alerts: Array<{
      key: "vllm_unavailable" | "error_spike" | "fallback_activated_repeatedly";
      triggered: boolean;
      severity: "warning" | "critical";
      threshold: string;
      value: string;
    }>;
  };
}
