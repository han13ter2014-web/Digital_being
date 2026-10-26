"""Причинный журнал не должен расходиться с реальной проверкой тупика."""

from src.core.loop_closure import LoopCloser
from src.core.world_delta import WorldSignature


def test_alias_diagnostic_uses_same_state_as_choice():
    closer = LoopCloser(max_no_effect=3)
    signature = WorldSignature()
    for _ in range(3):
        closer.observe("explore", signature, signature)
    before = closer.to_checkpoint_dict()
    normalize = lambda action: "explore" if action == "exploration" else action
    rows = closer.describe_candidates([{"action": "exploration"}], normalize=normalize)
    assert rows[0]["action"] == "exploration"
    assert rows[0]["normalized_action"] == "explore"
    assert rows[0]["stuck"]
    assert rows[0]["no_effect_streak"] == 3
    assert closer.choose([{"action": "exploration"}], normalize=normalize, fallback="rest")["action"] == "rest"
    assert closer.to_checkpoint_dict() == before


def test_denial_diagnostic_is_not_confused_with_failed_work():
    closer = LoopCloser()
    signature = WorldSignature()
    closer.observe("ask_user", signature, signature, reason="denied:budget")
    row = closer.describe_candidates([{"action": "ask_user"}])[0]
    assert row["stuck"]
    assert row["denied_streak"] == 1
    assert row["no_effect_streak"] == 0
