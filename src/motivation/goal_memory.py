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


def _goal_subject(title):
    """Точно нормализованный предмет цели, без нечёткого совпадения тем."""
    text = str(title or "")
    if ":" not in text:
        return ""
    from src.memory.knowledge_quality import normalize_concept_name

    return normalize_concept_name(text.split(":", 1)[1].strip())


def _goal_action(goal):
    origin = goal.get("motivation_origin")
    if not isinstance(origin, dict):
        origin = goal
    return str(origin.get("action_hint") or "").strip()


def capture_goal_evidence(agent, title):
    """Снять только доказанные данные по точному предмету цели.

    Гипотезы, сам факт встречи и глобальный рост счётчиков мира не являются
    новым основанием для повтора. Прямая запись в KB учитывается отдельно от
    наблюдений и сообщений в ментальной модели.
    """
    subject = _goal_subject(title)
    if not subject:
        return None

    from src.cognition.mental_models import EVIDENCE_MIN
    from src.memory.knowledge_quality import normalize_concept_name

    evidence_count = 0
    concepts = getattr(getattr(agent, "mental_models", None), "concepts", {})
    if isinstance(concepts, dict):
        for name, node in concepts.items():
            if normalize_concept_name(str(name)) != subject:
                continue
            experiences = getattr(node, "experiences", [])
            if not isinstance(experiences, (list, tuple)):
                continue
            for experience in experiences:
                if not isinstance(experience, dict):
                    continue
                if experience.get("evidence_kind") not in {
                    "observation",
                    "testimony",
                    "innate",
                }:
                    continue
                if not str(experience.get("source") or "").strip():
                    continue
                try:
                    strength = float(experience.get("evidence_strength", 0.0))
                except (TypeError, ValueError):
                    continue
                if isfinite(strength) and strength >= EVIDENCE_MIN:
                    evidence_count += 1

    knowledge_present = False
    knowledge_base = getattr(agent, "knowledge_base", {})
    if isinstance(knowledge_base, dict):
        knowledge_present = any(
            normalize_concept_name(str(name)) == subject
            and value is not None
            and bool(str(value).strip())
            for name, value in knowledge_base.items()
        )
    return {
        "subject": subject,
        "evidence_count": evidence_count,
        "knowledge_present": knowledge_present,
    }


def record_goal_evidence_at_outcome(agent, goal):
    """Сохранить на терминальной цели основание для будущего сравнения."""
    signature = capture_goal_evidence(agent, goal.get("title"))
    if signature is not None:
        goal["evidence_at_outcome"] = signature


def prefer_alternative_goal_templates(agent, templates, subject):
    """Не выбирать снова способ, который уже провалился на этом предмете."""
    from src.core.agent_act import classify_decision, executable_action
    from src.memory.knowledge_quality import normalize_concept_name

    normalized_subject = normalize_concept_name(str(subject or ""))
    failed_actions = {
        classify_decision(_goal_action(goal))
        for goal in getattr(agent, "goals", []) or []
        if isinstance(goal, dict)
        and goal.get("status") == "failed"
        and _goal_subject(goal.get("title")) == normalized_subject
        and _goal_action(goal)
    }
    if not failed_actions:
        return list(templates)
    alternatives = [
        template
        for template in templates
        if executable_action(template.get("action"))
        and classify_decision(template.get("action")) not in failed_actions
    ]
    return alternatives or list(templates)


def _evidence_retry_reason(previous, current):
    before = previous.get("evidence_at_outcome")
    if not isinstance(before, dict) or before.get("subject") != current["subject"]:
        return ""
    changes = []
    before_count = before.get("evidence_count")
    if isinstance(before_count, int) and not isinstance(before_count, bool):
        current_count = current["evidence_count"]
        if current_count > before_count:
            changes.append(
                f"подтверждённых свидетельств: {before_count} → {current_count}"
            )
    if current["knowledge_present"] and not before.get("knowledge_present", False):
        changes.append("появилась прямая запись в базе знаний")
    if not changes:
        return ""
    return (
        f"После исхода цели по теме «{current['subject']}» получены новые данные: "
        + "; ".join(changes)
    )


def _set_retry_reason(candidate, previous, reason):
    candidate["retry_reason"] = reason
    if previous.get("id") is not None:
        candidate["retry_of"] = previous["id"]


def prepare_automatic_goal_retry(agent, candidate):
    """Добавить причину только из записанной смены стратегии или новых данных."""
    if (
        not isinstance(candidate, dict)
        or str(candidate.get("retry_reason") or "").strip()
    ):
        return candidate

    from src.cognition.activity_goals import goal_work_key
    from src.core.agent_act import classify_decision, executable_action

    title = str(candidate.get("title") or "").strip()
    if not title:
        return candidate
    normalized_title = _normalize_goal_text(title)
    subject = _goal_subject(title)
    work_key = goal_work_key(candidate)
    terminal = [
        goal
        for goal in getattr(agent, "goals", []) or []
        if isinstance(goal, dict) and goal.get("status") in _REPEAT_CLOSED_STATUSES
    ]

    # Если этот же способ уже завершился, более ранняя неудача другого способа
    # не должна реанимировать его и запускать «пинг-понг» проваленных стратегий.
    previous = next(
        (goal for goal in reversed(terminal) if goal_work_key(goal) == work_key),
        None,
    )
    same_work = previous is not None
    if previous is None:
        previous = next(
            (
                goal
                for goal in reversed(terminal)
                if _normalize_goal_text(goal.get("title")) == normalized_title
                or (subject and _goal_subject(goal.get("title")) == subject)
            ),
            None,
        )
    if previous is None:
        return candidate

    current_evidence = capture_goal_evidence(agent, title)
    if current_evidence is not None:
        reason = _evidence_retry_reason(previous, current_evidence)
        if reason:
            _set_retry_reason(candidate, previous, reason)
            return candidate

    previous_action = _goal_action(previous)
    candidate_action = _goal_action(candidate)
    if (
        not same_work
        and previous.get("status") == "failed"
        and previous_action
        and executable_action(candidate_action)
        and classify_decision(previous_action) != classify_decision(candidate_action)
    ):
        _set_retry_reason(
            candidate,
            previous,
            "После неудачи выбрана другая стратегия: "
            f"{previous_action} → {candidate_action}",
        )
    return candidate


def is_automatic_goal_repeat_blocked(agent, candidate):
    """Запретить автоматический дубль, но не осознанную новую попытку."""
    if not isinstance(candidate, dict):
        candidate = {"title": candidate}
    title = str(candidate.get("title") or "").strip()
    if not title:
        return True
    normalized_title = _normalize_goal_text(title)
    subject = _goal_subject(title)
    retry_reason = str(candidate.get("retry_reason") or "").strip()

    from src.cognition.activity_goals import goal_work_key

    work_key = goal_work_key(candidate)
    for goal in getattr(agent, "goals", []) or []:
        if not isinstance(goal, dict):
            continue
        same_title = _normalize_goal_text(goal.get("title")) == normalized_title
        same_work = goal_work_key(goal) == work_key
        closed = goal.get("status") in _REPEAT_CLOSED_STATUSES
        same_subject = bool(subject and _goal_subject(goal.get("title")) == subject)
        if closed:
            # Для завершённой работы другая формулировка или стратегия по той
            # же теме тоже требует основания; живые разные стратегии остаются
            # самостоятельными целями и друг друга не блокируют.
            if (same_title or same_work or same_subject) and not retry_reason:
                return True
        elif same_title or same_work:
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
    "capture_goal_evidence",
    "collect_pending_goal_origins",
    "count_goal",
    "empty_goal_summary",
    "format_goal_outcome",
    "goal_outcome_importance",
    "is_automatic_goal_repeat_blocked",
    "prefer_alternative_goal_templates",
    "prepare_automatic_goal_retry",
    "recall_goal_outcome",
    "record_goal_evidence_at_outcome",
    "restore_goal_summary",
]
