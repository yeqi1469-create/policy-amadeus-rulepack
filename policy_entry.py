"""Start background updates without importing the desktop UI."""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def main() -> None:
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
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return
        try:
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
