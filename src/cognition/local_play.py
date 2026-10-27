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
