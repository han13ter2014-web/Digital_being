"""Тесты второй игры «угадай число»: бисекция, валидация, летопись."""
import random

import pytest

from src.cognition.local_play import (
    GUESS_MAX_ATTEMPTS,
    guess_turn,
    new_guess_game,
    validate_guess,
)


def _finish_round(state):
    """Доиграть партию до победы, вернуть число попыток."""
    while state["result"] is None:
        guess_turn(state)
    return state["attempts"]


def test_bisection_wins_within_limit():
    random.seed(7)
    for _ in range(50):
        state = new_guess_game()
        attempts = _finish_round(state)
        assert attempts <= GUESS_MAX_ATTEMPTS


def test_history_records_mastery():
    random.seed(3)
    state = new_guess_game()
    first = _finish_round(state)
    turn = guess_turn(state)  # победа есть — начинается новая партия
    assert turn["round"] == 2
    assert state["history"] == [first]
    assert state["attempts"] == 1  # ход новой партии уже сделан


def test_hints_narrow_range():
    state = new_guess_game()
    state["secret"] = 73
    turn = guess_turn(state)  # guess 50 → меньше... нет: 50 < 73 → «больше»
    assert turn["guess"] == 50
    assert turn["hint"] == "больше"
    assert state["low"] == 51
    turn = guess_turn(state)  # (51+100)//2 = 75 > 73 → «меньше»
    assert turn["hint"] == "меньше"
    assert state["high"] == 74


def test_validate_rejects_tampering():
    state = new_guess_game()
    _finish_round(state)
    broken = dict(state, result="win", high=state["secret"] + 5)
    with pytest.raises(ValueError, match="схождения"):
        validate_guess(broken)
    with pytest.raises(ValueError):
        validate_guess({"secret": "пятьдесят"})
    with pytest.raises(ValueError):
        validate_guess(None)


def test_state_is_json_serializable():
    import json

    state = new_guess_game()
    _finish_round(state)
    restored = json.loads(json.dumps(state))
    validate_guess(restored)
