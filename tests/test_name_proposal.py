"""Пользовательские фразы назначения имени: без LLM и без захвата всей речи."""

import pytest
from src.core.name_proposal import extract_name_proposal


@pytest.mark.parametrize("text,expected", [
    ('Привет, давай твоим именем будет Омелла?', 'Омелла'),
    ('Тебя будут звать Омелла', 'Омелла'),
    ('Пусть тебя зовут Луна', 'Луна'),
    ('Я буду звать тебя «Малютка»', 'Малютка'),
    ('Малютка', 'Малютка'),
    ('Ты понимаешь меня?', None),
    ('Не знаю', None),
    ('Привет, как твои дела сегодня?', None),
])
def test_name_proposal(text, expected):
    assert extract_name_proposal(text) == expected
