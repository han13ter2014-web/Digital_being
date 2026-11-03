"""Локальная партия крестиков-ноликов с простым соперником, без поиска знаний."""

import random

LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


def outcome(board):
    for line in LINES:
        if board[line[0]] != "." and len({board[index] for index in line}) == 1:
            return board[line[0]]
    return "draw" if "." not in board else None


def new_game():
    return {"board": ["."] * 9, "turns": 0, "round": 1, "result": None}


def validate_game(state):
    if not isinstance(state, dict):
        raise ValueError("local_play: нужен словарь")
    board = state.get("board")
    if not isinstance(board, list) or len(board) != 9 or any(cell not in (".", "X", "O") for cell in board):
        raise ValueError("local_play.board")
    if type(state.get("turns")) is not int or state["turns"] != board.count("X"):
        raise ValueError("local_play.turns")
    if type(state.get("round")) is not int or state["round"] < 1:
        raise ValueError("local_play.round")
    if state.get("result") != outcome(board):
        raise ValueError("local_play.result")
    if board.count("X") not in (board.count("O"), board.count("O") + 1):
        raise ValueError("local_play: нарушен порядок ходов")
    if state["result"] is None and board.count("X") != board.count("O"):
        raise ValueError("local_play: незавершённый ответ соперника")


def play_turn(state):
    validate_game(state)
    if state["result"] is not None:
        number = state["round"] + 1
        state.update(new_game())
        state["round"] = number
    # Один выбранный ход и ответ локального соперника, не отдельный act.
    chosen = random.choice([index for index, cell in enumerate(state["board"]) if cell == "."])
    state["board"][chosen] = "X"
    state["turns"] += 1
    state["result"] = outcome(state["board"])
    opponent = None
    if state["result"] is None:
        opponent = random.choice([index for index, cell in enumerate(state["board"]) if cell == "."])
        state["board"][opponent] = "O"
        state["result"] = outcome(state["board"])
    return {"chosen_cell": chosen, "opponent_cell": opponent, "result": state["result"],
            "board": list(state["board"]), "round": state["round"]}


# ============================================================
# Вторая игра: «угадай число».
# В отличие от крестиков-ноликов, здесь у существа есть настоящая
# стратегия — бисекция: каждый ход вдвое сужает живой диапазон.
# Мастерство измеримо: больше 7 попыток на сто — уже не бисекция.
# ============================================================

GUESS_MIN, GUESS_MAX = 1, 100
# log2(100) ≈ 6.6 — худший честный результат бисекции.
GUESS_MAX_ATTEMPTS = 7


def new_guess_game():
    return {
        "secret": random.randint(GUESS_MIN, GUESS_MAX),
        "low": GUESS_MIN,
        "high": GUESS_MAX,
        "attempts": 0,
        "round": 1,
        "result": None,
        # Сколько попыток заняла каждая выигранная партия — летопись мастерства.
        "history": [],
    }


def validate_guess(state):
    if not isinstance(state, dict):
        raise ValueError("local_guess: нужен словарь")
    low, high = state.get("low"), state.get("high")
    secret = state.get("secret")
    for name, value in (("low", low), ("high", high), ("secret", secret)):
        if type(value) is not int:
            raise ValueError(f"local_guess.{name}")
    if not (GUESS_MIN <= low <= secret <= high <= GUESS_MAX):
        raise ValueError("local_guess: нарушены границы диапазона")
    if type(state.get("attempts")) is not int or state["attempts"] < 0:
        raise ValueError("local_guess.attempts")
    if type(state.get("round")) is not int or state["round"] < 1:
        raise ValueError("local_guess.round")
    history = state.get("history")
    if not isinstance(history, list) or any(type(a) is not int or a < 1 for a in history):
        raise ValueError("local_guess.history")
    # Выигрыш возможен только когда диапазон сошёлся на секрете.
    if state.get("result") == "win" and not (low == high == secret):
        raise ValueError("local_guess: выигрыш без схождения диапазона")
    if state.get("result") not in (None, "win"):
        raise ValueError("local_guess.result")


def guess_turn(state):
    """Один ход угадывания: середина живого диапазона (бисекция)."""
    validate_guess(state)
    if state["result"] is not None:
        number = state["round"] + 1
        history = list(state["history"])
        state.update(new_guess_game())
        state["round"] = number
        state["history"] = history
    guess = (state["low"] + state["high"]) // 2
    state["attempts"] += 1
    if guess == state["secret"]:
        state["low"] = state["high"] = guess
        state["result"] = "win"
        state["history"].append(state["attempts"])
        hint = "угадал"
    elif guess < state["secret"]:
        state["low"] = guess + 1
        hint = "больше"
    else:
        state["high"] = guess - 1
        hint = "меньше"
    return {
        "guess": guess,
        "hint": hint,
        "attempts": state["attempts"],
        "result": state["result"],
        "round": state["round"],
    }
