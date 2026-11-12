"""Тесты «Источники-2»: Викибуки в цепочке еды и Викиновости как впечатления.

Сеть не нужна: urllib замокан. Границы: Викибуки — четвёртое звено
(после Викисловаря, до EN), фильтры качества общие; новости — не еда:
не идут в базу знаний, не кэшируются, считаются отдельно; у read_news
честный кулдаун (прочитал и «не нашлось» — одинаково закрывают тему).
"""

import json
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.perception.web_search import WebSearcher


def _make_wiki_response(title: str, extract: str, fullurl: str) -> bytes:
    payload = {
        "batchcomplete": "",
        "query": {
            "pages": {
                "1": {
                    "pageid": 1,
                    "title": title,
                    "extract": extract,
                    "fullurl": fullurl,
                }
            }
        },
    }
    return json.dumps(payload).encode("utf-8")


def _make_empty_response() -> bytes:
    return json.dumps({"batchcomplete": "", "query": {"pages": {}}}).encode("utf-8")


def _make_search_response(titles) -> bytes:
    payload = {
        "batchcomplete": "",
        "query": {
            "searchinfo": {"totalhits": len(titles)},
            "search": [{"title": t} for t in titles],
        },
    }
    return json.dumps(payload).encode("utf-8")


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _make_searcher() -> WebSearcher:
    return WebSearcher(
        lang="ru",
        timeout=2.0,
        max_chars=500,
        rate_limit_sec=0.0,
        cache_size=3,
        fallback_to_en=True,
    )


class WikibooksChainTests(unittest.TestCase):
    """Викибуки — четвёртое звено цепочки еды."""

    def test_wikibooks_fallback_found(self):
        """Всё молчало — учебник кормит, источник помечен честно."""
        responses = [
            _FakeResponse(_make_empty_response()),  # RU заголовок
            _FakeResponse(_make_search_response([])),  # полнотекст пуст
            _FakeResponse(_make_empty_response()),  # Викисловарь пуст
            _FakeResponse(
                _make_wiki_response(  # Викибуки
                    "Садоводство",
                    "Садоводство — отрасль растениеводства, занимающаяся "
                    "выращиванием плодовых, ягодных и декоративных растений.",
                    "https://ru.wikibooks.org/wiki/Садоводство",
                )
            ),
        ]
        ws = _make_searcher()
        with patch("urllib.request.urlopen", side_effect=responses) as mock_urlopen:
            result = ws.search("садоводство")

        self.assertTrue(result["found"])
        self.assertEqual(result["source"], "wikibooks:title")
        self.assertEqual(ws._stats["found_by"]["wikibooks"], 1)
        books_url = mock_urlopen.call_args_list[3][0][0].full_url
        self.assertIn("ru.wikibooks.org", books_url)

    def test_wikibooks_rejects_disambiguation_then_en(self):
        """Фильтры качества работают и для Викибукс: плохой учебник → EN."""
        responses = [
            _FakeResponse(_make_empty_response()),
            _FakeResponse(_make_search_response([])),
            _FakeResponse(_make_empty_response()),
            _FakeResponse(
                _make_wiki_response(
                    "Луна",
                    "Луна — может означать: спутник, богиня и прочее.",
                    "https://ru.wikibooks.org/wiki/Луна",
                )
            ),
            _FakeResponse(_make_empty_response()),  # EN тоже пуст
        ]
        ws = _make_searcher()
        with patch("urllib.request.urlopen", side_effect=responses) as mock_urlopen:
            result = ws.search("луна")

        self.assertFalse(result["found"])
        self.assertEqual(mock_urlopen.call_count, 5)  # вся цепочка честно пройдена

    def test_chain_stops_at_wiktionary(self):
        """Викисловарь нашёл — Викибуки не дёргаются (нет лишних запросов)."""
        responses = [
            _FakeResponse(_make_empty_response()),
            _FakeResponse(_make_search_response([])),
            _FakeResponse(
                _make_wiki_response(
                    "прозрачность",
                    "Прозрачность — свойство среды пропускать свет.",
                    "https://ru.wiktionary.org/wiki/прозрачность",
                )
            ),
        ]
        ws = _make_searcher()
        with patch("urllib.request.urlopen", side_effect=responses) as mock_urlopen:
            result = ws.search("прозрачность")

        self.assertTrue(result["found"])
        self.assertEqual(result["source"], "wiktionary:title")
        self.assertEqual(mock_urlopen.call_count, 3)


class NewsSearchTests(unittest.TestCase):
    """Викиновости — впечатления о «сегодня», а не еда для базы знаний."""

    _NEWS_EXTRACT = (
        "Садоводство переживает новый виток интереса: городские жители "
        "всё чаще высаживают плодовые деревья на приусадебных участках. "
        "Эксперты связывают это с желанием людей быть ближе к природе "
        "и есть свежие яблоки прямо с ветки. Корреспонденты побывали "
        "на трёх участках и рассказывают, что там растёт."
    )

    def test_news_found_and_counted_separately(self):
        """Новость найдена, но это не еда: счётчики находок не растут."""
        responses = [
            _FakeResponse(_make_search_response(["Садоводство в городе"])),
            _FakeResponse(
                _make_wiki_response(
                    "Садоводство в городе",
                    self._NEWS_EXTRACT,
                    "https://ru.wikinews.org/wiki/Садоводство_в_городе",
                )
            ),
        ]
        ws = _make_searcher()
        with patch("urllib.request.urlopen", side_effect=responses) as mock_urlopen:
            result = ws.search_news("садоводство")

        self.assertTrue(result["found"])
        self.assertEqual(result["source"], "wikinews:search")
        self.assertEqual(ws._stats["news_reads"], 1)
        self.assertEqual(ws._stats["found"], 0)  # не еда
        news_url = mock_urlopen.call_args_list[0][0][0].full_url
        self.assertIn("ru.wikinews.org", news_url)

    def test_news_not_cached(self):
        """Новость должна быть свежей при каждом чтении: кэша нет."""
        ws = _make_searcher()
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(_make_search_response([])),
        ) as mock_urlopen:
            ws.search_news("садоводство")
            ws.search_news("садоводство")

        self.assertEqual(mock_urlopen.call_count, 2)

    def test_news_short_extract_rejected(self):
        """Анонс вместо новости впечатлением не является."""
        responses = [
            _FakeResponse(_make_search_response(["Короткая"])),
            _FakeResponse(
                _make_wiki_response(
                    "Короткая",
                    "Садоводство: анонс.",
                    "https://ru.wikinews.org/wiki/Короткая",
                )
            ),
        ]
        ws = _make_searcher()
        with patch("urllib.request.urlopen", side_effect=responses):
            result = ws.search_news("садоводство")

        self.assertFalse(result["found"])
        self.assertEqual(ws._stats["news_reads"], 0)

    def test_news_irrelevant_rejected(self):
        """Новость не о теме — не впечатление о теме."""
        responses = [
            _FakeResponse(_make_search_response(["Постороннее"])),
            _FakeResponse(
                _make_wiki_response(
                    "Постороннее",
                    "Футбольный матч завершился вничью; команды разошлись "
                    "миром, болельщики долго обсуждали судейство встречи "
                    "и погоду на стадионе, но к теме это не относится.",
                    "https://ru.wikinews.org/wiki/Постороннее",
                )
            ),
        ]
        ws = _make_searcher()
        with patch("urllib.request.urlopen", side_effect=responses):
            result = ws.search_news("садоводство")

        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "irrelevant")

    def test_news_network_error_honest(self):
        ws = _make_searcher()
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("DNS failure"),
        ):
            result = ws.search_news("садоводство")

        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "network_error")

    def test_news_disabled(self):
        ws = _make_searcher()
        ws.toggle(False)
        with patch("urllib.request.urlopen") as mock_urlopen:
            result = ws.search_news("садоводство")

        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "disabled")
        self.assertEqual(mock_urlopen.call_count, 0)


class _FakeAgent(SimpleNamespace):
    """SimpleNamespace + настоящие методы DigitalBeing (как в test_hunt)."""

    ACTION_ALIASES = DigitalBeing.ACTION_ALIASES

    _is_learnable = DigitalBeing._is_learnable
    _normalize_action = DigitalBeing._normalize_action
    _pick_news_topic = DigitalBeing._pick_news_topic
    _act_read_news = DigitalBeing._act_read_news
    _record_will = DigitalBeing._record_will
    _is_action_available = DigitalBeing._is_action_available


class _FakeWillRegistry:
    def __init__(self):
        self.records = []

    def record(self, will_type, topic, reason, **kwargs):
        self.records.append({"type": will_type, "topic": topic, "reason": reason})


def _make_news_searcher(result):
    searcher = SimpleNamespace(is_enabled=True, calls=[])
    searcher.search_news = lambda query: (searcher.calls.append(query), result)[1]
    return searcher


_NEWS_FOUND = {
    "found": True,
    "title": "Садоводство в городе",
    "extract": "Горожане высаживают яблони на крышах домов.",
    "url": "https://ru.wikinews.org/wiki/Садоводство_в_городе",
    "lang": "ru",
    "source": "wikinews:search",
    "error": None,
}

_NEWS_MISS = {
    "found": False,
    "title": "",
    "extract": "",
    "url": "",
    "lang": "ru",
    "source": None,
    "error": "no_search_results",
}


def _make_agent(searcher, cycle=10, goal_title="выучить садоводство"):
    agent = _FakeAgent(
        web_searcher=searcher,
        cycle_count=cycle,
        knowledge_base={"старая тема": "старое знание"},
        _news_reads={},
        active_goal={"title": goal_title} if goal_title else None,
        mental_models=SimpleNamespace(concepts={}),
        will_registry=_FakeWillRegistry(),
    )
    return agent


class ReadNewsActionTests(unittest.TestCase):
    """Действие read_news: впечатление, кулдаун, чистота базы знаний."""

    def test_found_news_leaves_impression_not_knowledge(self):
        searcher = _make_news_searcher(_NEWS_FOUND)
        agent = _make_agent(searcher)

        result = agent._act_read_news()

        self.assertIn("Садоводство в городе", result["text"])
        # Новость — не знание: база не пополнилась.
        self.assertEqual(agent.knowledge_base, {"старая тема": "старое знание"})
        # Но впечатление — волевой акт, записан.
        self.assertEqual(agent.will_registry.records[0]["type"], "news_reads")
        self.assertEqual(agent._news_reads["выучить садоводство"], agent.cycle_count)

    def test_cooldown_blocks_repeat_without_network(self):
        searcher = _make_news_searcher(_NEWS_FOUND)
        agent = _make_agent(searcher)

        first = agent._act_read_news()
        agent.cycle_count += 10
        second = agent._act_read_news()

        self.assertEqual(len(searcher.calls), 1)
        self.assertIn("недавно проверял", second["text"])
        self.assertNotEqual(first["text"], second["text"])

    def test_miss_also_cools_down_honestly(self):
        """«Не нашлось» тоже закрывает тему: ленту не долбят каждый цикл."""
        searcher = _make_news_searcher(_NEWS_MISS)
        agent = _make_agent(searcher)

        first = agent._act_read_news()
        agent.cycle_count += 10
        second = agent._act_read_news()

        self.assertIn("не нашлось", first["text"])
        self.assertEqual(len(searcher.calls), 1)
        self.assertIn("недавно проверял", second["text"])

    def test_disabled_searcher_refuses_honestly(self):
        searcher = _make_news_searcher(_NEWS_FOUND)
        searcher.is_enabled = False
        agent = _make_agent(searcher)

        result = agent._act_read_news()

        self.assertIn("выключен", result["text"])
        self.assertEqual(len(searcher.calls), 0)

    def test_news_topic_prefers_active_goal(self):
        agent = _make_agent(
            _make_news_searcher(_NEWS_MISS), goal_title="выучить садоводство"
        )
        self.assertEqual(agent._pick_news_topic(), "выучить садоводство")

    def test_news_topic_falls_back_to_known_concept(self):
        agent = _make_agent(_make_news_searcher(_NEWS_MISS), goal_title=None)
        agent.mental_models.concepts = {"садоводство": SimpleNamespace(confidence=0.9)}
        self.assertEqual(agent._pick_news_topic(), "садоводство")

    def test_news_topic_none_when_nothing_cares(self):
        agent = _make_agent(_make_news_searcher(_NEWS_MISS), goal_title=None)
        self.assertIsNone(agent._pick_news_topic())

    def test_availability_needs_searcher_and_topic(self):
        agent = _make_agent(_make_news_searcher(_NEWS_MISS))
        self.assertTrue(agent._is_action_available("read_news"))

        agent.web_searcher = None
        self.assertFalse(agent._is_action_available("read_news"))


if __name__ == "__main__":
    unittest.main()
