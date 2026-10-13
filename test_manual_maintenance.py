import ast,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import policy_entry
import knowledge_update
import policy_studio

class ManualMaintenanceTests(unittest.TestCase):
    def test_retired_background_arguments_do_nothing(self):
        for flag in ('--auto-review','--auto-update','--review-health'):
            with patch('policy_entry.sys.argv',['program',flag]),patch.object(policy_studio,'PolicyStudio') as gui:
                policy_entry.main()
            gui.assert_not_called()
    def test_gui_has_no_update_actions(self):
        for method in ('_automatic_update_handoff','_poll_knowledge_check','_show_update_details','_update_progress'):
            self.assertFalse(hasattr(policy_studio.PolicyStudio,method))
    def test_offline_known_legal_finding_is_not_erased_or_approved(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,LOCALAPPDATA=folder),patch('rulepack_manager.load_rulepack',return_value={'rulepack_version':'synthetic'}):
            path=Path(folder)/'Policy Amadeus'
            path.mkdir()
            report=path/'knowledge_coverage_latest.json'
            text=json.dumps({'rulepack_version':'synthetic','changed':['Country — Latvia']})
            report.write_text(text,encoding='utf-8')
            with self.assertRaises(RuntimeError): knowledge_update.require_no_detected_change(['Latvia'])
            self.assertEqual(report.read_text(encoding='utf-8'),text)
    def test_packaged_modules_exclude_automatic_services(self):
        source=Path('Shopify Policy Studio.spec').read_text(encoding='utf-8')
        self.assertIn("'app_updater'",source)
        self.assertNotIn("('apply_app_update.ps1', '.')",source)
        self.assertNotIn("('register_update_tasks.ps1', '.')",source)

if __name__=='__main__': unittest.main()
