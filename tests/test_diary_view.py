"""Чистые форматтеры дневника и каталога занятий."""

from src.ui import diary_view


def _snapshot():
    return {
        "diary": {
            "episodes": [
                {
                    "id": 4,
                    "ts": "2026-10-29T12:30:00",
                    "task_id": "intention-4",
                    "action": "create_draft",
                    "args": {"target": "тишина"},
                    "ok": True,
                    "output": {"result": "revision 3"},
                    "error": None,
                    "metadata": {"status": "performed"},
                }
            ]
        },
        "activities": {
            "creative": {
                "drafts": [
                    {
                        "theme": "тишина",
                        "revision": 3,
                        "status": "active",
                        "sha256": "a" * 64,
                    }
                ]
            },
            "game": {
                "board": ["X", "O", ".", ".", "X", ".", ".", ".", "O"],
                "turns": 2,
                "round": 3,
                "result": None,
            },
        },
    }


def test_episode_uses_only_recorded_action_and_target():
    episode = diary_view.diary_rows(_snapshot())[0]
    assert diary_view.episode_title(episode) == "творческий черновик «тишина»"
    rows = dict(diary_view.episode_rows(episode))
    assert rows["Статус"] == "выполнено"
    assert rows["Результат"] == "revision 3"
    assert rows["ID намерения"] == "intention-4"


def test_draft_detail_explains_work_in_human_words():
    draft = diary_view.draft_rows(_snapshot())[0]
    rows = dict(diary_view.draft_detail(draft))
    assert "текстовый черновик" in rows["Что это"]
    assert "тишина" in rows["Что это"]
    assert rows["О состоянии"].startswith("Работа, к которой")
    assert rows["Состояние"] == "продолжается"
    assert rows["Редакция"] == "3 из 8"
    assert rows["Файл"] == "сохранён; отпечаток файла записан"
    assert "SHA" not in " ".join(rows)
    # Наличие отпечатка не доказывает повторную проверку файла на диске.
    assert "целостность проверена" not in rows["Файл"]


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


def test_episode_row_fields_come_from_recorded_data():
    episode = diary_view.diary_rows(_snapshot())[0]
    assert diary_view.episode_time(episode) == "12:30"
    assert diary_view.episode_time({}) == "—"
    assert diary_view.action_color_key("explore") == "cyan"
    assert diary_view.action_color_key("create_draft") == "violet"
    assert diary_view.action_color_key("чужое-действие") == "grey"


def test_group_diary_folds_only_consecutive_identical_episodes():
    first = {
        "action": "explore",
        "args": {"target": "туман"},
        "ok": True,
        "metadata": {"status": "performed"},
    }
    series = [dict(first, ts=f"2026-11-01T10:0{i}:00") for i in range(4)]
    other = {"action": "rest", "ok": True, "metadata": {"status": "performed"}}
    groups = diary_view.group_diary_episodes(series + [other, dict(first)])
    assert [len(group["episodes"]) for group in groups] == [4, 1, 1]


def test_group_diary_keeps_different_outcomes_apart():
    done = {
        "action": "explore",
        "args": {"target": "туман"},
        "ok": True,
        "metadata": {"status": "performed"},
    }
    failed = {
        "action": "explore",
        "args": {"target": "туман"},
        "ok": False,
        "error": "нет сил",
        "metadata": {"status": "error"},
    }
    groups = diary_view.group_diary_episodes([done, failed, dict(done)])
    assert [len(group["episodes"]) for group in groups] == [1, 1, 1]
