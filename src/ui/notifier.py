"""
Notifier — кросс-платформенные OS-уведомления.

Подписывается на EventBus и показывает уведомления, когда:
- ENERGY_LOW (низкая/критическая энергия)
- AGENT_EVOLVED (интеллект вырос — радостное событие)
- AGENT_WANTS_TO_SPEAK (агент хочет что-то сказать)
- GOAL_COMPLETED (цель достигнута)

Использует plyer (кросс-платформенный):
- Windows: balloon notification
- macOS: Notification Center
- Linux: libnotify / notify-send

Если plyer недоступен — fallback на console print (чтобы не падать).

Защита от спама: TRAY_NOTIFICATION_COOLDOWN_SEC между уведомлениями.
"""

import logging
import time

from config.simulation_config import LR_CONFIG
from src.core.event_bus import EventBus, Events


logger = logging.getLogger(__name__)


# Пробуем импортировать plyer (опциональная зависимость)
try:
    from plyer import notification as _plyer_notification
    _HAS_PLYER = True
except ImportError:
    _HAS_PLYER = False
    logger.warning("plyer недоступен — уведомления ОС будут писаться в лог")


class Notifier:
    """Подписчик EventBus, который показывает OS-уведомления."""

    def __init__(self, bus: EventBus, app_name: str = "Digital Being"):
        """
        Args:
            bus: EventBus, на который подписываемся.
            app_name: имя приложения в уведомлении (например, "Alpha").
        """
        self.bus = bus
        self.app_name = app_name

        # Защита от спама
        self._last_notification_ts: float = 0.0
        self._suppressed_until_ts: float = 0.0

        # Подписки
        self._setup_subscriptions()

        logger.info(
            f"[Notifier] Инициализирован. plyer={'доступен' if _HAS_PLYER else 'НЕТ'}"
        )

    def _setup_subscriptions(self) -> None:
        """Подписаться на события, на которые Notifier должен реагировать."""
        self.bus.subscribe(Events.ENERGY_LOW, self._on_energy_low)
        self.bus.subscribe(Events.ENERGY_RECOVERED, self._on_energy_recovered)
        self.bus.subscribe(Events.AGENT_EVOLVED, self._on_agent_evolved)
        self.bus.subscribe(Events.AGENT_WANTS_TO_SPEAK, self._on_agent_speaks)
        self.bus.subscribe(Events.GOAL_COMPLETED, self._on_goal_completed)

    # ============================================================
    # Cooldown / спам-защита
    # ============================================================

    def _can_notify(self) -> bool:
        """True, если можем показать уведомление (не в cooldown)."""
        now = time.time()
        if now < self._suppressed_until_ts:
            return False
        if now - self._last_notification_ts < LR_CONFIG.TRAY_NOTIFICATION_COOLDOWN_SEC:
            return False
        return True

    def suppress_for(self, seconds: float) -> None:
        """Временно отключить уведомления (например, на время фокусировки пользователя)."""
        self._suppressed_until_ts = time.time() + seconds

    # ============================================================
    # Показ уведомления
    # ============================================================

    def _show(self, title: str, message: str, timeout: int = 5) -> bool:
        """Показать OS-уведомление. Возвращает True если показано."""
        if not self._can_notify():
            logger.debug(f"[Notifier] Cooldown — пропускаем: {title}")
            return False

        # Защита от очень длинных текстов (Windows balloon лимит ~256)
        if len(message) > 250:
            message = message[:247] + "..."
        if len(title) > 64:
            title = title[:61] + "..."

        if _HAS_PLYER:
            try:
                # plyer.notification.notify — синхронный, но быстрый
                _plyer_notification.notify(
                    title=title,
                    message=message,
                    app_name=self.app_name,
                    timeout=timeout,
                )
                self._last_notification_ts = time.time()
                logger.info(f"[Notifier] OS-уведомление: {title} | {message[:50]}")
                return True
            except Exception as e:
                logger.exception(f"[Notifier] plyer упал: {e}")
                # fallback на печать

        # Fallback: пишем в лог
        print(f"\n🔔 [{self.app_name}] {title}")
        print(f"   {message}")
        logger.info(f"[Notifier] (fallback) {title} | {message}")
        self._last_notification_ts = time.time()
        return True

    # ============================================================
    # Обработчики событий
    # ============================================================

    async def _on_energy_low(self, event) -> None:
        data = event.data or {}
        level = data.get("level", "low")
        msg = data.get("message", "Энергия низкая.")
        title = "💤 Сильная усталость" if level == "critical" else "⚠️ Низкая энергия"
        self._show(title, msg, timeout=8 if level == "critical" else 5)

    async def _on_energy_recovered(self, event) -> None:
        data = event.data or {}
        msg = data.get("message", "Энергия восстановлена!")
        self._show("💚 Энергия восстановлена", msg, timeout=3)

    async def _on_agent_evolved(self, event) -> None:
        data = event.data or {}
        intel = data.get("intelligence", 0)
        self._show(
            "✨ Эволюция",
            f"Интеллект вырос до {intel}!",
            timeout=5,
        )

    async def _on_agent_speaks(self, event) -> None:
        data = event.data or {}
        content = data.get("content", "")
        msg_type = data.get("msg_type", "statement")
        if not content:
            return

        title_map = {
            "question": "❓ Агент спрашивает",
            "reflection": "💭 Мысль агента",
            "alert": "⚠️ Важное от агента",
            "proposal": "💡 Предложение",
            "poetry": "🎭 Стихи",
        }
        title = title_map.get(msg_type, "🤖 Агент говорит")
        self._show(title, content, timeout=8)

    async def _on_goal_completed(self, event) -> None:
        data = event.data or {}
        goal = data.get("goal_title", "Цель")
        self._show(
            "🎯 Цель достигнута!",
            f"Агент завершил: {goal}",
            timeout=7,
        )