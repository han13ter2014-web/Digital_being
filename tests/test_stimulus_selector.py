"""
test_stimulus_selector.py — тесты для src.core.stimulus_selector.

Покрывает:
- Приоритет 1: открытые вопросы перебивают всё.
- Приоритет 2: goal-priority выбор с заданной вероятностью.
- Приоритет 3: fallback на случайный стимул.
- Безопасный fallback при пустом пуле.
- Безопасный fallback при отсутствии active_goal.
- Сценарий «детерминированный» для CLI (p=0) и трея (p=1).
"""

from src.core.stimulus_selector import (
    DEFAULT_GOAL_PRIORITY_PROB,
    FALLBACK_STIMULUS,
    TRAIL_GOAL_PRIORITY_PROB,
    generate_prioritized_stimulus,
    select_stimulus,
)


# ============================================================
# Минимальный fake-агент (не нужно поднимать всё DigitalBeing).
# ============================================================
class FakeAgent:
    """Эмулирует интерфейс DigitalBeing, нужный stimulus_selector-у.

    Не нужно вызывать конструктор DigitalBeing (он тяжёлый и тянет подсистемы).
    """

    def __init__(self, *, open_questions=None, active_goal=None):
        # Очередь открытых вопросов (как в DigitalBeing._open_questions)
        self._open_questions = open_questions or []
        self.active_goal = active_goal
        # Счётчик вызовов _consume_open_question — для проверки
        self._consume_call_count = 0

    def has_open_questions(self) -> bool:
        return any(not q.get("answered", False) for q in self._open_questions)

    def _consume_open_question(self) -> str | None:
        self._consume_call_count += 1
        for q in self._open_questions:
            if not q.get("answered", False):
                # Сразу помечаем как отвеченный, чтобы следующий consume
                # не вернул то же самое.
                q["answered"] = True
                return (
                    f"вопрос: {q['text']} "
                    f"[стратегия=hypothesis_generation, попытка 1/5]"
                )
        return None


# ============================================================
# Приоритет 1: открытые вопросы
# ============================================================
def test_open_question_takes_priority_over_stimuli():
    """Если есть открытый вопрос, он ВСЕГДА выбирается первым."""
    agent = FakeAgent(
        open_questions=[
            {"text": "что такое любовь?", "answered": False},
        ],
        active_goal={"title": "Выучить основы Python"},
    )
    pool = ["вопрос: что такое сознание", "команда import", "функция def"]

    result = select_stimulus(agent, goal_priority_prob=1.0, stimuli_pool=pool)

    assert result.startswith("вопрос: что такое любовь?")
    assert agent._consume_call_count == 1


def test_no_open_questions_falls_through_to_pool():
    """Если очередь пуста — выбирается стимул из пула (или fallback)."""
    agent = FakeAgent(
        open_questions=[
            {"text": "x", "answered": True},  # уже отвечен
        ],
        active_goal=None,
    )
    pool = ["единственный_стимул"]

    result = select_stimulus(agent, goal_priority_prob=0.4, stimuli_pool=pool)
    assert result == "единственный_стимул"


def test_generate_prioritized_stimulus_uses_trail_prob():
    """generate_prioritized_stimulus — обратная совместимость (p=0.7).

    Использует ``LR_CONFIG.STIMULI_POOL`` (не принимает свой pool) и
    ``TRAIL_GOAL_PRIORITY_PROB = 0.7`` (жёстче, чем CLI-вариант).
    """
    from config.simulation_config import LR_CONFIG

    # Без active_goal — гарантированно берём из пула (без goal-приоритета).
    agent = FakeAgent(active_goal=None)
    result_old = generate_prioritized_stimulus(agent)
    assert result_old in LR_CONFIG.STIMULI_POOL


# ============================================================
# Приоритет 2: приоритезация по цели
# ============================================================
def test_goal_priority_always_picks_high_with_prob_1():
    """С p=1.0 всегда выбирается приоритетный стимул (если есть).

    _MATCH_THRESHOLD=2: стимул должен содержать минимум 2 ключевых слова из
    заголовка цели. Цель = "изучить python функции" (keywords: python, функции).
    Стимул "python функции" содержит оба — попадает в high.

    ВАЖНО: начиная с Этапа 5 приоритезации, Python-стимулы ("python импорт")
    тоже попадают в high_priority (через PYTHON_PRIORITY_MULTIPLIER) —
    поэтому выбираем только из high, но это может быть любой из них.
    """
    agent = FakeAgent(
        active_goal={"title": "изучить python функции"},
    )
    high_only = "python функции"  # содержит оба keyword-а + Python
    pool = [
        high_only,
        "python импорт",     # Python-стимул → high через _apply_python_priority
        "не_связано_1",      # 0 совпадений, не Python → low
        "не_связано_2",
    ]
    for _ in range(50):
        result = select_stimulus(agent, goal_priority_prob=1.0, stimuli_pool=pool)
        # Должен быть из high_priority, не low
        assert result in {high_only, "python импорт"}, (
            f"Неожиданный выбор из low_priority: {result}"
        )
        assert result not in {"не_связано_1", "не_связано_2"}, (
            f"Выпало в low: {result}"
        )


def test_no_priority_when_prob_zero():
    """С p=0 всегда выбирается не-приоритетный стимул (если есть).

    С p=0 random.random() < 0.0 — false, поэтому берём из low_priority.
    high_priority — "python функции" (2 совпадения), low — остальные.
    """
    agent = FakeAgent(
        active_goal={"title": "изучить python функции"},
    )
    pool = [
        "python функции",  # 2 совпадения → high_priority
        "не_связано_1",   # 0 совпадений → low_priority
        "не_связано_2",
    ]
    for _ in range(50):
        result = select_stimulus(agent, goal_priority_prob=0.0, stimuli_pool=pool)
        assert result in {"не_связано_1", "не_связано_2"}, f"Неожиданный выбор: {result}"


def test_short_goal_keywords_ignored():
    """Короткие слова (<=3 символов) не учитываются как ключевые."""
    agent = FakeAgent(
        active_goal={"title": "it is"},  # все слова слишком короткие
    )
    pool = ["единственный_стимул"]
    result = select_stimulus(agent, goal_priority_prob=1.0, stimuli_pool=pool)
    # Нет ключевых слов → все стимулы идут в low_priority → выбираем из low
    assert result == "единственный_стимул"


def test_no_active_goal_uses_random_pool():
    """Без active_goal → случайный стимул (даже при p=1.0)."""
    agent = FakeAgent(active_goal=None)
    pool = ["a", "b", "c"]
    result = select_stimulus(agent, goal_priority_prob=1.0, stimuli_pool=pool)
    assert result in pool


def test_prioritize_disabled_uses_random():
    """Если PRIORITIZE_STIMULI=False в конфиге — случайный стимул."""
    from config.simulation_config import LR_CONFIG
    original = LR_CONFIG.PRIORITIZE_STIMULI
    try:
        LR_CONFIG.PRIORITIZE_STIMULI = False
        agent = FakeAgent(
            active_goal={"title": "изучить python"},
        )
        pool = [
            "вопрос: python функции",  # было бы приоритетным
            "другой_стимул",
        ]
        for _ in range(20):
            result = select_stimulus(agent, goal_priority_prob=1.0, stimuli_pool=pool)
            assert result in pool
    finally:
        LR_CONFIG.PRIORITIZE_STIMULI = original


# ============================================================
# Приоритет 3: fallback
# ============================================================
def test_empty_pool_returns_fallback():
    """При пустом пуле — FALLBACK_STIMULUS."""
    agent = FakeAgent()
    result = select_stimulus(agent, stimuli_pool=[])
    assert result == FALLBACK_STIMULUS


def test_no_active_goal_no_pool_uses_fallback():
    """Нет цели + пустой пул = FALLBACK_STIMULUS."""
    agent = FakeAgent(active_goal=None)
    # Даже без явного пула — LR_CONFIG.STIMULI_POOL непустой, но мы передаём []
    result = select_stimulus(agent, stimuli_pool=[])
    assert result == FALLBACK_STIMULUS


# ============================================================
# Backward-compat: generate_prioritized_stimulus (используется в agent_runner.py)
# ============================================================
def test_generate_prioritized_stimulus_signature_preserved():
    """``generate_prioritized_stimulus(agent)`` — старый контракт, без kwargs."""
    agent = FakeAgent(active_goal=None)
    # Должен работать без явных kwargs (только позиционный agent)
    result = generate_prioritized_stimulus(agent)
    assert isinstance(result, str)
    assert result  # не пусто


def test_default_and_trail_probs_differ():
    """DEFAULT ≠ TRAIL — разные режимы (CLI vs tray)."""
    assert DEFAULT_GOAL_PRIORITY_PROB == 0.4
    assert TRAIL_GOAL_PRIORITY_PROB == 0.7
    assert DEFAULT_GOAL_PRIORITY_PROB != TRAIL_GOAL_PRIORITY_PROB


# ============================================================
# Граничные случаи
# ============================================================
def test_stimuli_pool_none_uses_config():
    """Если stimuli_pool=None — берётся LR_CONFIG.STIMULI_POOL."""
    agent = FakeAgent(active_goal=None)
    from config.simulation_config import LR_CONFIG
    # По умолчанию LR_CONFIG.STIMULI_POOL непустой
    result = select_stimulus(agent)  # stimuli_pool=None → из конфига
    assert result in LR_CONFIG.STIMULI_POOL


def test_high_priority_count_check():
    """Цель с 2+ совпадениями — попадает в high_priority.

    ВАЖНО: Python-стимулы ("python импорт") теперь поднимаются в high_priority
    через ``_apply_python_priority`` (Этап 5) — раньше они шли в low.
    """
    from src.core.stimulus_selector import _split_by_goal
    pool = ["python функции", "python импорт", "просто шум"]
    high, low = _split_by_goal(pool, "изучить python функции")
    # "python функции" — 2 keyword-а, "python импорт" — 1 keyword + Python-priority
    assert "python функции" in high
    assert "python импорт" in high  # Python-стимул поднялся
    assert low == ["просто шум"]


# ============================================================
# Этап 5: Python-приоритезация (PYTHON_PRIORITY_MULTIPLIER)
# ============================================================
def test_python_priority_disabled_with_low_multiplier():
    """При multiplier < threshold — Python-стимулы не поднимаются."""
    from src.core.stimulus_selector import _split_by_goal
    pool = ["python импорт", "не_связано"]
    high, low = _split_by_goal(
        pool, "изучить что-то другое",
        python_multiplier=0.5,  # ниже дефолтного threshold=0.6
        tech_threshold=0.6,
    )
    # Python-стимул НЕ поднимается (multiplier < threshold)
    assert high == []
    assert set(low) == {"python импорт", "не_связано"}


def test_python_priority_enabled_by_default():
    """При multiplier (3.0) >= threshold (0.6) — Python-стимулы поднимаются."""
    from src.core.stimulus_selector import _split_by_goal
    pool = ["python импорт", "python def", "не_связано"]
    high, low = _split_by_goal(
        pool, "изучить что-то",  # цель не содержит python
    )
    # Все Python-стимулы поднялись в high
    assert set(high) == {"python импорт", "python def"}
    assert low == ["не_связано"]


def test_python_priority_can_be_disabled_via_param():
    """apply_python_priority=False — отключает приоритезацию."""
    from src.core.stimulus_selector import _split_by_goal
    pool = ["python импорт", "не_связано"]
    high, low = _split_by_goal(
        pool, "изучить что-то",
        apply_python_priority=False,
    )
    # Python-стимул НЕ поднялся (отключено)
    assert high == []
    assert set(low) == {"python импорт", "не_связано"}


def test_is_python_tech_stimulus():
    """Распознавание Python/технических стимулов."""
    from src.core.stimulus_selector import _is_python_tech_stimulus
    # Питоновые
    assert _is_python_tech_stimulus("команда import")
    assert _is_python_tech_stimulus("функция def")
    assert _is_python_tech_stimulus("алгоритм сортировки")
    assert _is_python_tech_stimulus("нейросеть архитектура")
    # Не-питоновые
    assert not _is_python_tech_stimulus("что такое любовь")
    assert not _is_python_tech_stimulus("в чем смысл жизни")
    assert not _is_python_tech_stimulus("вопрос: что такое счастье")


def test_try_consume_open_question_returns_none_for_empty():
    """_try_consume_open_question возвращает None при пустой очереди."""
    from src.core.stimulus_selector import _try_consume_open_question
    agent = FakeAgent(open_questions=[])
    assert _try_consume_open_question(agent) is None