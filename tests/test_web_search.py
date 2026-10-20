"""Тесты для WebSearcher — все с моком urllib, сеть не нужна."""
import json
import unittest
from collections import OrderedDict
from unittest.mock import MagicMock, patch

from src.perception.web_search import WebSearcher


def _make_wiki_response(title: str, extract: str, fullurl: str) -> bytes:
    """Создаёт фейковый JSON-ответ Wikipedia API."""
    payload = {
        "batchcomplete": "",
        "query": {
            "pages": {
                "12345": {
                    "pageid": 12345,
                    "title": title,
                    "extract": extract,
                    "fullurl": fullurl,
                }
            }
        },
    }
    return json.dumps(payload).encode("utf-8")


def _make_empty_response() -> bytes:
    """Пустой ответ от Wikipedia (нет страниц)."""
    payload = {
        "batchcomplete": "",
        "query": {"pages": {}},
    }
    return json.dumps(payload).encode("utf-8")


def _make_missing_extract_response() -> bytes:
    """Страница без extract (disambiguation)."""
    payload = {
        "batchcomplete": "",
        "query": {
            "pages": {
                "999": {
                    "pageid": 999,
                    "title": "Some Title",
                    "extract": "",
                    "fullurl": "https://ru.wikipedia.org/wiki/Some_Title",
                }
            }
        },
    }
    return json.dumps(payload).encode("utf-8")


class _FakeResponse:
    """Подделка HTTPResponse для urllib."""
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class WebSearcherTests(unittest.TestCase):
    """Тесты WebSearcher."""

    def setUp(self):
        # rate_limit=0 → тесты не спят.
        self.ws = WebSearcher(
            lang="ru", timeout=2.0, max_chars=500,
            rate_limit_sec=0.0, cache_size=3, fallback_to_en=True,
        )

    # ---------- Базовые сценарии ----------

    def test_search_found(self):
        """Успешный поиск — есть результат."""
        fake_body = _make_wiki_response(
            "Сознание",
            "Сознание — состояние психической жизни человека, выражающееся "
            "в субъективном переживании...",
            "https://ru.wikipedia.org/wiki/Сознание",
        )
        with patch("urllib.request.urlopen", return_value=_FakeResponse(fake_body)):
            result = self.ws.search("что такое сознание")

        self.assertTrue(result["found"])
        self.assertEqual(result["title"], "Сознание")
        self.assertIn("состояние психической жизни", result["extract"])
        self.assertEqual(result["lang"], "ru")
        self.assertEqual(result["error"], None)
        self.assertEqual(self.ws._stats["found"], 1)

    def test_search_empty_pages(self):
        """Wikipedia не нашла страниц."""
        with patch("urllib.request.urlopen", return_value=_FakeResponse(_make_empty_response())):
            result = self.ws.search("xyzzzzzz no such concept")

        # Основной язык RU не нашёл, fallback на EN тоже не нашёл →
        # отдаём как not_found.
        self.assertFalse(result["found"])
        # При фоллбэке на EN — там тоже пусто, итог not_found.
        self.assertIn(result["error"], ("no_pages", "no_extract"))

    def test_search_no_extract(self):
        """Страница без extract (disambig)."""
        with patch("urllib.request.urlopen", return_value=_FakeResponse(_make_missing_extract_response())):
            result = self.ws.search("Луна")

        # RU вернул no_extract → пробуем EN (тоже пустой) → not_found.
        self.assertFalse(result["found"])

    def test_search_user_agent_in_request(self):
        """User-Agent обязательно передаётся в запросе."""
        fake_body = _make_wiki_response(
            "Сознание",
            "Сознание — состояние психической жизни человека.",
            "https://ru.wikipedia.org/wiki/Сознание",
        )
        with patch("urllib.request.urlopen", return_value=_FakeResponse(fake_body)) as mock_urlopen:
            self.ws.search("сознание")
            call_args = mock_urlopen.call_args
            request_obj = call_args[0][0]
            # urllib нормализует имя заголовка до "User-agent" (HTTP-стиль).
            # Ищем case-insensitive.
            ua_value = None
            for key, val in request_obj.headers.items():
                if key.lower() == "user-agent":
                    ua_value = val
                    break
            self.assertIsNotNone(ua_value, f"User-Agent не найден в {dict(request_obj.headers)}")
            self.assertEqual(ua_value, "DigitalBeing/2.5")

    # ---------- Кэш ----------

    def test_cache_hit(self):
        """Повторный запрос отдаёт из кэша без HTTP-вызова."""
        fake_body = _make_wiki_response(
            "Сознание",
            "Сознание — состояние психической жизни человека.",
            "https://ru.wikipedia.org/wiki/Сознание",
        )
        with patch("urllib.request.urlopen", return_value=_FakeResponse(fake_body)) as mock_urlopen:
            r1 = self.ws.search("сознание")  # HTTP-вызов
            r2 = self.ws.search("Сознание")  # cache_hit
            r3 = self.ws.search("СОЗНАНИЕ")  # тоже cache_hit (lower в ключе)

        self.assertEqual(mock_urlopen.call_count, 1)  # только первый раз
        self.assertEqual(self.ws._stats["cache_hits"], 2)
        self.assertEqual(r1["title"], r2["title"])
        self.assertEqual(r2["title"], r3["title"])

    def test_cache_lru_eviction(self):
        """При переполнении кэша вытесняется самый старый."""
        fake_body = _make_wiki_response(
            "Понятие",
            "Понятие — это альфа, бета, гамма, дельта и эпсилон.",
            "https://ru.wikipedia.org/wiki/Понятие",
        )
        queries = ["альфа", "бета", "гамма", "дельта", "эпсилон"]
        with patch("urllib.request.urlopen", return_value=_FakeResponse(fake_body)):
            # cache_size=3, добавим 5 разных запросов.
            for query in queries:
                self.ws.search(query)

        # Должно остаться только 3 последних: гамма, дельта, эпсилон.
        self.assertEqual(len(self.ws._cache), 3)
        self.assertNotIn("ru:альфа", self.ws._cache)
        self.assertNotIn("ru:бета", self.ws._cache)
        self.assertIn("ru:гамма", self.ws._cache)
        self.assertIn("ru:эпсилон", self.ws._cache)

    # ---------- Fallback RU → EN ----------

    def test_fallback_ru_to_en(self):
        """Если RU не нашёл, пробуем EN."""
        empty_ru = _make_empty_response()
        en_body = _make_wiki_response(
            "Consciousness",
            "Consciousness is the state of being aware...",
            "https://en.wikipedia.org/wiki/Consciousness",
        )

        # Первый вызов (RU) — пустой. Второй (EN) — найдено.
        responses = [_FakeResponse(empty_ru), _FakeResponse(en_body)]
        with patch("urllib.request.urlopen", side_effect=responses):
            result = self.ws.search("Consciousness")

        self.assertTrue(result["found"])
        self.assertEqual(result["lang"], "en")
        self.assertEqual(result["title"], "Consciousness")

    def test_fallback_disabled(self):
        """Если fallback выключен — RU-only."""
        ws_no_fb = WebSearcher(
            lang="ru", timeout=2.0, rate_limit_sec=0.0,
            cache_size=0, fallback_to_en=False,
        )
        with patch("urllib.request.urlopen", return_value=_FakeResponse(_make_empty_response())) as mock_urlopen:
            result = ws_no_fb.search("xyzzz")

        self.assertFalse(result["found"])
        self.assertEqual(mock_urlopen.call_count, 1)  # только RU, без EN

    # ---------- Ошибки ----------

    def test_http_error(self):
        """HTTP 404 / 5xx → graceful fail."""
        import urllib.error
        err = urllib.error.HTTPError(
            url="https://ru.wikipedia.org/w/api.php",
            code=503, msg="Service Unavailable", hdrs=None, fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=err):
            result = self.ws.search("сознание")

        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "http_503")
        self.assertEqual(self.ws._stats["errors"], 1)
        # При HTTP-ошибке fallback на EN НЕ срабатывает (сетевая ошибка).
        # Поэтому только один HTTP-вызов.
        # (Это проверяется ниже через mock_urlopen.call_count если нужно.)

    def test_network_error(self):
        """URLError → graceful fail без fallback."""
        import urllib.error
        err = urllib.error.URLError("DNS failure")
        with patch("urllib.request.urlopen", side_effect=err):
            result = self.ws.search("сознание")

        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "network_error")

    def test_timeout(self):
        """TimeoutError → graceful fail."""
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")):
            result = self.ws.search("сознание")

        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "timeout")

    def test_disabled(self):
        """Когда выключен — возвращает disabled без HTTP."""
        self.ws.toggle(False)
        with patch("urllib.request.urlopen") as mock_urlopen:
            result = self.ws.search("anything")

        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "disabled")
        self.assertEqual(mock_urlopen.call_count, 0)

    def test_empty_query(self):
        """Пустой запрос → empty_query."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            r1 = self.ws.search("")
            r2 = self.ws.search("   ")
            r3 = self.ws.search(None)

        self.assertEqual(r1["error"], "empty_query")
        self.assertEqual(r2["error"], "empty_query")
        self.assertEqual(r3["error"], "empty_query")
        self.assertEqual(mock_urlopen.call_count, 0)

    # ---------- Обрезка extract ----------

    def test_max_chars_truncation(self):
        """Длинный extract обрезается до max_chars с многоточием."""
        long_extract = "Слово " * 200  # ~1200 символов
        fake_body = _make_wiki_response("Long", long_extract, "https://ru.wikipedia.org/wiki/Long")
        with patch("urllib.request.urlopen", return_value=_FakeResponse(fake_body)):
            # max_chars=500
            ws2 = WebSearcher(lang="ru", max_chars=500, rate_limit_sec=0.0, cache_size=0)
            result = ws2.search("Long")

        self.assertTrue(result["found"])
        self.assertLessEqual(len(result["extract"]), 502)  # 500 + "…"
        self.assertTrue(result["extract"].endswith("…"))

    # ---------- Toggle / Stats ----------

    def test_toggle(self):
        """toggle включает/выключает."""
        self.assertTrue(self.ws.is_enabled)
        self.ws.toggle(False)
        self.assertFalse(self.ws.is_enabled)
        self.ws.toggle(True)
        self.assertTrue(self.ws.is_enabled)

    def test_stats(self):
        """Статистика обновляется."""
        fake_body = _make_wiki_response(
            "Сознание",
            "Сознание — состояние психической жизни человека.",
            "https://ru.wikipedia.org/wiki/Сознание",
        )
        with patch("urllib.request.urlopen", return_value=_FakeResponse(fake_body)):
            self.ws.search("сознание")
            self.ws.search("сознание")  # cache hit
        s = self.ws.get_stats()
        self.assertEqual(s["found"], 1)
        self.assertEqual(s["cache_hits"], 1)
        self.assertEqual(s["network_calls"], 1)

    def test_clear_cache(self):
        """clear_cache очищает."""
        fake_body = _make_wiki_response(
            "Сознание",
            "Сознание — состояние психической жизни человека.",
            "https://ru.wikipedia.org/wiki/Сознание",
        )
        with patch("urllib.request.urlopen", return_value=_FakeResponse(fake_body)):
            self.ws.search("сознание")
        self.assertEqual(len(self.ws._cache), 1)
        self.ws.clear_cache()
        self.assertEqual(len(self.ws._cache), 0)


if __name__ == "__main__":
    unittest.main()