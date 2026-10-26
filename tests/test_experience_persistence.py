"""Lossless concept evidence persistence and backwards-compatible inheritance."""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.app.bootstrap import awaken_from_seed
from src.cognition.mental_models import ConceptNode, MentalModel
from src.core.agent import DigitalBeing
from src.core.subsystems.mind_dream import MindDream


def _model():
    model = MentalModel("parent-model")
    node = ConceptNode("память")
    node.definition_hypothesis = "Память сохраняет накопленный опыт."
    for index in range(12):
        node.add_experience(
            f"context:{index}",
            f"observation:{index}",
            -0.4,
            evidence_strength=0.7 if index == 0 else 0.0,
            evidence_kind="observation",
            source="test:source",
            evidence_direction=1,
        )
    node.connections = {"опыт": 0.8123456789}
    node.usage_examples = [f"example:{index}" for index in range(8)]
    node.created_at = datetime(2020, 1, 2, 3, 4, 5, 123456)
    node.last_updated = datetime(2026, 10, 26, 12, 30, 0, 654321)
    model.concepts[node.name] = node
    model.metadata["total_concepts_encountered"] = 12
    model.association_memory = [{"concepts": ["память", "опыт"], "weight": 0.8}]
    return model


def _agent(model=None):
    return SimpleNamespace(
        name="child",
        mental_models=model if model is not None else MentalModel("empty"),
        save_state=Mock(),
        save_mental_models=Mock(),
    )


def _assert_node_equal(actual, expected):
    assert actual.to_storage_dict() == expected.to_storage_dict()
    assert actual.experiences == expected.experiences
    assert len(actual.contexts_encountered) == 12
    assert len(actual.usage_examples) == 8
    evidence = actual.experiences[0]
    assert evidence["evidence_strength"] == pytest.approx(0.7)
    assert evidence["evidence_kind"] == "observation"
    assert evidence["source"] == "test:source"
    assert evidence["evidence_direction"] == 1
    assert evidence["valence"] == -0.4
    before = actual.confidence
    assert actual.recompute_confidence() == pytest.approx(before)


def test_agent_save_load_preserves_full_experiences(tmp_path):
    original = _model()
    path = tmp_path / "mind" / "mental_models.json"
    DigitalBeing.save_mental_models(_agent(original), str(path))
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == original.to_storage_dict()
    assert "experiences" not in original.concepts["память"].to_dict()

    restored = _agent()
    restored.mental_models._related_cache[("stale", 1)] = (0, [])
    DigitalBeing.load_mental_models(restored, str(path))

    _assert_node_equal(restored.mental_models.concepts["память"], original.concepts["память"])
    assert restored.mental_models.name == original.name
    assert restored.mental_models.metadata == original.metadata
    assert restored.mental_models.association_memory == original.association_memory
    assert restored.mental_models._related_cache == {}


def test_node_storage_roundtrip_preserves_independent_data():
    original = _model().concepts["память"]
    restored = ConceptNode.from_dict(json.loads(json.dumps(original.to_storage_dict())))
    _assert_node_equal(restored, original)
    restored.experiences[0]["source"] = "changed"
    assert original.experiences[0]["source"] == "test:source"


@pytest.mark.parametrize("inherit", [False, True], ids=["agent-load", "seed-inheritance"])
def test_legacy_summary_remains_loadable(tmp_path, inherit):
    summary = {
        "definition_hypothesis": "Старое определение памяти",
        "confidence": 0.65,
        "experience_count": 25,
        "contexts": ["legacy context"],
        "usage_examples": ["legacy example"],
        "created_at": "2020-01-02T03:04:05",
        "last_updated": "2021-02-03T04:05:06",
    }
    seed_dir = tmp_path / "legacy"
    seed_dir.mkdir()
    path = seed_dir / "mental_models.json"
    path.write_text(json.dumps({"concepts": {"память": summary}}), encoding="utf-8")
    agent = _agent()
    if inherit:
        report = awaken_from_seed(agent, "legacy", str(tmp_path))
        assert report["inherited_concepts"] == 1
    else:
        DigitalBeing.load_mental_models(agent, str(path))

    node = agent.mental_models.concepts["память"]
    assert node.name == "память"
    assert node.definition_hypothesis == summary["definition_hypothesis"]
    assert node.legacy_confidence == pytest.approx(0.65)
    assert node.confidence == pytest.approx(0.1)
    assert node.experiences == []
    assert node.contexts_encountered == {"legacy context"}
    assert node.usage_examples == ["legacy example"]
    assert node.created_at == datetime(2020, 1, 2, 3, 4, 5)
    assert node.last_updated == datetime(2021, 2, 3, 4, 5, 6)


def test_dream_seed_export_and_inheritance_preserve_evidence(tmp_path):
    model = _model()
    parent = _agent(model)
    parent.intelligence = 1.0
    parent.cycle_count = 12
    parent.completed_goals = 2
    parent.energy = 0.5
    dream = MindDream("parent", registry=None)
    seed_data = dream._collect_seed_data(parent)
    assert seed_data["mental_models"] == model.to_storage_dict()

    seed_dir = tmp_path / "full-seed"
    seed_dir.mkdir()
    (seed_dir / "mental_models.json").write_text(
        json.dumps(seed_data["mental_models"], ensure_ascii=False), encoding="utf-8"
    )
    child = _agent()
    child.mental_models.concepts["existing"] = ConceptNode("existing")
    report = awaken_from_seed(child, "full-seed", str(tmp_path))

    assert report["inherited_concepts"] == 1
    assert report["concepts"] == 2
    assert report["saved"] is True
    _assert_node_equal(child.mental_models.concepts["память"], model.concepts["память"])
    child.save_state.assert_called_once_with()
    child.save_mental_models.assert_called_once_with()


def test_missing_model_file_leaves_existing_concepts_unchanged(tmp_path):
    model = _model()
    expected = model.to_storage_dict()
    DigitalBeing.load_mental_models(_agent(model), str(tmp_path / "missing.json"))
    assert model.to_storage_dict() == expected
