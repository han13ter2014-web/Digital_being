"""
Регрессионные тесты для src/core/open_questions.py.

Эти тесты покрывают новый модуль OpenQuestionsManager, вынесенный
из DigitalBeing в рамках рефакторинга (июль 2026).

Что проверяем:
- Базовые операции: ask/drop/hint/has_unanswered/list_public.
- Дедупликация: повторный ask() → "duplicate".
- Лимит очереди: при переполнении вытесняется самый старый неотвеченный.
- Round-robin стратегии: при consume() стратегии идут по списку.
- record_exploration: эвристика «ответ найден».
- Сериализация: to_dict/load_from (round-trip).
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.open_questions import (
    OpenQuestionsManager,
    EXPLORATION_STRATEGIES,
)


def _make_mgr(cycle=0, log=None, max_size=10, default_max_explorations=5):
    """Фабрика менеджера с подменой cycle_provider и логгера."""
    return OpenQuestionsManager(
        cycle_provider=lambda: cycle,
        log_info=log or (lambda msg: None),
        max_size=max_size,
        default_max_explorations=default_max_explorations,
    )


# === Базовые операции ===

def test_empty_manager_has_no_questions():
    mgr = _make_mgr()
    assert mgr.has_unanswered() is False
    assert mgr.list_public() == []
    assert mgr.consume() is None


def test_ask_adds_question_to_queue():
    mgr = _make_mgr(cycle=10)
    result = mgr.ask("что такое любовь?", source="user")

    assert result["status"] == "queued"
    assert result["queue_size"] == 1
    assert mgr.has_unanswered() is True
    assert len(mgr.list_public()) == 1


def test_ask_rejects_empty_question():
    mgr = _make_mgr()
    assert mgr.ask("")["status"] == "rejected"
    assert mgr.ask("   ")["status"] == "rejected"
    assert mgr.ask("\n\t")["status"] == "rejected"


def test_ask_deduplicates_same_question():
    mgr = _make_mgr()
    r1 = mgr.ask("что такое сознание?")
    r2 = mgr.ask("что такое сознание?")
    r3 = mgr.ask("  ЧТО ТАКОЕ СОЗНАНИЕ?  ")  # case + whitespace

    assert r1["status"] == "queued"
    assert r2["status"] == "duplicate"
    assert r3["status"] == "duplicate"
    assert mgr.list_public()[0]["text"] == "что такое сознание?"


def test_drop_removes_question():
    mgr = _make_mgr()
    mgr.ask("что такое X?")
    result = mgr.drop("что такое X?")

    assert result["status"] == "dropped"
    assert mgr.has_unanswered() is False


def test_drop_unknown_question():
    mgr = _make_mgr()
    result = mgr.drop("чего нет в очереди?")
    assert result["status"] == "not_found"


def test_hint_adds_hint_and_extra_explorations():
    mgr = _make_mgr()
    mgr.ask("что такое Y?")
    result = mgr.hint("что такое Y?", "Y — это абстракция")

    assert result["status"] == "hint_added"
    public = mgr.list_public()
    assert public[0]["hint"] == "Y — это абстракция"
    # hint даёт +2 попытки (default 5 → 7)
    assert public[0]["max"] == 7


def test_hint_unknown_question():
    mgr = _make_mgr()
    result = mgr.hint("нет такого", "любая подсказка")
    assert result["status"] == "not_found"


# === Лимит очереди ===

def test_queue_evicts_oldest_unanswered():
    mgr = _make_mgr(max_size=3)

    mgr.ask("вопрос 1")
    mgr.ask("вопрос 2")
    mgr.ask("вопрос 3")
    # Очередь полна. Добавление 4-го вытеснит вопрос 1.
    mgr.ask("вопрос 4")

    texts = [q["text"] for q in mgr.list_public()]
    assert "вопрос 1" not in texts
    assert "вопрос 4" in texts
    assert len(texts) == 3


# === Стратегии размышления (round_robin) ===

def test_answer_marks_latest_question_without_creating_learning_data():
    mgr = _make_mgr(cycle=12)
    mgr.ask("ты понимаешь меня?", source="self")

    result = mgr.answer("да, я стараюсь понять тебя")

    assert result["status"] == "answered"
    assert mgr.queue[0]["answered"] is True
    assert mgr.queue[0]["answer_source"] == "user"
    assert mgr.has_unanswered() is False


def test_answer_without_pending_question_is_explicit():
    assert _make_mgr().answer("ответ") == {"status": "not_found"}


def test_consume_returns_first_unanswered_with_strategy():
    mgr = _make_mgr(cycle=1)
    mgr.ask("вопрос X")

    stimulus = mgr.consume()
    assert stimulus is not None
    assert stimulus.startswith("вопрос: вопрос X ")
    assert EXPLORATION_STRATEGIES[0] in stimulus  # первая стратегия


def test_consume_cycles_strategies_in_order():
    """consume() выбирает стратегию round-robin по списку.

    Для ОДНОГО вопроса стратегия идёт по списку (mental_model_lookup →
    knowledge_base_search → ...) только если предыдущая была зафиксирована
    через record_exploration. Без record_exploration тот же вопрос всегда
    даёт первую неиспользованную стратегию.
    """
    mgr = _make_mgr(default_max_explorations=10)

    mgr.ask("q1")
    # Делаем consume+record_exploration циклически, пока не кончатся стратегии.
    # (max_explorations=10 нужно, чтобы вопрос не пометилось answered
    # после 5 итераций — у нас 6 стратегий.)
    seen_strategies = []
    for _ in range(len(EXPLORATION_STRATEGIES)):
        stimulus = mgr.consume()
        assert stimulus is not None
        # Извлекаем стратегию из стимула.
        strategy_part = stimulus.split("стратегия=")[1].split(",")[0].strip()
        seen_strategies.append(strategy_part)
        # Фиксируем размышление без маркера ответа.
        mgr.record_exploration(stimulus, thought="промежуточная мысль")

    assert seen_strategies == EXPLORATION_STRATEGIES, \
        f"Стратегии должны идти по списку, получили: {seen_strategies}"


def test_consume_returns_none_when_queue_empty():
    mgr = _make_mgr()
    assert mgr.consume() is None


# === record_exploration и эвристика «ответ найден» ===

def test_record_exploration_appends_to_history():
    mgr = _make_mgr(cycle=5)
    mgr.ask("q1")
    stimulus = mgr.consume()

    mgr.record_exploration(stimulus, thought="Какая-то мысль")

    # Внутренне: в q["explorations"] должна появиться запись.
    assert len(mgr.queue[0]["explorations"]) == 1
    assert mgr.queue[0]["explorations"][0]["thought"] == "Какая-то мысль"


def test_record_exploration_marks_answered_on_mental_model_marker():
    mgr = _make_mgr(cycle=5)
    mgr.ask("что такое любовь?")
    stimulus = mgr.consume()

    # Мысль с маркером [Ментальная модель] → считается ответом
    mgr.record_exploration(
        stimulus,
        thought="Любовь — это [Ментальная модель] сильная привязанность.",
    )

    assert mgr.has_unanswered() is False
    assert mgr.queue[0]["answered"] is True
    assert mgr.queue[0]["answer"] is not None


def test_record_exploration_does_not_mark_for_unknown_prefix():
    mgr = _make_mgr()
    mgr.ask("q1")
    stimulus = mgr.consume()

    # Стимул без префикса "вопрос: " — no-op
    mgr.record_exploration("обычный стимул", thought="[Ментальная модель] X")

    assert len(mgr.queue[0]["explorations"]) == 0


def test_record_exploration_rejects_dont_know_as_answer():
    mgr = _make_mgr()
    mgr.ask("q1")
    stimulus = mgr.consume()

    mgr.record_exploration(
        stimulus,
        thought="Не знаю, [Ментальная модель] пусто",
    )

    assert mgr.has_unanswered() is True


def test_record_exploration_rejects_new_concept_as_answer():
    mgr = _make_mgr()
    mgr.ask("q1")
    stimulus = mgr.consume()

    mgr.record_exploration(
        stimulus,
        thought="Новый концепт: что-то абстрактное [Ментальная модель] X",
    )

    assert mgr.has_unanswered() is True


# === Исчерпание лимита попыток ===

def test_consume_marks_unresolved_when_max_explorations_reached():
    """Если все max_explorations размышлений не дали ответа — вопрос
    помечается как answered (с текстом «не разрешён»), чтобы не
    блокировать consume() бесконечно."""
    mgr = _make_mgr(cycle=1, max_size=10, default_max_explorations=2)
    mgr.ask("неразрешимый вопрос")

    # Первый consume → стимул с попытка 1/2
    s1 = mgr.consume()
    assert s1 is not None
    mgr.record_exploration(s1, thought="Не знаю, не понимаю")

    # Второй consume → стимул с попытка 2/2
    s2 = mgr.consume()
    assert s2 is not None
    mgr.record_exploration(s2, thought="Не знаю, сложно")

    # Третий consume должен пометить вопрос как исчерпанный.
    s3 = mgr.consume()
    # s3 может быть None (если только один вопрос был и он помечен answered).
    # Вместо проверки s3 проверим, что вопрос помечен.
    assert mgr.queue[0]["answered"] is True
    assert "Не удалось найти ответ" in mgr.queue[0]["answer"]


# === Сериализация (чеклист) ===

def test_to_dict_returns_copy_of_queue():
    mgr = _make_mgr()
    mgr.ask("q1")
    mgr.ask("q2")

    exported = mgr.to_dict()
    assert len(exported) == 2
    # Изменение экспорта не должно затронуть очередь.
    exported.append({"fake": True})
    assert len(mgr.queue) == 2


def test_load_from_restores_queue():
    mgr = _make_mgr()

    saved = [
        {
            "text": "restored q",
            "source": "self",
            "started_at": 100,
            "last_explored_at": 105,
            "explorations": [{"cycle": 105, "thought": "x", "strategy": "hypothesis"}],
            "max_explorations": 5,
            "hint": None,
            "answered": False,
            "answer": None,
        }
    ]

    loaded_count = mgr.load_from(saved)
    assert loaded_count == 1
    assert mgr.queue[0]["text"] == "restored q"
    assert mgr.queue[0]["source"] == "self"
    assert len(mgr.queue[0]["explorations"]) == 1


def test_load_from_empty_or_none():
    mgr = _make_mgr()
    assert mgr.load_from(None) == 0
    assert mgr.load_from([]) == 0
    assert len(mgr.queue) == 0


def test_full_roundtrip():
    """Сохранение → восстановление работает корректно."""
    src = _make_mgr(cycle=10)
    src.ask("вопрос о сознании")
    src.hint("вопрос о сознании", "связано с рефлексией")
    saved = src.to_dict()

    dst = _make_mgr(cycle=11)
    dst.load_from(saved)

    assert dst.has_unanswered() is True
    assert dst.list_public()[0]["hint"] == "связано с рефлексией"