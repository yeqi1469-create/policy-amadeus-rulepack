import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from automation_pipeline import apply_reviewed_changes
from update_storage import write_json


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.pack = json.loads(Path("legal_rulepack.json").read_text(encoding="utf-8"))
        self.entries = json.loads(Path("reviewed_changes.json").read_text(encoding="utf-8"))
        for entry in self.entries:
            self.pack["legal_versions"].pop(entry["legal_version_name"], None)

    def test_future_change_is_not_applied_early(self):
        original = copy.deepcopy(self.pack)
        self.assertEqual(apply_reviewed_changes(self.pack, self.entries, date(2026, 9, 29)), [])
        self.assertEqual(self.pack, original)

    def test_reviewed_change_activates_once(self):
        self.assertEqual(len(apply_reviewed_changes(self.pack, self.entries, date(2026, 10, 1))), 2)
        self.assertTrue(self.pack["country_overlays"]["Austria"]["electronic_withdrawal_function"])
        self.assertEqual(apply_reviewed_changes(self.pack, self.entries, date(2026, 10, 1)), [])

    def test_unreviewed_changes_cannot_modify_rules(self):
        self.entries[0]["review_status"] = "pending"
        self.assertNotIn(self.entries[0]["legal_version_name"], apply_reviewed_changes(self.pack, self.entries, date(2026, 10, 1)))

    def test_unsupported_patch_is_rejected(self):
        self.entries[0]["overlay_updates"]["statutory_withdrawal_days"] = 0
        with self.assertRaises(ValueError):
            apply_reviewed_changes(self.pack, self.entries, date(2026, 10, 1))

    def test_atomic_write_failure_preserves_old_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_json(path, {"old": True})
            with patch("update_storage.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    write_json(path, {"new": True})
            self.assertEqual(json.loads(path.read_text()), {"old": True})

    def test_cloud_signing_never_generates_replacement_secret(self):
        import os
        from publisher_tools import init_key
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "POLICY_AMADEUS_PUBLISHER_KEY_B64": ""}):
            with self.assertRaises(RuntimeError):
                init_key()

    def test_waiting_install_does_not_duplicate_download(self):
        import os
        from datetime import datetime
        from app_updater import _already_staged
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            root = Path(directory) / "Policy Amadeus"
            root.mkdir()
            staged = root / "staged.exe"
            staged.write_bytes(b"MZ")
            write_json(root / "pending_app_update.json", {"version": "new", "sha256": "a" * 64,
                       "staged": str(staged), "created_at": datetime.now().timestamp(), "helper_pid": 123})
            with patch('app_updater._helper_alive', return_value=True):
                self.assertTrue(_already_staged("new", "a" * 64))
                self.assertFalse(_already_staged("different", "a" * 64))
            with patch('app_updater._helper_alive', return_value=False):
                self.assertFalse(_already_staged("new", "a" * 64))

    @unittest.skipUnless(__import__('sys').platform == 'win32', 'Windows PowerShell compatibility')
    def test_windows_powershell_can_parse_installer(self):
        import subprocess
        helper = str(Path('apply_app_update.ps1').resolve()).replace("'", "''")
        # Windows PowerShell 5.1 reads BOM-less scripts through the local code
        # page. ASCII prevents Chinese string bytes from becoming quote tokens.
        Path('apply_app_update.ps1').read_bytes().decode('ascii')
        command = "$tokens=$null; $errors=$null; [System.Management.Automation.Language.Parser]::ParseFile('" + helper + "',[ref]$tokens,[ref]$errors) | Out-Null; if ($errors.Count) { $errors | Out-String | Write-Output; exit 1 }"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))

    @unittest.skipUnless(__import__('sys').platform == 'win32', 'Windows installer integration')
    def test_installer_replaces_file_and_rejects_bad_hash(self):
        import hashlib
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target.exe'
            staged = root / 'staged.exe'
            status = root / 'status.json'
            old, new = b'old harmless test file', b'new harmless test file'
            helper = str(Path('apply_app_update.ps1').resolve())
            for expected, outcome in [(hashlib.sha256(new).hexdigest(), 'installed'), ('0' * 64, 'failed')]:
                target.write_bytes(old)
                staged.write_bytes(new)
                result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                    '-File', helper, '-ParentPid', str(os.getpid()), '-Target', str(target), '-Staged', str(staged),
                    '-ExpectedHash', expected, '-StatusFile', str(status)], capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                report = json.loads(status.read_text(encoding='utf-8-sig'))
                self.assertEqual(report['state'], outcome, report)
                self.assertEqual(target.read_bytes(), new if outcome == 'installed' else old)
                if outcome == 'installed':
                    self.assertEqual(Path(str(target) + '.backup').read_bytes(), old)

    def test_first_observation_is_not_claimed_as_verified_no_change(self):
        import os
        import knowledge_update as knowledge
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            with patch("knowledge_update.update_from_manifest", return_value={"state": "current"}), patch("knowledge_update._fingerprint_source", side_effect=lambda urls: {urls[0]: "a" * 64}):
                knowledge.run_startup_check()
            coverage = json.loads((knowledge._cache_path().parent / "knowledge_coverage_latest.json").read_text(encoding="utf-8"))
            self.assertEqual(coverage["countries"]["Germany"]["status"], "baseline_requires_review")
            self.assertFalse(coverage["countries"]["Germany"]["full_national_legal_review_completed"])

    def test_open_gui_adopts_newer_completed_background_report(self):
        import os
        import knowledge_update as knowledge
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            report = {"checked_at": "2026-09-30T12:00:00+08:00", "state": "partial", "message": "Reviewed update applied",
                      "changed": [], "unreachable": ["Country — Iceland"], "rulepack_version": self.pack["rulepack_version"]}
            write_json(knowledge._cache_path().parent / "knowledge_coverage_latest.json", report)
            with patch.dict(knowledge._STATUS, {"checked_at": "2026-09-30T11:00:00+08:00", "state": "review_required", "changed": ["Country — Austria"]}, clear=True), patch("knowledge_update.load_rulepack", return_value=self.pack):
                self.assertEqual(knowledge.get_status()["changed"], [])
                self.assertEqual(knowledge.get_status()["state"], "partial")

    def test_app_release_check_precedes_slow_government_scan(self):
        from app_updater import run_auto_update
        order = []
        with patch("app_updater._stage_app_update", side_effect=lambda: order.append("app") or {"app": "current"}), patch("knowledge_update.run_startup_check", side_effect=lambda **kwargs: order.append("knowledge") or {}), patch("app_updater._record", side_effect=lambda result: result):
            run_auto_update()
        self.assertEqual(order, ["app", "knowledge"])

    def test_scheduled_gate_uses_each_country_calendar(self):
        from datetime import datetime, timezone
        from knowledge_update import _scheduled_legal_versions
        with patch("knowledge_update.datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 30, 21, 30, tzinfo=timezone.utc)
            versions = _scheduled_legal_versions(self.pack)
        self.assertNotIn("Austrian FAGG electronic withdrawal function", versions)
        self.assertIn("Finnish deferred-payment identity verification", versions)

    def test_signed_exact_review_does_not_clear_other_changes(self):
        import os
        import knowledge_update as knowledge
        german = knowledge.SOURCES["Country — Germany"][0]
        french = knowledge.SOURCES["Country — France"][0]
        pack = copy.deepcopy(self.pack)
        pack["reviewed_source_fingerprints"] = {"Country — Germany": {german: "b" * 64}}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            write_json(knowledge._cache_path(), {"schema": knowledge.FINGERPRINT_SCHEMA, "sources": {
                "Country — Germany": {german: "a" * 64}, "Country — France": {french: "a" * 64}}})
            with patch("knowledge_update.load_rulepack", return_value=pack), patch("knowledge_update.update_from_manifest", return_value={"state": "updated"}), patch("knowledge_update._fingerprint_source", side_effect=lambda urls: {urls[0]: "b" * 64}):
                result = knowledge.run_startup_check()
            self.assertNotIn("Country — Germany", result["changed"])
            self.assertIn("Country — France", result["changed"])
            cache = json.loads(knowledge._cache_path().read_text(encoding="utf-8"))
            self.assertEqual(cache["sources"]["Country — France"][french], "a" * 64)
            self.assertEqual(cache["sources"]["Country — Germany"][german], "b" * 64)


if __name__ == "__main__":
    unittest.main()
