"""Ф3: диалоговое состояние переживает чекпоинт.

До этой секции question_history/pending_questions жили только в
оперативной памяти: после рестарта сущность забывала разговор, а
цепочка сложного вопроса обрывалась — синтез не мог завершиться,
потому что sub_answers терялись. Плюс схема id = len(pending)+1
после восстановления выдавала дубликаты: ответ попадал в чужой
вопрос.
"""

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
    ui.restore_from_checkpoint({
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
    })

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
    ui.restore_from_checkpoint({
        "pending_questions": [
            {"id": 1, "question": "Расскажи про «вопрос»?",
             "context": "самостоятельный вопрос по теме: вопрос",
             "cycle": 900},
            {"id": 2, "question": "Расскажи про «вопрос»?",
             "context": "самостоятельный вопрос по теме: вопрос",
             "cycle": 950},
            {"id": 3, "question": "Расскажи про «темы»?",
             "context": "самостоятельный вопрос по теме: темы",
             "cycle": 1000},
            {"id": 4, "question": "Я разбираюсь с темой «понимать»...",
             "context": "самостоятельный вопрос по теме: понимать",
             "cycle": 1100},
            {"id": 5, "question": "Я разбираюсь с темой «понимать»...",
             "context": "самостоятельный вопрос по теме: понимать",
             "cycle": 1150},
            {"id": 6, "question": "Что значит ответственный?",
             "context": "самостоятельный вопрос по теме: ответственный",
             "cycle": 1200},
        ],
    })

    assert [q["id"] for q in ui.pending_questions] == [4, 6]
    assert ui.get_pending_question()["question"].startswith(
        "Я разбираюсь с темой «понимать»"
    )
