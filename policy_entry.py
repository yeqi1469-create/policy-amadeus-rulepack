"""Start background updates without importing the desktop UI."""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def main() -> None:
    if "--runtime-audit" in sys.argv:
        try:
            from packaged_runtime_audit import run
            run()
        except Exception:
            if os.environ.get("POLICY_AMADEUS_PACKAGED_AUDIT") != "1":
                raise
            audit_folder = Path(os.environ["LOCALAPPDATA"])/"Policy Amadeus"
            audit_folder.mkdir(parents=True, exist_ok=True)
            (audit_folder/"audit_entry_failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return
    if "--review-health" in sys.argv:
        from codex_review_worker import locate_git, locate_codex, _repository_session, signed_repository_base, folder, failure_details
        from update_storage import write_json
        result = {"git_found": False, "codex_found": False, "publisher_auth_and_signature": False}
        try:
            result["git_found"] = Path(locate_git()).is_file()
            result["codex_found"] = locate_codex().is_file()
            _, _, pack = signed_repository_base(_repository_session())
            result.update(publisher_auth_and_signature=True, rulepack_version=pack["rulepack_version"])
            import subprocess
            import codex_handoff
            probe = subprocess.run([str(locate_codex()), "queue", "--help"], capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            result["event_queue_supported"] = probe.returncode == 0 and "--thread" in probe.stdout
            result["event_handoff_configured"] = codex_handoff.settings().get("dispatch_mode") == "codex_queue"
        except Exception as exc:
            result.update(failure_details(exc))
        write_json(folder()/"codex_review_health.json", result)
        return
    if "--auto-review" in sys.argv:
        from codex_review_worker import run
        run(retry_now="--retry-now" in sys.argv)
        return
    if "--auto-update" not in sys.argv:
        from app_updater import start_app_update_check, start_schedule_registration, installed_version
        if sys.platform=='win32' and getattr(sys,'frozen',False):
            recovered='--startup-update-recovery' in sys.argv
            applied=False
            if '--startup-update-applied' in sys.argv:
                index=sys.argv.index('--startup-update-applied')
                applied=index+1<len(sys.argv) and sys.argv[index+1]==installed_version()
            if os.environ.get('POLICY_AMADEUS_STARTUP_AUDIT')=='1' and applied:
                from update_storage import write_json
                from codex_review_worker import folder
                write_json(folder()/'startup_relaunch_probe.json',{'auto_relaunched':True,'app_version':installed_version()})
                return
            if not applied and not recovered:
                from startup_update import run_before_ui
                if run_before_ui()!='continue':
                    return
        from policy_studio import PolicyStudio

        start_schedule_registration()
        if not (sys.platform=='win32' and getattr(sys,'frozen',False)):
            start_app_update_check()
        PolicyStudio().mainloop()
        return

    folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Policy Amadeus"
    folder.mkdir(parents=True, exist_ok=True)
    # Windows releases the byte-range lock even when the process crashes.
    with (folder / "auto_update.lock").open("a+b") as lock:
        lock.seek(0)
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return
        try:
            # Lock before reading/writing: another process's byte-range lock
            # also denies reads, so probing the first byte can raise EACCES.
            # Windows permits locking a byte beyond EOF on a new empty file.
            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b"0")
                lock.flush()
            from app_updater import run_auto_update
            run_auto_update()
        except Exception:
            report = {"checked_at": datetime.now().astimezone().isoformat(),
                      "state": "failed", "traceback": traceback.format_exc()}
            from update_storage import write_json
            write_json(folder / "auto_update_error.json", report)
        finally:
            if sys.platform == "win32":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == "__main__":
    main()
