"""
ChatWindow — маленькое GUI-окно чата с агентом.

Использует Tkinter (в stdlib, не требует установки).

Особенности:
- Неблокирующий: использует Tk.after() и mainloop в отдельном потоке
- Слушает EventBus — все события от агента появляются в ленте
- Отправляет сообщения пользователя → USER_MESSAGE
- Поддерживает команды /status, /goals, /concepts, /pause и т.п.
- Кнопка «Свернуть в трей» вместо закрытия
- Позиция — справа внизу экрана

Зависимости: только stdlib (tkinter).
"""

import logging
import threading
import time
from queue import Queue, Empty
from typing import Optional

from src.core.event_bus import EventBus, Events


logger = logging.getLogger(__name__)


try:
    import tkinter as tk
    from tkinter import scrolledtext, font
    _HAS_TK = True
except ImportError:
    _HAS_TK = False
    logger.warning("tkinter недоступен — ChatWindow в режиме заглушки")


# ============================================================
# Команды чата (синтаксис /command)
# ============================================================

class ChatCommands:
    """Простой список команд для автодополнения / справки."""

    COMMANDS = {
        "/help": "Показать справку",
        "/status": "Статус агента",
        "/goals": "Список целей",
        "/concepts": "Изученные концепции",
        "/energy": "Энергия (алиас status)",
        "/name": "Дать агенту имя: /name <имя>",
        "/ask": "Поставить открытый вопрос: /ask <вопрос>",
        "/questions": "Показать очередь открытых вопросов",
        "/pause": "Поставить на паузу",
        "/resume": "Возобновить",
        "/save": "Сохранить состояние",
        "/quit": "Выйти (с сохранением)",
    }


# ============================================================
# ChatWindow
# ============================================================

class ChatWindow:
    """Tk-окно чата с агентом.

    Создаёт UI в отдельном потоке (Tk этого требует).
    С EventBus общается через publish_sync() и локальную очередь.
    """

    def __init__(self, bus: EventBus, agent_name: str = "DigitalBeing"):
        self.bus = bus
        self.agent_name = agent_name

        self._root: Optional["tk.Tk"] = None
        self._thread: Optional[threading.Thread] = None
        self._is_visible = False
        self._poll_running = False

        # Очередь сообщений от EventBus → UI (потокобезопасная)
        self._incoming_queue: Queue = Queue()

        # Подписки на события
        self._setup_subscriptions()

        if not _HAS_TK:
            logger.warning("[ChatWindow] tkinter недоступен — это no-op")
            return

        logger.info(f"[ChatWindow] Инициализирован для '{agent_name}'")

    # ============================================================
    # Подписки
    # ============================================================

    def _setup_subscriptions(self) -> None:
        """Подписаться на события, которые хотим видеть в чате."""
        self.bus.subscribe(Events.AGENT_THOUGHT, self._on_agent_thought)
        self.bus.subscribe(Events.AGENT_EVOLVED, self._on_agent_evolved)
        self.bus.subscribe(Events.ENERGY_LOW, self._on_energy_low)
        self.bus.subscribe(Events.ENERGY_RECOVERED, self._on_energy_recovered)
        self.bus.subscribe(Events.TICK, self._on_tick)
        # === Этап 2.5: вопросы и сообщения агента пользователю ===
        # Раньше UserInteraction только print()ал в stdout (для терминала),
        # а GUI не получал ничего. Теперь ask_user публикует AGENT_QUESTION,
        # send_message — AGENT_MESSAGE, и ChatWindow их видит.
        self.bus.subscribe(Events.AGENT_QUESTION, self._on_agent_question)
        self.bus.subscribe(Events.AGENT_MESSAGE, self._on_agent_message)
        # === Этап 2.5: результат web-поиска (Wikipedia) ===
        # Когда ThinkingPipeline находит ответ в интернете, он публикует
        # AGENT_WEB_RESULT. ChatWindow показывает это ярко.
        self.bus.subscribe(Events.AGENT_WEB_RESULT, self._on_agent_web_result)
        # === NamingDialogue: приветствие + просьба дать имя ===
        # Событие публикуется из main_tray/main.py при PHASE_NONE.
        # Подписка без prefix в Events, потому что это кастомное
        # событие, а не из перечисления Events.
        try:
            self.bus.subscribe("naming_initiated", self._on_naming_initiated)
        except Exception:
            pass

    async def _on_naming_initiated(self, event) -> None:
        """Показываем приветствие агента + просьбу ввести имя.

        Ожидаемый payload события:
            {
                "agent_name": str,
                "message_id": int | None,
            }
        """
        agent_name = (event.data or {}).get("agent_name", self.agent_name)
        # Попробуем достать последнее сообщение naming из user_interaction.
        msg_text = None
        try:
            ui = getattr(self, "_user_interaction_ref", None)
            if ui is not None:
                msgs = ui.get_pending_messages(include_acknowledged=False)
                for m in reversed(msgs or []):
                    if m.get("msg_type") == "naming":
                        msg_text = m.get("content")
                        break
        except Exception:
            pass

        if not msg_text:
            msg_text = (
                "Привет. Я только что появился на свет. "
                "Сейчас меня зовут временно — хочешь дать мне имя?"
            )

        self._incoming_queue.put(("agent", f"👋 {msg_text}"))
        self._incoming_queue.put((
            "system",
            f"Введите имя: >>> name <ваше_имя> (или просто имя в строке ввода)",
        ))

    async def _on_agent_thought(self, event) -> None:
        text = (event.data or {}).get("text", "")
        if text:
            self._incoming_queue.put(("agent", text))

    async def _on_agent_evolved(self, event) -> None:
        intel = (event.data or {}).get("intelligence", 0)
        self._incoming_queue.put(("agent", f"✨ Мой интеллект вырос до {intel}!"))

    async def _on_energy_low(self, event) -> None:
        msg = (event.data or {}).get("message", "")
        if msg:
            self._incoming_queue.put(("agent", f"⚠️ {msg}"))

    async def _on_energy_recovered(self, event) -> None:
        msg = (event.data or {}).get("message", "")
        if msg:
            self._incoming_queue.put(("agent", f"💚 {msg}"))

    async def _on_tick(self, event) -> None:
        # Тики НЕ показываем в чате — слишком шумно
        # Но можем показывать прогресс раз в N тиков
        tick = (event.data or {}).get("tick", 0)
        if tick > 0 and tick % 20 == 0:
            energy = (event.data or {}).get("energy", 0)
            self._incoming_queue.put(
                ("system", f"[тик #{tick}] энергия: {energy:.0f}")
            )

    # === Этап 2.5: вопросы и сообщения от агента к пользователю ===

    async def _on_agent_question(self, event) -> None:
        """Агент задал вопрос пользователю (user_interaction.ask_user).

        Показываем вопрос в чате ярко, чтобы пользователь точно заметил.
        Автоматически показываем окно чата, если оно свёрнуто — без этого
        вопрос легко пропустить.
        """
        data = event.data or {}
        qid = data.get("id", "?")
        question = data.get("question", "")
        context = data.get("context", "")
        priority = data.get("priority", "medium")

        lines = [f"❓ [{self.agent_name}] спрашивает (#{qid}, {priority}):"]
        lines.append(f"   {question}")
        if context:
            lines.append(f"   (контекст: {context})")
        lines.append("")
        lines.append(f"   Ответь в чате — например: «{question[:30]}… — …»")

        self._incoming_queue.put(("agent", "\n".join(lines)))
        # Подсветить окно: пользователь должен увидеть вопрос
        self._incoming_queue.put(("__show__", None))

    async def _on_agent_message(self, event) -> None:
        """Агент отправил сообщение (statement/reflection/greeting/etc.).

        В отличие от вопроса, не требует ответа, но показывается так же ярко.
        """
        data = event.data or {}
        msg_type = data.get("msg_type", "statement")
        content = data.get("content", "")
        urgency = data.get("urgency", 0.5)

        prefix_map = {
            "question": "?",
            "statement": "*",
            "reflection": "~",
            "greeting": ">",
            "farewell": "<",
            "proposal": "+",
            "alert": "!",
            "poetry": "~",
        }
        prefix = prefix_map.get(msg_type, "*")

        # Высокая urgency / alert / question → подсвечиваем как «агент говорит»
        if urgency >= 0.7 or msg_type in ("alert", "question", "greeting"):
            self._incoming_queue.put(("agent", f"{prefix} [{self.agent_name}]:\n   {content}"))
        else:
            self._incoming_queue.put(("system", f"{prefix} [{self.agent_name} → сообщение]:\n   {content}"))

    async def _on_agent_web_result(self, event) -> None:
        """Этап 2.5: агент нашёл ответ в интернете (Wikipedia).

        Показываем пользователю в чате: заголовок, краткий extract, ссылку.
        Подсвечиваем окно, чтобы пользователь точно заметил.
        """
        data = event.data or {}
        concept = data.get("concept", "")
        title = data.get("title", "")
        extract = data.get("extract", "")
        url = data.get("url", "")
        lang = data.get("lang", "ru")

        # Обрезаем extract для чата (до 400 символов).
        if len(extract) > 400:
            extract = extract[:400].rsplit(" ", 1)[0] + "…"

        lines = [
            f"🌐 [{self.agent_name}] нашёл в интернете (Wikipedia/{lang}):",
            f"   Тема: {concept}",
            f"   Статья: {title}",
            "",
            f"   {extract}",
            "",
            f"   Источник: {url}",
            "   ✓ Сохранил в свою базу знаний",
        ]

        self._incoming_queue.put(("agent", "\n".join(lines)))
        # Подсветить окно: пользователь должен увидеть
        self._incoming_queue.put(("__show__", None))

    # ============================================================
    # Жизненный цикл
    # ============================================================

    def start(self) -> None:
        """Запустить UI-поток. Окно НЕ создаётся сразу — только после show()."""
        if not _HAS_TK:
            return
        if self._thread is not None and self._thread.is_alive():
            return

        self._poll_running = True
        self._thread = threading.Thread(
            target=self._tk_mainloop,
            daemon=True,
            name=f"ChatWindow-{self.agent_name}",
        )
        self._thread.start()
        logger.info("[ChatWindow] UI-поток запущен")

    def stop(self) -> None:
        """Остановить UI-поток."""
        self._poll_running = False
        if self._root is not None:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass

    def show(self) -> None:
        """Показать окно (если не создано — создать)."""
        if not _HAS_TK:
            logger.info("[ChatWindow] show() — no-op (нет tkinter)")
            return

        # Запрос на показ — UI-поток создаст и поднимет окно
        self._incoming_queue.put(("__show__", None))

    def hide(self) -> None:
        """Скрыть окно (без уничтожения)."""
        if self._root is not None:
            try:
                self._root.after(0, self._root.withdraw)
            except Exception:
                pass

    # ============================================================
    # Tk mainloop (в отдельном потоке)
    # ============================================================

    def _tk_mainloop(self) -> None:
        """Основной цикл Tk — выполняется в отдельном потоке."""
        try:
            self._root = tk.Tk()
            self._root.title(f"💬 {self.agent_name}")
            self._root.protocol("WM_DELETE_WINDOW", self._on_close)
            self._build_ui()
            self._position_bottom_right()
            self._is_visible = True

            # Приветствие
            self._append_agent(
                f"Привет! Я {self.agent_name}. Я живу в трее и думаю в фоне.\n"
                "Введи сообщение или /help для команд."
            )

            # Polling: раз в 100мс забираем новые сообщения из очереди
            self._schedule_poll()

            self._root.mainloop()
        except Exception as e:
            logger.exception(f"[ChatWindow] UI-поток упал: {e}")

    def _build_ui(self) -> None:
        """Строит UI: лента сообщений, поле ввода, кнопки."""
        root = self._root

        # Шрифты
        mono_font = font.Font(family="Consolas" if self._is_windows() else "Menlo", size=10)
        bold_font = font.Font(family="Segoe UI" if self._is_windows() else "Helvetica", size=10, weight="bold")

        # === Лента сообщений ===
        self._text = scrolledtext.ScrolledText(
            root,
            wrap=tk.WORD,
            width=60,
            height=20,
            font=mono_font,
            bg="#1e1e1e",
            fg="#e0e0e0",
            insertbackground="#e0e0e0",
            state=tk.DISABLED,
        )
        self._text.pack(padx=8, pady=8, fill=tk.BOTH, expand=True)

        # Цветовые теги
        self._text.tag_config("user", foreground="#87ceeb")
        self._text.tag_config("agent", foreground="#98fb98")
        self._text.tag_config("system", foreground="#888888", font=bold_font)
        self._text.tag_config("error", foreground="#ff6b6b")

        # === Поле ввода ===
        input_frame = tk.Frame(root)
        input_frame.pack(padx=8, pady=(0, 8), fill=tk.X)

        self._input_var = tk.StringVar()
        self._input_entry = tk.Entry(
            input_frame,
            textvariable=self._input_var,
            font=mono_font,
            bg="#2a2a2a",
            fg="#e0e0e0",
            insertbackground="#e0e0e0",
        )
        self._input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._input_entry.bind("<Return>", self._on_send)
        self._input_entry.bind("<Up>", self._on_history_up)
        self._input_entry.bind("<Down>", self._on_history_down)
        self._input_entry.focus_set()

        # Кнопка отправки
        send_btn = tk.Button(
            input_frame,
            text="Сказать",
            command=self._on_send,
            bg="#3a3a3a",
            fg="#e0e0e0",
            activebackground="#4a4a4a",
            activeforeground="#ffffff",
        )
        send_btn.pack(side=tk.LEFT, padx=(4, 0))

        # === Кнопка "Свернуть в трей" ===
        min_btn = tk.Button(
            root,
            text="🫥 Свернуть в трей (не закрывать)",
            command=self.hide,
            bg="#2a2a2a",
            fg="#888888",
            relief=tk.FLAT,
        )
        min_btn.pack(padx=8, pady=(0, 8), fill=tk.X)

        # История команд (для Up/Down)
        self._history: list = []
        self._history_idx = -1

    def _is_windows(self) -> bool:
        import os
        return os.name == "nt"

    def _position_bottom_right(self) -> None:
        """Разместить окно в правом нижнем углу экрана."""
        root = self._root
        root.update_idletasks()
        w = 500
        h = 400
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = screen_w - w - 20
        y = screen_h - h - 60  # над панелью задач
        root.geometry(f"{w}x{h}+{x}+{y}")

    def _on_close(self) -> None:
        """Клик на × — НЕ закрываем, а прячем в трей."""
        self.hide()
        self._incoming_queue.put(
            ("system", "Я спрятался в трей. Двойной клик по иконке или меню → Открыть чат.")
        )

    # ============================================================
    # Polling очереди (вызывается из Tk-потока)
    # ============================================================

    def _schedule_poll(self) -> None:
        """Каждые 100мс забираем новые сообщения из очереди."""
        if not self._poll_running:
            return
        try:
            self._poll_incoming()
        except Exception as e:
            logger.exception(f"[ChatWindow] poll error: {e}")
        try:
            self._root.after(100, self._schedule_poll)
        except Exception:
            pass  # окно уже закрыто

    def _poll_incoming(self) -> None:
        """Забрать все доступные сообщения из очереди."""
        processed = 0
        while processed < 50:  # защита от зависания UI
            try:
                kind, data = self._incoming_queue.get_nowait()
            except Empty:
                break
            processed += 1

            if kind == "__show__":
                self._show_window()
            elif kind == "user":
                self._append_user(data)
            elif kind == "agent":
                self._append_agent(data)
            elif kind == "system":
                self._append_system(data)
            elif kind == "error":
                self._append_error(data)

    def _show_window(self) -> None:
        """Поднять и показать окно."""
        if self._root is None:
            return
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()
        self._input_entry.focus_set()
        self._is_visible = True

    # ============================================================
    # Добавление сообщений в ленту
    # ============================================================

    def _append(self, prefix: str, text: str, tag: str = "agent") -> None:
        """Добавить строку в ленту."""
        if self._text is None:
            return
        self._text.configure(state=tk.NORMAL)
        timestamp = time.strftime("%H:%M:%S")
        self._text.insert(tk.END, f"[{timestamp}] {prefix}\n", tag)
        if text:
            self._text.insert(tk.END, text + "\n\n", tag)
        self._text.see(tk.END)
        self._text.configure(state=tk.DISABLED)

    def _append_user(self, text: str) -> None:
        self._append("👤 Ты:", text, tag="user")

    def _append_agent(self, text: str) -> None:
        self._append(f"🤖 {self.agent_name}:", text, tag="agent")

    def _append_system(self, text: str) -> None:
        self._append("⚙ Система:", text, tag="system")

    def _append_error(self, text: str) -> None:
        self._append("❌ Ошибка:", text, tag="error")

    # ============================================================
    # Отправка сообщений
    # ============================================================

    def _on_send(self, event=None) -> None:
        """Обработка нажатия Enter или кнопки 'Сказать'."""
        text = self._input_var.get().strip()
        if not text:
            return
        self._input_var.set("")

        # Сохранить в историю (для Up/Down)
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            if len(self._history) > 50:
                self._history = self._history[-50:]
        self._history_idx = -1

        # Команда?
        if text.startswith("/"):
            self._handle_command(text)
            return

        # Обычное сообщение → EventBus
        self._append_user(text)
        self.bus.publish_sync(
            Events.USER_MESSAGE,
            {"text": text},
            source="chat",
        )

    def _on_history_up(self, event) -> None:
        """Up — предыдущее сообщение из истории."""
        if not self._history:
            return
        if self._history_idx == -1:
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        else:
            return
        self._input_var.set(self._history[self._history_idx])

    def _on_history_down(self, event) -> None:
        """Down — следующее сообщение."""
        if not self._history or self._history_idx == -1:
            return
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self._input_var.set(self._history[self._history_idx])
        else:
            self._history_idx = -1
            self._input_var.set("")

    # ============================================================
    # Команды чата
    # ============================================================

    def _handle_command(self, text: str) -> None:
        """Обработать /команду. Показывает ответ в чате."""
        cmd = text.strip().lower()
        self._append_user(text)

        # Help
        if cmd in ("/help", "/h", "/?"):
            lines = ["📖 Команды:"]
            for c, desc in ChatCommands.COMMANDS.items():
                lines.append(f"  {c:<12} {desc}")
            self._append_agent("\n".join(lines))
            return

        # === name <имя> — NamingDialogue ===
        # Позволяет пользователю дать имя агенту прямо из чата.
        # Совпадает с подсказкой, которую мы показали в _on_naming_initiated.
        if cmd.startswith("/name ") or cmd.startswith("name "):
            proposed = text.split(" ", 1)[1].strip() if " " in text else ""
            if proposed:
                self._append_system(
                    f"Отправляю агенту предложение имени: '{proposed}'"
                )
                self.bus.publish_sync(
                    Events.USER_COMMAND,
                    {"command": f"propose_name {proposed}"},
                    source="chat",
                )
            else:
                self._append_system(
                    "Использование: /name <имя_которое_ты_хочешь_дать>"
                )
            return

        # Status / goals / concepts — публикуем USER_COMMAND, обработает AgentRunner
        if cmd in ("/status", "/goals", "/concepts", "/energy",
                   "/pause", "/resume", "/save", "/quit"):
            self.bus.publish_sync(
                Events.USER_COMMAND,
                {"command": cmd.lstrip("/")},
                source="chat",
            )
            self._append_system(f"Команда {cmd} отправлена агенту.")
            return

        # === ask <вопрос> — открытый вопрос (свобода воли) ===
        # Позволяет из чата поставить вопрос в очередь открытых.
        # AgentRunner обработает его в ближайших циклах и ответ попадёт
        # в чат через событие AGENT_THOUGHT.
        if text.startswith("/ask ") or text.startswith("ask "):
            question = text.split(" ", 1)[1].strip() if " " in text else ""
            if question:
                self.bus.publish_sync(
                    Events.USER_COMMAND,
                    {"command": f"ask {question}"},
                    source="chat",
                )
                self._append_system(
                    f"Вопрос поставлен в очередь: «{question[:60]}». "
                    f"Я подумаю над ним в ближайших циклах."
                )
            else:
                self._append_system("Использование: /ask <вопрос>")
            return

        # === questions — показать текущую очередь открытых вопросов ===
        if cmd in ("/questions", "/q"):
            self.bus.publish_sync(
                Events.USER_COMMAND,
                {"command": "questions"},
                source="chat",
            )
            return

        self._append_error(f"Неизвестная команда {cmd}. /help для справки.")


# ============================================================
# Headless-режим (заглушка)
# ============================================================

class ChatWindowStub:
    """Заглушка для CI/серверов без GUI."""

    def __init__(self, *args, **kwargs):
        self._messages = []

    def start(self) -> None:
        logger.info("[ChatWindowStub] start() — no-op")

    def stop(self) -> None:
        logger.info("[ChatWindowStub] stop() — no-op")

    def show(self) -> None:
        logger.info("[ChatWindowStub] show() — no-op")

    def hide(self) -> None:
        pass