"""Display measured check progress without promising a precise deadline."""
import math


def check_progress(completed, total, elapsed):
    total = max(0, int(total))
    completed = min(total, max(0, int(completed)))
    return {"progress_percent": min(95, int(95 * completed / total)) if total else 95,
            "completed_sources": completed, "total_sources": total,
            "remaining_seconds": max(1, math.ceil(elapsed * (total - completed) / completed))
            if 0 < completed < total and elapsed > 0 else None}


def progress_caption(status):
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
