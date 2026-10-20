"""
main_tray.py — точка входа в трей-режиме Digital Being.

Запуск:
    python main_tray.py              # обычный запуск
    python main_tray.py --no-tray    # только чат, без иконки в трее
    python main_tray.py --no-chat    # только иконка в трее, без окна чата
    python main_tray.py --headless   # без GUI вообще (для CI/тестов)
    python main_tray.py --new        # начать новую жизнь (без загрузки чекпоинта)

Архитектура:
    ┌──────────────┐
    │ main_tray.py │ ← вы здесь
    └──────┬───────┘
           │ создаёт
           ▼
    ┌────────────────────────────────────┐
    │ EventBus + AgentRunner + Agent     │
    │ Notifier + TrayIcon + ChatWindow   │
    └────────────────────────────────────┘

Главный цикл:
    1. EventBus крутит asyncio.run() — обрабатывает события
    2. AgentRunner (async task) — каждые N секунд делает один «тик» агента
    3. TrayIcon (отдельный поток) — иконка и меню
    4. ChatWindow (отдельный поток) — Tk mainloop

Все они общаются через EventBus.publish / publish_sync.
"""

import argparse
import asyncio
import atexit
import io
import logging
from logging.handlers import RotatingFileHandler
import signal
import sys
import os
from datetime import datetime

# === Определяем базовую директорию ===
# Когда запускается DigitalBeing.exe (PyInstaller onefile), sys._MEIPASS
# указывает на временную папку с распакованными файлами (включая config/,
# data/knowledge_base.json). Когда запускается python main_tray.py из
# исходников — sys._MEIPASS не существует, поэтому используем корень проекта.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    # PyInstaller onefile: всё внутри распакованной временной папки
    BASE_DIR = sys._MEIPASS
    # Папка для пользовательских данных — %APPDATA%\DigitalBeing\
    # (не рядом с .exe! В Program Files обычный пользователь не имеет
    # прав на запись — PermissionError: WinError 5).
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            USER_DATA_DIR = os.path.join(appdata, "DigitalBeing")
        else:
            USER_DATA_DIR = os.path.expanduser("~/DigitalBeing")
    else:
        # Linux/macOS: ~/.local/share/digitalbeing
        xdg = os.environ.get("XDG_DATA_HOME",
                             os.path.expanduser("~/.local/share"))
        USER_DATA_DIR = os.path.join(xdg, "digitalbeing")
else:
    # Запуск из исходников: корень проекта (для разработки)
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    USER_DATA_DIR = BASE_DIR

# Переключаем cwd в BASE_DIR, чтобы относительные пути к config/ работали
os.chdir(BASE_DIR)

# Сначала создаём логгер (с минимальной конфигурацией), чтобы иметь
# возможность логировать ошибки при дальнейшей инициализации (в т.ч. при
# перенастройке stdout/stderr в UTF-8).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main_tray")

# UTF-8 для Windows-консоли.
# В PyInstaller onefile --windowed режиме sys.stdout/sys.stderr могут быть None
# (консоль не выделена), тогда sys.stdout.encoding падает с AttributeError.
# Оборачиваем безопасно.
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name)
    if _stream is not None and getattr(_stream, "encoding", None) != "utf-8":
        try:
            setattr(sys, _stream_name,
                    io.TextIOWrapper(_stream.buffer, encoding="utf-8"))
        except Exception as exc:
            # Логируем вместо тихого pass — раньше ошибка была невидима.
            logger.warning(
                "Не удалось перенастроить %s в UTF-8: %s. "
                "Логи будут в системной кодировке (cp1251).",
                _stream_name, exc,
            )

# Логирование — пишем в USER_DATA_DIR (рядом с .exe), а не во временную
# папку PyInstaller. Добавляем файл-хэндлер к уже созданному логгеру.
log_dir = os.path.join(USER_DATA_DIR, "data", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "tray_agent.log")
# Ротация: иначе tray_agent.log растёт без предела, как agent_log.txt (420 МБ).
_file_handler = RotatingFileHandler(
    log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
logger.addHandler(_file_handler)
# Консольный хэндлер — только если stdout доступен.
if sys.stdout is not None:
    _stream_handler = logging.StreamHandler(sys.stdout)
    _stream_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(_stream_handler)
# Не дублируем логи в корневой logger (иначе каждое сообщение идёт 2 раза).
logger.propagate = False

# Создаём нужные директории в USER_DATA_DIR
for sub in ("checkpoints", "logs", "mind", "memory", "nursery",
           "evolution", "cooperation", "architecture_proposals"):
    os.makedirs(os.path.join(USER_DATA_DIR, "data", sub), exist_ok=True)
logger.info(f"Пользовательские данные: {USER_DATA_DIR}")
logger.info(f"Ресурсы приложения: {BASE_DIR}")


# ============================================================
# Аргументы CLI
# ============================================================

def parse_args():
    p = argparse.ArgumentParser(description="Digital Being — режим трея")
    p.add_argument("--name", default="Alpha", help="Имя агента (по умолчанию Alpha)")
    p.add_argument("--no-tray", action="store_true", help="Не показывать иконку в трее")
    p.add_argument("--no-chat", action="store_true", help="Не показывать окно чата")
    p.add_argument("--headless", action="store_true", help="Без GUI (только логи)")
    p.add_argument("--new", action="store_true", help="Начать новую жизнь без чекпоинта")
    return p.parse_args()


# ============================================================
# Graceful shutdown
# ============================================================

class GracefulShutdown:
    """Управляет остановкой всех компонентов."""

    def __init__(self):
        self.bus = None
        self.runner = None
        self.tray = None
        self.chat = None
        self._shutdown_event = asyncio.Event()

    def request_shutdown(self, *args) -> None:
        """Вызывается по Ctrl+C или из других мест."""
        logger.info("[Shutdown] Получен сигнал остановки")
        if self.bus is not None:
            self.bus.publish_sync("shutdown_requested", source="signal")
        self._shutdown_event.set()

    async def wait_shutdown(self) -> None:
        """Ждём сигнала."""
        await self._shutdown_event.wait()

    async def do_shutdown(self) -> None:
        """Корректно останавливаем всё."""
        logger.info("[Shutdown] Останавливаем компоненты...")
        try:
            if self.runner is not None:
                await self.runner.stop()
            if self.bus is not None:
                self.bus.stop()
            if self.chat is not None:
                self.chat.stop()
            if self.tray is not None:
                self.tray.stop()
        except Exception as e:
            logger.exception(f"[Shutdown] Ошибка при остановке: {e}")
        logger.info("[Shutdown] Готово. Все компоненты остановлены.")


# ============================================================
# Главная функция
# ============================================================

async def main_async(args, shutdown: GracefulShutdown):
    """Главный асинхронная функция."""
    from src.core.agent import DigitalBeing
    from src.core.event_bus import EventBus, Events
    from src.core.agent_runner import (
        AgentRunner,
        get_latest_checkpoint,
        load_agent_from_checkpoint,
    )
    from config.simulation_config import LR_CONFIG
    from src.core.buffered_logger import flush_logs
    from src.core.subsystems import NamingDialogue

    # 1. Создаём агента
    logger.info(f"Создаю агента '{args.name}'...")
    # Передаём абсолютные пути к пользовательским данным, чтобы они
    # сохранялись рядом с .exe (а не во временной папке PyInstaller).
    user_kb_path = os.path.join(USER_DATA_DIR, "data", "knowledge_base.json")
    os.makedirs(os.path.dirname(user_kb_path), exist_ok=True)
    # Если у пользователя ещё нет своей копии — копируем базовую из поставки.
    if not os.path.isfile(user_kb_path):
        bundled_kb = os.path.join(BASE_DIR, "data", "knowledge_base.json")
        if os.path.isfile(bundled_kb):
            import shutil
            shutil.copy2(bundled_kb, user_kb_path)
            logger.info(f"Скопирована базовая БЗ → {user_kb_path}")
    # Создаём агента (использует internal knowledge_file, переопределим ниже)
    agent = DigitalBeing(args.name)
    # Переопределяем пути на пользовательские (рядом с .exe, не во временной)
    agent.knowledge_file = user_kb_path
    agent.checkpoint_dir = os.path.join(USER_DATA_DIR, "data", "checkpoints")
    agent.knowledge_subsystem.knowledge_file = user_kb_path
    # KnowledgeSubsystem внутри уже загрузил DEFAULT_KNOWLEDGE в память —
    # пересохраним в пользовательский файл, чтобы подхватились изменения.
    agent.knowledge_subsystem.knowledge_file = user_kb_path
    agent.knowledge_subsystem._known_definitions_file = user_kb_path
    os.makedirs(agent.checkpoint_dir, exist_ok=True)
    # Сохраняем начальную БЗ в пользовательский файл
    agent.knowledge_subsystem.save()
    logger.debug(f"БЗ пользователя: {user_kb_path}")
    logger.debug(f"Чекпоинты: {agent.checkpoint_dir}")

    # 2. Восстанавливаем из чекпоинта
    if not args.new and LR_CONFIG.TRAY_RESTORE_CHECKPOINT:
        checkpoint = get_latest_checkpoint(args.name)
        if checkpoint:
            ok = load_agent_from_checkpoint(agent, checkpoint)
            if ok:
                logger.info(
                    f"Восстановлен из {os.path.basename(checkpoint)}, "
                    f"цикл: {agent.cycle_count}, интеллект: {agent.intelligence}"
                )
        else:
            logger.info("Чекпоинтов не найдено — стартуем новую жизнь")

    # 3. EventBus
    bus = EventBus(max_queue_size=500, history_size=300)
    await bus.start()
    # Этап 2.5: привязать loop к шине (для thread-safe publish_sync из GUI)
    bus.attach_loop(asyncio.get_running_loop())
    # Слить отложенные события, накопленные до старта loop
    delivered = bus.drain_pre_start()
    if delivered:
        logger.info(f"[EventBus] Доставлено {delivered} отложенных событий")
    shutdown.bus = bus

    # === Этап 2.5: привязать bus к user_interaction и подсистемам агента ===
    # Без этого UserInteraction и другие подсистемы не публикуют события
    # в GUI (ChatWindow не увидит вопросы и сообщения агента).
    if hasattr(agent, "user_interaction"):
        agent.user_interaction.attach_bus(bus)
    if hasattr(agent, "naming_dialogue") and hasattr(agent.naming_dialogue, "user_interaction"):
        # NamingDialogue использует ту же user_interaction, но на всякий случай
        agent.naming_dialogue.user_interaction = agent.user_interaction
    if hasattr(agent, "proactive_communication") and hasattr(agent.proactive_communication, "user_interaction"):
        agent.proactive_communication.user_interaction = agent.user_interaction
    if hasattr(agent, "mind_dream") and hasattr(agent.mind_dream, "user_interaction"):
        agent.mind_dream.user_interaction = agent.user_interaction

    # Подписка на shutdown из шины
    async def on_shutdown_event(event):
        logger.info("Получено SHUTDOWN_REQUESTED через шину")
        shutdown.request_shutdown()
    bus.subscribe(Events.SHUTDOWN_REQUESTED, on_shutdown_event)

    # 4. AgentRunner
    runner = AgentRunner(agent, bus)
    await runner.start()
    shutdown.runner = runner

    # 5. UI-компоненты
    use_tray = not args.no_tray and not args.headless
    use_chat = not args.no_chat and not args.headless
    chat = None  # для последующего использования в NamingDialogue

    if use_tray:
        from src.ui.tray import TrayIcon
        tray = TrayIcon(bus, agent_name=args.name)
        # Обновление иконки по энергии (отдельная задача)
        async def energy_icon_updater():
            while not shutdown._shutdown_event.is_set():
                await asyncio.sleep(10)
                try:
                    level = runner.energy_policy.energy_level()
                    tray.update_energy_level(level)
                except Exception as e:
                    logger.debug(f"energy_icon_updater: {e}")
        tray.start()
        shutdown.tray = tray
        asyncio.create_task(energy_icon_updater())

    if use_chat:
        from src.ui.chat_window import ChatWindow
        chat = ChatWindow(bus, agent_name=args.name)
        chat.start()
        # Подписка: открытие чата из трея
        async def on_open_chat(event):
            chat.show()
        bus.subscribe(Events.USER_OPENED_CHAT, on_open_chat)
        shutdown.chat = chat

    # 6. === Запуск диалога об имени при первом контакте ===
    # Если у агента ещё не было naming-диалога (фаза NONE) — инициируем
    # приветствие ПОСЛЕ создания ChatWindow, чтобы подписка
    # `_on_naming_initiated` уже была зарегистрирована. Иначе
    # ChatWindow не получает событие и пользователь не видит приглашение.
    if agent.naming_dialogue.phase == NamingDialogue.PHASE_NONE:
        init_result = agent.start_naming_dialogue(cycle=agent.cycle_count)
        if init_result.get("status") == "initiated":
            logger.debug(
                f"[Naming] Диалог об имени инициирован для {agent.name}"
            )
            try:
                bus.publish_sync(
                    "naming_initiated",
                    source="main_tray",
                    agent_name=agent.name,
                    message_id=init_result.get("message_id"),
                )
            except Exception as exc:
                # Раньше тут был logger.debug(...) — оставляю.
                logger.debug("publish naming_initiated: %s", exc)
            # Автоматически показываем чат, чтобы пользователь не пропустил
            # приглашение дать имя. Особенно важно при первом запуске.
            if use_chat and chat is not None:
                try:
                    chat.show()
                except Exception as exc:
                    # Логируем вместо тихого pass: chat.show() — это
                    # UI-операция; если падает — пользователь не увидит
                    # приглашение, и нам важно это знать.
                    logger.warning(
                        "Не удалось показать чат при первом запуске: %s", exc,
                    )
    elif agent.naming_dialogue.phase == NamingDialogue.PHASE_AWAITING_NAME:
        logger.debug(
            f"[Naming] Агент {agent.name} ждёт ответа на предложение имени"
        )
        # Если восстановились из чекпоинта в фазе AWAITING_NAME — тоже
        # показываем чат (если уже был инициирован ранее).
        if use_chat and chat is not None:
            try:
                chat.show()
            except Exception as exc:
                logger.warning(
                    "Не удалось показать чат при восстановлении из "
                    "чекпоинта: %s", exc,
                )
    else:
        logger.debug(
            f"[Naming] Диалог об имени уже завершён (phase="
            f"{agent.naming_dialogue.phase})"
        )

    # 7. Notifier (всегда — даже без GUI)
    from src.ui.notifier import Notifier
    notifier = Notifier(bus, app_name=args.name)

    # 8. Запускаем всё
    logger.info("=" * 60)
    logger.info(f"🤖 {args.name} ЖИВЁТ В ТРЕЕ")
    logger.info("=" * 60)
    logger.info("  Иконка в трее: %s", "✅" if use_tray else "❌")
    logger.info("  Окно чата:     %s", "✅" if use_chat else "❌")
    logger.info("  Уведомления:   ✅")
    logger.info("  Циклов: ∞ (без смерти от энергии)")
    logger.info("=" * 60)
    logger.info("Горячие клавиши: Ctrl+C — выход (с сохранением)")
    logger.info("")

    # 8. Крутим EventBus + AgentRunner параллельно
    bus_task = asyncio.create_task(bus.run(), name="EventBus")
    runner_task = asyncio.create_task(runner.run_forever(), name="AgentRunner")
    shutdown_task = asyncio.create_task(shutdown.wait_shutdown(), name="WaitShutdown")

    # Ждём сигнала остановки
    await shutdown_task

    # 9. Останавливаем всё
    logger.info("Останавливаемся...")
    bus.stop()
    runner._stop_requested = True

    # Даём задачам 2 сек на завершение
    try:
        await asyncio.wait_for(
            asyncio.gather(bus_task, runner_task, return_exceptions=True),
            timeout=2.0,
        )
    except asyncio.TimeoutError:
        bus_task.cancel()
        runner_task.cancel()
        await asyncio.gather(bus_task, runner_task, return_exceptions=True)

    await shutdown.do_shutdown()
    flush_logs()


# ============================================================
# Точка входа
# ============================================================

def main():
    args = parse_args()
    shutdown = GracefulShutdown()

    # Обработка Ctrl+C
    def signal_handler(sig, frame):
        shutdown.request_shutdown(sig, frame)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # atexit — последний шанс сохранить. atexit-хэндлер не должен
    # поднимать исключения (иначе это маскирует исходную ошибку выхода),
    # но логировать сбой сохранения — полезно для диагностики.
    def atexit_handler():
        try:
            if shutdown.runner is not None:
                shutdown.runner._save_state_safe()
        except Exception as exc:
            # atexit не должен raise — но мы хотим видеть в логе, что
            # финальное сохранение провалилось.
            logger.warning(
                "atexit: не удалось сохранить состояние: %s", exc,
            )
    atexit.register(atexit_handler)

    # Запуск
    try:
        asyncio.run(main_async(args, shutdown))
    except KeyboardInterrupt:
        logger.info("Прервано пользователем (Ctrl+C)")
    except Exception as e:
        logger.exception(f"Неожиданная ошибка: {e}")
        sys.exit(1)

    # Финальное сообщение
    print("\n" + "=" * 60)
    print(f"  💤 {args.name} засыпает (с сохранением)")
    print(f"  📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"  💾 Состояние сохранено. До встречи!")


if __name__ == "__main__":
    main()