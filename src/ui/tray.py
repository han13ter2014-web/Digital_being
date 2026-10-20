"""
TrayIcon — иконка в системном трее с контекстным меню.

Использует pystray (кросс-платформенная обёртка над нативными API).

Особенности:
- Иконка динамически меняется по уровню энергии (полная/нормальная/низкая/спящая)
- Контекстное меню:
  - 🤖 Статус агента (всплывающее уведомление)
  - 💬 Открыть чат → публикует USER_OPENED_CHAT
  - ⏸ Пауза / ▶ Возобновить → публикует PAUSE/RESUME
  - 💾 Сохранить → публикует SAVE_REQUESTED
  - 🚪 Выход → публикует SHUTDOWN_REQUESTED

ВАЖНО: pystray запускает свой main loop в отдельном потоке.
Поэтому он НЕ блокирует asyncio-цикл. Но все коллбэки pystray
(при кликах) — синхронные. Чтобы отправить событие в EventBus
из такого коллбэка, используем publish_sync().

Зависимости:
- pystray (pip install pystray)
- Pillow (для генерации иконки) — уже в проекте
"""

import asyncio
import logging
import threading
import time
from typing import Optional

from src.core.event_bus import EventBus, Events


logger = logging.getLogger(__name__)


try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PYSTRAY = True
except ImportError:
    _HAS_PYSTRAY = False
    logger.warning("pystray недоступен — трей будет работать в режиме заглушки")


# ============================================================
# Генерация иконки (без зависимости от внешних файлов)
# ============================================================

def _generate_icon(energy_level: str = "full", size: int = 64) -> "Image.Image":
    """Генерирует иконку программно (без файлов).

    Цвета по уровню энергии:
    - full      → зелёный (бодр)
    - normal    → голубой (спокойный)
    - slow      → жёлтый (задумчивый)
    - tired     → оранжевый (устал)
    - exhausted → красноватый (спит)

    Args:
        energy_level: один из "full"/"normal"/"slow"/"tired"/"exhausted".
        size: размер иконки в пикселях.
    """
    color_map = {
        "full":      (76, 175, 80),     # green
        "normal":    (33, 150, 243),    # blue
        "slow":      (255, 235, 59),    # yellow
        "tired":     (255, 152, 0),     # orange
        "exhausted": (244, 67, 54),     # red
    }
    bg = color_map.get(energy_level, color_map["normal"])

    # Создаём RGBA-изображение
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Круглая «голова» агента
    pad = size // 8
    draw.ellipse(
        [pad, pad, size - pad, size - pad],
        fill=bg,
        outline=(255, 255, 255, 200),
        width=max(1, size // 32),
    )

    # Глаза
    eye_y = size // 2 - size // 12
    eye_size = max(2, size // 16)
    left_x = size // 2 - size // 6
    right_x = size // 2 + size // 6 - eye_size
    draw.ellipse([left_x, eye_y, left_x + eye_size, eye_y + eye_size], fill=(0, 0, 0))
    draw.ellipse([right_x, eye_y, right_x + eye_size, eye_y + eye_size], fill=(0, 0, 0))

    # Рот (разный для разных уровней)
    mouth_y = size // 2 + size // 8
    mouth_w = size // 4
    cx = size // 2

    if energy_level in ("full", "normal"):
        # Улыбка
        draw.arc(
            [cx - mouth_w // 2, mouth_y - mouth_w // 4,
             cx + mouth_w // 2, mouth_y + mouth_w // 2],
            start=20, end=160, fill=(0, 0, 0), width=max(1, size // 24),
        )
    elif energy_level == "exhausted":
        # Z (спит) — букву сложно, делаем закрытые глаза
        pass
    else:
        # Нейтральный/усталый — прямая линия
        draw.line(
            [cx - mouth_w // 2, mouth_y, cx + mouth_w // 2, mouth_y],
            fill=(0, 0, 0), width=max(1, size // 24),
        )

    # Если спит — добавляем "zZz"
    if energy_level == "exhausted":
        try:
            font = ImageFont.load_default()
            draw.text((size - size // 4, 0), "z", fill=(0, 0, 0, 200), font=font)
        except Exception:
            pass

    return img


# ============================================================
# TrayIcon
# ============================================================

class TrayIcon:
    """Иконка в трее с динамическим меню и иконкой."""

    def __init__(
        self,
        bus: EventBus,
        agent_name: str = "DigitalBeing",
        energy_provider=None,
    ):
        """
        Args:
            bus: EventBus для публикации событий из меню.
            agent_name: имя агента (отображается в tooltip).
            energy_provider: callable, возвращающий уровень энергии
                             ("full"/"normal"/"slow"/"tired"/"exhausted").
                             Если None — иконка не обновляется динамически.
        """
        self.bus = bus
        self.agent_name = agent_name
        self.energy_provider = energy_provider

        self._icon: Optional["pystray.Icon"] = None
        self._thread: Optional[threading.Thread] = None
        self._current_energy_level = "normal"
        self._is_running = False

        if not _HAS_PYSTRAY:
            logger.warning("[TrayIcon] pystray недоступен — это no-op")
            return

        logger.info(f"[TrayIcon] Инициализирован для '{agent_name}'")

    # ============================================================
    # Запуск / остановка
    # ============================================================

    def start(self) -> None:
        """Запустить иконку в отдельном потоке (неблокирующе)."""
        if not _HAS_PYSTRAY:
            return
        if self._is_running:
            logger.warning("[TrayIcon] Уже запущен")
            return

        # Создаём иконку и меню
        image = _generate_icon(self._current_energy_level)
        menu = self._build_menu()

        self._icon = pystray.Icon(
            name=self.agent_name,
            icon=image,
            title=f"{self.agent_name} — живёт в трее",
            menu=menu,
        )

        self._is_running = True
        self._thread = threading.Thread(
            target=self._icon.run,
            daemon=True,
            name=f"TrayIcon-{self.agent_name}",
        )
        self._thread.start()
        logger.info(f"[TrayIcon] Запущен в потоке для '{self.agent_name}'")

    def stop(self) -> None:
        """Остановить иконку."""
        if not _HAS_PYSTRAY or not self._is_running:
            return
        try:
            if self._icon is not None:
                self._icon.stop()
            self._is_running = False
            logger.info("[TrayIcon] Остановлен")
        except Exception as e:
            logger.exception(f"[TrayIcon] Ошибка при остановке: {e}")

    # ============================================================
    # Динамическое обновление
    # ============================================================

    def update_energy_level(self, level: str) -> None:
        """Обновить иконку в соответствии с уровнем энергии.

        Вызывайте это из любого места (хоть из async-кода) — pystray
        защищён своим внутренним lock-ом.
        """
        if not _HAS_PYSTRAY or self._icon is None:
            return
        if level == self._current_energy_level:
            return
        self._current_energy_level = level
        try:
            self._icon.icon = _generate_icon(level)
            self._icon.title = f"{self.agent_name} — энергия: {level}"
        except Exception as e:
            logger.exception(f"[TrayIcon] Не удалось обновить иконку: {e}")

    def notify(self, title: str, message: str) -> None:
        """Показать balloon-уведомление из трея (pystray-native)."""
        if not _HAS_PYSTRAY or self._icon is None:
            return
        try:
            self._icon.notify(message, title=title)
        except Exception as e:
            logger.debug(f"[TrayIcon] notify не поддерживается: {e}")

    # ============================================================
    # Меню (коллбэки — синхронные, работают в потоке pystray)
    # ============================================================

    def _build_menu(self):
        """Строит контекстное меню."""
        return pystray.Menu(
            pystray.MenuItem("🤖 Статус агента", self._on_status, default=True),
            pystray.MenuItem("💬 Открыть чат", self._on_open_chat),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⏸ Пауза", self._on_pause),
            pystray.MenuItem("▶ Возобновить", self._on_resume),
            pystray.MenuItem("💾 Сохранить", self._on_save),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🚪 Выход", self._on_exit),
        )

    def _on_status(self, icon, item):
        """Показать статус (balloon)."""
        level = self._current_energy_level
        text = f"{self.agent_name}\nЭнергия: {level}"
        try:
            icon.notify(text, title="Статус агента")
        except Exception:
            pass

    def _on_open_chat(self, icon, item):
        """Запросить открытие чата."""
        logger.info("[TrayIcon] Open chat requested")
        self.bus.publish_sync(Events.USER_OPENED_CHAT, source="tray")

    def _on_pause(self, icon, item):
        """Поставить на паузу."""
        logger.info("[TrayIcon] Pause requested")
        self.bus.publish_sync(Events.PAUSE_REQUESTED, source="tray")

    def _on_resume(self, icon, item):
        """Возобновить."""
        logger.info("[TrayIcon] Resume requested")
        self.bus.publish_sync(Events.RESUME_REQUESTED, source="tray")

    def _on_save(self, icon, item):
        """Сохранить состояние."""
        logger.info("[TrayIcon] Save requested")
        self.bus.publish_sync(Events.SAVE_REQUESTED, source="tray")

    def _on_exit(self, icon, item):
        """Выйти из приложения."""
        logger.info("[TrayIcon] Exit requested")
        self.bus.publish_sync(Events.SHUTDOWN_REQUESTED, source="tray")
        # Останавливаем иконку, чтобы main loop увидел сигнал
        self.stop()


# ============================================================
# Headless-режим (для CI/тестов, когда нет дисплея)
# ============================================================

class TrayIconStub:
    """Заглушка для тестов и серверов без GUI.

    Все методы — no-op, но подменяет TrayIcon по тому же контракту.
    """

    def __init__(self, *args, **kwargs):
        self._current_energy_level = "normal"

    def start(self) -> None:
        logger.info("[TrayIconStub] start() — no-op")

    def stop(self) -> None:
        logger.info("[TrayIconStub] stop() — no-op")

    def update_energy_level(self, level: str) -> None:
        self._current_energy_level = level

    def notify(self, title: str, message: str) -> None:
        logger.info(f"[TrayIconStub] notify: {title} | {message}")