import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from update_storage import write_json


class InstallSelectionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows installer")
    def test_superseded_package_never_replaces_current_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, old, latest = root/"application.exe", root/"old.exe", root/"latest.exe"
            target.write_bytes(b"existing application")
            old.write_bytes(b"old signed candidate fixture")
            latest.write_bytes(b"new signed candidate fixture")
            write_json(root/"pending_app_update.json", {"helper_pid":os.getpid(), "staged":str(latest),
                "sha256":hashlib.sha256(latest.read_bytes()).hexdigest()})
            result = subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass",
                "-File",str(Path("apply_app_update.ps1").resolve()),"-ParentPid",str(os.getpid()),
                "-Target",str(target),"-Staged",str(old),"-ExpectedHash",hashlib.sha256(old.read_bytes()).hexdigest(),
                "-StatusFile",str(root/"status.json")],capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0)
            self.assertEqual(json.loads((root/"status.json").read_text(encoding="utf-8-sig"))["state"],"superseded")
            self.assertEqual(target.read_bytes(),b"existing application")
            self.assertTrue(latest.exists())
            self.assertFalse(old.exists())
