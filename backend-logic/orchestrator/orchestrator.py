#!/usr/bin/env python3
"""
Intelligent Orchestrator: LLM-based dynamic task planning with rule-based fallback.

Flow:
  1. Try LLM call to generate dynamic plan (uses OPENAI_API_KEY if set).
  2. Validate and sanitize the LLM output.
  3. If LLM unavailable or returns invalid plan, fall back to rule-based routing.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

try:
    from agents.registry import DEFAULT_ROLE_ORDER, VALID_ROLE_KEYS
except Exception:  # noqa: BLE001
    DEFAULT_ROLE_ORDER = ["architect", "grunt", "pedant", "scribe"]
    VALID_ROLE_KEYS = tuple(DEFAULT_ROLE_ORDER)


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

_PLAN_SYSTEM_PROMPT = (
    "You are an AI task planner for a software engineering pipeline. "
    "Given a task, decide which agents to run and in what order. "
    "The valid agents are: architect, grunt, pedant, scribe.\n"
    "- architect: plans and designs (always first for complex work)\n"
    "- grunt: implements code changes\n"
    "- pedant: reviews quality and correctness\n"
    "- scribe: finalizes docs, creates PR (always last)\n\n"
    "Return ONLY a JSON object in this exact format, nothing else:\n"
    "Include every role the pipeline needs, in order (scribe is always last).\n"
    "{\n"
    '  "plan": [\n'
    '    {"agent": "architect", "task": "brief task description"},\n'
    '    {"agent": "grunt", "task": "brief task description"},\n'
    '    {"agent": "pedant", "task": "brief task description"},\n'
    '    {"agent": "scribe", "task": "brief task description"}\n'
    "  ]\n"
    "}"
)


def _build_user_prompt(task: dict[str, Any]) -> str:
    title = str(task.get("title", "") or "").strip()
    description = str(task.get("description", "") or "").strip()
    identifier = str(task.get("identifier", "") or "").strip()
    return (
        f"Task ID: {identifier}\n"
        f"Title: {title}\n"
        f"Description: {description}\n\n"
        "Return the execution plan as JSON."
    )


def _call_llm(task: dict[str, Any]) -> list[dict[str, str]] | None:
    """
    Call OpenAI-compatible API to get a dynamic execution plan.
    Returns list of plan steps or None if call fails/is unavailable.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    api_base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com").rstrip("/")
    model = os.environ.get("ORCHESTRATOR_MODEL", "gpt-4o-mini")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(task)},
        ],
        "max_tokens": 300,
        "temperature": 0.2,
    }

    req = urllib.request.Request(
        url=f"{api_base}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"].strip()
            parsed = json.loads(content)
            return parsed.get("plan") if isinstance(parsed.get("plan"), list) else None
    except Exception:  # noqa: BLE001 - always fall back to rule-based
        return None


# ---------------------------------------------------------------------------
# Plan validation
# ---------------------------------------------------------------------------

def _dedupe_and_validate(role_keys: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for key in role_keys:
        if key in VALID_ROLE_KEYS and key not in seen:
            ordered.append(key)
            seen.add(key)
    return ordered


def _validate_llm_plan(raw_plan: list[dict[str, str]]) -> list[str]:
    """Extract and validate agent keys from LLM plan output."""
    keys: list[str] = []
    for step in raw_plan:
        if isinstance(step, dict):
            agent = str(step.get("agent", "")).strip().lower()
            if agent:
                keys.append(agent)
    return _dedupe_and_validate(keys)


def _extend_if_default_role_prefix(plan: list[str]) -> list[str]:
    """
    If the plan is exactly DEFAULT_ROLE_ORDER[:n] for some n < len(DEFAULT),
    extend to the full default chain.

    LLM planners often copy the prompt example and stop after architect+grunt,
    which would otherwise truncate the cascade and close the issue early.
    Custom plans like ['pedant', 'scribe'] are left unchanged.
    """
    if not plan:
        return list(DEFAULT_ROLE_ORDER)
    n = len(plan)
    if n >= len(DEFAULT_ROLE_ORDER):
        return plan
    if plan == list(DEFAULT_ROLE_ORDER[:n]):
        return list(DEFAULT_ROLE_ORDER)
    return plan


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------

def _normalize_text(task: dict[str, Any]) -> str:
    title = str(task.get("title", "") or "")
    description = str(task.get("description", "") or "")
    return f"{title}\n{description}".lower()


def _rule_based_plan(task: dict[str, Any]) -> list[str]:
    text = _normalize_text(task)

    lightweight_markers = ("typo", "readme", "docs", "documentation", "comment-only", "formatting")
    if any(m in text for m in lightweight_markers):
        return ["pedant", "scribe"]

    feature_markers = (
        "frontend", "backend", "api", "endpoint", "database",
        "migration", "auth", "integration", "feature",
    )
    if any(m in text for m in feature_markers):
        return list(DEFAULT_ROLE_ORDER)

    return list(DEFAULT_ROLE_ORDER)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def orchestrate_task(task: dict[str, Any]) -> list[str]:
    """
    Return an ordered role plan for cascade execution.

    Tries LLM-based planning first; falls back to rule-based on any failure.
    Always returns a non-empty list of valid role keys.

    Emits a structured log line in this format for auditability:
      ORCHESTRATOR_PLAN identifier=<id> planner_mode=<llm|fallback> plan=<list>
    """
    identifier = task.get("identifier", "unknown")

    # --- LLM path ---
    llm_raw = _call_llm(task)
    if llm_raw is not None:
        plan = _validate_llm_plan(llm_raw)
        if plan:
            plan = _extend_if_default_role_prefix(plan)
            print(f"ORCHESTRATOR_PLAN identifier={identifier} planner_mode=llm plan={plan}")
            return plan
        print(f">>> Orchestrator [LLM] returned invalid plan for {identifier}. Using rule-based fallback.")

    # --- Rule-based fallback ---
    plan = _rule_based_plan(task)
    plan = _extend_if_default_role_prefix(plan)
    print(f"ORCHESTRATOR_PLAN identifier={identifier} planner_mode=fallback plan={plan}")
    return plan


def sanitize_plan(plan: list[str] | None) -> list[str]:
    """
    Normalize any external plan into supported role keys.
    Falls back to full default if empty or fully invalid.
    """
    normalized = _dedupe_and_validate(plan or [])
    if not normalized:
        return list(DEFAULT_ROLE_ORDER)
    return _extend_if_default_role_prefix(normalized)
