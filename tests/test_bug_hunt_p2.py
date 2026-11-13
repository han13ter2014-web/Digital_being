"""Регрессии оставшихся логических дефектов глобального багхантинга."""

from types import SimpleNamespace

import pytest

from src.cognition.meta_cognition import MetaCognitiveControl, MetaCognitiveSystem
from src.consciousness.internal_dialogue import InternalDialogueEngine
from src.core.social_cell import SocialCell, ToMLevel
from src.motivation.needs_system import InternalMotivationSystem


@pytest.mark.parametrize(
    ("success", "expected_depth"),
    [(0.1, 3), (0.5, 2), (0.9, 1)],
)
def test_processing_depth_is_bounded_integer_and_uses_complexity(
    success, expected_depth
):
    control = MetaCognitiveControl()

    depth = control.adjust_depth(task_complexity=0.5, current_success=success)

    assert type(depth) is int
    assert depth == expected_depth
    assert control.min_processing_depth <= depth <= control.max_processing_depth


def test_processing_depth_honors_configuration_and_disabled_adaptation():
    control = MetaCognitiveControl()
    control.min_processing_depth = 2
    control.max_processing_depth = 4
    control.default_depth = 2

    assert control.adjust_depth(0.0, 0.1) == 3
    assert control.adjust_depth(0.0, 0.9) == 2
    control.depth_adaptation = False
    assert control.adjust_depth(1.0, 0.1) == 2


def test_regulate_cognition_stores_numeric_processing_depth():
    system = MetaCognitiveSystem("DepthRegression")

    adjustment = system.regulate_cognition("обычная задача", success_rate=0.5)

    assert type(adjustment["depth_change"]["to"]) is int
    assert type(system.cognitive_state.processing_depth) is int
    assert type(system.cognitive_state.to_dict()["processing_depth"]) is int


def test_new_agent_models_inherit_current_tom_level():
    social = SocialCell(SimpleNamespace())

    default_peer = social.register_agent("default-peer")
    assert default_peer.tom_level is ToMLevel.SECOND

    social.set_tom_level(ToMLevel.FIRST)
    first_peer = social.register_agent("first-peer")
    assert default_peer.tom_level is ToMLevel.FIRST
    assert first_peer.tom_level is ToMLevel.FIRST

    social.set_tom_level(ToMLevel.THIRD)
    third_peer = social.register_agent("third-peer")
    assert default_peer.tom_level is ToMLevel.THIRD
    assert first_peer.tom_level is ToMLevel.THIRD
    assert third_peer.tom_level is ToMLevel.THIRD


def test_resolve_conflict_returns_result_and_records_event():
    engine = InternalDialogueEngine()

    result = engine.resolve_conflict(
        engine.BASE_VOICES["skeptic"], engine.BASE_VOICES["optimist"], "риск"
    )

    assert result["voices"] == ["Скептик", "Оптимист"]
    assert result["topic"] == "риск"
    assert isinstance(result["resolution"], dict)
    assert result["ecosystem_impact"] == 0.5
    assert engine.conflict_events == [result]


@pytest.mark.parametrize(
    ("first", "second", "winner"),
    [
        ("skeptic", "optimist", "objective"),
        ("experience", "heart", "experience"),
        ("will", "heart", "will"),
        ("objective", "skeptic", "objective"),
        ("objective", "optimist", "objective"),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_dominance_rules_use_stable_ids_in_either_order(first, second, winner, reverse):
    engine = InternalDialogueEngine()
    participants = [engine.BASE_VOICES[first], engine.BASE_VOICES[second]]
    if reverse:
        participants.reverse()

    resolution = engine._choose_winner(*participants, "конфликт")

    assert resolution["winner"] == winner
    assert resolution["reason"] == f"Правила доминирования: {winner} побеждает"
    assert resolution["confidence"] == 0.95


def test_internal_dialogue_engines_do_not_share_mutable_voices():
    first = InternalDialogueEngine()
    second = InternalDialogueEngine()
    template_strength = InternalDialogueEngine.BASE_VOICES["skeptic"].strength
    second_strength = second.get_micrbiome_state()["voices_status"]["skeptic"][
        "strength"
    ]

    adjustment = first.adjust_ecosystem("skeptic", 1.0)

    assert adjustment["new_strength"] > adjustment["old_strength"]
    assert (
        second.get_micrbiome_state()["voices_status"]["skeptic"]["strength"]
        == second_strength
    )
    assert InternalDialogueEngine.BASE_VOICES["skeptic"].strength == template_strength


def test_motivation_status_is_idempotent():
    system = InternalMotivationSystem("StatusRegression")
    for drive in system.drives.values():
        drive.active_count = 0

    first = system.get_status()
    second = system.get_status()

    assert first == second


def test_drive_activation_count_tracks_only_inactive_to_active_transition():
    system = InternalMotivationSystem("ActivationRegression")
    drive = system.drives["purposeful_learning"]

    system.calculate_drive_levels()
    assert drive.is_active()
    assert drive.active_count == 1

    system.calculate_drive_levels()
    assert drive.active_count == 1

    system.satisfy_need("knowledge_acquisition", 1.0)
    system.satisfy_need("competence", 1.0)
    system.calculate_drive_levels()
    assert not drive.is_active()
    assert drive.active_count == 1

    system.needs["knowledge_acquisition"].level = 1.0
    system.needs["competence"].level = 1.0
    system.calculate_drive_levels()
    assert drive.is_active()
    assert drive.active_count == 2


def test_legacy_motivation_drives_do_not_share_contributing_needs():
    first = InternalMotivationSystem("FirstLife")
    second = InternalMotivationSystem("SecondLife")
    own_drive = first.drives["purposeful_learning"]
    other_drive = second.drives["purposeful_learning"]

    assert own_drive.contributing_needs is not other_drive.contributing_needs
    own_drive.contributing_needs["knowledge_acquisition"] = 0.99

    assert other_drive.contributing_needs["knowledge_acquisition"] != 0.99
