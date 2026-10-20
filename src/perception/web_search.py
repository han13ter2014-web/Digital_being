"""
WebSearcher — поиск информации в Wikipedia API.

Даёт агенту возможность «спросить интернет», когда:
- В собственной knowledge_base нет концепции.
- Пользователь не ответил / не знает.

Этап 2.5: альтернативный источник знаний для ThinkingPipeline.
Используется ТОЛЬКО как fallback — не заменяет собственные знания агента
и не отвечает пользователю вместо живого собеседника.

Особенности:
- Без внешних зависимостей (только stdlib: urllib, json, time).
- HTTPS, User-Agent обязателен (Wikipedia блокирует без него).
- Rate limit между запросами (этикет Wikipedia API).
- In-memory LRU-кэш для повторных запросов.
- Graceful fallback: RU → EN если RU пуст.
- Graceful degradation: любая ошибка → {"found": False}, агент продолжает жить.
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

from src.memory.knowledge_quality import (
    is_relevant,
    is_valid_definition,
    is_worth_searching,
    normalize_concept_name,
)


logger = logging.getLogger(__name__)


class WebSearcher:
    """Поиск в Wikipedia API с кэшированием и rate limiting.

    Пример:
        ws = WebSearcher(lang="ru")
        result = ws.search("что такое сознание")
        if result["found"]:
            print(result["title"], result["extract"][:200])
    """

    BASE_URL = "https://{lang}.wikipedia.org/w/api.php"

    def __init__(
        self,
        lang: str = "ru",
        timeout: float = 5.0,
        max_chars: int = 2000,
        rate_limit_sec: float = 2.0,
        user_agent: str = "DigitalBeing/2.5",
        cache_size: int = 100,
        fallback_to_en: bool = True,
    ):
        """
        Args:
            lang: "ru" или "en".
            timeout: секунд на HTTP-запрос.
            max_chars: максимум символов извлечения (Wikipedia может вернуть больше).
            rate_limit_sec: минимальная пауза между запросами.
            user_agent: HTTP User-Agent (Wikipedia требует содержательный UA).
            cache_size: размер LRU-кэша в памяти.
            fallback_to_en: если RU не дал результата — попробовать EN.
        """
        self.lang = lang
        self.timeout = timeout
        self.max_chars = max_chars
        self.rate_limit_sec = rate_limit_sec
        self.user_agent = user_agent
        self.cache_size = max(0, cache_size)
        self.fallback_to_en = fallback_to_en

        # LRU-кэш: OrderedDict для простого LRU по порядку вставки.
        self._cache: "OrderedDict[str, dict]" = OrderedDict()

        # Состояние.
        self._last_request_ts = 0.0
        self._enabled = True

        # Статистика для отладки.
        self._stats = {
            "hits": 0,         # найдено в кэше
            "cache_hits": 0,
            "network_calls": 0,
            "found": 0,        # найдено в Wikipedia
            "misses": 0,       # не найдено
            "errors": 0,       # сетевые/HTTP ошибки
        }

    # ============================================================
    # Управление
    # ============================================================

    def toggle(self, enabled: bool) -> None:
        """Включить/выключить (для команды /web on|off)."""
        self._enabled = bool(enabled)
        logger.info(f"[WebSearcher] {'включён' if self._enabled else 'выключен'}")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def get_stats(self) -> dict:
        """Статистика для дашборда."""
        return dict(self._stats)

    def clear_cache(self) -> None:
        """Очистить кэш."""
        self._cache.clear()

    # ============================================================
    # Поиск
    # ============================================================

    def search(self, query: str) -> dict:
        """Поиск по Wikipedia.

        Args:
            query: запрос (например, "что такое сознание" или "сознание").

        Returns:
            dict: {
                "found": bool,
                "title": str,       # заголовок статьи
                "extract": str,     # текст (до max_chars)
                "url": str,         # ссылка на статью
                "lang": str,        # "ru" или "en"
                "error": str|None,  # описание ошибки, если есть
            }
        """
        if not self._enabled:
            return self._empty("disabled")

        query = (query or "").strip()
        if not query:
            return self._empty("empty_query")

        # В Wikipedia идём с чистым названием концепции, а не с целым
        # вопросом. Мусорные запросы («?», «s_1») отсекаем до сети.
        query = normalize_concept_name(query)
        if not is_worth_searching(query):
            self._stats["misses"] += 1
            logger.info(f"[WebSearcher] Запрос отклонён как неинформативный: {query!r}")
            return self._empty("not_worth_searching")

        # Нормализуем запрос для кэша: lower + strip.
        cache_key = f"{self.lang}:{query.lower()}"
        if cache_key in self._cache:
            self._stats["cache_hits"] += 1
            # LRU touch.
            self._cache.move_to_end(cache_key)
            return dict(self._cache[cache_key])

        # Сначала пробуем основной язык.
        result = self._fetch(query, lang=self.lang)

        # Если ничего не нашли и включён фоллбэк — пробуем EN.
        # Делаем фоллбэк ТОЛЬКО если первая попытка была "не нашли" (no_*),
        # а не "ошибка сети". Иначе при DNS-ошибке делаем 2 запроса и удваиваем
        # время отказа.
        NOT_FOUND_REASONS = (
            "no_pages", "no_extract", "not_found",
            "low_quality", "irrelevant",
        )
        if (
            not result["found"]
            and self.fallback_to_en
            and self.lang != "en"
            and result.get("error") in NOT_FOUND_REASONS
        ):
            en_result = self._fetch(query, lang="en")
            # Если EN нашёл — берём его.
            if en_result["found"]:
                result = en_result

        # Сохраняем в кэш.
        if self.cache_size > 0:
            self._cache[cache_key] = dict(result)
            self._cache.move_to_end(cache_key)
            # LRU eviction.
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

        return result

    def lookup(self, concept: str) -> dict:
        """Алиас для ThinkingPipeline / mental_models.

        Используется когда агент проверяет «знаю ли я это» и идёт в web.
        """
        return self.search(concept)

    # ============================================================
    # Внутреннее
    # ============================================================

    def _empty(self, reason: str = "not_found") -> dict:
        return {
            "found": False,
            "title": "",
            "extract": "",
            "url": "",
            "lang": self.lang,
            "error": reason,
        }

    def _respect_rate_limit(self) -> None:
        """Спим сколько нужно, чтобы не превысить rate_limit."""
        if self.rate_limit_sec <= 0:
            return
        elapsed = time.time() - self._last_request_ts
        if elapsed < self.rate_limit_sec:
            sleep_for = self.rate_limit_sec - elapsed
            time.sleep(sleep_for)
        self._last_request_ts = time.time()

    def _fetch(self, query: str, lang: str) -> dict:
        """Один HTTP-запрос к Wikipedia API.

        Использует action=query с prop=extracts|info для получения:
        - extracts (краткое извлечение, plaintext)
        - fullurl (канонический URL)
        """
        self._respect_rate_limit()
        self._stats["network_calls"] += 1

        params = {
            "action": "query",
            "prop": "extracts|info",
            "exintro": "1",          # только введение (2-3 параграфа)
            "explaintext": "1",      # plaintext, без HTML
            "inprop": "url",
            "redirects": "1",        # следовать за редиректами
            "titles": query,
            "format": "json",
            "formatversion": "1",    # современный формат без обёртки ["query"]
        }
        url = self.BASE_URL.format(lang=lang) + "?" + urllib.parse.urlencode(params)

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                    "Accept-Language": f"{lang},en;q=0.5",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    self._stats["errors"] += 1
                    return self._empty(f"http_{resp.status}")
                body = resp.read()
        except urllib.error.HTTPError as e:
            self._stats["errors"] += 1
            logger.warning(f"[WebSearcher] HTTP {e.code} для '{query}' (lang={lang}): {e.reason}")
            return self._empty(f"http_{e.code}")
        except urllib.error.URLError as e:
            self._stats["errors"] += 1
            logger.warning(f"[WebSearcher] URL error для '{query}' (lang={lang}): {e.reason}")
            return self._empty("network_error")
        except (TimeoutError, OSError) as e:
            self._stats["errors"] += 1
            logger.warning(f"[WebSearcher] Timeout/OSError для '{query}' (lang={lang}): {e}")
            return self._empty("timeout")
        except Exception as e:
            # Неизвестная ошибка — никогда не валим цикл агента.
            self._stats["errors"] += 1
            logger.exception(f"[WebSearcher] Unexpected error для '{query}': {e}")
            return self._empty("unknown_error")

        # Парсим JSON.
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._stats["errors"] += 1
            logger.warning(f"[WebSearcher] JSON decode error: {e}")
            return self._empty("json_error")

        # Структура ответа: {"query": {"pages": {"<pageid>": {title, extract, fullurl}}}}
        pages = (data.get("query") or {}).get("pages") or {}
        if not pages:
            self._stats["misses"] += 1
            return self._empty("no_pages")

        # Берём первую страницу.
        # Wikipedia возвращает pages как dict, где ключ — pageid (str).
        first_page = next(iter(pages.values()))
        title = first_page.get("title", "")
        extract = first_page.get("extract", "")
        fullurl = first_page.get("fullurl", "")

        # Если нет extract — статья пустая (например, disambiguation).
        if not extract or not extract.strip():
            self._stats["misses"] += 1
            return self._empty("no_extract")

        # Страницы-неоднозначности («S1 ... may refer to:») и слишком
        # короткие ответы знанием не являются.
        if not is_valid_definition(extract):
            self._stats["misses"] += 1
            logger.info(
                f"[WebSearcher] Низкое качество статьи '{title}' "
                f"(lang={lang}): {extract[:60]!r}"
            )
            return self._empty("low_quality")

        # Статья должна хоть как-то относиться к запросу.
        if not is_relevant(query, title, extract):
            self._stats["misses"] += 1
            logger.info(
                f"[WebSearcher] Статья '{title}' не относится к '{query}' "
                f"(lang={lang})"
            )
            return self._empty("irrelevant")

        # Обрезаем extract до max_chars.
        if len(extract) > self.max_chars:
            extract = extract[: self.max_chars].rsplit(" ", 1)[0] + "…"

        self._stats["found"] += 1
        logger.info(
            f"[WebSearcher] '{query}' (lang={lang}) → '{title}', "
            f"{len(extract)} символов"
        )

        return {
            "found": True,
            "title": title,
            "extract": extract.strip(),
            "url": fullurl,
            "lang": lang,
            "error": None,
        }