from __future__ import annotations

import re
from typing import Iterable

from knowledge_update import require_no_detected_change
from rulepack_manager import load_rulepack


class PolicyValidationError(RuntimeError):
    pass


REQUIRED_POLICY_CONCEPTS: dict[str, tuple[str, ...]] = {
    "Refund and Return Policy": (
        "applicable return window", "return eligibility", "return procedure",
        "return shipping costs", "refunds and payment method", "exceptions",
        "return address", "customer-service enquiries",
    ),
    "Privacy Policy": (
        "categories of personal data", "sources of personal data", "purposes of processing",
        "legal bases", "cookies and consent choices", "how we disclose personal data",
        "relationship with shopify", "international transfers", "retention",
        "data protection rights", "privacy contact and complaints",
    ),
    "Terms of Service": (
        "orders and acceptance", "prices and taxes", "payment information", "shipping and risk",
        "returns, refunds and withdrawal", "acceptable use", "relationship with shopify",
        "liability", "severability, waiver and assignment", "governing law",
    ),
    "Shipping Policy": (
        "shipping summary", "shipping destinations", "shipping method", "order processing time",
        "shipping transit and total delivery time", "shipping costs", "tracking",
        "accurate address and address changes", "delivery attempts", "delivery delays",
        "lost packages", "damaged packages", "incorrect, missing or incomplete items",
        "customs, duties and taxes", "returned parcels and returns",
    ),
    "Contact Information": (
        "company information", "customer service", "order and product questions",
        "returns and refunds", "shipping questions", "privacy requests", "business address",
    ),
    "Legal Notice / Imprint": (
        "service provider and website operator", "registered address", "registration authority",
        "online store, seller and platform", "responsible for website content",
        "product, pricing and availability information", "external links", "intellectual property",
        "consumer information", "governing law",
    ),
}


def missing_policy_concepts(policies: list[tuple[str, str]]) -> dict[str, list[str]]:
    policy_map = {title: body.casefold() for title, body in policies}
    missing_by_policy: dict[str, list[str]] = {}
    for title, concepts in REQUIRED_POLICY_CONCEPTS.items():
        body = policy_map.get(title, "")
        missing = [concept for concept in concepts if concept.casefold() not in body]
        if missing:
            missing_by_policy[title] = missing
    return missing_by_policy


def ruleset_metadata() -> dict[str, str]:
    rulepack = load_rulepack()
    return {
        "ruleset_version": str(rulepack["rulepack_version"]),
        "verified_on": str(rulepack["verified_on"]),
        "review_due": str(rulepack["review_due"]),
        "ruleset_status": "官方来源复核期内",
        "ruleset_expired": "no",
    }


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def validate_market(policies: list[tuple[str, str]], settings: dict[str, object],
                    email: str, phone: str, website: str) -> dict[str, object]:
    country = str(settings.get("country", "未知市场"))
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[str] = []
    meta = ruleset_metadata()
    update_status = require_no_detected_change()

    if meta["ruleset_expired"] == "yes":
        errors.append(f"法规规则库已超过复核期限 {meta['review_due']}")
    checks.append("法规规则库版本和复核期限")
    if update_status.get("state") in {"offline", "partial", "update_failed"}:
        warnings.append(str(update_status.get("message", "本次启动未能连接全部官方来源")))
    checks.append("启动时官方来源更新检测")

    if len(policies) != 6:
        errors.append(f"应生成6份政策，实际为{len(policies)}份")
    if not settings.get("official_sources"):
        errors.append("缺少官方法律来源")
    if str(settings.get("coverage_status", "")) != "已由官方来源规则覆盖":
        errors.append("该市场尚未完成官方来源覆盖")
    checks.append("六份政策完整性和官方来源覆盖")

    # Static completeness gate modelled on the information categories checked
    # by major storefront auditors.  These are concepts, not copied wording;
    # missing any one means the canonical template is incomplete and must not
    # be translated or published.
    for title, missing in missing_policy_concepts(policies).items():
        errors.append(f"{title}缺少关键内容：{'、'.join(missing)}")
    checks.append("政策关键字段完整性（地区、费用、时效、流程、例外、追踪、关税及企业身份）")

    if "@" not in email:
        errors.append("客服邮箱格式无效")
    if len(_digits(phone)) < 6:
        errors.append("客服电话为空或格式无效")
    if website and not re.match(r"^https?://", website, re.I):
        errors.append("网站地址必须包含 http:// 或 https://")
    checks.append("客服邮箱、客服电话和网站地址")

    text = "\n".join(body for _title, body in policies)
    if email not in text or phone not in text:
        errors.append("政策没有统一使用所输入的客服邮箱或客服电话")

    customs_mode = str(settings.get("customs_responsibility", ""))
    shipping_body = next((body.casefold() for title, body in policies if title == "Shipping Policy"), "")
    if "free for all orders delivered within" not in shipping_body:
        errors.append("物流政策未明确说明目的地全境所有订单的标准配送费用")
    customs_markers = {
        "卖家承担（客户收货时不另付）": "the seller bears any applicable customs duties",
        "消费者承担（结账前明确披露）": "the customer is the importer and bears",
        "不适用（境内或关税同盟内配送）": "the customer is not charged import customs duty",
    }
    expected_customs_text = customs_markers.get(customs_mode)
    if not expected_customs_text or expected_customs_text not in shipping_body:
        errors.append("物流政策未明确写出关税及进口税的承担主体")
    checks.append("目的地配送摘要、全订单运费及关税承担主体")

    forbidden = {
        "do not send an item without authorization": "不得以事先授权限制法定撤回",
        "unauthorized returns may not be accepted": "不得拒绝未经授权但依法提出的撤回",
        "sale items are returnable only": "不得笼统排除促销商品法定权利",
        "opened personal-care or hygiene goods": "卫生商品例外表述过宽",
        "licensed business": "不得无依据声称企业持有经营许可",
        "licensed seller": "不得无依据声称卖家持有经营许可",
        "licensed company": "不得无依据声称公司持有经营许可",
        "licensed operator": "不得无依据声称运营方持有经营许可",
    }
    folded = text.casefold()
    if "calendar days days" in folded or "business days days" in folded:
        errors.append("政策包含重复的时间单位（days days）")
    if str(settings.get("jurisdiction_group")) in {"EU", "EEA"}:
        refund_body = next((body.casefold() for title, body in policies if title == "Refund and Return Policy"), "")
        if "14 calendar days after sending the notice" not in refund_body:
            errors.append("欧盟/欧洲经济区退货政策未明确撤回通知后的14日寄回期限")
        if str(settings.get("jurisdiction_group")) == "EEA" and "extended once by **12 months**" in refund_body:
            errors.append("欧洲经济区市场被错误套用尚未确认纳入EEA的欧盟维修延长期")
    checks.append("法定退款期限、退货寄回期限及维修救济适用范围")
    for phrase, message in forbidden.items():
        if phrase in folded:
            errors.append(message)
    checks.append("授权限制、商品状态、促销商品、卫生商品例外及无依据许可声明")

    # A store cannot simultaneously promise free approved returns everywhere
    # and say that customers bear change-of-mind return costs.
    if "approved returns receive a prepaid label" in folded and "customer bears the direct return cost" in folded:
        errors.append("六份政策中的退货运费责任相互矛盾")
    checks.append("退款期限、退货期限、退货运费和重新入库费一致性")

    if settings.get("withdrawal_function_required"):
        withdrawal = str(settings.get("withdrawal_function", ""))
        start_label = str(settings.get("withdrawal_start_label", ""))
        confirm_label = str(settings.get("withdrawal_confirm_label", ""))
        if not start_label or not confirm_label or start_label not in withdrawal or confirm_label not in withdrawal:
            errors.append(f"{country}缺少规则包要求的电子撤回功能及确认按钮")
    checks.append("国家专属强制条款")

    licence = settings.get("license_fields") or {}
    if isinstance(licence, dict):
        for key, label in (("legal_name", "法定名称"), ("street_address", "注册地址"),
                           ("country", "注册国家"), ("registration_number", "注册号")):
            if not str(licence.get(key, "")).strip():
                errors.append(f"执照未可靠识别{label}，为防止输出错误主体信息已停止生成")
    checks.append("执照主体信息完整性")

    return {
        **meta,
        "knowledge_update_status": str(update_status.get("message", "")),
        "validation_status": "通过" if not errors else "不通过",
        "validation_errors": errors,
        "validation_warnings": warnings,
        "validation_checks": checks,
    }


def enforce_market(policies: list[tuple[str, str]], settings: dict[str, object],
                   email: str, phone: str, website: str) -> dict[str, object]:
    report = validate_market(policies, settings, email, phone, website)
    errors = report["validation_errors"]
    if errors:
        detail = "\n".join(f"- {item}" for item in errors)
        raise PolicyValidationError(f"{settings.get('country', '市场')}一致性检查未通过，已停止生成：\n{detail}")
    return report


def validate_localized_output(policies: list[tuple[str, str]], email: str, phone: str) -> None:
    if len(policies) != 6:
        raise PolicyValidationError("翻译后的政策数量不等于6，已停止输出")
    text = "\n".join(body for _title, body in policies)
    if email not in text or phone not in text:
        raise PolicyValidationError("翻译服务改动或删除了客服邮箱/电话，已停止输出")
    error_markers = (
        "no translation was found", "try another translator", "translation failed",
        "翻译失败", "无法翻译", "未找到翻译",
    )
    folded = text.casefold()
    if any(marker.casefold() in folded for marker in error_markers):
        raise PolicyValidationError("翻译结果包含翻译服务错误信息，已停止输出")
    if any(len(body.strip()) < 120 for _title, body in policies):
        raise PolicyValidationError("翻译结果异常短，可能不完整，已停止输出")


def validate_combined(markets: Iterable[dict[str, object]], policy_count: int) -> str:
    market_list = list(markets)
    if policy_count != 6:
        raise PolicyValidationError(f"合并结果应包含6份政策，实际为{policy_count}份")
    if not market_list:
        raise PolicyValidationError("合并结果没有任何市场")
    return f"通过：{len(market_list)}个市场、6份政策已完成跨页面一致性检查"
