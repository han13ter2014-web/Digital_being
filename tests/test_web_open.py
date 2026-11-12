"""Тесты участка «Интернет-1»: search_web (компас) и open_page (страница).

Вся сеть замокана: urlopen подменяется, DNS — тоже, где нужен гард.
Проверяется: компас отдаёт ссылки, страница читается в чистый текст,
SSRF-гард отсекает localhost и приватные адреса (и после редиректа),
не-текст и пустышки отбраковываются, действие browse_web оставляет
впечатление (волевой акт), а не знание (knowledge_base нетронута).
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.perception.web_search import WebSearcher


def _ddg_payload(abstract="", url="", heading="", related=()) -> bytes:
    return json.dumps(
        {
            "AbstractText": abstract,
            "AbstractURL": url,
            "Heading": "Тема",
            "RelatedTopics": [
                {"Text": text, "FirstURL": first} for text, first in related
            ],
        }
    ).encode("utf-8")


_PAGE_HTML = (
    "<html><head><title>Городские сады</title>"
    "<style>body{color:red}</style></head>"
    "<body><script>track()</script>"
    "<h1>Городские сады</h1>"
    "<p>Жители мегаполисов разводят сады на крышах и балконах, "
    "превращая серые кварталы в зелёные оазисы. Такие проекты "
    "объединяют соседей и улучшают воздух в городе.</p>"
    "</body></html>"
)


class _FakeResponse:
    def __init__(
        self,
        body: bytes,
        status: int = 200,
        content_type: str = "text/html; charset=utf-8",
        final_url: str = "https://example.com/page",
    ):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._final_url = final_url

    def read(self, n: int = -1) -> bytes:
        return self._body if n is None or n < 0 else self._body[:n]

    def geturl(self) -> str:
        return self._final_url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class SearchWebTests(unittest.TestCase):
    """Компас: DuckDuckGo Instant Answer — ответ и ссылки."""

    def setUp(self):
        self.searcher = WebSearcher(rate_limit_sec=0)

    def test_compass_returns_abstract_and_links(self):
        body = _ddg_payload(
            abstract="Нейросеть — вычислительная модель.",
            url="https://ru.wikipedia.org/wiki/Нейросеть",
            related=[("Глубокое обучение — раздел", "https://example.com/dl")],
        )
        with patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
            result = self.searcher.search_web("нейросеть")
        self.assertTrue(result["found"])
        self.assertEqual(result["source"], "duckduckgo:instant")
        self.assertEqual(len(result["related"]), 1)
        self.assertEqual(result["related"][0]["url"], "https://example.com/dl")
        self.assertEqual(self.searcher._stats["web_queries"], 1)
        # Компас — не еда: счётчик находок базы знаний не вырос.
        self.assertEqual(self.searcher._stats["found"], 0)

    def test_compass_empty_is_honest_miss(self):
        with patch(
            "urllib.request.urlopen", return_value=_FakeResponse(_ddg_payload())
        ):
            result = self.searcher.search_web("садоводство")
        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "no_search_results")

    def test_compass_disabled_refuses(self):
        self.searcher.toggle(False)
        result = self.searcher.search_web("нейросеть")
        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "disabled")


class OpenPageTests(unittest.TestCase):
    """Чтение страницы: стрип HTML, границы, SSRF-гард."""

    def setUp(self):
        self.searcher = WebSearcher(rate_limit_sec=0)

    def test_page_is_read_as_clean_text(self):
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(_PAGE_HTML.encode("utf-8")),
        ):
            result = self.searcher.open_page("https://example.com/gardens")
        self.assertTrue(result["found"])
        self.assertEqual(result["source"], "web:page")
        self.assertEqual(result["title"], "Городские сады")
        self.assertIn("зелёные оазисы", result["extract"])
        self.assertNotIn("track()", result["extract"])
        self.assertNotIn("color:red", result["extract"])
        self.assertEqual(self.searcher._stats["pages_read"], 1)

    def test_localhost_and_private_are_refused_without_network(self):
        for url in (
            "http://127.0.0.1/admin",
            "http://localhost/",
            "http://192.168.0.1/router",
            "file:///etc/passwd",
            "ftp://example.com/x",
        ):
            result = self.searcher.open_page(url)
            self.assertFalse(result["found"], url)
            self.assertIn(result["error"], ("private_host", "bad_scheme"), url)
        self.assertEqual(self.searcher._stats["network_calls"], 0)

    def test_redirect_into_private_is_refused(self):
        resp = _FakeResponse(
            _PAGE_HTML.encode("utf-8"), final_url="http://169.254.1.1/meta"
        )
        with patch("urllib.request.urlopen", return_value=resp):
            result = self.searcher.open_page("https://example.com/start")
        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "private_host")

    def test_non_text_is_refused(self):
        resp = _FakeResponse(b"%PDF-1.4 ...", content_type="application/pdf")
        with patch("urllib.request.urlopen", return_value=resp):
            result = self.searcher.open_page("https://example.com/doc.pdf")
        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "not_text")

    def test_thin_page_is_refused(self):
        thin = "<html><body><p>ок</p></body></html>"
        with patch(
            "urllib.request.urlopen", return_value=_FakeResponse(thin.encode("utf-8"))
        ):
            result = self.searcher.open_page("https://example.com/thin")
        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "no_extract")

    def test_cyrillic_url_is_quoted_to_ascii(self):
        """Кириллица в пути не должна ронять запрос (UnicodeEncodeError)."""
        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            return _FakeResponse(_PAGE_HTML.encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = self.searcher.open_page(
                "https://ru.wikipedia.org/wiki/Нейронная_сеть"
            )
        self.assertTrue(result["found"])
        # Запрошенный URL — чистый ASCII, кириллица закодирована.
        captured["url"].encode("ascii")
        self.assertIn("%D0", captured["url"])

    def test_long_page_is_capped(self):
        big = "<html><body><p>" + ("слово " * 3000) + "</p></body></html>"
        with patch(
            "urllib.request.urlopen", return_value=_FakeResponse(big.encode("utf-8"))
        ):
            result = self.searcher.open_page("https://example.com/big")
        self.assertTrue(result["found"])
        self.assertLessEqual(
            len(result["extract"]), self.searcher.WEB_PAGE_MAX_CHARS + 1
        )
        self.assertTrue(result["extract"].endswith("…"))


# ----------------------------------------------------------------------
# Действие browse_web на уровне агента
# ----------------------------------------------------------------------


class _FakeAgent(SimpleNamespace):
    ACTION_ALIASES = DigitalBeing.ACTION_ALIASES

    _is_learnable = DigitalBeing._is_learnable
    _normalize_action = DigitalBeing._normalize_action
    _pick_news_topic = DigitalBeing._pick_news_topic
    _act_browse_web = DigitalBeing._act_browse_web
    _record_will = DigitalBeing._record_will
    _is_action_available = DigitalBeing._is_action_available


class _FakeWillRegistry:
    def __init__(self):
        self.records = []

    def record(self, will_type, topic, reason, **kwargs):
        self.records.append({"type": will_type, "topic": topic, "reason": reason})


_COMPASS = {
    "found": True,
    "title": "Садоводство",
    "extract": "Садоводство — отрасль растениеводства.",
    "url": "https://example.com/gardens",
    "related": [],
    "lang": "ru",
    "source": "duckduckgo:instant",
    "error": None,
}

_PAGE = {
    "found": True,
    "title": "Городские сады",
    "extract": "Жители мегаполисов разводят сады на крышах.",
    "url": "https://example.com/gardens",
    "lang": "ru",
    "source": "web:page",
    "error": None,
}

_MISS = {
    "found": False,
    "title": "",
    "extract": "",
    "url": "",
    "lang": "ru",
    "source": None,
    "error": "no_search_results",
}


def _make_web_searcher(compass=_COMPASS, page=_PAGE):
    searcher = SimpleNamespace(is_enabled=True, compass_calls=[], page_calls=[])
    searcher.search_web = lambda q: (searcher.compass_calls.append(q), compass)[1]
    searcher.open_page = lambda u: (searcher.page_calls.append(u), page)[1]
    return searcher


def _make_agent(searcher, cycle=10, goal_title="выучить садоводство"):
    return _FakeAgent(
        web_searcher=searcher,
        cycle_count=cycle,
        knowledge_base={"старая тема": "старое знание"},
        _web_browses={},
        active_goal={"title": goal_title} if goal_title else None,
        mental_models=SimpleNamespace(concepts={}),
        will_registry=_FakeWillRegistry(),
    )


class BrowseWebActionTests(unittest.TestCase):
    """browse_web: впечатление, кулдаун, чистота базы знаний."""

    def test_browse_leaves_impression_not_knowledge(self):
        searcher = _make_web_searcher()
        agent = _make_agent(searcher)

        result = agent._act_browse_web()

        self.assertIn("Городские сады", result["text"])
        self.assertEqual(agent.knowledge_base, {"старая тема": "старое знание"})
        self.assertEqual(agent.will_registry.records[0]["type"], "web_browses")
        self.assertEqual(agent._web_browses["выучить садоводство"], agent.cycle_count)
        # Компас дал ссылку, страница прочитана по ней.
        self.assertEqual(searcher.page_calls, ["https://example.com/gardens"])

    def test_cooldown_blocks_repeat_without_network(self):
        searcher = _make_web_searcher()
        agent = _make_agent(searcher)

        agent._act_browse_web()
        agent.cycle_count += 10
        second = agent._act_browse_web()

        self.assertEqual(len(searcher.compass_calls), 1)
        self.assertIn("недавно обошла", second["text"])

    def test_compass_miss_cools_down_honestly(self):
        searcher = _make_web_searcher(compass=_MISS)
        agent = _make_agent(searcher)

        first = agent._act_browse_web()
        agent.cycle_count += 10
        second = agent._act_browse_web()

        self.assertIn("ничего не подсказал", first["text"])
        self.assertEqual(len(searcher.compass_calls), 1)
        self.assertIn("недавно обошла", second["text"])

    def test_unreadable_page_is_honest(self):
        searcher = _make_web_searcher(page=_MISS)
        agent = _make_agent(searcher)

        result = agent._act_browse_web()

        self.assertIn("не читается", result["text"])
        self.assertEqual(len(agent.will_registry.records), 0)

    def test_disabled_searcher_refuses_honestly(self):
        searcher = _make_web_searcher()
        searcher.is_enabled = False
        agent = _make_agent(searcher)

        result = agent._act_browse_web()

        self.assertIn("выключен", result["text"])
        self.assertEqual(len(searcher.compass_calls), 0)

    def test_availability_needs_searcher_and_topic(self):
        agent = _make_agent(_make_web_searcher())
        self.assertTrue(agent._is_action_available("browse_web"))

        agent.web_searcher.is_enabled = False
        self.assertFalse(agent._is_action_available("browse_web"))


if __name__ == "__main__":
    unittest.main()
