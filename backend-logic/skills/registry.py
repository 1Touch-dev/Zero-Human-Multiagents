#!/usr/bin/env python3
"""
Skills registry with structured input/output schemas and execute() method.

Each skill:
- Has a name, prompt, input_schema, output_schema.
- Implements execute() which calls tools internally and returns structured JSON.
- Is reusable across agents without code duplication.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

try:
    from tools.executor import read_file, run_bash, write_file
    from tools.runtime_logging import write_event
    _TOOLS_AVAILABLE = True
except Exception:  # noqa: BLE001
    _TOOLS_AVAILABLE = False
    run_bash = None
    read_file = None
    write_file = None
    write_event = None


# ---------------------------------------------------------------------------
# Base Skill class
# ---------------------------------------------------------------------------

@dataclass
class Skill:
    name: str
    prompt: str
    input_schema: dict[str, str] = field(default_factory=dict)
    output_schema: dict[str, str] = field(default_factory=dict)

    def execute(
        self,
        *,
        role_key: str,
        task: dict[str, Any] | None = None,
        identifier: str = "unknown",
        sandbox_dir: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute this skill and return structured output JSON.
        Subclasses override this. Base returns a safe no-op result.
        """
        _log(
            event_type=f"skill_execute_{self.name}",
            identifier=identifier,
            role_key=role_key,
            skill_name=self.name,
            run_id=run_id,
            payload={"sandbox_dir": sandbox_dir, "task_title": (task or {}).get("title", "")},
        )
        return {
            "skill": self.name,
            "role": role_key,
            "identifier": identifier,
            "status": "noop",
            "output": None,
        }

    def to_prompt_block(self) -> str:
        return self.prompt


# ---------------------------------------------------------------------------
# Logging helper (safe even if runtime_logging unavailable)
# ---------------------------------------------------------------------------

def _log(*, event_type: str, identifier: str, role_key: str | None,
         skill_name: str | None, run_id: str | None, payload: dict[str, Any]) -> None:
    if write_event:
        try:
            write_event(
                event_type=event_type,
                identifier=identifier,
                role_key=role_key,
                skill_name=skill_name,
                run_id=run_id,
                payload=payload,
            )
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Concrete Skill implementations
# ---------------------------------------------------------------------------

class PlanDesignSkill(Skill):
    """
    Architect skill: analyze scope and produce implementation plan.
    Reads repo structure, returns plan as structured JSON.
    """

    def execute(self, *, role_key: str, task: dict[str, Any] | None = None,
                identifier: str = "unknown", sandbox_dir: str | None = None,
                run_id: str | None = None) -> dict[str, Any]:
        _log(
            event_type="skill_execute_plan_design",
            identifier=identifier,
            role_key=role_key,
            skill_name=self.name,
            run_id=run_id,
            payload={"sandbox_dir": sandbox_dir},
        )

        repo_summary: list[str] = []
        if sandbox_dir and run_bash and _TOOLS_AVAILABLE:
            try:
                result = run_bash(
                    ["find", sandbox_dir, "-type", "f", "-name", "*.py", "-not", "-path", "*/.*"],
                    timeout_seconds=10,
                    capture_output=True,
                )
                files = [l.strip() for l in (result.stdout or "").splitlines() if l.strip()]
                repo_summary = files[:30]
            except Exception:  # noqa: BLE001
                pass

        return {
            "skill": self.name,
            "role": role_key,
            "identifier": identifier,
            "status": "ready",
            "output": {
                "phase": "plan_design",
                "repo_files_sampled": repo_summary,
                "task_title": (task or {}).get("title", ""),
                "task_description": (task or {}).get("description", ""),
                "instruction": self.prompt,
            },
        }


class WriteCodeSkill(Skill):
    """
    Grunt skill: implement the requested behavior.
    Validates sandbox, returns structured implementation context.
    """

    def execute(self, *, role_key: str, task: dict[str, Any] | None = None,
                identifier: str = "unknown", sandbox_dir: str | None = None,
                run_id: str | None = None) -> dict[str, Any]:
        _log(
            event_type="skill_execute_write_code",
            identifier=identifier,
            role_key=role_key,
            skill_name=self.name,
            run_id=run_id,
            payload={"sandbox_dir": sandbox_dir},
        )

        sandbox_exists = False
        if sandbox_dir and run_bash and _TOOLS_AVAILABLE:
            try:
                result = run_bash(["test", "-d", sandbox_dir], check=False, capture_output=True)
                sandbox_exists = result.returncode == 0
            except Exception:  # noqa: BLE001
                pass

        return {
            "skill": self.name,
            "role": role_key,
            "identifier": identifier,
            "status": "ready",
            "output": {
                "phase": "write_code",
                "sandbox_dir": sandbox_dir,
                "sandbox_exists": sandbox_exists,
                "task_title": (task or {}).get("title", ""),
                "task_description": (task or {}).get("description", ""),
                "instruction": self.prompt,
            },
        }


class ReviewCodeSkill(Skill):
    """
    Pedant skill: inspect code and report quality issues.
    Runs basic linting check if tools available.
    """

    def execute(self, *, role_key: str, task: dict[str, Any] | None = None,
                identifier: str = "unknown", sandbox_dir: str | None = None,
                run_id: str | None = None) -> dict[str, Any]:
        _log(
            event_type="skill_execute_review_code",
            identifier=identifier,
            role_key=role_key,
            skill_name=self.name,
            run_id=run_id,
            payload={"sandbox_dir": sandbox_dir},
        )

        lint_output: str | None = None
        if sandbox_dir and run_bash and _TOOLS_AVAILABLE:
            try:
                result = run_bash(
                    f"cd {sandbox_dir} && python3 -m py_compile $(find . -name '*.py' -not -path '*/.*') 2>&1 | head -40",
                    timeout_seconds=20,
                    capture_output=True,
                )
                lint_output = (result.stdout or "").strip() or "No syntax errors found."
            except Exception:  # noqa: BLE001
                lint_output = "Lint check skipped."

        return {
            "skill": self.name,
            "role": role_key,
            "identifier": identifier,
            "status": "ready",
            "output": {
                "phase": "review_code",
                "sandbox_dir": sandbox_dir,
                "lint_result": lint_output,
                "task_title": (task or {}).get("title", ""),
                "instruction": self.prompt,
            },
        }


class DeploySkill(Skill):
    """
    Scribe skill: finalize docs, confirm release readiness, create PR.
    Returns delivery context for downstream automation.
    """

    def execute(self, *, role_key: str, task: dict[str, Any] | None = None,
                identifier: str = "unknown", sandbox_dir: str | None = None,
                run_id: str | None = None) -> dict[str, Any]:
        _log(
            event_type="skill_execute_deploy",
            identifier=identifier,
            role_key=role_key,
            skill_name=self.name,
            run_id=run_id,
            payload={"sandbox_dir": sandbox_dir},
        )

        git_log: str | None = None
        if sandbox_dir and run_bash and _TOOLS_AVAILABLE:
            try:
                result = run_bash(
                    ["git", "log", "--oneline", "-5"],
                    cwd=sandbox_dir,
                    timeout_seconds=10,
                    capture_output=True,
                )
                git_log = (result.stdout or "").strip()
            except Exception:  # noqa: BLE001
                git_log = "Git log unavailable."

        return {
            "skill": self.name,
            "role": role_key,
            "identifier": identifier,
            "status": "ready",
            "output": {
                "phase": "deploy",
                "sandbox_dir": sandbox_dir,
                "recent_commits": git_log,
                "task_title": (task or {}).get("title", ""),
                "instruction": self.prompt,
                "pr_expected": True,
            },
        }


# ---------------------------------------------------------------------------
# Skills registry
# ---------------------------------------------------------------------------

SKILLS: dict[str, Skill] = {
    "plan_design": PlanDesignSkill(
        name="plan_design",
        prompt=(
            "SKILL (PLAN_DESIGN): analyze scope and produce a concrete implementation plan only. "
            "Do not implement code changes in this phase."
        ),
        input_schema={"task_title": "str", "task_description": "str", "repo_files": "list[str]"},
        output_schema={"phase": "str", "plan_steps": "list[str]", "dependencies": "list[str]"},
    ),
    "write_code": WriteCodeSkill(
        name="write_code",
        prompt=(
            "SKILL (WRITE_CODE): implement the requested behavior with minimal, production-safe changes. "
            "Prefer correctness first, then clarity. Use tools for all file/bash/git operations."
        ),
        input_schema={"task_description": "str", "repo_context": "str", "sandbox_dir": "str"},
        output_schema={"files_changed": "list[str]", "summary": "str"},
    ),
    "review_code": ReviewCodeSkill(
        name="review_code",
        prompt=(
            "SKILL (REVIEW_CODE): inspect code paths, edge cases, and regressions. "
            "Fix correctness issues and improve reliability where needed."
        ),
        input_schema={"sandbox_dir": "str", "changed_files": "list[str]"},
        output_schema={"issues_found": "list[str]", "fixes_applied": "list[str]", "lint_result": "str"},
    ),
    "deploy": DeploySkill(
        name="deploy",
        prompt=(
            "SKILL (DEPLOY): finalize deliverables, confirm release readiness, "
            "and ensure handoff/output is actionable for deployment or PR completion."
        ),
        input_schema={"sandbox_dir": "str", "identifier": "str", "title": "str"},
        output_schema={"pr_url": "str", "release_notes": "str", "pr_expected": "bool"},
    ),
}


ROLE_DEFAULT_SKILL: dict[str, str] = {
    "architect": "plan_design",
    "grunt": "write_code",
    "pedant": "review_code",
    "scribe": "deploy",
}


def get_skill(role_key: str, task: dict[str, Any] | None = None, model: str | None = None) -> Skill:
    """Resolve the correct skill for a role. Always returns a valid Skill."""
    _ = model
    skill_name = ROLE_DEFAULT_SKILL.get(role_key, "write_code")
    return SKILLS.get(skill_name, SKILLS["write_code"])
