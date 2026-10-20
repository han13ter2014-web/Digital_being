"""
stimulus_selector.py — единый модуль выбора стимула для агента.

Раньше логика «какой стимул дать агенту в следующем тике» жила в двух
местах с разной вероятностью приоритезации по цели:

- ``main.py::_generate_prioritized_stimulus`` — p=0.4 (мягче, для CLI-режима)
- ``agent_runner.py::generate_prioritized_stimulus`` — p=0.7 (жёстче, для трея)

Это приводило к расхождению поведения и дублированию кода. Здесь — единая
реализация с параметром ``goal_priority_prob``.

Приоритеты (от высшего к низшему):
    1. Открытый вопрос пользователя/агента (свобода воли) — если есть и
       не исчерпан. Агент САМ решает, когда думать над вопросом.
    2. Приоритезация по активной цели — с вероятностью
       ``goal_priority_prob`` берём стимул, пересекающийся с целью.
    3. Случайный стимул из пула ``LR_CONFIG.STIMULI_POOL``.

Использование:
    >>> from src.core.stimulus_selector import select_stimulus
    >>> stim = select_stimulus(agent, goal_priority_prob=0.4)
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from config.simulation_config import LR_CONFIG

if TYPE_CHECKING:
    # Циклический импорт только для type-checking.
    pass


# Дефолтные вероятности, сохранённые из прежних локаций:
#   - main.py использовал 0.4 (мягкая приоритезация для CLI)
#   - agent_runner.py использовал 0.7 (жёсткая для трея)
DEFAULT_GOAL_PRIORITY_PROB = 0.4
TRAIL_GOAL_PRIORITY_PROB = 0.7

# Запасной стимул, если пул пуст (или kwargs некорректны).
FALLBACK_STIMULUS = "вопрос: что такое я"

# Длина ключевого слова в заголовке цели для матчинга.
_MIN_KEYWORD_LEN = 3

# Минимальное число совпадений ключевых слов для «приоритетного» стимула.
_MATCH_THRESHOLD = 2


def _try_consume_open_question(agent) -> str | None:
    """Попытаться взять следующий открытый вопрос (приоритет 1).

    Args:
        agent: экземпляр DigitalBeing.

    Returns:
        Готовый стимул-вопрос (``"вопрос: ... [стратегия=...]"``) или ``None``,
        если очередь пуста.
    """
    if not getattr(agent, "_open_questions", None):
        return None
    if not agent.has_open_questions():
        return None
    exploration = agent._consume_open_question()
    return exploration if exploration else None


def _pick_random(pool: list[str]) -> str:
    """Случайный стимул из пула, с безопасным fallback."""
    if not pool:
        return FALLBACK_STIMULUS
    return random.choice(pool)


# Python-стимулы, которым даётся доп. приоритет (используются
# в ``_apply_python_priority`` совместно с PYTHON_PRIORITY_MULTIPLIER).
_PYTHON_TECH_KEYWORDS: tuple[str, ...] = (
    "python", "питон", "import", "def", "класс", "объект",
    "модуль", "словарь", "список", "цикл", "переменная",
    "функция", "итерация", "генератор", "декоратор", "лямбда",
    "код", "алгоритм", "структура данных", "база данных", "sql",
    "нейросеть", "обучение", "трансформер", "языковая модель",
    "обработка естественного", "робототехника", "искусственный интеллект",
)


def _is_python_tech_stimulus(stimulus: str) -> bool:
    """Является ли стимул «Python/техническим» (для приоритезации).

    Используется в связке с ``PYTHON_PRIORITY_MULTIPLIER`` и
    ``TECH_PRIORITY_THRESHOLD`` из ``LR_CONFIG`` для улучшенной
    приоритезации Python-стимулов (раньше эти параметры конфига были
    объявлены, но игнорировались — мёртвый код).
    """
    s_lower = stimulus.lower()
    return any(kw in s_lower for kw in _PYTHON_TECH_KEYWORDS)


def _apply_python_priority(
    high_priority: list[str], low_priority: list[str],
    multiplier: float, threshold: float,
) -> tuple[list[str], list[str]]:
    """Дублирует Python-стимулы в ``high_priority`` (с учётом множителя).

    Логика:
    - Если ``multiplier >= threshold`` — каждый Python-стимул из ``low_priority``
      переносится в начало ``high_priority`` (теперь он приоритетный).
    - Это позволяет увеличить вероятность выбора Python-стимулов
      без поломки обычного keyword-матчинга.

    Args:
        high_priority: уже приоритетные стимулы (по цели).
        low_priority: остальные стимулы.
        multiplier: ``PYTHON_PRIORITY_MULTIPLIER`` (по умолчанию 3.0).
        threshold: ``TECH_PRIORITY_THRESHOLD`` (по умолчанию 0.6).

    Returns:
        (обновлённый high_priority, обновлённый low_priority).
    """
    if multiplier < threshold:
        return high_priority, low_priority

    new_high = list(high_priority)
    new_low = []
    for stim in low_priority:
        if _is_python_tech_stimulus(stim):
            new_high.append(stim)
        else:
            new_low.append(stim)
    return new_high, new_low


def _split_by_goal(
    pool: list[str], goal_title: str,
    *,
    apply_python_priority: bool = True,
    python_multiplier: float = 3.0,
    tech_threshold: float = 0.6,
) -> tuple[list[str], list[str]]:
    """Разделить пул на приоритетные и обычные стимулы по цели.

    Стимул считается «приоритетным», если в нём встречается ≥ 2 ключевых
    слов из заголовка активной цели (каждое слово длиной > ``_MIN_KEYWORD_LEN``).

    Дополнительно: если ``apply_python_priority=True`` (и
    ``python_multiplier >= tech_threshold``), Python/технические стимулы
    из обычного пула переносятся в приоритетный — используются
    ``PYTHON_PRIORITY_MULTIPLIER`` и ``TECH_PRIORITY_THRESHOLD`` из
    ``LR_CONFIG`` (раньше эти константы были объявлены, но не
    использовались).
    """
    goal_keywords = [w for w in goal_title.lower().split() if len(w) > _MIN_KEYWORD_LEN]
    if not goal_keywords:
        # Нет ключевых слов для матчинга — возвращаем всё как low,
        # но Python-стимулы всё равно поднимаем в приоритет.
        if apply_python_priority:
            return _apply_python_priority(
                [], list(pool), python_multiplier, tech_threshold
            )
        return [], list(pool)

    high_priority: list[str] = []
    low_priority: list[str] = []
    for stimulus in pool:
        s_lower = stimulus.lower()
        matches = sum(1 for kw in goal_keywords if kw in s_lower)
        if matches >= _MATCH_THRESHOLD:
            high_priority.append(stimulus)
        else:
            low_priority.append(stimulus)

    if apply_python_priority:
        high_priority, low_priority = _apply_python_priority(
            high_priority, low_priority, python_multiplier, tech_threshold
        )

    return high_priority, low_priority


def select_stimulus(
    agent,
    *,
    goal_priority_prob: float = DEFAULT_GOAL_PRIORITY_PROB,
    stimuli_pool: list[str] | None = None,
) -> str:
    """Выбрать следующий стимул для агента с учётом приоритетов.

    Args:
        agent: экземпляр DigitalBeing (любой объект с методами
            ``has_open_questions()``, ``_consume_open_question()`` и
            атрибутом ``active_goal``).
        goal_priority_prob: вероятность (0..1) выбрать приоритетный
            стимул, связанный с активной целью. По умолчанию 0.4
            (мягче — для CLI).
        stimuli_pool: пул стимулов (если ``None`` — берётся
            ``LR_CONFIG.STIMULI_POOL``).

    Returns:
        Текст стимула для ``agent.perceive(stimulus)``.
    """
    # === Приоритет 1: открытые вопросы (свобода воли) ===
    open_q = _try_consume_open_question(agent)
    if open_q:
        return open_q

    return _select_from_pool(
        agent,
        goal_priority_prob=goal_priority_prob,
        stimuli_pool=stimuli_pool,
    )


def _select_from_pool(
    agent,
    *,
    goal_priority_prob: float = DEFAULT_GOAL_PRIORITY_PROB,
    stimuli_pool: list[str] | None = None,
) -> str:
    """Выбор стимула только из пула (без открытых вопросов)."""
    pool = stimuli_pool if stimuli_pool is not None else LR_CONFIG.STIMULI_POOL

    # === Приоритет 2: приоритезация по активной цели ===
    if not LR_CONFIG.PRIORITIZE_STIMULI or not getattr(agent, "active_goal", None):
        return _pick_random(pool)

    goal_title = agent.active_goal["title"].lower()
    high_priority, low_priority = _split_by_goal(pool, goal_title)

    if high_priority and random.random() < goal_priority_prob:
        return random.choice(high_priority)

    return random.choice(low_priority) if low_priority else _pick_random(pool)


def _stimulus_key(stimulus: str) -> str:
    """Нормализованный ключ стимула для учёта повторов."""
    return stimulus.strip().lower()


def is_open_question_stimulus(stimulus: str) -> bool:
    """Является ли стимул открытым вопросом агента (а не пунктом пула).

    ``_consume_open_question`` добавляет к тексту ``[стратегия=...]``,
    поэтому такие стимулы уникальны и не должны попадать под кулдаун.
    """
    return "[стратегия=" in stimulus


def select_novel_stimulus(
    agent,
    recent: dict[str, int],
    tick: int,
    cooldown: int,
    *,
    goal_priority_prob: float = DEFAULT_GOAL_PRIORITY_PROB,
    stimuli_pool: list[str] | None = None,
) -> str | None:
    """Выбрать стимул, который агент не использовал последние ``cooldown`` тиков.

    Зачем: за 4 месяца агент повторил один и тот же стимул 13 596 раз
    (см. docs/BASELINE.md). Кулдаун превращает «бесконечный повтор»
    в осмысленный обход пула.

    Args:
        agent: экземпляр DigitalBeing.
        recent: словарь ``{ключ стимула: тик последнего использования}``.
            Мутируется вызывающим кодом, здесь только читается.
        tick: текущий номер тика (монотонно растёт).
        cooldown: сколько тиков стимул считается «скучным». 0 — выключено.
        goal_priority_prob: как в ``select_stimulus``.
        stimuli_pool: пул стимулов (по умолчанию ``LR_CONFIG.STIMULI_POOL``).

    Returns:
        Текст стимула или ``None``, если все стимулы на кулдауне —
        это сигнал «отдохнуть», а не повторять себя.
    """
    # Открытый вопрос — всегда свежий и одноразовый, кулдаун к нему не применяется.
    open_q = _try_consume_open_question(agent)
    if open_q:
        return open_q

    pool = stimuli_pool if stimuli_pool is not None else LR_CONFIG.STIMULI_POOL

    if cooldown > 0 and recent:
        fresh = [
            s for s in pool
            if tick - recent.get(_stimulus_key(s), -(10 ** 9)) >= cooldown
        ]
        if not fresh:
            return None
        pool = fresh

    return _select_from_pool(
        agent,
        goal_priority_prob=goal_priority_prob,
        stimuli_pool=pool,
    )


# Backwards-compat: функции, которые жили в main.py и agent_runner.py.
# Сигнатуры сохранены, чтобы существующие импорты не ломались.
def generate_prioritized_stimulus(agent) -> str:
    """Обратная совместимость: agent_runner.py::generate_prioritized_stimulus.

    Использует ``TRAIL_GOAL_PRIORITY_PROB = 0.7`` (жёсткая приоритезация для трея).
    """
    return select_stimulus(agent, goal_priority_prob=TRAIL_GOAL_PRIORITY_PROB)


__all__ = [
    "DEFAULT_GOAL_PRIORITY_PROB",
    "TRAIL_GOAL_PRIORITY_PROB",
    "FALLBACK_STIMULUS",
    "select_stimulus",
    "select_novel_stimulus",
    "is_open_question_stimulus",
    "generate_prioritized_stimulus",
]