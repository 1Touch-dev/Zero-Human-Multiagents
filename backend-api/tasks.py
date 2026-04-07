import time
from typing import Any

from celery.utils.log import get_task_logger

from celery_app import celery_app


logger = get_task_logger(__name__)


@celery_app.task(name="execute_agent_task")
def execute_agent_task(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Minimal async task placeholder for the orchestrator pipeline.
    This intentionally does no external side effects yet.
    """
    started_at = int(time.time())
    issue_id = payload.get("issue_id")
    repo_url = payload.get("repo_url")
    user_id = payload.get("user_id")

    logger.info(
        "Executing agent task for issue_id=%s repo_url=%s user_id=%s",
        issue_id,
        repo_url,
        user_id,
    )

    # Simulate async work while preserving a no-risk first slice.
    time.sleep(2)

    return {
        "ok": True,
        "message": "Task executed successfully",
        "issue_id": issue_id,
        "repo_url": repo_url,
        "user_id": user_id,
        "started_at": started_at,
        "completed_at": int(time.time()),
    }
