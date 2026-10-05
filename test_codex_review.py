import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import codex_review_worker as worker
from update_storage import write_json


class CodexReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.pack = json.loads(Path("legal_rulepack.json").read_text(encoding="utf-8"))
        self.pack["country_overlays"].setdefault("Malta", {"legal_guarantee": "a minimum 2-year legal guarantee"})
        from knowledge_update import SOURCES
        self.source = "Country — Malta"
        self.url = SOURCES[self.source][0]
        before = "The law provides mandatory consumer rights. " * 40
        after = "The law provides mandatory consumer rights. Navigation count: 2. " * 40
        self.evidence = {"source": self.source, "url": self.url, "before": before, "after": after,
                         "old_sha256": hashlib.sha256(before.encode()).hexdigest(),
                         "new_sha256": hashlib.sha256(after.encode()).hexdigest()}
        self.decision = {"classification": "metadata_only", "reason": "Navigation count changes only",
                         "effective_on": "", "effective_timezone": "", "quotes": ["The law provides mandatory consumer rights."], "patches": []}
        self.verifier = {"approved": True, "reason": "Consumer rights unchanged", "quotes": self.decision["quotes"]}
        self.proposal_id = worker.digest({"source": self.source, "url": self.url,
                "new": self.evidence["new_sha256"], "base": worker.digest(self.pack)})
        self.proposal = {"id": self.proposal_id, "base_rulepack_sha256": worker.digest(self.pack),
                         "evidence": self.evidence, "decision": self.decision, "verification": self.verifier}

    def enable(self):
        write_json(worker.folder()/"codex_review_settings.json", {"enabled": True, "repository": worker.REPO})

    def law_patch(self):
        self.decision.update(classification="effective_change", effective_on="2026-10-01", effective_timezone="Europe/Malta",
            patches=[{"path": "/country_overlays/Malta/legal_guarantee", "value_json": json.dumps("a revised statutory guarantee, based on supplied official law")}])

    def test_opt_in_disabled_by_default(self):
        self.assertFalse(worker.enabled())
        self.assertEqual(worker.run(), {"state": "disabled"})

    def test_wrong_repository_not_enabled(self):
        write_json(worker.folder()/"codex_review_settings.json", {"enabled": True, "repository": "other/repo"})
        self.assertFalse(worker.enabled())

    def test_metadata_only_approves_exact_body_without_changing_law(self):
        result = worker.merge_proposal(self.pack, self.proposal)
        self.assertEqual(result["coverage_groups"], self.pack["coverage_groups"])
        self.assertEqual(result["country_overlays"], self.pack["country_overlays"])
        self.assertEqual(result["reviewed_source_fingerprints"][self.source][self.url], self.evidence["new_sha256"])
        self.assertNotIn("codex_review_history", self.pack)

    def test_law_change_updates_rules_only_after_effective_date(self):
        self.law_patch()
        result = worker.merge_proposal(self.pack, self.proposal, datetime(2026, 10, 5, tzinfo=timezone.utc))
        self.assertIn("revised statutory", result["country_overlays"]["Malta"]["legal_guarantee"])

    def test_future_law_is_recorded_without_early_activation(self):
        self.law_patch()
        self.decision.update(classification="future_change", effective_on="2099-01-01")
        result = worker.merge_proposal(self.pack, self.proposal)
        self.assertEqual(result["country_overlays"], self.pack["country_overlays"])
        self.assertEqual(len(result["codex_scheduled_patches"]), 1)

    def test_positive_timezone_does_not_activate_before_national_date(self):
        self.law_patch()
        self.decision.update(effective_on="2026-10-06", effective_timezone="America/New_York")
        result = worker.merge_proposal(self.pack, self.proposal, datetime(2026, 10, 6, 1, tzinfo=timezone.utc))
        self.assertEqual(result["country_overlays"], self.pack["country_overlays"])

    def test_base_conflict_refuses_to_overwrite_new_rules(self):
        self.proposal["base_rulepack_sha256"] = "b"*64
        with self.assertRaises(worker.ReviewError):
            worker.merge_proposal(self.pack, self.proposal)

    def test_no_second_approval_no_source_approval(self):
        self.verifier["approved"] = False
        with self.assertRaises(worker.ReviewError):
            worker.merge_proposal(self.pack, self.proposal)

    def test_fabricated_quote_rejected(self):
        self.decision["quotes"] = ["An invented new requirement"]
        with self.assertRaises(worker.ReviewError):
            worker.merge_proposal(self.pack, self.proposal)

    def test_evidence_tampering_rejected(self):
        self.evidence["after"] += "Different law"
        with self.assertRaises(worker.ReviewError):
            worker.merge_proposal(self.pack, self.proposal)

    def test_nonofficial_endpoint_rejected(self):
        self.evidence["url"] = "https://untrusted.example/law"
        with self.assertRaises(worker.ReviewError):
            worker.merge_proposal(self.pack, self.proposal)

    def test_empty_legal_patch_cannot_clear_block(self):
        self.decision.update(classification="effective_change", effective_on="2026-10-01", effective_timezone="Europe/Malta")
        with self.assertRaises(worker.ReviewError):
            worker.merge_proposal(self.pack, self.proposal)

    def test_metadata_cannot_change_statutory_rules(self):
        self.decision["patches"] = [{"path": "/coverage_groups/EU/statutory_withdrawal_days", "value_json": "15"}]
        with self.assertRaises(worker.ReviewError):
            worker.merge_proposal(self.pack, self.proposal)

    def test_single_country_cannot_modify_shared_baseline(self):
        self.law_patch()
        self.decision["patches"] = [{"path": "/coverage_groups/EU/statutory_withdrawal_days", "value_json": "15"}]
        with self.assertRaises(worker.ReviewError):
            worker.merge_proposal(self.pack, self.proposal)

    def test_signature_verification_date_identity_paths_not_writable(self):
        for path in ("/verified_on", "/reviewed_source_fingerprints/any/url", "/official_sources/EU/0", "/country_overlays/Malta/unknown"):
            with self.subTest(path=path), self.assertRaises(worker.ReviewError):
                worker._apply_patches(copy.deepcopy(self.pack), [{"path": path, "value_json": '"anything"'}])

    def test_invalid_numeric_rule_type_and_range_refused(self):
        for value in ('"14"', "true", "0", "-1", "999"):
            with self.subTest(value=value), self.assertRaises(worker.ReviewError):
                worker._apply_patches(copy.deepcopy(self.pack), [{"path": "/coverage_groups/EU/statutory_withdrawal_days", "value_json": value}])

    def test_additional_clause_is_data_not_model_code(self):
        clause = "Mandatory consumer remedies remain available under the supplied official amendment."
        pack = copy.deepcopy(self.pack)
        worker._apply_patches(pack, [{"path": "/country_overlays/Malta/additional_legal_clauses/Legal Notice ~1 Imprint", "value_json": json.dumps(clause)}])
        self.assertEqual(pack["country_overlays"]["Malta"]["additional_legal_clauses"]["Legal Notice / Imprint"], clause)
        with self.assertRaises(worker.ReviewError):
            worker._apply_patches(pack, [{"path": "/country_overlays/Malta/additional_legal_clauses/Shipping Policy", "value_json": '"<script>unsafe generated code</script>"'}])

    def test_cloud_merge_increments_version_and_deduplicates(self):
        root = Path(self.temp.name)/"repository"
        write_json(root/"legal_rulepack.json", self.pack)
        write_json(root/"automation_state/codex_proposals/a.json", self.proposal)
        self.assertEqual(worker.apply_cloud_proposals(root), [self.proposal_id])
        active = json.loads((root/"legal_rulepack.json").read_text(encoding="utf-8"))
        self.assertNotEqual(active["rulepack_version"], self.pack["rulepack_version"])
        self.assertEqual(worker.apply_cloud_proposals(root), [])

    def test_cloud_rebase_conflict_preserves_active_rules(self):
        root = Path(self.temp.name)/"repository"
        write_json(root/"legal_rulepack.json", self.pack)
        self.proposal["base_rulepack_sha256"] = "b"*64
        write_json(root/"automation_state/codex_proposals/a.json", self.proposal)
        self.assertEqual(worker.apply_cloud_proposals(root), [])
        self.assertEqual(json.loads((root/"legal_rulepack.json").read_text(encoding="utf-8")), self.pack)

    def test_no_model_calls_without_pending_change(self):
        self.enable()
        write_json(worker.folder()/"knowledge_coverage_latest.json", {"changed": []})
        with patch("codex_review_worker.review") as review:
            self.assertEqual(worker.run()["state"], "current")
            review.assert_not_called()

    def test_cloud_never_uses_local_account_credentials(self):
        self.enable()
        with patch.dict(os.environ, GITHUB_ACTIONS="true"), patch("subprocess.Popen") as popen:
            worker.launch_if_needed()
            popen.assert_not_called()

    def test_replacement_records_only_the_reviewed_official_body(self):
        from knowledge_update import SOURCES
        self.source = "EU Consumer Rights Directive"
        original, replacement = SOURCES[self.source][-1], SOURCES[self.source][0]
        self.evidence.update(source=self.source, url=original, old_url=replacement, new_url=replacement)
        self.proposal["id"] = worker.digest({"source": self.source, "url": original,
                     "new": self.evidence["new_sha256"], "base": worker.digest(self.pack)})
        result = worker.merge_proposal(self.pack, self.proposal)
        self.assertEqual(result["reviewed_source_replacements"][self.source][original]["url"], replacement)
        self.assertEqual(result["reviewed_source_fingerprints"][self.source][replacement], self.evidence["new_sha256"])

    def test_fabricated_replacement_not_allowed(self):
        self.evidence["new_url"] = "https://untrusted.example/statute"
        with self.assertRaises(worker.ReviewError):
            worker.merge_proposal(self.pack, self.proposal)

    def test_replacement_requires_fresh_signed_body_to_resolve_pending(self):
        import knowledge_update as knowledge
        name = "EU Consumer Rights Directive"
        old_url, replacement = knowledge.SOURCES[name][-1], knowledge.SOURCES[name][0]
        pack = copy.deepcopy(self.pack)
        pack["legal_versions"].update(knowledge._scheduled_legal_versions(pack))
        pack["reviewed_source_fingerprints"] = {name: {replacement: "b"*64}}
        pack["reviewed_source_replacements"] = {name: {old_url: {"url": replacement, "sha256": "b"*64}}}
        for observed, should_resolve in (("b"*64, True), ("c"*64, False)):
            write_json(knowledge._cache_path(), {"schema":knowledge.FINGERPRINT_SCHEMA, "sources":{name:{old_url:"a"*64,replacement:"a"*64}}})
            write_json(knowledge._cache_path().parent/"knowledge_coverage_latest.json", {"changed":[name], "pending_source_fingerprints":{name:{old_url:"d"*64}}})
            with patch.dict(knowledge.SOURCES,{name:(old_url,replacement)},clear=True), patch("knowledge_update.load_rulepack",return_value=pack), patch("knowledge_update.update_from_manifest",return_value={"state":"current"}), patch("knowledge_update._fingerprint_source",return_value={replacement:observed}):
                result = knowledge.run_startup_check()
            self.assertEqual(name not in result["changed"], should_resolve)

    @unittest.skipUnless(sys.platform == "win32", "Windows byte-range locking")
    def test_occupied_worker_lock_exits_without_read_error(self):
        import msvcrt
        with worker.worker_lock() as acquired:
            self.assertTrue(acquired)
            with (worker.folder()/"codex_review.lock").open("a+b") as second:
                second.seek(0)
                with self.assertRaises(OSError):
                    msvcrt.locking(second.fileno(), msvcrt.LK_NBLCK, 1)
            with worker.worker_lock() as second_acquired:
                self.assertFalse(second_acquired)


if __name__ == "__main__":
    unittest.main()
