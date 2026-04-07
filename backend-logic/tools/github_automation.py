#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from .executor import run_bash


def _git(args: list[str], *, repo_path: str, check: bool = True):
    return run_bash(["git", *args], cwd=repo_path, check=check, capture_output=True)


def clone_repo(repo_url: str, workspace_dir: str) -> str:
    Path(workspace_dir).mkdir(parents=True, exist_ok=True)
    target = Path(workspace_dir).resolve()
    if not any(target.iterdir()):
        run_bash(["git", "clone", repo_url, "."], cwd=str(target), check=True, capture_output=True)
    return str(target)


def create_branch(repo_path: str, branch_name: str, base_branch: str | None = None) -> None:
    if base_branch:
        _git(["fetch", "origin", base_branch], repo_path=repo_path, check=False)
        _git(["checkout", base_branch], repo_path=repo_path, check=True)
        _git(["pull", "origin", base_branch], repo_path=repo_path, check=False)
    _git(["checkout", "-B", branch_name], repo_path=repo_path, check=True)


def commit_all(repo_path: str, message: str) -> None:
    _git(["add", "."], repo_path=repo_path, check=True)
    _git(["commit", "-m", message], repo_path=repo_path, check=True)


def push_branch(repo_path: str, branch_name: str, remote: str = "origin") -> None:
    _git(["push", "-u", remote, branch_name], repo_path=repo_path, check=True)


def current_branch(repo_path: str) -> str:
    result = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path=repo_path, check=True)
    return (result.stdout or "").strip()


def create_pr(
    repo_path: str,
    title: str,
    body: str,
    *,
    base_branch: str | None = None,
    head_branch: str | None = None,
) -> str:
    cmd = ["gh", "pr", "create", "--title", title, "--body", body]
    if base_branch:
        cmd.extend(["--base", base_branch])
    if head_branch:
        cmd.extend(["--head", head_branch])
    result = run_bash(cmd, cwd=repo_path, check=True, capture_output=True)
    return (result.stdout or "").strip()


def create_pr_from_repo(
    repo_path: str,
    *,
    title: str,
    body: str,
    base_branch: str | None = None,
) -> str:
    if not os.path.isdir(repo_path):
        raise RuntimeError(f"Repository path does not exist: {repo_path}")

    branch = current_branch(repo_path)
    if branch in ("", "HEAD"):
        raise RuntimeError("Unable to resolve current branch for PR creation")

    return create_pr(
        repo_path,
        title=title,
        body=body,
        base_branch=base_branch,
        head_branch=branch,
    )
