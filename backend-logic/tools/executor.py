#!/usr/bin/env python3
"""
Tool Execution Layer — enforced single path for all agent actions.

RULES:
- Agents MUST use these functions for ALL file/bash/git operations.
- No agent may call subprocess, open(), or os directly.
- Every tool call is logged to ZERO_HUMAN_LOG_DIR (JSONL) automatically.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


# ---------------------------------------------------------------------------
# Internal structured tool logger
# ---------------------------------------------------------------------------

def _log_tool_call(
    tool_name: str,
    args: dict[str, Any],
    result_summary: str,
    *,
    success: bool,
    duration_ms: int,
) -> None:
    """Write a JSONL entry for every tool call, always. Never raises."""
    try:
        log_dir = Path(os.environ.get("ZERO_HUMAN_LOG_DIR", "/tmp/zero-human-logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "layer": "tool",
            "tool": tool_name,
            "args": args,
            "success": success,
            "duration_ms": duration_ms,
            "result_summary": result_summary,
        }
        with (log_dir / "tool_calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
    except Exception:  # noqa: BLE001 - logging must never break execution
        pass


# ---------------------------------------------------------------------------
# Core tool functions
# ---------------------------------------------------------------------------

def run_bash(
    cmd: str | Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int | None = None,
    check: bool = False,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """
    Execute a shell/CLI command and return CompletedProcess.
    All calls are logged automatically.
    """
    start = time.monotonic()
    cmd_str = cmd if isinstance(cmd, str) else " ".join(str(c) for c in cmd)
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            shell=isinstance(cmd, str),
            check=check,
            capture_output=capture_output,
            text=True,
            timeout=timeout_seconds,
        )
        duration = int((time.monotonic() - start) * 1000)
        stdout_snippet = (result.stdout or "")[:200]
        _log_tool_call(
            "run_bash",
            {"cmd": cmd_str, "cwd": cwd},
            f"rc={result.returncode} stdout={stdout_snippet!r}",
            success=result.returncode == 0,
            duration_ms=duration,
        )
        return result
    except Exception as exc:
        duration = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            "run_bash",
            {"cmd": cmd_str, "cwd": cwd},
            f"exception={exc}",
            success=False,
            duration_ms=duration,
        )
        raise


def read_file(path: str) -> str:
    """
    Read file contents as UTF-8 text.
    All calls are logged automatically.
    """
    start = time.monotonic()
    try:
        content = Path(path).read_text(encoding="utf-8")
        duration = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            "read_file",
            {"path": path},
            f"bytes={len(content)}",
            success=True,
            duration_ms=duration,
        )
        return content
    except Exception as exc:
        duration = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            "read_file",
            {"path": path},
            f"exception={exc}",
            success=False,
            duration_ms=duration,
        )
        raise


def write_file(path: str, content: str) -> None:
    """
    Write UTF-8 text to disk, creating parent directories if missing.
    All calls are logged automatically.
    """
    start = time.monotonic()
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        duration = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            "write_file",
            {"path": path, "bytes": len(content)},
            f"written {len(content)} bytes",
            success=True,
            duration_ms=duration,
        )
    except Exception as exc:
        duration = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            "write_file",
            {"path": path},
            f"exception={exc}",
            success=False,
            duration_ms=duration,
        )
        raise


def git_commit(
    message: str,
    *,
    repo_path: str,
    paths: Sequence[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Stage changes and create a git commit in repo_path.
    All calls are logged automatically.
    """
    start = time.monotonic()
    try:
        add_target: list[str] = list(paths) if paths else ["."]
        add_result = run_bash(["git", "add", *add_target], cwd=repo_path, check=True, capture_output=True)
        if add_result.stdout:
            print(add_result.stdout.strip())

        commit_result = run_bash(["git", "commit", "-m", message], cwd=repo_path, check=True, capture_output=True)
        duration = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            "git_commit",
            {"repo_path": repo_path, "message": message, "paths": add_target},
            f"committed in {repo_path}",
            success=True,
            duration_ms=duration,
        )
        return commit_result
    except Exception as exc:
        duration = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            "git_commit",
            {"repo_path": repo_path, "message": message},
            f"exception={exc}",
            success=False,
            duration_ms=duration,
        )
        raise


def delete_file(path: str) -> bool:
    """
    Delete a file. Returns True if deleted, False if not found.
    All calls are logged automatically.
    """
    start = time.monotonic()
    target = Path(path)
    try:
        if target.exists():
            target.unlink()
            duration = int((time.monotonic() - start) * 1000)
            _log_tool_call(
                "delete_file",
                {"path": path},
                "deleted",
                success=True,
                duration_ms=duration,
            )
            return True
        duration = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            "delete_file",
            {"path": path},
            "not_found",
            success=True,
            duration_ms=duration,
        )
        return False
    except Exception as exc:
        duration = int((time.monotonic() - start) * 1000)
        _log_tool_call(
            "delete_file",
            {"path": path},
            f"exception={exc}",
            success=False,
            duration_ms=duration,
        )
        raise


def file_size_bytes(path: str) -> int:
    """Return file size in bytes. Returns 0 if file does not exist."""
    try:
        return Path(path).stat().st_size
    except Exception:  # noqa: BLE001
        return 0


def ensure_dir(path: str) -> None:
    """Create directory and parents if they don't exist."""
    os.makedirs(path, exist_ok=True)
