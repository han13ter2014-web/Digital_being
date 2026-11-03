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
- «Всеядность» (Питание-1): если точного заголовка нет — полнотекстовый
  поиск (list=search, до 3 кандидатов по рангу), затем Викисловарь,
  затем Викибуки («Источники-2»), затем EN. Каждый шаг — только после
  «не нашли», не после ошибки сети.
- «Источники-2»: отдельное окно в «сегодня» — ``search_news`` читает
  Викиновости. Новости — впечатления, не определения: в базу знаний и
  кэш они не идут, фильтры качества у них свои.
- Фильтры качества (is_valid_definition, is_relevant) применяются к
  каждому источнику одинаково: всеядность не значит «есть что попало».
- Graceful degradation: любая ошибка → {"found": False}, агент продолжает жить.
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

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
    WIKTIONARY_BASE_URL = "https://{lang}.wiktionary.org/w/api.php"
    # «Источники-2»: Викибуки — учебные тексты; Викиновости — не еда для
    # базы знаний, а окно в «сегодня» (см. search_news).
    WIKIBOOKS_BASE_URL = "https://{lang}.wikibooks.org/w/api.php"
    WIKINEWS_BASE_URL = "https://{lang}.wikinews.org/w/api.php"

    # Сколько кандидатов полнотекстового поиска проверять по рангу.
    SEARCH_CANDIDATES = 3

    # Причины «не нашли», при которых имеет смысл идти к следующему
    # источнику в цепочке. Сетевые ошибки цепочку прерывают: при
    # DNS-ошибке делать четыре запроса — учетверять время отказа.
    NOT_FOUND_REASONS = (
        "no_pages", "no_extract", "not_found",
        "low_quality", "irrelevant", "no_search_results",
    )

    # Источник находки → слот статистики found_by.
    _SOURCE_KIND = {
        "wikipedia:title": "title",
        "wikipedia:search": "search",
        "wiktionary:title": "wiktionary",
        "wikibooks:title": "wikibooks",
    }

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
        self._stats: Dict[str, Any] = {
            "hits": 0,         # найдено в кэше
            "cache_hits": 0,
            "network_calls": 0,
            "found": 0,        # найдено в Wikipedia
            "misses": 0,       # не найдено
            "errors": 0,       # сетевые/HTTP ошибки
            # Диета существа: из какого источника пришла находка.
            "found_by": {"title": 0, "search": 0, "wiktionary": 0,
                         "wikibooks": 0},
            # «Источники-2»: новости — не еда, а впечатления; считаются
            # отдельно от находок в базу знаний.
            "news_reads": 0,
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
        stats = dict(self._stats)
        stats["found_by"] = dict(self._stats["found_by"])
        return stats

    def clear_cache(self) -> None:
        """Очистить кэш."""
        self._cache.clear()

    def cache_size(self) -> int:
        """Сколько записей сейчас в кэше (для /web без приватного доступа)."""
        return len(self._cache)

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
                "source": str|None, # "wikipedia:title" / "wikipedia:search" /
                                    # "wiktionary:title" / "wikibooks:title";
                                    # None, если не найдено
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

        # Цепочка источников — существо всеядно, но детерминировано:
        # точный заголовок → полнотекстовый поиск → Викисловарь →
        # Викибуки → EN. Каждый следующий шаг — только после «не нашли»,
        # а не после ошибки сети: при DNS-отказе цепочка обрывается на
        # первом звене.
        result = self._fetch(query, lang=self.lang, source="wikipedia:title")

        if not result["found"] and result.get("error") in self.NOT_FOUND_REASONS:
            result = self._search_fulltext(query, self.lang)

        if not result["found"] and result.get("error") in self.NOT_FOUND_REASONS:
            result = self._fetch_wiktionary(query, self.lang)

        if not result["found"] and result.get("error") in self.NOT_FOUND_REASONS:
            result = self._fetch_wikibooks(query, self.lang)

        if (
            not result["found"]
            and self.fallback_to_en
            and self.lang != "en"
            and result.get("error") in self.NOT_FOUND_REASONS
        ):
            en_result = self._fetch(query, lang="en", source="wikipedia:title")
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
            "source": None,
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

    def _request_json(
        self, url: str, lang: str, query: str
    ) -> Tuple[Optional[dict], Optional[str]]:
        """Один HTTP GET → ``(data, None)`` или ``(None, причина)``.

        Любая ошибка превращается в строку-причину: поиск — необязательная
        активность, он не имеет права уронить цикл агента.
        """
        self._respect_rate_limit()
        self._stats["network_calls"] += 1

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
                    return None, f"http_{resp.status}"
                body = resp.read()
        except urllib.error.HTTPError as e:
            self._stats["errors"] += 1
            logger.warning(f"[WebSearcher] HTTP {e.code} для '{query}' (lang={lang}): {e.reason}")
            return None, f"http_{e.code}"
        except urllib.error.URLError as e:
            self._stats["errors"] += 1
            logger.warning(f"[WebSearcher] URL error для '{query}' (lang={lang}): {e.reason}")
            return None, "network_error"
        except (TimeoutError, OSError) as e:
            self._stats["errors"] += 1
            logger.warning(f"[WebSearcher] Timeout/OSError для '{query}' (lang={lang}): {e}")
            return None, "timeout"
        except Exception as e:
            # Неизвестная ошибка — никогда не валим цикл агента.
            self._stats["errors"] += 1
            logger.exception(f"[WebSearcher] Unexpected error для '{query}': {e}")
            return None, "unknown_error"

        try:
            return json.loads(body.decode("utf-8")), None
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._stats["errors"] += 1
            logger.warning(f"[WebSearcher] JSON decode error: {e}")
            return None, "json_error"

    def _fetch(
        self,
        query: str,
        lang: str,
        *,
        base_url: Optional[str] = None,
        source: str = "wikipedia:title",
        intro_only: bool = True,
        relevance_query: Optional[str] = None,
    ) -> dict:
        """Один запрос «дать статью по названию» к MediaWiki API.

        Использует action=query с prop=extracts|info для получения:
        - extracts (краткое извлечение, plaintext)
        - fullurl (канонический URL)

        ``base_url`` позволяет ходить не только в Wikipedia, но и в
        Викисловарь — API одинаковое. У словаря нет «введения», поэтому
        для него ``intro_only=False``: берём весь extract, обрезку до
        max_chars делает общий код ниже.

        ``relevance_query`` — исходный запрос для проверки релевантности.
        Полнотекстовый поиск подставляет сюда запрос пользователя: без
        этого кандидат проверялся бы на совпадение с собственным
        заголовком и проходил всегда.
        """
        params = {
            "action": "query",
            "prop": "extracts|info",
            "explaintext": "1",      # plaintext, без HTML
            "inprop": "url",
            "redirects": "1",        # следовать за редиректами
            "titles": query,
            "format": "json",
            "formatversion": "1",    # современный формат без обёртки ["query"]
        }
        if intro_only:
            params["exintro"] = "1"  # только введение (2-3 параграфа)
        url = (base_url or self.BASE_URL).format(lang=lang) + "?" + urllib.parse.urlencode(params)

        data, error = self._request_json(url, lang=lang, query=query)
        if error is not None or data is None:
            return self._empty(error or "json_error")

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
        relevance_query = relevance_query or query
        if not is_relevant(relevance_query, title, extract):
            self._stats["misses"] += 1
            logger.info(
                f"[WebSearcher] Статья '{title}' не относится к "
                f"'{relevance_query}' (lang={lang})"
            )
            return self._empty("irrelevant")

        # Обрезаем extract до max_chars.
        if len(extract) > self.max_chars:
            extract = extract[: self.max_chars].rsplit(" ", 1)[0] + "…"

        self._stats["found"] += 1
        kind = self._SOURCE_KIND.get(source, "title")
        self._stats["found_by"][kind] += 1
        logger.info(
            f"[WebSearcher] '{query}' (lang={lang}, {source}) → '{title}', "
            f"{len(extract)} символов"
        )

        return {
            "found": True,
            "title": title,
            "extract": extract.strip(),
            "url": fullurl,
            "lang": lang,
            "source": source,
            "error": None,
        }

    def _search_fulltext(self, query: str, lang: str) -> dict:
        """Полнотекстовый поиск: когда точного заголовка нет.

        Wikipedia API ``list=search`` возвращает кандидатов по рангу.
        Берём до SEARCH_CANDIDATES лучших и проверяем каждого теми же
        фильтрами качества, что и точное совпадение.
        """
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(self.SEARCH_CANDIDATES),
            "format": "json",
            "formatversion": "1",
        }
        url = self.BASE_URL.format(lang=lang) + "?" + urllib.parse.urlencode(params)

        data, error = self._request_json(url, lang=lang, query=query)
        if error is not None or data is None:
            return self._empty(error or "json_error")

        hits = (data.get("query") or {}).get("search") or []
        if not hits:
            self._stats["misses"] += 1
            return self._empty("no_search_results")

        last_error = "no_search_results"
        for hit in hits[: self.SEARCH_CANDIDATES]:
            title = str(hit.get("title") or "").strip()
            if not title:
                continue
            candidate = self._fetch(
                title, lang=lang,
                source="wikipedia:search",
                relevance_query=query,
            )
            if candidate["found"]:
                return candidate
            reason = candidate.get("error") or "not_found"
            if reason not in self.NOT_FOUND_REASONS:
                # Ошибка сети — не продолжаем перебор кандидатов.
                return candidate
            last_error = reason
        return self._empty(last_error)

    def _fetch_wiktionary(self, query: str, lang: str) -> dict:
        """Викисловарь — второй источник: короткие словарные определения.

        То же MediaWiki API, тот же разбор ответа и те же фильтры
        качества — меняется только адрес и отсутствие exintro.
        """
        return self._fetch(
            query,
            lang=lang,
            base_url=self.WIKTIONARY_BASE_URL,
            source="wiktionary:title",
            intro_only=False,
        )

    def _fetch_wikibooks(self, query: str, lang: str) -> dict:
        """Викибуки — четвёртое звено: учебные тексты.

        Википедия отвечает «что это», Викибуки — «как это устроено
        в деле»: для тем-навыков (садоводство, программирование) учебник
        питательнее определения. Те же фильтры качества, intro_only=False:
        у учебника нет «введения» в смысле extracts.
        """
        return self._fetch(
            query,
            lang=lang,
            base_url=self.WIKIBOOKS_BASE_URL,
            source="wikibooks:title",
            intro_only=False,
        )

    # Минимальная длина новостного текста: короче — скорее анонс, чем
    # новость, и впечатления не оставит.
    NEWS_MIN_CHARS = 150
    # Сколько новостных кандидатов проверять по рангу.
    NEWS_CANDIDATES = 3

    def search_news(self, query: str) -> dict:
        """Прочитать новость по теме — окно в «сегодня», а не еда.

        Новости сознательно НЕ идут в цепочку базы знаний: определение
        вечно, новость — про сейчас. Поэтому здесь свои фильтры: не
        «похоже ли на определение», а «непустой связный текст по теме».
        Найденное не кэшируется: новость должна быть свежей при каждом
        чтении. Любая ошибка — {"found": False}, цикл агента не валится.
        """
        if not self._enabled:
            return self._empty("disabled")

        query = normalize_concept_name((query or "").strip())
        if not is_worth_searching(query):
            self._stats["misses"] += 1
            return self._empty("not_worth_searching")

        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(self.NEWS_CANDIDATES),
            "format": "json",
            "formatversion": "1",
        }
        url = self.WIKINEWS_BASE_URL.format(lang=self.lang) + "?" + urllib.parse.urlencode(params)

        data, error = self._request_json(url, lang=self.lang, query=query)
        if error is not None or data is None:
            return self._empty(error or "json_error")

        hits = (data.get("query") or {}).get("search") or []
        if not hits:
            self._stats["misses"] += 1
            return self._empty("no_search_results")

        last_error = "no_search_results"
        for hit in hits[: self.NEWS_CANDIDATES]:
            title = str(hit.get("title") or "").strip()
            if not title:
                continue
            candidate = self._fetch_news_extract(title, query)
            if candidate["found"]:
                self._stats["news_reads"] += 1
                return candidate
            reason = candidate.get("error") or "not_found"
            if reason not in self.NOT_FOUND_REASONS:
                return candidate  # сеть отвалилась — не долбим кандидатов
            last_error = reason
        self._stats["misses"] += 1
        return self._empty(last_error)

    def _fetch_news_extract(self, title: str, relevance_query: str) -> dict:
        """Один новостной кандидат: текст + мягкие фильтры впечатления."""
        params = {
            "action": "query",
            "prop": "extracts|info",
            "explaintext": "1",
            "inprop": "url",
            "redirects": "1",
            "titles": title,
            "format": "json",
            "formatversion": "1",
        }
        url = self.WIKINEWS_BASE_URL.format(lang=self.lang) + "?" + urllib.parse.urlencode(params)

        data, error = self._request_json(url, lang=self.lang, query=title)
        if error is not None or data is None:
            return self._empty(error or "json_error")

        pages = (data.get("query") or {}).get("pages") or {}
        if not pages:
            return self._empty("no_pages")
        first_page = next(iter(pages.values()))
        page_title = first_page.get("title", "")
        extract = (first_page.get("extract") or "").strip()
        fullurl = first_page.get("fullurl", "")

        if len(extract) < self.NEWS_MIN_CHARS:
            return self._empty("no_extract")
        if not is_relevant(relevance_query, page_title, extract):
            return self._empty("irrelevant")

        if len(extract) > self.max_chars:
            extract = extract[: self.max_chars].rsplit(" ", 1)[0] + "…"

        logger.info(
            f"[WebSearcher] новость по '{relevance_query}' → "
            f"'{page_title}', {len(extract)} символов"
        )
        return {
            "found": True,
            "title": page_title,
            "extract": extract,
            "url": fullurl,
            "lang": self.lang,
            "source": "wikinews:search",
            "error": None,
        }