import json,queue,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import session_checkpoint as checkpoint
from policy_studio import PolicyStudio

class AutomaticDraftHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.path=self.root/'private_session_checkpoint.json'
    def tearDown(self): self.temp.cleanup()
    def test_private_draft_roundtrip_version_gate_and_consumption(self):
        config={'store_name':'Synthetic private draft','email':'test@example.invalid'}
        checkpoint.save(self.path,'2026.10.12-21',config,2,[('Terms of Service','Synthetic text')],{})
        self.assertIsNone(checkpoint.restore(self.path,'2026.10.12-20'))
        self.assertEqual(checkpoint.restore(self.path,'2026.10.12-21')['config'],config)
        checkpoint.acknowledge(self.path)
        self.assertIsNone(checkpoint.restore(self.path,'2026.10.12-21'))
        self.assertEqual(json.loads(self.path.read_text())['saved_policy_result']['policies'][0][1],'Synthetic text')
    def fake_gui(self,busy=False):
        events=queue.Queue()
        events.put(('ok',{'app':'installation_staged','new_version':'2026.10.12-21'}))
        return SimpleNamespace(_app_handoff_started=True,_app_handoff_retry_after=0,_app_handoff_failures=0,
            _app_handoff_queue=events,_app_handoff_result=None,_license_busy=busy,_generation_active=False,
            _draft_config=lambda:{'store_name':'Synthetic unsaved input'},_config_path=lambda:self.root/'config.json',
            knowledge_status=Mock(),software_status=Mock(),step=1,policies=[],settings={},destroy=Mock())
    def test_saves_and_verifies_before_automatic_close(self):
        gui=self.fake_gui()
        with patch('app_updater.sys.frozen',True,create=True),patch('app_updater._data_dir',return_value=self.root):
            PolicyStudio._automatic_update_handoff(gui,{})
        gui.destroy.assert_called_once()
        self.assertEqual(checkpoint.restore(self.path,'2026.10.12-21')['config']['store_name'],'Synthetic unsaved input')
        self.assertEqual(json.loads((self.root/'config.json').read_text())['store_name'],'Synthetic unsaved input')
    def test_active_license_task_does_not_close_window(self):
        gui=self.fake_gui(busy=True)
        with patch('app_updater.sys.frozen',True,create=True),patch('app_updater._data_dir',return_value=self.root):
            PolicyStudio._automatic_update_handoff(gui,{})
        gui.destroy.assert_not_called()
        self.assertFalse(self.path.exists())
    def test_failed_checkpoint_never_closes_or_loses_input(self):
        gui=self.fake_gui()
        with patch('app_updater.sys.frozen',True,create=True),patch('app_updater._data_dir',return_value=self.root),patch.object(checkpoint,'save',side_effect=PermissionError):
            PolicyStudio._automatic_update_handoff(gui,{})
        gui.destroy.assert_not_called()
    def test_corrupt_local_checkpoint_is_not_loaded(self):
        self.path.write_text('{corrupt',encoding='utf-8')
        self.assertIsNone(checkpoint.restore(self.path,'2026.10.12-21'))
    def test_failed_install_reenters_verified_handoff_without_manual_restart(self):
        for state in ('installation_failed','restart_needed'):
            gui=self.fake_gui(busy=True)
            gui._app_handoff_started=False
            gui._app_handoff_queue=queue.Queue()
            with patch('app_updater.sys.frozen',True,create=True),patch('policy_studio.sys.platform','win32'), \
                 patch('policy_studio.threading.Thread') as thread:
                PolicyStudio._automatic_update_handoff(gui,{'app':state})
            thread.return_value.start.assert_called_once()
            self.assertTrue(gui._app_handoff_started)
            gui.destroy.assert_not_called()

if __name__=='__main__': unittest.main()
