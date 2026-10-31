"""Служебные записи не выдаются за знание, но и не удаляются из Core."""

from src.ui.concept_filter import is_service_concept, split_service_concepts


def test_real_service_records_are_hidden():
    for name in (
        "телесный опыт: deep_rest повышает энергию ниже потолка",
        "убеждение_1",
        "убеждение_8",
        "_bootstrap_loaded",
    ):
        assert is_service_concept(name), name


def test_raw_user_utterances_are_not_topics():
    for name in (
        "ты понимаешь меня",
        'привет, давай я буду звать тебя "малютка"',
        "получается не понимаешь",
        "как связаны слои нейросети",
        "что такое сознание?",
    ):
        assert is_service_concept(name), name


def test_real_concepts_stay_visible():
    for name in (
        "сверточный слой",
        "нейрон",
        "любопытство",
        "curiosity",
        "теория относительности",
        "ты",
        "цель",
    ):
        assert not is_service_concept(name), name


def test_split_counts_hidden_but_keeps_order():
    concepts = [
        ("я", object()),
        ("убеждение_1", object()),
        ("сверточный слой", object()),
        ("_bootstrap_loaded", object()),
    ]
    visible, hidden = split_service_concepts(concepts)
    assert [name for name, _ in visible] == ["я", "сверточный слой"]
    assert hidden == 2


def test_graph_hides_service_but_reports_count(tmp_path, monkeypatch):
    from src.core.agent import DigitalBeing
    from src.ui.graph_view import build_life_graph

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing("Alpha")
    agent.mental_models.encounter_concept(
        "телесный опыт: deep_rest повышает энергию ниже потолка", "тест", "ok"
    )
    agent.mental_models.encounter_concept("убеждение_1", "тест", "ok")
    agent.mental_models.encounter_concept("сверточный слой", "тест", "ok")

    graph = build_life_graph(agent)
    labels = {node["label"] for node in graph["nodes"] if node["kind"] == "concept"}
    assert "сверточный слой" in labels
    assert "убеждение_1" not in labels
    assert graph["hidden_service"] >= 2
    # Скрытие не означает удаление: Core по-прежнему знает эти записи.
    assert "убеждение_1" in agent.mental_models.concepts
