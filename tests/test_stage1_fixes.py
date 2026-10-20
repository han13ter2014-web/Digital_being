"""Регрессионные тесты этапа 1 (docs/BASELINE.md → docs/STAGE1_REPORT.md).

Покрывают четыре дефекта, найденные на этапе 0:

1. «что такое такое» — 252 938 повторов в логе из-за декомпозиции.
2. Лог 420 МБ без ротации.
3. Энергия уходила в минус (−2.34 в чекпоинте).
4. Один и тот же стимул повторялся 13 596 раз.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cognition.thinking_pipeline import (  # noqa: E402
    ThinkingPipeline,
    normalize_concept_name,
)
from src.core.buffered_logger import BufferedLogger  # noqa: E402
from src.core.stimulus_selector import (  # noqa: E402
    is_open_question_stimulus,
    select_novel_stimulus,
)
from src.core.subsystems.energy_economics import EnergySubsystem  # noqa: E402


@pytest.fixture()
def pipeline():
    """ThinkingPipeline не трогает агента в _decompose_query."""
    return ThinkingPipeline(object())


class _FakeMentalModels:
    def __init__(self):
        self.concepts = {}

    def encounter_concept(self, concept_name, **kwargs):
        self.concepts[concept_name] = kwargs
        return type("Node", (), {"confidence": 0.1})()


class _FakeAgentWithModels:
    cycle_count = 0

    def __init__(self):
        self.mental_models = _FakeMentalModels()


# ============================================================
# 1. Декомпозиция
# ============================================================

def test_simple_what_is_question_is_not_decomposed(pipeline):
    """«что такое X» — уже простой вопрос, дробить нечего.

    Регресс: раньше возвращалось ['что такое счастье', 'что такое такое'].
    """
    for query in (
        "что такое счастье",
        "что такое жизнь",
        "что такое сознание",
        "что такое счастье?",
    ):
        assert pipeline._decompose_query(query) is None, query


def test_decomposition_never_contains_the_query_itself(pipeline):
    query = "что такое обучение нейросети"
    parts = pipeline._decompose_query(query) or []
    assert query not in [p.lower() for p in parts]


def test_decomposition_never_produces_stop_word_parts(pipeline):
    """«такое», «это», «как» не могут быть под-концепциями."""
    stop_words = ("такое", "это", "как", "что", "меня", "ты")
    for query in (
        "что такое счастье",
        "как работает мышление",
        "что такое обучение нейросети",
        "почему меня не понимают",
    ):
        for part in pipeline._decompose_query(query) or []:
            concept = part.replace("что такое ", "").strip()
            assert concept not in stop_words, (query, part)


def test_verb_form_does_not_become_a_concept(pipeline):
    """Регресс: «как работает мышление» → «что такое работает»."""
    parts = pipeline._decompose_query("как работает мышление") or []
    assert "что такое работает" not in [p.lower() for p in parts]


def test_decomposition_has_no_duplicate_parts(pipeline):
    parts = pipeline._decompose_query("что такое обучение нейросети") or []
    assert len(parts) == len(set(parts))


def test_known_complex_query_still_decomposes(pipeline):
    """Заготовленные разборы не сломаны фиксом."""
    parts = pipeline._decompose_query("глубокое обучение")
    assert parts == [
        "что такое обучение нейросети",
        "что такое глубокая сеть",
        "как работает backpropagation",
    ]


def test_stop_word_is_not_registered_as_concept():
    """_register_unknown_concept не должен создавать узел «такое»."""

    agent = _FakeAgentWithModels()
    pipe = ThinkingPipeline(agent)
    pipe._register_unknown_concept("такое", "вопрос: что такое?")
    assert agent.mental_models.concepts == {}


def test_register_unknown_concept_strips_question_prefix():
    """«что такое счастье» → узел «счастье», а не узел-фраза."""
    agent = _FakeAgentWithModels()
    pipe = ThinkingPipeline(agent)
    pipe._register_unknown_concept("что такое счастье", "вопрос: что такое счастье")
    assert list(agent.mental_models.concepts) == ["счастье"]


def test_normalize_concept_name():
    assert normalize_concept_name("что такое счастье") == "счастье"
    assert normalize_concept_name("Что такое счастье?") == "счастье"
    assert normalize_concept_name("как работает мышление?") == "мышление"
    assert normalize_concept_name("расскажи про энтропию") == "энтропию"
    assert normalize_concept_name("сознание") == "сознание"


# ============================================================
# 2. Ротация логов
# ============================================================

def test_buffered_logger_rotates(tmp_path):
    log_path = tmp_path / "agent_log.txt"
    logger = BufferedLogger(
        log_file=str(log_path), buffer_size=1, max_bytes=300, backup_count=2
    )
    for i in range(50):
        logger.log("x" * 100 + f" #{i}")
    logger.flush()

    files = sorted(p.name for p in tmp_path.iterdir())
    assert "agent_log.txt" in files
    assert "agent_log.txt.1" in files
    assert "agent_log.txt.2" in files
    # Больше backup_count+1 файлов быть не должно.
    assert len([f for f in files if f.startswith("agent_log.txt")]) <= 3


def test_log_files_stay_bounded(tmp_path):
    log_path = tmp_path / "agent_log.txt"
    logger = BufferedLogger(
        log_file=str(log_path), buffer_size=1, max_bytes=500, backup_count=3
    )
    for i in range(200):
        logger.log("y" * 80 + f" #{i}")
    logger.flush()

    for path in tmp_path.iterdir():
        # Немного больше лимита допустимо: размер проверяется до записи.
        assert path.stat().st_size <= 500 + 200, path.name


def test_rotation_disabled_when_max_bytes_zero(tmp_path):
    log_path = tmp_path / "agent_log.txt"
    logger = BufferedLogger(
        log_file=str(log_path), buffer_size=1, max_bytes=0, backup_count=3
    )
    for i in range(20):
        logger.log("z" * 50 + f" #{i}")
    logger.flush()
    assert log_path.exists()
    assert not (tmp_path / "agent_log.txt.1").exists()


# ============================================================
# 3. Энергия
# ============================================================

def test_energy_never_goes_negative():
    energy = EnergySubsystem(starting_energy=5)
    for _ in range(10):
        energy.pay("decomposition")
    assert energy.energy == 0.0
    assert energy.is_alive() is True
    assert energy.is_exhausted() is True


def test_energy_is_capped_at_max():
    energy = EnergySubsystem(starting_energy=150, max_energy=200)
    energy.energy = 10 ** 9
    assert energy.energy == 200
    energy.energy += 100
    assert energy.energy == 200


def test_restore_clamps_negative_energy():
    """В чекпоинте Alpha_cycle_186 лежало −2.34."""
    energy = EnergySubsystem(starting_energy=150, max_energy=200)
    energy.restore_from_checkpoint({"energy": -2.34})
    assert energy.energy == 0.0
    energy.restore_from_checkpoint({"energy": 10 ** 6})
    assert energy.energy == 200


def test_non_numeric_energy_does_not_crash():
    energy = EnergySubsystem(starting_energy=100)
    energy.energy = "not a number"
    assert energy.energy == 0.0


# ============================================================
# 4. Кулдаун стимулов
# ============================================================

class FakeAgent:
    """Минимальный агент для тестов селектора."""

    def __init__(self, active_goal=None, open_questions=None):
        self.active_goal = active_goal
        self._open_questions = open_questions or []

    def has_open_questions(self):
        return bool(self._open_questions)

    def _consume_open_question(self):
        if not self._open_questions:
            return None
        return self._open_questions.pop()


POOL = ["вопрос: a", "вопрос: b", "вопрос: c"]


def test_novel_stimulus_skips_recent():
    agent = FakeAgent()
    recent = {"вопрос: a": 9, "вопрос: b": 10}
    # tick=10, cooldown=2 → «a» (10-9=1) и «b» (0) скучные, «c» свежий.
    for _ in range(20):
        assert select_novel_stimulus(
            agent, recent, 10, 2, stimuli_pool=POOL, goal_priority_prob=0.0
        ) == "вопрос: c"


def test_novel_stimulus_returns_none_when_everything_cools_down():
    agent = FakeAgent()
    recent = {s: 10 for s in POOL}
    assert select_novel_stimulus(
        agent, recent, 10, 5, stimuli_pool=POOL, goal_priority_prob=0.0
    ) is None


def test_stimulus_becomes_fresh_again_after_cooldown():
    agent = FakeAgent()
    recent = {"вопрос: a": 1, "вопрос: b": 10, "вопрос: c": 10}
    # Прошло 20 тиков — «a» снова можно.
    for _ in range(20):
        assert select_novel_stimulus(
            agent, recent, 21, 20, stimuli_pool=POOL, goal_priority_prob=0.0
        ) == "вопрос: a"


def test_open_question_ignores_cooldown():
    """Открытый вопрос одноразовый и всегда свежий."""
    agent = FakeAgent(open_questions=["вопрос: новое [стратегия=hypothesis]"])
    recent = {s: 100 for s in POOL}
    stimulus = select_novel_stimulus(
        agent, recent, 100, 20, stimuli_pool=POOL, goal_priority_prob=0.0
    )
    assert stimulus == "вопрос: новое [стратегия=hypothesis]"


def test_is_open_question_stimulus():
    assert is_open_question_stimulus("вопрос: x [стратегия=декомпозиция]")
    assert not is_open_question_stimulus("вопрос: что такое жизнь")
