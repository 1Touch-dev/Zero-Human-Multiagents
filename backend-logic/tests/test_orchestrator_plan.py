"""Regression tests for cascade role planning (PAP-203-style early closes)."""

import importlib.util
import pathlib
import unittest

ORCH_PATH = pathlib.Path(__file__).resolve().parents[1] / "orchestrator" / "orchestrator.py"
SPEC = importlib.util.spec_from_file_location("orchestrator_plan_tests_target", ORCH_PATH)
assert SPEC and SPEC.loader
orch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(orch)


class TestOrchestratorPlanExtension(unittest.TestCase):
    def test_truncated_default_prefix_extends(self) -> None:
        self.assertEqual(
            orch.sanitize_plan(["architect", "grunt"]),
            ["architect", "grunt", "pedant", "scribe"],
        )
        self.assertEqual(
            orch.sanitize_plan(["architect", "grunt", "pedant"]),
            ["architect", "grunt", "pedant", "scribe"],
        )

    def test_lightweight_plan_unchanged(self) -> None:
        self.assertEqual(
            orch.sanitize_plan(["pedant", "scribe"]),
            ["pedant", "scribe"],
        )

    def test_non_prefix_custom_order_unchanged(self) -> None:
        self.assertEqual(
            orch.sanitize_plan(["grunt", "pedant", "scribe"]),
            ["grunt", "pedant", "scribe"],
        )


if __name__ == "__main__":
    unittest.main()
