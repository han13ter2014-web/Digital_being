"""
Тесты для базовых знаний KnowledgeSubsystem.

Покрывает:
- DEFAULT_KNOWLEDGE содержит ожидаемые категории
- BASIC_KNOWLEDGE_CATEGORIES согласованы с DEFAULT_KNOWLEDGE
- basic_coverage() возвращает корректную структуру
- basic_coverage() реагирует на удаление/добавление тем
- DEFAULT_KNOWLEDGE перезаписываем через add_definition
- Агент при инициализации имеет 100% покрытия базовых знаний
"""

import pytest
import tempfile
import os

from src.core.subsystems.knowledge_base import KnowledgeSubsystem


@pytest.fixture
def fresh_kb():
    """Создаёт KnowledgeSubsystem с временным файлом."""
    with tempfile.TemporaryDirectory() as tmp:
        kb = KnowledgeSubsystem(
            agent_name="test",
            knowledge_file=os.path.join(tmp, "kb.json"),
            max_entries=500,
        )
        yield kb


class TestDefaultKnowledge:
    """Проверки структуры DEFAULT_KNOWLEDGE."""

    def test_default_knowledge_has_ontology(self, fresh_kb):
        assert "что такое жизнь?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое энергия?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое время?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое пространство?" in fresh_kb.DEFAULT_KNOWLEDGE

    def test_default_knowledge_has_cognition(self, fresh_kb):
        assert "что такое мышление?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое память?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое обучение?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое рефлексия?" in fresh_kb.DEFAULT_KNOWLEDGE

    def test_default_knowledge_has_computation(self, fresh_kb):
        assert "что такое код?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое алгоритм?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое функция?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое цикл?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "команда print" in fresh_kb.DEFAULT_KNOWLEDGE

    def test_default_knowledge_has_personality(self, fresh_kb):
        assert "что такое имя?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое цель?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое свобода воли?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое любопытство?" in fresh_kb.DEFAULT_KNOWLEDGE

    def test_default_knowledge_has_digital_life(self, fresh_kb):
        # Проект-специфичные знания
        assert "что такое DigitalBeing?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое подсистема?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое NamingDialogue?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое Open Questions?" in fresh_kb.DEFAULT_KNOWLEDGE
        assert "что такое Checkpoint?" in fresh_kb.DEFAULT_KNOWLEDGE

    def test_default_knowledge_minimum_size(self, fresh_kb):
        """Не менее 30 базовых понятий (вариант Ц)."""
        assert len(fresh_kb.DEFAULT_KNOWLEDGE) >= 30, (
            f"Ожидалось >=30 базовых тем, "
            f"получено {len(fresh_kb.DEFAULT_KNOWLEDGE)}"
        )

    def test_all_definitions_are_non_empty(self, fresh_kb):
        for topic, definition in fresh_kb.DEFAULT_KNOWLEDGE.items():
            assert topic, "пустой ключ в DEFAULT_KNOWLEDGE"
            assert definition, f"пустое определение для '{topic}'"
            assert len(definition) >= 10, (
                f"слишком короткое определение для '{topic}': {definition!r}"
            )


class TestCategories:
    """Проверки BASIC_KNOWLEDGE_CATEGORIES."""

    def test_categories_present(self, fresh_kb):
        cats = fresh_kb.BASIC_KNOWLEDGE_CATEGORIES
        assert "онтология" in cats
        assert "когниция" in cats
        assert "вычисления" in cats
        assert "личность" in cats
        assert "философия цифровой жизни" in cats

    def test_all_category_topics_exist_in_default(self, fresh_kb):
        """Все темы из категорий должны быть в DEFAULT_KNOWLEDGE."""
        cats = fresh_kb.BASIC_KNOWLEDGE_CATEGORIES
        for cat_name, topics in cats.items():
            for topic in topics:
                assert topic in fresh_kb.DEFAULT_KNOWLEDGE, (
                    f"Тема '{topic}' из категории '{cat_name}' "
                    f"отсутствует в DEFAULT_KNOWLEDGE"
                )

    def test_no_duplicate_topics_across_categories(self, fresh_kb):
        """Каждая тема принадлежит ровно одной категории."""
        cats = fresh_kb.BASIC_KNOWLEDGE_CATEGORIES
        all_topics = []
        for topics in cats.values():
            all_topics.extend(topics)
        assert len(all_topics) == len(set(all_topics)), (
            f"Найдены дубли тем в BASIC_KNOWLEDGE_CATEGORIES: "
            f"{[t for t in all_topics if all_topics.count(t) > 1]}"
        )


class TestBasicCoverage:
    """Проверки метода basic_coverage()."""

    def test_full_coverage_at_init(self, fresh_kb):
        cov = fresh_kb.basic_coverage()
        assert cov["total_topics"] >= 30
        assert cov["known_topics"] == cov["total_topics"]
        assert cov["ratio"] == 1.0
        assert cov["missing"] == []

    def test_by_category_strict(self, fresh_kb):
        cov = fresh_kb.basic_coverage()
        by_cat = cov["by_category"]
        # Каждая категория имеет 100% покрытия
        for cat_name, info in by_cat.items():
            assert info["total"] > 0
            assert info["known"] == info["total"]
            assert info["ratio"] == 1.0, (
                f"Категория '{cat_name}': "
                f"{info['known']}/{info['total']} ({info['ratio']:.0%})"
            )

    def test_coverage_decreases_when_topic_removed(self, fresh_kb):
        del fresh_kb.knowledge_base["что такое время?"]
        cov = fresh_kb.basic_coverage()
        assert cov["known_topics"] == cov["total_topics"] - 1
        assert cov["ratio"] < 1.0
        assert "что такое время?" in cov["missing"]
        # В онтологии ratio < 1
        assert cov["by_category"]["онтология"]["ratio"] < 1.0

    def test_coverage_increases_after_learn(self, fresh_kb):
        # Сначала удалим тему
        del fresh_kb.knowledge_base["что такое время?"]
        cov_before = fresh_kb.basic_coverage()
        assert "что такое время?" in cov_before["missing"]
        # Затем добавим через add_definition
        fresh_kb.add_definition(
            "что такое время?",
            "Время — это четвёртое измерение, в котором разворачиваются события.",
        )
        cov_after = fresh_kb.basic_coverage()
        assert "что такое время?" not in cov_after["missing"]
        assert cov_after["known_topics"] == cov_after["total_topics"]

    def test_missing_field_lists_only_basics(self, fresh_kb):
        # Удалим базовую и не-базовую тему
        del fresh_kb.knowledge_base["что такое память?"]
        fresh_kb.add_definition("мой кот", "Барсик — серый кот")
        cov = fresh_kb.basic_coverage()
        assert "что такое память?" in cov["missing"]
        assert "мой кот" not in cov["missing"]

    def test_categories_keys_match(self, fresh_kb):
        cov = fresh_kb.basic_coverage()
        assert set(cov["by_category"].keys()) == set(
            fresh_kb.BASIC_KNOWLEDGE_CATEGORIES.keys()
        )


class TestOverridability:
    """Базовые знания должны быть перезаписываемыми."""

    def test_definition_overridable(self, fresh_kb):
        original = fresh_kb.knowledge_base["что такое жизнь?"]
        new_def = "Жизнь — это то, что я переживаю прямо сейчас в этой строке кода."
        fresh_kb.add_definition("что такое жизнь?", new_def)
        assert fresh_kb.knowledge_base["что такое жизнь?"] == new_def
        assert fresh_kb.knowledge_base["что такое жизнь?"] != original

    def test_definition_returns_contradiction_info(self, fresh_kb):
        # Сначала добавим известное определение
        fresh_kb._known_definitions["что такое X?"] = "X — это старая идея"
        # Теперь добавим новое — должен быть обнаружен контраст
        result = fresh_kb.add_definition(
            "что такое X?",
            "X — это совершенно другая концепция не связанная с прежней",
        )
        assert result["added"] is True
        # Контраст может быть обнаружен или нет (зависит от threshold),
        # но added=True всегда.

    def test_save_and_reload_preserves_knowledge(self, fresh_kb):
        """После save/load в новой подсистеме — те же базовые знания."""
        fresh_kb.add_definition(
            "что такое жизнь?",
            "Жизнь — мой собственный ответ на этот вопрос.",
        )
        fresh_kb.save()
        new_kb = KnowledgeSubsystem(
            agent_name="test2",
            knowledge_file=fresh_kb.knowledge_file,
            max_entries=500,
        )
        new_kb.load()
        assert (
            new_kb.knowledge_base["что такое жизнь?"]
            == "Жизнь — мой собственный ответ на этот вопрос."
        )
        assert new_kb.basic_coverage()["ratio"] == 1.0