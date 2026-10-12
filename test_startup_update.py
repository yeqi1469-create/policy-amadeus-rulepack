import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import startup_update as startup
import knowledge_update as knowledge


class StartupUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,LOCALAPPDATA=self.temp.name)
        env.start()
        self.addCleanup(env.stop)

    def test_current_version_continues_without_restart(self):
        with patch.object(startup.app_updater,'_stage_app_update',return_value={'app':'current'}) as stage:
            self.assertEqual(startup.startup_check(Mock(),threading.Event()),'continue')
        self.assertTrue(stage.call_args.kwargs['restart_after_install'])

    def test_new_version_hands_off_before_any_editable_input(self):
        with patch.object(startup.app_updater,'_stage_app_update',return_value={'app':'installation_staged'}):
            self.assertEqual(startup.startup_check(Mock(),threading.Event()),'handoff')

    def test_cancelled_start_does_not_download_or_restart(self):
        event=threading.Event()
        event.set()
        with patch.object(startup.app_updater,'_stage_app_update') as stage:
            self.assertEqual(startup.startup_check(Mock(),event),'cancelled')
        stage.assert_not_called()

    def test_network_failure_falls_back_without_erasing_findings(self):
        folder=startup.app_updater._data_dir()
        marker=folder/'knowledge_coverage_latest.json'
        marker.write_text('synthetic retained finding',encoding='utf-8')
        with patch.object(startup.app_updater,'_stage_app_update',side_effect=TimeoutError('private payload')):
            self.assertEqual(startup.startup_check(Mock(),threading.Event()),'continue')
        self.assertEqual(marker.read_text(encoding='utf-8'),'synthetic retained finding')
        status=json.loads((folder/'startup_update_status.json').read_text(encoding='utf-8'))
        self.assertNotIn('private payload',json.dumps(status))

    def test_small_startup_window_has_wrapping_status_and_cancel_cleanup(self):
        app=startup.StartupUpdateWindow()
        try:
            app.geometry('480x240')
            app.operation.set('更新已验证，正在自动安装并重新进入程序；当前步骤需要等待签名验证完成。')
            app.update()
            self.assertLessEqual(int(app.operation_label.cget('wraplength')),424)
            self.assertEqual(app.result,'cancelled')
            app.cancel_startup()
            self.assertTrue(app.cancelled.is_set())
        finally:
            try:
                if app.winfo_exists(): app.destroy()
            except startup.tk.TclError:
                pass


class RelevantMarketGateTests(unittest.TestCase):
    def call(self,changes,markets):
        status={'state':'review_required','changed':changes,'message':'pending'}
        with patch.object(knowledge,'get_status',return_value=status),patch('codex_review_worker.enabled',return_value=False):
            return knowledge.require_no_detected_change(markets=markets)

    def test_other_country_not_approved_or_erased(self):
        changes=['Country — Ukraine','Country — Montenegro']
        result=self.call(changes,['Germany','Denmark'])
        self.assertEqual(result['state'],'applicable_markets_clear')
        self.assertEqual(result['changed'],changes)
        self.assertEqual(result['unrelated_findings'],changes)

    def test_market_operator_and_shared_baseline_still_block(self):
        for source in ['Country — Germany','Country — Denmark','EU Consumer Rights Directive']:
            with self.subTest(source=source),self.assertRaises(RuntimeError):
                self.call([source],['Germany','Denmark'])

    def test_unknown_operator_never_reduces_scope(self):
        for markets in (None,[],['Unverified operator country']):
            with self.subTest(markets=markets),self.assertRaises(RuntimeError):
                self.call(['Country — Montenegro'],markets)


if __name__=='__main__': unittest.main()
