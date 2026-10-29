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
from src.ui import life_view, theme
from src.ui.chat_window import _HAS_TK, ChatWindow

if _HAS_TK:
    import tkinter as tk
    from tkinter import font, scrolledtext


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

        # Новый каркас версии 1.0: страницы и карточки «Сейчас».
        # Снимок жизни приходит отдельно от плоского снимка показателей.
        self._life_snapshot: Dict[str, Any] = {}
        self._pages: Dict[str, Any] = {}
        self._nav_buttons: Dict[str, Any] = {}
        self._current_page: Optional[str] = None
        self._state_pill = None
        self._now_headline = None
        self._now_sub = None
        self._now_activity = None
        self._now_choice = None
        self._now_influence = None
        self._access_card = None
        self._effector_card = None
        self._mono_font = None

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
        """Потокобезопасно передать снимок жизни в окно (экран «Сейчас»)."""
        self._incoming_queue.put(("__life_data__", dict(snapshot or {})))

    # ============================================================
    # Обработка очереди
    # ============================================================

    def _handle_incoming(self, kind: str, data) -> None:
        if kind == "__status__":
            self._apply_status(data)
        elif kind == "__life_data__":
            self._apply_life_data(data)
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
            self._set_state_pill(life_state)

    def _set_state_pill(self, life_state: Any) -> None:
        """Пилюля состояния в шапке: слово берём из форматтера, не выдумываем."""
        if self._state_pill is None:
            return
        colors = {
            "alive": theme.CYAN,
            "dormant": theme.VIOLET,
            "terminated": theme.GREY,
        }
        try:
            self._state_pill.configure(
                text=life_view.life_state_label(life_state),
                fg=colors.get(str(life_state), theme.MUTED),
            )
        except Exception:
            pass

    # ============================================================
    # Экран «Сейчас»: рендер из снимка жизни
    # ============================================================

    def _apply_life_data(self, snapshot: Dict[str, Any]) -> None:
        """Перерисовать карточки «Сейчас» и «Доступы» из снимка жизни.

        Ошибка форматтера не должна рушить окно: показываем остальное.
        """
        self._life_snapshot = dict(snapshot or {})
        if self._now_headline is None:
            return
        snap = self._life_snapshot
        try:
            self._now_headline.configure(text=life_view.now_headline(snap))
            if self._now_sub is not None:
                self._now_sub.configure(text=life_view.body_summary(snap))
            self._now_activity.configure(text=self._rows_text(life_view.activity_rows(snap)))
            self._now_choice.configure(text=self._rows_text(life_view.choice_rows(snap)))
            if self._now_influence is not None:
                self._now_influence.configure(
                    text=self._rows_text(life_view.influence_rows(snap))
                )
            if self._access_card is not None:
                self._access_card.configure(text=self._rows_text(life_view.access_rows(snap)))
            if self._effector_card is not None:
                text = self._rows_text(life_view.effector_rows(snap))
                note = life_view.pending_effector_note(snap)
                if note:
                    text = f"{text}\n{note}"
                self._effector_card.configure(text=text)
            life_state = (snap.get("life") or {}).get("state")
            if life_state:
                self._set_state_pill(life_state)
        except Exception as exc:
            logger.debug("[MainWindow] life data: %s", exc)

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
                active = key == mode
                button.configure(
                    bg=theme.BG_CENTER if active else theme.SURFACE,
                    fg=theme.CYAN if active else theme.MUTED,
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
        """Современный каркас: шапка, навигация, страницы, панель управления.

        Виджеты, которые нужны унаследованной логике, остаются на месте:
        ``_text`` (лента), ``_input_var``/``_input_entry`` (ввод),
        ``_status_text`` (технические подробности). Их переезд по страницам
        не меняет поведение — только вид.
        """
        root = self._root
        root.configure(bg=theme.BG_DEEP)

        self._mono_font = font.Font(family=theme.mono_family(), size=10)
        self._ui_font = font.Font(family=theme.font_family(), size=11)
        self._card_title_font = font.Font(family=theme.font_family(), size=9)
        self._card_body_font = font.Font(family=theme.font_family(), size=12)
        self._headline_font = font.Font(
            family=theme.font_family(), size=20, weight="bold"
        )
        self._brand_font = font.Font(
            family=theme.font_family(), size=16, weight="bold"
        )

        # --- Шапка: имя и состояние жизни ---
        header = tk.Frame(root, bg=theme.BG_DEEP)
        header.pack(fill=tk.X)
        tk.Label(
            header, text=self.agent_name, font=self._brand_font,
            bg=theme.BG_DEEP, fg=theme.TEXT, anchor="w",
        ).pack(side=tk.LEFT, padx=theme.SPACING["md"], pady=theme.SPACING["sm"])
        self._state_pill = tk.Label(
            header, text="жив", font=self._ui_font,
            bg=theme.SURFACE, fg=theme.CYAN, padx=10, pady=3,
        )
        self._state_pill.pack(side=tk.LEFT)

        body = tk.Frame(root, bg=theme.BG_DEEP)
        body.pack(fill=tk.BOTH, expand=True)

        # --- Боковая навигация. Пока три реальные страницы; карта жизни,
        # дневник и занятия появятся отдельными участками этапа 7. ---
        sidebar = tk.Frame(body, bg=theme.SIDEBAR, width=190)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        tk.Label(
            sidebar, text="ЯДРО", font=self._card_title_font, bg=theme.SIDEBAR,
            fg=theme.DIMMED, anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"],
               pady=(theme.SPACING["md"], theme.SPACING["sm"]))
        self._nav_buttons = {}
        for key, label in (("now", "Сейчас"), ("access", "Доступы"),
                           ("dialog", "Диалог")):
            button = tk.Button(
                sidebar, text=label, font=self._ui_font, anchor="w",
                command=lambda k=key: self._show_page(k),
                bg=theme.SIDEBAR, fg=theme.MUTED,
                activebackground=theme.SURFACE, activeforeground=theme.TEXT,
                relief=tk.FLAT, bd=0, padx=theme.SPACING["md"], pady=8,
            )
            button.pack(fill=tk.X)
            self._nav_buttons[key] = button

        # --- Страницы ---
        content = tk.Frame(body, bg=theme.BG_DEEP)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._pages = {
            "now": self._build_page_now(content),
            "access": self._build_page_access(content),
            "dialog": self._build_page_dialog(content),
        }
        self._show_page("now")

        self._build_controls(root, self._mono_font)

    # ------------------------------------------------------------------
    # Страницы каркаса
    # ------------------------------------------------------------------

    def _make_card(self, parent, title: str):
        """Карточка: тонкая рамка, приглушённый заголовок, светлое тело."""
        frame = tk.Frame(
            parent, bg=theme.SURFACE,
            highlightbackground=theme.BORDER, highlightthickness=1,
        )
        frame.pack(fill=tk.X, padx=theme.SPACING["md"], pady=(0, theme.SPACING["sm"]))
        tk.Label(
            frame, text=title, font=self._card_title_font, bg=theme.SURFACE,
            fg=theme.MUTED, anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"],
               pady=(theme.SPACING["sm"], 2))
        body = tk.Label(
            frame, text="", font=self._card_body_font, bg=theme.SURFACE,
            fg=theme.TEXT, anchor="w", justify=tk.LEFT, wraplength=680,
        )
        body.pack(fill=tk.X, padx=theme.SPACING["md"], pady=(0, theme.SPACING["sm"]))
        return body

    def _build_page_now(self, parent):
        """Экран «Сейчас»: живая фраза, занятие, причина выбора, влияния."""
        page = tk.Frame(parent, bg=theme.BG_DEEP)
        self._now_headline = tk.Label(
            page, text="…", font=self._headline_font, bg=theme.BG_DEEP,
            fg=theme.TEXT, anchor="w", wraplength=760, justify=tk.LEFT,
        )
        self._now_headline.pack(fill=tk.X, padx=theme.SPACING["md"],
                                pady=(theme.SPACING["md"], 0))
        self._now_sub = tk.Label(
            page, text="", font=self._ui_font, bg=theme.BG_DEEP,
            fg=theme.MUTED, anchor="w",
        )
        self._now_sub.pack(fill=tk.X, padx=theme.SPACING["md"],
                           pady=(2, theme.SPACING["sm"]))
        self._now_activity = self._make_card(page, "ЧЕМ ЗАНЯТО")
        self._now_choice = self._make_card(page, "ПОЧЕМУ ИМЕННО ЭТО")
        self._now_influence = self._make_card(page, "ЧТО ВЛИЯЕТ НА ВЫБОР")
        return page

    def _build_page_access(self, parent):
        """Экран «Доступы»: что разрешено и что делает Effector."""
        page = tk.Frame(parent, bg=theme.BG_DEEP)
        self._access_card = self._make_card(page, "ЧТО РАЗРЕШЕНО")
        self._effector_card = self._make_card(page, "ДЕЙСТВИЯ")

        detail = tk.Frame(
            page, bg=theme.SURFACE,
            highlightbackground=theme.BORDER, highlightthickness=1,
        )
        detail.pack(fill=tk.BOTH, expand=True, padx=theme.SPACING["md"],
                    pady=(0, theme.SPACING["md"]))
        tk.Label(
            detail, text="ПОДРОБНОСТИ", font=self._card_title_font,
            bg=theme.SURFACE, fg=theme.MUTED, anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"],
               pady=(theme.SPACING["sm"], 2))
        self._status_text = tk.Text(
            detail, height=10, font=self._mono_font, bg=theme.SURFACE,
            fg=theme.TEXT, relief=tk.FLAT, state=tk.DISABLED, wrap=tk.NONE,
        )
        self._status_text.pack(fill=tk.BOTH, expand=True, padx=theme.SPACING["md"],
                               pady=(0, theme.SPACING["md"]))
        return page

    def _build_page_dialog(self, parent):
        """Страница диалога: знакомая лента и поле ввода."""
        page = tk.Frame(parent, bg=theme.BG_DEEP)

        self._text = scrolledtext.ScrolledText(
            page, wrap=tk.WORD, width=60, height=20, font=self._mono_font,
            bg=theme.BG_CENTER, fg=theme.TEXT, insertbackground=theme.TEXT,
            relief=tk.FLAT, state=tk.DISABLED,
        )
        self._text.pack(padx=theme.SPACING["sm"], pady=theme.SPACING["sm"],
                        fill=tk.BOTH, expand=True)
        self._text.tag_config("user", foreground="#87ceeb")
        self._text.tag_config("agent", foreground="#98fb98")
        self._text.tag_config("system", foreground="#888888",
                              font=self._card_body_font)
        self._text.tag_config("error", foreground="#ff6b6b")
        self._text.tag_config("life", foreground="#ffd479",
                              font=self._card_body_font)

        input_frame = tk.Frame(page, bg=theme.BG_DEEP)
        input_frame.pack(padx=theme.SPACING["sm"], pady=(0, theme.SPACING["sm"]),
                         fill=tk.X)
        self._input_var = tk.StringVar()
        self._input_entry = tk.Entry(
            input_frame, textvariable=self._input_var, font=self._mono_font,
            bg=theme.SURFACE, fg=theme.TEXT, insertbackground=theme.TEXT,
            relief=tk.FLAT, bd=0, highlightthickness=1,
            highlightbackground=theme.BORDER, highlightcolor=theme.CYAN,
        )
        self._input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        self._input_entry.bind("<Return>", self._on_send)
        self._input_entry.bind("<Up>", self._on_history_up)
        self._input_entry.bind("<Down>", self._on_history_down)
        self._input_entry.focus_set()
        tk.Button(
            input_frame, text="Сказать", command=self._on_send,
            bg=theme.SURFACE, fg=theme.TEXT, activebackground=theme.BORDER,
            activeforeground=theme.TEXT, relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=(4, 0))

        self._history = []
        self._history_idx = -1
        return page

    def _show_page(self, key: str) -> None:
        """Переключить страницу, не пересоздавая окно."""
        if not self._pages:
            return
        for page in self._pages.values():
            page.pack_forget()
        page = self._pages.get(key)
        if page is not None:
            page.pack(fill=tk.BOTH, expand=True)
        for name, button in self._nav_buttons.items():
            active = name == key
            try:
                button.configure(
                    bg=theme.SURFACE if active else theme.SIDEBAR,
                    fg=theme.TEXT if active else theme.MUTED,
                )
            except Exception:
                pass
        self._current_page = key

    @staticmethod
    def _rows_text(rows) -> str:
        """Строки карточки в один текст: «подпись: значение»."""
        return "\n".join(f"{label}: {value}" for label, value in rows)

    # ------------------------------------------------------------------
    # Панель управления
    # ------------------------------------------------------------------

    def _build_controls(self, root, mono) -> None:
        if not self._enabled_controls:
            return

        frame = tk.Frame(
            root, bg=theme.BG_DEEP,
            highlightbackground=theme.BORDER, highlightthickness=1,
        )
        frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._controls_frame = frame

        def button(text, command, *, bg=theme.SURFACE, fg=theme.TEXT):
            widget = tk.Button(
                frame,
                text=text,
                command=command,
                bg=bg,
                fg=fg,
                activebackground=theme.BORDER,
                activeforeground=theme.TEXT,
                relief=tk.FLAT,
                bd=0,
                padx=10,
                pady=5,
            )
            widget.pack(side=tk.LEFT, padx=3, pady=6)
            return widget

        self._pause_button = button("⏸ Пауза", self._action_toggle_pause)

        # Скорость жизни
        tk.Label(
            frame, text="Темп:", bg=theme.BG_DEEP, fg=theme.MUTED,
            font=self._ui_font,
        ).pack(side=tk.LEFT, padx=(10, 2))

        for mode in ("live", "fast", "max"):
            self._speed_buttons[mode] = button(
                SPEED_LABELS[mode],
                lambda m=mode: self._action_set_speed(m),
                bg=theme.BG_CENTER,
                fg=theme.MUTED,
            )

        button("⏭ Шаг", self._action_step)

        tk.Label(
            frame, text="│", bg=theme.BG_DEEP, fg=theme.BORDER,
            font=self._ui_font,
        ).pack(side=tk.LEFT, padx=4)

        button("💾 Сохранить", self._action_save)

        # Кнопки ухода: отдельная группа, визуально отличается
        self._sleep_button = button("🌙 Сон", self._action_request_dream)
        self._terminate_button = button(
            "🕯 Уйти без семени", self._action_request_termination,
            fg=theme.DANGER,
        )
        self._wake_button = button("☀ Разбудить", self._action_wake,
                                   fg=theme.GREEN)
        self._cancel_life_button = button(
            "✖ Отменить запрос", self._action_cancel_life
        )
        self._cancel_life_button.pack_forget()  # появляется только при запросе

        button("Выход", self._action_quit)

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
        width = 1040
        height = 680
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