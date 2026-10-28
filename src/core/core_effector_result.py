"""Core-owned interpretation of terminal EffectorResult; Delamain remains technical."""

from src.core.effector_port import EffectorStatus


def interpret_result(result):
    """Вернуть только смысловой payload; не записывает память и не меняет цели."""
    if result is None:
        return None
    status = result.status.value if hasattr(result.status, "value") else str(result.status)
    metadata = dict(result.detail.get("metadata") or {})
    if status not in {item.value for item in EffectorStatus}:
        raise ValueError("Неизвестный статус эффектора")
    return {
        "request_id": result.request_id,
        "status": status,
        "terminal": status in {"succeeded", "failed", "rejected"},
        "ok": bool(result.ok),
        "intention_id": metadata.get("intention_id"),
        "target": metadata.get("target"),
        "core_cycle": metadata.get("core_cycle"),
        "activity": metadata.get("activity"),
        "error": result.error,
        "detail": dict(result.detail),
    }
