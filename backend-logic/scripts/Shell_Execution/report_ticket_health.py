#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_events(identifier: str, log_dir: str) -> list[dict[str, Any]]:
    path = Path(log_dir) / f"{identifier}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _latest_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    matched = [e for e in events if e.get("event_type") == event_type]
    return matched[-1] if matched else None


def _build_summary(identifier: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    roles: dict[str, dict[str, Any]] = defaultdict(dict)
    skill_counts: dict[str, int] = defaultdict(int)
    pr_status = "not_detected"
    errors: list[str] = []

    for event in events:
        role_key = str(event.get("role_key") or "unknown")
        skill_name = str(event.get("skill_name") or "unknown")
        payload = event.get("payload") or {}
        event_type = str(event.get("event_type") or "")
        ts = str(event.get("ts") or "")

        if skill_name and skill_name != "unknown":
            skill_counts[skill_name] += 1

        if event_type == "agent_run_started":
            roles[role_key]["started_at"] = ts
            roles[role_key]["skill"] = skill_name
            roles[role_key]["model"] = payload.get("model")

        if event_type == "agent_run_completed":
            roles[role_key]["completed_at"] = ts
            roles[role_key]["duration_ms"] = payload.get("duration_ms")
            roles[role_key]["status_code"] = payload.get("status_code")

        if event_type == "pr_detected":
            pr_status = "detected"
            roles[role_key]["pr_url"] = payload.get("pr_url")
        elif event_type == "pr_auto_created":
            pr_status = "auto_created"
            roles[role_key]["pr_url"] = payload.get("pr_url")
        elif event_type == "pr_auto_create_failed":
            pr_status = "auto_create_failed"
            errors.append(str(payload.get("error") or "unknown pr auto-create failure"))

    latest_completion = _latest_event(events, "agent_run_completed")
    latest_status_code = None
    if latest_completion:
        latest_status_code = (latest_completion.get("payload") or {}).get("status_code")

    return {
        "identifier": identifier,
        "event_count": len(events),
        "latest_status_code": latest_status_code,
        "healthy": latest_status_code == 0 and pr_status in {"detected", "auto_created"},
        "pr_status": pr_status,
        "roles": roles,
        "skill_counts": skill_counts,
        "errors": errors,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: report_ticket_health.py <IDENTIFIER> [LOG_DIR]")
        return 1

    identifier = sys.argv[1].strip()
    log_dir = sys.argv[2].strip() if len(sys.argv) > 2 else os.environ.get("ZERO_HUMAN_LOG_DIR", "/tmp/zero-human-logs")

    try:
        events = _load_events(identifier, log_dir)
    except FileNotFoundError as err:
        print(str(err))
        return 2

    summary = _build_summary(identifier, events)
    print(json.dumps(summary, indent=2, sort_keys=True, default=dict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
