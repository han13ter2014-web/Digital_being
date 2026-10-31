"""Классификатор речевых актов: социальная речь ≠ ответ и ≠ учебный материал.

Маркеры сведены к реальным репликам живого прогона 2026-11-01 на
сущности Тэсс: тогда «Я же уже отвечал тебе.» уходило в изучение
концептов («Не нашел файл для…»), а «Привет! Я рядом…» — в «Ответ
записан.». Классификатор детерминированный, без LLM; нераспознанное
→ ACT_UNKNOWN (старая маршрутизация без изменений).
"""

import pytest

from src.core.dialogue_acts import (
    ACT_ANSWER,
    ACT_SOCIAL,
    ACT_UNKNOWN,
    classify_user_text,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        # === реальные реплики живого прогона ===
        ("Я же уже отвечал тебе.", ACT_SOCIAL),
        (
            "Привет! Я рядом. Только учти: могу отлучаться надолго — "
            "не переживай, если молчу.",
            ACT_SOCIAL,
        ),
        # === протест / мета о диалоге ===
        ("Ты снова спрашиваешь то же самое.", ACT_SOCIAL),
        ("Это тот же вопрос, что и вчера.", ACT_SOCIAL),
        ("Зачем снова спрашиваешь?", ACT_SOCIAL),
        # === присутствие и обещания ===
        ("Я рядом с тобой.", ACT_SOCIAL),
        ("Не переживай, буду молчать пару дней.", ACT_SOCIAL),
        ("Могу долго не писать, не жди меня.", ACT_SOCIAL),
        ("Завтра отлучусь по делам.", ACT_SOCIAL),
        # === приветствия и smalltalk ===
        ("Привет!", ACT_SOCIAL),
        ("Здравствуй, как дела?", ACT_SOCIAL),
        ("Доброе утро!", ACT_SOCIAL),
        ("Как настроение?", ACT_SOCIAL),
        ("Чем занимаешься?", ACT_SOCIAL),
        # === тепло ===
        ("Скучаю по тебе.", ACT_SOCIAL),
        ("Спасибо тебе за разговор.", ACT_SOCIAL),
        # === явные ответные формулы ===
        ("Мой ответ: тишина и покой.", ACT_ANSWER),
        ("ответ такой: данные важнее скорости", ACT_ANSWER),
        ("Ответ: теория информации.", ACT_ANSWER),
        # приоритет: явная формула бьёт социальные слова внутри текста
        ("мой ответ: я рядом и всё хорошо", ACT_ANSWER),
        # === настоящие ответы без формул — unknown (старый путь) ===
        ("Спокойно и тепло. А что тебя самого сейчас занимает?", ACT_UNKNOWN),
        ("Тишина и покой, много отдыха.", ACT_UNKNOWN),
        ("42.", ACT_UNKNOWN),
        ("", ACT_UNKNOWN),
        ("   ", ACT_UNKNOWN),
        (None, ACT_UNKNOWN),
    ],
)
def test_classification_table(text, expected):
    assert classify_user_text(text).kind == expected


def test_matched_marker_is_reported():
    act = classify_user_text("Я же уже отвечал тебе.")
    assert act.kind == ACT_SOCIAL
    # первым в таблице стоит более длинный маркер — он и отчёжается
    assert act.matched_marker == "уже отвечал"


def test_unknown_has_no_marker():
    act = classify_user_text("Просто слова без маркеров.")
    assert act.kind == ACT_UNKNOWN
    assert act.matched_marker == ""


def test_whitespace_and_case_are_normalized():
    assert classify_user_text("   ПРИВЕТ!   ").kind == ACT_SOCIAL
    assert classify_user_text("не   переживай").kind == ACT_SOCIAL
