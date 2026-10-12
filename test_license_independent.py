"""Independent licence UI uses synthetic identity, never a legal bypass."""
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from policy_studio import PolicyStudio, license_information_rows, LICENSE_LABELS


class IndependentLicenseTests(unittest.TestCase):
    def test_worker_does_not_call_policy_generator_or_update_gate(self):
        app = Mock(_license_queue=queue.Queue())
        fields = {"legal_name": "Synthetic Example Ltd", "registration_number": "12345678"}
        with patch("policy_studio.extract_license_fields", return_value=fields) as extract, \
             patch("policy_studio.generate_translated_bundle", side_effect=AssertionError("policy gate")), \
             patch("policy_studio.get_status", side_effect=AssertionError("update dependency")):
            PolicyStudio._extract_license_worker(app, "synthetic.pdf")
        extract.assert_called_once_with("synthetic.pdf")
        self.assertEqual(app._license_queue.get_nowait(), ("ok", (fields, "synthetic.pdf")))

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
                app._license_queue.put(("ok", ({"legal_name": "Synthetic Example Ltd", "registration_number": "12345678"}, "synthetic.pdf")))
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
                self.assertEqual(len(app._license_fields_form.grid_slaves()), len(LICENSE_LABELS))
                self.assertEqual({int(item.grid_info()["column"]) for item in app._license_fields_form.grid_slaves()}, {0,1})
                app._show_license_fields({})
                app._license_window.withdraw()
                self.assertNotIn("Synthetic Example Ltd", "".join(texts(app._license_window)))
            finally:
                app.destroy()

    def test_licence_rows_are_identical_for_both_result_views(self):
        rows=license_information_rows({"legal_name":"Synthetic Example Ltd","street_address":"Long sample address"})
        self.assertEqual(len(rows),16)
        self.assertIn(("执照 · 法定名称","Synthetic Example Ltd"),rows)
        self.assertIn(("执照 · VAT ID（仅执照明确记载时）","未识别（请对照执照手动确认）"),rows)

    def test_result_filename_tracks_parsed_file_not_later_selection(self):
        with patch("policy_studio.start_startup_check"), patch.object(PolicyStudio,"_load_config"), \
             patch.object(PolicyStudio,"_set_card_transparency"),patch.object(PolicyStudio,"_apply_windows_icons"):
            app=PolicyStudio()
            app.withdraw()
            try:
                app.pdf_path.set("later-selection.pdf")
                app._license_queue.put(("ok",({"legal_name":"Synthetic Example Ltd"},"actually-parsed.pdf")))
                app._poll_license()
                app._license_window.withdraw()
                labels=[item.cget("text") for item in app._license_window.winfo_children() if item.winfo_class()=="Label"]
                self.assertIn("文件：actually-parsed.pdf",labels)
                self.assertNotIn("文件：later-selection.pdf",labels)
            finally:
                app.destroy()

    def test_long_field_copy_is_complete_and_small_window_can_scroll(self):
        with patch("policy_studio.start_startup_check"),patch.object(PolicyStudio,"_load_config"), \
             patch.object(PolicyStudio,"_set_card_transparency"),patch.object(PolicyStudio,"_apply_windows_icons"):
            app=PolicyStudio()
            app.withdraw()
            try:
                address="Synthetic Long Address, "*90
                app._show_license_fields({"legal_name":"Synthetic Example Ltd","street_address":address},"synthetic.pdf")
                app._license_window.geometry("660x440")
                app._license_window.update_idletasks()
                app._license_window.withdraw()
                box=app._license_fields_form.grid_slaves(row=4,column=0)[0]
                text=next(item for item in box.winfo_children() if item.winfo_class()=="Text")
                self.assertEqual(text.get("1.0","end-1c"),address.strip())
                self.assertLessEqual(int(text["height"]),8)
                heading=next(item for item in box.winfo_children() if item.winfo_class()=="Frame")
                button=next(item for item in heading.winfo_children() if item.winfo_class()=="Button")
                with patch.object(app,"clipboard_clear"),patch.object(app,"clipboard_append") as copy:
                    button.invoke()
                    copy.assert_called_once_with(address.strip())
                self.assertLess(app._license_result_scroll.yview()[1],1)
                app._license_result_scroll.yview_moveto(1)
                self.assertEqual(app._license_result_scroll.yview()[1],1)
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
