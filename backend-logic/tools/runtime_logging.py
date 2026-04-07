#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _log_dir() -> Path:
    raw = os.environ.get("ZERO_HUMAN_LOG_DIR", "/tmp/zero-human-logs")
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return str(value)


def write_event(
    *,
    event_type: str,
    identifier: str,
    role_key: str | None = None,
    skill_name: str | None = None,
    run_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    record = {
        "ts": _timestamp(),
        "event_type": event_type,
        "identifier": identifier,
        "role_key": role_key,
        "skill_name": skill_name,
        "run_id": run_id,
        "payload": {k: _sanitize(v) for k, v in (payload or {}).items()},
    }
    logfile = _log_dir() / f"{identifier}.jsonl"
    with logfile.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=True) + "\n")
    return str(logfile)
