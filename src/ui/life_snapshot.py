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
    network = getattr(getattr(agent, "web_searcher", None), "is_enabled", False)
    delamain = getattr(_own(agent, "delamain", None), "enabled", False)
    effector = getattr(_own(agent, "delamain_effector", None), "enabled", False)
    return {
        "network": {"enabled": bool(network), "label": "Интернет-поиск"},
        "delamain": {"enabled": bool(delamain), "label": "Delamain (эффектор)"},
        "effector": {"enabled": bool(effector), "label": "Выполнение действий"},
        "workspace": {"path": "profile/delamain/workspace/creative",
                      "label": "Творческая рабочая область"},
    }


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
    """Только собственные работы Core: черновики и партии."""
    drafts: List[Dict] = []
    list_drafts = getattr(agent, "list_creative_drafts", None)
    if callable(list_drafts):
        try:
            drafts = [deepcopy(item) for item in list_drafts()]
        except Exception:  # pragma: no cover - защита UI
            drafts = []
    return {
        "creative": {"count": len(drafts), "drafts": drafts},
        "game": deepcopy(_own(agent, "_local_play", None)),
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
    waiting_entries = [deepcopy(entry) for entry in waiting_all.values()
                       if isinstance(entry, dict) and not entry.get("resolution")]
    waiting_entries = waiting_entries[-RECENT_INTENTIONS:]
    # Забытое не удаляется из опыта: показываем отдельным списком, чтобы
    # карта могла приглушить узел, а не сделать вид, что его не было.
    forgotten_entries = [
        deepcopy(entry) for entry in waiting_all.values()
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
        "intentions": {
            "active": current,
            "waiting": waiting_entries,
            "forgotten": forgotten_entries,
            "recent": deepcopy(history[-RECENT_INTENTIONS:]),
            "last_finished": _last_finished(history),
        },
        "activities": _activity_section(agent),
        "preferences": preferences,
        "goals": goals_view,
        "access": _access_section(agent),
        "effector": _effector_section(agent),
    }


def recent_life_episodes(agent: Any, limit: int = RECENT_EPISODES) -> List[Dict[str, Any]]:
    """Прочитать автобиографические эпизоды Core из SQLite Delamain.

    Только чтение. Если Delamain не подключён, возвращаем пустой список:
    у UI нет собственного хранилища истории.
    """
    memory = getattr(getattr(_own(agent, "delamain", None), "runtime", None), "memory", None)
    reader = getattr(memory, "recent_life_episodes", None)
    if not callable(reader):
        return []
    try:
        return [dict(row) for row in reader(life_id=str(getattr(agent, "name", "?")),
                                            limit=max(0, min(int(limit), RECENT_EPISODES)))]
    except Exception:  # pragma: no cover - защита UI
        return []
