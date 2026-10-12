"""Test an actual EXE after its launching process exits, using synthetic data."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

exe = str(Path(sys.argv[1]).resolve())
results = {}
for role in ("parent",):
    with tempfile.TemporaryDirectory(prefix="policy-runtime-audit-") as directory:
        env = dict(os.environ, LOCALAPPDATA=directory, POLICY_AMADEUS_PACKAGED_AUDIT="1",
                   PYINSTALLER_RESET_ENVIRONMENT="1")
        launched = subprocess.run([exe, "--runtime-audit", role], env=env,
            timeout=45, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if launched.returncode:
            raise RuntimeError(f"Compiled audit parent exited {launched.returncode}")
        report = Path(directory)/"Policy Amadeus/child_finished.json"
        deadline = time.monotonic() + 45
        while not report.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        if not report.exists():
            started = Path(directory)/"Policy Amadeus/child_started.json"
            failure = Path(directory)/"Policy Amadeus/audit_entry_failure.txt"
            results[role] = {"finished": False, "started": started.exists(),
                             "entry_failure": failure.read_text(encoding="utf-8") if failure.exists() else ""}
        else:
            results[role] = {"finished": True, **json.loads(report.read_text(encoding="utf-8"))}
        # The result is written just before the worker exits. Its bootloader
        # may still own stdout; wait for that handle instead of deleting a
        # live worker's log or mistaking cleanup timing for runtime failure.
        log = Path(directory)/"Policy Amadeus/worker.log"
        close_deadline = time.monotonic() + 30
        while log.exists():
            try:
                log.rename(log.with_suffix(".finished.log"))
                break
            except PermissionError:
                if time.monotonic() >= close_deadline:
                    raise RuntimeError("Compiled worker did not release its log after finishing")
                time.sleep(0.2)
print(json.dumps(results, ensure_ascii=False))
fixed = results["parent"]
if not (fixed.get("independent_resources") and fixed.get("imports_ok") and fixed.get("parent_resources_removed")):
    raise SystemExit("Independent background runtime failed")
