#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Skill:
    name: str
    prompt: str


SKILLS: dict[str, Skill] = {
    "plan_design": Skill(
        name="plan_design",
        prompt=(
            "SKILL (PLAN_DESIGN): analyze scope and produce a concrete implementation plan only. "
            "Do not implement code changes in this phase."
        ),
    ),
    "write_code": Skill(
        name="write_code",
        prompt=(
            "SKILL (WRITE_CODE): implement the requested behavior with minimal, production-safe changes. "
            "Prefer correctness first, then clarity."
        ),
    ),
    "review_code": Skill(
        name="review_code",
        prompt=(
            "SKILL (REVIEW_CODE): inspect code paths, edge cases, and regressions. "
            "Fix correctness issues and improve reliability where needed."
        ),
    ),
    "deploy": Skill(
        name="deploy",
        prompt=(
            "SKILL (DEPLOY): finalize deliverables, confirm release readiness, "
            "and ensure handoff/output is actionable for deployment or PR completion."
        ),
    ),
}


ROLE_DEFAULT_SKILL: dict[str, str] = {
    "architect": "plan_design",
    "grunt": "write_code",
    "pedant": "review_code",
    "scribe": "deploy",
}


def get_skill(role_key: str, task: dict[str, Any] | None = None, model: str | None = None) -> Skill:
    """
    Resolve a skill for a role and task context.
    Currently role-first with a conservative fallback.
    """
    skill_name = ROLE_DEFAULT_SKILL.get(role_key, "write_code")
    # Keep model available for future model-specific skill variants.
    _ = model
    _ = task
    return SKILLS.get(skill_name, SKILLS["write_code"])
