"""Чистые форматтеры дневника и каталога занятий."""

from src.ui import diary_view


def _snapshot():
    return {
        "diary": {"episodes": [{
            "id": 4,
            "ts": "2026-10-29T12:30:00",
            "task_id": "intention-4",
            "action": "create_draft",
            "args": {"target": "тишина"},
            "ok": True,
            "output": {"result": "revision 3"},
            "error": None,
            "metadata": {"status": "performed"},
        }]},
        "activities": {
            "creative": {"drafts": [{
                "theme": "тишина", "revision": 3, "status": "active",
                "sha256": "a" * 64,
            }]},
            "game": {"board": ["X", "O", ".", ".", "X", ".", ".", ".", "O"],
                     "turns": 2, "round": 3, "result": None},
        },
    }


def test_episode_uses_only_recorded_action_and_target():
    episode = diary_view.diary_rows(_snapshot())[0]
    assert diary_view.episode_title(episode) == "творческий черновик «тишина»"
    rows = dict(diary_view.episode_rows(episode))
    assert rows["Статус"] == "выполнено"
    assert rows["Результат"] == "revision 3"
    assert rows["ID намерения"] == "intention-4"


def test_draft_detail_keeps_real_revision_and_hash():
    draft = diary_view.draft_rows(_snapshot())[0]
    rows = dict(diary_view.draft_detail(draft))
    assert rows["Тема"] == "тишина"
    assert rows["Редакция"] == "3"
    assert rows["SHA-256"] == "a" * 64


def test_game_detail_shows_real_board_and_result():
    rows = dict(diary_view.game_detail(_snapshot()))
    assert rows["Партия"] == "3"
    assert rows["Ходов"] == "2"
    assert rows["Результат"] == "идёт"
    assert rows["Поле"] == "X O . . X . . . O"


def test_empty_catalog_is_explicit():
    assert diary_view.game_detail({})[0] == ("Партия", "ещё не начиналась")
    assert diary_view.diary_rows({}) == []
    assert diary_view.draft_rows({}) == []
