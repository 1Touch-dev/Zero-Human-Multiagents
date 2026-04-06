#!/usr/bin/env python3
import glob
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


def load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")


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


def resolve_role_agents(api_base, api_key, run_id, company_id, env):
    role_specs = [
        ("architect", "The Architect"),
        ("grunt", "The Grunt"),
        ("pedant", "The Pedant"),
        ("scribe", "The Scribe"),
    ]
    _, all_agents = api_request(
        "GET",
        f"{api_base}/companies/{urllib.parse.quote(company_id)}/agents",
        api_key,
        run_id,
    )
    all_agents = all_agents if isinstance(all_agents, list) else []
    resolved = []
    for key, default_name in role_specs:
        explicit_id = env.get(f"ZERO_HUMAN_{key.upper()}_AGENT_ID", "").strip()
        if explicit_id:
            resolved.append({"key": key, "name": default_name, "agent_id": explicit_id})
            continue
        lookup_name = env.get(f"ZERO_HUMAN_{key.upper()}_AGENT_NAME", default_name).strip()
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


def build_role_prompt(role_key, role_name, identifier, title, description):
    delivery_guard = (
        "CRITICAL DELIVERY OWNERSHIP RULES:\n"
        "- ONLY The Scribe may push branches or create pull requests.\n"
        "- The Architect, The Grunt, and The Pedant MUST NOT run `git push` or `gh pr create`.\n"
        "- Non-scribe roles must hand off implementation/testing artifacts only."
    )
    role_specific = {
        "architect": (
            "ROLE DIRECTIVE (ARCHITECT): analyze requirements, inspect stack, and produce an implementation plan. "
            "You may make preparatory code edits, but do NOT create a PR."
        ),
        "grunt": (
            "ROLE DIRECTIVE (GRUNT): perform implementation and integration work. "
            "Do NOT create a PR. Leave explicit handoff notes for Pedant."
        ),
        "pedant": (
            "ROLE DIRECTIVE (PEDANT): run quality checks, fix issues, and improve correctness. "
            "Do NOT create a PR. Leave explicit handoff notes for Scribe."
        ),
        "scribe": (
            "ROLE DIRECTIVE (SCRIBE): finalize documentation/changelog, verify final quality gates, "
            "then create exactly one PR. You MUST print a single bare line exactly in this form "
            "(copy-paste the real URL): PR_URL: https://github.com/<org>/<repo>/pull/<number> "
            "so automation can detect it."
        ),
    }.get(role_key, "ROLE DIRECTIVE: execute your assigned phase and provide explicit logs.")
    return (
        f"You are {role_name}. "
        f"You are handling ticket {identifier} - {title}. "
        "Execute only your role-specific phase now, leave clear artifacts for the next role, "
        "and print explicit terminal logs for what you changed. "
        "Work strictly in /tmp/zero-human-sandbox/. "
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


def main():
    load_env()
    try:
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")
        if os.environ.get("GITHUB_TOKEN", "").strip():
            env["GITHUB_TOKEN"] = os.environ["GITHUB_TOKEN"]

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

        role_agents = resolve_role_agents(api_base, api_key, run_id, company_id, env)
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

        target_model = os.environ.get("OPENCLAW_MODEL", "openai/gpt-4o")
        subprocess.run(["/usr/bin/openclaw", "models", "set", target_model], env=env, check=False)
        subprocess.run("rm -rf /tmp/zero-human-sandbox/*", shell=True, check=False)
        subprocess.run(["mkdir", "-p", "/tmp/zero-human-sandbox"], check=False)

        message = build_role_prompt(role_key, role_name, identifier, title, description)
        print(f">>> Running {role_name} phase for {identifier} ...")
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
        if result.returncode != 0:
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
                        f"```plaintext\n{error_body}\n```"
                    ),
                },
            )
            raise RuntimeError(f"{role_name} phase failed with code {result.returncode}")

        if is_scribe:
            combined_output = f"{result.stdout or ''}\n{result.stderr or ''}"
            pr_url = extract_pr_url(combined_output) or extract_pr_url_from_openclaw_sessions()
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
            patch_issue(
                api_base,
                api_key,
                run_id,
                issue_id,
                {
                    "status": "done",
                    "comment": f"{role_name} phase complete. Cascade finished for {identifier}.",
                },
            )
            print(f">>> Cascade complete. Closed {identifier}.")

        sys.exit(0)
    except Exception as e:
        print(f"Bridge execution failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
