"""Тесты «Эволюция-1»: рука — сигнал → черновик config_change.

Границы: рычаги только из белого списка; diff читает живое значение
LR_CONFIG и ничего не выдумывает; категории без безопасного рычага не
дают черновика; трекер требует подряд идущих повторов.
"""

from config.simulation_config import LR_CONFIG
from src.evolution.self_coding import (
    SAFE_TUNABLES,
    SignalTracker,
    draft_config_change,
    parse_proposal_decision,
)


class TestSignalTracker:
    def test_threshold_reached_only_after_consecutive_repeats(self):
        tracker = SignalTracker(threshold=3)
        assert tracker.observe(["energy_efficiency"]) is None
        assert tracker.observe(["energy_efficiency"]) is None
        assert tracker.observe(["energy_efficiency"]) == "energy_efficiency"

    def test_gap_resets_streak(self):
        tracker = SignalTracker(threshold=3)
        tracker.observe(["energy_efficiency"])
        tracker.observe(["energy_efficiency"])
        tracker.observe([])  # тик без сигнала — серия прервана
        assert tracker.streak("energy_efficiency") == 0
        assert tracker.observe(["energy_efficiency"]) is None

    def test_category_without_safe_lever_never_ripens(self):
        tracker = SignalTracker(threshold=2)
        for _ in range(5):
            assert tracker.observe(["goal_management"]) is None

    def test_ripe_streak_resets_to_collect_again(self):
        tracker = SignalTracker(threshold=2)
        tracker.observe(["memory_management"])
        assert tracker.observe(["memory_management"]) == "memory_management"
        assert tracker.streak("memory_management") == 0


class TestDraftConfigChange:
    def test_diff_uses_real_current_value(self):
        draft = draft_config_change("memory_management")
        assert draft is not None
        assert draft["attr"] == "FORGETTING_INTERVAL"
        assert draft["old"] == LR_CONFIG.FORGETTING_INTERVAL
        expected = f"-    FORGETTING_INTERVAL = {LR_CONFIG.FORGETTING_INTERVAL!r}"
        assert expected in draft["diff"]
        assert f"+    FORGETTING_INTERVAL = {draft['new']!r}" in draft["diff"]

    def test_unknown_category_gives_no_draft(self):
        assert draft_config_change("learning_strategy") is None
        assert draft_config_change("несуществующая") is None

    def test_no_draft_when_already_at_candidate(self, monkeypatch):
        tunable = SAFE_TUNABLES["concept_quality"]
        monkeypatch.setattr(LR_CONFIG, tunable.attr, tunable.candidate)
        assert draft_config_change("concept_quality") is None

    def test_no_draft_when_attr_missing(self, monkeypatch):
        # LR_CONFIG — экземпляр; атрибут живёт на классе LongRunningConfig.
        monkeypatch.delattr(type(LR_CONFIG), "FORGETTING_INTERVAL")
        assert draft_config_change("memory_management") is None

    def test_safe_tunables_never_touch_forbidden_areas(self):
        forbidden = ("WILL", "WATCHDOG", "MAX_CYCLES", "TERMINATION", "DREAM")
        for tunable in SAFE_TUNABLES.values():
            for marker in forbidden:
                assert marker not in tunable.attr
            assert hasattr(LR_CONFIG, tunable.attr)


class TestParseProposalDecision:
    def test_approve_with_id(self):
        assert parse_proposal_decision("одобри prop_20261103_1") == (
            "approve",
            "prop_20261103_1",
        )

    def test_reject_without_id(self):
        assert parse_proposal_decision("отклони") == ("reject", None)

    def test_more_synonyms(self):
        assert parse_proposal_decision("Принимаю предложение")[0] == "approve"
        assert parse_proposal_decision("отвергаю")[0] == "reject"

    def test_plain_speech_is_not_a_decision(self):
        assert parse_proposal_decision("я одобряю такой подход") is None
        assert parse_proposal_decision("привет") is None
        assert parse_proposal_decision("") is None
