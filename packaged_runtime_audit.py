"""Offline compiled-process lifecycle audit. No review, credentials or network."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def run() -> None:
    if os.environ.get("POLICY_AMADEUS_PACKAGED_AUDIT") != "1" or not getattr(sys, "frozen", False):
        raise RuntimeError("Compiled audit requires explicit isolated test mode")
    from update_storage import write_json
    from codex_review_worker import folder, spawn_review_process, failure_details
    root = folder()
    root.mkdir(parents=True, exist_ok=True)
    role = sys.argv[sys.argv.index("--runtime-audit") + 1]
    if role == "parent":
        write_json(root/"parent.json", {"resources": sys._MEIPASS, "pid": os.getpid()})
        command = [sys.executable, "--runtime-audit", "child"]
        spawn_review_process(command, root/"worker.log")
        deadline = time.monotonic() + 15
        while not (root/"child_started.json").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not (root/"child_started.json").exists():
            raise RuntimeError("Compiled worker did not start")
        return
    if role != "child":
        raise RuntimeError("Invalid compiled audit role")
    parent = json.loads((root/"parent.json").read_text(encoding="utf-8"))
    result = {"independent_resources": sys._MEIPASS != parent["resources"], "imports_ok": False}
    write_json(root/"child_started.json", result)
    # Wait for the parent's bootloader to remove its unpacked resources.
    deadline = time.monotonic() + 30
    while Path(parent["resources"]).exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    result["parent_resources_removed"] = not Path(parent["resources"]).exists()
    try:
        import requests
        import charset_normalizer
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from pypdf import PdfReader
        from zoneinfo import ZoneInfo
        from app_updater import installed_version
        from official_document import extract_official_document
        ZoneInfo("Europe/Helsinki")
        result.update(imports_ok=True, app_version=installed_version())
    except Exception as exc:
        result.update(failure_details(exc))
    write_json(root/"child_finished.json", result)
