#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .executor import run_bash


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _token() -> str:
    """Return the GitHub token from environment (GH_TOKEN preferred over GITHUB_TOKEN)."""
    return (
        os.environ.get("GH_TOKEN", "").strip()
        or os.environ.get("GITHUB_TOKEN", "").strip()
    )


def _inject_token(url: str, token: str) -> str:
    """Return url with token embedded for authenticated push/fetch.

    https://github.com/<owner>/<repo>.git  ->
    https://<token>@github.com/<owner>/<repo>.git
    """
    if not token or not url:
        return url
    url = url.strip()
    if url.startswith("https://") and "@" not in url.split("/")[2]:
        url = url.replace("https://", f"https://{token}@", 1)
    return url


def _extract_owner_repo(remote_url: str) -> tuple[str, str] | tuple[None, None]:
    """Extract (owner, repo) from a GitHub remote URL."""
    match = re.search(
        r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
        remote_url.strip(),
    )
    if not match:
        return None, None
    return match.group("owner").strip(), match.group("repo").strip()


def _list_remotes(repo_path: str) -> list[str]:
    """Return names of all configured git remotes."""
    result = run_bash(["git", "remote"], cwd=repo_path, check=False, capture_output=True)
    return [r.strip() for r in (result.stdout or "").splitlines() if r.strip()]


def _remote_url(repo_path: str, remote: str) -> str:
    result = run_bash(
        ["git", "remote", "get-url", remote],
        cwd=repo_path,
        check=False,
        capture_output=True,
    )
    return (result.stdout or "").strip()


def _git(args: list[str], *, repo_path: str, check: bool = True):
    return run_bash(["git", *args], cwd=repo_path, check=check, capture_output=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clone_repo(repo_url: str, workspace_dir: str) -> str:
    """Clone repo_url into workspace_dir (token-authenticated if token in env).

    Always clones fresh — if the dir already contains a .git repo it is wiped
    first so stale branch state from previous runs never carries over.
    """
    import shutil
    target = Path(workspace_dir).resolve()
    if target.exists():
        shutil.rmtree(str(target))
    target.mkdir(parents=True, exist_ok=True)
    authed_url = _inject_token(repo_url, _token())
    run_bash(["git", "clone", authed_url, "."], cwd=str(target), check=True, capture_output=True)
    return str(target)


def create_branch(repo_path: str, branch_name: str, base_branch: str | None = None) -> None:
    if base_branch:
        _git(["fetch", "--all"], repo_path=repo_path, check=False)
        _git(["checkout", base_branch], repo_path=repo_path, check=True)
        _git(["pull"], repo_path=repo_path, check=False)
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
    """Create a PR from whatever repo/token is in the environment.

    Fully dynamic — no hardcoded remote names or owners.
    Steps:
    1. Read token from env (GH_TOKEN / GITHUB_TOKEN).
    2. Discover all remotes in the sandbox repo.
    3. Attempt push to each remote using token-authenticated URL.
    4. On first successful push, determine PR head owner:branch and open PR.
    """
    if not os.path.isdir(repo_path):
        raise RuntimeError(f"Repository path does not exist: {repo_path}")

    token = _token()
    if not token:
        raise RuntimeError(
            "No GitHub token found. Set GH_TOKEN or GITHUB_TOKEN in "
            "/home/ubuntu/Zero-Human-Multiagents-Dev/backend-logic/.env"
        )

    branch = current_branch(repo_path)
    if branch in ("", "HEAD"):
        raise RuntimeError("Unable to resolve current branch for PR creation")

    base = (base_branch or "main").strip()

    # Validate there are commits to PR (avoid opaque gh GraphQL failures).
    _git(["fetch", "--all"], repo_path=repo_path, check=False)
    diff_check = _git(
        ["rev-list", "--count", f"--not", "--remotes", branch],
        repo_path=repo_path,
        check=False,
    )
    ahead_count = int((diff_check.stdout or "0").strip() or "0")
    if ahead_count <= 0:
        # Fallback: compare against base on any remote
        diff_check2 = run_bash(
            ["git", "log", "--oneline", f"HEAD", f"--not", f"origin/{base}", f"--not", f"fork/{base}"],
            cwd=repo_path,
            check=False,
            capture_output=True,
        )
        has_commits = bool((diff_check2.stdout or "").strip())
        if not has_commits:
            raise RuntimeError(
                f"No commits to PR on branch '{branch}'. "
                "Ensure the Scribe phase commits feature changes."
            )

    # Discover all remotes and attempt push using token-authenticated URL.
    remotes = _list_remotes(repo_path)
    if not remotes:
        raise RuntimeError(f"No git remotes configured in {repo_path}")

    push_errors: list[str] = []
    pushed_remote: str | None = None
    pushed_url: str | None = None

    for remote in remotes:
        raw_url = _remote_url(repo_path, remote)
        if not raw_url or "github.com" not in raw_url:
            continue
        authed_url = _inject_token(raw_url, token)
        result = run_bash(
            ["git", "push", "-u", authed_url, f"{branch}:{branch}"],
            cwd=repo_path,
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            pushed_remote = remote
            pushed_url = raw_url
            break
        push_errors.append(f"[{remote}] {(result.stderr or '').strip()}")

    if not pushed_remote or not pushed_url:
        raise RuntimeError(
            f"Unable to push branch '{branch}' to any remote. Errors:\n"
            + "\n".join(push_errors)
        )

    # Determine PR head — if pushed to the same repo as origin, use bare branch name.
    # If a different fork repo, use owner:branch cross-repo format.
    origin_url = _remote_url(repo_path, "origin") if "origin" in remotes else ""
    origin_owner, _ = _extract_owner_repo(origin_url)
    pushed_owner, _ = _extract_owner_repo(pushed_url)

    if pushed_owner and origin_owner and pushed_owner.lower() != origin_owner.lower():
        head_for_pr = f"{pushed_owner}:{branch}"
    else:
        head_for_pr = branch

    return create_pr(
        repo_path,
        title=title,
        body=body,
        base_branch=base,
        head_branch=head_for_pr,
    )
