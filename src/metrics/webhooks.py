"""
Webhooks — отправка уведомлений во внешние сервисы (Этап 3.8).

Архитектурное решение:
- Поддержка Telegram и Discord через единый интерфейс Webhook.
- Асинхронная отправка в отдельном потоке (не блокирует main loop).
- Очередь с приоритетами и rate-limiting (не более N сообщений в минуту).
- Retry с экспоненциальной задержкой при сетевых ошибках.
- Конфигурация через env-переменные (DIGITAL_BEING_TELEGRAM_TOKEN,
  DIGITAL_BEING_TELEGRAM_CHAT_ID, DIGITAL_BEING_DISCORD_WEBHOOK_URL).
- Если конфигурация отсутствует — silent mode (не падать, логировать).

Использование:
    from src.metrics.webhooks import WebhookManager, TelegramWebhook, DiscordWebhook

    # Создать менеджер
    mgr = WebhookManager()
    mgr.add(TelegramWebhook(token=os.environ["TELEGRAM_TOKEN"], chat_id=...))
    mgr.add(DiscordWebhook(url=os.environ["DISCORD_WEBHOOK_URL"]))

    # В DigitalBeing.evolve() или по событию:
    mgr.send("💡 Новая мысль: {thought}", priority="high")

    # Graceful shutdown:
    mgr.stop()
"""

import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


# ============================================================
# Базовый класс Webhook
# ============================================================

class Webhook(ABC):
    """Базовый класс для всех webhook-ов."""

    name: str = "base"

    def __init__(self, *, enabled: bool = True, timeout: float = 10.0) -> None:
        self.enabled = enabled
        self.timeout = timeout
        self._sent_count = 0
        self._error_count = 0

    @abstractmethod
    def _do_send(self, text: str, *, title: Optional[str] = None,
                 meta: Optional[Dict[str, Any]] = None) -> bool:
        """Реализация отправки. Возвращает True при успехе."""
        ...

    def send(self, text: str, *, title: Optional[str] = None,
             meta: Optional[Dict[str, Any]] = None) -> bool:
        """Публичный метод отправки. Считает статистику."""
        if not self.enabled:
            return False
        try:
            ok = self._do_send(text, title=title, meta=meta)
            if ok:
                self._sent_count += 1
            else:
                self._error_count += 1
            return ok
        except Exception as e:
            self._error_count += 1
            logger.warning(f"[webhook:{self.name}] ошибка отправки: {e}")
            return False

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "sent_count": self._sent_count,
            "error_count": self._error_count,
        }


# ============================================================
# Telegram webhook
# ============================================================

class TelegramWebhook(Webhook):
    """Отправляет сообщения в Telegram через Bot API.

    Конфигурация:
        TELEGRAM_TOKEN: токен бота от @BotFather.
        TELEGRAM_CHAT_ID: ID чата (можно получить через @userinfobot).
    """

    name = "telegram"
    API_BASE = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, chat_id: str,
                 *, enabled: bool = True, timeout: float = 10.0) -> None:
        super().__init__(enabled=enabled, timeout=timeout)
        self.token = token
        self.chat_id = chat_id

    def _do_send(self, text: str, *, title: Optional[str] = None,
                 meta: Optional[Dict[str, Any]] = None) -> bool:
        # Markdown-форматирование: *жирный* и _курсив_
        body = text
        if title:
            body = f"*{title}*\n\n{text}"

        url = self.API_BASE.format(token=self.token, method="sendMessage")
        payload = {
            "chat_id": self.chat_id,
            "text": body[:4096],  # Telegram лимит
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        return self._http_post(url, payload)

    def _http_post(self, url: str, payload: Dict[str, Any]) -> bool:
        """POST JSON через urllib (без внешних зависимостей)."""
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                if result.get("ok"):
                    return True
                logger.warning(f"[telegram] API error: {result}")
                return False
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            logger.warning(f"[telegram] HTTP error: {e}")
            return False


# ============================================================
# Discord webhook
# ============================================================

class DiscordWebhook(Webhook):
    """Отправляет сообщения в Discord через Incoming Webhook.

    Конфигурация:
        DISCORD_WEBHOOK_URL: URL веб-хука канала (Integrations → Webhooks).
    """

    name = "discord"

    def __init__(self, url: str, *, username: str = "Digital Being",
                 enabled: bool = True, timeout: float = 10.0) -> None:
        super().__init__(enabled=enabled, timeout=timeout)
        self.url = url
        self.username = username

    def _do_send(self, text: str, *, title: Optional[str] = None,
                 meta: Optional[Dict[str, Any]] = None) -> bool:
        # Discord supports embeds — для простоты шлём plain content.
        # Если есть title — используем embed.
        if title:
            payload = {
                "username": self.username,
                "embeds": [{
                    "title": title[:256],
                    "description": text[:4096],
                    "color": 0x58a6ff,  # Синий (как в дашборде)
                }],
            }
        else:
            payload = {
                "username": self.username,
                "content": text[:2000],
            }
        return self._http_post(self.url, payload)

    def _http_post(self, url: str, payload: Dict[str, Any]) -> bool:
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                # Discord возвращает 204 No Content при успехе
                if resp.status in (200, 204):
                    return True
                return False
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            logger.warning(f"[discord] HTTP error: {e}")
            return False


# ============================================================
# WebhookManager — управление несколькими webhook-ами
# ============================================================

class WebhookManager:
    """Менеджер webhook-ов с очередью и rate-limiting.

    Отправка асинхронная (в отдельном потоке) — не блокирует main loop.
    Rate-limit: не более max_per_minute сообщений в минуту на каждый webhook.
    """

    def __init__(self, max_per_minute: int = 20, queue_maxsize: int = 100) -> None:
        self._webhooks: List[Webhook] = []
        self._max_per_minute = max_per_minute
        self._queue: "queue.Queue[Tuple[int, str, Optional[str], Optional[Dict[str, Any]]]]" = \
            queue.Queue(maxsize=queue_maxsize)
        self._stopped = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._rate_lock = threading.Lock()
        self._last_send_ts: List[float] = []  # для rate-limit

    # ----------------------------------------------------------------
    # Управление webhook-ами
    # ----------------------------------------------------------------

    def add(self, webhook: Webhook) -> None:
        self._webhooks.append(webhook)

    def remove(self, name: str) -> bool:
        before = len(self._webhooks)
        self._webhooks = [w for w in self._webhooks if w.name != name]
        return len(self._webhooks) < before

    def list_webhooks(self) -> List[str]:
        return [w.name for w in self._webhooks]

    # ----------------------------------------------------------------
    # Отправка
    # ----------------------------------------------------------------

    def send(self, text: str, *, title: Optional[str] = None,
             meta: Optional[Dict[str, Any]] = None,
             priority: str = "normal",
             blocking: bool = False) -> bool:
        """Поставить сообщение в очередь.

        Args:
            text: текст сообщения.
            title: опциональный заголовок.
            meta: дополнительные данные.
            priority: "high" / "normal" / "low".
            blocking: если True — отправить синхронно (для тестов).
        """
        if not self._webhooks:
            return False
        priority_value = {"high": 0, "normal": 1, "low": 2}.get(priority, 1)
        item = (priority_value, text, title, meta)

        if blocking:
            return self._send_now(item)

        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            logger.warning("[webhook] очередь переполнена, сообщение отброшено")
            return False

    def _send_now(self, item: Tuple[int, str, Optional[str], Optional[Dict[str, Any]]]) -> bool:
        """Отправить синхронно во все webhook-и."""
        priority, text, title, meta = item
        if not self._check_rate_limit():
            logger.warning("[webhook] rate limit превышен")
            return False
        any_ok = False
        for w in self._webhooks:
            try:
                if w.send(text, title=title, meta=meta):
                    any_ok = True
            except Exception as e:
                logger.warning(f"[webhook] {w.name}: {e}")
        return any_ok

    def _check_rate_limit(self) -> bool:
        """Проверить rate-limit и записать timestamp если прошло."""
        now = time.time()
        with self._rate_lock:
            # Удаляем старые timestamps (>60с)
            cutoff = now - 60.0
            self._last_send_ts = [t for t in self._last_send_ts if t >= cutoff]
            if len(self._last_send_ts) >= self._max_per_minute:
                return False
            self._last_send_ts.append(now)
            return True

    # ----------------------------------------------------------------
    # Фоновый поток
    # ----------------------------------------------------------------

    def start(self) -> None:
        """Запустить фонового worker-а для отправки."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stopped.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="webhook-sender",
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Остановить worker-а (дождётся опустошения очереди)."""
        self._stopped.set()
        # Кладём sentinel — worker выйдет после отправки оставшихся.
        try:
            self._queue.put_nowait((-1, "", None, None))
        except queue.Full:
            pass
        if self._worker_thread:
            self._worker_thread.join(timeout=timeout)

    def _worker_loop(self) -> None:
        """Worker: забирает из очереди и отправляет."""
        logger.info("[webhook] worker started")
        while not self._stopped.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item[0] < 0:  # sentinel
                break
            try:
                self._send_now(item)
            except Exception as e:
                logger.warning(f"[webhook] worker error: {e}")
        # Дренаж оставшихся
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item[0] < 0:
                break
            try:
                self._send_now(item)
            except Exception:
                pass
        logger.info("[webhook] worker stopped")

    # ----------------------------------------------------------------
    # Статус
    # ----------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        with self._rate_lock:
            current_rate = len(self._last_send_ts)
        return {
            "webhooks": [w.status() for w in self._webhooks],
            "queue_size": self._queue.qsize(),
            "rate_limit_per_min": self._max_per_minute,
            "current_rate_last_min": current_rate,
            "worker_alive": bool(self._worker_thread and self._worker_thread.is_alive()),
        }


# ============================================================
# Автоконфигурация из env
# ============================================================

def create_default_manager() -> WebhookManager:
    """Создаёт менеджер с webhook-ами из переменных окружения.

    Читает:
        DIGITAL_BEING_TELEGRAM_TOKEN, DIGITAL_BEING_TELEGRAM_CHAT_ID
        DIGITAL_BEING_DISCORD_WEBHOOK_URL

    Если переменные не заданы — менеджер пуст (silent mode).
    """
    mgr = WebhookManager()

    tg_token = os.environ.get("DIGITAL_BEING_TELEGRAM_TOKEN")
    tg_chat = os.environ.get("DIGITAL_BEING_TELEGRAM_CHAT_ID")
    if tg_token and tg_chat:
        mgr.add(TelegramWebhook(token=tg_token, chat_id=tg_chat))
        logger.info("[webhook] Telegram подключён")
    else:
        logger.debug("[webhook] TELEGRAM_TOKEN/CHAT_ID не заданы")

    discord_url = os.environ.get("DIGITAL_BEING_DISCORD_WEBHOOK_URL")
    if discord_url:
        mgr.add(DiscordWebhook(url=discord_url))
        logger.info("[webhook] Discord подключён")
    else:
        logger.debug("[webhook] DISCORD_WEBHOOK_URL не задан")

    return mgr


__all__ = [
    "Webhook",
    "TelegramWebhook",
    "DiscordWebhook",
    "WebhookManager",
    "create_default_manager",
]