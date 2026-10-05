import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import deepseek_client as client
from update_storage import write_json


class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"LOCALAPPDATA": folder.name,
            "DEEPSEEK_API_KEY": "synthetic-test-key-not-real", "POLICY_AMADEUS_AI_AUDIT_URL": "",
            "POLICY_AMADEUS_AI_AUDIT_KEY": "", "POLICY_AMADEUS_AI_AUDIT_MODEL": ""})
        env.start()
        self.addCleanup(env.stop)
        client.save_settings(None, enabled=True, model="deepseek-flash", budget_cny="10")
        self.response = Mock(status_code=200)
        self.response.json.return_value = {"usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}

    def invoke(self, **kwargs):
        return client.complete_json("Review public evidence", "Public text", purpose="test", **kwargs)

    def test_defaults_do_not_send_policy_or_enable_api(self):
        (client.data_dir() / "deepseek_settings.json").unlink()
        self.assertFalse(client.settings()["enabled"])
        self.assertFalse(client.settings()["policy_audit_enabled"])

    def test_no_key_no_network(self):
        with patch.dict(os.environ, DEEPSEEK_API_KEY=""), patch("requests.post") as post:
            with self.assertRaises(client.DeepSeekError):
                self.invoke()
            post.assert_not_called()

    def test_disabled_no_network(self):
        client.save_settings(None, enabled=False, model="deepseek-flash", budget_cny="10")
        with patch("requests.post") as post:
            with self.assertRaises(client.DeepSeekError):
                self.invoke()
            post.assert_not_called()

    def test_success_deduplicates_and_counts_usage(self):
        with patch("requests.post", return_value=self.response) as post:
            self.assertEqual(self.invoke(), {"ok": True})
            self.assertEqual(self.invoke(), {"ok": True})
            self.assertEqual(post.call_count, 1)
            args, kwargs = post.call_args
            self.assertEqual(args[0], "https://api.deepseek.com/chat/completions")
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(kwargs["json"]["response_format"], {"type": "json_object"})
            self.assertEqual(kwargs["json"]["thinking"], {"type": "enabled"})
        self.assertEqual(client.usage_status()["estimated_cny"], "0.0006")

    def test_budget_blocks_before_call(self):
        client.save_settings(None, enabled=True, model="deepseek-flash", budget_cny="0.001")
        with patch("requests.post") as post:
            with self.assertRaises(client.DeepSeekError):
                self.invoke()
            post.assert_not_called()

    def test_save_does_not_reset_used_budget(self):
        with patch("requests.post", return_value=self.response):
            self.invoke()
        before = client.usage_status()
        client.save_settings(None, enabled=True, model="deepseek-v4-pro", budget_cny="5")
        self.assertEqual(client.usage_status(), before)

    def test_bad_configuration_and_nan_budget_refused(self):
        for budget in ("NaN", "Infinity", "-1", "0", "invalid"):
            with self.subTest(budget=budget), self.assertRaises(client.DeepSeekError):
                client.save_settings(None, enabled=True, model="deepseek-flash", budget_cny=budget)
        with self.assertRaises(client.DeepSeekError):
            client.save_settings(None, enabled=True, model="unknown", budget_cny="10")

    def test_corrupt_ledger_does_not_reset(self):
        write_json(client.data_dir() / "deepseek_usage.json", {"requests": {"x": {"cost_cny": "NaN"}}})
        with patch("requests.post") as post:
            with self.assertRaises(client.DeepSeekError):
                self.invoke()
            post.assert_not_called()

    def test_timeout_keeps_reserve_and_cooldown(self):
        with patch("requests.post", side_effect=requests.Timeout("synthetic-test-key-not-real")) as post:
            with self.assertRaises(client.DeepSeekError) as error:
                self.invoke()
            self.assertNotIn("synthetic-test-key", str(error.exception))
            first = client.usage_status()
            self.assertGreater(float(first["estimated_cny"]), 0)
            with self.assertRaises(client.DeepSeekError):
                self.invoke()
            self.assertEqual(post.call_count, 1)
        self.assertEqual(first["unknown_charge_count"], 1)

    def test_retry_does_not_erase_old_unknown_charge(self):
        with patch("time.time", return_value=1000), patch("requests.post", side_effect=requests.Timeout()):
            with self.assertRaises(client.DeepSeekError):
                self.invoke()
        before = float(client.usage_status()["estimated_cny"])
        with patch("time.time", return_value=5000), patch("requests.post", return_value=self.response):
            self.invoke()
        self.assertGreater(float(client.usage_status()["estimated_cny"]), before)
        self.assertEqual(client.usage_status()["request_count"], 2)

    def test_http_failure_never_exposes_body_key_or_redirects(self):
        for code in (301, 401, 402, 429, 500):
            response = Mock(status_code=code, text="synthetic-test-key-not-real")
            with self.subTest(code=code), patch("requests.post", return_value=response), patch("time.time", return_value=code * 10000):
                with self.assertRaises(client.DeepSeekError) as error:
                    self.invoke()
                self.assertNotIn("synthetic-test-key", str(error.exception))
                response.json.assert_not_called()

    def test_invalid_or_truncated_output_not_accepted(self):
        for index, (content, finish) in enumerate((("[]", "stop"), ("invalid", "stop"), ('{"ok":true}', "length"), ("", "stop"))):
            response = copy.deepcopy(self.response)
            response.json.return_value["choices"][0].update(finish_reason=finish, message={"content": content})
            with self.subTest(content=content), patch("requests.post", return_value=response), patch("time.time", return_value=10000 + index * 5000):
                with self.assertRaises(client.DeepSeekError):
                    self.invoke()

    def test_missing_usage_retains_conservative_reservation(self):
        self.response.json.return_value.pop("usage")
        with patch("requests.post", return_value=self.response), self.assertRaises(client.DeepSeekError):
            self.invoke()
        self.assertEqual(client.usage_status()["unknown_charge_count"], 1)

    def test_oversized_input_and_unbounded_output_rejected(self):
        with patch("requests.post") as post:
            with self.assertRaises(client.DeepSeekError):
                client.complete_json("review", "x" * 513000, purpose="test")
            for limit in (0, 999999, True):
                with self.subTest(limit=limit), self.assertRaises(client.DeepSeekError):
                    self.invoke(max_tokens=limit)
            post.assert_not_called()

    def test_balance_does_not_run_model_or_log_key(self):
        response = Mock(status_code=200)
        response.json.return_value = {"is_available": True, "balance_infos": [
            {"currency": "CNY", "total_balance": "10.00", "granted_balance": "10.00"}]}
        with patch("requests.get", return_value=response) as get, patch("requests.post") as post:
            self.assertEqual(client.balance()["balances"], [{"currency": "CNY", "total_balance": "10.00"}])
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
            post.assert_not_called()

    def test_policy_audit_remains_opt_in(self):
        from policy_ai_assist import audit_policies
        with patch("deepseek_client.complete_json") as complete:
            result = audit_policies([("policy", "PRIVATE MERCHANT INFORMATION")], {})
            complete.assert_not_called()
            self.assertEqual(result["ai_audit_findings"], [])

    def test_policy_audit_explicit_opt_in(self):
        from policy_ai_assist import audit_policies
        client.save_settings(None, enabled=True, model="deepseek-flash", budget_cny="10", policy_audit_enabled=True)
        with patch("deepseek_client.complete_json", return_value={"findings": [{"message": "Ambiguous charge"}]}):
            result = audit_policies([("policy", "Synthetic policy")], {})
            self.assertEqual(result["ai_audit_findings"], ["warning: Ambiguous charge"])

    def test_official_review_requires_allowlisted_url(self):
        with patch("deepseek_client.complete_json") as complete:
            with self.assertRaises(client.DeepSeekError):
                client.review_official_change("Country — Malta", "https://attacker.example", "old", "new", {})
            complete.assert_not_called()

    def test_official_review_validates_verbatim_evidence(self):
        from knowledge_update import SOURCES
        result = {"classification": "metadata_only", "reason": "UI counter", "evidence_quotes": ["Missing"]}
        with patch("deepseek_client.complete_json", return_value=result), self.assertRaises(client.DeepSeekError):
            client.review_official_change("Country — Malta", SOURCES["Country — Malta"][0], "old", "new", {})

    def test_official_review_does_not_install_or_modify_rules(self):
        from knowledge_update import SOURCES
        rules = {"withdrawal_days": 14}
        original = copy.deepcopy(rules)
        result = {"classification": "effective_change", "reason": "New law", "effective_on": "2026-10-01",
                  "evidence_quotes": ["new law"], "proposed_rule_changes": []}
        with patch("deepseek_client.complete_json", return_value=result):
            self.assertEqual(client.review_official_change("Country — Malta", SOURCES["Country — Malta"][0], "old", "new law", rules), result)
        self.assertEqual(rules, original)

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI")
    def test_dpapi_round_trip_without_plaintext_storage(self):
        key = "synthetic-encryption-test-key"
        with patch.dict(os.environ, DEEPSEEK_API_KEY=""):
            client.save_settings(key, enabled=True, model="deepseek-flash", budget_cny="10")
            self.assertEqual(client.api_key(), key)
            for path in client.data_dir().glob("*.json"):
                self.assertNotIn(key, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
