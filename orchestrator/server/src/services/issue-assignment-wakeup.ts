import { logger } from "../middleware/logger.js";

type WakeupTriggerDetail = "manual" | "ping" | "callback" | "system";
type WakeupSource = "timer" | "assignment" | "on_demand" | "automation";

export interface IssueAssignmentWakeupDeps {
  wakeup: (
    agentId: string,
    opts: {
      source?: WakeupSource;
      triggerDetail?: WakeupTriggerDetail;
      reason?: string | null;
      payload?: Record<string, unknown> | null;
      requestedByActorType?: "user" | "agent" | "system";
      requestedByActorId?: string | null;
      contextSnapshot?: Record<string, unknown>;
    },
  ) => Promise<unknown>;
}

export function queueIssueAssignmentWakeup(input: {
  heartbeat: IssueAssignmentWakeupDeps;
  issue: { id: string; assigneeAgentId: string | null; status: string };
  reason: string;
  mutation: string;
  contextSource: string;
  requestedByActorType?: "user" | "agent" | "system";
  requestedByActorId?: string | null;
  rethrowOnError?: boolean;
}) {
  if (!input.issue.assigneeAgentId || input.issue.status === "backlog") return;

  return input.heartbeat
    .wakeup(input.issue.assigneeAgentId, {
      source: "assignment",
      triggerDetail: "system",
      reason: input.reason,
      payload: { issueId: input.issue.id, mutation: input.mutation },
      requestedByActorType: input.requestedByActorType,
      requestedByActorId: input.requestedByActorId ?? null,
      contextSnapshot: { issueId: input.issue.id, source: input.contextSource },
    })
    .catch((err) => {
      logger.warn({ err, issueId: input.issue.id }, "failed to wake assignee on issue assignment");
      if (input.rethrowOnError) throw err;
      return null;
    });
}

type AgentListEntry = { id: string; status: string };

/**
 * After a human gate clears (execution preview approved, or generic approval approved),
 * ensure at least one agent is nudged to resume work:
 * - wake assignee when present
 * - else wake the agent that requested approval (if any)
 * - else wake all non-pending agents in the company (unassigned backlog pickup)
 */
export function wakeAgentsAfterHumanGateClears(input: {
  heartbeat: IssueAssignmentWakeupDeps;
  agentsSvc: { list: (companyId: string) => Promise<AgentListEntry[]> };
  issue: { id: string; companyId: string; assigneeAgentId: string | null; status: string };
  approval: { id: string; requestedByAgentId: string | null };
  mutation: string;
  contextSource: string;
  requestedByActorType?: "user" | "agent" | "system" | "board";
  requestedByActorId?: string | null;
  /** Set when `/approvals/:id/approve` already wakes `requestedByAgentId` once for the whole approval */
  skipRequesterWake?: boolean;
}): void {
  void queueIssueAssignmentWakeup({
    heartbeat: input.heartbeat,
    issue: input.issue,
    reason: "approval_approved",
    mutation: input.mutation,
    contextSource: input.contextSource,
    requestedByActorType:
      input.requestedByActorType === "board" ? "system" : input.requestedByActorType,
    requestedByActorId: input.requestedByActorId ?? null,
  });

  const woken = new Set<string>();
  if (input.issue.assigneeAgentId) {
    woken.add(input.issue.assigneeAgentId);
  }

  const requesterId = input.skipRequesterWake ? null : input.approval.requestedByAgentId;
  if (requesterId && !woken.has(requesterId)) {
    void input.heartbeat
      .wakeup(requesterId, {
        source: "automation",
        triggerDetail: "system",
        reason: "approval_approved",
        payload: {
          approvalId: input.approval.id,
          issueId: input.issue.id,
        },
        requestedByActorType:
          input.requestedByActorType === "board" ? "system" : input.requestedByActorType,
        requestedByActorId: input.requestedByActorId ?? null,
        contextSnapshot: {
          source: input.contextSource,
          approvalId: input.approval.id,
          issueId: input.issue.id,
          wakeReason: "approval_approved",
        },
      })
      .catch((err) => {
        logger.warn(
          { err, issueId: input.issue.id, agentId: requesterId },
          "failed to wake approval requester after human gate",
        );
      });
    woken.add(requesterId);
  }

  if (woken.size > 0) return;

  void input.agentsSvc
    .list(input.issue.companyId)
    .then((roster) => {
      for (const agent of roster) {
        if (agent.status === "pending_approval") continue;
        void input.heartbeat
          .wakeup(agent.id, {
            source: "automation",
            triggerDetail: "system",
            reason: "execution_gate_cleared_unassigned",
            payload: {
              issueId: input.issue.id,
              approvalId: input.approval.id,
            },
            requestedByActorType:
              input.requestedByActorType === "board" ? "system" : input.requestedByActorType,
            requestedByActorId: input.requestedByActorId ?? null,
            contextSnapshot: {
              source: input.contextSource,
              issueId: input.issue.id,
              wakeReason: "execution_gate_cleared",
            },
          })
          .catch((err) => {
            logger.warn(
              { err, issueId: input.issue.id, agentId: agent.id },
              "failed roster wake after human gate",
            );
          });
      }
    })
    .catch((err) => {
      logger.warn({ err, issueId: input.issue.id }, "failed to list agents for roster wake");
    });
}
