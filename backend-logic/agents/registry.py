#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


AGENTS: dict[str, dict[str, Any]] = {
    "architect": {
        "display_name": "The Architect",
        "env_key": "ARCHITECT",
        "description": "Plans implementation strategy and architecture.",
    },
    "grunt": {
        "display_name": "The Grunt",
        "env_key": "GRUNT",
        "description": "Implements features and integration changes.",
    },
    "pedant": {
        "display_name": "The Pedant",
        "env_key": "PEDANT",
        "description": "Performs quality checks and correctness fixes.",
    },
    "scribe": {
        "display_name": "The Scribe",
        "env_key": "SCRIBE",
        "description": "Finalizes delivery and owns PR creation.",
    },
}


DEFAULT_ROLE_ORDER: list[str] = ["architect", "grunt", "pedant", "scribe"]
VALID_ROLE_KEYS: tuple[str, ...] = tuple(DEFAULT_ROLE_ORDER)


def get_role_specs(ordered_role_keys: list[str] | None = None) -> list[dict[str, str]]:
    """
    Return role metadata in execution order.

    Each item contains:
    - key: canonical role key
    - display_name: user-facing role label
    - env_key: suffix used by environment overrides
    """
    keys = ordered_role_keys or list(DEFAULT_ROLE_ORDER)
    specs: list[dict[str, str]] = []
    for key in keys:
        role = AGENTS.get(key)
        if not role:
            continue
        specs.append(
            {
                "key": key,
                "display_name": str(role["display_name"]),
                "env_key": str(role["env_key"]),
            }
        )
    return specs
