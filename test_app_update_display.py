import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_updater as updater
from update_progress import app_update_caption, progress_caption
from update_storage import write_json


class InstallationDisplayTests(unittest.TestCase):
    def test_waiting_for_exit_has_no_fake_countdown_or_agent_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            stage=root/"signed.exe"
            stage.write_bytes(b"synthetic")
            write_json(root/"pending_app_update.json",{"version":"2026.10.12-12","staged":str(stage),"helper_pid":1})
            with patch.object(updater,"_data_dir",return_value=root),patch.object(updater,"installed_version",return_value="2026.10.12-10"),patch.object(updater,"_helper_alive",return_value=True),patch("requests.get") as network:
                value=updater.read_app_update_status()
            self.assertEqual(value["app"],"waiting_for_app_exit")
            self.assertIn("10",app_update_caption(value))
            self.assertIn("12",app_update_caption(value))
            self.assertIn("窗口何时退出",progress_caption({"app_update_status":value,"update_status":{"state":"retry_pending"}}))
            network.assert_not_called()

    def test_dead_installer_is_not_displayed_as_running(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            stage=root/"signed.exe"
            stage.write_bytes(b"synthetic")
            write_json(root/"pending_app_update.json",{"version":"2026.10.12-12","staged":str(stage),"helper_pid":0})
            with patch.object(updater,"_data_dir",return_value=root),patch.object(updater,"installed_version",return_value="2026.10.12-10"),patch.object(updater,"_helper_alive",return_value=False):
                value=updater.read_app_update_status()
            self.assertEqual(value["app"],"installer_inactive")

    def test_installed_windows_bom_result_means_old_window_needs_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            write_json(root/"pending_app_update.json",{"version":"2026.10.12-12","staged":str(root/"removed-stage.exe")})
            (root/"app_install_status.json").write_text(json.dumps({"state":"installed"}),encoding="utf-8-sig")
            with patch.object(updater,"_data_dir",return_value=root),patch.object(updater,"installed_version",return_value="2026.10.12-10"):
                value=updater.read_app_update_status()
            self.assertEqual(value["app"],"restart_needed")
            self.assertIn("重开",app_update_caption(value))

    def test_current_program_does_not_imply_current_law(self):
        self.assertIn("独立状态",app_update_caption({"app":"current","installed_version":"2026.10.12-12"}))
