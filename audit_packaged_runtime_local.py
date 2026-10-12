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
for role in ("legacy-parent", "parent"):
    with tempfile.TemporaryDirectory(prefix="policy-runtime-audit-") as directory:
        env = dict(os.environ, LOCALAPPDATA=directory, POLICY_AMADEUS_PACKAGED_AUDIT="1",
                   PYINSTALLER_RESET_ENVIRONMENT="1")
        launched = subprocess.run([exe, "--runtime-audit", role], env=env,
            timeout=45, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if launched.returncode:
            raise RuntimeError(f"Compiled audit parent exited {launched.returncode}")
        report = Path(directory)/"Policy Amadeus/child_finished.json"
        deadline = time.monotonic() + 45
        while not report.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        if not report.exists():
            started = Path(directory)/"Policy Amadeus/child_started.json"
            results[role] = {"finished": False, "started": started.exists()}
        else:
            results[role] = {"finished": True, **json.loads(report.read_text(encoding="utf-8"))}
print(json.dumps(results, ensure_ascii=False))
fixed = results["parent"]
if not (fixed.get("independent_resources") and fixed.get("imports_ok") and fixed.get("parent_resources_removed")):
    raise SystemExit("Independent background runtime failed")
if results["legacy-parent"].get("independent_resources"):
    raise SystemExit("Negative control did not exercise inherited runtime")
