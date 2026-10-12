import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from update_storage import write_json


@unittest.skipUnless(os.name=='nt','Windows installer')
class StartupInstallerTests(unittest.TestCase):
    def test_same_version_live_other_helper_is_superseded(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            target,stage=root/'target.exe',root/'stage.exe'
            target.write_bytes(b'old synthetic application')
            stage.write_bytes(b'new synthetic application')
            expected=hashlib.sha256(stage.read_bytes()).hexdigest()
            write_json(root/'pending_app_update.json',{'helper_pid':os.getpid(),'version':'2026.10.12-17',
                'sha256':expected,'staged':str(root/'another-stage.exe')})
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                '-File',str(Path('apply_app_update.ps1').resolve()),'-ParentPid',str(os.getpid()),
                '-Target',str(target),'-Staged',str(stage),'-ExpectedHash',expected,
                '-StatusFile',str(root/'status.json'),'-CandidateVersion','2026.10.12-17'],capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0)
            self.assertEqual(json.loads((root/'status.json').read_text(encoding='utf-8-sig'))['state'],'superseded')
            self.assertEqual(target.read_bytes(),b'old synthetic application')

    def test_restart_flag_parser_and_cancel_scope_are_present(self):
        # Real end-to-end relaunch uses the signed compiled release audit,
        # not a fake executable which would invoke the user's desktop.
        text=Path('apply_app_update.ps1').read_text(encoding='ascii')
        self.assertIn('[switch]$RestartAfterInstall',text)
        self.assertIn('$cancel.parent_pid -eq $ParentPid',text)
        self.assertIn('--startup-update-applied',text)
        self.assertIn('--startup-update-recovery',text)


if __name__=='__main__':unittest.main()
