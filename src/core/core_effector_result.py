"""Core-owned interpretation of terminal EffectorResult; Delamain remains technical."""

from typing import Mapping

from src.core.effector_port import EffectorStatus


def interpret_result(result):
    """Вернуть смысловой payload из EffectorResult или отчёта драйвера.

    Входные словари копируются; интерпретатор не записывает память и не
    меняет цели. Конверт ``EffectorDriver._report`` разворачивается здесь,
    чтобы у Core была одна точка нормализации результата.
    """
    if result is None:
        return None
    if isinstance(result, Mapping):
        if result.get("result") is not None:
            return interpret_result(result["result"])
        if result.get("status") is None:
            return None
        raw_status = result.get("status")
        status = raw_status.value if hasattr(raw_status, "value") else str(raw_status)
        detail = dict(result.get("detail") or {})
        request_id = result.get("request_id")
        ok = result.get("ok")
        error = result.get("error")
    else:
        raw_status = result.status
        status = raw_status.value if hasattr(raw_status, "value") else str(raw_status)
        detail = dict(result.detail or {})
        request_id = result.request_id
        ok = result.ok
        error = result.error
    if status not in {item.value for item in EffectorStatus}:
        raise ValueError("Неизвестный статус эффектора")
    metadata = dict(detail.get("metadata") or {})
    return {
        "request_id": request_id,
        "status": status,
        "terminal": status in {"succeeded", "failed", "rejected"},
        "ok": bool(ok),
        "intention_id": metadata.get("intention_id"),
        "target": metadata.get("target"),
        "core_cycle": metadata.get("core_cycle"),
        "activity": metadata.get("activity"),
        "error": error,
        "detail": detail,
    }
