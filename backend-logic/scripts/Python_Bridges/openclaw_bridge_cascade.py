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


def api_request(method, url, api_key, run_id, payload=None, *, include_auth=True):
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if include_auth:
        headers["Authorization"] = f"Bearer {api_key}"
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
        {
            "agentId": agent_id,
            "expectedStatuses": [
                "todo",
                "backlog",
                "blocked",
                "in_progress",
                "awaiting_human_approval",
            ],
        },
    )


MAJOR_DECISION_TYPE = "major_decision_guardrail"
REQUIRES_APPROVAL_CATEGORIES = (
    "pr_merge_protected_push",
    "deploy_prod_config_change",
    "destructive_data_action",
    "security_sensitive_policy_change",
    "high_cost_model_provider_switch",
)


def list_issue_approvals(api_base, api_key, run_id, issue_id):
    _, payload = api_request("GET", f"{api_base}/issues/{issue_id}/approvals", api_key, run_id)
    if isinstance(payload, list):
        return payload
    return []


def create_company_approval(api_base, api_key, run_id, company_id, payload):
    return api_request(
        "POST",
        f"{api_base}/companies/{urllib.parse.quote(company_id)}/approvals",
        api_key,
        run_id,
        payload,
    )


def _maybe_add_category(categories, text, pattern, category):
    if re.search(pattern, text, flags=re.IGNORECASE):
        categories.add(category)


def evaluate_major_decision_policy(issue, *, role_key, llm_provider, llm_model):
    text = " ".join(
        [
            str(issue.get("title", "") or ""),
            str(issue.get("description", "") or ""),
        ]
    )
    categories = set()
    if role_key == "scribe":
        categories.add("pr_merge_protected_push")
    _maybe_add_category(
        categories,
        text,
        r"\b(deploy|deployment|production|prod|rollout|release|k8s|helm|terraform|feature flag)\b",
        "deploy_prod_config_change",
    )
    _maybe_add_category(
        categories,
        text,
        r"\b(delete|drop table|truncate|destroy|wipe|erase|remove all|purge)\b",
        "destructive_data_action",
    )
    _maybe_add_category(
        categories,
        text,
        r"\b(permission|policy|rbac|oauth|secret|api key|credential|iam|access control)\b",
        "security_sensitive_policy_change",
    )
    llm_change_hint = bool(
        re.search(r"\b(model|provider|llm)\b", text, flags=re.IGNORECASE)
        and re.search(r"\b(change|switch|migrate|upgrade|replace)\b", text, flags=re.IGNORECASE)
    )
    expensive_target = bool(
        re.search(
            r"(claude[-_ ]?opus|gpt[-_ ]?(4|5)|o3|r1|70b|405b|ultra|sonnet)",
            f"{llm_provider} {llm_model}",
            flags=re.IGNORECASE,
        )
    )
    if llm_change_hint and expensive_target:
        categories.add("high_cost_model_provider_switch")
    return {
        "requires_approval": bool(categories),
        "categories": sorted(categories),
    }


def enforce_major_decision_guardrails(
    *,
    api_base,
    api_key,
    run_id,
    company_id,
    agent_id,
    role_key,
    issue,
    llm_provider,
    llm_model,
):
    if _truthy(os.environ.get("ZERO_HUMAN_MAJOR_DECISION_APPROVAL_DISABLED")):
        return {"paused": False, "reason": "guardrail_disabled"}

    policy = evaluate_major_decision_policy(
        issue,
        role_key=role_key,
        llm_provider=str(llm_provider or ""),
        llm_model=str(llm_model or ""),
    )
    categories = [c for c in policy["categories"] if c in REQUIRES_APPROVAL_CATEGORIES]
    if not categories:
        return {"paused": False, "reason": "not_major"}

    issue_id = str(issue.get("id", "")).strip()
    identifier = str(issue.get("identifier", issue_id[:8])).strip()
    linked_approvals = [
        a
        for a in list_issue_approvals(api_base, api_key, run_id, issue_id)
        if str(a.get("type", "")).strip() == MAJOR_DECISION_TYPE
    ]
    approved = [a for a in linked_approvals if str(a.get("status", "")).strip() == "approved"]
    if approved:
        return {
            "paused": False,
            "reason": "already_approved",
            "approval_id": str(approved[0].get("id", "")).strip() or None,
            "categories": categories,
        }

    pending = [a for a in linked_approvals if str(a.get("status", "")).strip() in {"pending", "revision_requested"}]
    approval_id = str(pending[0].get("id", "")).strip() if pending else None
    if not approval_id:
        payload = {
            "type": MAJOR_DECISION_TYPE,
            "requestedByAgentId": agent_id,
            "issueIds": [issue_id],
            "payload": {
                "guardrail_version": "v1",
                "identifier": identifier,
                "issue_id": issue_id,
                "issue_title": str(issue.get("title", "") or ""),
                "requested_role": role_key,
                "run_id": run_id or None,
                "required_categories": categories,
                "planned_actions": [
                    "Evaluate execution plan for major decision risk categories",
                    "Pause execution before major actions",
                    "Resume only after explicit human approval",
                ],
                "llm_provider": llm_provider or None,
                "llm_model": llm_model or None,
            },
        }
        _, created = create_company_approval(api_base, api_key, run_id, company_id, payload)
        approval_id = str(created.get("id", "")).strip() or None

    comment = (
        "Human approval is required before executing major actions.\n\n"
        f"- approval_id: {approval_id or 'pending'}\n"
        f"- role: {role_key}\n"
        f"- categories: {', '.join(categories)}\n"
        "- status: awaiting_human_approval"
    )
    patch_issue(
        api_base,
        api_key,
        run_id,
        issue_id,
        {"status": "awaiting_human_approval", "comment": comment},
    )
    return {
        "paused": True,
        "reason": "awaiting_human_approval",
        "approval_id": approval_id,
        "categories": categories,
    }


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def dynamic_llm_enabled(env):
    return _truthy((env or os.environ).get("ZERO_HUMAN_DYNAMIC_LLM_ENABLED"))


def _safe_json_loads(raw):
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_llm_payload(payload):
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("llm"), dict):
        return payload
    settings = payload.get("settings")
    if isinstance(settings, dict) and isinstance(settings.get("llm"), dict):
        return settings
    return None


def _canonicalize_model(provider, model):
    provider_text = str(provider or "").strip().lower()
    model_text = str(model or "").strip()
    if not model_text:
        return model_text
    if "/" in model_text:
        return model_text

    prefix = None
    if "openai" in provider_text or provider_text == "vllm_openai_compatible":
        prefix = "openai"
    elif "anthropic" in provider_text:
        prefix = "anthropic"
    elif "google" in provider_text or "gemini" in provider_text:
        prefix = "google"

    if not prefix:
        return model_text
    return f"{prefix}/{model_text}"


def fetch_company_llm_settings(api_base, api_key, run_id, company_id):
    url = f"{api_base}/companies/{urllib.parse.quote(company_id)}/llm-settings"
    try:
        _, payload = api_request("GET", url, api_key, run_id)
    except Exception as err:
        # Local-trusted orchestrator instances may expose this route as board-only.
        # For loopback API URLs, retry without bearer auth so middleware can use
        # the implicit local board actor and still return company settings.
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").strip().lower()
        is_loopback = host in {"127.0.0.1", "localhost", "::1"}
        if not (is_loopback and "Board access required" in str(err)):
            raise
        _, payload = api_request("GET", url, None, run_id, include_auth=False)
    return _normalize_llm_payload(payload)


def _resolve_from_llm_payload(payload, role_key):
    config = _normalize_llm_payload(payload)
    if not config:
        return None
    llm = config.get("llm")
    if not isinstance(llm, dict):
        return None

    default_provider = str(llm.get("default_provider", "")).strip()
    default_model = str(llm.get("default_model", "")).strip()
    providers = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}
    role_models = llm.get("role_models") if isinstance(llm.get("role_models"), dict) else {}
    guardrails = llm.get("guardrails") if isinstance(llm.get("guardrails"), dict) else {}
    role_entry = role_models.get(role_key) if isinstance(role_models.get(role_key), dict) else {}

    provider = str(role_entry.get("provider", "")).strip() or default_provider
    model = str(role_entry.get("model", "")).strip() or default_model
    model = _canonicalize_model(provider, model)
    if not provider or not model:
        return None
    provider_cfg = providers.get(provider) if isinstance(providers.get(provider), dict) else {}

    resolved = {
        "provider": provider,
        "model": model,
        "base_url": str(provider_cfg.get("base_url", "")).strip() or None,
        "api_key": str(provider_cfg.get("api_key", "")).strip() or None,
        "timeout_seconds": provider_cfg.get("timeout_seconds"),
        "allowed_models": guardrails.get("allowed_models") if isinstance(guardrails.get("allowed_models"), list) else [],
        "max_timeout_seconds": guardrails.get("max_timeout_seconds"),
        "max_tokens_per_request": guardrails.get("max_tokens_per_request"),
        "role_retries": guardrails.get("role_retries") if isinstance(guardrails.get("role_retries"), dict) else {},
    }

    # Never propagate masked secrets as active credentials.
    if resolved["api_key"] and resolved["api_key"] in {"***REDACTED***", "REDACTED"}:
        resolved["api_key"] = None
    return resolved


def _resolve_from_env(role_key, env):
    role_var = f"ZERO_HUMAN_ROLE_MODEL_{role_key.upper()}"
    model = (
        env.get(role_var, "").strip()
        or env.get("ZERO_HUMAN_LLM_MODEL", "").strip()
        or env.get("OPENCLAW_MODEL", "").strip()
        or env.get("MODEL", "").strip()
        or "openai/gpt-4o"
    )
    provider = env.get("ZERO_HUMAN_LLM_PROVIDER", "").strip() or "openai_compatible_env"
    model = _canonicalize_model(provider, model)
    base_url = (
        env.get("ZERO_HUMAN_LLM_BASE_URL", "").strip()
        or env.get("OPENAI_BASE_URL", "").strip()
        or env.get("OPENAI_API_BASE", "").strip()
    )
    api_key = (
        env.get("ZERO_HUMAN_LLM_API_KEY", "").strip()
        or env.get("OPENAI_API_KEY", "").strip()
    )
    timeout_raw = env.get("ZERO_HUMAN_LLM_TIMEOUT_SECONDS", "").strip()
    timeout_seconds = int(timeout_raw) if timeout_raw.isdigit() else None
    max_tokens_raw = env.get("ZERO_HUMAN_LLM_MAX_TOKENS", "").strip()
    max_tokens_per_request = int(max_tokens_raw) if max_tokens_raw.isdigit() else None
    role_retries_raw = env.get(f"ZERO_HUMAN_ROLE_RETRIES_{role_key.upper()}", "").strip()
    role_retries = {role_key: int(role_retries_raw)} if role_retries_raw.isdigit() else {}
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url or None,
        "api_key": api_key or None,
        "timeout_seconds": timeout_seconds,
        "allowed_models": [],
        "max_timeout_seconds": timeout_seconds,
        "max_tokens_per_request": max_tokens_per_request,
        "role_retries": role_retries,
    }


def apply_llm_guardrails(config, role_key):
    normalized = dict(config or {})
    model = str(normalized.get("model", "")).strip()
    default_model = model
    allowed_models = [str(item).strip() for item in normalized.get("allowed_models") or [] if str(item).strip()]
    if allowed_models and model and model not in allowed_models:
        fallback_model = default_model if default_model in allowed_models else allowed_models[0]
        normalized["fallback_activated"] = True
        normalized["fallback_reason"] = "model_not_in_allowlist"
        normalized["fallback_from_model"] = model
        normalized["model"] = fallback_model
    max_timeout = normalized.get("max_timeout_seconds")
    timeout = normalized.get("timeout_seconds")
    if isinstance(max_timeout, (int, float)) and max_timeout > 0:
        if not isinstance(timeout, (int, float)) or timeout > max_timeout:
            normalized["timeout_seconds"] = int(max_timeout)
    else:
        normalized["max_timeout_seconds"] = None

    max_tokens = normalized.get("max_tokens_per_request")
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        normalized["max_tokens_per_request"] = None

    role_retries = normalized.get("role_retries") if isinstance(normalized.get("role_retries"), dict) else {}
    retries_value = role_retries.get(role_key)
    retries = int(retries_value) if isinstance(retries_value, int) and retries_value >= 0 else 0
    normalized["resolved_role_retries"] = min(retries, 5)
    normalized["allowed_models"] = allowed_models
    return normalized


def resolve_llm_config(role_key, *, api_base=None, api_key=None, run_id=None, company_id=None, env=None):
    runtime_env = env or os.environ
    if not dynamic_llm_enabled(runtime_env):
        legacy = _resolve_from_env(role_key, runtime_env)
        legacy["source"] = "dynamic_llm_disabled"
        return legacy

    # 1) Heartbeat/company payload injected into runtime env.
    for key in ("COMPANY_LLM_CONFIG_JSON", "ZERO_HUMAN_COMPANY_LLM_CONFIG_JSON"):
        candidate = _safe_json_loads(runtime_env.get(key))
        resolved = _resolve_from_llm_payload(candidate, role_key)
        if resolved:
            resolved["source"] = "heartbeat_payload"
            return resolved

    # 2) DB-stored company settings.
    if api_base and api_key and company_id:
        try:
            db_payload = fetch_company_llm_settings(api_base, api_key, run_id, company_id)
            resolved = _resolve_from_llm_payload(db_payload, role_key)
            if resolved:
                resolved["source"] = "db_company_settings"
                return resolved
        except Exception as fetch_err:  # noqa: BLE001 - non-fatal, continue down precedence chain
            print(f"LLM config DB fetch skipped: {fetch_err}", file=sys.stderr)

    # 3) User-level override (only when enabled by policy flag).
    if _truthy(runtime_env.get("ZERO_HUMAN_LLM_USER_OVERRIDE_ENABLED")) or _truthy(
        runtime_env.get("USER_LLM_OVERRIDE_ENABLED")
    ):
        for key in ("ZERO_HUMAN_USER_LLM_CONFIG_JSON", "USER_LLM_CONFIG_JSON"):
            candidate = _safe_json_loads(runtime_env.get(key))
            resolved = _resolve_from_llm_payload(candidate, role_key)
            if resolved:
                resolved["source"] = "user_override"
                return resolved

    # 4) .env + process env fallback (legacy compatible).
    env_resolved = _resolve_from_env(role_key, runtime_env)
    env_resolved["source"] = "env"
    return env_resolved


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

        llm_config = resolve_llm_config(
            role_key,
            api_base=api_base,
            api_key=api_key,
            run_id=run_id,
            company_id=company_id,
            env=os.environ,
        )
        llm_config = apply_llm_guardrails(llm_config, role_key)
        target_model = llm_config.get("model", os.environ.get("OPENCLAW_MODEL", "openai/gpt-4o"))
        target_provider = llm_config.get("provider", "")
        target_base_url = llm_config.get("base_url")
        target_api_key = llm_config.get("api_key")
        target_timeout = llm_config.get("timeout_seconds")
        target_max_tokens = llm_config.get("max_tokens_per_request")
        role_retry_budget = int(llm_config.get("resolved_role_retries", 0) or 0)

        env["ZERO_HUMAN_LLM_PROVIDER"] = str(target_provider or "")
        env["ZERO_HUMAN_LLM_MODEL"] = str(target_model or "")
        if target_base_url:
            env["ZERO_HUMAN_LLM_BASE_URL"] = str(target_base_url)
            env["OPENAI_BASE_URL"] = str(target_base_url)
            env["OPENAI_API_BASE"] = str(target_base_url)
        if target_api_key:
            env["ZERO_HUMAN_LLM_API_KEY"] = str(target_api_key)
            env["OPENAI_API_KEY"] = str(target_api_key)
        if target_timeout is not None:
            env["ZERO_HUMAN_LLM_TIMEOUT_SECONDS"] = str(target_timeout)
        if target_max_tokens is not None:
            env["ZERO_HUMAN_LLM_MAX_TOKENS"] = str(target_max_tokens)

        print(
            f">>> Resolved LLM for role={role_key}: provider={target_provider or 'n/a'} "
            f"model={target_model} source={llm_config.get('source', 'unknown')}"
        )
        if llm_config.get("fallback_activated"):
            print(
                ">>> LLM guardrail fallback activated: "
                f"reason={llm_config.get('fallback_reason')} "
                f"from={llm_config.get('fallback_from_model')} "
                f"to={target_model}"
            )
            if write_event:
                write_event(
                    event_type="llm_fallback_activated",
                    identifier=identifier,
                    role_key=role_key,
                    skill_name=getattr(selected_skill, "name", None) if "selected_skill" in locals() else None,
                    run_id=run_id,
                    payload={
                        "provider": target_provider or "n/a",
                        "from_model": llm_config.get("fallback_from_model"),
                        "to_model": target_model,
                        "reason": llm_config.get("fallback_reason"),
                    },
                )
        guardrail_state = enforce_major_decision_guardrails(
            api_base=api_base,
            api_key=api_key,
            run_id=run_id,
            company_id=company_id,
            agent_id=agent_id,
            role_key=role_key,
            issue=issue,
            llm_provider=target_provider,
            llm_model=target_model,
        )
        if guardrail_state.get("paused"):
            print(
                ">>> Execution paused pending human approval "
                f"(approval_id={guardrail_state.get('approval_id')}, "
                f"categories={guardrail_state.get('categories', [])})"
            )
            sys.exit(0)

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
        attempt = 0
        result = None
        while True:
            llm_attempt_started_at = time.monotonic()
            if log_usage:
                log_usage(
                    agent_run_id=agent_run_id,
                    skill_run_id=skill_run_id,
                    metric_key="llm_request_total",
                    metric_value=1,
                    unit="count",
                    metadata={
                        "identifier": identifier,
                        "role_key": role_key,
                        "provider": target_provider or "unknown",
                        "model": target_model,
                        "attempt": attempt + 1,
                    },
                )
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
            llm_attempt_latency_ms = int((time.monotonic() - llm_attempt_started_at) * 1000)
            if log_usage:
                log_usage(
                    agent_run_id=agent_run_id,
                    skill_run_id=skill_run_id,
                    metric_key="llm_request_latency_ms",
                    metric_value=llm_attempt_latency_ms,
                    unit="ms",
                    metadata={
                        "identifier": identifier,
                        "role_key": role_key,
                        "provider": target_provider or "unknown",
                        "model": target_model,
                        "attempt": attempt + 1,
                    },
                )
            if result.returncode == 0:
                break
            if log_usage:
                log_usage(
                    agent_run_id=agent_run_id,
                    skill_run_id=skill_run_id,
                    metric_key="llm_request_error_total",
                    metric_value=1,
                    unit="count",
                    metadata={
                        "identifier": identifier,
                        "role_key": role_key,
                        "provider": target_provider or "unknown",
                        "model": target_model,
                        "attempt": attempt + 1,
                    },
                )
            if attempt >= role_retry_budget:
                break
            attempt += 1
            print(
                f">>> Retry {attempt}/{role_retry_budget} for role={role_key} "
                f"provider={target_provider or 'unknown'} model={target_model}"
            )
        if result is None:
            raise RuntimeError("OpenClaw execution did not produce a result")
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
