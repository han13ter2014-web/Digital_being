"""Карта жизни: только реальные узлы и связи, без выдуманных рёбер."""

from copy import deepcopy

from src.cognition.intention_history import begin_intention
from src.cognition.mental_models import ConceptNode
from src.core.agent import DigitalBeing
from src.ui.graph_view import (
    MAX_CONCEPTS,
    MAX_NODES,
    MAX_VALUES,
    build_life_graph,
    layout_labels,
    layout_nodes,
    node_radius,
    node_shows_label,
    short_label,
)
from src.ui.life_snapshot import build_life_snapshot


def _agent(name="Graph"):
    agent = DigitalBeing(name=name)
    # Чистая сцена: стартовые понятия и ценности Core здесь только мешают.
    agent.mental_models.concepts.clear()
    agent.innate_values = {}
    return agent


def _concept(agent, name, *, confidence=0.5, experiences=1, connections=None):
    node = ConceptNode(name)
    node.confidence = confidence
    node.experiences = [{}] * experiences
    node.connections = dict(connections or {})
    agent.mental_models.concepts[name] = node
    return node


def _ids(graph):
    return {node["id"] for node in graph["nodes"]}


# ---------------------------------------------------------------- связи


def test_graph_uses_only_recorded_links():
    agent = _agent()
    _concept(agent, "память", confidence=0.6, experiences=3,
             connections={"внимание": 0.7})
    _concept(agent, "внимание", confidence=0.4, experiences=2)
    entry = begin_intention(agent, {"action": "explore", "source": "activity",
                                    "params": {"topic": "память", "reason": "интерес"}})

    graph = build_life_graph(agent, build_life_snapshot(agent))

    assert {"concept:память", "concept:внимание",
            f"intention:{entry['id']}", "activity:explore"} <= _ids(graph)
    edges = {(edge["source"], edge["target"], edge["kind"]) for edge in graph["edges"]}
    assert ("concept:память", "concept:внимание", "association") in edges
    assert (f"intention:{entry['id']}", "concept:память", "about") in edges
    assert (f"intention:{entry['id']}", "activity:explore", "uses") in edges


def test_graph_has_no_edges_without_basis():
    agent = _agent()
    _concept(agent, "тишина")
    _concept(agent, "город")

    graph = build_life_graph(agent)

    assert graph["edges"] == []
    assert not any(node["kind"] == "activity" for node in graph["nodes"])


def test_connection_to_unknown_concept_does_not_become_an_edge():
    agent = _agent()
    _concept(agent, "память", connections={"нет-такой": 0.9})

    graph = build_life_graph(agent)

    assert _ids(graph) == {"concept:память"}
    assert graph["edges"] == []


def test_concept_detail_reports_sources_and_last_seen():
    agent = _agent()
    node = _concept(agent, "память", confidence=0.5)
    node.experiences = [
        {"source": "наблюдение", "timestamp": "2026-10-01T10:00:00"},
        {"source": "наблюдение", "timestamp": "2026-10-02T11:00:00"},
        {"source": "человек", "timestamp": "2026-09-30T09:00:00"},
    ]

    graph = build_life_graph(agent)
    detail = next(n for n in graph["nodes"] if n["id"] == "concept:память")["detail"]

    assert detail["свидетельств"] == 3
    assert detail["источников"] == 2
    assert detail["последнее"] == "2026-10-02 11:00"


def test_forgotten_intention_is_marked_not_hidden():
    agent = _agent()
    entry = {"id": "f" * 8, "action": "explore", "target": None,
             "status": "performed"}
    forgotten = dict(entry, resolution={
        "kind": "forgotten", "reason": "источников нет", "cycle": 3})

    # Тот же id есть и в истории, и в забытых: узел должен стать забытым,
    # а не остаться «выполненным».
    graph = build_life_graph(agent, {"intentions": {
        "recent": [entry], "waiting": [], "forgotten": [forgotten]}})

    kinds = {node["id"]: node["kind"] for node in graph["nodes"]}
    assert kinds[f"intention:{entry['id']}"] == "forgotten"


# ---------------------------------------------------------------- границы


def test_graph_respects_node_limit_and_reports_omission():
    agent = _agent()
    for index in range(MAX_NODES + 40):
        _concept(agent, f"к{index}", confidence=0.1 + index / 1000)

    graph = build_life_graph(agent)

    assert len(graph["nodes"]) <= MAX_NODES
    assert len(graph["nodes"]) <= MAX_CONCEPTS
    assert graph["truncated"] is True
    assert graph["omitted"] >= 40
    kept = _ids(graph)
    for edge in graph["edges"]:
        assert edge["source"] in kept
        assert edge["target"] in kept


def test_values_come_from_core_and_are_capped():
    agent = _agent()
    agent.innate_values = {f"v{index}": 0.5 for index in range(MAX_VALUES + 4)}

    graph = build_life_graph(agent)

    values = [node for node in graph["nodes"] if node["kind"] == "value"]
    assert len(values) == MAX_VALUES
    assert {node["id"] for node in values} <= {
        f"value:v{index}" for index in range(MAX_VALUES + 4)
    }


def test_known_value_gets_russian_label_unknown_stays_as_is():
    agent = _agent()
    agent.innate_values = {"autonomy": 0.7, "неизвестное": 0.3}

    graph = build_life_graph(agent)

    labels = {node["id"]: node["label"] for node in graph["nodes"]}
    assert labels["value:autonomy"] == "автономия"
    assert labels["value:неизвестное"] == "неизвестное"


# ---------------------------------------------------------------- read-only


def test_graph_does_not_mutate_core_or_create_lazy_fields():
    agent = _agent()
    _concept(agent, "память", connections={"город": 0.4})
    _concept(agent, "город")
    begin_intention(agent, {"action": "explore", "params": {"topic": "память"}})

    keys_before = set(agent.__dict__)
    history_before = deepcopy(agent._intention_history)
    concepts_before = {
        name: (dict(node.connections), node.confidence)
        for name, node in agent.mental_models.concepts.items()
    }

    first = build_life_graph(agent, build_life_snapshot(agent))
    second = build_life_graph(agent, build_life_snapshot(agent))

    assert first == second
    assert set(agent.__dict__) == keys_before
    assert agent._intention_history == history_before
    assert {
        name: (dict(node.connections), node.confidence)
        for name, node in agent.mental_models.concepts.items()
    } == concepts_before


def test_graph_does_not_create_lazy_fields_on_fresh_agent():
    agent = _agent()
    assert "_intention_history" not in agent.__dict__
    assert "_waiting_intentions" not in agent.__dict__

    build_life_graph(agent)

    assert "_intention_history" not in agent.__dict__
    assert "_waiting_intentions" not in agent.__dict__


# ---------------------------------------------------------------- раскладка


def test_layout_is_deterministic_and_inside_bounds():
    nodes = [{"id": f"concept:{index}", "kind": "concept", "weight": 0.3}
             for index in range(30)]
    nodes.append({"id": "value:autonomy", "kind": "value", "weight": 0.5})

    first = layout_nodes(nodes, 800, 600)
    second = layout_nodes(list(reversed(nodes)), 800, 600)

    assert first == second
    assert set(first) == {node["id"] for node in nodes}
    for x, y in first.values():
        assert 0 <= x <= 800
        assert 0 <= y <= 600


def test_radius_and_labels_follow_weight():
    assert node_radius(1.0) > node_radius(0.0)
    assert node_shows_label(0.9)
    assert not node_shows_label(0.1)
    # Ценность подписана всегда: иначе её не отличить от фона.
    assert node_shows_label(0.1, "value")


def _label_box(position, text):
    x, y, anchor = position
    width = len(text) * 6.8 + 6.0
    height = 17.0
    if anchor == "w":
        return (x, y - height / 2, x + width, y + height / 2)
    if anchor == "e":
        return (x - width, y - height / 2, x, y + height / 2)
    if anchor == "n":
        return (x - width / 2, y, x + width / 2, y + height)
    return (x - width / 2, y - height, x + width / 2, y)


def test_labels_do_not_overlap_and_stay_inside():
    nodes = [
        {"id": f"concept:{index}", "kind": "concept", "label": f"тема {index}",
         "weight": 0.9 - index * 0.05}
        for index in range(14)
    ]
    nodes.append({"id": "intention:1", "kind": "intention",
                  "label": "исследую тему «память»", "weight": 0.8})
    nodes.append({"id": "value:autonomy", "kind": "value",
                  "label": "автономия", "weight": 0.5})
    positions = layout_nodes(nodes, 800, 600)

    labels = layout_labels(nodes, positions, 800, 600)
    text_by_id = {node["id"]: node["label"] for node in nodes}
    boxes = {node_id: _label_box(label, short_label(text_by_id[node_id]))
             for node_id, label in labels.items()}

    assert len(boxes) >= 10
    for box in boxes.values():
        assert box[0] >= 4 and box[1] >= 4
        assert box[2] <= 796 and box[3] <= 596
    ordered = list(boxes.values())
    for first_index, first in enumerate(ordered):
        for second in ordered[first_index + 1:]:
            assert (first[2] + 3 < second[0] or second[2] + 3 < first[0]
                    or first[3] + 3 < second[1] or second[3] + 3 < first[1])


def test_labels_are_deterministic_and_skip_what_does_not_fit():
    nodes = [{"id": f"concept:{index}", "kind": "concept",
              "label": f"тема {index}", "weight": 0.7}
             for index in range(6)]
    positions = layout_nodes(nodes, 900, 600)

    first = layout_labels(nodes, positions, 900, 600)
    second = layout_labels(list(reversed(nodes)), positions, 900, 600)

    assert first == second
    # В крошечной области подписи не помещаются — лучше не рисовать их вовсе.
    assert layout_labels(nodes, layout_nodes(nodes, 60, 60), 60, 60) == {}
