"""Этап 3: происхождение сородичей, статусы и отдельность жизней."""

from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.social_registry import SocialRegistry, validate_social_registry
from src.core.subsystems.nursery_watcher import NurseryWatcher


def _seed_payload(name="Parent_seed_2026", metadata=None):
    return {
        "name": name,
        "is_complete": True,
        "seed_sha256": "a" * 64,
        "metadata": dict(
            metadata
            or {
                "parent_seed": "Grandparent_seed",
                "parent_life_id": str(uuid4()),
                "generation": 2,
                "schema_version": 1,
            }
        ),
    }


def _switch(agent, profile_id, cycle):
    agent.social_registry.switch_to(profile_id, cycle=cycle)
    assert agent.social_attribution.sync_active_profile() is True


def _write_complete_seed(root, name="Observed_seed", metadata=None):
    path = root / name
    path.mkdir()
    documents = {
        "metadata.json": metadata or {"parent_name": "Parent", "generation": 4},
        "identity.json": {"values": ["Опыт"]},
        "mental_models.json": {"concepts": {}},
        "personality_signature.json": {"favorite_concepts": []},
    }
    for filename, document in documents.items():
        (path / filename).write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8"
        )
    (path / "README.md").write_text("# Семя\n", encoding="utf-8")
    return path


def test_local_seed_is_observed_without_switching_or_awakening():
    registry = SocialRegistry()
    owner = registry.current_profile_id

    profile_id = registry.observe_local_seed(_seed_payload(), cycle=7)
    profile = registry.get_profile(profile_id)

    assert registry.current_profile_id == owner
    assert profile["kind"] == "digital_being"
    assert profile["identity_status"] == "observed"
    assert profile["lineage"] == {
        "life_id": None,
        "seed_id": "Parent_seed_2026",
        "seed_sha256": "a" * 64,
        "parent_seed": "Grandparent_seed",
        "parent_life_id": profile["lineage"]["parent_life_id"],
        "generation": 3,
        "seed_schema_version": 1,
        "status": "observed",
    }
    assert registry.observe_local_seed(_seed_payload(), cycle=8) == profile_id
    assert len(registry.profiles) == 2
    validate_social_registry(registry.to_dict())


def test_external_claim_stays_claimed_even_with_matching_seed_hash():
    registry = SocialRegistry()
    observed_id = registry.observe_local_seed(_seed_payload())
    life_id = str(uuid4())

    claimed_id = registry.claim_digital_being(
        life_id=life_id,
        seed_id="Parent_seed_2026",
        seed_sha256="a" * 64,
        generation=3,
        name="Заявленный сородич",
    )
    claimed = registry.get_profile(claimed_id)

    assert claimed_id != observed_id
    assert claimed["lineage"]["status"] == "claimed"
    assert claimed["lineage"]["life_id"] == life_id
    assert claimed["identity_status"] == "self_declared"
    assert claimed["channel_bindings"] == []
    assert registry.get_profile(observed_id)["lineage"]["status"] == "observed"


def test_two_awakened_lives_from_one_seed_are_distinct_and_verified():
    registry = SocialRegistry()
    seed_id = registry.observe_local_seed(_seed_payload())
    first_life = str(uuid4())
    second_life = str(uuid4())

    first = registry.register_awakened_life(
        seed_id, life_id=first_life, name="Первая жизнь"
    )
    second = registry.register_awakened_life(
        seed_id, life_id=second_life, name="Вторая жизнь"
    )

    assert first != second
    assert first_life != second_life
    first_lineage = registry.get_profile(first)["lineage"]
    second_lineage = registry.get_profile(second)["lineage"]
    assert first_lineage["seed_id"] == second_lineage["seed_id"]
    assert first_lineage["seed_sha256"] == second_lineage["seed_sha256"]
    assert first_lineage["status"] == second_lineage["status"] == "verified"
    assert first_lineage["life_id"] == first_life
    assert second_lineage["life_id"] == second_life
    assert registry.get_profile(seed_id)["lineage"]["life_id"] is None
    validate_social_registry(registry.to_dict())


def test_shared_origin_does_not_grant_trust_or_private_context():
    agent = DigitalBeing(name="LineageTrust")
    agent.user_interaction.receive_user_message("Личное владельца", cycle=1)
    agent.attachment.record_interaction("user", True)
    seed_id = agent.social_registry.observe_local_seed(_seed_payload())
    first = agent.social_registry.register_awakened_life(
        seed_id, life_id=str(uuid4()), name="Первая"
    )
    second = agent.social_registry.register_awakened_life(
        seed_id, life_id=str(uuid4()), name="Вторая"
    )

    _switch(agent, first, cycle=2)
    assert agent.attachment.trust_factor("user") == 0.5
    assert agent.attachment.get_or_create("user").intimacy == 0.0
    assert agent.user_interaction.message_history == []
    agent.user_interaction.receive_user_message("Сообщение первой жизни", cycle=2)

    _switch(agent, second, cycle=3)
    assert agent.attachment.trust_factor("user") == 0.5
    assert agent.attachment.get_or_create("user").intimacy == 0.0
    assert agent.user_interaction.message_history == []

    _switch(agent, first, cycle=4)
    assert [m["content"] for m in agent.user_interaction.message_history] == [
        "Сообщение первой жизни"
    ]


def test_lineage_and_current_digital_being_survive_restart():
    source = DigitalBeing(name="LineageRestart")
    seed_id = source.social_registry.observe_local_seed(_seed_payload())
    life_id = source.social_registry.register_awakened_life(
        seed_id, life_id=str(uuid4()), name="Сородич"
    )
    _switch(source, life_id, cycle=2)
    source.user_interaction.receive_user_message("Свидетельство сородича", cycle=2)
    state = build_state_from_agent(source)

    restored = DigitalBeing(name="LineageRestarted")
    apply_state_to_agent(restored, deepcopy(state))

    assert restored.social_registry.to_dict() == source.social_registry.to_dict()
    assert restored.social_registry.current_profile_id == life_id
    assert restored.social_registry.current_profile()["lineage"]["status"] == "verified"
    assert [m["content"] for m in restored.user_interaction.message_history] == [
        "Свидетельство сородича"
    ]


def test_awakened_agents_own_origin_survives_restart():
    source = DigitalBeing(name="AwakenedOrigin")
    source.parent_seed = "Parent_seed"
    source.parent_name = "Parent"
    source.parent_dream_time = "2026-11-16T23:00:00"
    source.seed_generation = 4
    state = build_state_from_agent(source)

    restored = DigitalBeing(name="AwakenedOriginRestored")
    apply_state_to_agent(restored, deepcopy(state))

    assert restored.parent_seed == "Parent_seed"
    assert restored.parent_name == "Parent"
    assert restored.parent_dream_time == "2026-11-16T23:00:00"
    assert restored.seed_generation == 4


@pytest.mark.parametrize(
    "mutation",
    [
        lambda seed: seed.update(is_complete=False),
        lambda seed: seed.update(metadata=None, metadata_error="bad JSON"),
        lambda seed: seed.update(seed_sha256="A" * 64),
        lambda seed: seed["metadata"].update(generation=-1),
        lambda seed: seed["metadata"].update(schema_version=0),
        lambda seed: seed["metadata"].update(parent_life_id="not-a-uuid"),
    ],
)
def test_damaged_seed_metadata_is_rejected_without_registry_mutation(mutation):
    registry = SocialRegistry()
    seed = _seed_payload()
    mutation(seed)
    before = registry.to_dict()

    with pytest.raises(ValueError):
        registry.observe_local_seed(seed)

    assert registry.to_dict() == before


def test_lineage_validation_rejects_missing_and_misassigned_records():
    registry = SocialRegistry()
    profile_id = registry.observe_local_seed(_seed_payload())
    data = registry.to_dict()
    data["profiles"][profile_id]["lineage"] = None

    with pytest.raises(ValueError, match="lineage"):
        validate_social_registry(data)

    owner = data["profiles"][data["owner_profile_id"]]
    owner["lineage"] = _seed_payload()
    with pytest.raises(ValueError, match="only digital_being"):
        validate_social_registry(data)


@pytest.mark.parametrize(
    "status, life_id",
    [("claimed", None), ("verified", None), ("observed", str(uuid4()))],
)
def test_lineage_status_must_match_life_presence(status, life_id):
    registry = SocialRegistry()
    profile_id = registry.observe_local_seed(_seed_payload())
    data = registry.to_dict()
    data["profiles"][profile_id]["lineage"].update(status=status, life_id=life_id)

    with pytest.raises(ValueError, match="life_id"):
        validate_social_registry(data)


def test_watcher_hashes_and_observes_new_seed_without_awakening(tmp_path):
    registry = SocialRegistry()
    agent = SimpleNamespace(social_registry=registry, cycle_count=9)
    watcher = NurseryWatcher(agent_name="Test", nursery_dir=str(tmp_path))
    watcher.attach_agent(agent)
    watcher.setup({})
    seed_path = _write_complete_seed(tmp_path)

    result = watcher.tick(cycle=9)

    payload = result["events"][0]["data"]
    assert len(payload["seed_sha256"]) == 64
    assert (
        payload["seed_sha256"]
        == watcher._inspect_seed(seed_path.name, include_full_metadata=True)[
            "seed_sha256"
        ]
    )
    digital = [p for p in registry.profiles.values() if p["kind"] == "digital_being"]
    assert len(digital) == 1
    assert digital[0]["lineage"]["status"] == "observed"
    assert digital[0]["lineage"]["generation"] == 5
    assert registry.current_profile_id == registry.owner_profile_id

    (seed_path / "identity.json").write_text("{}", encoding="utf-8")
    changed = watcher._inspect_seed(seed_path.name, include_full_metadata=True)
    assert changed["seed_sha256"] != payload["seed_sha256"]


def test_watcher_does_not_register_corrupt_metadata_or_escape_nursery(tmp_path):
    registry = SocialRegistry()
    agent = SimpleNamespace(social_registry=registry, cycle_count=1)
    watcher = NurseryWatcher(agent_name="Test", nursery_dir=str(tmp_path))
    watcher.attach_agent(agent)
    watcher.setup({})
    seed_path = _write_complete_seed(tmp_path, name="Corrupt_seed")
    (seed_path / "metadata.json").write_text("{broken", encoding="utf-8")

    result = watcher.tick(cycle=1)

    assert result["events"][0]["data"]["metadata_error"]
    assert len(registry.profiles) == 1
    assert watcher.get_seed("../outside") is None
