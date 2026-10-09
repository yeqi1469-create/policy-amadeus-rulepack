"""Start background updates without importing the desktop UI."""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def main() -> None:
    if "--review-health" in sys.argv:
        from codex_review_worker import locate_git, locate_codex, _repository_session, signed_repository_base, folder
        from update_storage import write_json
        result = {"git_found": False, "codex_found": False, "publisher_auth_and_signature": False}
        try:
            result["git_found"] = Path(locate_git()).is_file()
            result["codex_found"] = locate_codex().is_file()
            _, _, pack = signed_repository_base(_repository_session())
            result.update(publisher_auth_and_signature=True, rulepack_version=pack["rulepack_version"])
        except Exception as exc:
            result["failure_type"] = type(exc).__name__
        write_json(folder()/"codex_review_health.json", result)
        return
    if "--auto-review" in sys.argv:
        from codex_review_worker import run
        run()
        return
    if "--auto-update" not in sys.argv:
        from app_updater import start_app_update_check, start_schedule_registration
        from policy_studio import PolicyStudio

        start_schedule_registration()
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
