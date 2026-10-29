"""Тесты порога зрелости: «семя стоит раздавать» как измеримое событие.

Главное требование: порог не должен проходиться на новорождённом агенте,
иначе он ничего не измеряет.
"""

import json

import pytest

from src.core.maturity import (
    CONFIDENT_THRESHOLD,
    CriterionResult,
    MaturityCriteria,
    MaturityReport,
    assess,
    load_criteria,
)


# ============================================================
# Заглушки
# ============================================================


class FakeNode:
    def __init__(self, confidence=0.1, definition=""):
        self.confidence = confidence
        self.definition_hypothesis = definition


class FakeMentalModels:
    def __init__(self, confidences, defined=0):
        self.concepts = {}
        for i, value in enumerate(confidences):
            self.concepts[f"концепт_{i}"] = FakeNode(
                value,
                "формулировка из накопленного опыта" if i < defined else "",
            )


class FakeRegistry:
    def __init__(self, value_changes=0):
        self._value_changes = value_changes

    def get_stats(self):
        return {"by_type": {"value_changes": self._value_changes}}


class FakeLoopCloser:
    def __init__(self, effective_ratio=0.0):
        self._ratio = float(effective_ratio)

    def effect_ratio(self):
        return self._ratio


class FakeAgent:
    """Управляемый агент: задаём ровно те значения, что нужно."""

    name = "Fake"

    def __init__(
        self,
        *,
        cycles=0,
        confidences=(),
        birth=0,
        birth_defined=0,
        defined=0,
        value_changes=0,
        goals=0,
        effective_ratio=0.0,
    ):
        self.cycle_count = cycles
        self.mental_models = FakeMentalModels(confidences, defined)
        self._birth_concepts = birth
        self._birth_defined = birth_defined
        self.will_registry = FakeRegistry(value_changes)
        self.completed_goals = goals
        self.loop_closer = FakeLoopCloser(effective_ratio)


# ============================================================
# 1. Новорождённый не зрелый
# ============================================================


def test_newborn_is_not_mature():
    """Порог не проходит на пустом месте — иначе он бесполезен."""
    newborn = FakeAgent(
        cycles=0,
        confidences=[0.1] * 26,   # родовые знания
        birth=26,
        value_changes=0,
        goals=0,
        effective_ratio=0.0,
    )
    report = assess(newborn)

    assert report.is_mature is False
    assert report.met_count == 0
    assert report.total == 6


def test_newborn_reports_all_blockers():
    report = assess(FakeAgent(confidences=[0.1] * 26, birth=26))
    names = {item.name for item in report.blockers}

    assert names == {
        "cycles",
        "new_concepts",
        "defined_concepts",
        "value_changes",
        "goals_completed",
        "effective_ratio",
    }


# ============================================================
# 2. Зрелый агент проходит все критерии
# ============================================================


def _mature_agent():
    return FakeAgent(
        cycles=600,
        confidences=[0.8] * 50,
        birth=26,
        birth_defined=0,
        defined=30,               # у 30 есть своя формулировка
        value_changes=2,
        goals=3,
        effective_ratio=0.8,
    )


def test_mature_agent_passes():
    report = assess(_mature_agent())

    assert report.is_mature is True
    assert report.met_count == report.total
    assert report.blockers == []
    assert "порог пройден" in report.summary()


def test_mature_summary_has_no_missing_parts():
    summary = assess(_mature_agent()).summary()
    assert "не хватает" not in summary


# ============================================================
# 3. Каждый критерий считается отдельно
# ============================================================


def test_cycles_criterion():
    report = assess(
        FakeAgent(cycles=499, confidences=[0.8] * 50, birth=26),
        MaturityCriteria(min_cycles=500, min_new_concepts=1,
                         min_defined_concepts=1, min_value_changes=0,
                         min_goals_completed=0, min_effective_ratio_pct=0),
    )
    cycles = next(c for c in report.criteria if c.name == "cycles")
    assert cycles.met is False
    assert cycles.value == 499
    assert cycles.target == 500


def test_new_concepts_counts_only_earned():
    """Родовые знания не считаются достижением."""
    agent = FakeAgent(confidences=[0.8] * 46, birth=26)
    report = assess(agent)
    new = next(c for c in report.criteria if c.name == "new_concepts")

    assert new.value == 20  # 46 - 26


def test_new_concepts_never_negative():
    """После забывания концепций разница не должна уходить в минус."""
    agent = FakeAgent(confidences=[0.8] * 10, birth=26)
    report = assess(agent)
    new = next(c for c in report.criteria if c.name == "new_concepts")

    assert new.value == 0


def test_defined_concepts_counts_definitions():
    """Считаются концепции с собственной формулировкой сверх родовых."""
    agent = FakeAgent(
        confidences=[0.1] * 12, birth=0, birth_defined=0,
        defined=7,
    )
    report = assess(agent)
    item = next(
        c for c in report.criteria if c.name == "defined_concepts"
    )

    assert item.value == 7


def test_defined_concepts_excludes_innate():
    """Родовые определения не засчитываются как достижение агента."""
    agent = FakeAgent(
        confidences=[0.8] * 10, birth=10, birth_defined=4, defined=10
    )
    report = assess(agent)
    item = next(
        c for c in report.criteria if c.name == "defined_concepts"
    )

    assert item.value == 6  # 10 всего минус 4 родовых


def test_value_changes_from_registry():
    agent = FakeAgent(confidences=[], birth=0, value_changes=3)
    report = assess(agent)
    changes = next(c for c in report.criteria if c.name == "value_changes")

    assert changes.value == 3
    assert changes.met is True


def test_effective_ratio_is_percentage():
    """Доля результативных действий показывается в процентах."""
    agent = FakeAgent(confidences=[], birth=0, effective_ratio=0.73)
    report = assess(agent)
    item = next(
        c for c in report.criteria if c.name == "effective_ratio"
    )

    assert item.value == 73
    assert item.target == 50
    assert item.met is True


def test_zero_ratio_is_not_met():
    agent = FakeAgent(confidences=[], birth=0, effective_ratio=0.0)
    item = next(
        c for c in assess(agent).criteria if c.name == "effective_ratio"
    )
    assert item.met is False


# ============================================================
# 4. Неизвестное не выдаётся за успех
# ============================================================


def test_unknown_birth_mark_is_not_success():
    """Старый чекпоинт без отметки рождения — не повод считать зрелым."""

    class NoBirthMark(FakeAgent):
        def __init__(self):
            super().__init__(cycles=600, confidences=[0.8] * 50, birth=0)
            del self._birth_concepts

    report = assess(NoBirthMark())
    new = next(c for c in report.criteria if c.name == "new_concepts")

    assert new.value is None
    assert new.met is False
    assert report.birth_concepts_known is False
    assert report.is_mature is False
    assert "неизвестно" in new.describe()


def test_broken_agent_does_not_crash():
    class Broken:
        name = "B"
        cycle_count = "не число"

        @property
        def mental_models(self):
            raise RuntimeError("нет моделей")

    report = assess(Broken())
    assert report.agent_name == "B"
    assert report.is_mature is False


# ============================================================
# 5. Порог настраивается
# ============================================================


def test_custom_threshold():
    strict = MaturityCriteria(min_cycles=10000)
    report = assess(_mature_agent(), strict)
    assert report.is_mature is False
    assert any(c.name == "cycles" for c in report.blockers)


def test_criteria_from_dict_ignores_unknown_keys():
    criteria = MaturityCriteria.from_dict(
        {"min_cycles": 10, "неизвестно": 5, "min_goals_completed": 2}
    )
    assert criteria.min_cycles == 10
    assert criteria.min_goals_completed == 2


def test_criteria_from_garbage_is_default():
    assert MaturityCriteria.from_dict(None) == MaturityCriteria()
    assert MaturityCriteria.from_dict("мусор") == MaturityCriteria()


def test_load_criteria_from_file(tmp_path):
    path = tmp_path / "maturity.json"
    path.write_text(
        json.dumps({"criteria": {"min_cycles": 42}}), encoding="utf-8"
    )
    criteria = load_criteria(str(path))
    assert criteria.min_cycles == 42


def test_load_criteria_missing_file_is_default(tmp_path):
    criteria = load_criteria(str(tmp_path / "нет.json"))
    assert criteria == MaturityCriteria()


# ============================================================
# 6. Форматы вывода
# ============================================================


def test_report_json_roundtrip():
    report = assess(_mature_agent())
    data = json.loads(report.to_json())

    assert data["is_mature"] is True
    assert data["total"] == 6
    assert len(data["criteria"]) == 6
    assert data["blockers"] == []


def test_report_describe_mentions_verdict():
    text = assess(FakeAgent(confidences=[0.1] * 26, birth=26)).describe()
    assert "ВЕРДИКТ" in text
    assert "порог не пройден" in text


def test_criterion_progress_for_ui():
    item = CriterionResult(
        name="cycles", label="Циклы", value=250, target=500
    )
    assert item.progress() == 0.5
    assert item.met is False


def test_criterion_progress_unknown_is_zero():
    item = CriterionResult(name="x", label="X", value=None, target=10)
    assert item.progress() == 0.0
    assert item.met is False


def test_zero_target_is_always_met():
    item = CriterionResult(name="x", label="X", value=0, target=0)
    assert item.met is True
    assert item.progress() == 1.0