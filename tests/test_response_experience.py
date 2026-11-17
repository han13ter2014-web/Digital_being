"""Этап 5: план ответа, наблюдаемый результат и социальное подражание."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import (
    CheckpointSerializer,
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.dialogue_acts import (
    ACT_FOLLOW_UP,
    ACT_SOCIAL,
    DialogueAct,
    social_reply_kind,
)
from src.core.event_bus import Events
from src.core.life_systems_bridge import observe_user_message
from src.core.response_experience import (
    RESPONSE_TTL_CYCLES,
    ResponseExperience,
    parse_generic_feedback,
)
from src.core.speech_imitation import USE_COOLDOWN_CYCLES, SpeechImitation


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))

    async def publish(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


def _agent(name="ResponseExperience"):
    return DigitalBeing(name=name)


def _make_runner(name="ResponseRunner"):
    agent = _agent(name)
    bus = RecordingBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    return agent, runner, bus


def _prepare(experience, agent, response_id=None, *, borrow_context=""):
    prepared = experience.prepare_plan(
        agent,
        "Привет. Рада тебя слышать.",
        context="social_reply",
        source="test",
        user_text="Привет",
        borrow_context=borrow_context,
    )
    if response_id is not None:
        experience.register_delivery(response_id, prepared["plan"], agent.cycle_count)
    return prepared


def _make_situational(
    experience, profile_id, expression="доброе утро", context="greeting"
):
    assert (
        experience.imitation.observe(
            expression, context=context, profile_id=profile_id, cycle=1
        )["level"]
        == "recognized"
    )
    assert (
        experience.imitation.observe(
            expression, context=context, profile_id=profile_id, cycle=2
        )["level"]
        == "situational"
    )


def _switch(agent, profile_id, cycle):
    agent.social_registry.switch_to(profile_id, cycle=cycle)
    assert agent.social_attribution.sync_active_profile() is True


def test_plan_verifies_real_state_concept_episode_and_affect_references():
    agent = _agent("ResponseReferences")
    agent.cycle_count = 4
    concept = next(iter(agent.mental_models.concepts))
    episode = agent.long_term_memory.store("Реальный разговор", memory_type="episodic")
    agent.emotional_state.levels["joy"] = 0.5
    references = [
        {"kind": "state", "id": "name"},
        {"kind": "state", "id": "cycle_count"},
        {"kind": "state", "id": "active_profile"},
        {"kind": "concept", "id": concept},
        {"kind": "episode", "id": episode},
        {"kind": "affect", "id": "joy"},
    ]

    prepared = agent.response_experience.prepare_plan(
        agent,
        "Ответ из существующего состояния.",
        context="about_self",
        source="test",
        references=references,
    )

    assert prepared["plan"]["references"] == references
    assert prepared["plan"]["state"]["cycle"] == 4
    assert prepared["plan"]["provenance_verified"] is True
    assert agent.response_experience.responses == {}


@pytest.mark.parametrize(
    "reference",
    [
        {"kind": "state", "id": "imagined"},
        {"kind": "concept", "id": "несуществующее понятие"},
        {"kind": "episode", "id": "mem_missing"},
        {"kind": "affect", "id": "joy"},
    ],
)
def test_missing_reference_is_rejected_before_registration(reference):
    agent = _agent("ResponseMissingReference")
    with pytest.raises(ValueError, match="reference"):
        agent.response_experience.prepare_plan(
            agent,
            "Не отправлять.",
            context="about_self",
            source="test",
            references=[reference],
        )
    assert agent.response_experience.responses == {}


@pytest.mark.asyncio
async def test_runner_checks_reference_before_voice_webhook_and_ui():
    agent, runner, bus = _make_runner("ResponseAtomicPlan")
    delivered = []
    agent.voice_router = SimpleNamespace(speak=delivered.append)
    agent.webhooks = SimpleNamespace(
        send=lambda *args, **kwargs: delivered.append(args)
    )

    with pytest.raises(ValueError, match="real concept"):
        await runner._reply_to_user(
            "Не отправлять.",
            context="about_self",
            source="test",
            response_references=[{"kind": "concept", "id": "выдумка"}],
        )

    assert delivered == []
    assert bus.published == []
    assert agent.response_experience.responses == {}


@pytest.mark.asyncio
async def test_pending_is_created_only_after_actual_message_id():
    agent, runner, _ = _make_runner("ResponseDelivery")

    message_id = await runner._reply_to_user(
        "Доставленный ответ.", context="social_reply", source="test"
    )

    assert isinstance(message_id, str) and message_id
    assert agent.response_experience.responses[message_id]["status"] == "pending"

    agent.user_interaction = None
    agent.cycle_count += 1
    assert (
        await runner._reply_to_user(
            "Только мысль.", context="social_reply", source="test"
        )
        is None
    )
    assert len(agent.response_experience.responses) == 1


def test_reply_feedback_and_expiry_are_distinct_observed_outcomes():
    agent = _agent("ResponseOutcomes")
    experience = agent.response_experience
    _prepare(experience, agent, "reply")
    assert experience.observe_reply(ACT_FOLLOW_UP, 0)["outcome"] == "follow_up"

    _prepare(experience, agent, "support")
    assert experience.observe_feedback("support", "support", 0)["outcome"] == (
        "explicit_support"
    )

    _prepare(experience, agent, "opposition")
    assert experience.observe_feedback("opposition", "opposition", 0)["outcome"] == (
        "explicit_opposition"
    )

    _prepare(experience, agent, "silent")
    assert experience.expire(RESPONSE_TTL_CYCLES + 1) == 1
    assert experience.responses["silent"]["status"] == "expired"
    assert experience.responses["silent"]["outcome"] == "no_observed_reaction"
    assert (
        experience.observe_feedback("silent", "support", RESPONSE_TTL_CYCLES + 2)
        is None
    )


def test_recognized_then_situational_then_habit_requires_shown_supported_answers():
    agent = _agent("ResponseHabit")
    experience = agent.response_experience
    profile_id = agent.social_registry.current_profile_id
    _make_situational(experience, profile_id)
    assert (
        experience.imitation.candidate(
            context="greeting", profile_id=profile_id, cycle=2
        )["level"]
        == "situational"
    )

    agent.cycle_count = 3
    first = _prepare(experience, agent, "first", borrow_context="greeting")
    assert first["text"].startswith("Доброе утро. ")
    assert experience.imitation.response_links == {"first": "доброе утро"}
    experience.observe_feedback("first", "support", 4)
    record = experience.imitation.expressions[("доброе утро", "greeting", profile_id)]
    assert record["level"] == "situational"
    assert record["successful_uses"] == 1

    agent.cycle_count = 3 + USE_COOLDOWN_CYCLES
    second = _prepare(experience, agent, "second", borrow_context="greeting")
    assert second["plan"]["borrowed"]["expression"] == "доброе утро"
    experience.observe_feedback("second", "support", agent.cycle_count + 1)
    assert record["level"] == "habit"
    assert record["successful_uses"] == 2


def test_recognized_expression_is_never_used_and_opposition_rejects_it():
    imitation = SpeechImitation()
    imitation.observe("Привет", context="greeting", profile_id="owner", cycle=1)
    assert imitation.candidate(context="greeting", profile_id="owner", cycle=1) is None

    imitation.observe("Привет", context="greeting", profile_id="owner", cycle=2)
    imitation.mark_used(
        "привет",
        context="greeting",
        profile_id="owner",
        response_id="shown",
        cycle=3,
    )
    imitation.apply_feedback("shown", "opposition", profile_id="owner", cycle=4)
    assert (
        imitation.expressions[("привет", "greeting", "owner")]["status"] == "rejected"
    )
    assert (
        imitation.candidate(context="greeting", profile_id="owner", cycle=100) is None
    )


def test_explicit_reject_revokes_expression():
    imitation = SpeechImitation()
    imitation.observe("Молодец", context="other", profile_id="owner", cycle=1)
    imitation.observe("Молодец", context="other", profile_id="owner", cycle=2)
    assert imitation.reject("молодец", context="other", profile_id="owner", cycle=3)
    assert imitation.candidate(context="other", profile_id="owner", cycle=100) is None
    assert (
        imitation.reject("отсутствует", context="other", profile_id="owner", cycle=3)
        is False
    )


@pytest.mark.parametrize(
    "text",
    [
        "я рядом",
        "ты рядом",
        "я люблю тебя",
        "горжусь тобой",
        "скучаю",
        "солнце светит",
        "мой ответ привет",
        "не переживай 123",
    ],
)
def test_facts_personal_claims_and_unsafe_formulas_are_not_borrowed(text):
    imitation = SpeechImitation()
    context = social_reply_kind(text)
    assert imitation.observe(text, context=context, profile_id="owner", cycle=1) is None
    assert imitation.observe(text, context=context, profile_id="owner", cycle=2) is None
    assert imitation.expressions == {}


def test_plans_expectations_and_expressions_do_not_cross_profiles():
    agent = _agent("ResponseProfiles")
    owner = agent.social_registry.owner_profile_id
    _make_situational(agent.response_experience, owner)
    agent.cycle_count = 3
    _prepare(
        agent.response_experience, agent, "owner-response", borrow_context="greeting"
    )

    guest = agent.social_registry.create_local_person("Миша", cycle=4)
    assert agent.social_attribution.sync_active_profile() is True
    assert agent.response_experience.responses == {}
    assert agent.response_experience.imitation.expressions == {}
    assert (
        agent.response_experience.imitation.candidate(
            context="greeting", profile_id=guest, cycle=4
        )
        is None
    )

    _switch(agent, owner, 5)
    assert agent.response_experience.latest_response_id == "owner-response"
    available_cycle = 3 + USE_COOLDOWN_CYCLES
    assert (
        agent.response_experience.imitation.candidate(
            context="greeting", profile_id=owner, cycle=available_cycle
        )
        is not None
    )
    _switch(agent, guest, available_cycle + 1)
    assert agent.response_experience.responses == {}


def test_file_restart_restores_plan_pending_imitation_and_response_link(tmp_path):
    agent = _agent("ResponseRestart")
    owner = agent.social_registry.current_profile_id
    _make_situational(agent.response_experience, owner)
    agent.cycle_count = 3
    _prepare(
        agent.response_experience, agent, "restart-response", borrow_context="greeting"
    )
    serializer = CheckpointSerializer(checkpoint_dir=str(tmp_path))

    path = serializer.save(build_state_from_agent(agent), agent.name, agent.cycle_count)
    state = serializer.load(path)
    restored = _agent("ResponseRestarted")
    apply_state_to_agent(restored, state)

    assert restored.response_experience.to_dict() == state["response_experience"]
    assert (
        restored.response_experience.responses["restart-response"]["status"]
        == "pending"
    )
    assert restored.response_experience.imitation.response_links == {
        "restart-response": "доброе утро"
    }


def test_corrupted_response_checkpoint_is_rejected_before_mutation():
    agent = _agent("ResponseCorruption")
    _prepare(agent.response_experience, agent, "response")
    state = build_state_from_agent(agent)
    state["energy"] = 1.0
    state["response_experience"]["responses"][0]["plan"]["state"]["profile_id"] = (
        "other"
    )
    before = build_state_from_agent(agent)

    with pytest.raises(ValueError, match="response_experience"):
        apply_state_to_agent(agent, state)

    assert agent.energy == before["energy"]
    assert agent.response_experience.to_dict() == before["response_experience"]


def test_stage4_checkpoint_without_response_state_gets_empty_default():
    source = _agent("ResponseLegacy")
    state = build_state_from_agent(source)
    state.pop("response_experience")
    for profile_state in state["social_attribution"]["states"].values():
        profile_state.pop("response_experience")

    restored = _agent("ResponseLegacyRestored")
    apply_state_to_agent(restored, state)

    assert restored.response_experience.to_dict() == ResponseExperience().to_dict()


@pytest.mark.asyncio
async def test_social_pipeline_observes_borrows_and_accepts_exact_generic_feedback():
    agent, runner, bus = _make_runner("ResponsePipeline")
    agent.cycle_count = 1
    await runner._on_user_message(SimpleNamespace(data={"text": "Доброе утро"}))
    agent.cycle_count = 2
    await runner._on_user_message(SimpleNamespace(data={"text": "Доброе утро"}))

    replies = [data for name, data in bus.published if name == Events.AGENT_MESSAGE]
    assert replies[-1]["content"].startswith("Доброе утро. ")
    response_id = agent.response_experience.latest_response_id
    agent.cycle_count = 3
    await runner._on_user_message(SimpleNamespace(data={"text": "так лучше"}))

    assert (
        agent.response_experience.responses[response_id]["outcome"]
        == "explicit_support"
    )
    assert agent.dialogue_learning.strategy_memory.outcomes == {}


@pytest.mark.asyncio
async def test_existing_strategy_feedback_also_closes_response_expectation():
    agent, runner, _ = _make_runner("ResponseStrategyFeedback")
    _prepare(agent.response_experience, agent, "message:7")
    agent.dialogue_learning.strategy_memory.register_response(
        "message:7", "unknown_listen", "unknown", 0
    )

    await runner._on_user_message(SimpleNamespace(data={"text": "так лучше"}))

    assert (
        agent.response_experience.responses["message:7"]["outcome"]
        == "explicit_support"
    )
    assert (
        agent.dialogue_learning.strategy_memory.outcomes["unknown"]["unknown_listen"][
            "response_count"
        ]
        == 1
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("так понятно", "support"),
        ("не то", "opposition"),
        ("не то?", None),
        ("не то, продолжай", None),
        ("она сказала не то", None),
    ],
)
def test_generic_feedback_is_exact_not_inferred(text, expected):
    assert parse_generic_feedback(text) == expected


def test_social_observation_does_not_change_existing_strategy_or_core_choice():
    agent = _agent("ResponseCoreCompatibility")
    strategies_before = deepcopy(agent.dialogue_learning.strategy_memory.to_dict())
    active_goal_before = deepcopy(agent.active_goal)

    observe_user_message(agent, "Привет", DialogueAct(ACT_SOCIAL, "привет"), 1)

    assert agent.dialogue_learning.strategy_memory.to_dict() == strategies_before
    assert agent.active_goal == active_goal_before


def test_identical_history_is_deterministic():
    def history():
        registry = SimpleNamespace(current_profile_id="owner")
        agent = SimpleNamespace(cycle_count=3, social_registry=registry)
        experience = ResponseExperience()
        _make_situational(experience, "owner")
        _prepare(experience, agent, "same", borrow_context="greeting")
        experience.observe_feedback("same", "support", 4)
        return experience.to_dict()

    assert history() == history()
