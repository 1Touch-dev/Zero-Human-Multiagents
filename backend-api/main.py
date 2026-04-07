from typing import Any

from celery.result import AsyncResult
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from celery_app import celery_app
from tasks import execute_agent_task


app = FastAPI(title="Zero-Human Backend API", version="0.1.0")


class TaskRequest(BaseModel):
    issue_id: str = Field(..., description="Paperclip issue identifier")
    repo_url: str = Field(..., description="Target repository URL")
    user_id: str = Field(..., description="Requester identifier")
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/task")
def create_task(request: TaskRequest) -> dict[str, str]:
    task_payload = request.model_dump()
    task = execute_agent_task.delay(task_payload)
    return {"task_id": task.id, "status": "queued"}


@app.get("/status/{task_id}")
def get_task_status(task_id: str) -> dict[str, Any]:
    if not task_id.strip():
        raise HTTPException(status_code=400, detail="task_id is required")

    result = AsyncResult(task_id, app=celery_app)
    response: dict[str, Any] = {"task_id": task_id, "state": result.state}

    if result.state == "SUCCESS":
        response["result"] = result.result
    elif result.state == "FAILURE":
        response["error"] = str(result.result)

    return response
