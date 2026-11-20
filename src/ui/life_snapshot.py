"""Единый read-only снимок жизни для оболочки версии 1.0.

Зачем отдельно от ``src/app/status.py``: ``build_status_snapshot`` — плоская
панель цифр для существующего окна. Здесь нужен DTO, из которого собираются
карточки «Сейчас», объяснение выбора, намерения и доступы. Это слой
представления, а не второй источник истины: все поля читаются из Core.

Функция чистая: не меняет агента, не создаёт ленивые атрибуты
(``_intention_history``, ``_waiting_intentions``, ``_method_preferences``
появляются только при первой записи), не пишет на диск и не ждёт сеть.

Честность данных:

* ``preferences`` — накопленная статистика способов, а не эмоции;
* ``motivation.needs`` — уровни потребностей, а не «желания личности»;
* ``activities`` — то, что Core реально создал, а не любой файл профиля;
* ``access`` — текущее состояние переключателей, а не политика на будущее;
* ``effector`` — счётчики по статусам; ``queued`` здесь не значит «сделано».
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Dict, List, Optional

# Сколько последних попыток и ожиданий показывать в снимке.
RECENT_INTENTIONS = 20
RECENT_EPISODES = 20

_LIFE_STATE_LABELS = {
    "alive": "жив",
    "dormant": "спит",
    "terminated": "ушёл",
    "unknown": "неизвестно",
}


def _own(agent: Any, name: str, default: Any) -> Any:
    """Прочитать атрибут без создания ленивого поля.

    ``getattr(obj, name, default)`` сам по себе безопасен, но для полей,
    которые Core создаёт в момент первой записи (они появляются в
    ``__dict__``), нужна отдельная проверка: если поля нет, возвращаем
    ``default`` и ничего не создаём.
    """
    return getattr(agent, name, default)


def _status_of(component: Any) -> Dict[str, Any]:
    """Вызвать ``status()``/``get_status()``, если он есть и не падает.

    Ошибка подсистемы не должна ломать весь снимок: окно должно
    показать остальное, а не пустой экран.
    """
    for method in ("status", "get_status"):
        callback = getattr(component, method, None)
        if callable(callback):
            try:
                result = callback()
            except Exception:  # pragma: no cover - защита UI
                return {}
            return deepcopy(result) if isinstance(result, dict) else {}
    return {}


def _current_intention(history: List[Dict]) -> Optional[Dict]:
    """Последнее начатое и ещё не завершённое намерение."""
    for entry in reversed(history):
        if entry.get("status") == "started":
            return deepcopy(entry)
    return None


def _last_finished(history: List[Dict]) -> Optional[Dict]:
    for entry in reversed(history):
        if entry.get("status") != "started":
            return deepcopy(entry)
    return None


def _access_section(agent: Any) -> Dict[str, Any]:
    """Текущие доступы. Не описываем то, чего у Core нет."""
    from src.app.access_control import LABELS, current_state

    states = current_state(agent)
    delamain_subsystem = _own(agent, "delamain", None)
    workspace = getattr(delamain_subsystem, "workspace", None)
    section: Dict[str, Any] = {
        key: {"enabled": states[key], "label": LABELS[key]}
        for key in ("network", "delamain", "effector", "presence")
    }
    section["workspace"] = {
        "path": str(workspace) if workspace else "—",
        "label": "Творческая рабочая область",
    }
    return section


def _effector_section(agent: Any) -> Dict[str, Any]:
    """Счётчики Effector по статусам.

    Ключ ``counts`` берётся из ``status()``: там есть и ``queued``,
    и ``waiting_approval``. UI обязан показывать их отдельно от
    ``succeeded``, иначе ожидание будет выглядеть выполненной работой.
    """
    effector = _own(agent, "delamain_effector", None)
    status = _status_of(effector)
    counts = status.get("counts") if isinstance(status.get("counts"), dict) else {}
    return {
        "available": effector is not None,
        "counts": {key: int(value) for key, value in counts.items()},
        "last_error": status.get("last_error"),
    }


def _activity_section(agent: Any) -> Dict[str, Any]:
    """Только собственные работы Core: черновики, рисунки, мелодии и партии."""
    drafts: List[Dict] = []
    list_drafts = getattr(agent, "list_creative_drafts", None)
    if callable(list_drafts):
        try:
            drafts = [deepcopy(item) for item in list_drafts()]
        except Exception:  # pragma: no cover - защита UI
            drafts = []
    art: List[Dict] = []
    list_art = getattr(agent, "list_art_works", None)
    if callable(list_art):
        try:
            art = [deepcopy(item) for item in list_art()]
        except Exception:  # pragma: no cover - защита UI
            art = []
    music: List[Dict] = []
    list_music = getattr(agent, "list_music_works", None)
    if callable(list_music):
        try:
            music = [deepcopy(item) for item in list_music()]
        except Exception:  # pragma: no cover - защита UI
            music = []
    return {
        "creative": {"count": len(drafts), "drafts": drafts},
        "art": {"count": len(art), "works": art},
        "music": {"count": len(music), "works": music},
        "game": deepcopy(_own(agent, "_local_play", None)),
        "guess_game": deepcopy(_own(agent, "_local_guess", None)),
    }


def _proposal_section(agent: Any) -> Dict[str, Any]:
    """Ожидающие решения и действующие per-life настройки, только для чтения."""
    section: Dict[str, Any] = {
        "pending": [],
        "effective_overrides": deepcopy(
            _own(agent, "_safe_config_overrides", {}) or {}
        ),
    }
    proposals = _own(agent, "architecture_proposal", None)
    list_pending = getattr(proposals, "list_pending", None)
    if not callable(list_pending):
        return section
    try:
        records = list_pending()
    except Exception:  # pragma: no cover - защита UI
        return section
    fields = (
        "id",
        "type",
        "title",
        "description",
        "category",
        "attr",
        "old",
        "new",
        "verification",
    )
    section["pending"] = [
        {key: deepcopy(record.get(key)) for key in fields}
        for record in records
        if isinstance(record, dict) and record.get("id")
    ]
    return section


def _tutor_section(agent: Any) -> Dict[str, Any]:
    """Безопасный DTO наставника: ни эталонов, ни сети, ни изменений Core."""
    tutor = _own(agent, "language_tutor", None)
    status = _status_of(tutor)
    approved = _own(tutor, "approved_sources", [])
    requests = _own(tutor, "source_requests", [])
    approved = approved if isinstance(approved, list) else []
    requests = requests if isinstance(requests, list) else []
    current = status.get("pending_exercise")
    current = current if isinstance(current, dict) else None
    searcher = _own(agent, "web_searcher", None)
    return {
        "available": tutor is not None,
        "web_enabled": bool(getattr(searcher, "is_enabled", False)),
        "approved_sources": deepcopy(approved),
        "source_requests": deepcopy(requests),
        "approved_count": len(approved),
        "request_count": len(requests),
        "materials": int(status.get("materials", 0) or 0),
        "lessons": int(status.get("lessons", 0) or 0),
        "source_verified": int(status.get("source_verified", 0) or 0),
        "pending_exercise": (
            {
                key: deepcopy(current.get(key))
                for key in ("prompt", "kind", "lesson_id", "exercise_id")
            }
            if current is not None
            else None
        ),
    }


def _english_tutor_section(agent: Any) -> Dict[str, Any]:
    """Безопасный EN DTO без эталонов, excerpt и изменений Core."""
    tutor = _own(agent, "english_language_tutor", None)
    status = _status_of(tutor)
    approved = _own(tutor, "approved_sources", [])
    requests = _own(tutor, "source_requests", [])
    approved = approved if isinstance(approved, list) else []
    requests = requests if isinstance(requests, list) else []
    current = status.get("pending_exercise")
    current = current if isinstance(current, dict) else None
    searcher = _own(agent, "web_searcher", None)
    return {
        "available": tutor is not None,
        "web_enabled": bool(getattr(searcher, "is_enabled", False)),
        "approved_sources": deepcopy(approved),
        "source_requests": deepcopy(requests),
        "approved_count": len(approved),
        "request_count": len(requests),
        "materials": int(status.get("materials", 0) or 0),
        "rule_packs": int(status.get("rule_packs", 0) or 0),
        "source_verified": int(status.get("source_verified", 0) or 0),
        "pending_exercise": (
            {
                key: deepcopy(current.get(key))
                for key in (
                    "prompt",
                    "kind",
                    "pack_id",
                    "exercise_id",
                    "rule_id",
                )
            }
            if current is not None
            else None
        ),
    }


def _dialogue_section(agent: Any) -> Dict[str, Any]:
    """Последняя языковая диагностика без текста памяти и содержимого evidence."""
    section: Dict[str, Any] = {
        "available": False,
        "input_language": None,
        "dialogue_language": None,
        "response_language": None,
        "language_source": None,
        "act": None,
        "rule_id": None,
        "fallback_policy": None,
        "reference_count": 0,
        "references_verified": False,
        "profile_id": None,
    }
    experience = _own(agent, "response_experience", None)
    responses = _own(experience, "responses", {})
    response_id = _own(experience, "latest_response_id", None)
    if not isinstance(responses, dict) or response_id not in responses:
        return section
    record = responses[response_id]
    plan = record.get("plan") if isinstance(record, dict) else None
    if not isinstance(plan, dict):
        return section
    language = plan.get("language_context")
    language = language if isinstance(language, dict) else {}
    realization = plan.get("realization")
    realization = realization if isinstance(realization, dict) else {}
    references = plan.get("references")
    references = references if isinstance(references, list) else []
    state = plan.get("state")
    state = state if isinstance(state, dict) else {}
    section.update(
        {
            "available": True,
            "input_language": deepcopy(language.get("input_language")),
            "dialogue_language": deepcopy(language.get("dialogue_language")),
            "response_language": deepcopy(language.get("response_language")),
            "language_source": deepcopy(language.get("source")),
            "act": deepcopy(realization.get("act")),
            "rule_id": deepcopy(realization.get("rule_id")),
            "fallback_policy": deepcopy(realization.get("fallback_policy", "none")),
            "reference_count": len(references),
            "references_verified": plan.get("provenance_verified") is True,
            "profile_id": deepcopy(state.get("profile_id")),
        }
    )
    return section


def _external_contacts_section(agent: Any) -> Dict[str, Any]:
    """Ограниченный read-only журнал внешних сессий без чужой памяти."""
    manager = _own(agent, "external_contacts", None)
    registry = _own(agent, "social_registry", None)
    section: Dict[str, Any] = {
        "available": manager is not None,
        "can_manage": False,
        "active": 0,
        "messages": 0,
        "pending_drafts": 0,
        "journal_limit": 12,
        "sessions": [],
    }
    if manager is None:
        return section
    section["can_manage"] = bool(
        registry is not None
        and getattr(registry, "owner_profile_id", None) is not None
        and getattr(registry, "current_profile_id", None)
        == getattr(registry, "owner_profile_id", None)
    )
    status = _status_of(manager)
    for key in ("active", "messages", "pending_drafts"):
        try:
            section[key] = int(status.get(key, 0) or 0)
        except (TypeError, ValueError):
            section[key] = 0

    message_fields = (
        "message_id",
        "direction",
        "claim_type",
        "status",
        "text",
        "text_sha256",
        "cycle",
        "origin",
        "revision",
        "error",
        "response",
    )
    sessions = _own(manager, "sessions", [])
    if not isinstance(sessions, list):
        return section
    controllers = _own(agent, "_external_dialogue_controllers", {})
    controllers = controllers if isinstance(controllers, dict) else {}
    getter = getattr(manager, "get_session", None)
    if not callable(getter):
        return section
    for raw_session in sessions:
        if not isinstance(raw_session, dict) or not raw_session.get("session_id"):
            continue
        session_id = str(raw_session["session_id"])
        try:
            detail = getter(session_id)
        except Exception:  # pragma: no cover - защита UI
            continue
        if not isinstance(detail, dict):
            continue
        profile = None
        if registry is not None:
            try:
                profile = registry.get_profile(str(detail.get("profile_id", "")))
            except Exception:  # pragma: no cover - защита UI
                profile = None
        raw_messages = detail.get("messages")
        raw_messages = raw_messages if isinstance(raw_messages, list) else []
        messages = [
            {key: deepcopy(message.get(key)) for key in message_fields}
            for message in raw_messages[-section["journal_limit"] :]
            if isinstance(message, dict)
        ]
        pending = next(
            (
                deepcopy(message)
                for message in reversed(messages)
                if message.get("direction") == "outbound"
                and message.get("status") in {"draft", "approved"}
            ),
            None,
        )
        automation = {"state": "idle", "automatic_resume": False}
        controller = controllers.get(session_id)
        status_getter = getattr(controller, "get_status", None)
        if callable(status_getter):
            try:
                raw_automation = status_getter()
            except Exception:  # pragma: no cover - защита UI
                raw_automation = None
            if isinstance(raw_automation, dict):
                for key in (
                    "state",
                    "in_flight",
                    "replies_sent",
                    "max_replies",
                    "tokens_used",
                    "max_total_tokens",
                    "min_interval_sec",
                    "usage",
                    "tokens_estimated",
                    "billing_receipts",
                    "last_error",
                    "pause_reason",
                    "automatic_resume",
                ):
                    automation[key] = deepcopy(raw_automation.get(key))
        item = {
            key: deepcopy(detail.get(key))
            for key in (
                "session_id",
                "profile_id",
                "provider",
                "model",
                "external_id",
                "topic",
                "reason",
                "status",
                "created_cycle",
                "last_cycle",
                "stopped_cycle",
                "stop_reason",
                "metrics",
            )
        }
        item.update(
            {
                "display_name": str(
                    (profile or {}).get("display_name") or "Внешний ИИ"
                ),
                "message_count": len(raw_messages),
                "messages": messages,
                "pending_draft": pending,
                "automation": automation,
                "control_events": [
                    {
                        key: deepcopy(event.get(key))
                        for key in ("kind", "cycle", "reason")
                    }
                    for event in (detail.get("control_events") or [])[-12:]
                    if isinstance(event, dict)
                ],
            }
        )
        section["sessions"].append(item)
    return section


def _social_channels_section(agent: Any) -> Dict[str, Any]:
    """Ограниченный журнал и sanitized runtime-сессии без credentials."""
    manager = _own(agent, "social_channels", None)
    registry = _own(agent, "social_registry", None)
    section: Dict[str, Any] = {
        "available": manager is not None,
        "can_manage": False,
        "channel_count": 0,
        "active": 0,
        "active_sessions": 0,
        "messages": 0,
        "pending_drafts": 0,
        "sent": 0,
        "workers": 0,
        "automatic_resume": False,
        "journal_limit": 12,
        "channels": [],
    }
    controllers = _own(agent, "_social_session_controllers", {})
    controllers = controllers if isinstance(controllers, dict) else {}
    session_snapshots: Dict[str, Dict[str, Any]] = {}
    session_fields = (
        "session_id",
        "channel_id",
        "conversation_id",
        "grant_version",
        "state",
        "in_flight",
        "started_at",
        "deadline",
        "remaining_sec",
        "duration_sec",
        "poll_interval_sec",
        "initiative_after_sec",
        "received",
        "sent",
        "initiatives_sent",
        "last_error",
        "pause_reason",
        "automatic_resume",
    )
    for channel_id, controller in controllers.items():
        try:
            raw_session = controller.get_status()
        except Exception:  # pragma: no cover - защита UI
            continue
        if not isinstance(raw_session, dict):
            continue
        snapshot = {key: deepcopy(raw_session.get(key)) for key in session_fields}
        snapshot["automatic_resume"] = False
        session_snapshots[str(channel_id)] = snapshot
        state = snapshot.get("state")
        if state in {"running", "pausing", "stopping", "paused", "manual"}:
            section["active_sessions"] += 1
        if state in {"running", "pausing", "stopping"}:
            section["workers"] += 1
    if manager is None:
        return section
    section["can_manage"] = bool(
        registry is not None
        and getattr(registry, "owner_profile_id", None) is not None
        and getattr(registry, "current_profile_id", None)
        == getattr(registry, "owner_profile_id", None)
    )
    status = _status_of(manager)
    for key in ("active", "messages", "pending_drafts", "sent"):
        try:
            section[key] = int(status.get(key, 0) or 0)
        except (TypeError, ValueError):
            section[key] = 0
    try:
        section["channel_count"] = int(status.get("channels", 0) or 0)
    except (TypeError, ValueError):
        section["channel_count"] = 0
    getter = getattr(manager, "get_channel", None)
    raw_channels = _own(manager, "channels", [])
    if not callable(getter) or not isinstance(raw_channels, list):
        return section
    message_fields = (
        "message_id",
        "direction",
        "claim_type",
        "status",
        "text",
        "text_sha256",
        "cycle",
        "conversation_id",
        "author_id",
        "profile_id",
        "visibility",
        "external_message_id",
        "based_on",
        "in_reply_to",
        "origin",
        "revision",
        "grant_version",
        "error",
    )
    for raw_channel in raw_channels:
        if not isinstance(raw_channel, dict) or not raw_channel.get("channel_id"):
            continue
        try:
            detail = getter(str(raw_channel["channel_id"]))
        except Exception:  # pragma: no cover - защита UI
            continue
        if not isinstance(detail, dict):
            continue
        channel_id = str(raw_channel["channel_id"])
        raw_messages = detail.get("messages")
        raw_messages = raw_messages if isinstance(raw_messages, list) else []
        item = {
            key: deepcopy(detail.get(key))
            for key in (
                "channel_id",
                "provider",
                "account_id",
                "default_author_kind",
                "status",
                "created_cycle",
                "last_cycle",
                "stopped_cycle",
                "stop_reason",
                "grant",
                "received_count",
                "sent_count",
                "last_sent_at",
                "pending_draft",
            )
        }
        item["session"] = session_snapshots.get(
            channel_id, {"state": "idle", "automatic_resume": False}
        )
        item["message_count"] = len(raw_messages)
        item["messages"] = [
            {key: deepcopy(message.get(key)) for key in message_fields}
            for message in raw_messages[-section["journal_limit"] :]
            if isinstance(message, dict)
        ]
        item["control_events"] = [
            {key: deepcopy(event.get(key)) for key in ("kind", "cycle", "reason")}
            for event in _own(manager, "control_events", [])
            if isinstance(event, dict)
            and event.get("channel_id") == raw_channel["channel_id"]
        ][-12:]
        section["channels"].append(item)
    return section


_HORMONE_NAMES = ("dopamine", "serotonin", "oxytocin", "cortisol", "prolactin")
_HORMONE_PROFILE_FIELDS = (
    "baseline",
    "sensitivity",
    "half_life_scale",
    "confidence",
    "sample_count",
    "source_sample_counts",
)
_HORMONE_REASON_FIELDS = ("event", "source", "cycle", "reason", "action", "origin")
_HORMONAL_BEHAVIOR_CHANNELS = ("dopamine", "oxytocin", "cortisol")
_HORMONAL_BEHAVIOR_NUMBER_FIELDS = (
    "before_strength",
    "after_strength",
    "contribution",
)


def _hormonal_behavior_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _hormonal_behavior_code(value: Any) -> str:
    """Пропустить только короткий машинный код, не текст, путь или ошибку."""
    if not isinstance(value, str) or not 0 < len(value) <= 64:
        return "unknown"
    if not all(character.isalnum() or character in "_-." for character in value):
        return "unknown"
    return value


def _hormonal_behavior_section(agent: Any) -> Optional[Dict[str, Any]]:
    """Ограниченный DTO последнего тика; не является частью checkpoint."""
    runtime = _own(agent, "hormonal_behavior_last", None)
    if not isinstance(runtime, dict):
        return None
    raw_signals = runtime.get("signals")
    raw_evidence = runtime.get("evidence")
    raw_signals = raw_signals if isinstance(raw_signals, dict) else {}
    raw_evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
    raw_adjustments = runtime.get("adjustments")
    raw_adjustments = raw_adjustments if isinstance(raw_adjustments, list) else []
    adjustments = []
    for entry in raw_adjustments[-3:]:
        if not isinstance(entry, dict):
            continue
        input_index = entry.get("input_index")
        adjustments.append(
            {
                "input_index": (
                    input_index
                    if not isinstance(input_index, bool)
                    and isinstance(input_index, int)
                    and input_index >= 0
                    else None
                ),
                "action": _hormonal_behavior_code(entry.get("action")),
                "source": _hormonal_behavior_code(entry.get("source")),
                **{
                    field: _hormonal_behavior_number(entry.get(field))
                    for field in _HORMONAL_BEHAVIOR_NUMBER_FIELDS
                },
            }
        )
    return {
        "mode": _hormonal_behavior_code(runtime.get("mode")),
        "active": runtime.get("active") is True,
        "reason": _hormonal_behavior_code(runtime.get("reason")),
        "signals": {
            name: _hormonal_behavior_number(raw_signals.get(name))
            for name in _HORMONAL_BEHAVIOR_CHANNELS
        },
        "evidence": {
            name: _hormonal_behavior_number(raw_evidence.get(name))
            for name in _HORMONAL_BEHAVIOR_CHANNELS
        },
        "adjustments": adjustments,
    }


def _recovery_cycle_count(value: Any) -> int:
    return (
        value
        if not isinstance(value, bool) and isinstance(value, int) and value >= 0
        else 0
    )


def _hardware_recovery_behavior_section(agent: Any) -> Optional[Dict[str, Any]]:
    """Sanitized DTO последнего recovery-тика; не часть checkpoint."""
    runtime = _own(agent, "hardware_recovery_behavior_last", None)
    if not isinstance(runtime, dict):
        return None
    raw_adjustments = runtime.get("adjustments")
    raw_adjustments = raw_adjustments if isinstance(raw_adjustments, list) else []
    adjustments = []
    for entry in raw_adjustments[-3:]:
        if not isinstance(entry, dict):
            continue
        input_index = entry.get("input_index")
        adjustments.append(
            {
                "input_index": (
                    input_index
                    if not isinstance(input_index, bool)
                    and isinstance(input_index, int)
                    and input_index >= 0
                    else None
                ),
                "action": _hormonal_behavior_code(entry.get("action")),
                "source": _hormonal_behavior_code(entry.get("source")),
                "before_strength": _hormonal_behavior_number(
                    entry.get("before_strength")
                ),
                "after_strength": _hormonal_behavior_number(
                    entry.get("after_strength")
                ),
                "factor": _hormonal_behavior_number(entry.get("factor")),
            }
        )
    return {
        "mode": _hormonal_behavior_code(runtime.get("mode")),
        "active": runtime.get("active") is True,
        "eligible": runtime.get("eligible") is True,
        "reason": _hormonal_behavior_code(runtime.get("reason")),
        "strain_cycles": _recovery_cycle_count(runtime.get("strain_cycles")),
        "recovery_cycles": _recovery_cycle_count(runtime.get("recovery_cycles")),
        "max_recovery_risk": _hormonal_behavior_number(
            runtime.get("max_recovery_risk")
        ),
        "recovery": _hormonal_behavior_number(runtime.get("recovery")),
        "factor": _hormonal_behavior_number(runtime.get("factor")),
        "adjustments": adjustments,
    }


def _hardware_relevant_root_section(hardware: Dict[str, Any]) -> Dict[str, Any]:
    """Whitelisted per-root DTO без путей, устройств и полной истории эпизодов."""
    raw_roots = hardware.get("relevant_root_observations")
    if not isinstance(raw_roots, dict):
        return {}
    roots = {}
    for raw_id, raw in list(raw_roots.items())[:8]:
        root_id = _hormonal_behavior_code(raw_id)
        if root_id != raw_id or not isinstance(raw, dict):
            continue
        channel = raw.get("channel")
        channel = channel if isinstance(channel, dict) else {}
        trend = raw.get("trend")
        trend = trend if isinstance(trend, dict) else {}
        writes = raw.get("writes")
        writes = writes if isinstance(writes, dict) else {}
        latest_write = writes.get("latest")
        latest_write = latest_write if isinstance(latest_write, dict) else {}
        risk = raw.get("risk")
        risk = risk if isinstance(risk, dict) else {}
        experience = raw.get("experience")
        experience = experience if isinstance(experience, dict) else {}
        latest = experience.get("latest")
        latest = latest if isinstance(latest, dict) else {}
        episode = experience.get("current_episode")
        episode = episode if isinstance(episode, dict) else None
        baseline = experience.get("baseline")
        baseline = baseline if isinstance(baseline, dict) else {}
        episodes = experience.get("episodes")
        episode_count = len(episodes) if isinstance(episodes, list) else 0
        roots[root_id] = {
            "channel": {
                key: deepcopy(channel.get(key))
                for key in ("status", "value", "unit", "reason", "source")
                if key in channel
            },
            "trend": {
                key: deepcopy(trend.get(key))
                for key in (
                    "version",
                    "window_size",
                    "decline_cycles",
                    "drop",
                    "reason",
                )
                if key in trend
            },
            "writes": {
                "latest": {
                    key: deepcopy(latest_write.get(key))
                    for key in ("operation", "outcome", "category", "origin", "cycle")
                    if key in latest_write
                },
                "sample_count": _recovery_cycle_count(writes.get("sample_count")),
            },
            "risk": {
                key: deepcopy(risk.get(key))
                for key in (
                    "value",
                    "confidence",
                    "reason",
                    "origin",
                    "expectedness",
                    "evidence",
                )
                if key in risk
            },
            "experience": {
                "latest": {
                    key: deepcopy(latest.get(key))
                    for key in (
                        "risk",
                        "experienced",
                        "expectedness",
                        "freshness",
                        "reason",
                    )
                    if key in latest
                },
                "current_episode": (
                    {
                        key: deepcopy(episode.get(key))
                        for key in (
                            "start_cycle",
                            "strain_cycle",
                            "end_cycle",
                            "max_pressure",
                            "origin",
                            "evidence",
                            "slow_cycle",
                            "fresh_observations",
                            "fresh_high_cycles",
                            "recovery_duration_cycles",
                            "complete",
                        )
                        if key in episode
                    }
                    if episode is not None
                    else None
                ),
                "baseline": {
                    key: deepcopy(baseline.get(key))
                    for key in (
                        "baseline",
                        "deviation",
                        "sample_count",
                        "last_update_cycle",
                        "confidence",
                    )
                    if key in baseline
                },
                "adaptation": _hormonal_behavior_number(experience.get("adaptation")),
                "confidence": _hormonal_behavior_number(experience.get("confidence")),
                "episode_count": episode_count,
            },
        }
    return roots


def _hardware_action_experience_section(hardware: Dict[str, Any]) -> Optional[Dict]:
    """Только sanitized latest; profiles остаются в checkpoint, а не в UI."""
    raw = hardware.get("action_experience")
    if not isinstance(raw, dict) or not isinstance(raw.get("latest"), dict):
        return None
    latest = raw["latest"]
    action = latest.get("action")
    return {
        "latest": {
            "action": (_hormonal_behavior_code(action) if action is not None else None),
            "sample_count": _recovery_cycle_count(latest.get("sample_count")),
            "expectedness": _hormonal_behavior_code(latest.get("expectedness")),
            "freshness": _hormonal_behavior_code(latest.get("freshness")),
            "reason": _hormonal_behavior_code(latest.get("reason")),
            "risk": _hormonal_behavior_number(latest.get("risk")),
        }
    }


def _hardware_behavior_section(
    agent: Any, runtime_attribute: str
) -> Optional[Dict[str, Any]]:
    """Sanitized DTO последнего hardware-тика; не часть checkpoint."""
    runtime = _own(agent, runtime_attribute, None)
    if not isinstance(runtime, dict):
        return None
    raw_adjustments = runtime.get("adjustments")
    raw_adjustments = raw_adjustments if isinstance(raw_adjustments, list) else []
    adjustments = []
    for entry in raw_adjustments[-3:]:
        if not isinstance(entry, dict):
            continue
        input_index = entry.get("input_index")
        adjustments.append(
            {
                "input_index": (
                    input_index
                    if not isinstance(input_index, bool)
                    and isinstance(input_index, int)
                    and input_index >= 0
                    else None
                ),
                "action": _hormonal_behavior_code(entry.get("action")),
                "source": _hormonal_behavior_code(entry.get("source")),
                "before_strength": _hormonal_behavior_number(
                    entry.get("before_strength")
                ),
                "after_strength": _hormonal_behavior_number(
                    entry.get("after_strength")
                ),
                "factor": _hormonal_behavior_number(entry.get("factor")),
            }
        )
    return {
        "mode": _hormonal_behavior_code(runtime.get("mode")),
        "active": runtime.get("active") is True,
        "eligible": runtime.get("eligible") is True,
        "reason": _hormonal_behavior_code(runtime.get("reason")),
        "duration_cycles": _recovery_cycle_count(runtime.get("duration_cycles")),
        "risk": _hormonal_behavior_number(runtime.get("risk")),
        "experienced": _hormonal_behavior_number(runtime.get("experienced")),
        "confidence": _hormonal_behavior_number(runtime.get("confidence")),
        "factor": _hormonal_behavior_number(runtime.get("factor")),
        "adjustments": adjustments,
    }


def _conditional_write_behavior_section(agent: Any) -> Optional[Dict[str, Any]]:
    """Sanitized runtime DTO conditional-write advisor; не часть checkpoint."""
    runtime = _own(agent, "hardware_conditional_write_behavior_last", None)
    if not isinstance(runtime, dict):
        return None
    raw_evidence = runtime.get("write_evidence")
    raw_evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
    raw_adjustments = runtime.get("adjustments")
    raw_adjustments = raw_adjustments if isinstance(raw_adjustments, list) else []
    adjustments = []
    for entry in raw_adjustments[-3:]:
        if not isinstance(entry, dict):
            continue
        input_index = entry.get("input_index")
        adjustments.append(
            {
                "input_index": (
                    input_index
                    if not isinstance(input_index, bool)
                    and isinstance(input_index, int)
                    and input_index >= 0
                    else None
                ),
                "action": _hormonal_behavior_code(entry.get("action")),
                "source": _hormonal_behavior_code(entry.get("source")),
                "before_strength": _hormonal_behavior_number(
                    entry.get("before_strength")
                ),
                "after_strength": _hormonal_behavior_number(
                    entry.get("after_strength")
                ),
                "factor": _hormonal_behavior_number(entry.get("factor")),
            }
        )
    return {
        "mode": _hormonal_behavior_code(runtime.get("mode")),
        "active": runtime.get("active") is True,
        "eligible": runtime.get("eligible") is True,
        "reason": _hormonal_behavior_code(runtime.get("reason")),
        "profile_class": _hormonal_behavior_code(runtime.get("profile_class")),
        "write_evidence": {
            "sample_count": _recovery_cycle_count(raw_evidence.get("sample_count")),
            "write_count": _recovery_cycle_count(raw_evidence.get("write_count")),
            "failed_count": _recovery_cycle_count(raw_evidence.get("failed_count")),
            "write_ratio": _hormonal_behavior_number(raw_evidence.get("write_ratio")),
        },
        "risk": _hormonal_behavior_number(runtime.get("risk")),
        "experienced": _hormonal_behavior_number(runtime.get("experienced")),
        "confidence": _hormonal_behavior_number(runtime.get("confidence")),
        "factor": _hormonal_behavior_number(runtime.get("factor")),
        "adjustments": adjustments,
    }


def _hormonal_projection_section(agent: Any) -> Dict[str, Any]:
    """Компактная проекция checkpoint без истории, текста и обращения к ОС."""
    fallback = {
        "initialized": False,
        "mode": "shadow_interoception",
        "reason": "not_initialized",
    }
    system = _own(agent, "hormonal_system", None)
    callback = getattr(system, "to_checkpoint", None)
    if not callable(callback):
        return fallback
    try:
        checkpoint = callback()
    except Exception:  # pragma: no cover - защита UI
        return fallback
    if not isinstance(checkpoint, dict):
        return fallback
    raw_levels = checkpoint.get("hormones")
    raw_profile = checkpoint.get("profile")
    if not isinstance(raw_levels, dict) or not isinstance(raw_profile, dict):
        return fallback

    levels = {
        name: deepcopy(raw_levels[name])
        for name in _HORMONE_NAMES
        if name in raw_levels
    }
    profile: Dict[str, Any] = {}
    for name in _HORMONE_NAMES:
        values = raw_profile.get(name)
        if isinstance(values, dict):
            profile[name] = {
                field: deepcopy(values[field])
                for field in _HORMONE_PROFILE_FIELDS
                if field in values
            }

    recent_reasons = []
    episodes = checkpoint.get("episodes")
    if isinstance(episodes, list):
        for entry in episodes[-3:]:
            if not isinstance(entry, dict):
                continue
            reason = {
                field: deepcopy(entry[field])
                for field in _HORMONE_REASON_FIELDS
                if field in entry
            }
            if reason:
                recent_reasons.append(reason)
    return {
        "initialized": True,
        "mode": "shadow_interoception",
        "time_model": deepcopy(checkpoint.get("time_model")),
        "legacy_mixed_time": deepcopy(checkpoint.get("legacy_mixed_time")),
        "levels": levels,
        "profile": profile,
        "recent_reasons": recent_reasons,
        "behavior": _hormonal_behavior_section(agent),
    }


def build_life_snapshot(agent: Any, runner: Optional[Any] = None) -> Dict[str, Any]:
    """Собрать снимок жизни существа для интерфейса.

    Args:
        agent: ``DigitalBeing`` (или совместимый объект).
        runner: ``AgentRunner``; нужен только для режима скорости.

    Returns:
        Словарь с разделами ``life``, ``now``, ``motivation``, ``intentions``,
        ``activities``, ``preferences``, ``goals``, ``access``, ``effector``.
        Отсутствующие данные — пустые значения, но ключи на месте.
    """
    history: List[Dict] = list(_own(agent, "_intention_history", []) or [])
    waiting_all: Dict[str, Dict] = _own(agent, "_waiting_intentions", None) or {}
    # Ожидание без решения — то, что ещё «висит»; решённые не считаются активными.
    waiting_entries = [
        deepcopy(entry)
        for entry in waiting_all.values()
        if isinstance(entry, dict) and not entry.get("resolution")
    ]
    waiting_entries = waiting_entries[-RECENT_INTENTIONS:]
    # Забытое не удаляется из опыта: показываем отдельным списком, чтобы
    # карта могла приглушить узел, а не сделать вид, что его не было.
    forgotten_entries = [
        deepcopy(entry)
        for entry in waiting_all.values()
        if isinstance(entry, dict)
        and isinstance(entry.get("resolution"), dict)
        and entry["resolution"].get("kind") == "forgotten"
    ][-RECENT_INTENTIONS:]

    interoception = _status_of(_own(agent, "interoception", None))
    hardware = _status_of(_own(agent, "hardware_interoception", None))
    if hardware:
        hardware["initialized"] = True
        hardware["episode_count"] = len(hardware.pop("episodes", []))
        domains = hardware.get("domain_experience") or {}
        if isinstance(domains, dict):
            for domain in domains.values():
                if isinstance(domain, dict):
                    domain["episode_count"] = len(domain.pop("episodes", []))
        hardware["recent_events"] = list(hardware.get("recent_events") or [])[-10:]
        if "relevant_root_observations" in hardware:
            hardware["relevant_root_observations"] = _hardware_relevant_root_section(
                hardware
            )
    else:
        hardware = {
            "mode": "shadow",
            "initialized": False,
            "reason": "not_initialized",
        }
    hardware["action_experience"] = _hardware_action_experience_section(hardware)
    hardware["recovery_behavior"] = _hardware_recovery_behavior_section(agent)
    hardware["physical_behavior"] = _hardware_behavior_section(
        agent, "hardware_physical_behavior_last"
    )
    hardware["storage_behavior"] = _hardware_behavior_section(
        agent, "hardware_storage_behavior_last"
    )
    hardware["conditional_write_behavior"] = _conditional_write_behavior_section(agent)
    life_guard = _own(agent, "life_guard", None)
    guard_details: Dict[str, Any] = {}
    if life_guard is not None:
        try:
            guard_details = dict(life_guard.state_details())
        except Exception:  # pragma: no cover - защита UI
            guard_details = {}
    life_state = str(guard_details.get("state", "unknown"))

    goals_view: Dict[str, Any] = {}
    goals_status = getattr(agent, "get_goals_status", None)
    if callable(goals_status):
        try:
            view = goals_status()
            goals_view = dict(view) if isinstance(view, dict) else {}
        except Exception:  # pragma: no cover - защита UI
            goals_view = {}

    speed: Dict[str, Any] = {}
    if runner is not None:
        try:
            speed = dict(runner.get_speed_status())
        except Exception:  # pragma: no cover - защита UI
            speed = {}

    preferences = {
        action: deepcopy(entry)
        for action, entry in (_own(agent, "_method_preferences", None) or {}).items()
        if isinstance(entry, dict)
    }

    current = _current_intention(history)
    diary_episodes = _combined_diary(agent, history, RECENT_EPISODES)
    return {
        "name": str(getattr(agent, "name", "?")),
        "life": {
            "cycle": int(getattr(agent, "cycle_count", 0) or 0),
            "energy": float(getattr(agent, "energy", 0.0) or 0.0),
            "state": life_state,
            "state_label": _LIFE_STATE_LABELS.get(life_state, life_state),
            "fatigue": interoception.get("fatigue"),
            "fatigue_level": interoception.get("fatigue_level"),
            "needs_rest": interoception.get("needs_rest"),
            "seed_folder": guard_details.get("seed_folder"),
            "speed_mode": speed.get("mode"),
            "speed_interval_sec": speed.get("interval_sec"),
            "paused": speed.get("paused"),
        },
        "now": {
            "activity": current,
            "goal": deepcopy(_own(agent, "active_goal", None)),
            "loop": _status_of(_own(agent, "loop_closer", None)),
        },
        "motivation": _status_of(_own(agent, "motivation_system", None)),
        "emotions": _status_of(_own(agent, "emotional_state", None)),
        "body": interoception,
        "hardware": hardware,
        "hormonal_projection": _hormonal_projection_section(agent),
        "intentions": {
            "active": current,
            "waiting": waiting_entries,
            "forgotten": forgotten_entries,
            "recent": deepcopy(history[-RECENT_INTENTIONS:]),
            "last_finished": _last_finished(history),
        },
        "activities": _activity_section(agent),
        "diary": {"episodes": diary_episodes, "count": len(diary_episodes)},
        "preferences": preferences,
        "goals": goals_view,
        "proposals": _proposal_section(agent),
        "access": _access_section(agent),
        "effector": _effector_section(agent),
        "tutor": _tutor_section(agent),
        "english_tutor": _english_tutor_section(agent),
        "dialogue": _dialogue_section(agent),
        "external_contacts": _external_contacts_section(agent),
        "social_channels": _social_channels_section(agent),
    }


def build_diary_snapshot(agent: Any, limit: int = 500) -> Dict[str, Any]:
    """Расширенный кэш дневника для веб-пагинации.

    Использует тот же сборщик, что и Tk, но не уменьшает окно Tk с 20 записей.
    HTTP-слой получает уже готовый список и не обращается к SQLite сам.
    """
    history: List[Dict] = list(_own(agent, "_intention_history", []) or [])
    episodes = _combined_diary(agent, history, limit)
    return {
        "episodes": episodes,
        "count": len(episodes),
        "cache_limit": max(0, int(limit)),
    }


def _combined_diary(
    agent: Any, history: List[Dict], limit: int
) -> List[Dict[str, Any]]:
    diary_episodes = recent_life_episodes(agent, limit)
    recorded_ids = {
        str(item.get("task_id"))
        for item in diary_episodes
        if isinstance(item, dict) and item.get("task_id")
    }
    # Автономные занятия принадлежат Core даже без подключённого Delamain.
    # Незавершённое намерение не выдаётся за событие дневника.
    for entry in reversed(history):
        if (
            not isinstance(entry, dict)
            or entry.get("status") == "started"
            or str(entry.get("id")) in recorded_ids
        ):
            continue
        outcome = entry.get("outcome")
        diary_episodes.append(
            {
                "id": f"core:{entry.get('id')}",
                "ts": entry.get("cycle"),
                "task_id": entry.get("id"),
                "task": "digital_life",
                "action": entry.get("action"),
                "args": {"target": entry.get("target")},
                "ok": entry.get("status") == "performed",
                "output": deepcopy(outcome),
                "error": (outcome or {}).get("error")
                if isinstance(outcome, dict)
                else None,
                "metadata": {"status": entry.get("status"), "source": "core_history"},
            }
        )
    return diary_episodes[: max(0, int(limit))]


def recent_life_episodes(
    agent: Any, limit: int = RECENT_EPISODES
) -> List[Dict[str, Any]]:
    """Прочитать автобиографические эпизоды Core из SQLite Delamain.

    Только чтение. Если Delamain не подключён, возвращаем пустой список:
    у UI нет собственного хранилища истории.
    """
    memory = getattr(
        getattr(_own(agent, "delamain", None), "runtime", None), "memory", None
    )
    reader = getattr(memory, "recent_life_episodes", None)
    if not callable(reader):
        return []
    try:
        bounded_limit = max(0, min(int(limit), 500))
        episodes = [
            deepcopy(dict(row))
            for row in reader(
                life_id=str(getattr(agent, "life_id", getattr(agent, "name", "?"))),
                limit=bounded_limit,
            )
        ]
        legacy_reader = getattr(memory, "legacy_life_episodes", None)
        if callable(legacy_reader):
            identifiers = [
                entry["id"]
                for entry in (_own(agent, "_intention_history", []) or [])
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            ]
            episodes.extend(
                deepcopy(legacy_reader(intention_ids=identifiers, limit=bounded_limit))
            )
        episodes.sort(key=lambda item: int(item.get("id", 0)), reverse=True)
        return episodes[:bounded_limit]
    except Exception:  # pragma: no cover - защита UI
        return []
