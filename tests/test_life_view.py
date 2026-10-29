"""Форматтеры карточек «Сейчас»: только реальные данные, без вымысла."""

from src.ui import life_view as view


def _snapshot(**overrides):
    base = {
        "name": "Alpha",
        "life": {"cycle": 428, "energy": 148.0, "state": "alive",
                 "fatigue": 0.21, "fatigue_level": "normal", "needs_rest": False},
        "now": {"activity": None, "goal": None, "loop": {}},
        "motivation": {},
        "intentions": {"active": None, "waiting": [], "recent": []},
        "activities": {"creative": {"count": 0, "drafts": []}, "game": None},
        "preferences": {},
        "goals": {},
        "access": {"network": {"enabled": True, "label": "Интернет-поиск"},
                   "delamain": {"enabled": False, "label": "Delamain (эффектор)"},
                   "effector": {"enabled": False, "label": "Выполнение действий"},
                   "workspace": {"path": "profile/delamain/workspace/creative",
                                 "label": "Творческая рабочая область"}},
        "effector": {"available": True, "counts": {}, "last_error": None},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


# ---------------------------------------------------------------- заголовок


def test_headline_when_idle_and_rested():
    assert view.now_headline(_snapshot()) == "Выбираю, чем заняться"


def test_headline_when_dormant():
    assert view.now_headline(_snapshot(life={"state": "dormant"})) == "Сплю в Яслях"


def test_headline_names_creative_draft():
    snap = _snapshot(now={"activity": {"action": "create_draft", "target": "тишина"}})
    assert "черновик" in view.now_headline(snap).lower()
    assert "тишина" in view.now_headline(snap)


def test_headline_when_waiting_for_evidence():
    snap = _snapshot(intentions={"waiting": [{"target": "память"}]})
    assert "память" in view.now_headline(snap)


def test_headline_reports_rest_need():
    snap = _snapshot(life={"needs_rest": True})
    assert "Отдыхаю" in view.now_headline(snap)


# ---------------------------------------------------------------- занятие


def test_activity_rows_empty_when_nothing_started():
    rows = dict(view.activity_rows(_snapshot()))
    assert "начатого дела пока нет" in rows["Занятие"]


def test_activity_rows_play_use_real_game_state():
    snap = _snapshot(
        now={"activity": {"action": "play", "target": "партия"}},
        activities={"game": {"board": ["X"] * 0, "turns": 4, "round": 2, "result": "draw"}},
    )
    rows = dict(view.activity_rows(snap))
    assert rows["Ходов"] == "4"
    assert rows["Результат"] == "ничья"


def test_activity_rows_creative_use_real_draft():
    snap = _snapshot(
        now={"activity": {"action": "create_draft", "target": "тишина"}},
        activities={"creative": {"count": 1, "drafts": [
            {"id": "a" * 32, "theme": "тишина", "revision": 3, "status": "active",
             "sha256": "b" * 64}]}},
    )
    rows = dict(view.activity_rows(snap))
    assert rows["Редакция"] == "3"
    assert rows["Черновик"] == "тишина"
    # Тема черновика не дублируется отдельной строкой.
    assert "Тема" not in rows


# ---------------------------------------------------------------- выбор


def test_choice_rows_include_recorded_reason_only():
    snap = _snapshot(
        now={"activity": {"action": "play", "target": "партия", "source": "activity",
                          "reason": "интерес к партии выше", "cycle": 12},
             "loop": {"last_action": "explore", "last_effect": False}},
        preferences={"play": {"attempts": 5, "effects": 3, "failures": 1, "leaves": 0}},
    )
    rows = dict(view.choice_rows(snap))
    assert rows["Причина"] == "интерес к партии выше"
    assert rows["Источник"] == "activity"
    assert "3" in rows["Опыт способа"]
    assert "без эффекта" in rows["Прошлый исход"]


def test_choice_rows_do_not_invent_alternatives():
    snap = _snapshot(now={"activity": {"action": "play", "target": "партия",
                                       "source": "activity"}})
    labels = [label for label, _ in view.choice_rows(snap)]
    assert "Рассматривал" not in labels
    assert "Другие варианты" not in labels
    assert dict(view.choice_rows(snap))["Причина"] == "не записана"


def test_choice_rows_empty_without_activity():
    assert view.choice_rows(_snapshot()) == []


# ---------------------------------------------------------------- влияния


def test_body_summary_is_one_compact_line():
    text = view.body_summary(_snapshot())
    assert "цикл 428" in text
    assert "энергия 148" in text
    assert "усталость 0.21" in text


def test_influence_rows_show_needs_and_waiting():
    snap = _snapshot(
        motivation={"most_pressing_need": "curiosity",
                    "pressing_needs": ["curiosity", "rest"],
                    "active_drives": ["exploration"]},
        intentions={"waiting": [{"target": "память"}]},
    )
    rows = dict(view.influence_rows(snap))
    assert rows["Сильнее всего"] == "curiosity"
    assert "curiosity" in rows["Настойчивые потребности"]
    assert rows["Ждут условий"] == "память"


def test_influence_rows_state_when_nothing_presses():
    rows = dict(view.influence_rows(_snapshot()))
    assert rows["Сейчас"] == "ничего заметно не давит"


# ---------------------------------------------------------------- доступы


def test_access_rows_show_real_switches():
    rows = dict(view.access_rows(_snapshot()))
    assert rows["Интернет-поиск"] == "включено"
    assert rows["Delamain (эффектор)"] == "выключено"


# ---------------------------------------------------------------- effector


def test_effector_rows_keep_queued_and_succeeded_separate():
    snap = _snapshot(effector={"available": True, "counts": {
        "queued": 2, "waiting_approval": 1, "succeeded": 3, "failed": 1, "rejected": 0}})
    rows = dict(view.effector_rows(snap))
    assert rows["в очереди"] == "2"
    assert rows["ждёт подтверждения"] == "1"
    assert rows["выполнено"] == "3"


def test_effector_absent_is_stated_not_hidden():
    rows = dict(view.effector_rows(_snapshot(effector={"available": False, "counts": {}})))
    assert "не подключён" in rows["Состояние"]


def test_pending_note_only_when_something_is_unfinished():
    assert view.pending_effector_note(_snapshot()) is None
    snap = _snapshot(effector={"available": True, "counts": {"queued": 1, "succeeded": 9}})
    assert "Не завершено" in view.pending_effector_note(snap)
