#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from typing import Any

try:
    import psycopg2
except Exception:  # noqa: BLE001 - optional dependency for non-db environments
    psycopg2 = None


def _dsn() -> str | None:
    return (os.environ.get("DATABASE_URL") or "").strip() or None


def _enabled() -> bool:
    return psycopg2 is not None and _dsn() is not None


def _insert_returning_id(query: str, params: tuple[Any, ...]) -> str | None:
    if not _enabled():
        return None
    try:
        with psycopg2.connect(_dsn()) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                if not row:
                    return None
                return str(row[0])
    except Exception:
        return None


def _execute(query: str, params: tuple[Any, ...]) -> None:
    if not _enabled():
        return
    try:
        with psycopg2.connect(_dsn()) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute(query, params)
    except Exception:
        return


def create_agent_run(
    *,
    issue_id: str | None,
    issue_identifier: str,
    heartbeat_run_id: str | None,
    agent_id: str | None,
    role_key: str,
    github_mode: str,
    status: str = "running",
    metadata: dict[str, Any] | None = None,
) -> str | None:
    return _insert_returning_id(
        """
        INSERT INTO public.agent_runs
        (issue_id, issue_identifier, heartbeat_run_id, agent_id, role_key, github_mode, status, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        RETURNING id;
        """,
        (
            issue_id,
            issue_identifier,
            heartbeat_run_id,
            agent_id,
            role_key,
            github_mode,
            status,
            json.dumps(metadata or {}),
        ),
    )


def complete_agent_run(
    *,
    agent_run_id: str | None,
    status: str,
    duration_ms: int | None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not agent_run_id:
        return
    _execute(
        """
        UPDATE public.agent_runs
        SET status = %s,
            completed_at = now(),
            duration_ms = %s,
            error_message = %s,
            metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
        WHERE id = %s::uuid;
        """,
        (status, duration_ms, error_message, json.dumps(metadata or {}), agent_run_id),
    )


def create_skill_run(
    *,
    agent_run_id: str | None,
    issue_id: str | None,
    skill_name: str,
    model: str | None,
    status: str = "running",
    input_summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    if not agent_run_id:
        return None
    return _insert_returning_id(
        """
        INSERT INTO public.skill_runs
        (agent_run_id, issue_id, skill_name, model, status, input_summary, metadata)
        VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::jsonb)
        RETURNING id;
        """,
        (
            agent_run_id,
            issue_id,
            skill_name,
            model,
            status,
            input_summary,
            json.dumps(metadata or {}),
        ),
    )


def complete_skill_run(
    *,
    skill_run_id: str | None,
    status: str,
    duration_ms: int | None,
    output_summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not skill_run_id:
        return
    _execute(
        """
        UPDATE public.skill_runs
        SET status = %s,
            completed_at = now(),
            duration_ms = %s,
            output_summary = %s,
            metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
        WHERE id = %s::uuid;
        """,
        (status, duration_ms, output_summary, json.dumps(metadata or {}), skill_run_id),
    )


def log_usage(
    *,
    agent_run_id: str | None,
    skill_run_id: str | None,
    metric_key: str,
    metric_value: float | int | None,
    unit: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    _execute(
        """
        INSERT INTO public.usage_logs
        (agent_run_id, skill_run_id, metric_key, metric_value, unit, metadata)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::jsonb);
        """,
        (
            agent_run_id,
            skill_run_id,
            metric_key,
            metric_value,
            unit,
            json.dumps(metadata or {}),
        ),
    )
