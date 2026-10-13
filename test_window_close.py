import unittest
from unittest.mock import patch
from policy_studio import PolicyStudio

class ModalCloseTests(unittest.TestCase):
    def create_app(self):
        with patch.object(PolicyStudio,'_load_config'),patch.object(PolicyStudio,'_set_card_transparency'),patch.object(PolicyStudio,'_apply_windows_icons'):
            app=PolicyStudio()
        app.withdraw()
        return app
    def test_close_main_window_releases_modal_wait(self):
        app=self.create_app()
        app.after(20,app.destroy)
        self.assertIsNone(app._app_dialog('Synthetic test','Synthetic modal'))
        self.assertTrue(app._destroying)
    def test_confirm_still_returns_normally(self):
        app=self.create_app()
        def invoke(widget):
            for child in widget.winfo_children():
                if child.winfo_class()=='Button' and child.cget('text')=='确定':
                    child.invoke()
                    return True
                if invoke(child): return True
            return False
        app.after(20,lambda:invoke(app.card))
        try: self.assertEqual(app._app_dialog('Synthetic test','Synthetic modal'),'__OK__')
        finally: app.destroy()

if __name__=='__main__': unittest.main()
