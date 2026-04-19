import importlib.util
import pathlib
import unittest
from unittest.mock import patch


BRIDGE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "Python_Bridges" / "openclaw_bridge_cascade.py"
SPEC = importlib.util.spec_from_file_location("openclaw_bridge_cascade", BRIDGE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load bridge module from {BRIDGE_PATH}")
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class ResolveLlmConfigTests(unittest.TestCase):
    def test_dynamic_llm_disabled_uses_env_and_skips_db(self):
        env = {
            "ZERO_HUMAN_DYNAMIC_LLM_ENABLED": "false",
            "OPENCLAW_MODEL": "legacy-openclaw-model",
        }
        with patch.object(bridge, "fetch_company_llm_settings") as fetch_mock:
            resolved = bridge.resolve_llm_config(
                "architect",
                api_base="http://x/api",
                api_key="tok",
                run_id="run1",
                company_id="c1",
                env=env,
            )
        fetch_mock.assert_not_called()
        self.assertEqual(resolved["model"], "legacy-openclaw-model")
        self.assertEqual(resolved["source"], "dynamic_llm_disabled")

    def test_heartbeat_payload_takes_highest_precedence(self):
        env = {
            "ZERO_HUMAN_DYNAMIC_LLM_ENABLED": "true",
            "COMPANY_LLM_CONFIG_JSON": (
                '{"llm":{"default_provider":"openai","default_model":"db-default",'
                '"providers":{"openai":{"api_key":"k1"}},'
                '"role_models":{"architect":{"provider":"openai","model":"heartbeat-model"}}}}'
            ),
            "OPENCLAW_MODEL": "legacy-model",
        }
        with patch.object(bridge, "fetch_company_llm_settings", return_value=None):
            resolved = bridge.resolve_llm_config(
                "architect",
                api_base="http://x/api",
                api_key="tok",
                run_id="run1",
                company_id="c1",
                env=env,
            )
        self.assertEqual(resolved["model"], "heartbeat-model")
        self.assertEqual(resolved["source"], "heartbeat_payload")

    def test_db_settings_beat_user_override_and_env(self):
        env = {
            "ZERO_HUMAN_DYNAMIC_LLM_ENABLED": "true",
            "ZERO_HUMAN_LLM_USER_OVERRIDE_ENABLED": "true",
            "ZERO_HUMAN_USER_LLM_CONFIG_JSON": (
                '{"llm":{"default_provider":"openai","default_model":"user-model",'
                '"providers":{"openai":{"api_key":"uk"}},"role_models":{}}}'
            ),
            "OPENCLAW_MODEL": "legacy-model",
        }
        db_payload = {
            "llm": {
                "default_provider": "vllm_openai_compatible",
                "default_model": "db-default",
                "providers": {"vllm_openai_compatible": {"base_url": "http://vllm:8000/v1"}},
                "role_models": {"grunt": {"provider": "vllm_openai_compatible", "model": "db-grunt-model"}},
            }
        }
        with patch.object(bridge, "fetch_company_llm_settings", return_value=db_payload):
            resolved = bridge.resolve_llm_config(
                "grunt",
                api_base="http://x/api",
                api_key="tok",
                run_id="run1",
                company_id="c1",
                env=env,
            )
        self.assertEqual(resolved["model"], "db-grunt-model")
        self.assertEqual(resolved["source"], "db_company_settings")

    def test_user_override_beats_env_when_enabled(self):
        env = {
            "ZERO_HUMAN_DYNAMIC_LLM_ENABLED": "true",
            "ZERO_HUMAN_LLM_USER_OVERRIDE_ENABLED": "1",
            "USER_LLM_CONFIG_JSON": (
                '{"llm":{"default_provider":"openai","default_model":"user-default",'
                '"providers":{"openai":{"api_key":"ukey"}},"role_models":{'
                '"pedant":{"provider":"openai","model":"user-pedant-model"}}}}'
            ),
            "OPENCLAW_MODEL": "legacy-model",
        }
        with patch.object(bridge, "fetch_company_llm_settings", return_value=None):
            resolved = bridge.resolve_llm_config("pedant", env=env)
        self.assertEqual(resolved["model"], "user-pedant-model")
        self.assertEqual(resolved["source"], "user_override")

    def test_env_fallback_preserves_legacy_openclaw_model(self):
        env = {"OPENCLAW_MODEL": "legacy-openclaw-model"}
        with patch.object(bridge, "fetch_company_llm_settings", return_value=None):
            resolved = bridge.resolve_llm_config("architect", env=env)
        self.assertEqual(resolved["model"], "legacy-openclaw-model")
        self.assertEqual(resolved["source"], "dynamic_llm_disabled")

    def test_default_when_no_configuration_present(self):
        with patch.object(bridge, "fetch_company_llm_settings", return_value=None):
            resolved = bridge.resolve_llm_config("scribe", env={})
        self.assertEqual(resolved["model"], "openai/gpt-4o")
        self.assertEqual(resolved["source"], "dynamic_llm_disabled")

    def test_apply_guardrails_enforces_allowlist_and_timeout(self):
        guarded = bridge.apply_llm_guardrails(
            {
                "provider": "vllm_openai_compatible",
                "model": "non-allowed-model",
                "timeout_seconds": 300,
                "allowed_models": ["allowed-model-a", "allowed-model-b"],
                "max_timeout_seconds": 45,
                "role_retries": {"architect": 2},
            },
            "architect",
        )
        self.assertEqual(guarded["model"], "allowed-model-a")
        self.assertEqual(guarded["timeout_seconds"], 45)
        self.assertEqual(guarded["resolved_role_retries"], 2)
        self.assertTrue(guarded["fallback_activated"])

    def test_db_settings_can_route_different_models_by_role(self):
        env = {"ZERO_HUMAN_DYNAMIC_LLM_ENABLED": "true"}
        db_payload = {
            "llm": {
                "default_provider": "vllm_openai_compatible",
                "default_model": "default-model",
                "providers": {"vllm_openai_compatible": {"base_url": "http://vllm:8000/v1"}},
                "role_models": {
                    "architect": {"provider": "vllm_openai_compatible", "model": "architect-model"},
                    "grunt": {"provider": "vllm_openai_compatible", "model": "grunt-model"},
                },
            }
        }
        with patch.object(bridge, "fetch_company_llm_settings", return_value=db_payload):
            architect = bridge.resolve_llm_config(
                "architect",
                api_base="http://x/api",
                api_key="tok",
                run_id="run1",
                company_id="c1",
                env=env,
            )
            grunt = bridge.resolve_llm_config(
                "grunt",
                api_base="http://x/api",
                api_key="tok",
                run_id="run1",
                company_id="c1",
                env=env,
            )
        self.assertEqual(architect["model"], "architect-model")
        self.assertEqual(grunt["model"], "grunt-model")
        self.assertNotEqual(architect["model"], grunt["model"])

    def test_api_save_then_resolve_runtime_uses_effective_model_provider_without_leaking_key(self):
        saved = {
            "llm": {
                "default_provider": "openai",
                "default_model": "gpt-4o-mini",
                "providers": {
                    "openai": {
                        "enabled": True,
                        "api_key": "***REDACTED***",
                    }
                },
                "role_models": {
                    "scribe": {
                        "provider": "openai",
                        "model": "gpt-4.1-mini",
                    }
                },
            }
        }

        def fake_api_request(method, url, api_key, run_id, payload=None):
            _ = api_key
            _ = run_id
            if method == "PUT" and url.endswith("/companies/c1/llm-settings"):
                return 200, {"companyId": "c1", "settings": payload, "updatedAt": "2026-01-01T00:00:00Z"}
            if method == "GET" and url.endswith("/companies/c1/llm-settings"):
                return 200, {"companyId": "c1", "settings": saved, "updatedAt": "2026-01-01T00:00:00Z"}
            raise AssertionError(f"Unexpected call: {method} {url}")

        with patch.object(bridge, "api_request", side_effect=fake_api_request):
            status, _ = bridge.api_request(
                "PUT",
                "http://x/api/companies/c1/llm-settings",
                "token",
                "run1",
                saved,
            )
            self.assertEqual(status, 200)
            resolved = bridge.resolve_llm_config(
                "scribe",
                api_base="http://x/api",
                api_key="token",
                run_id="run1",
                company_id="c1",
                env={"ZERO_HUMAN_DYNAMIC_LLM_ENABLED": "true"},
            )
        self.assertEqual(resolved["provider"], "openai")
        self.assertEqual(resolved["model"], "gpt-4.1-mini")
        self.assertIsNone(resolved["api_key"])


class MajorDecisionGuardrailsTests(unittest.TestCase):
    def test_policy_flags_required_major_categories(self):
        issue = {
            "title": "Deploy production policy and remove old records",
            "description": "Update RBAC permission policy and truncate staging mirror table",
        }
        policy = bridge.evaluate_major_decision_policy(
            issue,
            role_key="architect",
            llm_provider="vllm_openai_compatible",
            llm_model="meta-llama/Llama-3.1-8B-Instruct",
        )
        self.assertTrue(policy["requires_approval"])
        self.assertIn("deploy_prod_config_change", policy["categories"])
        self.assertIn("destructive_data_action", policy["categories"])
        self.assertIn("security_sensitive_policy_change", policy["categories"])

    def test_enforcement_pauses_and_creates_approval_when_missing(self):
        issue = {
            "id": "issue-1",
            "identifier": "ISSUE-1",
            "title": "Prepare protected push and prod rollout",
            "description": "Deploy to prod and push to protected branch",
        }
        with (
            patch.object(bridge, "list_issue_approvals", return_value=[]),
            patch.object(bridge, "create_company_approval", return_value=(201, {"id": "approval-1"})),
            patch.object(bridge, "patch_issue") as patch_issue_mock,
        ):
            result = bridge.enforce_major_decision_guardrails(
                api_base="http://localhost/api",
                api_key="key",
                run_id="run-1",
                company_id="company-1",
                agent_id="agent-1",
                role_key="scribe",
                issue=issue,
                llm_provider="openai",
                llm_model="gpt-4o",
            )
        self.assertTrue(result["paused"])
        self.assertEqual(result["approval_id"], "approval-1")
        self.assertIn("pr_merge_protected_push", result["categories"])
        patch_issue_mock.assert_called_once()

    def test_enforcement_allows_execution_when_approval_exists(self):
        issue = {
            "id": "issue-1",
            "identifier": "ISSUE-1",
            "title": "Push release branch",
            "description": "Need protected push for release",
        }
        with (
            patch.object(
                bridge,
                "list_issue_approvals",
                return_value=[{"id": "approval-2", "type": "major_decision_guardrail", "status": "approved"}],
            ),
            patch.object(bridge, "patch_issue") as patch_issue_mock,
        ):
            result = bridge.enforce_major_decision_guardrails(
                api_base="http://localhost/api",
                api_key="key",
                run_id="run-1",
                company_id="company-1",
                agent_id="agent-1",
                role_key="scribe",
                issue=issue,
                llm_provider="openai",
                llm_model="gpt-4o",
            )
        self.assertFalse(result["paused"])
        self.assertEqual(result["reason"], "already_approved")
        patch_issue_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

