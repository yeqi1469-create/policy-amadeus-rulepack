"""Independent licence UI uses synthetic identity, never a legal bypass."""
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from policy_studio import PolicyStudio


class IndependentLicenseTests(unittest.TestCase):
    def test_worker_does_not_call_policy_generator_or_update_gate(self):
        app = Mock(_license_queue=queue.Queue())
        fields = {"legal_name": "Synthetic Example Ltd", "registration_number": "12345678"}
        with patch("policy_studio.extract_license_fields", return_value=fields) as extract, \
             patch("policy_studio.generate_translated_bundle", side_effect=AssertionError("policy gate")), \
             patch("policy_studio.get_status", side_effect=AssertionError("update dependency")):
            PolicyStudio._extract_license_worker(app, "synthetic.pdf")
        extract.assert_called_once_with("synthetic.pdf")
        self.assertEqual(app._license_queue.get_nowait(), ("ok", fields))

    def test_failed_worker_returns_safe_error_and_no_fields(self):
        app = Mock(_license_queue=queue.Queue())
        with patch("policy_studio.extract_license_fields", side_effect=RuntimeError("private payload")):
            PolicyStudio._extract_license_worker(app, "synthetic.pdf")
        state, message = app._license_queue.get_nowait()
        self.assertEqual(state, "error")
        self.assertNotIn("private payload", message)

    def test_cancelled_selection_does_not_launch_worker(self):
        app = Mock(_license_busy=False)
        with patch("policy_studio.filedialog.askopenfilename", return_value=""), patch("policy_studio.threading.Thread") as thread:
            PolicyStudio._extract_license(app)
        thread.assert_not_called()
        app.pdf_path.set.assert_not_called()

    def test_result_available_from_all_steps_while_updates_blocked(self):
        blocked = {"state": "review_required", "message": "政策尚未更新",
                   "update_status": {"state": "retry_pending"}}
        with patch("policy_studio.start_startup_check"), patch("policy_studio.get_status", return_value=blocked), \
             patch.object(PolicyStudio, "_load_config"), \
             patch.object(PolicyStudio, "_set_card_transparency"), patch.object(PolicyStudio, "_apply_windows_icons"):
            app = PolicyStudio()
            app.withdraw()
            try:
                for step in range(3):
                    app.show_step(step)
                    self.assertEqual(str(app._license_button["state"]), "normal")
                app._license_queue.put(("ok", {"legal_name": "Synthetic Example Ltd", "registration_number": "12345678"}))
                app._license_busy = True
                app._poll_license()
                app._license_window.withdraw()
                app.update_idletasks()
                def texts(widget):
                    for child in widget.winfo_children():
                        if child.winfo_class() == "Text":
                            yield child.get("1.0", "end")
                        yield from texts(child)
                self.assertIn("Synthetic Example Ltd", "".join(texts(app._license_window)))
                self.assertIn("未识别", "".join(texts(app._license_window)))
                self.assertFalse(app._license_busy)
                self.assertEqual(app.policies, [])
                self.assertEqual(app.settings, {})
                self.assertEqual(app.step, 2)
                app._show_license_fields({})
                app._license_window.withdraw()
                self.assertNotIn("Synthetic Example Ltd", "".join(texts(app._license_window)))
            finally:
                app.destroy()

    def test_selection_requires_only_valid_pdf_not_store_contact_or_country(self):
        app = Mock(_license_busy=False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.pdf"
            path.touch()
            with patch("policy_studio.filedialog.askopenfilename", return_value=str(path)), \
                 patch("policy_studio.threading.Thread") as thread:
                PolicyStudio._extract_license(app)
            app.pdf_path.set.assert_called_once_with(str(path))
            thread.assert_called_once_with(target=app._extract_license_worker, args=(str(path),), daemon=True)
            app.country.get.assert_not_called()
            app.phone.get.assert_not_called()
            app._app_dialog.assert_not_called()


if __name__ == "__main__":
    unittest.main()
