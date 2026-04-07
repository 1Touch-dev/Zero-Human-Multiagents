#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

try:
    from agents.registry import DEFAULT_ROLE_ORDER, VALID_ROLE_KEYS
except Exception:  # noqa: BLE001 - keep orchestrator resilient if registry import fails
    DEFAULT_ROLE_ORDER = ["architect", "grunt", "pedant", "scribe"]
    VALID_ROLE_KEYS = tuple(DEFAULT_ROLE_ORDER)


def _normalize_text(task: dict[str, Any]) -> str:
    title = str(task.get("title", "") or "")
    description = str(task.get("description", "") or "")
    return f"{title}\n{description}".lower()


def _dedupe_and_validate(role_keys: list[str]) -> list[str]:
    seen = set()
    ordered: list[str] = []
    for key in role_keys:
        if key in VALID_ROLE_KEYS and key not in seen:
            ordered.append(key)
            seen.add(key)
    return ordered


def orchestrate_task(task: dict[str, Any]) -> list[str]:
    """
    Return an ordered role plan for cascade execution.

    This keeps the existing role keys used by bridge scripts:
    - architect, grunt, pedant, scribe
    """
    text = _normalize_text(task)

    # Fast-path small changes that usually do not need full design pass.
    lightweight_markers = (
        "typo",
        "readme",
        "docs",
        "documentation",
        "comment-only",
        "formatting",
    )
    if any(marker in text for marker in lightweight_markers):
        return ["pedant", "scribe"]

    # Feature and implementation work generally benefits from full chain.
    feature_markers = (
        "frontend",
        "backend",
        "api",
        "endpoint",
        "database",
        "migration",
        "auth",
        "integration",
        "feature",
    )
    if any(marker in text for marker in feature_markers):
        return list(DEFAULT_ROLE_ORDER)

    # If we cannot confidently classify, use the conservative default.
    return list(DEFAULT_ROLE_ORDER)


def sanitize_plan(plan: list[str] | None) -> list[str]:
    """
    Normalize any custom plan into supported role keys.
    Falls back to full default if empty/invalid.
    """
    normalized = _dedupe_and_validate(plan or [])
    return normalized or list(DEFAULT_ROLE_ORDER)
