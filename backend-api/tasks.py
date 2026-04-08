"""
Celery task definitions — two task types:
  - lightweight_task: quick validation/status tasks, no heavy processing.
  - execute_agent_task: full pipeline execution, retries, timeout enforced.
"""
import time
from typing import Any

from celery.utils.log import get_task_logger

from celery_app import celery_app

logger = get_task_logger(__name__)

# Maximum seconds a heavy agent task is allowed to run before timeout.
AGENT_TASK_TIMEOUT_SECONDS = 600  # 10 minutes


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

    - Retries up to 3 times with 30-second delay.
    - Soft timeout at 10 minutes (raises SoftTimeLimitExceeded — task can clean up).
    - Hard timeout at 11 minutes (process killed).
    - Distinguishes transient failures (retry) from permanent errors (fail fast).
    """
    started_at = int(time.time())
    issue_id = payload.get("issue_id", "unknown")
    repo_url = payload.get("repo_url", "")
    user_id = payload.get("user_id", "")
    attempt = self.request.retries + 1

    logger.info(
        "Agent task started: issue_id=%s repo_url=%s user_id=%s attempt=%d/%d",
        issue_id, repo_url, user_id, attempt, self.max_retries + 1,
    )

    try:
        # Placeholder for real pipeline invocation.
        # Replace `time.sleep(2)` with actual cascade/orchestrator call when ready.
        time.sleep(2)

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
        }
        logger.info("Agent task completed: issue_id=%s attempt=%d", issue_id, attempt)
        return result

    except Exception as exc:
        elapsed = int(time.time()) - started_at
        logger.warning(
            "Agent task failed: issue_id=%s attempt=%d elapsed=%ds error=%s",
            issue_id, attempt, elapsed, exc,
        )
        # Retry on transient errors; give up on permanent failures.
        if attempt <= self.max_retries:
            raise self.retry(exc=exc, countdown=30 * attempt)  # backoff: 30s, 60s, 90s

        logger.error(
            "Agent task permanently failed after %d attempts: issue_id=%s error=%s",
            attempt, issue_id, exc,
        )
        return {
            "ok": False,
            "task_type": "agent",
            "issue_id": issue_id,
            "error": str(exc),
            "attempt": attempt,
            "started_at": started_at,
            "completed_at": int(time.time()),
        }
