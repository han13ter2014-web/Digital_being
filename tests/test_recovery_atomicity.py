"""Неудачное восстановление не должно оставлять смесь состояний."""

import json
from types import SimpleNamespace

from src.cognition.empirical_claims import EmpiricalClaim
from src.cognition.mental_models import ConceptNode, MentalModel
from src.core.agent import DigitalBeing
from src.memory.long_term_memory import LongTermMemory


def memory_snapshot(memory):
    return (
        {key: trace.to_dict() for key, trace in memory._short_term.items()},
        {key: trace.to_dict() for key, trace in memory._long_term.items()},
        [trace.to_dict() for trace in memory._episodic],
        memory._consolidation_count,
        memory._decay_events_count,
    )


def test_corrupt_legacy_memory_does_not_replace_short_term_part(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    memory = LongTermMemory("RecoveryProbe")
    memory.store("прежнее воспоминание")
    previous = memory_snapshot(memory)

    new_trace = memory._short_term[
        memory._generate_id("прежнее воспоминание")
    ].to_dict()
    new_trace["content"] = "новое воспоминание"
    broken = new_trace.copy()
    del broken["created_at"]
    memory.memory_file = str(tmp_path / "memory" / "broken.json")
    with open(memory.memory_file, "w", encoding="utf-8") as handle:
        json.dump(
            {"short_term": {"new": new_trace}, "long_term": {"broken": broken}},
            handle,
        )

    memory._load_from_disk()

    assert memory_snapshot(memory) == previous


def test_corrupt_claims_do_not_leave_partially_loaded_concepts(tmp_path):
    model = MentalModel("текущая модель")
    model.concepts["прежняя"] = ConceptNode("прежняя")
    model.claims["прежнее"] = EmpiricalClaim.create(
        "прежнее", "прежняя", "energy", "increase", {}
    )
    previous = model.to_storage_dict()
    agent = SimpleNamespace(name="RecoveryProbe", mental_models=model)

    path = tmp_path / "mental_models.json"
    path.write_text(
        json.dumps(
            {
                "concepts": {
                    "новая": ConceptNode("новая").to_storage_dict(),
                },
                "claims": {
                    "повреждённое": {
                        "claim_id": "повреждённое",
                        "subject": "новая",
                        "metric": "неизвестная величина",
                        "relation": "increase",
                        "conditions": {},
                        "evidence": ConceptNode("доказательство").to_storage_dict(),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    DigitalBeing.load_mental_models(agent, str(path))

    assert model.to_storage_dict() == previous
