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
        "external_contacts": _external_contacts_section(agent),
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
