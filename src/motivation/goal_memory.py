"""Общие правила ограниченной истории и накопленного опыта целей."""

from copy import deepcopy
from math import isfinite


GOAL_HISTORY_LIMIT = 50
GOAL_OUTCOMES = ("generated", "achieved", "failed", "cancelled")
TERMINAL_GOAL_STATUSES = frozenset({"achieved", "failed", "cancelled"})


def _empty_counters():
    return {outcome: 0 for outcome in GOAL_OUTCOMES}


def empty_goal_summary():
    return {
        **{outcome: 0 for outcome in GOAL_OUTCOMES},
        "by_need": {},
        "by_drive": {},
    }


def count_goal(summary, entry, outcome, *, needs, drives=None):
    """Учесть только известные потребности/драйвы, не создавая новых ключей."""
    if not isinstance(entry, dict):
        return
    summary[outcome] += 1
    need_name = entry.get("need")
    if need_name in needs:
        counters = summary["by_need"].setdefault(need_name, _empty_counters())
        counters[outcome] += 1
    drive_name = entry.get("drive") or entry.get("internal_drive")
    if drives is not None and drive_name in drives:
        counters = summary["by_drive"].setdefault(drive_name, _empty_counters())
        counters[outcome] += 1


def restore_goal_summary(saved, history, *, needs, drives=None):
    """Восстановить итоги; для старого чекпоинта доступна нижняя оценка."""
    summary = empty_goal_summary()
    for entry in history:
        count_goal(summary, entry, "generated", needs=needs, drives=drives)
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        if status in TERMINAL_GOAL_STATUSES:
            count_goal(summary, entry, status, needs=needs, drives=drives)
    if not isinstance(saved, dict):
        return summary

    for outcome in GOAL_OUTCOMES:
        value = saved.get(outcome)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            summary[outcome] = max(summary[outcome], value)
    for section, allowed in (("by_need", needs), ("by_drive", drives or {})):
        saved_counts = saved.get(section, {})
        if not isinstance(saved_counts, dict):
            continue
        for name, counters in saved_counts.items():
            if name not in allowed or not isinstance(counters, dict):
                continue
            target = summary[section].setdefault(name, _empty_counters())
            for outcome in GOAL_OUTCOMES:
                value = counters.get(outcome)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                ):
                    target[outcome] = max(target[outcome], value)
    return summary


def collect_pending_goal_origins(history, saved=None):
    """Связи живых целей не вытесняются вместе с autobiographical window."""
    pending = {}
    if isinstance(saved, dict):
        for goal_id, entry in saved.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("status") not in TERMINAL_GOAL_STATUSES:
                pending[str(goal_id)] = deepcopy(entry)
    for entry in history:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") in TERMINAL_GOAL_STATUSES:
            continue
        goal_id = entry.get("goal_id")
        if goal_id is not None:
            pending[str(goal_id)] = deepcopy(entry)
    return pending


def goal_outcome_importance(goal):
    """Оценить значимость завершённой цели без выдумывания её свойств."""
    significance = goal.get("significance")
    if (
        isinstance(significance, (int, float))
        and not isinstance(significance, bool)
        and isfinite(significance)
    ):
        return max(0.0, min(1.0, float(significance)))

    try:
        difficulty = float(goal.get("difficulty", 1))
    except (TypeError, ValueError):
        difficulty = 1.0
    if not isfinite(difficulty):
        difficulty = 1.0
    difficulty = max(1.0, min(5.0, difficulty))
    importance = 0.5 + 0.15 * difficulty

    priority = {"low": 0.3, "normal": 0.6, "high": 0.9}.get(
        str(goal.get("priority", "")).lower(), 0.0
    )
    return max(importance, priority)


_GOAL_OUTCOME_LABELS = {
    "completed": "Цель достигнута",
    "failed": "Цель не выполнена",
    "cancelled": "Цель отменена",
}
_REPEAT_CLOSED_STATUSES = frozenset(
    {"completed", "achieved", "failed", "cancelled", "duplicate"}
)


def _normalize_goal_text(value):
    return " ".join(str(value or "").split()).casefold()


def format_goal_outcome(goal, status):
    """Сформулировать только наблюдаемый исход и указанную причину."""
    title = str(goal.get("title") or "Без названия")[:240]
    content = f"{_GOAL_OUTCOME_LABELS[status]}: {title}"
    reason_field = {
        "failed": "failure_reason",
        "cancelled": "cancellation_reason",
    }.get(status)
    reason = str(goal.get(reason_field, "") or "").strip()[:240] if reason_field else ""
    return f"{content}. Причина: {reason}" if reason else content


def recall_goal_outcome(long_term_memory, title):
    """Найти исход только по точному названию, без нечёткого запрета."""
    if long_term_memory is None or not str(title or "").strip():
        return None
    try:
        memories = long_term_memory.recall(
            str(title).strip(), threshold=0.0, max_results=20
        )
    except Exception:
        return None
    reason_marker = _normalize_goal_text(". Причина:")
    for memory in memories or []:
        content = _normalize_goal_text(memory.get("content"))
        for status, label in _GOAL_OUTCOME_LABELS.items():
            prefix = _normalize_goal_text(f"{label}: {str(title).strip()[:240]}")
            if content == prefix or content.startswith(prefix + reason_marker):
                return status
    return None


def is_automatic_goal_repeat_blocked(agent, candidate):
    """Запретить автоматический дубль, но не осознанную новую попытку."""
    if not isinstance(candidate, dict):
        candidate = {"title": candidate}
    title = str(candidate.get("title") or "").strip()
    if not title:
        return True
    normalized_title = _normalize_goal_text(title)
    retry_reason = str(candidate.get("retry_reason") or "").strip()

    from src.cognition.activity_goals import goal_work_key

    work_key = goal_work_key(candidate)
    for goal in getattr(agent, "goals", []) or []:
        if not isinstance(goal, dict):
            continue
        same_title = _normalize_goal_text(goal.get("title")) == normalized_title
        if not same_title and goal_work_key(goal) != work_key:
            continue
        if goal.get("status") not in _REPEAT_CLOSED_STATUSES:
            return True
        if not retry_reason:
            return True

    if retry_reason:
        return False
    return (
        recall_goal_outcome(getattr(agent, "long_term_memory", None), title) is not None
    )


__all__ = [
    "GOAL_HISTORY_LIMIT",
    "GOAL_OUTCOMES",
    "TERMINAL_GOAL_STATUSES",
    "collect_pending_goal_origins",
    "count_goal",
    "empty_goal_summary",
    "format_goal_outcome",
    "goal_outcome_importance",
    "is_automatic_goal_repeat_blocked",
    "recall_goal_outcome",
    "restore_goal_summary",
]
