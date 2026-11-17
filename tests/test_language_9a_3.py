"""9A-3: личный языковой опыт без смешивания RU/EN и профилей."""

from __future__ import annotations

import socket
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.associative_lexicon import AssociativeLexicon
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.dialogue_learning import DialogueLearning
from src.core.english_dialogue import english_feedback_realization
from src.core.language_context import LanguageContext
from src.core.response_experience import ResponseExperience
from src.core.speech_imitation import SpeechImitation


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("9A-3 must remain offline")

    monkeypatch.setattr(socket, "create_connection", blocked)


def _context(profile_id: str, language: str) -> dict:
    return LanguageContext(
        profile_id=profile_id,
        input_language=language,
        dialogue_language=language,
        response_language=language,
        source="stable_dialogue",
        confidence=None,
    ).to_dict()


def _deliver(experience, agent, response_id: str, language: str) -> None:
    profile_id = agent.social_registry.current_profile_id
    realization = english_feedback_realization() if language == "en" else None
    text = realization["text"] if realization else "Ответ текущего языка."
    prepared = experience.prepare_plan(
        agent,
        text,
        context="dialogue_feedback",
        source="language_9a_3_test",
        language_context=_context(profile_id, language),
        english_realization=realization,
    )
    experience.register_delivery(response_id, prepared["plan"], agent.cycle_count)


def test_dialogue_learning_preserves_independent_language_states_and_restart():
    learning = DialogueLearning()
    learning.resolve("личная фраза", "1", 1)
    learning.resolve_affect("тепло", "joy", "да", 1)
    learning.strategy_memory.set_preference("unknown", "unknown_listen", 1)
    learning.mark_proposed(1)

    learning.set_language("en")
    assert learning.learned == {}
    assert learning.learned_affect == {}
    assert learning.strategy_memory.preferences == {}
    assert learning.last_proposal_cycle != 1
    learning.resolve("shared surface", "1", 2)
    learning.resolve("english only", "4", 2)
    learning.strategy_memory.set_preference("unknown", "learning_question", 2)
    learning.mark_proposed(2)

    learning.set_language("ru")
    assert set(learning.learned) == {"личная фраза"}
    assert "shared surface" not in learning.learned
    assert learning.strategy_memory.preference_for("unknown")["strategy"] == (
        "unknown_listen"
    )
    assert learning.last_proposal_cycle == 1

    restored = DialogueLearning()
    restored.load_from(learning.to_dict())
    assert restored.active_language == "ru"
    restored.set_language("en")
    assert set(restored.learned) == {"shared surface"}
    assert restored.suppressed == {"english only": 2}
    assert restored.strategy_memory.preference_for("unknown")["strategy"] == (
        "learning_question"
    )
    assert restored.last_proposal_cycle == 2


def test_legacy_dialogue_learning_is_russian_and_new_snapshot_is_validated():
    legacy = DialogueLearning()
    legacy.resolve("старая фраза", "1", 3)
    snapshot = legacy.to_dict()
    for field in ("schema_version", "active_language", "language_states"):
        snapshot.pop(field, None)

    restored = DialogueLearning()
    restored.load_from(snapshot)
    assert restored.active_language == "ru"
    assert restored.learned == legacy.learned
    validate_checkpoint_state({"dialogue_learning": snapshot})


def test_associations_with_same_surface_have_independent_language_provenance():
    lexicon = AssociativeLexicon()
    lexicon.associate(
        "same surface",
        "context",
        "personal context",
        cycle=1,
        profile_id="owner",
        source="observed_act",
        language_id="ru",
    )
    lexicon.associate(
        "same surface",
        "context",
        "personal context",
        cycle=2,
        profile_id="owner",
        source="user_taught",
        language_id="en",
    )

    russian = lexicon.recall(
        "same surface", cycle=3, profile_id="owner", language_id="ru"
    )
    english = lexicon.recall(
        "same surface", cycle=3, profile_id="owner", language_id="en"
    )
    assert russian[0]["language_id"] == "ru"
    assert english[0]["language_id"] == "en"
    assert russian[0]["provenance"][0]["source"] == "observed_act"
    assert english[0]["provenance"][0]["source"] == "user_taught"
    assert russian[0]["confidence"] != english[0]["confidence"]
    assert len(lexicon.to_personal_dict()["records"]) == 2


def test_legacy_association_snapshot_defaults_to_russian_atomically():
    current = AssociativeLexicon()
    current.associate(
        "старое выражение",
        "act",
        "social",
        cycle=1,
        profile_id="owner",
    )
    legacy = current.to_personal_dict()
    legacy["schema_version"] = 1
    for record in legacy["records"]:
        record.pop("language_id", None)

    restored = AssociativeLexicon()
    restored.load_personal_from(legacy)
    assert restored.recall("старое выражение", cycle=2, profile_id="owner")
    assert not restored.recall(
        "старое выражение", cycle=2, profile_id="owner", language_id="en"
    )

    corrupted = deepcopy(legacy)
    corrupted["schema_version"] = 2
    before = restored.to_personal_dict()
    with pytest.raises(ValueError, match="language_id"):
        restored.load_personal_from(corrupted)
    assert restored.to_personal_dict() == before


def test_imitation_candidates_links_and_feedback_do_not_cross_languages():
    imitation = SpeechImitation()
    for language in ("ru", "en"):
        expression = "доброе утро" if language == "ru" else "hello"
        for cycle in (1, 2):
            imitation.observe(
                expression,
                context="greeting",
                profile_id="owner",
                cycle=cycle,
                language_id=language,
            )
        imitation.mark_used(
            expression,
            context="greeting",
            profile_id="owner",
            response_id=f"shown:{language}",
            cycle=3,
            language_id=language,
        )

    imitation.apply_feedback(
        "shown:en", "support", profile_id="owner", cycle=4, language_id="en"
    )
    russian = imitation.expressions[("доброе утро", "greeting", "owner")]
    english = imitation.expressions[("hello", "greeting", "owner", "en")]
    assert russian["successful_uses"] == 0
    assert english["successful_uses"] == 1
    assert (
        imitation.candidate(
            context="greeting", profile_id="owner", cycle=30, language_id="ru"
        )["language_id"]
        == "ru"
    )


def test_legacy_imitation_snapshot_is_russian():
    legacy = SpeechImitation()
    for cycle in (1, 2):
        legacy.observe("привет", context="greeting", profile_id="owner", cycle=cycle)
    snapshot = legacy.to_dict()
    snapshot["schema_version"] = 1
    for record in snapshot["expressions"]:
        record.pop("language_id", None)

    restored = SpeechImitation()
    restored.load_from(snapshot)
    assert restored.candidate(context="greeting", profile_id="owner", cycle=3)
    assert (
        restored.candidate(
            context="greeting", profile_id="owner", cycle=3, language_id="en"
        )
        is None
    )


def test_reply_and_feedback_select_pending_of_current_language_ru_en_ru():
    agent = DigitalBeing(name="LanguagePending9A3")
    experience = agent.response_experience
    _deliver(experience, agent, "ru-first", "ru")
    _deliver(experience, agent, "en-second", "en")

    assert experience.observe_reply("unknown", 0, language_id="en")["response_id"] == (
        "en-second"
    )
    assert experience.responses["ru-first"]["status"] == "pending"
    assert experience.observe_reply("unknown", 0, language_id="ru")["response_id"] == (
        "ru-first"
    )

    _deliver(experience, agent, "ru-third", "ru")
    _deliver(experience, agent, "en-fourth", "en")
    assert (
        experience.observe_feedback("en-fourth", "support", 0, language_id="en")[
            "outcome"
        ]
        == "explicit_support"
    )
    assert (
        experience.observe_feedback("en-fourth", "opposition", 0, language_id="ru")
        is None
    )
    assert experience.responses["ru-third"]["status"] == "pending"


def test_response_pending_and_borrowing_remain_profile_scoped_after_restart():
    source = DigitalBeing(name="LanguageProfiles9A3")
    owner = source.social_registry.owner_profile_id
    _deliver(source.response_experience, source, "owner-ru", "ru")
    source.social_registry.create_local_person("Миша", cycle=1)
    assert source.social_attribution.sync_active_profile()
    _deliver(source.response_experience, source, "guest-en", "en")

    state = build_state_from_agent(source)
    restored = DigitalBeing(name="LanguageProfiles9A3Restored")
    apply_state_to_agent(restored, state)
    assert set(restored.response_experience.responses) == {"guest-en"}
    assert (
        restored.response_experience.observe_feedback(
            "owner-ru", "support", 1, language_id="ru"
        )
        is None
    )

    restored.social_registry.switch_to(owner, cycle=2)
    assert restored.social_attribution.sync_active_profile()
    assert (
        restored.response_experience.observe_feedback(
            "owner-ru", "support", 2, language_id="ru"
        )["outcome"]
        == "explicit_support"
    )


def test_checkpoint_rejects_bad_inactive_language_before_agent_mutation():
    agent = DigitalBeing(name="LanguageTamper9A3")
    agent.dialogue_learning.set_language("en")
    agent.dialogue_learning.resolve("english marker", "1", 1)
    agent.dialogue_learning.set_language("ru")
    state = build_state_from_agent(agent)
    state["energy"] = 1.0
    state["dialogue_learning"]["language_states"]["en"]["learned"]["bad"] = {
        "act": "answer",
        "cycle": 1,
    }
    before = build_state_from_agent(agent)

    with pytest.raises(ValueError, match="language_states.*learnable act"):
        apply_state_to_agent(agent, state)
    assert agent.energy == before["energy"]
    assert agent.dialogue_learning.to_dict() == before["dialogue_learning"]


def test_sleep_consolidates_both_languages_without_generalization_or_new_habit():
    agent = DigitalBeing(name="LanguageSleep9A3")
    owner = agent.social_registry.owner_profile_id
    for language, expression in (("ru", "русский шум"), ("en", "english noise")):
        agent.associative_lexicon.associate(
            expression,
            "act",
            "social",
            cycle=0,
            profile_id=owner,
            source="observed_act",
            language_id=language,
        )
    for cycle in (1, 2):
        agent.response_experience.imitation.observe(
            "hello",
            context="greeting",
            profile_id=owner,
            cycle=cycle,
            language_id="en",
        )

    first = agent.sleep_cycle.sleep(200)["language"]
    before_repeat = agent.social_attribution.to_dict()
    second = agent.sleep_cycle.sleep(200)["language"]

    assert first["forgotten_associations"] == 2
    assert second["forgotten_associations"] == 0
    assert agent.associative_lexicon.to_shared_dict()["records"] == []
    assert agent.social_attribution.to_dict() == before_repeat
    record = agent.response_experience.imitation.expressions[
        ("hello", "greeting", owner, "en")
    ]
    assert record["observations"] == 2
    assert record["successful_uses"] == 0
    assert record["level"] == "situational"


def test_response_experience_rejects_cross_language_borrowed_plan():
    experience = ResponseExperience()
    data = experience.to_dict()
    data["imitation"]["expressions"] = [
        {
            "expression": "hello",
            "context": "greeting",
            "profile_id": "owner",
            "language_id": "en",
            "level": "situational",
            "status": "active",
            "observations": 2,
            "uses": 0,
            "successful_uses": 0,
            "created_cycle": 1,
            "last_observed_cycle": 2,
            "last_used_cycle": None,
            "provenance": [{"kind": "observation", "cycle": 2}],
        }
    ]
    data["imitation"]["response_links"] = {
        "response": {"expression": "hello", "language_id": "ru"}
    }

    with pytest.raises(ValueError, match="response_links"):
        experience.load_from(data)


class _Bus:
    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        pass

    async def publish(self, name, data=None, source="system", priority=1):
        pass


@pytest.mark.asyncio
async def test_english_borrowing_feedback_and_restart_follow_real_dialogue_path(
    monkeypatch,
):
    def blocked(*args, **kwargs):
        raise AssertionError("9A-3 must remain offline")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    agent = DigitalBeing(name="EnglishBorrowing9A3")
    agent.social_attribution.set_stable_dialogue_language("en")
    runner = AgentRunner(agent, _Bus())

    for cycle in (1, 2):
        agent.cycle_count = cycle
        await runner._on_user_message(SimpleNamespace(data={"text": "Hello"}))

    response_id = agent.response_experience.latest_response_id
    response = agent.response_experience.responses[response_id]
    assert response["plan"]["borrowed"]["language_id"] == "en"
    assert response["plan"]["realization"]["text"].startswith(
        "Hello. Hello. I'm glad to hear from you."
    )
    assert response["plan"]["provenance_verified"] is True

    state = build_state_from_agent(agent)
    restored = DigitalBeing(name="EnglishBorrowing9A3Restored")
    apply_state_to_agent(restored, state)
    assert (
        restored.response_experience.observe_feedback(
            response_id, "support", 3, language_id="ru"
        )
        is None
    )
    assert restored.response_experience.responses[response_id]["status"] == "pending"
    assert (
        restored.response_experience.observe_feedback(
            response_id, "support", 3, language_id="en"
        )["outcome"]
        == "explicit_support"
    )
    owner = restored.social_registry.owner_profile_id
    record = restored.response_experience.imitation.expressions[
        ("hello", "greeting", owner, "en")
    ]
    assert record["successful_uses"] == 1
    assert not any(
        item.get("language_id", "ru") == "ru"
        for item in restored.response_experience.imitation.expressions.values()
    )


def test_mixed_input_does_not_become_unambiguous_language_experience():
    from src.core.life_systems_bridge import observe_user_message

    agent = DigitalBeing(name="MixedLanguage9A3")
    owner = agent.social_registry.owner_profile_id
    agent.social_attribution.resolve_language("Привет")
    context = agent.social_attribution.resolve_language("Привет hello")
    assert context.input_language == "mixed"
    observe_user_message(
        agent, "Привет hello", SimpleNamespace(kind="social", matched_marker=""), 1
    )
    assert agent.associative_lexicon.to_personal_dict()["records"] == []
    assert agent.response_experience.imitation.expressions == {}

    agent.social_attribution.set_stable_dialogue_language("en")
    agent.social_attribution.resolve_language("Hello")
    observe_user_message(
        agent, "Hello", SimpleNamespace(kind="social", matched_marker="hello"), 2
    )
    records = agent.associative_lexicon.to_personal_dict()["records"]
    assert records and {item["language_id"] for item in records} == {"en"}
    assert ("hello", "greeting", owner, "en") in (
        agent.response_experience.imitation.expressions
    )
