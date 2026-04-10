"""
Celery task definitions — two task types:
  - lightweight_task: quick validation/status tasks, no heavy processing.
  - execute_agent_task: full pipeline execution, retries, timeout enforced.
"""
import time
from typing import Any
import os
import sys
import contextlib
import io

from celery.utils.log import get_task_logger

from celery_app import celery_app

logger = get_task_logger(__name__)

def run_issue(issue_id: str, repo_url: str | None = None, paperclip_context: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Programmatic entry point for the cascade bridge, intended for use by Celery workers.
    Sets up the environment and executes the main cascade logic.
    """
    if paperclip_context:
        for k, v in paperclip_context.items():
            os.environ[k] = str(v)

    # If repo_url is provided, ensure it's in env for tools to use
    if repo_url:
        os.environ["ZERO_HUMAN_WORKSPACE_REPO_URL"] = repo_url

    # The original script relies on environment variables set by the heartbeat.
    # We maintain this behavior for compatibility but can wrap the logic here.
    try:
        # We call main() which will pull from the environment we just set/verified
        # Use a sub-process or direct call? Direct call is faster but needs env management.
        # Since main() ends with sys.exit(0), we need to handle that.
        from openclaw_bridge_cascade import main

        f = io.StringIO()
        with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
            try:
                main()
            except SystemExit as e:
                if e.code != 0:
                    return {"ok": False, "error": f"Cascade exited with code {e.code}", "logs": f.getvalue()}

        return {"ok": True, "logs": f.getvalue()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Maximum seconds a heavy agent task is allowed to run before timeout.
AGENT_TASK_TIMEOUT_SECONDS = 3600  # 60 minutes — full 4-agent cascade needs up to 40 min


# ---------------------------------------------------------------------------
# Lightweight task (quick, low-cost)
# ---------------------------------------------------------------------------

@celery_app.task(
    name="lightweight_task",
    bind=True,
    max_retries=2,
    default_retry_delay=5,
    soft_time_limit=60,
    time_limit=90,
)
def lightweight_task(self, payload: dict[str, Any]) -> dict[str, Any]:
    """
    For quick tasks: health checks, status pings, metadata refreshes.
    Retries twice on failure with 5-second delay.
    Hard-killed at 90s.
    """
    try:
        started_at = int(time.time())
        issue_id = payload.get("issue_id", "unknown")
        logger.info("Lightweight task started: issue_id=%s", issue_id)

        return {
            "ok": True,
            "task_type": "lightweight",
            "issue_id": issue_id,
            "started_at": started_at,
            "completed_at": int(time.time()),
        }
    except Exception as exc:
        logger.warning("Lightweight task failed (attempt %d): %s", self.request.retries + 1, exc)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Heavy agent task (full pipeline execution)
# ---------------------------------------------------------------------------

@celery_app.task(
    name="execute_agent_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=AGENT_TASK_TIMEOUT_SECONDS,
    time_limit=AGENT_TASK_TIMEOUT_SECONDS + 60,
)
def execute_agent_task(self, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Full agent pipeline execution task.
    Wires into the real openclaw_bridge_cascade.
    """
    import sys
    import os

    # Ensure backend-logic is in path for imports
    logic_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend-logic"))
    bridge_path = os.path.join(logic_root, "scripts", "Python_Bridges")
    if bridge_path not in sys.path:
        sys.path.insert(0, bridge_path)

    from openclaw_bridge_cascade import run_issue

    started_at = int(time.time())
    issue_id = payload.get("issue_id", "unknown")
    repo_url = payload.get("repo_url", "")
    user_id = payload.get("user_id", "")
    attempt = self.request.retries + 1

    logger.info(
        "Agent task started: issue_id=%s repo_url=%s user_id=%s attempt=%d/%d",
        issue_id, repo_url, user_id, attempt, self.max_retries + 1,
    )

    # NOTE: We intentionally do NOT reset the assignee_agent_id here.
    # The cascade bridge reads the CURRENT assignee from the DB and runs that
    # agent's phase. Resetting to Architect on every call broke the relay chain.

    # Inject the correct PAPERCLIP_AGENT_ID from payload so the bridge runs
    # as the right agent (Architect / Grunt / Pedant / Scribe).
    agent_id = payload.get("agent_id", "").strip()
    if agent_id:
        os.environ["PAPERCLIP_AGENT_ID"] = agent_id
        logger.info("Running cascade as agent_id=%s for issue_id=%s", agent_id, issue_id)

    try:
        # Execute the real cascade
        # We pass the payload metadata which may contain Paperclip context
        result_data = run_issue(
            issue_id=issue_id,
            repo_url=repo_url,
            paperclip_context=payload.get("metadata", {})
        )

        logs_output = result_data.get("logs", "")
        if "No assigned issue" in logs_output:
            raise RuntimeError("Cascade bypassed execution: No assigned issue found in DB for this agent.")

        if not result_data.get("ok"):
            raise RuntimeError(result_data.get("error", "Unknown cascade error"))

        result = {
            "ok": True,
            "task_type": "agent",
            "message": "Task executed successfully",
            "issue_id": issue_id,
            "repo_url": repo_url,
            "user_id": user_id,
            "attempt": attempt,
            "started_at": started_at,
            "completed_at": int(time.time()),
            "logs_summary": result_data.get("logs", "")[-1000:]
        }
        logger.info("Agent task completed: issue_id=%s attempt=%d", issue_id, attempt)
        return result

    except Exception as exc:
        elapsed = int(time.time()) - started_at
        logger.warning(
            "Agent task failed: issue_id=%s attempt=%d elapsed=%ds error=%s",
            issue_id, attempt, elapsed, exc,
        )
        if attempt <= self.max_retries:
            raise self.retry(exc=exc, countdown=30 * attempt)

        return {
            "ok": False,
            "task_type": "agent",
            "issue_id": issue_id,
            "error": str(exc),
            "attempt": attempt,
            "started_at": started_at,
            "completed_at": int(time.time()),
        }
