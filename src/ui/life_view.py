"""Преобразование снимка жизни в строки для карточек окна.

Чистая логика без Tk: сюда приходит словарь из ``build_life_snapshot``,
отсюда выходят готовые строки. Так карточки можно тестировать без экрана.

Главное правило — не выдумывать. Карточка показывает только то, что реально
лежит в снимке:

* «Почему выбрано» строится из причины намерения, состояния тела и прошлого
  исхода. Если ядро не сохранило проигравшие варианты, карточка их не
  рисует — лучше пусто, чем выдуманное «рассматривал X, Y, Z»;
* Effector показывает ``queued`` и ``waiting_approval`` отдельно от
  ``succeeded``: ожидание не выдаётся за выполненную работу.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

Row = Tuple[str, str]

# Действие → человеческая фраза для заголовка «Сейчас».
_ACTION_PHRASES = {
    "play": "Играю партию",
    "create_draft": "Продолжаю творческий черновик",
    "explore": "Исследую тему",
    "communicate": "Общаюсь",
    "rest": "Отдыхаю",
    "reflect": "Размышляю",
    "wait": "Жду",
}

# Темы, к которым осмысленно добавлять название в кавычках.
_ACTION_WITH_TOPIC = {"create_draft", "explore"}

_FATIGUE_LABELS = {
    "fresh": "свежая",
    "normal": "обычная",
    "tired": "усталость",
    "exhausted": "истощение",
    "critical": "критическая",
}

_STATE_LABELS = {
    "alive": "жив",
    "dormant": "спит",
    "terminated": "ушёл",
    "unknown": "неизвестно",
}

# Статусы Effector в человекочитаемом виде. Порядок важен: активные сверху.
_EFFECTOR_LABELS = (
    ("queued", "в очереди"),
    ("waiting_approval", "ждёт подтверждения"),
    ("succeeded", "выполнено"),
    ("failed", "ошибка"),
    ("rejected", "отклонено"),
)

_GAME_RESULTS = {
    "X": "победа",
    "O": "поражение",
    "draw": "ничья",
    None: "идёт",
}


def life_state_label(state: Any) -> str:
    """Состояние жизни по-русски; неизвестное значение отдаём как есть."""
    text = str(state)
    return _STATE_LABELS.get(text, text)


def _action_phrase(action: str, target: Optional[str]) -> str:
    phrase = _ACTION_PHRASES.get(action, action or "занятие")
    if target and action in _ACTION_WITH_TOPIC:
        return f"{phrase} «{target}»"
    return phrase


def now_headline(snapshot: Dict[str, Any]) -> str:
    """Одна живая фраза о том, что происходит прямо сейчас."""
    life = snapshot.get("life") or {}
    state = str(life.get("state", "unknown"))
    if state == "dormant":
        return "Сплю в Яслях"
    if state == "terminated":
        return "Жизнь завершена"
    if state not in {"alive", "unknown"}:
        return f"Состояние: {state}"

    activity = (snapshot.get("now") or {}).get("activity")
    if activity:
        return _action_phrase(str(activity.get("action") or ""), activity.get("target"))

    waiting = (snapshot.get("intentions") or {}).get("waiting") or []
    if waiting:
        target = waiting[0].get("target")
        if target:
            return f"Жду новых сведений по теме «{target}»"
        return "Жду новых условий"

    if life.get("needs_rest"):
        return "Отдыхаю после напряжённой работы"
    return "Выбираю, чем заняться"


def body_rows(snapshot: Dict[str, Any]) -> List[Row]:
    """Строки карточки тела: цифры, которые действительно есть."""
    life = snapshot.get("life") or {}
    rows: List[Row] = [("Цикл", str(life.get("cycle", 0)))]
    energy = life.get("energy")
    if energy is not None:
        rows.append(("Энергия", f"{float(energy):.0f}"))
    fatigue = life.get("fatigue")
    if fatigue is not None:
        level = life.get("fatigue_level")
        suffix = f" ({_FATIGUE_LABELS.get(str(level), level)})" if level else ""
        rows.append(("Усталость", f"{float(fatigue):.2f}{suffix}"))
    if life.get("needs_rest") is True:
        rows.append(("Нужен отдых", "да"))
    return rows


def body_summary(snapshot: Dict[str, Any]) -> str:
    """Одна строка о теле для подзаголовка: цикл · энергия · усталость."""
    life = snapshot.get("life") or {}
    parts: List[str] = []
    if life.get("cycle") is not None:
        parts.append(f"цикл {life.get('cycle')}")
    energy = life.get("energy")
    if energy is not None:
        parts.append(f"энергия {float(energy):.0f}")
    fatigue = life.get("fatigue")
    if fatigue is not None:
        level = life.get("fatigue_level")
        suffix = f" ({_FATIGUE_LABELS.get(str(level), level)})" if level else ""
        parts.append(f"усталость {float(fatigue):.2f}{suffix}")
    if life.get("needs_rest") is True:
        parts.append("нужен отдых")
    return " · ".join(parts) if parts else "нет данных о теле"


def activity_rows(snapshot: Dict[str, Any]) -> List[Row]:
    """Строки текущего занятия с реальными деталями игры или черновика."""
    activity = (snapshot.get("now") or {}).get("activity")
    if not activity:
        return [("Занятие", "начатого дела пока нет")]

    action = str(activity.get("action") or "")
    rows: List[Row] = [("Действие", _action_phrase(action, activity.get("target")))]
    # Для черновика тему покажет сама карточка работы: не дублируем.
    if activity.get("target") and action != "create_draft":
        rows.append(("Тема", str(activity["target"])))

    if action == "play":
        game = (snapshot.get("activities") or {}).get("game")
        if isinstance(game, dict):
            rows.append(("Ходов", str(game.get("turns", 0))))
            rows.append(("Партия", str(game.get("round", 1))))
            rows.append(("Результат", _GAME_RESULTS.get(game.get("result"), "идёт")))
    elif action == "create_draft":
        drafts = ((snapshot.get("activities") or {}).get("creative") or {}).get("drafts") or []
        active = [d for d in drafts if isinstance(d, dict) and d.get("status", "active") == "active"]
        if active:
            draft = active[-1]
            rows.append(("Черновик", str(draft.get("theme") or "—")))
            rows.append(("Редакция", str(draft.get("revision", 1))))

    if activity.get("cycle") is not None:
        rows.append(("Начато", f"цикл {activity['cycle']}"))
    return rows


def choice_rows(snapshot: Dict[str, Any]) -> List[Row]:
    """Почему выбрано именно это — из реальных полей, без вымысла."""
    activity = (snapshot.get("now") or {}).get("activity")
    if not activity:
        return []

    action = str(activity.get("action") or "")
    rows: List[Row] = [
        ("Выбрано", _action_phrase(action, activity.get("target"))),
        ("Источник", str(activity.get("source") or "—")),
    ]
    reason = str(activity.get("reason") or "").strip()
    rows.append(("Причина", reason or "не записана"))

    life = snapshot.get("life") or {}
    energy = life.get("energy")
    fatigue = life.get("fatigue")
    if energy is not None or fatigue is not None:
        parts = []
        if energy is not None:
            parts.append(f"энергия {float(energy):.0f}")
        if fatigue is not None:
            parts.append(f"усталость {float(fatigue):.2f}")
        rows.append(("Состояние тела", ", ".join(parts)))

    pref = (snapshot.get("preferences") or {}).get(action)
    if isinstance(pref, dict):
        rows.append((
            "Опыт способа",
            f"попыток {pref.get('attempts', 0)}, "
            f"с эффектом {pref.get('effects', 0)}, "
            f"сбоев {pref.get('failures', 0)}",
        ))

    loop = (snapshot.get("now") or {}).get("loop") or {}
    last_action = loop.get("last_action")
    if last_action:
        effect = "был эффект" if loop.get("last_effect") else "без эффекта"
        rows.append(("Прошлый исход", f"{last_action}: {effect}"))

    return rows


def influence_rows(snapshot: Dict[str, Any]) -> List[Row]:
    """Что влияет на выбор: потребности, влечения и ожидающие дела.

    Это уровни, а не «желания личности»: подпись так и говорит.
    """
    motivation = snapshot.get("motivation") or {}
    rows: List[Row] = []

    most = motivation.get("most_pressing_need")
    if most:
        rows.append(("Сильнее всего", str(most)))
    pressing = motivation.get("pressing_needs") or []
    if pressing:
        rows.append(("Настойчивые потребности", ", ".join(map(str, pressing))))
    drives = motivation.get("active_drives") or []
    if drives:
        rows.append(("Активные влечения", ", ".join(map(str, drives))))

    waiting = (snapshot.get("intentions") or {}).get("waiting") or []
    if waiting:
        targets = [str(item.get("target") or "—") for item in waiting[:3]]
        rows.append(("Ждут условий", ", ".join(targets)))

    if not rows:
        rows.append(("Сейчас", "ничего заметно не давит"))
    return rows


def access_rows(snapshot: Dict[str, Any]) -> List[Row]:
    """Что реально разрешено. Только существующие переключатели."""
    access = snapshot.get("access") or {}
    rows: List[Row] = []
    for key in ("network", "delamain", "effector"):
        item = access.get(key)
        if isinstance(item, dict):
            rows.append((str(item.get("label") or key),
                         "включено" if item.get("enabled") else "выключено"))
    workspace = access.get("workspace")
    if isinstance(workspace, dict):
        rows.append((str(workspace.get("label") or "Рабочая область"),
                     str(workspace.get("path") or "—")))
    return rows


def effector_rows(snapshot: Dict[str, Any]) -> List[Row]:
    """Счётчики действий. Ожидание и выполнение — разные строки."""
    effector = snapshot.get("effector") or {}
    if not effector.get("available"):
        return [("Состояние", "Effector не подключён")]
    counts = effector.get("counts") or {}
    rows = [(label, str(int(counts.get(key, 0) or 0)))
            for key, label in _EFFECTOR_LABELS]
    return rows


def pending_effector_note(snapshot: Dict[str, Any]) -> Optional[str]:
    """Честная пометка, если есть незавершённые действия.

    Возвращает текст, когда в очереди или на подтверждении что-то есть:
    иначе пользователь решит, что всё уже сделано.
    """
    counts = (snapshot.get("effector") or {}).get("counts") or {}
    pending = int(counts.get("queued", 0) or 0) + int(counts.get("waiting_approval", 0) or 0)
    if pending <= 0:
        return None
    return f"Не завершено: {pending} (в очереди или ждёт подтверждения)"
