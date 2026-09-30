from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from rulepack_manager import _channel_config, version_key


TASK_NAME = "Policy Amadeus Auto Update"
MAX_EXE_BYTES = 150 * 1024 * 1024


def _resource(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def _data_dir() -> Path:
    target = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Policy Amadeus"
    target.mkdir(parents=True, exist_ok=True)
    return target


def installed_version() -> str:
    return str(json.loads(_resource("app_version.json").read_text(encoding="utf-8"))["version"])


def _signed_fields(version: str, download_url: str, sha256: str) -> bytes:
    return json.dumps(
        {"download_url": download_url, "sha256": sha256, "version": version},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _verify_manifest(manifest: dict[str, object], public_key_b64: str) -> tuple[str, str, str]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    version = str(manifest.get("version", ""))
    download_url = str(manifest.get("download_url", ""))
    digest = str(manifest.get("sha256", "")).lower()
    if not version or not download_url.startswith("https://"):
        raise RuntimeError("程序更新清单缺少有效版本或 HTTPS 下载地址")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise RuntimeError("程序更新清单 SHA-256 无效")
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        signature = base64.b64decode(str(manifest.get("signature", "")), validate=True)
        key.verify(signature, _signed_fields(version, download_url, digest))
    except Exception as exc:
        raise RuntimeError("程序更新清单数字签名验证失败") from exc
    return version, download_url, digest


def _download_verified(url: str, expected_hash: str) -> Path:
    import requests

    fd, name = tempfile.mkstemp(prefix="policy-amadeus-", suffix=".exe", dir=_data_dir())
    staged = Path(name)
    try:
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "wb") as stream, requests.get(url, stream=True, timeout=(15, 90)) as response:
            response.raise_for_status()
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_EXE_BYTES:
                    raise RuntimeError("程序更新包超过大小上限")
                digest.update(chunk)
                stream.write(chunk)
        with staged.open("rb") as stream:
            magic = stream.read(2)
        if size < 1024 * 1024 or digest.hexdigest() != expected_hash or magic != b"MZ":
            raise RuntimeError("程序更新包校验失败")
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def _record(result: dict[str, object]) -> dict[str, object]:
    from update_storage import write_json
    result = {"checked_at": datetime.now().astimezone().isoformat(), **result}
    write_json(_data_dir() / "auto_update_status.json", result)
    return result


def _already_staged(version: str, digest: str) -> bool:
    try:
        pending = json.loads((_data_dir() / "pending_app_update.json").read_text(encoding="utf-8"))
        age = datetime.now().timestamp() - float(pending["created_at"])
        return (pending["version"] == version and pending["sha256"] == digest
                and 0 <= age < 12 * 3600 and Path(pending["staged"]).is_file()
                and _helper_alive(int(pending.get("helper_pid", 0))))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _helper_alive(pid: int) -> bool:
    if pid <= 0 or sys.platform != 'win32':
        return False
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def _stage_app_update() -> dict[str, object]:
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return {"app": "source_run", "version": installed_version()}
    config = _channel_config()
    manifest_url = str(config.get("app_manifest_url", ""))
    if not manifest_url.startswith("https://"):
        return {"app": "channel_not_configured", "version": installed_version()}
    if not config["publisher_public_key"]:
        raise RuntimeError("程序更新发布者公钥未配置")
    import requests

    response = requests.get(manifest_url, timeout=(15, 30))
    if response.status_code == 404:
        return {"app": "no_published_release", "version": installed_version()}
    response.raise_for_status()
    version, download_url, digest = _verify_manifest(response.json(), config["publisher_public_key"])
    if version_key(version) <= version_key(installed_version()):
        return {"app": "current", "version": installed_version()}
    if _already_staged(version, digest):
        return {"app": "waiting_for_app_exit", "installed_version": installed_version(), "new_version": version}
    staged = _download_verified(download_url, digest)
    helper = _data_dir() / "apply_app_update.ps1"
    shutil.copyfile(_resource("apply_app_update.ps1"), helper)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    installer_log = _data_dir() / 'app_install_helper.log'
    try:
        with installer_log.open('ab') as log:
            process = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-File", str(helper), "-ParentPid", str(os.getpid()),
                 "-Target", str(Path(sys.executable).resolve()), "-Staged", str(staged),
                 "-ExpectedHash", digest, "-StatusFile", str(_data_dir() / "app_install_status.json")],
                creationflags=flags, stdout=log, stderr=subprocess.STDOUT,
            )
        try:
            exit_code = process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            exit_code = None
        if exit_code is not None:
            raise RuntimeError(f'自动安装助手提前退出（代码 {exit_code}）；详情已保存到 app_install_helper.log')
        from update_storage import write_json
        write_json(_data_dir() / "pending_app_update.json", {"version": version, "sha256": digest,
                   "staged": str(staged), "created_at": datetime.now().timestamp(), "helper_pid": process.pid})
    except Exception:
        staged.unlink(missing_ok=True)
        raise
    return {"app": "installation_staged", "installed_version": installed_version(), "new_version": version}


def run_auto_update() -> dict[str, object]:
    result: dict[str, object] = {}
    # Fetch the small signed release first. Slow government sites must not
    # postpone checking whether a corrected application is already published.
    try:
        result.update(_stage_app_update())
    except Exception as exc:
        result.update({"app": "failed", "app_error": str(exc)})
    try:
        from knowledge_update import run_startup_check

        now = datetime.now().astimezone()
        try:
            coverage = json.loads((_data_dir() / "knowledge_coverage_latest.json").read_text(encoding="utf-8"))
            last_full = datetime.fromisoformat(coverage["last_full_checked_at"]).astimezone()
            incremental = last_full.date() == now.date() or now.hour < 9 and (now - last_full).total_seconds() < 86400
        except (OSError, ValueError, KeyError):
            incremental = False
        result["knowledge"] = run_startup_check(incremental=incremental)
    except Exception as exc:
        result["knowledge"] = {"state": "failed", "message": str(exc)}
    return _record(result)


def ensure_daily_task() -> None:
    """Register a per-user 09:00 Windows task once for an installed EXE."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        executable = str(Path(sys.executable).resolve())
        created = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(_resource("register_update_tasks.ps1")), "-Executable", executable],
            capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=25,
        )
        if created.returncode != 0:
            _record({"scheduler": "failed", "error": created.stderr.decode(errors="replace")})
    except Exception as exc:
        _record({"scheduler": "failed", "error": str(exc)})


def start_schedule_registration() -> None:
    threading.Thread(target=ensure_daily_task, daemon=True).start()


def start_app_update_check() -> None:
    """Catch an update when the computer was off at the scheduled hour."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return

    def check() -> None:
        try:
            result = _stage_app_update()
        except Exception as exc:
            result = {"app": "failed", "app_error": str(exc)}
        from update_storage import write_json
        write_json(_data_dir() / "app_update_launch_status.json", {"checked_at": datetime.now().astimezone().isoformat(), **result})

    threading.Thread(target=check, daemon=True).start()
