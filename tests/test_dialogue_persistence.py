"""Диалоговое состояние переживает чекпоинт.

До этой секции question_history/pending_questions жили только в
оперативной памяти: после рестарта сущность забывала разговор, а
цепочка сложного вопроса обрывалась — синтез не мог завершиться,
потому что sub_answers терялись. Плюс схема id = len(pending)+1
после восстановления выдавала дубликаты: ответ попадал в чужой
вопрос.
"""

import json

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import (
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.checkpoint_validation import validate_checkpoint_state


def test_dialogue_state_survives_checkpoint_and_synthesis_completes():
    """История, ожидающий под-вопрос и накопитель цепочки живут после
    рестарта — синтез сложного вопроса завершается на новой жизни."""
    original = DigitalBeing(name="DI")
    ui = original.user_interaction
    first = ui.ask_user(
        "Что такое тумелость?",
        context="Под-вопрос 1/2 для: глиф",
        cycle=10,
    )
    assert first["status"] == "queued"
    ui.submit_answer(first["id"], "Тумелость — это тихое тепло", cycle=11)
    second = ui.ask_user(
        "Также для понимания 'глиф': что такое глиф?",
        context="Под-вопрос 2/2 для: глиф",
        cycle=62,
        complex_question="глиф",
        sub_questions=["Что такое тумелость?", "Что такое глиф?"],
        sub_question_index=1,
        sub_answers={"Что такое тумелость?": "Тумелость — это тихое тепло"},
    )
    assert second["status"] == "queued"

    state = build_state_from_agent(original)
    validate_checkpoint_state(state)
    assert state["user_interaction"]["question_history"], "история в снапшоте"
    assert state["user_interaction"]["pending_questions"], "очередь в снапшоте"

    restored = DigitalBeing(name="DI")
    restored.cycle_count = original.cycle_count
    apply_state_to_agent(restored, state)

    rui = restored.user_interaction
    assert [(h["question"], h["answer"]) for h in rui.question_history] == [
        ("Что такое тумелость?", "Тумелость — это тихое тепло")
    ]
    pending = rui.get_pending_question()
    assert pending is not None
    assert pending["question"] == "Также для понимания 'глиф': что такое глиф?"
    assert pending["complex_question"] == "глиф"
    assert pending["sub_question_index"] == 1
    assert pending["sub_answers"] == {
        "Что такое тумелость?": "Тумелость — это тихое тепло"
    }

    synthesized = []
    result = rui.submit_answer(
        pending["id"],
        "Глиф — это знак",
        on_synthesis_needed=lambda cq, sa: synthesized.append((cq, dict(sa))),
        cycle=12,
    )
    assert result["status"] == "answered"
    assert result.get("synthesis_needed") is True
    assert synthesized == [
        (
            "глиф",
            {
                "Что такое тумелость?": "Тумелость — это тихое тепло",
                "Что такое глиф?": "Глиф — это знак",
            },
        )
    ]


def test_ask_user_ids_stay_unique_after_restore():
    """id = max(pending)+1: после рестарта новый вопрос не дублирует id
    восстановленного, и ответ попадает в свой вопрос."""
    original = DigitalBeing(name="DU")
    first = original.user_interaction.ask_user("Открытый вопрос?", cycle=10)
    assert first["id"] == 1

    state = build_state_from_agent(original)
    restored = DigitalBeing(name="DU")
    apply_state_to_agent(restored, state)

    rui = restored.user_interaction
    assert [q["id"] for q in rui.pending_questions] == [1]
    second = rui.ask_user("Новый вопрос?", cycle=200)
    assert second["status"] == "queued"
    assert second["id"] == 2

    result = rui.submit_answer(2, "Ответ на новый", cycle=201)
    assert result["status"] == "answered"
    assert result["question_id"] == 2
    assert rui.question_history[-1]["question"] == "Новый вопрос?"


def test_restore_skips_corrupt_and_answered_entries():
    """Битые записи пропускаются, мёртвые (отвечённые) вопросы не
    восстанавливаются, id без коллизий, маркеры цикла на месте."""
    ui = DigitalBeing(name="DC").user_interaction
    ui.restore_from_checkpoint(
        {
            "question_history": [
                {"question": "", "answer": "x", "cycle": 1},
                "мусор",
                {
                    "question": "Что такое X?",
                    "answer": "Y",
                    "context": "c",
                    "cycle": 5,
                    "priority": "high",
                },
            ],
            "pending_questions": [
                {"id": 1, "question": "Отвечен?", "answered": True},
                {"id": 2, "question": "Живой?", "cycle": 7},
                {"id": "битый", "question": "Странный?", "cycle": "нет"},
            ],
            "last_question_cycle": 10,
            "last_user_message_cycle": 11,
        }
    )

    assert len(ui.question_history) == 1
    assert ui.question_history[0]["question"] == "Что такое X?"
    assert ui.question_history[0]["priority"] == "high"
    live_ids = [q["id"] for q in ui.pending_questions]
    assert len(live_ids) == 2
    assert len(set(live_ids)) == 2
    assert ui.get_pending_question()["question"] == "Живой?"
    assert ui.last_question_cycle == 10
    assert ui.get_last_user_message_cycle() == 11


def test_restore_ignores_non_dict_payload():
    """Чекпоинт без секции или с мусором вместо секции — не падение."""
    ui = DigitalBeing(name="DN").user_interaction
    ui.restore_from_checkpoint(None)
    ui.restore_from_checkpoint("мусор")
    assert ui.question_history == []
    assert ui.pending_questions == []


def test_ask_user_skips_identical_pending_question():
    """Идентичный неотвеченный вопрос не встаёт в очередь дважды:
    возвращается duplicate с id уже висящего вопроса. После ответа
    тот же вопрос можно задать заново."""
    ui = DigitalBeing(name="DD").user_interaction
    context = "самостоятельный вопрос по теме: понимать"
    question = "Я разбираюсь с темой «понимать» — объяснишь?"

    first = ui.ask_user(question, context=context, cycle=10)
    assert first["status"] == "queued"

    second = ui.ask_user(question, context=context, cycle=100)
    assert second["status"] == "duplicate"
    assert second["id"] == first["id"]
    assert len(ui.pending_questions) == 1

    ui.submit_answer(first["id"], "Понимать — это постигать смысл", cycle=101)
    third = ui.ask_user(question, context=context, cycle=200)
    assert third["status"] == "queued"


def test_restore_drops_meta_topic_and_duplicate_pending():
    """Миграция: самостоятельные вопросы про метаслова диалога
    («вопрос», «темы»...) и идентичные дубликаты не восстанавливаются
    — не напоминают вечно после рестарта. Обычные темы живут, проверка
    по целым словам: «ответственный» метасловом не считается."""
    ui = DigitalBeing(name="DM").user_interaction
    ui.restore_from_checkpoint(
        {
            "pending_questions": [
                {
                    "id": 1,
                    "question": "Расскажи про «вопрос»?",
                    "context": "самостоятельный вопрос по теме: вопрос",
                    "cycle": 900,
                },
                {
                    "id": 2,
                    "question": "Расскажи про «вопрос»?",
                    "context": "самостоятельный вопрос по теме: вопрос",
                    "cycle": 950,
                },
                {
                    "id": 3,
                    "question": "Расскажи про «темы»?",
                    "context": "самостоятельный вопрос по теме: темы",
                    "cycle": 1000,
                },
                {
                    "id": 4,
                    "question": "Я разбираюсь с темой «понимать»...",
                    "context": "самостоятельный вопрос по теме: понимать",
                    "cycle": 1100,
                },
                {
                    "id": 5,
                    "question": "Я разбираюсь с темой «понимать»...",
                    "context": "самостоятельный вопрос по теме: понимать",
                    "cycle": 1150,
                },
                {
                    "id": 6,
                    "question": "Что значит ответственный?",
                    "context": "самостоятельный вопрос по теме: ответственный",
                    "cycle": 1200,
                },
            ],
        }
    )

    assert [q["id"] for q in ui.pending_questions] == [4, 6]
    assert ui.get_pending_question()["question"].startswith(
        "Я разбираюсь с темой «понимать»"
    )


def test_outgoing_trace_survives_json_checkpoint_without_replay():
    """Персистентный след: две одинаковые публикации остаются двумя записями после
    рестарта; входные реплики не попадают в след, старая очередь не
    показывается повторно, а новые сообщения продолжают историю."""
    original = DigitalBeing(name="DT")
    ui = original.user_interaction
    question = "Хочешь переименовать меня?"
    context = "naming_dialogue"
    ui.send_reply(question, context=context, cycle=8150)
    ui.send_reply(question, context=context, cycle=8150)
    ui.receive_user_message("Нет", cycle=8151)

    state = json.loads(
        json.dumps(
            build_state_from_agent(original),
            ensure_ascii=False,
        )
    )
    validate_checkpoint_state(state)
    saved = state["user_interaction"]["outgoing_messages"]
    assert len(saved) == 2
    assert all(entry["sender"] == "agent" for entry in saved)
    assert all({"id", "content", "cycle", "context"} <= entry.keys() for entry in saved)

    restored = DigitalBeing(name="DT")
    apply_state_to_agent(restored, state)
    rui = restored.user_interaction
    assert rui.message_queue == []

    trace = rui.to_checkpoint_dict()["outgoing_messages"]
    matching = [
        entry
        for entry in trace
        if entry["content"] == question and entry["context"] == context
    ]
    assert len(matching) == 2
    assert [entry["cycle"] for entry in matching] == [8150, 8150]

    rui.send_reply(question, context=context, cycle=8152)
    trace = rui.to_checkpoint_dict()["outgoing_messages"]
    assert (
        len(
            [
                entry
                for entry in trace
                if entry["content"] == question and entry["context"] == context
            ]
        )
        == 3
    )


def test_outgoing_trace_is_bounded_to_latest_messages(monkeypatch):
    """Персистентный след: чекпоинт хранит кольцо последних публикаций, а не всю жизнь."""
    ui = DigitalBeing(name="DR").user_interaction
    monkeypatch.setattr(ui, "OUTGOING_TRACE_MAX", 3)
    for index in range(5):
        ui.send_reply(f"Реплика {index}", context="ring", cycle=index)

    saved = ui.to_checkpoint_dict()["outgoing_messages"]
    assert [entry["content"] for entry in saved] == [
        "Реплика 2",
        "Реплика 3",
        "Реплика 4",
    ]

    restored = DigitalBeing(name="DR").user_interaction
    restored.restore_from_checkpoint({"outgoing_messages": saved})
    assert [entry["content"] for entry in restored.message_history] == [
        "Реплика 2",
        "Реплика 3",
        "Реплика 4",
    ]


def test_outgoing_trace_restore_skips_corrupt_entries_and_legacy_payload():
    """Персистентный след: старый чекпоинт без нового поля и мусор в новом поле безопасны."""
    ui = DigitalBeing(name="DL").user_interaction
    ui.restore_from_checkpoint({"question_history": []})
    assert ui.message_history == []

    ui.restore_from_checkpoint(
        {
            "outgoing_messages": [
                "мусор",
                {"id": "u1", "sender": "user", "content": "Вход", "cycle": 1},
                {"id": "", "sender": "agent", "content": "Нет id", "cycle": 2},
                {"id": "a1", "sender": "agent", "content": "", "cycle": 3},
                {
                    "id": "a2",
                    "sender": "agent",
                    "content": "Битый цикл",
                    "cycle": "нет",
                },
                {
                    "id": "a3",
                    "sender": "agent",
                    "content": "Сохранить",
                    "cycle": 4,
                    "context": "test",
                },
            ],
        }
    )
    assert ui.message_queue == []
    assert ui.message_history == [
        {
            "id": "a3",
            "sender": "agent",
            "content": "Сохранить",
            "cycle": 4,
            "context": "test",
        }
    ]


def test_acknowledged_messages_leave_queue_and_live_history_is_bounded(monkeypatch):
    from src.perception.user_interaction import UserInteraction

    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
    ui = UserInteraction("BoundedDialogue")
    ui.MESSAGE_HISTORY_MAX = 20
    ids = [ui.send_message(f"Сообщение {index}", cycle=7) for index in range(30)]
    assert len(set(ids)) == len(ids)

    for msg_id in ids:
        assert ui.acknowledge_message(msg_id) is True
    assert ui.message_queue == []
    assert ui.get_pending_messages() == []
    assert len(ui.message_history) == 20
    assert all(item["acknowledged"] for item in ui.message_history)

    for index in range(30):
        ui.receive_user_message(f"Ответ {index}", cycle=8)
    assert len(ui.message_history) == 20
    assert ui.message_history[-1]["content"] == "Ответ 29"

    # Удаление из очереди и обрезка history не должны приводить к повторному ID.
    assert ui.send_message("Новое", cycle=7) not in ids
    assert len(ui.to_checkpoint_dict()["outgoing_messages"]) <= ui.OUTGOING_TRACE_MAX
