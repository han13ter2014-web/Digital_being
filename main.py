"""Digital Being — единственная точка входа.

Один агент, одно время, один вход. Режим отображения выбирается флагом
``--ui``, а темп жизни — флагом ``--interval``.

    python main.py                     # окно обсерватории (Tkinter)
    python main.py --ui tray           # иконка в трее + окно
    python main.py --ui console        # консольный режим (как раньше)
    python main.py --ui headless       # без UI (CI, сервер)

    python main.py --interval 5        # реальное время: существо рядом
    python main.py --interval 0.5      # ускоренно: видно развитие
    python main.py --interval 0        # на скорости CPU: лаборатория
    python main.py --interval step     # один цикл по кнопке «Шаг»

    python main.py --seed Alpha_seed_2026-06-23T23-15-00   # прорастить семя
    python main.py --new                                   # начать заново

Почему Tk в главном потоке
--------------------------
Tkinter требует главного потока для mainloop (на macOS — строго).
Поэтому UI живёт в главном потоке, а жизнь агента (asyncio: EventBus,
AgentRunner) — в фоновом. Общение между ними идёт через EventBus и
очередь окна, без прямого доступа к объектам агента.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import logging
import signal
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("app.main")

# Интервалы CLI → режимы скорости раннера.
INTERVAL_TO_MODE = {
    "5": "live",
    "5.0": "live",
    "0.5": "fast",
    "0": "max",
    "0.0": "max",
    "max": "max",
    "step": "step",
    "live": "live",
    "fast": "fast",
}


# ============================================================
# Аргументы
# ============================================================


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Digital Being — цифровая жизнь",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--name", default=None, help="Имя агента")
    parser.add_argument(
        "--ui",
        default="gui",
        choices=("gui", "tray", "console", "headless"),
        help="Режим отображения (по умолчанию gui)",
    )
    parser.add_argument(
        "--interval",
        default="5",
        help="Темп жизни: 5 | 0.5 | 0 | max | step | live | fast",
    )
    parser.add_argument(
        "--new", action="store_true", help="Начать новую жизнь без чекпоинта"
    )
    parser.add_argument(
        "--seed", default=None, help="Имя папки семени в Яслях"
    )
    parser.add_argument(
        "--maturity",
        action="store_true",
        help="Показать зрелость агента и выйти (пора ли раздавать семя)",
    )
    parser.add_argument(
        "--maturity-json",
        action="store_true",
        help="Зрелость в машиночитаемом виде (для скриптов и CI)",
    )
    parser.add_argument(
        "--no-restore",
        action="store_true",
        help="Не восстанавливать из чекпоинта",
    )
    parser.add_argument("--stimuli", choices=("quiet", "pool"), default="quiet",
                        help="quiet — без искусственных вопросов; pool — лабораторный пул")
    # Совместимость с прежним main_tray.py
    parser.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-tray", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-chat", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def resolve_speed(interval: str) -> str:
    """Переводит значение ``--interval`` в режим раннера."""
    key = str(interval).strip().lower()
    if key in INTERVAL_TO_MODE:
        return INTERVAL_TO_MODE[key]
    try:
        seconds = float(key)
    except ValueError:
        raise SystemExit(
            f"Неизвестный интервал: {interval!r}. "
            f"Допустимо: {sorted(INTERVAL_TO_MODE)}"
        ) from None
    if seconds <= 0:
        return "max"
    if seconds < 1:
        return "fast"
    return "live"


# ============================================================
# Жизнь агента (фоновый поток asyncio)
# ============================================================


class Runtime:
    """Всё, что живёт в потоке asyncio."""

    def __init__(self, agent, bus, runner, window=None):
        self.agent = agent
        self.bus = bus
        self.runner = runner
        self.window = window
        self.started_at = time.time()
        self.shutdown = asyncio.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.finished = threading.Event()
        self.error = None
        self.saved_on_stop = False

    # --- поток ---

    def start(self, speed_mode: str) -> None:
        self._thread = threading.Thread(
            target=self._run, args=(speed_mode,), daemon=True,
            name="agent-loop",
        )
        self._thread.start()

    def _run(self, speed_mode: str) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main(speed_mode))
        except Exception as exc:
            self.error = str(exc)
            logger.exception("Цикл жизни упал")
        finally:
            try:
                loop.close()
            except Exception:
                pass
            tray = getattr(self, "tray", None)
            if tray is not None:
                tray.stop()
            self.finished.set()
            if self.window is not None:
                self.window.request_close()

    async def _main(self, speed_mode: str) -> None:
        from src.core.event_bus import Events

        bus = self.bus

        async def on_shutdown(event) -> None:
            self.shutdown.set()

        bus.subscribe(Events.SHUTDOWN_REQUESTED, on_shutdown)

        await bus.start()
        bus.attach_loop(asyncio.get_running_loop())
        delivered = bus.drain_pre_start()
        if delivered:
            logger.info("[EventBus] Доставлено %s отложенных событий", delivered)

        await self.runner.start()
        self.runner.set_speed(speed_mode)

        # Первый чекпоинт сразу после старта: если окно закроют или
        # процесс упадёт, жизнь не исчезнет целиком.
        self.runner.save_now()

        tasks = [
            asyncio.create_task(bus.run(), name="EventBus"),
            asyncio.create_task(self.runner.run_forever(), name="AgentRunner"),
        ]
        if self.window is not None:
            tasks.append(
                asyncio.create_task(self._status_loop(), name="StatusLoop")
            )

        shutdown_task = asyncio.create_task(self.shutdown.wait(), name="ShutdownWait")
        try:
            done, _ = await asyncio.wait([*tasks, shutdown_task], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not shutdown_task and not task.cancelled():
                    exception = task.exception()
                    if exception is not None:
                        self.error = str(exception)
                        logger.error("Задача %s завершилась ошибкой: %s", task.get_name(), exception)
        finally:
            self.shutdown.set()
            shutdown_task.cancel()
            await asyncio.gather(shutdown_task, return_exceptions=True)

        logger.info("Останавливаемся...")
        self.runner._stop_requested = True
        bus.stop()
        try:
            await asyncio.wait(tasks, timeout=2.0)
        except Exception:
            pass
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.runner.stop()
        self.saved_on_stop = self.runner.save_now()
        if not self.saved_on_stop:
            self.error = self.error or "Не удалось сохранить состояние при остановке"
        try:
            from src.core.buffered_logger import flush_logs

            flush_logs()
        except Exception:
            pass

    async def _status_loop(self) -> None:
        """Отдаёт окну снимок показателей дважды в секунду, карту — реже."""
        from src.app.status import build_status_snapshot
        from src.ui.graph_view import build_life_graph
        from src.ui.life_snapshot import build_life_snapshot

        tick = 0
        while not self.shutdown.is_set():
            try:
                self.window.push_status(
                    build_status_snapshot(
                        self.agent, self.runner, started_at=self.started_at
                    )
                )
                # Снимок жизни — отдельный поток данных для экрана «Сейчас»:
                # он читает Core, но не меняет его.
                life = build_life_snapshot(self.agent, self.runner)
                push_life = getattr(self.window, "push_life_status", None)
                if callable(push_life):
                    push_life(life)
                # Карта тяжелее карточек: раз в 10 тиков (≈5 с) достаточно,
                # чтобы она выглядела живой, и не грузит поток Tk.
                if tick % 10 == 0:
                    push_graph = getattr(self.window, "push_graph", None)
                    if callable(push_graph):
                        push_graph(build_life_graph(self.agent, life))
            except Exception as exc:
                logger.debug("status push: %s", exc)
            tick += 1
            await asyncio.sleep(0.5)

    # --- управление из главного потока ---

    def request_shutdown(self) -> None:
        try:
            self.bus.publish_sync("shutdown_requested", source="main")
        except Exception:
            pass
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self.shutdown.set)
            except Exception:
                pass

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self.finished.wait(timeout)


# ============================================================
# Сборка
# ============================================================


def build_runtime(args: argparse.Namespace, env) -> Runtime:
    """Создаёт агента, шину, раннер, контроллер и (если нужно) окно."""
    from src.app.bootstrap import create_agent, start_naming_dialogue
    from src.app.life_controller import LifeController
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    from src.app.active_profile import active_name

    name = args.name or (
        _default_name() if args.new or args.seed or args.no_restore
        else active_name(env.data_root, _default_name())
    )
    agent, report = create_agent(
        env,
        name,
        new=args.new,
        restore=not args.no_restore,
        seed=args.seed,
    )

    bus = EventBus(max_queue_size=500, history_size=300)
    runner = AgentRunner(agent, bus)
    runner.set_stimulus_mode(getattr(args, "stimuli", "quiet"))
    # Контроллер жизни нужен во всех режимах: он же обрабатывает
    # команды /dream и /terminate из чата.
    LifeController(agent, bus)

    # Подсистемы должны публиковать события в шину, иначе окно их не видит.
    user_interaction = getattr(agent, "user_interaction", None)
    if user_interaction is not None:
        user_interaction.attach_bus(bus)
    for attr in ("naming_dialogue", "proactive_communication", "mind_dream"):
        subsystem = getattr(agent, attr, None)
        if subsystem is not None and hasattr(subsystem, "user_interaction"):
            subsystem.user_interaction = user_interaction

    window = None
    # Отчёт о зрелости не нуждается в окне: не создаём Tk зря.
    wants_report = getattr(args, "maturity", False) or getattr(
        args, "maturity_json", False
    )
    if args.ui in ("gui", "tray") and not wants_report:
        from src.ui.main_window import MainWindow

        window = MainWindow(
            bus,
            agent.name,
            # Без трея прятать окно нельзя: вернуть его нечем.
            hide_on_close=False,
        )

    runtime = Runtime(agent, bus, runner, window)
    runtime.report = report  # type: ignore[attr-defined]

    # Знакомство — после создания окна, чтобы приветствие было видно.
    if window is not None:
        start_naming_dialogue(agent, bus)
    return runtime


def _default_name() -> str:
    try:
        from config.settings import SETTINGS

        return SETTINGS.DEFAULT_AGENT_NAME
    except Exception:
        return "Alpha"


# ============================================================
# Режимы
# ============================================================


def run_gui(runtime: Runtime, args: argparse.Namespace) -> int:
    """Окно в главном потоке, жизнь — в фоновом."""
    window = runtime.window
    speed = resolve_speed(args.interval)
    runtime.start(speed)

    # Ждём, пока шина поднимется: publish_sync до start() отбрасывается.
    for _ in range(100):
        if runtime.bus._running:  # noqa: SLF001 - проверка готовности
            break
        time.sleep(0.05)

    logger.info("=" * 60)
    logger.info("🤖 %s ЖИВЁТ", runtime.agent.name)
    logger.info("  Темп: %s", speed)
    logger.info("  Окно: %s", args.ui)
    logger.info("=" * 60)

    window.show()
    window.run_blocking()  # возвращается, когда окно закрыто

    runtime.request_shutdown()
    if not runtime.wait(timeout=10):
        logger.error("Поток жизни не завершён; сохранение из чужого потока отменено")
        return 1
    return 1 if runtime.error else 0


def run_maturity(runtime: Runtime, args: argparse.Namespace) -> int:
    """Печатает зрелость и выходит. Ничего не запускает и не меняет.

    Это ответ на вопрос «пора ли раздавать семя?» — измеримый, а не по
    ощущению. Код возврата: 0 — порог пройден, 1 — нет (удобно для CI).
    """
    from src.core.maturity import assess, load_criteria

    report = assess(runtime.agent, load_criteria())

    if args.maturity_json:
        print(report.to_json())
    else:
        print()
        print(report.describe())
        print()
        print("Подробнее о критериях: docs/MATURITY.md")

    return 0 if report.is_mature else 1


def run_headless(runtime: Runtime, args: argparse.Namespace) -> int:
    """Без UI: живёт, пока не остановят (Ctrl+C или shutdown)."""
    speed = resolve_speed(args.interval)
    runtime.start(speed)

    stop = threading.Event()

    def on_signal(signum, frame) -> None:
        logger.info("Получен сигнал %s", signum)
        stop.set()

    try:
        signal.signal(signal.SIGINT, on_signal)
        signal.signal(signal.SIGTERM, on_signal)
    except (ValueError, OSError):
        pass

    logger.info("🤖 %s живёт без UI (темп: %s)", runtime.agent.name, speed)
    while not stop.is_set() and not runtime.finished.is_set():
        stop.wait(0.5)

    runtime.request_shutdown()
    if not runtime.wait(timeout=10):
        logger.error("Поток жизни не завершён; сохранение из чужого потока отменено")
        return 1
    return 1 if runtime.error else 0


def run_console(runtime: Runtime, args: argparse.Namespace) -> int:
    """Консольный режим: прежний main.py, но на общем раннере."""
    from src.perception.user_interaction import UserPromptHandler

    speed = resolve_speed(args.interval)
    runtime.start(speed)

    for _ in range(100):
        if runtime.bus._running:  # noqa: SLF001
            break
        time.sleep(0.05)

    agent = runtime.agent
    _print_banner(agent)

    handler = UserPromptHandler()
    try:
        while agent.is_alive() and not runtime.finished.is_set():
            # Неблокирующий опрос: пустой Enter = «продолжай».
            try:
                raw = input("\n>>> ").strip()
            except EOFError:
                break
            if not raw:
                continue
            if raw.lower() in ("exit", "q", "quit"):
                break
            result = handler.process_command(raw, agent)
            if result == "__EXIT__":
                break
    except KeyboardInterrupt:
        pass

    runtime.request_shutdown()
    if not runtime.wait(timeout=10):
        logger.error("Поток жизни не завершён; сохранение из чужого потока отменено")
        return 1
    return 1 if runtime.error else 0


def _print_banner(agent) -> None:
    try:
        status = agent.get_goals_status()
        print(f"\n{'=' * 60}")
        print(
            f"  🤖 [{agent.name}] цикл {agent.cycle_count} | "
            f"интеллект {agent.intelligence} | энергия {agent.energy:.0f}"
        )
        print(
            f"  📚 концепций: {len(agent.mental_models.concepts)} | "
            f"цели: {status.get('completed')}/{status.get('total')}"
        )
        print(f"{'=' * 60}")
    except Exception:
        print(f"\n[{agent.name}] живёт.")


def _save_and_report(agent) -> None:
    try:
        agent.save_state(force=True)
        from config.simulation_config import SIM_CONFIG

        if getattr(SIM_CONFIG, "CHECKPOINT_BACKEND", "sqlite") != "sqlite":
            agent.save_mental_models()
    except Exception as exc:
        logger.warning("Не удалось сохранить состояние: %s", exc)
    print("\n" + "=" * 60)
    print(f"  💤 {agent.name} засыпает (с сохранением)")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


# ============================================================
# Точка входа
# ============================================================


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)

    # Совместимость со старыми флагами main_tray.py
    if args.headless:
        args.ui = "headless"
    elif args.no_chat and args.ui == "gui":
        args.ui = "tray"

    from src.app.paths import setup_environment

    # В режиме машиночитаемого отчёта stdout принадлежит JSON: логи и
    # сообщения подсистем уводим из stdout.
    json_output = bool(getattr(args, "maturity_json", False))
    env = setup_environment(console=not json_output)

    from src.app.bootstrap import RecoveryRequiredError

    try:
        if json_output:
            import contextlib

            with contextlib.redirect_stdout(sys.stderr):
                runtime = build_runtime(args, env)
        else:
            runtime = build_runtime(args, env)
    except RecoveryRequiredError as exc:
        message = (
            f"Восстановление жизни остановлено: {exc}\n\n"
            "Данные не заменены новой жизнью. Сохраните копию профиля и "
            "проверьте резервный комплект. Не используйте --new для исправления ошибки."
        )
        logger.error("%s", message)
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        if args.ui in ("gui", "tray") and not (args.maturity or json_output):
            from src.app.recovery_notice import show_recovery_notice

            show_recovery_notice(message)
        return 3
    except FileNotFoundError as exc:
        print(f"\n❌ {exc}\n", file=sys.stderr)
        return 2

    def atexit_save() -> None:
        try:
            if not runtime.finished.is_set():
                runtime.agent.save_state(force=True)
        except Exception:
            pass

    atexit.register(atexit_save)

    # «Пора ли раздавать семя?» — отчёт без запуска жизни.
    if args.maturity or args.maturity_json:
        return run_maturity(runtime, args)

    if args.ui in ("gui", "tray"):
        if args.ui == "tray":
            _start_tray(runtime)
        return run_gui(runtime, args)
    if args.ui == "console":
        return run_console(runtime, args)
    return run_headless(runtime, args)


def _start_tray(runtime: Runtime) -> None:
    """Иконка в системном трее (необязательная зависимость)."""
    try:
        from src.ui.tray import TrayIcon, _HAS_PYSTRAY

        if not _HAS_PYSTRAY:
            logger.warning("Трей недоступен; окно останется обычным")
            return
    except Exception as exc:
        logger.warning("Трей недоступен: %s", exc)
        return

    tray = TrayIcon(runtime.bus, agent_name=runtime.agent.name)
    try:
        tray.start()
        runtime.tray = tray  # type: ignore[attr-defined]
        if runtime.window is not None:
            runtime.window._hide_on_close = True
    except Exception as exc:
        logger.warning("Не удалось запустить трей: %s", exc)


def run_long_living_agent() -> int:
    """Совместимость: точка входа из pyproject.toml."""
    return main([])


if __name__ == "__main__":
    sys.exit(main())