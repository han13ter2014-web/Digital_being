"""P1: векторный разбор свидетельств о состоянии человека."""

import pytest

from src.core.dialogue_acts import (
    ACT_ANSWER,
    ACT_ASK_ABOUT_SELF,
    ACT_HUMAN_AFFECT,
    ACT_REQUEST,
    ACT_SOCIAL,
    classify_user_text,
)
from src.core.human_affect import (
    AFFECT_HARD_TTL_CYCLES,
    AFFECT_HALF_LIFE_CYCLES,
    attachment_testimony_weight,
    extract_affect_teaching,
    extract_static_human_affect,
    restore_affect,
    restore_learned_affect,
    shared_affect_components,
)
from src.core.subsystems.attachment_system import AttachmentSystem
from src.perception.user_interaction import UserInteraction


@pytest.mark.parametrize(
    "text,component",
    [
        ("Мне радостно", "joy"),
        ("Я рад", "joy"),
        ("Я рада", "joy"),
        ("Я счастлив", "joy"),
        ("Я счастлива", "joy"),
        ("Мне грустно", "sadness"),
        ("Я грущу", "sadness"),
        ("Мне спокойно", "calm"),
        ("Я спокоен", "calm"),
        ("Я спокойна", "calm"),
        ("Мне тревожно", "anxiety"),
        ("Я тревожусь", "anxiety"),
        ("Мне радостно, потому что ты рядом", "joy"),
    ],
)
def test_static_self_reports_have_one_explicit_component(text, component):
    act = classify_user_text(text, cycle=12, testimony_weight=0.6)
    assert act.kind == ACT_HUMAN_AFFECT
    assert act.affect["components"] == {component: 0.7}
    assert act.affect["evidence"] == "self_report"
    assert act.affect["testimony_weight"] == 0.6
    assert act.affect["cycle"] == 12


def test_mixed_contrast_preserves_both_components():
    affect = extract_static_human_affect(
        "Мне немного грустно, но я рад, что ты рядом", cycle=20
    )
    assert affect["components"] == {"sadness": 0.35, "joy": 0.7}


def test_negation_is_local_to_its_clause():
    affect = extract_static_human_affect("Я не грущу, но мне тревожно")
    assert affect["components"] == {"anxiety": 0.7}


@pytest.mark.parametrize(
    "text,value",
    [
        ("Мне немного грустно", 0.35),
        ("Мне чуть-чуть грустно", 0.35),
        ("Мне слегка грустно", 0.35),
        ("Мне очень грустно", 0.875),
        ("Мне сильно грустно", 0.875),
        ("Мне крайне грустно", 0.875),
    ],
)
def test_modifiers_scale_activation(text, value):
    assert extract_static_human_affect(text)["components"] == {"sadness": value}


@pytest.mark.parametrize(
    "text",
    [
        "Мне не грустно",
        "Я не грущу",
        "Я не рад",
        "Тебе грустно?",
        "А тебе радостно?",
        "Он сказал: “мне грустно”",
        "Ей грустно",
        "Мне очень немного грустно",
        "Мне немного очень грустно",
    ],
)
def test_unclear_or_non_self_reports_do_not_create_affect(text):
    assert extract_static_human_affect(text) is None
    assert classify_user_text(text).kind != ACT_HUMAN_AFFECT


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Мой ответ: мне радостно", ACT_ANSWER),
        ("Как ты себя чувствуешь, мне радостно?", ACT_ASK_ABOUT_SELF),
        ("Нарисуй кота, мне радостно", ACT_REQUEST),
    ],
)
def test_older_static_acts_keep_priority(text, kind):
    assert classify_user_text(text).kind == kind


def test_learned_affect_is_exact_testimony_not_fuzzy_fact():
    learned = {
        "на душе светло": {
            "components": {"joy": 1.0},
            "weight": 0.7,
            "evidence": "user_taught",
            "cycle": 8,
        }
    }
    act = classify_user_text(
        "На душе светло!", learned_affect=learned, cycle=9, testimony_weight=1.0
    )
    assert act.kind == ACT_HUMAN_AFFECT
    assert act.affect["components"] == {"joy": 0.7}
    assert act.affect["evidence"] == "user_taught"
    assert act.affect["testimony_weight"] == 1.0
    for text in (
        "на душе очень светло",
        "рассказ про то, как на душе светло",
        "на душе не светло",
        "он сказал: “на душе светло”",
        "на душе светло?",
    ):
        assert classify_user_text(text, learned_affect=learned).kind != ACT_HUMAN_AFFECT


def test_static_affect_wins_over_learned_and_general_markers():
    learned_affect = {
        "мне радостно": {
            "components": {"sadness": 1.0},
            "weight": 1.0,
            "evidence": "user_taught",
            "cycle": 1,
        }
    }
    act = classify_user_text(
        "Мне радостно",
        learned={"мне радостно": ACT_SOCIAL},
        learned_affect=learned_affect,
    )
    assert act.affect["components"] == {"joy": 0.7}


def test_trust_and_intimacy_change_weight_not_epistemic_status():
    attachment = AttachmentSystem()
    user = attachment.get_or_create("user")
    user.trust = 0.0
    user.intimacy = 0.0
    low = attachment_testimony_weight(attachment)
    user.trust = 1.0
    user.intimacy = 1.0
    high = attachment_testimony_weight(attachment)
    assert low == 0.2
    assert high == 1.0
    affect = extract_static_human_affect("Мне радостно", testimony_weight=high)
    assert affect["evidence"] == "self_report"
    assert attachment_testimony_weight(None) == 0.5


def test_decay_threshold_and_hard_ttl():
    interaction = UserInteraction()
    affect = extract_static_human_affect("Мне грустно", cycle=100)
    interaction.set_human_affect(affect)
    assert interaction.negative_affect_strength(100) == pytest.approx(0.35)
    assert interaction.can_ask_question(100) is False
    half = 100 + AFFECT_HALF_LIFE_CYCLES
    assert interaction.human_affect_at(half)["components"]["sadness"] == pytest.approx(
        0.35
    )
    assert interaction.negative_affect_strength(half) == pytest.approx(0.175)
    interaction.last_question_cycle = -50
    assert interaction.can_ask_question(half) is True
    assert interaction.human_affect_at(100 + AFFECT_HARD_TTL_CYCLES) is not None
    assert interaction.human_affect_at(101 + AFFECT_HARD_TTL_CYCLES) is None
    assert interaction.human_affect_at(99) is None


def test_weak_negative_weight_can_stay_below_behavioral_threshold():
    interaction = UserInteraction()
    interaction.set_human_affect(
        extract_static_human_affect("Мне немного грустно", cycle=10)
    )
    assert interaction.negative_affect_strength(10) == pytest.approx(0.175)
    assert interaction.can_ask_question(10) is True
    interaction.set_human_affect(
        extract_static_human_affect(
            "Мне немного грустно", cycle=10, testimony_weight=1.0
        )
    )
    assert interaction.negative_affect_strength(10) == pytest.approx(0.35)
    assert interaction.can_ask_question(10) is False
    # Явно инициированное человеком подтверждение не блокируется аффектом.
    assert interaction.can_ask_question(10, respect_affect=False) is True


def test_positive_affect_does_not_block_questions():
    interaction = UserInteraction()
    interaction.set_human_affect(extract_static_human_affect("Мне радостно", cycle=1))
    assert interaction.negative_affect_strength(1) == 0.0
    assert interaction.can_ask_question(1) is True


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), 10**1000, 0.0, 1.1])
def test_restore_rejects_bad_weights_without_overflow(bad):
    base = {
        "components": {"joy": 0.7},
        "evidence": "self_report",
        "testimony_weight": 0.5,
        "cycle": 1,
    }
    assert restore_affect(dict(base, testimony_weight=bad)) is None
    learned = {
        "components": {"joy": 1.0},
        "weight": 0.7,
        "evidence": "user_taught",
        "cycle": 1,
    }
    assert restore_learned_affect(dict(learned, weight=bad)) is None


@pytest.mark.parametrize(
    "components",
    [
        {"unknown": 0.7},
        {"joy": True},
        {"joy": float("nan")},
        {"joy": -0.1},
        {"joy": 1.1},
        {},
    ],
)
def test_restore_rejects_bad_components(components):
    assert (
        restore_affect(
            {
                "components": components,
                "evidence": "self_report",
                "testimony_weight": 0.5,
                "cycle": 1,
            }
        )
        is None
    )


def test_teaching_requires_explicit_supported_association():
    assert extract_affect_teaching("Запомни: “на душе светло” — это радость") == {
        "phrase": "на душе светло",
        "component": "joy",
    }
    assert extract_affect_teaching(
        "Это я так говорю, когда мне радостно", default_phrase="на душе светло"
    ) == {"phrase": "на душе светло", "component": "joy"}
    assert extract_affect_teaching("Мне радостно") is None
    assert extract_affect_teaching("Запомни: “свет” — это восторг") is None


def test_shared_guard_uses_only_latest_fresh_agent_act():
    affect = extract_static_human_affect("И мне радостно", cycle=20)
    matching = {
        "cycle": 19,
        "user_text": "",
        "agent_text": "Мне радостно.",
        "attention": 1.0,
    }
    assert shared_affect_components(affect, [matching]) == ["joy"]
    unrelated = dict(matching, agent_text="Я записала новую связь.")
    assert shared_affect_components(affect, [unrelated, matching]) == []
    assert shared_affect_components(affect, [dict(matching, user_text="Привет")]) == []
    assert shared_affect_components(affect, [dict(matching, cycle=-31)]) == []
    plain = extract_static_human_affect("Мне радостно", cycle=20)
    assert shared_affect_components(plain, [matching]) == []
