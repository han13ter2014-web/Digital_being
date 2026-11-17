"""Этап 4: scoped ассоциативный лексикон без изменения Core choice."""

from copy import deepcopy

import pytest

from src.cognition.mental_models import ConceptNode
from src.core.agent import DigitalBeing
from src.core.associative_lexicon import (
    MAX_PROVENANCE,
    MAX_RECORDS,
    AssociativeLexicon,
)
from src.core.checkpoint_serializer import (
    CheckpointSerializer,
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.dialogue_acts import (
    ACT_SOCIAL,
    ACT_UNKNOWN,
    DialogueAct,
    classify_user_text,
)
from src.core.life_systems_bridge import associate_expression, observe_user_message


def _record(lexicon, expression, *, shared=False):
    state = lexicon.to_shared_dict() if shared else lexicon.to_personal_dict()
    return next(item for item in state["records"] if item["expression"] == expression)


def test_held_out_recall_proposes_candidate_without_changing_dialogue_act():
    lexicon = AssociativeLexicon()
    lexicon.observe_act("тихий огонь рядом", ACT_SOCIAL, cycle=1, profile_id="owner")
    held_out = "огонь тихий"

    before = classify_user_text(held_out)
    candidates = lexicon.recall(held_out, cycle=2, profile_id="owner")
    after = classify_user_text(held_out)

    assert before.kind == ACT_UNKNOWN
    assert candidates[0]["target_kind"] == "act"
    assert candidates[0]["target_id"] == ACT_SOCIAL
    assert candidates[0]["scope"] == "personal"
    assert candidates[0]["provenance"][0]["source"] == "observed_act"
    assert after == before


def test_same_observation_history_is_reproducible():
    first = AssociativeLexicon()
    second = AssociativeLexicon()
    for cycle in (1, 2, 3):
        for lexicon in (first, second):
            lexicon.observe_act(
                "спокойный свет", ACT_SOCIAL, cycle=cycle, profile_id="owner"
            )

    assert first.to_personal_dict() == second.to_personal_dict()
    assert first.recall("свет спокойный", cycle=4, profile_id="owner") == second.recall(
        "свет спокойный", cycle=4, profile_id="owner"
    )


def test_personal_observation_never_becomes_shared_automatically():
    lexicon = AssociativeLexicon()
    lexicon.observe_act("личный оборот", ACT_SOCIAL, cycle=1, profile_id="first")
    lexicon.associate(
        "общий оборот",
        "context",
        "вечерний разговор",
        cycle=2,
        scope="shared",
        profile_id="first",
        source="explicit",
    )

    assert not lexicon.recall("личный оборот", cycle=3, profile_id="second")
    assert lexicon.recall("личный оборот", cycle=3, profile_id="first")
    shared = lexicon.recall("общий оборот", cycle=3, profile_id="second")
    assert shared[0]["scope"] == "shared"
    assert shared[0]["profile_id"] == ""
    assert shared[0]["provenance"][0]["profile_id"] == "first"
    assert all(
        record["scope"] == "shared" for record in lexicon.to_shared_dict()["records"]
    )


def test_unconfirmed_decay_and_confirmed_stability():
    lexicon = AssociativeLexicon()
    lexicon.associate(
        "слабая связь",
        "context",
        "разговор",
        cycle=0,
        profile_id="owner",
        source="observed_act",
    )
    lexicon.associate(
        "подтверждённая связь",
        "context",
        "разговор",
        cycle=0,
        profile_id="owner",
        source="user_taught",
    )

    assert lexicon.decay_unconfirmed(50) == 0
    assert _record(lexicon, "слабая связь")["confidence"] == pytest.approx(0.15)
    assert lexicon.decay_unconfirmed(200) == 1
    assert not lexicon.recall("слабая связь", cycle=200, profile_id="owner")
    assert _record(lexicon, "подтверждённая связь")["confidence"] == 0.7


def test_provenance_and_record_collections_are_bounded():
    lexicon = AssociativeLexicon()
    for cycle in range(MAX_PROVENANCE + 4):
        lexicon.associate(
            "ограниченная связь",
            "context",
            "разговор",
            cycle=cycle,
            profile_id="owner",
            source="observed_act",
        )
    record = _record(lexicon, "ограниченная связь")
    assert len(record["provenance"]) == MAX_PROVENANCE
    assert record["confirmations"] == MAX_PROVENANCE

    for index in range(MAX_RECORDS + 5):
        lexicon.associate(
            f"связь {index}",
            "context",
            "предел",
            cycle=20 + index,
            profile_id="owner",
            source="observed_act",
        )
    assert len(lexicon.to_personal_dict()["records"]) == MAX_RECORDS


def test_concept_and_episode_require_real_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="LexiconTargets")
    agent.mental_models.concepts["дружба"] = ConceptNode("дружба")
    episode_id = agent.long_term_memory.store(
        "Реальный разговор", memory_type="episodic"
    )

    concept = associate_expression(
        agent, "близкий человек", "concept", "дружба", cycle=1
    )
    episode = associate_expression(
        agent, "тот разговор", "episode", episode_id, cycle=2
    )

    assert concept["target_id"] == "дружба"
    assert episode["target_id"] == episode_id
    assert agent.long_term_memory.has_episode(episode_id)
    with pytest.raises(ValueError, match="real concept target"):
        associate_expression(agent, "выдумка", "concept", "отсутствует", cycle=3)
    with pytest.raises(ValueError, match="real episode target"):
        associate_expression(agent, "выдумка", "episode", "mem_missing", cycle=3)


def test_profile_switch_isolates_personal_associations(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing(name="LexiconProfiles")
    owner = agent.social_registry.owner_profile_id
    observe_user_message(agent, "вечерний маяк", DialogueAct(ACT_SOCIAL), 1)

    guest = agent.social_registry.create_local_person("Миша", cycle=2)
    assert agent.social_attribution.sync_active_profile()
    assert not agent.associative_lexicon.recall(
        "маяк вечерний", cycle=2, profile_id=guest
    )
    observe_user_message(agent, "тёплый ветер", DialogueAct(ACT_SOCIAL), 2)

    agent.social_registry.switch_to(owner, cycle=3)
    assert agent.social_attribution.sync_active_profile()
    assert (
        agent.associative_lexicon.recall("маяк вечерний", cycle=3, profile_id=owner)[0][
            "target_id"
        ]
        == ACT_SOCIAL
    )
    assert not agent.associative_lexicon.recall(
        "ветер тёплый", cycle=3, profile_id=owner
    )


def test_file_restart_restores_shared_and_active_personal_lexicon(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))
    source = DigitalBeing(name="LexiconRestart")
    owner = source.social_registry.owner_profile_id
    observe_user_message(source, "тихий огонь", DialogueAct(ACT_SOCIAL), 1)
    source.associative_lexicon.associate(
        "общий свет",
        "context",
        "разговор",
        cycle=1,
        scope="shared",
        profile_id=owner,
        source="explicit",
    )
    serializer = CheckpointSerializer(checkpoint_dir=str(tmp_path / "checkpoints"))
    checkpoint = serializer.save(build_state_from_agent(source), source.name, 1)

    restored = DigitalBeing(name="LexiconRestarted")
    restored.load_state(checkpoint)

    assert (
        restored.associative_lexicon.recall("огонь тихий", cycle=2, profile_id=owner)[
            0
        ]["target_id"]
        == ACT_SOCIAL
    )
    assert (
        restored.associative_lexicon.recall("общий свет", cycle=2, profile_id=owner)[0][
            "scope"
        ]
        == "shared"
    )


def test_corrupted_nested_lexicon_is_rejected_before_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    source = DigitalBeing(name="LexiconCorruption")
    owner = source.social_registry.owner_profile_id
    source.associative_lexicon.observe_act(
        "личный оборот", ACT_SOCIAL, cycle=1, profile_id=owner
    )
    state = build_state_from_agent(source)
    state["energy"] = 1.0
    state["social_attribution"]["states"][owner]["associative_lexicon"]["records"][0][
        "confidence"
    ] = 2.0
    restored = DigitalBeing(name="LexiconCorruptionRestored")
    before = build_state_from_agent(restored)

    with pytest.raises(ValueError, match="confidence"):
        apply_state_to_agent(restored, state)

    after = build_state_from_agent(restored)
    after.pop("saved_at")
    before.pop("saved_at")
    assert after == before


def test_invalid_snapshot_does_not_partially_replace_live_lexicon():
    lexicon = AssociativeLexicon()
    lexicon.observe_act("старая связь", ACT_SOCIAL, cycle=1, profile_id="owner")
    before = lexicon.to_personal_dict()
    corrupted = deepcopy(before)
    corrupted["records"][0]["scope"] = "shared"

    with pytest.raises(ValueError, match="expected personal"):
        lexicon.load_personal_from(corrupted)

    assert lexicon.to_personal_dict() == before


def test_stage_3_profile_without_lexicon_restores_with_empty_default(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    source = DigitalBeing(name="LexiconStage3")
    owner = source.social_registry.owner_profile_id
    source.dialogue_learning.learned["старый маркер"] = {
        "act": ACT_SOCIAL,
        "cycle": 1,
    }
    state = build_state_from_agent(source)
    state["social_attribution"]["states"][owner].pop("associative_lexicon")

    restored = DigitalBeing(name="LexiconStage3Restored")
    apply_state_to_agent(restored, state)

    assert restored.dialogue_learning.learned["старый маркер"]["act"] == ACT_SOCIAL
    assert restored.associative_lexicon.to_personal_dict()["records"] == []
    assert (
        restored.social_attribution.states[owner]["associative_lexicon"]["records"]
        == []
    )
