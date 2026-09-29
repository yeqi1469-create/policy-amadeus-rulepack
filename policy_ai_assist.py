from __future__ import annotations

import json
import os
from typing import Any


def audit_policies(policies: list[tuple[str, str]], settings: dict[str, object]) -> dict[str, object]:
    """Optional read-only AI audit.

    AI may identify wording or consistency risks, but its response is never
    written back into a policy and never changes statutory rulepack values.
    Configuration is opt-in through environment variables so customer and
    licence data is not sent to a third party without deliberate setup.
    """
    endpoint = os.environ.get("POLICY_AMADEUS_AI_AUDIT_URL", "").strip()
    api_key = os.environ.get("POLICY_AMADEUS_AI_AUDIT_KEY", "").strip()
    model = os.environ.get("POLICY_AMADEUS_AI_AUDIT_MODEL", "").strip()
    if not endpoint or not api_key or not model:
        return {
            "ai_audit_status": "未启用（本地规则和一致性检查不受影响）",
            "ai_audit_findings": [],
        }
    if not endpoint.lower().startswith("https://"):
        return {"ai_audit_status": "配置错误：AI审阅地址必须使用HTTPS", "ai_audit_findings": []}

    hard_rules = {
        key: settings.get(key) for key in (
            "country", "statutory_withdrawal", "refund_time", "return_window",
            "return_shipping_cost", "restocking_fee", "legal_guarantee",
        )
    }
    documents = "\n\n---DOCUMENT---\n\n".join(body for _title, body in policies)
    prompt = (
        "You are a read-only ecommerce policy quality reviewer. Identify omissions, ambiguous wording, "
        "internal contradictions and language-quality problems. Do not propose or change statutory periods. "
        "Treat HARD_RULES as immutable. Return JSON only: {\"findings\":[{\"severity\":\"warning\","
        "\"message\":\"...\"}]}.\nHARD_RULES=" + json.dumps(hard_rules, ensure_ascii=False) + "\nPOLICIES=\n" + documents
    )
    try:
        import requests
        response = requests.post(
            endpoint,
            timeout=45,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        findings = result.get("findings", [])
        if not isinstance(findings, list):
            raise ValueError("findings is not a list")
        safe_findings: list[str] = []
        for item in findings[:20]:
            if isinstance(item, dict) and item.get("message"):
                safe_findings.append(f"{item.get('severity', 'warning')}: {item['message']}")
        return {"ai_audit_status": "已完成只读辅助审阅", "ai_audit_findings": safe_findings}
    except Exception as exc:
        return {"ai_audit_status": f"AI辅助审阅失败（不影响本地硬性校验）：{exc}", "ai_audit_findings": []}
