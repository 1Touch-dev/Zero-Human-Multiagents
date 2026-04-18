#!/usr/bin/env python3
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BACKEND_LOGIC_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if BACKEND_LOGIC_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_LOGIC_ROOT)

try:
    from orchestrator.orchestrator import orchestrate_task, sanitize_plan
except Exception:  # noqa: BLE001 - bridge must preserve legacy flow if orchestrator is unavailable
    orchestrate_task = None
    sanitize_plan = None

try:
    from agents.registry import DEFAULT_ROLE_ORDER, get_role_specs
except Exception:  # noqa: BLE001 - keep legacy role behavior if registry is unavailable
    DEFAULT_ROLE_ORDER = ["architect", "grunt", "pedant", "scribe"]

    def get_role_specs(ordered_role_keys=None):
        keys = ordered_role_keys or list(DEFAULT_ROLE_ORDER)
        return [
            {
                "key": key,
                "display_name": f"The {key.capitalize()}",
                "env_key": key.upper(),
            }
            for key in keys
        ]

try:
    from skills.registry import get_skill
except Exception:  # noqa: BLE001 - keep bridge resilient if skills module is unavailable

    class _FallbackSkill:
        def __init__(self):
            self.name = "write_code"
            self.prompt = "SKILL (WRITE_CODE): implement requested behavior safely."

    def get_skill(role_key, task=None, model=None):
        _ = role_key
        _ = task
        _ = model
        return _FallbackSkill()

try:
    from tools.executor import ensure_dir, run_bash
except Exception:  # noqa: BLE001 - keep bridge resilient if tools module is unavailable
    ensure_dir = None
    run_bash = None

try:
    from tools.github_automation import clone_repo, create_pr_from_repo
except Exception:  # noqa: BLE001 - keep bridge resilient if github automation is unavailable
    clone_repo = None
    create_pr_from_repo = None

try:
    from tools.s3_storage import (
        build_log_key,
        is_enabled as s3_enabled,
        sweep_sandbox_output,
        upload_text,
    )
except Exception:  # noqa: BLE001 - keep bridge resilient if s3 layer is unavailable
    build_log_key = None
    s3_enabled = None
    sweep_sandbox_output = None
    upload_text = None

try:
    from tools.db_telemetry import (
        complete_agent_run,
        complete_skill_run,
        create_agent_run,
        create_skill_run,
        log_usage,
    )
except Exception:  # noqa: BLE001 - keep bridge resilient if telemetry layer is unavailable
    complete_agent_run = None
    complete_skill_run = None
    create_agent_run = None
    create_skill_run = None
    log_usage = None

try:
    from tools.runtime_logging import write_event
except Exception:  # noqa: BLE001 - keep bridge resilient if runtime logging is unavailable
    write_event = None


def prefer_system_node_in_path(env: dict[str, str]) -> dict[str, str]:
    """
    OpenClaw is installed as `#!/usr/bin/env node ...`. The first `node` on PATH
    wins. Cursor/IDE sessions often prepend a bundled Node (e.g. v20) ahead of
    /usr/bin/node (v22+), which makes OpenClaw fail its version check even when
    the system Node is correct. Prepend standard locations so `env node` matches
    the OS toolchain.
    """
    out = dict(env)
    raw = out.get("PATH", "")
    parts = [p for p in raw.split(os.pathsep) if p]
    priority = ("/usr/bin", "/bin")
    seen: set[str] = set()
    merged: list[str] = []
    for p in priority:
        if p not in seen:
            merged.append(p)
            seen.add(p)
    for p in parts:
        if p not in seen:
            merged.append(p)
            seen.add(p)
    out["PATH"] = os.pathsep.join(merged)
    return out


def load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    k = k.strip()
                    # Do NOT overwrite vars already set in the environment.
                    # This allows PAPERCLIP_AGENT_ID injected by the Celery task
                    # to take precedence over the .env default (Architect's ID).
                    if k not in os.environ:
                        os.environ[k] = v.strip().strip('"').strip("'")


def api_request(method, url, api_key, run_id, payload=None):
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if run_id:
        headers["X-Paperclip-Run-Id"] = run_id
    req = urllib.request.Request(url=url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read().decode("utf-8").strip()
            return response.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as err:
        error_body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed ({err.code}): {error_body}") from err


def patch_issue(api_base, api_key, run_id, issue_id, payload):
    return api_request("PATCH", f"{api_base}/issues/{issue_id}", api_key, run_id, payload)


def post_checkout(api_base, api_key, run_id, issue_id, agent_id):
    return api_request(
        "POST",
        f"{api_base}/issues/{issue_id}/checkout",
        api_key,
        run_id,
        {"agentId": agent_id, "expectedStatuses": ["todo", "backlog", "blocked", "in_progress"]},
    )


def resolve_run_id(api_base, api_key, company_id, agent_id):
    query = urllib.parse.urlencode({
        "agentId": agent_id,
        "limit": 25,
    })
    _, runs = api_request(
        "GET",
        f"{api_base}/companies/{urllib.parse.quote(company_id)}/heartbeat-runs?{query}",
        api_key,
        None,
    )
    if not isinstance(runs, list):
        return None
    for run in runs:
        if run.get("status") == "running":
            return str(run.get("id", "")).strip() or None
    for run in runs:
        if run.get("status") == "queued":
            return str(run.get("id", "")).strip() or None
    return None


def get_assigned_issue(api_base, api_key, run_id, company_id, agent_id):
    query = urllib.parse.urlencode({
        "assigneeAgentId": agent_id,
        "status": "todo,in_progress",
    })
    _, issues = api_request(
        "GET",
        f"{api_base}/companies/{urllib.parse.quote(company_id)}/issues?{query}",
        api_key,
        run_id,
    )
    if not isinstance(issues, list) or not issues:
        return None
    in_progress = [i for i in issues if i.get("status") == "in_progress"]
    if in_progress:
        return in_progress[0]
    return issues[0]


def resolve_role_agents(api_base, api_key, run_id, company_id, env, planned_role_keys=None):
    role_specs = get_role_specs()
    if planned_role_keys:
        planned = set(planned_role_keys)
        role_specs = [role for role in role_specs if role["key"] in planned]
        if not role_specs:
            role_specs = get_role_specs(list(DEFAULT_ROLE_ORDER))
    _, all_agents = api_request(
        "GET",
        f"{api_base}/companies/{urllib.parse.quote(company_id)}/agents",
        api_key,
        run_id,
    )
    all_agents = all_agents if isinstance(all_agents, list) else []
    resolved = []
    for role in role_specs:
        key = role["key"]
        default_name = role["display_name"]
        env_key = role["env_key"]
        explicit_id = env.get(f"ZERO_HUMAN_{env_key}_AGENT_ID", "").strip()
        if explicit_id:
            resolved.append({"key": key, "name": default_name, "agent_id": explicit_id})
            continue
        lookup_name = env.get(f"ZERO_HUMAN_{env_key}_AGENT_NAME", default_name).strip()
        normalized_lookup = lookup_name.strip().lower()
        matched = next(
            (a for a in all_agents if str(a.get("name", "")).strip().lower() == normalized_lookup),
            None,
        )
        if not matched:
            matched = next(
                (a for a in all_agents if key in str(a.get("name", "")).strip().lower()),
                None,
            )
        resolved.append({"key": key, "name": lookup_name, "agent_id": matched.get("id") if matched else None})
    return resolved


def build_role_prompt(role_key, role_name, identifier, title, description, skill_prompt, github_mode):
    repo_url = os.environ.get("ZERO_HUMAN_WORKSPACE_REPO_URL", "").strip()
    base_branch = os.environ.get("ZERO_HUMAN_PR_BASE_BRANCH", "main").strip() or "main"
    delivery_guard = (
        "CRITICAL DELIVERY OWNERSHIP RULES:\n"
        "- ONLY The Scribe may push branches or create pull requests.\n"
        "- The Architect, The Grunt, and The Pedant MUST NOT run `git push` or `gh pr create`.\n"
        "- Non-scribe roles must hand off implementation/testing artifacts only."
    )
    scribe_directive = (
        "ROLE DIRECTIVE (SCRIBE): finalize documentation/changelog, verify final quality gates, "
        "then create exactly one PR. You MUST print a single bare line exactly in this form "
        "(copy-paste the real URL): PR_URL: https://github.com/<org>/<repo>/pull/<number> "
        "so automation can detect it."
    )
    if github_mode == "tool_first":
        scribe_directive = (
            "ROLE DIRECTIVE (SCRIBE - TOOL_FIRST MODE): "
            "You are responsible for BOTH implementation AND preparation for automated PR creation. "
            "Follow these steps strictly in order:\n"
            f"1. Inspect /tmp/zero-human-sandbox/ (cloned from {repo_url or 'the workspace repo'}).\n"
            f"2. If the requested feature is NOT yet implemented, implement it fully now.\n"
            f"3. Create a new branch named after the ticket identifier (e.g. {identifier.lower()}-feature).\n"
            "4. Run: git add . && git commit -m 'feat: <short description of change>'\n"
            "5. Do NOT run gh pr create or git push — PR creation and push are handled by automation.\n"
            "6. NEVER run `git init`, `git remote add`, or `git remote set-url` in this repository.\n"
            "7. Print explicit terminal logs of every file you changed and every git command you ran.\n"
            "8. End with a one-line summary: SCRIBE_DONE: <branch-name> ready for automated PR to "
            f"{base_branch}."
        )

    role_specific = {
        "architect": (
            "ROLE DIRECTIVE (ARCHITECT): analyze requirements, inspect stack, and produce an implementation plan. "
            "Do NOT make code edits in this phase and do NOT create a PR."
        ),
        "grunt": (
            "ROLE DIRECTIVE (GRUNT): perform implementation and integration work. "
            "Do NOT create a PR. Leave explicit handoff notes for Pedant."
        ),
        "pedant": (
            "ROLE DIRECTIVE (PEDANT): run quality checks, fix issues, and improve correctness. "
            "Do NOT create a PR. Leave explicit handoff notes for Scribe."
        ),
        "scribe": scribe_directive,
    }.get(role_key, "ROLE DIRECTIVE: execute your assigned phase and provide explicit logs.")
    return (
        f"You are {role_name}. "
        f"You are handling ticket {identifier} - {title}. "
        "Execute only your role-specific phase now, leave clear artifacts for the next role, "
        "and print explicit terminal logs for what you changed. "
        "Work strictly in /tmp/zero-human-sandbox/. "
        f"{skill_prompt} "
        f"{delivery_guard} "
        f"{role_specific} "
        f"Instructions: {description}"
    )


_GITHUB_PR_URL_RE = re.compile(
    r"https://(?:www\.)?github\.com/[^\s<>\]\"')]+/pull/\d+",
    re.IGNORECASE,
)
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OSC_SEQUENCE_RE = re.compile(r"\x1b\][^\x07]*\x07|\x1b\][0-9]+;[^\x1b]*(?:\x1b\\|\x07)")


def strip_terminal_escapes(text):
    if not text:
        return text
    text = _ANSI_CSI_RE.sub("", text)
    text = _OSC_SEQUENCE_RE.sub("", text)
    return text


def extract_pr_url(text):
    if not text:
        return None
    for candidate in (text, strip_terminal_escapes(text)):
        match = _GITHUB_PR_URL_RE.search(candidate)
        if match:
            return match.group(0).rstrip(").,;]")
    return None


def extract_pr_url_from_openclaw_sessions(max_files=6):
    """Fallback when CLI stdout/stderr misses URL but session JSON contains it."""
    sessions_dir = os.path.expanduser("~/.openclaw/agents/main/sessions")
    if not os.path.isdir(sessions_dir):
        return None
    paths = glob.glob(os.path.join(sessions_dir, "*.json"))
    if not paths:
        return None
    paths.sort(key=os.path.getmtime, reverse=True)

    blobs = []
    for path in paths[:max_files]:
        try:
            with open(path, encoding="utf-8", errors="replace") as session_file:
                blobs.append(session_file.read())
        except OSError:
            continue
    return extract_pr_url("\n".join(blobs))


def ensure_project_readme(workspace_dir, identifier, title, description):
    """
    Ensure the Scribe phase leaves a project README artifact in the sandbox.
    If no README exists, auto-create a concise README.md from issue context.
    Returns the created path when a file is generated, otherwise None.
    """
    candidate_names = [
        "README.md",
        "README.MD",
        "Readme.md",
        "readme.md",
    ]
    for candidate in candidate_names:
        existing_path = os.path.join(workspace_dir, candidate)
        if os.path.isfile(existing_path):
            return None

    safe_title = (title or "Project Update").strip()
    safe_identifier = (identifier or "UNKNOWN").strip()
    short_description = (description or "").strip()
    if len(short_description) > 1200:
        short_description = short_description[:1200].rstrip() + "..."

    readme_body = [
        f"# {safe_title}",
        "",
        f"Generated by Zero-Human Scribe for issue **{safe_identifier}**.",
        "",
        "## Overview",
        short_description if short_description else "Implementation updates are tracked in the related issue/PR.",
        "",
        "## Notes",
        "- This README was auto-generated because no README file existed in the repository during Scribe handoff.",
        "- Update this document with setup, architecture, and usage details as the project evolves.",
        "",
    ]
    created_path = os.path.join(workspace_dir, "README.md")
    with open(created_path, "w", encoding="utf-8") as readme_file:
        readme_file.write("\n".join(readme_body))
    return created_path


def maybe_upload_run_log(*, identifier, role_key, run_id, payload):
    if not (s3_enabled and upload_text and build_log_key):
        return None
    if not s3_enabled():
        return None
    try:
        key = build_log_key(identifier=identifier, role_key=role_key, run_id=run_id, suffix="run.log")
        return upload_text(payload, key=key)
    except Exception as s3_err:  # noqa: BLE001 - never fail run on storage issues
        print(f"S3 upload skipped due to error: {s3_err}", file=sys.stderr)
        return None


def main():
    load_env()

    # ── Company Settings bridge ────────────────────────────────────────────────
    # The Paperclip UI stores keys under friendly names (REPO_LINK, MODEL).
    # Map them to the internal names the bridge uses so any non-technical user
    # can configure everything from the UI without touching .env files.
    #
    # REPO_LINK (injected by heartbeat from Company Settings) always wins over
    # the static ZERO_HUMAN_WORKSPACE_REPO_URL in .env so the UI value is used.
    repo_link_from_ui = os.environ.get("REPO_LINK", "").strip()
    if repo_link_from_ui:
        os.environ["ZERO_HUMAN_WORKSPACE_REPO_URL"] = repo_link_from_ui

    # MODEL from Company Settings maps to OPENCLAW_MODEL (only if not already set).
    model_from_ui = os.environ.get("MODEL", "").strip()
    if model_from_ui and not os.environ.get("OPENCLAW_MODEL", "").strip():
        os.environ["OPENCLAW_MODEL"] = model_from_ui
    # ──────────────────────────────────────────────────────────────────────────

    try:
        env = prefer_system_node_in_path(os.environ.copy())
        env["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")
        if os.environ.get("GITHUB_TOKEN", "").strip():
            env["GITHUB_TOKEN"] = os.environ["GITHUB_TOKEN"]
        if os.environ.get("GH_TOKEN", "").strip():
            env["GH_TOKEN"] = os.environ["GH_TOKEN"]

        agent_id = os.environ.get("PAPERCLIP_AGENT_ID", "").strip()
        api_url = os.environ.get("PAPERCLIP_API_URL", "").rstrip("/")
        api_key = os.environ.get("PAPERCLIP_API_KEY", "").strip()
        run_id = os.environ.get("PAPERCLIP_RUN_ID", "").strip()
        company_id = os.environ.get("PAPERCLIP_COMPANY_ID", "").strip()
        if not agent_id or not api_url or not api_key or not company_id:
            raise RuntimeError("Missing PAPERCLIP_AGENT_ID / PAPERCLIP_API_URL / PAPERCLIP_API_KEY")
        api_base = f"{api_url}/api"
        if not run_id:
            run_id = resolve_run_id(api_base, api_key, company_id, agent_id) or ""

        issue = get_assigned_issue(api_base, api_key, run_id, company_id, agent_id)
        if not issue:
            print("No assigned issue for this agent.")
            sys.exit(0)
        issue_id = str(issue.get("id", "")).strip()
        identifier = str(issue.get("identifier", issue_id[:8])).strip()
        title = str(issue.get("title", "Untitled issue")).strip()
        description = str(issue.get("description", "") or "").strip()

        full_role_chain = list(DEFAULT_ROLE_ORDER)
        planned_role_keys = list(full_role_chain)
        if orchestrate_task and sanitize_plan:
            try:
                task_context = {
                    "id": issue_id,
                    "identifier": identifier,
                    "title": title,
                    "description": description,
                }
                orchestrated_role_keys = sanitize_plan(orchestrate_task(task_context))
                print(f">>> Orchestrator plan for {identifier}: {orchestrated_role_keys}")
                if orchestrated_role_keys != full_role_chain:
                    print(
                        f">>> Full-role enforcement active for {identifier}. "
                        f"Using {full_role_chain} instead of orchestrator plan."
                    )
            except Exception as plan_err:
                print(
                    f"Orchestrator planning failed for {identifier}. "
                    f"Falling back to enforced full-role flow. reason={plan_err}",
                    file=sys.stderr,
                )

        role_agents = resolve_role_agents(
            api_base,
            api_key,
            run_id,
            company_id,
            env,
            planned_role_keys=planned_role_keys,
        )
        role_index = {}
        for idx, role in enumerate(role_agents):
            if role["agent_id"]:
                role_index[role["agent_id"]] = idx
        current_idx = role_index.get(agent_id)

        # Safety fallback: if the current assignee is not in the planned role set,
        # preserve previous behavior by reloading the full role chain.
        if current_idx is None and planned_role_keys:
            print(
                f"Current agent {agent_id} is outside orchestrator plan for {identifier}. "
                "Falling back to legacy role flow."
            )
            role_agents = resolve_role_agents(api_base, api_key, run_id, company_id, env, planned_role_keys=None)
            role_index = {}
            for idx, role in enumerate(role_agents):
                if role["agent_id"]:
                    role_index[role["agent_id"]] = idx
            current_idx = role_index.get(agent_id)

        role_key = role_agents[current_idx]["key"] if current_idx is not None else "unknown"
        role_name = role_agents[current_idx]["name"] if current_idx is not None else "Assigned Agent"
        is_scribe = role_key == "scribe"

        # Ensure the current run explicitly owns the issue lock.
        if run_id:
            try:
                post_checkout(api_base, api_key, run_id, issue_id, agent_id)
            except Exception as checkout_err:
                print(f"Checkout warning for {identifier}: {checkout_err}", file=sys.stderr)

        # Enforce single PR owner by role: only Scribe receives GitHub token.
        if not is_scribe:
            env.pop("GITHUB_TOKEN", None)
            env.pop("GH_TOKEN", None)

        target_model = os.environ.get("OPENCLAW_MODEL", "openai/gpt-4o")
        # Default to tool_first so PRs are created by controlled automation,
        # not by free-form agent gh behavior that may target upstream forks.
        github_mode = os.environ.get("ZERO_HUMAN_GITHUB_MODE", "tool_first").strip().lower()
        if github_mode not in {"legacy_first", "tool_first"}:
            github_mode = "tool_first"
        print(f">>> GitHub automation mode: {github_mode}")
        task_context = {
            "id": issue_id,
            "identifier": identifier,
            "title": title,
            "description": description,
        }
        selected_skill = get_skill(role_key, task=task_context, model=target_model)
        print(f">>> Using skill for {role_name}: {selected_skill.name}")

        # --- H1: Wire Skill.execute() as runtime preparation step ---
        # Skill.execute() runs preparatory checks (repo scan, sandbox check, lint, git log)
        # and returns a structured JSON context used to enrich the role prompt.
        skill_context: dict = {}
        if hasattr(selected_skill, "execute"):
            try:
                skill_context = selected_skill.execute(
                    role_key=role_key,
                    task=task_context,
                    identifier=identifier,
                    sandbox_dir="/tmp/zero-human-sandbox",
                    run_id=run_id,
                )
                print(f">>> Skill.execute() output for {role_key}: status={skill_context.get('status')} phase={skill_context.get('output', {}).get('phase', 'n/a')}")
            except Exception as skill_exec_err:  # noqa: BLE001 - never block on skill execute failure
                print(f">>> Skill.execute() failed for {role_key} (non-fatal): {skill_exec_err}", file=sys.stderr)

        structured_log_path = None
        if write_event:
            structured_log_path = write_event(
                event_type="agent_run_started",
                identifier=identifier,
                role_key=role_key,
                skill_name=selected_skill.name,
                run_id=run_id,
                payload={
                    "issue_id": issue_id,
                    "agent_id": agent_id,
                    "github_mode": github_mode,
                    "model": target_model,
                    "title": title,
                },
            )
            print(f">>> Structured log path: {structured_log_path}")
        agent_run_id = None
        skill_run_id = None
        run_started_at = time.monotonic()
        if create_agent_run:
            agent_run_id = create_agent_run(
                issue_id=issue_id,
                issue_identifier=identifier,
                heartbeat_run_id=run_id or None,
                agent_id=agent_id or None,
                role_key=role_key,
                github_mode=github_mode,
                status="running",
                metadata={"title": title},
            )
        if create_skill_run:
            skill_run_id = create_skill_run(
                agent_run_id=agent_run_id,
                issue_id=issue_id,
                skill_name=selected_skill.name,
                model=target_model,
                status="running",
                input_summary=f"{identifier} - {title}",
                metadata={"role_key": role_key},
            )
        if run_bash:
            run_bash(["/usr/bin/openclaw", "models", "set", target_model], env=env, check=False)
            # Full removal including .git so each run starts from a clean slate.
            # "rm -rf /tmp/zero-human-sandbox/*" misses hidden dirs (.git) and
            # leaves stale branch state that causes wrong head branch on PR creation.
            run_bash("rm -rf /tmp/zero-human-sandbox && mkdir -p /tmp/zero-human-sandbox", check=False)
        else:
            subprocess.run(["/usr/bin/openclaw", "models", "set", target_model], env=env, check=False)
            subprocess.run(
                "rm -rf /tmp/zero-human-sandbox && mkdir -p /tmp/zero-human-sandbox",
                shell=True,
                check=False,
            )
        if ensure_dir:
            ensure_dir("/tmp/zero-human-sandbox")
        else:
            subprocess.run(["mkdir", "-p", "/tmp/zero-human-sandbox"], check=False)

        repo_url = os.environ.get("ZERO_HUMAN_WORKSPACE_REPO_URL")
        if repo_url and clone_repo:
            print(f">>> Auto-initializing sandbox from {repo_url}...")
            clone_repo(repo_url, "/tmp/zero-human-sandbox")

        message = build_role_prompt(
            role_key,
            role_name,
            identifier,
            title,
            description,
            selected_skill.prompt,
            github_mode,
        )
        print(f">>> Running {role_name} phase for {identifier} ...")
        # --- H3: Route main OpenClaw call through tool layer when available ---
        if run_bash:
            result = run_bash(
                ["/usr/bin/openclaw", "agent", "--agent", "main", "-m", message],
                env=env,
                check=False,
                capture_output=True,
            )
        else:
            result = subprocess.run(
                ["/usr/bin/openclaw", "agent", "--agent", "main", "-m", message],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        duration_ms = int((time.monotonic() - run_started_at) * 1000)
        if write_event:
            write_event(
                event_type="agent_run_completed",
                identifier=identifier,
                role_key=role_key,
                skill_name=selected_skill.name,
                run_id=run_id,
                payload={
                    "status_code": result.returncode,
                    "duration_ms": duration_ms,
                    "stdout_chars": len(result.stdout or ""),
                    "stderr_chars": len(result.stderr or ""),
                },
            )
        if log_usage:
            log_usage(
                agent_run_id=agent_run_id,
                skill_run_id=skill_run_id,
                metric_key="stdout_chars",
                metric_value=len(result.stdout or ""),
                unit="chars",
                metadata={"identifier": identifier, "role_key": role_key},
            )
            log_usage(
                agent_run_id=agent_run_id,
                skill_run_id=skill_run_id,
                metric_key="stderr_chars",
                metric_value=len(result.stderr or ""),
                unit="chars",
                metadata={"identifier": identifier, "role_key": role_key},
            )
            log_usage(
                agent_run_id=agent_run_id,
                skill_run_id=skill_run_id,
                metric_key="run_duration_ms",
                metric_value=duration_ms,
                unit="ms",
                metadata={"identifier": identifier, "role_key": role_key},
            )
        s3_log_payload = (
            f"identifier={identifier}\n"
            f"role={role_key}\n"
            f"status_code={result.returncode}\n"
            f"stdout:\n{result.stdout or ''}\n\n"
            f"stderr:\n{result.stderr or ''}\n"
        )
        s3_log_uri = maybe_upload_run_log(
            identifier=identifier,
            role_key=role_key,
            run_id=run_id,
            payload=s3_log_payload,
        )
        if s3_log_uri:
            print(f">>> Uploaded run log to {s3_log_uri}")
        if result.returncode != 0:
            if complete_skill_run:
                complete_skill_run(
                    skill_run_id=skill_run_id,
                    status="failed",
                    duration_ms=duration_ms,
                    output_summary=(result.stderr or result.stdout or "")[-500:],
                    metadata={"return_code": result.returncode},
                )
            if complete_agent_run:
                complete_agent_run(
                    agent_run_id=agent_run_id,
                    status="failed",
                    duration_ms=duration_ms,
                    error_message=(result.stderr or result.stdout or "")[-500:],
                    metadata={"return_code": result.returncode},
                )
            error_body = (result.stderr if result.stderr else result.stdout)[-1200:]
            patch_issue(
                api_base,
                api_key,
                run_id,
                issue_id,
                {
                    "status": "blocked",
                    "comment": (
                        f"**{role_name} failed during cascade phase.**\n\n"
                        "Blocking this issue for investigation.\n\n"
                        f"```plaintext\n{error_body}\n```\n\n"
                        f"{f'S3 log: {s3_log_uri}' if s3_log_uri else 'S3 log unavailable.'}"
                    ),
                },
            )
            raise RuntimeError(f"{role_name} phase failed with code {result.returncode}")
        else:
            if complete_skill_run:
                complete_skill_run(
                    skill_run_id=skill_run_id,
                    status="succeeded",
                    duration_ms=duration_ms,
                    output_summary=(result.stdout or "")[-500:],
                    metadata={"return_code": result.returncode},
                )
            if complete_agent_run:
                complete_agent_run(
                    agent_run_id=agent_run_id,
                    status="succeeded",
                    duration_ms=duration_ms,
                    metadata={"return_code": result.returncode},
                )

            # --- H2: Sweep sandbox for large files and offload to S3 after role success ---
            # Files >= 1MB are uploaded to S3 and deleted locally to prevent EC2 disk buildup.
            if sweep_sandbox_output:
                try:
                    offloaded_uris = sweep_sandbox_output(
                        "/tmp/zero-human-sandbox",
                        identifier=identifier,
                        run_id=run_id,
                        delete_after_upload=True,
                    )
                    if offloaded_uris:
                        print(f">>> S3 sweep offloaded {len(offloaded_uris)} large file(s) for {identifier}: {offloaded_uris}")
                        if write_event:
                            write_event(
                                event_type="sandbox_swept",
                                identifier=identifier,
                                role_key=role_key,
                                skill_name=selected_skill.name,
                                run_id=run_id,
                                payload={"offloaded_uris": offloaded_uris},
                            )
                except Exception as sweep_err:  # noqa: BLE001 - never block on sweep failure
                    print(f">>> S3 sweep failed for {identifier} (non-fatal): {sweep_err}", file=sys.stderr)

        if is_scribe:
            workspace_dir = os.environ.get("ZERO_HUMAN_WORKSPACE_DIR", "/tmp/zero-human-sandbox").strip()
            created_readme = ensure_project_readme(workspace_dir, identifier, title, description)
            if created_readme:
                print(f">>> Scribe safeguard created missing README: {created_readme}")
                if write_event:
                    write_event(
                        event_type="scribe_readme_generated",
                        identifier=identifier,
                        role_key=role_key,
                        skill_name=selected_skill.name,
                        run_id=run_id,
                        payload={"path": created_readme},
                    )
            combined_output = f"{result.stdout or ''}\n{result.stderr or ''}"
            # In tool_first mode, ignore PR URLs emitted by Scribe and always route
            # PR creation through deterministic tool automation.
            if github_mode == "tool_first":
                pr_url = None
            else:
                pr_url = extract_pr_url(combined_output) or extract_pr_url_from_openclaw_sessions()
            auto_pr_enabled = os.environ.get("ZERO_HUMAN_AUTO_PR_FALLBACK", "1").strip().lower() not in {
                "0",
                "false",
                "no",
            }
            should_try_auto_pr = (
                auto_pr_enabled
                and create_pr_from_repo is not None
                and (
                    github_mode == "tool_first"
                    or (github_mode == "legacy_first" and not pr_url)
                )
            )
            if should_try_auto_pr and not pr_url:
                base_branch = os.environ.get("ZERO_HUMAN_PR_BASE_BRANCH", "").strip() or "main"
                workspace_repo_url = os.environ.get("ZERO_HUMAN_WORKSPACE_REPO_URL", "").strip()

                # Remote lock: re-point origin to the workspace repo immediately before
                # PR fallback, then verify shared ancestry with origin/<base>.
                if workspace_repo_url:
                    try:
                        if run_bash:
                            set_origin = run_bash(
                                ["git", "remote", "set-url", "origin", workspace_repo_url],
                                cwd=workspace_dir,
                                check=False,
                                capture_output=True,
                            )
                            if set_origin.returncode != 0:
                                add_origin = run_bash(
                                    ["git", "remote", "add", "origin", workspace_repo_url],
                                    cwd=workspace_dir,
                                    check=False,
                                    capture_output=True,
                                )
                                if add_origin.returncode != 0:
                                    raise RuntimeError(
                                        f"unable to set origin to workspace repo: {(set_origin.stderr or '').strip() or (add_origin.stderr or '').strip()}"
                                    )
                            fetch_base = run_bash(
                                ["git", "fetch", "origin", base_branch],
                                cwd=workspace_dir,
                                check=False,
                                capture_output=True,
                            )
                            if fetch_base.returncode != 0:
                                raise RuntimeError(
                                    f"unable to fetch origin/{base_branch}: {(fetch_base.stderr or '').strip()}"
                                )
                            merge_base = run_bash(
                                ["git", "merge-base", "HEAD", f"origin/{base_branch}"],
                                cwd=workspace_dir,
                                check=False,
                                capture_output=True,
                            )
                            if merge_base.returncode != 0:
                                # Recovery path: rebuild branch from origin/<base> and
                                # cherry-pick latest commit so PR flow can proceed.
                                current_branch_result = run_bash(
                                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                    cwd=workspace_dir,
                                    check=False,
                                    capture_output=True,
                                )
                                head_sha_result = run_bash(
                                    ["git", "rev-parse", "HEAD"],
                                    cwd=workspace_dir,
                                    check=False,
                                    capture_output=True,
                                )
                                source_branch = (current_branch_result.stdout or "").strip()
                                head_sha = (head_sha_result.stdout or "").strip()
                                if current_branch_result.returncode != 0 or head_sha_result.returncode != 0 or not head_sha:
                                    raise RuntimeError(
                                        f"branch has no common history with origin/{base_branch} after origin lock"
                                    )
                                recovery_branch = source_branch if source_branch and source_branch != "HEAD" else f"{identifier.lower()}-feature"
                                reset_branch = run_bash(
                                    ["git", "checkout", "-B", recovery_branch, f"origin/{base_branch}"],
                                    cwd=workspace_dir,
                                    check=False,
                                    capture_output=True,
                                )
                                if reset_branch.returncode != 0:
                                    raise RuntimeError(
                                        f"failed recovery checkout to origin/{base_branch}: {(reset_branch.stderr or '').strip()}"
                                    )
                                cherry_pick = run_bash(
                                    ["git", "cherry-pick", head_sha],
                                    cwd=workspace_dir,
                                    check=False,
                                    capture_output=True,
                                )
                                if cherry_pick.returncode != 0:
                                    raise RuntimeError(
                                        f"failed recovery cherry-pick from {head_sha}: {(cherry_pick.stderr or '').strip()}"
                                    )
                        else:
                            set_origin = subprocess.run(
                                ["git", "remote", "set-url", "origin", workspace_repo_url],
                                cwd=workspace_dir,
                                check=False,
                                capture_output=True,
                                text=True,
                            )
                            if set_origin.returncode != 0:
                                add_origin = subprocess.run(
                                    ["git", "remote", "add", "origin", workspace_repo_url],
                                    cwd=workspace_dir,
                                    check=False,
                                    capture_output=True,
                                    text=True,
                                )
                                if add_origin.returncode != 0:
                                    raise RuntimeError(
                                        f"unable to set origin to workspace repo: {(set_origin.stderr or '').strip() or (add_origin.stderr or '').strip()}"
                                    )
                            fetch_base = subprocess.run(
                                ["git", "fetch", "origin", base_branch],
                                cwd=workspace_dir,
                                check=False,
                                capture_output=True,
                                text=True,
                            )
                            if fetch_base.returncode != 0:
                                raise RuntimeError(
                                    f"unable to fetch origin/{base_branch}: {(fetch_base.stderr or '').strip()}"
                                )
                            merge_base = subprocess.run(
                                ["git", "merge-base", "HEAD", f"origin/{base_branch}"],
                                cwd=workspace_dir,
                                check=False,
                                capture_output=True,
                                text=True,
                            )
                            if merge_base.returncode != 0:
                                # Recovery path: rebuild branch from origin/<base> and
                                # cherry-pick latest commit so PR flow can proceed.
                                current_branch_result = subprocess.run(
                                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                    cwd=workspace_dir,
                                    check=False,
                                    capture_output=True,
                                    text=True,
                                )
                                head_sha_result = subprocess.run(
                                    ["git", "rev-parse", "HEAD"],
                                    cwd=workspace_dir,
                                    check=False,
                                    capture_output=True,
                                    text=True,
                                )
                                source_branch = (current_branch_result.stdout or "").strip()
                                head_sha = (head_sha_result.stdout or "").strip()
                                if current_branch_result.returncode != 0 or head_sha_result.returncode != 0 or not head_sha:
                                    raise RuntimeError(
                                        f"branch has no common history with origin/{base_branch} after origin lock"
                                    )
                                recovery_branch = source_branch if source_branch and source_branch != "HEAD" else f"{identifier.lower()}-feature"
                                reset_branch = subprocess.run(
                                    ["git", "checkout", "-B", recovery_branch, f"origin/{base_branch}"],
                                    cwd=workspace_dir,
                                    check=False,
                                    capture_output=True,
                                    text=True,
                                )
                                if reset_branch.returncode != 0:
                                    raise RuntimeError(
                                        f"failed recovery checkout to origin/{base_branch}: {(reset_branch.stderr or '').strip()}"
                                    )
                                cherry_pick = subprocess.run(
                                    ["git", "cherry-pick", head_sha],
                                    cwd=workspace_dir,
                                    check=False,
                                    capture_output=True,
                                    text=True,
                                )
                                if cherry_pick.returncode != 0:
                                    raise RuntimeError(
                                        f"failed recovery cherry-pick from {head_sha}: {(cherry_pick.stderr or '').strip()}"
                                    )
                    except Exception as pre_pr_err:
                        raise RuntimeError(
                            f"Pre-PR remote lock failed for {identifier}: {pre_pr_err}"
                        ) from pre_pr_err
                try:
                    pr_url = create_pr_from_repo(
                        workspace_dir,
                        title=f"[{identifier}] {title}",
                        body=(
                            f"Automated fallback PR creation for {identifier}.\n\n"
                            f"Generated by Scribe phase in zero-human cascade."
                        ),
                        base_branch=base_branch,
                    )
                    print(f">>> Auto-created PR for {identifier}: {pr_url}")
                    if write_event:
                        write_event(
                            event_type="pr_auto_created",
                            identifier=identifier,
                            role_key=role_key,
                            skill_name=selected_skill.name,
                            run_id=run_id,
                            payload={"pr_url": pr_url, "workspace_dir": workspace_dir},
                        )
                except Exception as auto_pr_err:
                    print(f"Auto PR fallback failed for {identifier}: {auto_pr_err}", file=sys.stderr)
                    if write_event:
                        write_event(
                            event_type="pr_auto_create_failed",
                            identifier=identifier,
                            role_key=role_key,
                            skill_name=selected_skill.name,
                            run_id=run_id,
                            payload={"error": str(auto_pr_err)},
                        )
            if not pr_url:
                patch_issue(
                    api_base,
                    api_key,
                    run_id,
                    issue_id,
                    {
                        "status": "blocked",
                        "comment": (
                            "**Scribe completed coding but no PR URL was detected.**\n\n"
                            "Please create one PR and include the URL in output/comments before closing."
                        ),
                    },
                )
                raise RuntimeError("Scribe phase finished without a detectable PR URL")
            if write_event:
                write_event(
                    event_type="pr_detected",
                    identifier=identifier,
                    role_key=role_key,
                    skill_name=selected_skill.name,
                    run_id=run_id,
                    payload={"pr_url": pr_url},
                )

        next_idx = current_idx + 1 if current_idx is not None else None
        if next_idx is not None and next_idx < len(role_agents):
            next_role = role_agents[next_idx]
            if not next_role["agent_id"]:
                raise RuntimeError(
                    f"Next role agent not resolvable for {next_role['name']}. "
                    f"Set ZERO_HUMAN_{next_role['key'].upper()}_AGENT_ID in environment."
                )
            patch_issue(
                api_base,
                api_key,
                run_id,
                issue_id,
                {
                    "status": "todo",
                    "assigneeAgentId": next_role["agent_id"],
                    "comment": (
                        f"{role_name} phase complete for {identifier}. "
                        f"Handoff to {next_role['name']}."
                    ),
                },
            )
            print(f">>> Handoff complete: {role_name} -> {next_role['name']} for {identifier}")
        else:
            done_comment = f"{role_name} phase complete. Cascade finished for {identifier}."
            if s3_log_uri:
                done_comment = f"{done_comment}\nS3 log: {s3_log_uri}"
            if structured_log_path:
                done_comment = f"{done_comment}\nStructured log: {structured_log_path}"
            patch_issue(
                api_base,
                api_key,
                run_id,
                issue_id,
                {
                    "status": "done",
                    "comment": done_comment,
                },
            )
            print(f">>> Cascade complete. Closed {identifier}.")

        sys.exit(0)
    except Exception as e:
        print(f"Bridge execution failed: {e}", file=sys.stderr)
        sys.exit(1)


def run_issue(issue_id: str, repo_url: str | None = None, paperclip_context: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Programmatic entry point for the cascade bridge, intended for use by Celery workers.
    Sets up the environment and executes the main cascade logic.
    """
    import os
    from typing import Any

    if paperclip_context:
        for k, v in paperclip_context.items():
            os.environ[k] = str(v)

    # If repo_url is provided, ensure it's in env for tools to use
    if repo_url:
        os.environ["ZERO_HUMAN_WORKSPACE_REPO_URL"] = repo_url

    # The original script relies on environment variables set by the heartbeat.
    # We maintain this behavior for compatibility but can wrap the logic here.
    try:
        # Since main() ends with sys.exit(0), we need to handle that.
        import contextlib
        import io

        f = io.StringIO()
        with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
            try:
                main()
            except SystemExit as e:
                if e.code != 0:
                    return {"ok": False, "error": f"Cascade exited with code {e.code}", "logs": f.getvalue()}

        return {"ok": True, "logs": f.getvalue()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    main()
