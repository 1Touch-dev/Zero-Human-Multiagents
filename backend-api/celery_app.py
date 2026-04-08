import os

from celery import Celery


broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery_app = Celery(
    "backend_api",
    broker=broker_url,
    backend=result_backend,
    include=["tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,

    # Results expire after 24 hours — prevents Redis memory growth.
    result_expires=86400,

    # Route lightweight vs heavy tasks to separate queues.
    task_routes={
        "lightweight_task": {"queue": "light"},
        "execute_agent_task": {"queue": "heavy"},
    },

    # Default queue for unrouted tasks.
    task_default_queue="heavy",

    # Prefetch one task at a time per worker — prevents one worker hoarding tasks.
    worker_prefetch_multiplier=1,

    # Acknowledge task only after it completes, not when received.
    # Ensures failed tasks are re-queued on worker crash.
    task_acks_late=True,
)
