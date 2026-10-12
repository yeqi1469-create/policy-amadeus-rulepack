"""Own-widget layout checks, with synthetic state and no networking."""
import os
import tempfile
import unittest
from unittest.mock import patch

from policy_studio import PolicyStudio


class UpdateDetailsUITests(unittest.TestCase):
    def test_language_and_pdf_fields_survive_small_card_and_long_status(self):
        with patch("policy_studio.start_startup_check"), patch.object(PolicyStudio,"_load_config"), \
             patch.object(PolicyStudio,"_set_card_transparency"), patch.object(PolicyStudio,"_apply_windows_icons"):
            app = PolicyStudio()
            app.withdraw()
            try:
                app.knowledge_status.set("政策待审；已按需交接当前聊天；正在获取官方新旧正文。" * 3)
                for step in (0, 2):
                    app.show_step(step)
                    app.canvas.itemconfigure(app.card_window, width=640, height=420)
                    app.update_idletasks()
                    viewport = app._result_scroll_canvas
                    self.assertIsNotNone(viewport)
                    body = viewport.nametowidget(viewport.itemcget(viewport.find_all()[0], "window"))
                    children = body.winfo_children()
                    last = children[-1]
                    self.assertGreater(last.winfo_height(), 1)
                    self.assertGreater(body.winfo_height(), viewport.winfo_height())
                    viewport.yview_moveto(1)
                    app.update_idletasks()
                    self.assertLessEqual(last.winfo_rooty()+last.winfo_height(), viewport.winfo_rooty()+viewport.winfo_height()+2)
                    self.assertGreater(app.footer.winfo_height(), 30)
            finally:
                app.destroy()

    def test_steps_and_reopened_details_remain_readable(self):
        status = {"state":"review_required", "progress_percent":55,
                  "message":"正在独立复核官方正文和政策规则",
                  "update_status":{"state":"reviewing","stage":"verifying","progress_percent":55,
                                   "source":"Country — Montenegro","source_index":5,"source_total":7,
                                   "operation":"独立复核结论","model_round":2}}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,LOCALAPPDATA=directory,POLICY_AMADEUS_AUTOMATION_TEST="1"), \
             patch("policy_studio.start_startup_check"), patch("policy_studio.get_status",return_value=status), \
             patch.object(PolicyStudio,"_set_card_transparency"), patch.object(PolicyStudio,"_apply_windows_icons"):
            app = PolicyStudio()
            app.withdraw()
            try:
                app.progress_status = status
                app._update_progress()
                for step in range(3):
                    app.show_step(step)
                    app.canvas.itemconfigure(app.card_window,width=640,height=500)
                    app.update_idletasks()
                    self.assertGreater(app.content.winfo_height(),150)
                    self.assertLessEqual(app.progress.winfo_y()+app.progress.winfo_height(),app.footer.winfo_y())
                app._show_update_details()
                app._update_details_window.withdraw()
                self.assertIn("步骤 4/8",app._update_details_text.get("1.0","end"))
                app._update_details_window.destroy()
                app._show_update_details()
                app._update_details_window.withdraw()
                self.assertIn("独立复核结论",app._update_details_text.get("1.0","end"))
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
