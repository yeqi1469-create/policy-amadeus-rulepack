"""Unattended, no-paid-API maintenance. Unknown legal changes are never guessed."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from update_storage import write_json

BEIJING = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent


def apply_reviewed_changes(pack: dict, entries: list[dict], today: date) -> list[str]:
    """Only activate explicitly pre-reviewed, date-bound patches."""
    applied = []
    for entry in entries:
        if entry.get("review_status") != "approved" or not entry.get("evidence"):
            continue
        if today < date.fromisoformat(entry["effective_on"]):
            continue
        name = entry["legal_version_name"]
        version = entry["legal_version"]
        if pack.get("legal_versions", {}).get(name) == version:
            continue
        if not all(str(url).startswith("https://") for url in entry["evidence"]):
            raise ValueError("Reviewed changes require HTTPS official evidence")
        country = entry["country"]
        if country not in pack.get("country_overlays", {}):
            raise ValueError("Reviewed country overlay is missing")
        allowed = {"electronic_withdrawal_function", "withdrawal_start_label",
                   "withdrawal_confirm_label", "national_product_marketing_clause", "official_update_note"}
        updates = entry.get("overlay_updates", {})
        if set(updates) - allowed:
            raise ValueError("Unsupported automatic legal patch")
        pack["country_overlays"][country].update(updates)
        pack.setdefault("legal_versions", {})[name] = version
        applied.append(name)
    return applied


def activate(today: date) -> list[str]:
    path = ROOT / "legal_rulepack.json"
    pack = json.loads(path.read_text(encoding="utf-8"))
    entries = json.loads((ROOT / "reviewed_changes.json").read_text(encoding="utf-8"))
    from zoneinfo import ZoneInfo
    applied = []
    for entry in entries:
        # National effective dates use the country's calendar, not the
        # scheduler's Beijing date. Never activate several hours early.
        national_today = datetime.now(timezone.utc).astimezone(ZoneInfo(entry["effective_timezone"])).date()
        applied.extend(apply_reviewed_changes(pack, [entry], min(today, national_today)))
    if applied:
        from rulepack_manager import validate_rulepack
        # Activation is not a blanket new verification of every country.
        pack["rulepack_version"] = today.isoformat().replace("-", ".") + "-auto1"
        pack["automatic_activation"] = {"date": today.isoformat(), "reviewed_changes": applied}
        validate_rulepack(pack)
        write_json(path, pack)
    return applied


def check() -> dict:
    import knowledge_update as knowledge
    state = ROOT / "automation_state"
    state.mkdir(exist_ok=True)
    previous_path = state / "coverage_latest.json"
    try:
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        previous = {}
    now = datetime.now(BEIJING)
    full = not previous or previous.get("last_full_date") != now.date().isoformat() and now.hour >= 9
    selected = dict(knowledge.SOURCES)
    if not full:
        flagged = set(previous.get("changed", [])) | set(previous.get("unreachable", []))
        # Hourly shared baseline checks; whole-country coverage refreshed daily.
        selected = {name: urls for name, urls in selected.items() if name in flagged or not name.startswith("Country — ")}
    data = state / "runtime"
    os.environ["LOCALAPPDATA"] = str(data)
    os.environ["POLICY_AMADEUS_EVIDENCE_DIR"] = str(state / "evidence")
    with patch.dict(knowledge.SOURCES, selected, clear=True), patch("knowledge_update.update_from_manifest", return_value={"state": "cloud_source_run"}):
        knowledge.run_startup_check()
    raw = json.loads((data / "Policy Amadeus" / "knowledge_coverage_latest.json").read_text(encoding="utf-8"))
    if not full:
        for country, row in raw["countries"].items():
            if row["status"] == "not_verified" and country in previous.get("countries", {}):
                raw["countries"][country] = previous["countries"][country]
    raw["mode"] = "full" if full else "incremental"
    raw["last_full_date"] = now.date().isoformat() if full else previous.get("last_full_date")
    write_json(previous_path, raw)
    queue_path = state / "review_queue.json"
    try:
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        queue = {}
    for name in raw["changed"] + raw["unreachable"]:
        entry = queue.setdefault(name, {"first_seen": raw["checked_at"]})
        entry.update(last_seen=raw["checked_at"], status="pending_legal_review" if name in raw["changed"] else "retry_official_source",
                     observed_source_fingerprints=raw.get("observed_source_fingerprints", {}).get(name, {}))
    for country, row in raw["countries"].items():
        name = f"Country — {country}"
        if row["status"] == "baseline_requires_review" and name not in queue:
            queue[name] = {"first_seen": raw["checked_at"], "last_seen": raw["checked_at"],
                           "status": "pending_initial_baseline_review",
                           "observed_source_fingerprints": raw.get("observed_source_fingerprints", {}).get(name, {})}
    # Close only findings whose observed document digests match explicit
    # approvals in the signed rules. Other legal questions remain pending.
    pack = knowledge.load_rulepack()
    for name, entry in queue.items():
        observed = raw.get("observed_source_fingerprints", {}).get(name, {})
        approved = pack.get("reviewed_source_fingerprints", {}).get(name, {})
        if name in raw.get("reviewed_resolutions", []):
            entry.update(status="resolved_by_reviewed_rulepack", resolved_at=raw["checked_at"],
                         rulepack_version=pack["rulepack_version"])
    write_json(queue_path, queue)
    audit = {"checked_at": raw["checked_at"], "mode": raw["mode"],
             "changed": raw["changed"], "unreachable": raw["unreachable"],
             "country_count": len(raw["countries"]), "full_national_legal_review_completed": False}
    with (state / "runs.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(audit, ensure_ascii=False) + "\n")
    return audit


def release_needed() -> bool:
    paths = ["legal_rulepack.json", "app_version.json", "policy_generator.py", "policy_validator.py",
             "policy_studio.py", "policy_entry.py", "app_updater.py", "knowledge_update.py",
             "rulepack_manager.py", "update_storage.py", "official_document.py", "deepseek_client.py", "policy_ai_assist.py", "apply_app_update.ps1", "register_update_tasks.ps1", "tk_runtime_hook.py"]
    digest = hashlib.sha256()
    for name in paths:
        digest.update(name.encode())
        digest.update((ROOT / name).read_bytes())
    path = ROOT / "automation_state" / "published_input_hash.txt"
    current = digest.hexdigest()
    needed = not path.exists() or path.read_text().strip() != current
    # Marker written only after a successful publish by --mark-published.
    os.environ["POLICY_PUBLISH_INPUT_HASH"] = current
    return needed


def prepare_release() -> str:
    """Give every published binary a monotonically increasing version."""
    from rulepack_manager import version_key
    import re
    path = ROOT / 'app_version.json'
    current = json.loads(path.read_text(encoding='utf-8'))['version']
    manifest_path = ROOT / 'app_manifest.json'
    if not manifest_path.exists():
        return current
    published = json.loads(manifest_path.read_text(encoding='utf-8'))['version']
    if version_key(current) > version_key(published):
        return current
    daily = datetime.now(BEIJING).strftime('%Y.%m.%d') + '-1'
    if version_key(daily) > version_key(published):
        version = daily
    else:
        match = re.fullmatch(r'(\d{4}\.\d{2}\.\d{2}-)(\d+)', published)
        if not match:
            raise ValueError('Cannot safely increment published application version')
        version = match[1] + str(int(match[2]) + 1)
    write_json(path, {'version': version})
    return version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check", "activate", "release-needed", "prepare-release", "mark-published"])
    args = parser.parse_args()
    if args.command == "check":
        print(json.dumps(check(), ensure_ascii=False))
    elif args.command == "activate":
        print(json.dumps(activate(datetime.now(BEIJING).date()), ensure_ascii=False))
    elif args.command == "release-needed":
        print("true" if release_needed() else "false")
    elif args.command == "prepare-release":
        print(prepare_release())
    else:
        release_needed()
        path = ROOT / "automation_state" / "published_input_hash.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text(os.environ["POLICY_PUBLISH_INPUT_HASH"], encoding="utf-8")


if __name__ == "__main__":
    main()
