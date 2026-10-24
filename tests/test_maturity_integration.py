"""Интеграционные тесты зрелости: живой агент, чекпоинт, семя, CLI."""

import json
import os

import pytest

from src.core.agent import DigitalBeing
from src.core.maturity import assess


@pytest.fixture()
def agent():
    a = DigitalBeing(name="MaturityAgent")
    searcher = getattr(a, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    return a


# ============================================================
# 1. Отметка рождения
# ============================================================


def test_birth_mark_is_recorded(agent):
    """Агент помнит, с чем родился: иначе «нажитое» не измерить."""
    assert isinstance(agent._birth_concepts, int)
    assert agent._birth_concepts == len(agent.mental_models.concepts)
    assert agent._birth_concepts > 0


def test_birth_values_are_recorded(agent):
    assert hasattr(agent, "_birth_values")
    assert len(agent._birth_values) >= 1


# ============================================================
# 2. Новорождённый не зрелый
# ============================================================


def test_fresh_agent_is_not_mature(agent):
    report = assess(agent)

    assert report.is_mature is False
    assert report.met_count == 0
    # Все шесть критериев видны человеку с числами.
    assert len(report.criteria) == 6
    for item in report.criteria:
        assert item.value is not None


def test_fresh_agent_has_zero_earned_concepts(agent):
    report = assess(agent)
    new = next(c for c in report.criteria if c.name == "new_concepts")
    assert new.value == 0


# ============================================================
# 3. Жизнь приближает к порогу
# ============================================================


def test_life_advances_maturity(agent):
    """Циклы, концепции и результативные действия растут от жизни."""
    before = assess(agent)

    for i in range(20):
        agent.cycle_count = i + 1
        agent.autonomous_tick()

    after = assess(agent)

    def value(report, name):
        return next(c.value for c in report.criteria if c.name == name)

    assert value(after, "cycles") > value(before, "cycles")
    assert value(after, "new_concepts") > value(before, "new_concepts")
    assert value(after, "effective_ratio") > value(
        before, "effective_ratio"
    )


def test_value_change_counts_toward_maturity(agent):
    # Смена ценностей ограничена по времени (MIN_TIME_BETWEEN_VALUE_CHANGES),
    # поэтому сначала проживаем достаточно циклов.
    agent.cycle_count = 100
    result = agent.add_value("Тишина", reason="вырос из суеты")
    assert result.get("outcome") == "added", result

    report = assess(agent)
    changes = next(
        c for c in report.criteria if c.name == "value_changes"
    )
    assert changes.value >= 1
    assert changes.met is True


def test_completed_goal_counts_toward_maturity(agent):
    agent.set_goal("Проверить порог", activate=True)
    agent.complete_goal()

    report = assess(agent)
    goals = next(c for c in report.criteria if c.name == "goals_completed")
    assert goals.value >= 1
    assert goals.met is True


# ============================================================
# 4. Чекпоинт сохраняет возможность измерения
# ============================================================


def test_birth_mark_survives_checkpoint(agent):
    from src.core.checkpoint_serializer import (
        apply_state_to_agent,
        build_state_from_agent,
    )

    for i in range(5):
        agent.cycle_count = i + 1
        agent.autonomous_tick()

    state = build_state_from_agent(agent)
    assert state["birth_concepts"] == agent._birth_concepts

    reborn = DigitalBeing(name="MaturityAgent")
    searcher = getattr(reborn, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    apply_state_to_agent(reborn, state)

    assert reborn._birth_concepts == agent._birth_concepts
    assert reborn._birth_values == agent._birth_values
    # Оценка после рестарта не «обнуляется» и не завышается.
    assert assess(reborn).is_mature is False


# ============================================================
# 5. Семя несёт отчёт о зрелости
# ============================================================


def _make_seed(agent, name="Maturity_seed"):
    from src.core.paths import data_path

    seed_dir = os.path.join(data_path("nursery"), name)
    os.makedirs(seed_dir, exist_ok=True)
    data = agent.mind_dream._collect_seed_data(agent)
    agent.mind_dream._save_seed_files(seed_dir, agent, data, "тест")
    return seed_dir


def test_seed_contains_maturity_report(agent):
    seed_dir = _make_seed(agent)
    path = os.path.join(seed_dir, "maturity.json")

    assert os.path.isfile(path), "семя без отчёта о зрелости"
    with open(path, encoding="utf-8") as handle:
        report = json.load(handle)

    assert report["agent_name"] == "MaturityAgent"
    assert report["is_mature"] is False
    assert len(report["criteria"]) == 6
    assert "summary" in report


def test_seed_readme_mentions_maturity(agent):
    seed_dir = _make_seed(agent, "Maturity_seed_readme")
    with open(
        os.path.join(seed_dir, "README.md"), encoding="utf-8"
    ) as handle:
        text = handle.read()

    assert "maturity.json" in text
    # Инструкция запуска должна вести на единую точку входа.
    assert "python main.py --seed" in text


def test_child_inherits_concepts_but_starts_own_maturity(agent):
    """Ребёнок наследует знания, но не «зрелость» родителя.

    Зрелость — про прожитое, а не про унаследованное. Иначе любой ребёнок
    из зрелого семени сразу считался бы зрелым, и порог обесценился.
    """
    from src.app.bootstrap import awaken_from_seed

    # Родитель наживает концепции.
    for i in range(10):
        agent.cycle_count = i + 1
        agent.autonomous_tick()
    seed_dir = _make_seed(agent, "Maturity_seed_child")

    child = DigitalBeing(name="ChildMaturity")
    searcher = getattr(child, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    awaken_from_seed(child, os.path.basename(seed_dir))

    # Концепции унаследованы.
    assert len(child.mental_models.concepts) >= len(
        agent.mental_models.concepts
    )
    # Но циклов у ребёнка нет, и порог не пройден.
    child_report = assess(child)
    cycles = next(
        c for c in child_report.criteria if c.name == "cycles"
    )
    assert cycles.value == 0
    assert child_report.is_mature is False


# ============================================================
# 6. Публичный API и CLI
# ============================================================


def test_get_maturity_is_exposed(agent):
    data = agent.get_maturity()

    assert data["agent_name"] == "MaturityAgent"
    assert data["total"] == 6
    assert data["is_mature"] is False
    assert "blockers" in data


def test_cli_maturity_flag_exits_with_code(tmp_path, monkeypatch):
    """--maturity печатает отчёт и не запускает жизнь."""
    import main as entry

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))

    code = entry.main(["--maturity", "--new", "--ui", "headless"])
    # Новорождённый порог не проходит → код 1 (удобно для CI).
    assert code == 1


def test_cli_maturity_json_is_machine_readable(tmp_path, monkeypatch, capsys):
    import main as entry

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))

    code = entry.main(["--maturity-json", "--new", "--ui", "headless"])
    captured = capsys.readouterr().out

    payload = json.loads(captured)
    assert payload["is_mature"] is False
    assert payload["total"] == 6
    assert code == 1