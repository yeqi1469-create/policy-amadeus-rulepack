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
    for country,overlay in data.get('country_overlays',{}).items():
        for field in ('statutory_withdrawal_days','refund_deadline_days'):
            if field in overlay and (type(overlay[field]) is not int or not 1<=overlay[field]<=365):
                raise RulepackError(f'{country} 的 {field} 国家参数无效')
        if 'refund_deadline_unit' in overlay and overlay['refund_deadline_unit'] not in {'calendar days','business days'}:
            raise RulepackError(f'{country} 的退款单位无效')
        if 'repair_remedy_liability_extension_months' in overlay and (
                type(overlay['repair_remedy_liability_extension_months']) is not int or not 0<=overlay['repair_remedy_liability_extension_months']<=120):
            raise RulepackError(f'{country} 的修理延长期无效')
        if 'objective_conformity_includes_repairability' in overlay and type(overlay['objective_conformity_includes_repairability']) is not bool:
            raise RulepackError(f'{country} 的可修理性国家参数无效')
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




def re_full_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def version_key(value: str) -> tuple[object, ...]:
    import re
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.findall(r"\d+|[A-Za-z]+", value))
