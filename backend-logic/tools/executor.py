#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Sequence


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
    """
    use_shell = isinstance(cmd, str)
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        shell=use_shell,
        check=check,
        capture_output=capture_output,
        text=True,
        timeout=timeout_seconds,
    )


def read_file(path: str) -> str:
    """
    Read file contents as UTF-8 text.
    """
    return Path(path).read_text(encoding="utf-8")


def write_file(path: str, content: str) -> None:
    """
    Write UTF-8 text to disk, creating parent directories if missing.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def git_commit(message: str, *, repo_path: str, paths: Sequence[str] | None = None) -> subprocess.CompletedProcess[str]:
    """
    Stage changes and create a git commit in repo_path.
    """
    add_target: Sequence[str] = list(paths) if paths else ["."]
    add_cmd = ["git", "add", *add_target]
    add_result = run_bash(add_cmd, cwd=repo_path, check=True, capture_output=True)
    if add_result.stdout:
        print(add_result.stdout.strip())

    commit_cmd = ["git", "commit", "-m", message]
    return run_bash(commit_cmd, cwd=repo_path, check=True, capture_output=True)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)
