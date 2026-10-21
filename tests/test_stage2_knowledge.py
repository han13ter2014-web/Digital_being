"""Тесты этапа 2: качество базы знаний и фильтр внешнего поиска.

Проверяют, что мусор из Wikipedia (страницы-неоднозначности, ключи-заглушки,
служебные слова) больше не попадает в KB — ни при загрузке, ни при поиске.
"""

import json
import sys
import urllib.parse
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cognition.thinking_pipeline import ThinkingPipeline  # noqa: E402
from src.core.subsystems.knowledge_base import KnowledgeSubsystem  # noqa: E402
from src.memory.knowledge_quality import (  # noqa: E402
    check_entry,
    clean_knowledge_base,
    is_relevant,
    is_worth_searching,
    normalize_concept_name,
)
from src.perception.web_search import WebSearcher  # noqa: E402


VALID_DEF = "Жизнь — это процесс самовоспроизведения и эволюции системы."


# ============================================================
# 1. Фильтр записей
# ============================================================

@pytest.mark.parametrize(
    "key,definition,expected",
    [
        ("s_1", "S1, S01, S.I, S-1, S.1, Š-1 or S 1 may refer to:", "placeholder"),
        ("s_45", "S45 may refer to:", "placeholder"),
        ("?", "S1, S01 may refer to:", "no_letters"),
        ("42", "Число сорок два — натуральное число.", "no_letters"),
        ("меня", "Меня — это форма местоимения «я».", "stop_word"),
        ("ты", "Ты — это местоимение второго лица.", "stop_word"),
        ("", VALID_DEF, "empty_key"),
        ("что такое жизнь?", "", "empty_definition"),
        ("что такое жизнь?", "Коротко.", "definition_too_short"),
        (
            "что такое жизнь?",
            "S1, S01, S.I, S-1, S.1, Š-1 or S 1 may refer to:",
            "disambiguation",
        ),
    ],
)
def test_check_entry_rejects_garbage(key, definition, expected):
    assert check_entry(key, definition) == expected


def test_check_entry_accepts_seed_knowledge():
    for key, definition in KnowledgeSubsystem.DEFAULT_KNOWLEDGE.items():
        assert check_entry(key, definition) is None, key


def test_default_knowledge_has_no_garbage():
    cleaned, removed = clean_knowledge_base(KnowledgeSubsystem.DEFAULT_KNOWLEDGE)
    assert removed == {}
    assert len(cleaned) == len(KnowledgeSubsystem.DEFAULT_KNOWLEDGE)


def test_clean_knowledge_base_keeps_only_valid():
    kb = {
        "что такое жизнь?": VALID_DEF,
        "s_1": "S1, S01, S.I, S-1, S.1, Š-1 or S 1 may refer to:",
        "ты": "Ты — это местоимение второго лица.",
    }
    cleaned, removed = clean_knowledge_base(kb)
    assert list(cleaned) == ["что такое жизнь?"]
    assert removed == {"s_1": "placeholder", "ты": "stop_word"}


def test_tracked_knowledge_base_is_clean():
    """Файл в репозитории не должен содержать мусора."""
    path = PROJECT_ROOT / "data" / "knowledge_base.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    _, removed = clean_knowledge_base(data)
    assert removed == {}, f"В KB остался мусор: {removed}"


def test_normalize_concept_name_still_available():
    assert normalize_concept_name("что такое счастье") == "счастье"


# ============================================================
# 2. Запросы в интернет
# ============================================================

@pytest.mark.parametrize("query", ["?", "s_1", "42", "что такое?", "", "   "])
def test_junk_query_is_not_worth_searching(query):
    assert is_worth_searching(query) is False


@pytest.mark.parametrize(
    "query", ["счастье", "что такое счастье", "как работает мышление", "ии"]
)
def test_meaningful_query_is_worth_searching(query):
    assert is_worth_searching(query) is True


def test_relevance_requires_query_token():
    assert is_relevant("альфа", "Альфа", "Альфа — первая буква алфавита.")
    assert not is_relevant("альфа", "Бета", "Бета — вторая буква алфавита.")
    assert not is_relevant("?", "X", "X — что-то")


# ============================================================
# 3. WebSearcher
# ============================================================

class _FakeResponse:
    status = 200

    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _install_wikipedia(monkeypatch, title: str, extract: str) -> list[str]:
    """Подменяет urlopen и возвращает список запрошенных URL."""
    import src.perception.web_search as web_module

    payload = {
        "query": {
            "pages": {
                "1": {
                    "title": title,
                    "extract": extract,
                    "fullurl": "https://example.org/wiki",
                }
            }
        }
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    calls: list[str] = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        return _FakeResponse(body)

    monkeypatch.setattr(web_module.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_web_searcher_strips_question_wrapper(monkeypatch):
    calls = _install_wikipedia(
        monkeypatch, "Альфа", "Альфа — первая буква греческого алфавита."
    )
    searcher = WebSearcher(lang="ru", fallback_to_en=False, rate_limit_sec=0)

    result = searcher.search("что такое альфа")

    assert result["found"] is True
    assert result["title"] == "Альфа"
    assert len(calls) == 1
    assert "titles=альфа" in urllib.parse.unquote(calls[0])


def test_web_searcher_rejects_disambiguation(monkeypatch):
    _install_wikipedia(
        monkeypatch,
        "S1",
        "S1, S01, S.I, S-1, S.1, Š-1 or S 1 may refer to:",
    )
    searcher = WebSearcher(lang="ru", fallback_to_en=False, rate_limit_sec=0)

    result = searcher.search("альфа")

    assert result["found"] is False
    assert result["error"] == "low_quality"


def test_web_searcher_rejects_irrelevant_article(monkeypatch):
    _install_wikipedia(
        monkeypatch, "Бета", "Бета — вторая буква греческого алфавита."
    )
    searcher = WebSearcher(lang="ru", fallback_to_en=False, rate_limit_sec=0)

    result = searcher.search("альфа")

    assert result["found"] is False
    assert result["error"] == "irrelevant"


def test_web_searcher_does_not_call_network_for_junk(monkeypatch):
    calls = _install_wikipedia(monkeypatch, "X", "X — что-то осмысленное тут.")
    searcher = WebSearcher(lang="ru", fallback_to_en=False, rate_limit_sec=0)

    for query in ("?", "s_1", "42"):
        result = searcher.search(query)
        assert result["found"] is False

    assert calls == []


def test_web_search_pipeline_normalizes_query():
    class RecordingSearcher:
        is_enabled = True

        def __init__(self):
            self.queries = []

        def search(self, query):
            self.queries.append(query)
            return {"found": False, "error": "no_pages"}

    searcher = RecordingSearcher()
    pipe = ThinkingPipeline(object(), web_searcher=searcher)

    pipe._search_web("что такое счастье")
    pipe._search_web("?")
    pipe._search_web("s_1")

    assert searcher.queries == ["счастье"]


# ============================================================
# 4. Запись в KB через ThinkingPipeline
# ============================================================

class _FakeMentalModels:
    def __init__(self):
        self.names = []

    def find_related_concepts(self, concept, max_distance=1):
        return []

    def encounter_concept(self, name, *args, **kwargs):
        self.names.append(name)


class _FakeAgent:
    def __init__(self):
        self.knowledge_base = {}
        self._known_definitions = {}
        self.mental_models = _FakeMentalModels()
        self.success_streak = 0
        self.cycle_count = 0
        self.name = "Fake"
        self.user_interaction = None

    def _prune_knowledge_base_if_needed(self):
        pass

    def _save_knowledge_base(self):
        pass

    def _check_goal_progress(self, concept, answered=False):
        pass


def _web_result(title, extract):
    return {
        "found": True,
        "title": title,
        "extract": extract,
        "url": "https://example.org/wiki",
        "lang": "ru",
        "error": None,
    }


def test_apply_web_result_rejects_disambiguation():
    agent = _FakeAgent()
    pipe = ThinkingPipeline(agent)
    web = _web_result("S1", "S1, S01, S.I, S-1, S.1, Š-1 or S 1 may refer to:")

    thought = pipe._apply_web_result("s_1", web, "fallback")

    assert thought == "fallback"
    assert agent.knowledge_base == {}
    assert agent.mental_models.names == []


def test_apply_web_result_saves_valid_entry():
    agent = _FakeAgent()
    pipe = ThinkingPipeline(agent)
    web = _web_result(
        "Счастье", "Счастье — состояние человека, которое соответствует наибольшей внутренней удовлетворённости."
    )

    thought = pipe._apply_web_result("что такое счастье", web, "fallback")

    assert "Нашёл в интернете" in thought
    assert "что такое счастье" in agent.knowledge_base
    # Узел графа — без вопросительной обёртки.
    assert agent.mental_models.names == ["счастье"]


# ============================================================
# 5. KnowledgeSubsystem
# ============================================================

def _subsystem(tmp_path):
    return KnowledgeSubsystem(
        agent_name="test", knowledge_file=str(tmp_path / "kb.json")
    )


def test_add_definition_rejects_garbage(tmp_path):
    kb = _subsystem(tmp_path)
    result = kb.add_definition("s_1", "S1 may refer to:")
    assert result["added"] is False
    assert result["reason"] == "placeholder"
    assert "s_1" not in kb.knowledge_base


def test_load_drops_garbage(tmp_path):
    path = tmp_path / "kb.json"
    path.write_text(
        json.dumps(
            {
                "s_1": "S1, S01, S.I, S-1, S.1, Š-1 or S 1 may refer to:",
                "что такое жизнь?": VALID_DEF,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    kb = _subsystem(tmp_path)
    assert kb.load() == 1
    assert "s_1" not in kb.knowledge_base
    assert kb.knowledge_base["что такое жизнь?"] == VALID_DEF


def test_save_cleans_garbage(tmp_path):
    kb = _subsystem(tmp_path)
    kb.knowledge_base["s_1"] = "S1, S01 may refer to:"
    kb.save()

    saved = json.loads((tmp_path / "kb.json").read_text(encoding="utf-8"))
    assert "s_1" not in saved
    assert "что такое жизнь?" in saved
