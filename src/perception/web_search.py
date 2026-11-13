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
- «Интернет-1»: открытый веб. ``search_web`` — компас (DuckDuckGo
  Instant Answer, официальный API без ключа; живые поисковые выдачи
  закрыты капчей), ``open_page`` — чтение произвольной страницы с
  SSRF-гардом (только публичный http/https, текст, потолки по размеру).
  Страницы — впечатления, как новости: базу знаний не кормят.
- Фильтры качества (is_valid_definition, is_relevant) применяются к
  каждому источнику одинаково: всеядность не значит «есть что попало».
- Graceful degradation: любая ошибка → {"found": False}, агент продолжает жить.
"""

import html
import http.client
import ipaddress
import json
import logging
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from src.memory.knowledge_quality import (
    is_relevant,
    is_valid_definition,
    is_worth_searching,
    normalize_concept_name,
)


logger = logging.getLogger(__name__)


def _resolve_public_addresses(host, port):
    """Разрешить host и вернуть только публичные числовые адреса."""

    try:
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return [], "dns_error"
    addresses = []
    try:
        for family, _type, _proto, _canon, sockaddr in resolved:
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            ip = ipaddress.ip_address(sockaddr[0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return [], "private_host"
            addresses.append(str(ip))
    except ValueError:
        return [], "dns_error"
    if not addresses:
        return [], "dns_error"
    return addresses, None


def _create_public_connection(address, timeout, source_address):
    """Подключиться к числовому IP из проверенного DNS-ответа.

    HTTPConnection вызывает эту фабрику вместо socket.create_connection.
    Повторное разрешение имени при подключении не происходит: DNS rebinding
    не может подменить адрес между проверкой и отправкой HTTP-запроса.
    """

    host, port = address
    addresses, error = _resolve_public_addresses(host, port)
    if error is not None:
        raise urllib.error.URLError(error)
    last_error = None
    for ip in addresses:
        try:
            return socket.create_connection((ip, port), timeout, source_address)
        except OSError as exc:
            last_error = exc
    raise last_error


class _PublicHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _create_public_connection


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # TLS по-прежнему получает self.host для SNI и проверки сертификата.
        self._create_connection = _create_public_connection


class _PublicHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PublicHTTPConnection, req)


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicHTTPSConnection, req, context=self._context)


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Проверить каждый redirect до того, как opener перейдёт по нему."""

    def __init__(self, guard):
        self._guard = guard

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        error = self._guard(newurl)
        if error is not None:
            raise urllib.error.URLError(error)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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
        "no_pages",
        "no_extract",
        "not_found",
        "low_quality",
        "irrelevant",
        "no_search_results",
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
            "hits": 0,  # найдено в кэше
            "cache_hits": 0,
            "network_calls": 0,
            "found": 0,  # найдено в Wikipedia
            "misses": 0,  # не найдено
            "errors": 0,  # сетевые/HTTP ошибки
            # Диета существа: из какого источника пришла находка.
            "found_by": {"title": 0, "search": 0, "wiktionary": 0, "wikibooks": 0},
            # «Источники-2»: новости — не еда, а впечатления; считаются
            # отдельно от находок в базу знаний.
            "news_reads": 0,
            # «Интернет-1»: открытый веб. pages_read — прочитанные страницы
            # (впечатления, не определения), web_queries — запросы к
            # компасу (DuckDuckGo Instant Answer).
            "pages_read": 0,
            "web_queries": 0,
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
            with urllib.request.urlopen(  # nosec B310
                req, timeout=self.timeout
            ) as resp:
                if resp.status != 200:
                    self._stats["errors"] += 1
                    return None, f"http_{resp.status}"
                body = resp.read()
        except urllib.error.HTTPError as e:
            self._stats["errors"] += 1
            logger.warning(
                f"[WebSearcher] HTTP {e.code} для '{query}' (lang={lang}): {e.reason}"
            )
            return None, f"http_{e.code}"
        except urllib.error.URLError as e:
            self._stats["errors"] += 1
            logger.warning(
                f"[WebSearcher] URL error для '{query}' (lang={lang}): {e.reason}"
            )
            return None, "network_error"
        except (TimeoutError, OSError) as e:
            self._stats["errors"] += 1
            logger.warning(
                f"[WebSearcher] Timeout/OSError для '{query}' (lang={lang}): {e}"
            )
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
            "explaintext": "1",  # plaintext, без HTML
            "inprop": "url",
            "redirects": "1",  # следовать за редиректами
            "titles": query,
            "format": "json",
            "formatversion": "1",  # современный формат без обёртки ["query"]
        }
        if intro_only:
            params["exintro"] = "1"  # только введение (2-3 параграфа)
        url = (
            (base_url or self.BASE_URL).format(lang=lang)
            + "?"
            + urllib.parse.urlencode(params)
        )

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
                title,
                lang=lang,
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
        url = (
            self.WIKINEWS_BASE_URL.format(lang=self.lang)
            + "?"
            + urllib.parse.urlencode(params)
        )

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
        url = (
            self.WIKINEWS_BASE_URL.format(lang=self.lang)
            + "?"
            + urllib.parse.urlencode(params)
        )

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

    # ============================================================
    # «Интернет-1»: открытый веб — впечатления, не определения
    # ============================================================

    # Компас: DuckDuckGo Instant Answer API — официальный, без ключа.
    # Это НЕ полный поиск: мгновенный ответ + несколько связанных ссылок.
    # Живые поисковые выдачи (HTML) закрыты капчей для скриптов — проверено
    # вживую 2026-11-03 (DuckDuckGo html, Mojeek).
    DDG_INSTANT_URL = "https://api.duckduckgo.com/"
    # Сколько связанных ссылок отдавать существу.
    WEB_RELATED_LIMIT = 3
    # Страница читается с потолком по байтам и по символам текста.
    WEB_PAGE_MAX_BYTES = 500_000
    WEB_PAGE_MAX_CHARS = 4000
    # Короче — скорее визитка-заглушка, чем страница; впечатления не даст.
    WEB_PAGE_MIN_CHARS = 150

    _DDG_KL = {"ru": "ru-ru", "en": "us-en"}

    def search_web(self, query: str) -> dict:
        """Компас по открытому вебу: краткий ответ и ссылки для open_page.

        DuckDuckGo Instant Answer — не полнотекстовый поиск, а мгновенный
        ответ плюс горстка связанных тем. Его ценность для существа —
        ссылки: по ним она идёт читать сама через ``open_page``. Найденное
        не кэшируется и не кормит базу знаний напрямую.
        """
        if not self._enabled:
            return self._empty("disabled")

        query = normalize_concept_name((query or "").strip())
        if not is_worth_searching(query):
            self._stats["misses"] += 1
            return self._empty("not_worth_searching")

        params = {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
            "kl": self._DDG_KL.get(self.lang, "wt-wt"),
        }
        url = self.DDG_INSTANT_URL + "?" + urllib.parse.urlencode(params)

        data, error = self._request_json(url, lang=self.lang, query=query)
        if error is not None or data is None:
            return self._empty(error or "json_error")

        abstract = str(data.get("AbstractText") or "").strip()
        abstract_url = str(data.get("AbstractURL") or "").strip()
        heading = str(data.get("Heading") or "").strip()

        related: List[Dict[str, str]] = []
        for topic in data.get("RelatedTopics") or []:
            if not isinstance(topic, dict) or "Topics" in topic:
                continue  # вложенные группы пропускаем — берём плоские темы
            text = str(topic.get("Text") or "").strip()
            first_url = str(topic.get("FirstURL") or "").strip()
            if text and first_url:
                related.append({"text": text, "url": first_url})
            if len(related) >= self.WEB_RELATED_LIMIT:
                break

        if not abstract and not related:
            self._stats["misses"] += 1
            return self._empty("no_search_results")

        self._stats["web_queries"] += 1
        return {
            "found": True,
            "title": heading or query,
            "extract": abstract,
            "url": abstract_url,
            "related": related,
            "lang": self.lang,
            "source": "duckduckgo:instant",
            "error": None,
        }

    def _open_page_url(self, request):
        return urllib.request.build_opener(
            _GuardedRedirectHandler(self._url_guard),
            _PublicHTTPHandler(),
            _PublicHTTPSHandler(),
        ).open(request, timeout=self.timeout)

    def open_page(self, url: str) -> dict:
        """Прочитать произвольную страницу интернета — впечатление, не знание.

        Границы безопасности (это не полная ОС-изоляция, но бытовые ловушки
        закрыты):
        * только http/https;
        * хост не должен быть localhost, приватным, служебным или
          link-local адресом — проверяется до каждого запроса, на каждом
          редиректе и при подключении к проверенному числовому IP;
        * читаются только текстовые ответы (html/plain/xhtml);
        * потолки: WEB_PAGE_MAX_BYTES на сырой ответ, WEB_PAGE_MAX_CHARS
          на извлечённый текст;
        * общий rate limit и тот же User-Agent, что у вики-источников.

        Страница НЕ проходит фильтры «похоже на определение»: веб шумный,
        и его место — впечатления (дневник, реестр воли), а не база знаний.
        """
        if not self._enabled:
            return self._empty("disabled")

        url = (url or "").strip()
        guard_error = self._url_guard(url)
        if guard_error is not None:
            self._stats["misses"] += 1
            return self._empty(guard_error)
        url = self._quote_url(url)

        self._respect_rate_limit()
        self._stats["network_calls"] += 1
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
                    "Accept-Language": f"{self.lang},en;q=0.5",
                },
            )
            with self._open_page_url(req) as resp:
                if resp.status != 200:
                    self._stats["errors"] += 1
                    return self._empty(f"http_{resp.status}")
                # Дополнительная проверка финального URL после всех переходов.
                final_error = self._url_guard(resp.geturl())
                if final_error is not None:
                    self._stats["errors"] += 1
                    return self._empty(final_error)
                content_type = str(resp.headers.get("Content-Type") or "").lower()
                if not (
                    "text/html" in content_type
                    or "application/xhtml" in content_type
                    or content_type.startswith("text/plain")
                ):
                    self._stats["misses"] += 1
                    return self._empty("not_text")
                body = resp.read(self.WEB_PAGE_MAX_BYTES + 1)
                final_url = resp.geturl()
        except urllib.error.HTTPError as e:
            self._stats["errors"] += 1
            return self._empty(f"http_{e.code}")
        except urllib.error.URLError as e:
            self._stats["errors"] += 1
            logger.warning(f"[WebSearcher] URL error для страницы: {e.reason}")
            if e.reason in ("private_host", "dns_error", "bad_url", "bad_scheme"):
                return self._empty(e.reason)
            return self._empty("network_error")
        except (TimeoutError, OSError) as e:
            self._stats["errors"] += 1
            logger.warning(f"[WebSearcher] Timeout/OSError для страницы: {e}")
            return self._empty("timeout")
        except Exception as e:
            self._stats["errors"] += 1
            logger.exception(f"[WebSearcher] Unexpected error для страницы: {e}")
            return self._empty("unknown_error")

        if len(body) > self.WEB_PAGE_MAX_BYTES:
            body = body[: self.WEB_PAGE_MAX_BYTES]

        charset = "utf-8"
        match = re.search(r"charset=([\w.-]+)", content_type)
        if match:
            charset = match.group(1)
        raw = body.decode(charset, errors="replace")

        title, text = self._html_to_text(raw)
        if len(text) < self.WEB_PAGE_MIN_CHARS:
            self._stats["misses"] += 1
            return self._empty("no_extract")
        if len(text) > self.WEB_PAGE_MAX_CHARS:
            text = text[: self.WEB_PAGE_MAX_CHARS].rsplit(" ", 1)[0] + "…"

        self._stats["pages_read"] += 1
        logger.info(
            f"[WebSearcher] страница прочитана: {final_url!r} "
            f"({len(text)} символов)"
        )
        return {
            "found": True,
            "title": title or final_url,
            "extract": text,
            "url": final_url,
            "lang": self.lang,
            "source": "web:page",
            "error": None,
        }

    def _url_guard(self, url: str) -> Optional[str]:
        """Причина отказа или None: только публичный http/https."""

        try:
            parts = urllib.parse.urlsplit(url)
            if parts.scheme not in ("http", "https"):
                return "bad_scheme"
            host = parts.hostname
            if not host:
                return "bad_url"
            port = parts.port
        except ValueError:
            return "bad_url"
        _addresses, error = _resolve_public_addresses(host, port)
        return error

    @staticmethod
    def _quote_url(url: str) -> str:
        """Перевести URL в ASCII: кириллица в пути и запросе кодируется,
        хост — через IDNA. Уже закодированное (%XX) не трогается."""

        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        try:
            host_ascii = host.encode("idna").decode("ascii")
        except (UnicodeError, ValueError):
            host_ascii = host
        if parts.port is not None:
            host_ascii = f"{host_ascii}:{parts.port}"
        path = urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
        query = urllib.parse.quote(parts.query, safe="=&%?/:@!$'()*+,;-._~")
        return urllib.parse.urlunsplit(
            (parts.scheme, host_ascii, path, query, parts.fragment)
        )

    def _html_to_text(self, raw: str) -> Tuple[str, str]:
        """Грубый, но честный стрип HTML → (заголовок, текст)."""

        title = ""
        match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
        if match:
            title = html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()

        body = re.sub(
            r"<(script|style|noscript|template|svg|head)[^>]*>.*?</\1>",
            " ",
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        body = re.sub(r"<!--.*?-->", " ", body, flags=re.DOTALL)
        body = re.sub(r"<[^>]+>", " ", body)
        body = html.unescape(body)
        lines = [" ".join(line.split()) for line in body.splitlines()]
        text = "\n".join(line for line in lines if line).strip()
        return title, text
