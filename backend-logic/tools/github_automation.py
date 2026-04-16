#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import time
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


def _has_uncommitted_changes(repo_path: str) -> bool:
    result = _git(["status", "--porcelain"], repo_path=repo_path, check=False)
    return bool((result.stdout or "").strip())


def _safe_auto_commit(repo_path: str, message: str) -> bool:
    add_result = _git(["add", "."], repo_path=repo_path, check=False)
    if add_result.returncode != 0:
        return False
    commit_result = run_bash(
        [
            "git",
            "-c",
            "user.name=Zero Human Scribe",
            "-c",
            "user.email=zero-human-scribe@local",
            "commit",
            "-m",
            message,
        ],
        cwd=repo_path,
        check=False,
        capture_output=True,
    )
    return commit_result.returncode == 0


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
        remotes = _list_remotes(repo_path)
        preferred_remote = "origin" if "origin" in remotes else (remotes[0] if remotes else "")
        base_ref = base_branch
        if preferred_remote:
            fetch_result = _git(["fetch", preferred_remote, base_branch], repo_path=repo_path, check=False)
            if fetch_result.returncode == 0:
                base_ref = f"{preferred_remote}/{base_branch}"
        _git(["checkout", "-B", base_branch, base_ref], repo_path=repo_path, check=True)
    _git(["checkout", "-B", branch_name], repo_path=repo_path, check=True)


def commit_all(repo_path: str, message: str) -> None:
    _git(["add", "."], repo_path=repo_path, check=True)
    _git(["commit", "-m", message], repo_path=repo_path, check=True)


def push_branch(repo_path: str, branch_name: str, remote: str = "origin") -> None:
    _git(["push", "-u", remote, branch_name], repo_path=repo_path, check=True)


def current_branch(repo_path: str) -> str:
    result = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path=repo_path, check=True)
    return (result.stdout or "").strip()


def _gh_env() -> dict[str, str]:
    """Return an env dict for gh CLI calls that includes the GitHub token.

    gh CLI reads GH_TOKEN (preferred) or GITHUB_TOKEN automatically, but we
    pass them explicitly so the env is correct regardless of how run_bash
    inherits the process environment.
    """
    env = dict(os.environ)
    token = _token()
    if token:
        env["GH_TOKEN"] = token
        env["GITHUB_TOKEN"] = token
    return env


def _preflight_pr_target(
    repo_path: str,
    *,
    raw_url: str,
    token: str,
    base_branch: str,
) -> tuple[bool, str]:
    """Validate candidate target has common history with HEAD and pending commits."""
    authed_url = _inject_token(raw_url, token)
    fetch_result = run_bash(
        ["git", "fetch", "--quiet", authed_url, base_branch],
        cwd=repo_path,
        check=False,
        capture_output=True,
    )
    if fetch_result.returncode != 0:
        return False, f"unable to fetch base '{base_branch}': {(fetch_result.stderr or '').strip()}"

    merge_base_result = _git(["merge-base", "HEAD", "FETCH_HEAD"], repo_path=repo_path, check=False)
    if merge_base_result.returncode != 0:
        return (
            False,
            f"branch has no common history with target base '{base_branch}'",
        )

    ahead_result = _git(["rev-list", "--count", "FETCH_HEAD..HEAD"], repo_path=repo_path, check=False)
    if ahead_result.returncode != 0:
        return False, f"unable to compare commits against '{base_branch}'"

    try:
        ahead_count = int((ahead_result.stdout or "0").strip() or "0")
    except ValueError:
        ahead_count = 0
    if ahead_count <= 0:
        return False, f"no commits ahead of target base '{base_branch}'"

    return True, ""


def create_pr(
    repo_path: str,
    title: str,
    body: str,
    *,
    repo_target: str | None = None,
    base_branch: str | None = None,
    head_branch: str | None = None,
) -> str:
    cmd = ["gh", "pr", "create", "--title", title, "--body", body]
    if repo_target:
        cmd.extend(["--repo", repo_target])
    if base_branch:
        cmd.extend(["--base", base_branch])
    if head_branch:
        cmd.extend(["--head", head_branch])
    result = run_bash(cmd, cwd=repo_path, env=_gh_env(), check=False, capture_output=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"gh pr create failed with code {result.returncode}"
        raise RuntimeError(detail)
    return (result.stdout or "").strip()


def _find_existing_pr_url(
    repo_path: str,
    *,
    repo_target: str | None,
    head_branch: str | None,
) -> str | None:
    """Return an existing PR URL for the current branch, if present."""
    if not head_branch:
        return None
    cmd = ["gh", "pr", "list", "--state", "all", "--head", head_branch, "--json", "url"]
    if repo_target:
        cmd.extend(["--repo", repo_target])
    result = run_bash(cmd, cwd=repo_path, env=_gh_env(), check=False, capture_output=True)
    if result.returncode != 0:
        return None
    import json

    try:
        rows = json.loads((result.stdout or "[]").strip() or "[]")
    except json.JSONDecodeError:
        return None
    if isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, dict):
            candidate = str(first.get("url", "")).strip()
            if candidate:
                return candidate
    return None


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
            "No GitHub token found. Set GH_TOKEN or GITHUB_TOKEN in your backend-logic/.env file."
        )

    branch = current_branch(repo_path)
    if branch in ("", "HEAD"):
        raise RuntimeError("Unable to resolve current branch for PR creation")

    base = (base_branch or "main").strip()

    # Never try to open a PR from main/master directly.
    if branch in {"main", "master"}:
        generated_branch = f"zero-human/{int(time.time())}"
        checkout_result = _git(["checkout", "-B", generated_branch], repo_path=repo_path, check=False)
        if checkout_result.returncode != 0:
            raise RuntimeError(
                f"Failed to create working branch '{generated_branch}' from '{branch}': "
                f"{(checkout_result.stderr or '').strip()}"
            )
        branch = generated_branch

    # If Scribe produced file edits but forgot to commit, commit them automatically.
    if _has_uncommitted_changes(repo_path):
        committed = _safe_auto_commit(repo_path, "chore: prepare automated scribe PR")
        if not committed:
            raise RuntimeError(
                "Detected uncommitted changes but failed to create an automated commit for PR fallback."
            )

    # Discover all remotes and attempt push using token-authenticated URL.
    # Also try ZERO_HUMAN_WORKSPACE_REPO_URL directly so PR automation works
    # even when local remote config points at a non-writable upstream.
    remotes = _list_remotes(repo_path)
    if not remotes:
        raise RuntimeError(f"No git remotes configured in {repo_path}")

    # Validate there are commits to PR (avoid opaque gh GraphQL failures).
    # This is dynamic across whatever remotes exist; no hardcoded remote names.
    _git(["fetch", "--all"], repo_path=repo_path, check=False)
    ahead_count = 0
    for remote_name in remotes:
        remote_base = f"{remote_name}/{base}"
        rev_count = _git(["rev-list", "--count", f"{remote_base}..HEAD"], repo_path=repo_path, check=False)
        if rev_count.returncode == 0:
            try:
                ahead_count = max(ahead_count, int((rev_count.stdout or "0").strip() or "0"))
            except ValueError:
                pass
    if ahead_count <= 0:
        raise RuntimeError(
            f"No commits to PR on branch '{branch}'. "
            "Ensure the Scribe phase commits feature changes."
        )

    push_errors: list[str] = []
    pushed_remote: str | None = None
    pushed_url: str | None = None
    push_candidates: list[tuple[str, str]] = []
    for remote in remotes:
        raw_url = _remote_url(repo_path, remote)
        if raw_url and "github.com" in raw_url:
            push_candidates.append((remote, raw_url))

    workspace_repo_url = os.environ.get("ZERO_HUMAN_WORKSPACE_REPO_URL", "").strip()
    if workspace_repo_url and "github.com" in workspace_repo_url:
        # Prefer the explicitly configured workspace repo first.
        push_candidates.insert(0, ("workspace_repo_url", workspace_repo_url))

    seen_urls: set[str] = set()
    unique_candidates: list[tuple[str, str]] = []
    for source_name, raw_url in push_candidates:
        normalized = raw_url.rstrip("/")
        if normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        unique_candidates.append((source_name, raw_url))

    for source_name, raw_url in unique_candidates:
        is_valid_target, invalid_reason = _preflight_pr_target(
            repo_path,
            raw_url=raw_url,
            token=token,
            base_branch=base,
        )
        if not is_valid_target:
            push_errors.append(f"[{source_name}] preflight failed: {invalid_reason}")
            continue

        authed_url = _inject_token(raw_url, token)
        result = run_bash(
            ["git", "push", "-u", authed_url, f"{branch}:{branch}"],
            cwd=repo_path,
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            pushed_remote = source_name
            pushed_url = raw_url
            break
        push_errors.append(f"[{source_name}] {(result.stderr or '').strip()}")

    if not pushed_remote or not pushed_url:
        raise RuntimeError(
            f"Unable to push branch '{branch}' to any remote. Errors:\n"
            + "\n".join(push_errors)
        )

    # Determine PR head and target repo dynamically from where push succeeded.
    # This prevents gh from auto-targeting an upstream parent repo.
    origin_url = _remote_url(repo_path, "origin") if "origin" in remotes else ""
    origin_owner, _ = _extract_owner_repo(origin_url)
    pushed_owner, pushed_repo = _extract_owner_repo(pushed_url)

    if pushed_owner and origin_owner and pushed_owner.lower() != origin_owner.lower():
        head_for_pr = f"{pushed_owner}:{branch}"
    else:
        head_for_pr = branch
    repo_target = f"{pushed_owner}/{pushed_repo}" if pushed_owner and pushed_repo else None

    try:
        return create_pr(
            repo_path,
            title=title,
            body=body,
            repo_target=repo_target,
            base_branch=base,
            head_branch=head_for_pr,
        )
    except Exception as pr_err:
        existing_pr_url = _find_existing_pr_url(
            repo_path,
            repo_target=repo_target,
            head_branch=head_for_pr,
        )
        if existing_pr_url:
            return existing_pr_url
        raise RuntimeError(f"PR creation failed and no existing PR found: {pr_err}") from pr_err
