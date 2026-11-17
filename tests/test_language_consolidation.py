"""Этап 6: консолидация языкового опыта без нового обучения во сне."""

from copy import deepcopy

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import (
    CheckpointSerializer,
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.dialogue_acts import ACT_ANSWER
from src.core.response_experience import (
    CONSOLIDATED_RESPONSE_HISTORY,
    RESPONSE_TTL_CYCLES,
)
from src.core.speech_imitation import USE_COOLDOWN_CYCLES


def _agent(name="LanguageSleep"):
    return DigitalBeing(name=name)


def _associate(agent, expression, *, cycle=0, source="observed_act", confirmed=False):
    profile_id = agent.social_registry.current_profile_id
    return agent.associative_lexicon.associate(
        expression,
        "act",
        "social",
        cycle=cycle,
        profile_id=profile_id,
        source=source,
        confirmed=confirmed,
    )


def _deliver(agent, response_id, *, cycle=0, borrow_context=""):
    agent.cycle_count = cycle
    prepared = agent.response_experience.prepare_plan(
        agent,
        "Ответ из существующего состояния.",
        context="social_reply",
        source="test",
        borrow_context=borrow_context,
    )
    agent.response_experience.register_delivery(response_id, prepared["plan"], cycle)


def _make_situational(agent, expression="доброе утро"):
    profile_id = agent.social_registry.current_profile_id
    for cycle in (1, 2):
        agent.response_experience.imitation.observe(
            expression,
            context="greeting",
            profile_id=profile_id,
            cycle=cycle,
        )


def test_sleep_decays_noise_but_preserves_confirmed_provenance():
    agent = _agent("SleepProvenance")
    _associate(agent, "неподтверждённый шум")
    confirmed = _associate(
        agent,
        "подтверждённая связь",
        source="user_taught",
        confirmed=True,
    )

    report = agent.sleep_cycle.sleep(200)["language"]

    assert report["forgotten_associations"] == 1
    assert agent.associative_lexicon.to_personal_dict()["records"] == [confirmed]
    assert agent.associative_lexicon.to_shared_dict()["records"] == []


def test_sleep_does_not_generalize_personal_rule_or_create_new_evidence():
    agent = _agent("SleepNoGeneralization")
    record = _associate(
        agent,
        "личное правило",
        source="user_taught",
        confirmed=True,
    )

    first = agent.sleep_cycle.sleep(100)["language"]
    before_repeat = agent.social_attribution.to_dict()
    second = agent.sleep_cycle.sleep(100)["language"]

    assert first["forgotten_associations"] == 0
    assert second["forgotten_associations"] == 0
    assert agent.associative_lexicon.to_personal_dict()["records"] == [record]
    assert agent.associative_lexicon.to_shared_dict()["records"] == []
    assert agent.social_attribution.to_dict() == before_repeat


def test_sleep_expires_pending_as_no_observed_reaction_not_support():
    agent = _agent("SleepPending")
    _deliver(agent, "pending", cycle=0)

    report = agent.sleep_cycle.sleep(RESPONSE_TTL_CYCLES + 1)["language"]
    record = agent.response_experience.responses["pending"]

    assert report["expired_responses"] == 1
    assert record["status"] == "expired"
    assert record["outcome"] == "no_observed_reaction"
    assert (
        agent.response_experience.observe_feedback(
            "pending", "support", RESPONSE_TTL_CYCLES + 2
        )
        is None
    )


def test_sleep_cleans_stale_borrowing_link_without_counting_success():
    agent = _agent("SleepBorrowingLink")
    _make_situational(agent)
    _deliver(agent, "shown", cycle=3, borrow_context="greeting")
    agent.response_experience.observe_reply(ACT_ANSWER, 4)
    assert agent.response_experience.imitation.response_links == {
        "shown": "доброе утро"
    }

    report = agent.response_experience.consolidate(4)
    record = agent.response_experience.imitation.expressions[
        ("доброе утро", "greeting", agent.social_registry.owner_profile_id)
    ]

    assert report["stale_response_links"] == 1
    assert agent.response_experience.imitation.response_links == {}
    assert record["successful_uses"] == 0
    assert record["level"] == "situational"


def test_sleep_bounds_terminal_responses_and_retains_pending():
    agent = _agent("SleepResponseWindow")
    for index in range(CONSOLIDATED_RESPONSE_HISTORY + 8):
        response_id = f"terminal-{index}"
        _deliver(agent, response_id, cycle=index)
        agent.response_experience.observe_reply(ACT_ANSWER, index)
    _deliver(agent, "still-pending", cycle=40)

    report = agent.response_experience.consolidate(40)

    assert report["pruned_responses"] == 8
    assert len(agent.response_experience.responses) == CONSOLIDATED_RESPONSE_HISTORY + 1
    assert "terminal-0" not in agent.response_experience.responses
    assert "terminal-7" not in agent.response_experience.responses
    assert "terminal-8" in agent.response_experience.responses
    assert agent.response_experience.responses["still-pending"]["status"] == "pending"
    assert agent.response_experience.latest_response_id == "still-pending"


def test_sleep_consolidates_inactive_profiles_without_switching_or_choice_changes():
    agent = _agent("SleepProfiles")
    owner = agent.social_registry.owner_profile_id
    _associate(agent, "шум владельца")
    _deliver(agent, "owner-pending", cycle=0)
    guest = agent.social_registry.create_local_person("Миша", cycle=1)
    assert agent.social_attribution.sync_active_profile() is True
    _associate(agent, "шум гостя", cycle=1)
    active_goal = deepcopy(agent.active_goal)

    report = agent.sleep_cycle.sleep(200)["language"]
    owner_state = agent.social_attribution.states[owner]

    assert report["profiles"] == 2
    assert report["forgotten_associations"] == 2
    assert report["expired_responses"] == 1
    assert agent.social_registry.current_profile_id == guest
    assert agent.social_attribution.active_profile_id == guest
    assert owner_state["associative_lexicon"]["records"] == []
    assert owner_state["response_experience"]["responses"][0]["outcome"] == (
        "no_observed_reaction"
    )
    assert agent.associative_lexicon.to_personal_dict()["records"] == []
    assert agent.active_goal == active_goal


def test_rejected_expression_survives_sleep_and_cannot_be_reactivated_by_repetition():
    agent = _agent("SleepRejected")
    _make_situational(agent, "привет")
    owner = agent.social_registry.owner_profile_id
    _deliver(agent, "rejected", cycle=3, borrow_context="greeting")
    agent.response_experience.observe_feedback("rejected", "opposition", 4)

    agent.sleep_cycle.sleep(100)
    for cycle in (101, 102):
        agent.response_experience.imitation.observe(
            "привет", context="greeting", profile_id=owner, cycle=cycle
        )

    record = agent.response_experience.imitation.expressions[
        ("привет", "greeting", owner)
    ]
    assert record["status"] == "rejected"
    assert record["level"] == "situational"
    assert record["successful_uses"] == 0
    assert (
        agent.response_experience.imitation.candidate(
            context="greeting", profile_id=owner, cycle=1000
        )
        is None
    )


def test_repeated_sleep_cannot_turn_observations_into_habit():
    agent = _agent("SleepNoRumination")
    _make_situational(agent)
    owner = agent.social_registry.owner_profile_id

    for cycle in (100, 200, 300):
        agent.sleep_cycle.sleep(cycle)

    record = agent.response_experience.imitation.expressions[
        ("доброе утро", "greeting", owner)
    ]
    assert record["observations"] == 2
    assert record["uses"] == 0
    assert record["successful_uses"] == 0
    assert record["level"] == "situational"
    assert len(record["provenance"]) == 2


def test_consolidation_is_identical_after_file_restart(tmp_path):
    source = _agent("SleepRestart")
    _associate(source, "шум владельца")
    _deliver(source, "owner-pending", cycle=0)
    guest = source.social_registry.create_local_person("Миша", cycle=1)
    assert source.social_attribution.sync_active_profile() is True
    _associate(source, "подтверждённая связь гостя", cycle=1, source="user_taught")
    serializer = CheckpointSerializer(checkpoint_dir=str(tmp_path))
    path = serializer.save(build_state_from_agent(source), source.name, 1)
    restored = _agent("SleepRestarted")
    apply_state_to_agent(restored, serializer.load(path))

    source_report = source.sleep_cycle.sleep(200)["language"]
    restored_report = restored.sleep_cycle.sleep(200)["language"]

    assert restored_report == source_report
    assert restored.social_attribution.to_dict() == source.social_attribution.to_dict()
    assert (
        restored.response_experience.to_dict() == source.response_experience.to_dict()
    )
    assert restored.associative_lexicon.to_shared_dict() == (
        source.associative_lexicon.to_shared_dict()
    )
    assert restored.social_registry.current_profile_id == guest


def test_habit_requires_real_feedback_even_with_many_sleep_cycles():
    agent = _agent("SleepHabitBoundary")
    _make_situational(agent)
    owner = agent.social_registry.owner_profile_id
    _deliver(agent, "shown", cycle=3, borrow_context="greeting")
    agent.response_experience.observe_feedback("shown", "support", 4)

    for cycle in range(100, 1000, 100):
        agent.sleep_cycle.sleep(cycle)

    record = agent.response_experience.imitation.expressions[
        ("доброе утро", "greeting", owner)
    ]
    assert record["successful_uses"] == 1
    assert record["level"] == "situational"
    next_use = 3 + USE_COOLDOWN_CYCLES
    assert (
        agent.response_experience.imitation.candidate(
            context="greeting", profile_id=owner, cycle=next_use
        )
        is not None
    )
