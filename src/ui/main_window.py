"""MainWindow — окно наблюдения и общения с цифровой жизнью.

Расширяет ``ChatWindow`` тремя вещами, которых не хватало:

1. **Панель показателей** слева: цикл, энергия, интеллект, концепции,
   цели, время жизни, память, режим скорости, состояние жизни.
2. **Панель управления** снизу: пауза, шаг, скорость, сохранение,
   сон, пробуждение, выход.
3. **Подтверждение ухода.** Кнопки сна и ухода не убивают агента:
   они создают запрос, а окно просит ввести точную фразу. Подробности —
   ``src/core/life_guard.py``.

Окно ничего не решает про жизнь само: оно публикует события, а
обрабатывает их ``LifeController`` в потоке агента.

Потокобезопасность: окно работает в потоке Tk. Данные приходят через
очередь (``push_status``), действия уходят через ``bus.publish_sync``.
Прямого доступа к объектам агента из потока Tk нет.

Известное ограничение: при выходе из процесса Windows может напечатать
``Tcl_AsyncDelete: async handler deleted by the wrong thread``. Это
следствие того, что Tk живёт в фоновом потоке, а сборка мусора при
завершении происходит в главном. На работу окна не влияет. Устраняется
переносом Tk в главный поток — это делается в единой точке входа
(``main.py``).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from src.core.event_bus import Events
from src.ui.chat_window import _HAS_TK, ChatWindow

if _HAS_TK:
    import tkinter as tk
    from tkinter import font


logger = logging.getLogger(__name__)

# Отображение режима скорости на кнопке
SPEED_LABELS = {
    "live": "5 с",
    "fast": "0.5 с",
    "max": "МАКС",
    "step": "Шаг",
}


class MainWindow(ChatWindow):
    """Окно обсерватории: показатели, лента, управление."""

    def __init__(
        self,
        bus,
        agent_name: str = "DigitalBeing",
        *,
        enabled_controls: bool = True,
        hide_on_close: bool = False,
    ):
        """
        Args:
            bus: EventBus.
            agent_name: имя агента.
            enabled_controls: показывать ли кнопки управления. Выключено
                для режима «только смотреть».
            hide_on_close: крестик прячет окно (режим трея) вместо
                выхода. По умолчанию False: без трея спрятанное окно
                вернуть нечем.
        """
        super().__init__(bus, agent_name, hide_on_close=hide_on_close)
        self._enabled_controls = bool(enabled_controls)

        self._status_text = None
        self._status_snapshot: Dict[str, Any] = {}
        self._controls_frame = None
        self._speed_buttons: Dict[str, Any] = {}
        self._pause_button = None
        self._wake_button = None
        self._cancel_life_button = None

        # Ожидающее подтверждение ухода
        self._life_prompt: Optional[Dict[str, Any]] = None
        self._life_deadline: Optional[float] = None
        self._life_tick_job = None

        self._last_paused: Optional[bool] = None
        self._last_speed_mode: Optional[str] = None
        self._last_life_state: Optional[str] = None

        self._subscribe_life_events()

    # ============================================================
    # Подписки на события жизни
    # ============================================================

    def _subscribe_life_events(self) -> None:
        try:
            self.bus.subscribe(Events.LIFE_PROMPT, self._on_life_prompt)
            self.bus.subscribe(Events.LIFE_RESULT, self._on_life_result)
        except Exception as exc:
            logger.debug("[MainWindow] life subscriptions: %s", exc)

    async def _on_life_prompt(self, event) -> None:
        """Ядро просит подтвердить уход. Показываем инструкцию и ждём фразу."""
        data = dict(event.data or {})
        self._life_prompt = data
        cooldown = float(data.get("cooldown_sec") or 0.0)
        self._life_deadline = time.time() + cooldown if cooldown else None
        self._incoming_queue.put(("__life_prompt__", data))
        self._incoming_queue.put(("__show__", None))

    async def _on_life_result(self, event) -> None:
        data = dict(event.data or {})
        self._incoming_queue.put(("__life_result__", data))

    # ============================================================
    # Приём снимка показателей (из потока агента)
    # ============================================================

    def push_status(self, snapshot: Dict[str, Any]) -> None:
        """Потокобезопасно передать снимок показателей в окно."""
        self._incoming_queue.put(("__status__", dict(snapshot or {})))

    def push_life_status(self, snapshot: Dict[str, Any]) -> None:
        """Потокобезопасно передать состояние жизни в окно."""
        self._incoming_queue.put(("__status__", dict(snapshot or {})))

    # ============================================================
    # Обработка очереди
    # ============================================================

    def _handle_incoming(self, kind: str, data) -> None:
        if kind == "__status__":
            self._apply_status(data)
        elif kind == "__life_prompt__":
            self._apply_life_prompt(data)
        elif kind == "__life_result__":
            self._apply_life_result(data)
        else:
            super()._handle_incoming(kind, data)

    # ============================================================
    # Панель показателей
    # ============================================================

    def _apply_status(self, snapshot: Dict[str, Any]) -> None:
        self._status_snapshot = snapshot
        if self._status_text is not None:
            from src.app.status import format_status_lines

            try:
                self._status_text.configure(state=tk.NORMAL)
                self._status_text.delete("1.0", tk.END)
                self._status_text.insert(
                    tk.END, "\n".join(format_status_lines(snapshot))
                )
                self._status_text.configure(state=tk.DISABLED)
            except Exception as exc:
                logger.debug("[MainWindow] status update: %s", exc)

        # Кнопки отражают состояние, даже если его изменили не через окно
        # (например, командой /pause в чате).
        paused = snapshot.get("paused")
        if paused is not None and paused != self._last_paused:
            self._last_paused = paused
            self._refresh_pause_button(paused)

        mode = snapshot.get("speed_mode")
        if mode and mode != self._last_speed_mode:
            self._last_speed_mode = mode
            self._refresh_speed_buttons(mode)

        life_state = snapshot.get("life_state")
        if life_state and life_state != self._last_life_state:
            self._last_life_state = life_state
            self._refresh_life_buttons(life_state)

    def _refresh_pause_button(self, paused: bool) -> None:
        if self._pause_button is None:
            return
        try:
            self._pause_button.configure(
                text="▶ Продолжить" if paused else "⏸ Пауза"
            )
        except Exception:
            pass

    def _refresh_speed_buttons(self, mode: str) -> None:
        for key, button in self._speed_buttons.items():
            try:
                button.configure(
                    relief=tk.SUNKEN if key == mode else tk.RAISED,
                    fg="#ffffff" if key == mode else "#c0c0c0",
                )
            except Exception:
                pass

    def _refresh_life_buttons(self, life_state: str) -> None:
        alive = life_state == "alive"
        if self._wake_button is not None:
            try:
                self._wake_button.configure(
                    state=tk.NORMAL if life_state == "dormant" else tk.DISABLED
                )
            except Exception:
                pass
        for name in ("_sleep_button", "_terminate_button"):
            button = getattr(self, name, None)
            if button is not None:
                try:
                    button.configure(state=tk.NORMAL if alive else tk.DISABLED)
                except Exception:
                    pass

    # ============================================================
    # Построение UI
    # ============================================================

    def _build_ui(self) -> None:  # noqa: D401 - переопределение родителя
        root = self._root

        mono = font.Font(
            family="Consolas" if self._is_windows() else "Menlo", size=10
        )
        bold = font.Font(
            family="Segoe UI" if self._is_windows() else "Helvetica",
            size=10,
            weight="bold",
        )

        body = tk.Frame(root)
        body.pack(fill=tk.BOTH, expand=True)

        # === Левая панель: показатели ===
        left = tk.Frame(body, bg="#181818", width=260)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        tk.Label(
            left,
            text="ПОКАЗАТЕЛИ",
            bg="#181818",
            fg="#7f7f7f",
            font=bold,
            anchor="w",
        ).pack(fill=tk.X, padx=10, pady=(10, 4))

        self._status_text = tk.Text(
            left,
            width=30,
            height=14,
            font=mono,
            bg="#181818",
            fg="#e0e0e0",
            relief=tk.FLAT,
            state=tk.DISABLED,
            wrap=tk.NONE,
        )
        self._status_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 8))

        # === Правая часть: лента и ввод ===
        right = tk.Frame(body)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._text = tk.scrolledtext.ScrolledText(
            right,
            wrap=tk.WORD,
            width=60,
            height=20,
            font=mono,
            bg="#1e1e1e",
            fg="#e0e0e0",
            insertbackground="#e0e0e0",
            state=tk.DISABLED,
        )
        self._text.pack(padx=8, pady=8, fill=tk.BOTH, expand=True)
        self._text.tag_config("user", foreground="#87ceeb")
        self._text.tag_config("agent", foreground="#98fb98")
        self._text.tag_config("system", foreground="#888888", font=bold)
        self._text.tag_config("error", foreground="#ff6b6b")
        self._text.tag_config("life", foreground="#ffd479", font=bold)

        input_frame = tk.Frame(right)
        input_frame.pack(padx=8, pady=(0, 6), fill=tk.X)

        self._input_var = tk.StringVar()
        self._input_entry = tk.Entry(
            input_frame,
            textvariable=self._input_var,
            font=mono,
            bg="#2a2a2a",
            fg="#e0e0e0",
            insertbackground="#e0e0e0",
        )
        self._input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._input_entry.bind("<Return>", self._on_send)
        self._input_entry.bind("<Up>", self._on_history_up)
        self._input_entry.bind("<Down>", self._on_history_down)
        self._input_entry.focus_set()

        tk.Button(
            input_frame,
            text="Сказать",
            command=self._on_send,
            bg="#3a3a3a",
            fg="#e0e0e0",
            activebackground="#4a4a4a",
            activeforeground="#ffffff",
        ).pack(side=tk.LEFT, padx=(4, 0))

        self._history = []
        self._history_idx = -1

        self._build_controls(root, mono)

    # ------------------------------------------------------------------
    # Панель управления
    # ------------------------------------------------------------------

    def _build_controls(self, root, mono) -> None:
        if not self._enabled_controls:
            return

        frame = tk.Frame(root, bg="#141414")
        frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._controls_frame = frame

        def button(text, command, *, bg="#2f2f2f"):
            widget = tk.Button(
                frame,
                text=text,
                command=command,
                bg=bg,
                fg="#e0e0e0",
                activebackground="#3f3f3f",
                activeforeground="#ffffff",
                relief=tk.RAISED,
                padx=6,
                pady=3,
            )
            widget.pack(side=tk.LEFT, padx=3, pady=6)
            return widget

        self._pause_button = button("⏸ Пауза", self._action_toggle_pause)

        # Скорость жизни
        tk.Label(
            frame, text="Темп:", bg="#141414", fg="#7f7f7f", font=mono
        ).pack(side=tk.LEFT, padx=(10, 2))

        for mode in ("live", "fast", "max"):
            self._speed_buttons[mode] = button(
                SPEED_LABELS[mode],
                lambda m=mode: self._action_set_speed(m),
                bg="#243040",
            )

        button("⏭ Шаг", self._action_step)

        tk.Label(
            frame, text="│", bg="#141414", fg="#3f3f3f", font=mono
        ).pack(side=tk.LEFT, padx=4)

        button("💾 Сохранить", self._action_save)

        # Кнопки ухода: отдельная группа, визуально отличается
        self._sleep_button = button("🌙 Сон", self._action_request_dream,
                                    bg="#3d3520")
        self._terminate_button = button(
            "🕯 Уйти без семени", self._action_request_termination,
            bg="#402020",
        )
        self._wake_button = button("☀ Разбудить", self._action_wake, bg="#204030")
        self._cancel_life_button = button(
            "✖ Отменить запрос", self._action_cancel_life, bg="#303030"
        )
        self._cancel_life_button.pack_forget()  # появляется только при запросе

        button("Выход", self._action_quit, bg="#2a2a2a")

        self._refresh_life_buttons("alive")

    # ============================================================
    # Действия панели управления
    # ============================================================

    def _action_toggle_pause(self) -> None:
        paused = bool(self._status_snapshot.get("paused"))
        event = Events.RESUME_REQUESTED if paused else Events.PAUSE_REQUESTED
        self._publish(event, {})
        self._append_system(
            "Возобновляю жизнь." if paused else "Ставлю на паузу."
        )

    def _action_set_speed(self, mode: str) -> None:
        self._publish(Events.SPEED_CHANGED, {"mode": mode})
        self._append_system(f"Темп жизни: {SPEED_LABELS.get(mode, mode)}.")

    def _action_step(self) -> None:
        self._publish(Events.STEP_REQUESTED, {})
        self._append_system("Один цикл по кнопке «Шаг».")

    def _action_save(self) -> None:
        self._publish(Events.SAVE_REQUESTED, {})
        self._append_system("Прошу сохранить состояние.")

    def _action_wake(self) -> None:
        self._publish(Events.LIFE_WAKE, {})

    def _action_cancel_life(self) -> None:
        prompt = self._life_prompt or {}
        self._publish(
            Events.LIFE_CANCEL, {"request_id": prompt.get("request_id")}
        )

    def _action_request_dream(self) -> None:
        self._publish(
            Events.LIFE_REQUEST, {"kind": "dream", "reason": "запрос из окна"}
        )

    def _action_request_termination(self) -> None:
        self._publish(
            Events.LIFE_REQUEST,
            {"kind": "terminate", "reason": "запрос из окна"},
        )

    def _action_quit(self) -> None:
        self._publish(Events.SHUTDOWN_REQUESTED, {})

    def _publish(self, event: str, payload: Dict[str, Any]) -> None:
        try:
            self.bus.publish_sync(event, payload, source="main_window")
        except Exception as exc:
            logger.warning("[MainWindow] publish %s: %s", event, exc)
            self._append_error(f"Не удалось передать событие {event}: {exc}")

    # ============================================================
    # Подтверждение ухода
    # ============================================================

    def _apply_life_prompt(self, data: Dict[str, Any]) -> None:
        kind = str(data.get("kind", "dream"))
        phrase = str(data.get("phrase", ""))
        cooldown = float(data.get("cooldown_sec") or 0.0)
        description = str(data.get("description", ""))

        self._life_prompt = data
        self._life_deadline = time.time() + cooldown if cooldown else None

        self._append_life(
            f"ЗАПРОС: {'сон' if kind == 'dream' else 'уход без семени'}\n"
            f"{description}\n\n"
            f"Чтобы подтвердить, подождите {cooldown:.0f} с и введите "
            f"точно:\n    {phrase}\n"
            f"Или нажмите «Отменить запрос»."
        )
        if self._cancel_life_button is not None:
            self._cancel_life_button.pack(side=tk.LEFT, padx=3, pady=6)
        self._start_life_countdown()

    def _apply_life_result(self, data: Dict[str, Any]) -> None:
        ok = bool(data.get("ok"))
        message = str(data.get("message", ""))
        if ok:
            self._append_life(message)
            self._clear_life_prompt()
        else:
            # Отказ — не ошибка программы: показываем спокойно.
            self._append_system(f"Уход не выполнен: {message}")

    def _clear_life_prompt(self) -> None:
        self._life_prompt = None
        self._life_deadline = None
        if self._life_tick_job is not None:
            try:
                self._root.after_cancel(self._life_tick_job)
            except Exception:
                pass
            self._life_tick_job = None
        if self._cancel_life_button is not None:
            try:
                self._cancel_life_button.pack_forget()
            except Exception:
                pass

    def _start_life_countdown(self) -> None:
        if self._life_deadline is None:
            return
        # Окно может быть ещё не построено (запрос пришёл раньше показа).
        # В этом случае отсчёт не нужен: время всё равно проверяется при
        # вводе фразы в _try_confirm_life().
        if self._root is None:
            return
        self._life_tick()

    def _life_tick(self) -> None:
        if self._life_prompt is None or self._life_deadline is None:
            return
        if self._root is None:
            return
        remaining = self._life_deadline - time.time()
        if remaining <= 0:
            self._append_system(
                "Пауза выдержана. Введите фразу в поле ниже."
            )
            self._life_deadline = None
            return
        self._life_tick_job = self._root.after(1000, self._life_tick)

    # ============================================================
    # Ввод: подтверждение ухода или обычное сообщение
    # ============================================================

    def _on_send(self, event=None) -> None:
        text = self._input_var.get().strip()
        if not text:
            return

        # Пока ждём подтверждение — проверяем, не введена ли фраза.
        if self._life_prompt is not None:
            if self._try_confirm_life(text):
                self._input_var.set("")
                return

        super()._on_send(event)

    def _try_confirm_life(self, text: str) -> bool:
        """Если введена точная фраза — отправляем подтверждение.

        Сравниваем здесь только для удобства: окончательное решение
        принимает ``LifeGuard`` в потоке агента. Обычный текст остаётся
        обычным сообщением, поэтому случайный Enter уход не подтвердит.
        """
        from src.core.life_guard import normalize_phrase

        prompt = self._life_prompt or {}
        expected = str(prompt.get("phrase", ""))
        if not expected or normalize_phrase(text) != normalize_phrase(expected):
            return False

        if self._life_deadline is not None and time.time() < self._life_deadline:
            remaining = self._life_deadline - time.time()
            self._append_system(
                f"Рано: подождите ещё {remaining:.0f} с."
            )
            return True

        self._append_user(text)
        self._publish(
            Events.LIFE_CONFIRM,
            {
                "request_id": prompt.get("request_id"),
                "phrase": text,
            },
        )
        return True

    # ============================================================
    # Лента
    # ============================================================

    def _append_life(self, text: str) -> None:
        self._append("🌙 ЖИЗНЬ:", text, tag="life")

    # ============================================================
    # Жизненный цикл
    # ============================================================

    def _position_bottom_right(self) -> None:
        """Большое окно обсерватории — по центру экрана."""
        root = self._root
        root.update_idletasks()
        width = 940
        height = 560
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        root.geometry(f"{width}x{height}+{x}+{y}")

    def _tk_mainloop(self) -> None:
        super()._tk_mainloop()
        # После закрытия окна отменить таймеры, иначе Tk ругается.
        self._clear_life_prompt()

    def _destroy_root(self) -> None:
        """Освободить виджеты окна в потоке Tk."""
        self._status_text = None
        self._controls_frame = None
        self._speed_buttons = {}
        super()._destroy_root()


__all__ = ["MainWindow", "SPEED_LABELS"]