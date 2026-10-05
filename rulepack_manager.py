from __future__ import annotations

import hashlib
import json
import os
import tempfile
import base64
import shutil
from datetime import date
from pathlib import Path
from typing import Any


class RulepackError(RuntimeError):
    pass


def _bundled_path() -> Path:
    import sys
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "legal_rulepack.json"


def _channel_config() -> dict[str, str]:
    import sys
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    path = base / "update_channel.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {
        "manifest_url": os.environ.get("POLICY_AMADEUS_RULEPACK_MANIFEST", "").strip()
        or str(data.get("manifest_url", "")).strip(),
        "app_manifest_url": os.environ.get("POLICY_AMADEUS_APP_MANIFEST", "").strip()
        or str(data.get("app_manifest_url", "")).strip(),
        "publisher_public_key": os.environ.get("POLICY_AMADEUS_RULEPACK_PUBLIC_KEY", "").strip()
        or str(data.get("publisher_public_key", "")).strip(),
    }


def configured_manifest_url() -> str:
    return _channel_config()["manifest_url"]


def _data_dir() -> Path:
    path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Policy Amadeus"
    path.mkdir(parents=True, exist_ok=True)
    return path


def active_rulepack_path() -> Path:
    downloaded = _data_dir() / "legal_rulepack.json"
    bundled = _bundled_path()
    if not downloaded.exists():
        return bundled
    try:
        local = json.loads(downloaded.read_text(encoding="utf-8"))
        shipped = json.loads(bundled.read_text(encoding="utf-8"))
        if version_key(str(shipped["rulepack_version"])) > version_key(str(local["rulepack_version"])):
            return bundled
    except (OSError, ValueError, KeyError):
        # Retain normal validation errors for corrupt downloaded data.
        pass
    return downloaded


def validate_rulepack(data: dict[str, Any]) -> None:
    required = ("schema_version", "rulepack_version", "verified_on", "review_due", "coverage_groups", "official_sources")
    missing = [key for key in required if key not in data]
    if missing:
        raise RulepackError("规则包缺少字段：" + "、".join(missing))
    if data["schema_version"] != 1:
        raise RulepackError("规则包架构版本不受支持")
    try:
        review_due = date.fromisoformat(str(data["review_due"]))
    except ValueError as exc:
        raise RulepackError("规则包复核日期无效") from exc
    if date.today() > review_due:
        raise RulepackError(f"规则包已超过复核期限 {review_due.isoformat()}")
    for group, rules in data["coverage_groups"].items():
        withdrawal = rules.get("statutory_withdrawal_days")
        if withdrawal is not None and (not isinstance(withdrawal, int) or withdrawal <= 0 or withdrawal > 365):
            raise RulepackError(f"{group} 的 statutory_withdrawal_days 无效")
        for key in ("refund_deadline_days", "commercial_return_days"):
            value = rules.get(key)
            if not isinstance(value, int) or value <= 0 or value > 365:
                raise RulepackError(f"{group} 的 {key} 无效")
        if rules.get("refund_deadline_unit") not in {"calendar days", "business days"}:
            raise RulepackError(f"{group} 的 refund_deadline_unit 无效")
        if rules.get("return_shipping_mode") not in {"customer_change_of_mind", "free_designated_carrier"}:
            raise RulepackError(f"{group} 的 return_shipping_mode 无效")
        if not isinstance(rules.get("restocking_fee"), bool):
            raise RulepackError(f"{group} 的 restocking_fee 无效")
    for source_group, urls in data["official_sources"].items():
        if not isinstance(urls, list) or not urls or any(not str(url).lower().startswith("https://") for url in urls):
            raise RulepackError(f"{source_group} 的官方来源无效")
    for source, endpoints in data.get("reviewed_source_fingerprints", {}).items():
        if not isinstance(endpoints, dict) or any(not str(url).startswith("https://") or not re_full_sha256(str(digest)) for url, digest in endpoints.items()):
            raise RulepackError(f"{source} 的已复核来源指纹无效")


def load_rulepack() -> dict[str, Any]:
    try:
        data = json.loads(active_rulepack_path().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RulepackError(f"无法读取政策规则包：{exc}") from exc
    validate_rulepack(data)
    return data


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_from_manifest(manifest_url: str) -> dict[str, str]:
    """Install a verified JSON rulepack from an HTTPS manifest.

    Manifest fields: rulepack_version, download_url, sha256. The endpoint must
    be controlled by the publisher; official law pages are evidence sources,
    not executable update packages.
    """
    if not manifest_url:
        return {"state": "not_configured", "message": "规则包自动更新通道未配置"}
    if not manifest_url.lower().startswith("https://"):
        raise RulepackError("规则包更新地址必须使用 HTTPS")
    import requests

    response = requests.get(manifest_url, timeout=10)
    response.raise_for_status()
    manifest = response.json()
    download_url = str(manifest.get("download_url", ""))
    expected = str(manifest.get("sha256", "")).lower()
    public_key_b64 = _channel_config()["publisher_public_key"]
    signature_b64 = str(manifest.get("signature", "")).strip()
    if not public_key_b64:
        raise RulepackError("未配置规则包发布者公钥，禁止自动安装远程规则包")
    signed_payload = json.dumps(
        {key: manifest.get(key) for key in ("rulepack_version", "download_url", "sha256")},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64)).verify(
            base64.b64decode(signature_b64), signed_payload
        )
    except Exception as exc:
        raise RulepackError("规则包更新清单数字签名验证失败") from exc
    if not download_url.lower().startswith("https://") or not re_full_sha256(expected):
        raise RulepackError("更新清单中的下载地址或SHA-256无效")
    current = load_rulepack()
    if version_key(str(manifest.get("rulepack_version", ""))) <= version_key(str(current["rulepack_version"])):
        return {"state": "current", "message": f"规则包已是最新版本 {current['rulepack_version']}"}
    payload = requests.get(download_url, timeout=20)
    payload.raise_for_status()
    if hashlib.sha256(payload.content).hexdigest() != expected:
        raise RulepackError("下载规则包的SHA-256校验失败")
    candidate = json.loads(payload.content.decode("utf-8"))
    validate_rulepack(candidate)
    if str(candidate["rulepack_version"]) != str(manifest["rulepack_version"]):
        raise RulepackError("更新清单与规则包版本不一致")
    target = _data_dir() / "legal_rulepack.json"
    backup = _data_dir() / "legal_rulepack.backup.json"
    fd, temp_name = tempfile.mkstemp(prefix="rulepack-", suffix=".json", dir=_data_dir())
    replaced = False
    had_target = target.exists()
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload.content)
            stream.flush()
            os.fsync(stream.fileno())
        if had_target:
            # Keep the active file available until the atomic replacement.
            shutil.copyfile(target, backup)
        Path(temp_name).replace(target)
        replaced = True
        load_rulepack()
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        if replaced:
            if had_target and backup.exists():
                backup.replace(target)
            elif not had_target:
                target.unlink(missing_ok=True)
        raise
    return {"state": "updated", "message": f"政策规则包已自动更新到 {candidate['rulepack_version']}"}


def re_full_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def version_key(value: str) -> tuple[object, ...]:
    import re
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.findall(r"\d+|[A-Za-z]+", value))
