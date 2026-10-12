"""Display measured check progress without promising a precise deadline."""
import math
from datetime import datetime, timezone, timedelta


STAGES = {"preparing": (1, "检查授权与签名基线"), "fetching_evidence": (2, "获取法律正文"),
          "reviewing": (3, "审查法律与政策"), "verifying": (4, "独立复核结论"),
          "publishing": (5, "提交修复候选"), "awaiting_cloud_tests": (6, "等待测试和签名"),
          "installing": (7, "安装签名修复"), "rechecking": (8, "安装后复核")}


def age(value, now=None):
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, ((now or datetime.now(timezone.utc))-parsed).total_seconds())
    except (ValueError, TypeError):
        return None


def duration(seconds):
    if seconds is None:
        return "未知"
    seconds = int(max(0, seconds))
    return f"{seconds//60}分{seconds%60:02d}秒" if seconds >= 60 else f"{seconds}秒"


def handoff_label(update):
    handoff = update.get("handoff", {})
    state = handoff.get("state")
    if state == "processing":
        return "当前聊天已接手处理"
    if state == "awaiting_chat":
        return "修复请求已排入当前聊天，等待接手"
    if state == "queued":
        return "工单已保存；聊天发送失败，等恢复连接重试" if handoff.get("delivery_failed") else "工单已保存，准备按需发送当前聊天"
    if state == "write_failed":
        return "工单保存失败，尚未交接"
    if state == "idle":
        return "无未解决交接事项"
    if state == "not_configured":
        return "按需聊天接入尚未配置"
    return "等待自动重试"


def activity_caption(status, now=None):
    update = status.get("update_status")
    if not update:
        if status.get("state") == "checking":
            completed, total = status.get("completed_sources", 0), status.get("total_sources", 0)
            return f"官方来源已检查 {completed}/{total}；检查完成不等于法律核验完成" if total else "正在建立官方来源检查任务"
        return "检查结果可在更新详情中查看"
    if update.get("state") in ("retry_pending", "not_started", "more_reviews_pending"):
        return handoff_label(update)+"；尚未完成修复"
    elapsed = age(update.get("operation_started_at", update.get("checked_at")), now)
    last = age(update.get("last_model_output_at") or update.get("last_event_at", update.get("checked_at")), now)
    heartbeat = age(update.get("heartbeat_at", update.get("checked_at")), now)
    parts = ["本步骤已用 "+duration(elapsed), "最近事件 "+duration(last)+"前"]
    limit = update.get("operation_limit_seconds")
    if heartbeat is not None and heartbeat > 30:
        parts.append("后台信号失联，可能已卡住")
    elif limit and elapsed is not None and elapsed > limit:
        parts.append("超过等待阈值，可能卡住；进程在线不代表有进展")
    elif update.get("model_running"):
        parts.append("审查进程在线，等待输出")
    else:
        parts.append("后台在线" if heartbeat is not None else "后台信号尚未建立")
    return " · ".join(parts)


def check_progress(completed, total, elapsed):
    total = max(0, int(total))
    completed = min(total, max(0, int(completed)))
    return {"progress_percent": min(95, int(95 * completed / total)) if total else 95,
            "completed_sources": completed, "total_sources": total,
            "remaining_seconds": max(1, math.ceil(elapsed * (total - completed) / completed))
            if 0 < completed < total and elapsed > 0 else None}


def progress_caption(status):
    update = status.get("update_status")
    if update:
        percent = max(0, min(100, int(update.get("progress_percent", 0))))
        if update.get("state") in ("retry_pending", "not_started", "more_reviews_pending"):
            return "更新暂停 · 完成时间暂不可估算"
        remaining = update.get("remaining_seconds")
        eta = f"预计剩余约 {max(1, math.ceil(remaining/60))} 分钟（基于历史耗时）" if remaining else "预计剩余：正在估算"
        step, label = STAGES.get(update.get("stage", update.get("state")), (0, update.get("operation", "处理更新")))
        source = update.get("source_label") or str(update.get("source") or "").removeprefix("Country — ")
        scope = f" · {source}" if source else ""
        return f"步骤 {step}/8：{label}{scope} · 本项阶段 {percent}%\n{eta}"
    percent = max(0, min(100, int(status.get("progress_percent", 0))))
    if status.get("state") != "checking":
        return "检查完成 · 100%" if status.get("checked_at") else "等待检查 · 0%"
    remaining = status.get("remaining_seconds")
    if remaining is None:
        eta = "预计剩余：正在估算" if percent < 95 else "正在完成规则校验"
    elif remaining < 60:
        eta = f"预计剩余约 {max(1, math.ceil(remaining))} 秒"
    else:
        eta = f"预计剩余约 {math.ceil(remaining / 60)} 分钟"
    return f"{percent}% · {eta}"


def update_detail_text(status, events=(), requests=(), now=None):
    update = status.get("update_status", {})
    lines = [progress_caption(status), activity_caption(status, now), "",
             "当前操作："+str(update.get("operation", status.get("message", "等待检查"))),
             f"本轮处理位置：{update.get('source_index') or 0}/{update.get('source_total') or 0}",
             "说明：阶段百分比不是全部国家完成率；后台存活不等于有新结果。"]
    if update.get("endpoint"):
        lines.extend(("当前访问入口：", str(update["endpoint"])))
    if update.get("model_round"):
        lines.append(f"审查轮次：{update['model_round']}/2；单轮时限15分钟")
    if update.get("cloud_poll"):
        lines.append(f"签名发布检查：{update['cloud_poll']}/{update.get('cloud_poll_total',30)}次")
    if update.get("retry_at"):
        lines.append("后台重试最早时间："+str(update["retry_at"])+"（实际还受任务调度影响）")
    lines.extend(("", "逐国未解决原因："))
    for source, failure in update.get("source_errors", {}).items():
        lines.append(str(source)+"："+str(failure.get("reason", "原因尚未确认")))
    if not update.get("source_errors"):
        lines.append("暂无逐国失败记录；不表示所有国家已核验。")
    lines.extend(("", "当前聊天交接："+handoff_label(update)))
    for item in requests:
        if item.get("state") != "resolved":
            states = {"pending":"等待本聊天接手" if item.get("queue_accepted") else "尚未成功发送",
                      "processing":"当前聊天处理中", "awaiting_evidence":"调查已记录，待补足官方证据或分段复核", "resolved":"已复核解决"}
            lines.append(f"{item.get('source')}：{item.get('action') or item.get('reason')}；{states.get(item.get('state'),'状态待确认')}")
    lines.extend(("", "最近实际步骤（北京时间）："))
    for event in list(events)[-20:]:
        try:
            stamp = datetime.fromisoformat(event["checked_at"]).astimezone(timezone(timedelta(hours=8))).strftime("%H:%M:%S")
        except (KeyError, ValueError, TypeError):
            stamp = "时间未知"
        lines.append(f"{stamp}  {event.get('source') or ''}  {event.get('operation') or event.get('message') or ''}")
    return "\n".join(lines)
