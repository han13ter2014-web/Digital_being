"""MainWindow — окно наблюдения и общения с цифровой жизнью.

Каркас версии 1.0: шапка с состоянием жизни, боковая навигация
(«Сейчас», «Карта жизни», «Доступы», «Диалог»), карточки из реального
снимка Core и нижняя панель управления. Страницы:

1. **Сейчас** — живая фраза, занятие, причина выбора, влияния и тело.
2. **Карта жизни** — Canvas с концепциями, намерениями, занятиями и
   ценностями; связи только те, что записаны в Core.
3. **Доступы** — реальные переключатели и счётчики Effector.
4. **Диалог** — лента общения и ввод.

Кнопки сна и ухода не убивают агента: они создают запрос, а окно просит
ввести точную фразу. Подробности — ``src/core/life_guard.py``.

Окно ничего не решает про жизнь само: оно публикует события, а
обрабатывает их ``LifeController`` в потоке агента.

Потокобезопасность: окно работает в потоке Tk. Данные приходят через
очередь (``push_status``, ``push_life_status``, ``push_graph``), действия
уходят через ``bus.publish_sync``. Прямого доступа к объектам агента из
потока Tk нет.

Известное ограничение: при выходе из процесса Windows может напечатать
``Tcl_AsyncDelete: async handler deleted by the wrong thread``. Это
следствие того, что Tk живёт в фоновом потоке, а сборка мусора при
завершении происходит в главном. На работу окна не влияет. Устраняется
переносом Tk в главный поток — это делается в единой точке входа
(``main.py``).
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Optional

from src.core.event_bus import Events
from src.ui import diary_view, graph_view, life_view, theme
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
        self._display_name_label = None
        self._now_headline = None
        self._now_sub = None
        self._now_activity = None
        self._now_choice = None
        self._now_influence = None
        self._diary_list = None
        self._diary_detail = None
        self._activity_list = None
        self._activity_detail = None
        self._access_card = None
        self._effector_card = None
        self._mono_font = None

        # Карта жизни: данные приходят отдельным, более редким потоком.
        self._graph_canvas = None
        self._graph_detail = None
        self._graph_counter = None
        self._diary_entries = []
        self._activity_entries = []
        self._activity_game = None
        self._graph_data: Dict[str, Any] = {}
        self._graph_tag_nodes: Dict[str, Dict[str, Any]] = {}
        self._graph_positions: Dict[str, Any] = {}
        self._graph_size = (0, 0)
        self._graph_render_job = None
        self._graph_selected: Optional[str] = None

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

    def push_graph(self, graph: Dict[str, Any]) -> None:
        """Потокобезопасно передать карту жизни (приходит реже снимка)."""
        self._incoming_queue.put(("__graph__", dict(graph or {})))

    # ============================================================
    # Обработка очереди
    # ============================================================

    def _handle_incoming(self, kind: str, data) -> None:
        if kind == "__status__":
            self._apply_status(data)
        elif kind == "__life_data__":
            self._apply_life_data(data)
        elif kind == "__graph__":
            self._apply_graph_data(data)
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
            new_name = snap.get("name")
            if isinstance(new_name, str) and new_name and new_name != self.agent_name:
                self._handle_incoming("__name_changed__", new_name)
            if self._display_name_label is not None:
                self._display_name_label.configure(text=self.agent_name)
            self._now_headline.configure(text=life_view.now_headline(snap))
            if self._now_sub is not None:
                self._now_sub.configure(text=life_view.body_summary(snap))
            self._now_activity.configure(text=self._rows_text(life_view.activity_rows(snap)))
            self._now_choice.configure(text=self._rows_text(life_view.choice_rows(snap)))
            if self._now_influence is not None:
                self._now_influence.configure(
                    text=self._rows_text(life_view.influence_rows(snap))
                )
            self._apply_diary_data(snap)
            self._apply_activity_data(snap)
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
        self._display_name_label = tk.Label(
            header, text=self.agent_name, font=self._brand_font,
            bg=theme.BG_DEEP, fg=theme.TEXT, anchor="w",
        )
        self._display_name_label.pack(side=tk.LEFT, padx=theme.SPACING["md"], pady=theme.SPACING["sm"])
        self._state_pill = tk.Label(
            header, text="жив", font=self._ui_font,
            bg=theme.SURFACE, fg=theme.CYAN, padx=10, pady=3,
        )
        self._state_pill.pack(side=tk.LEFT)

        body = tk.Frame(root, bg=theme.BG_DEEP)
        body.pack(fill=tk.BOTH, expand=True)

        # --- Боковая навигация: жизнь отдельно от системных действий. ---
        sidebar = tk.Frame(body, bg=theme.SIDEBAR, width=214)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        tk.Label(
            sidebar, text="ЯДРО", font=self._brand_font, bg=theme.SIDEBAR,
            fg=theme.TEXT, anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"],
               pady=(theme.SPACING["lg"], 0))
        tk.Label(
            sidebar, text="живая карта", font=self._card_title_font,
            bg=theme.SIDEBAR, fg=theme.MUTED, anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(0, theme.SPACING["lg"]))

        def nav_section(text):
            tk.Label(
                sidebar, text=text, font=self._card_title_font,
                bg=theme.SIDEBAR, fg=theme.DIMMED, anchor="w",
            ).pack(fill=tk.X, padx=theme.SPACING["md"],
                   pady=(theme.SPACING["sm"], theme.SPACING["xs"]))

        self._nav_buttons = {}
        nav_section("ЖИЗНЬ")
        navigation = (("now", "◉", "Сейчас"), ("graph", "✦", "Карта жизни"),
                      ("diary", "◌", "Дневник"), ("activities", "◇", "Занятия"))
        for key, marker, label in navigation:
            button = tk.Button(
                sidebar, text=f"  {marker}  {label}", font=self._ui_font,
                anchor="w", command=lambda k=key: self._show_page(k),
                bg=theme.SIDEBAR, fg=theme.MUTED,
                activebackground=theme.SURFACE, activeforeground=theme.TEXT,
                relief=tk.FLAT, bd=0, padx=theme.SPACING["sm"], pady=9,
            )
            button.pack(fill=tk.X, padx=theme.SPACING["sm"])
            self._nav_buttons[key] = button

        nav_section("СИСТЕМА")
        for key, marker, label in (("access", "▣", "Доступы"), ("dialog", "◫", "Диалог")):
            button = tk.Button(
                sidebar, text=f"  {marker}  {label}", font=self._ui_font,
                anchor="w", command=lambda k=key: self._show_page(k),
                bg=theme.SIDEBAR, fg=theme.MUTED,
                activebackground=theme.SURFACE, activeforeground=theme.TEXT,
                relief=tk.FLAT, bd=0, padx=theme.SPACING["sm"], pady=9,
            )
            button.pack(fill=tk.X, padx=theme.SPACING["sm"])
            self._nav_buttons[key] = button

        # --- Страницы ---
        content = tk.Frame(body, bg=theme.BG_DEEP)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._pages = {
            "now": self._build_page_now(content),
            "graph": self._build_page_graph(content),
            "diary": self._build_page_diary(content),
            "activities": self._build_page_activities(content),
            "access": self._build_page_access(content),
            "dialog": self._build_page_dialog(content),
        }
        self._show_page("now")

        self._build_controls(root, self._mono_font)

    # ------------------------------------------------------------------
    # Страницы каркаса
    # ------------------------------------------------------------------

    def _make_card(self, parent, title: str, *, side=None, expand=False,
                   wraplength=680):
        """Карточка: тонкая рамка, приглушённый заголовок, светлое тело."""
        frame = tk.Frame(
            parent, bg=theme.SURFACE,
            highlightbackground=theme.BORDER, highlightthickness=1,
        )
        options = {"fill": tk.BOTH if expand else tk.X,
                   "padx": theme.SPACING["md"],
                   "pady": (0, theme.SPACING["sm"])}
        if side is not None:
            options["side"] = side
            options["padx"] = (0, theme.SPACING["sm"])
            options["expand"] = expand
        frame.pack(**options)
        tk.Label(
            frame, text=title, font=self._card_title_font, bg=theme.SURFACE,
            fg=theme.MUTED, anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"],
               pady=(theme.SPACING["sm"], 2))
        body = tk.Label(
            frame, text="", font=self._card_body_font, bg=theme.SURFACE,
            fg=theme.TEXT, anchor="w", justify=tk.LEFT, wraplength=wraplength,
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
        cards = tk.Frame(page, bg=theme.BG_DEEP)
        cards.pack(fill=tk.X, padx=theme.SPACING["md"])
        self._now_activity = self._make_card(
            cards, "ЧЕМ ЗАНЯТО", side=tk.LEFT, expand=True, wraplength=330
        )
        self._now_choice = self._make_card(
            cards, "ПОЧЕМУ ИМЕННО ЭТО", side=tk.LEFT, expand=True, wraplength=330
        )
        self._now_influence = self._make_card(
            page, "ЧТО ВЛИЯЕТ НА ВЫБОР", wraplength=720
        )
        return page

    # ------------------------------------------------------------------
    # Карта жизни
    # ------------------------------------------------------------------

    _NODE_TYPE_LABELS = {
        "concept": "концепция",
        "intention": "намерение",
        "value": "ценность ядра",
        "activity": "занятие",
        "forgotten": "забытое намерение",
        "topic": "тема",
    }

    _EDGE_BASIS = {
        "association": "запись ментальной модели: концепции связаны по опыту",
        "about": "намерение называет эту тему",
        "uses": "намерение породило это занятие",
    }

    def _build_page_graph(self, parent):
        """Экран «Карта жизни»: Canvas с реальными узлами и панель деталей."""
        page = tk.Frame(parent, bg=theme.BG_DEEP)
        tk.Label(
            page, text="Карта жизни", font=self._brand_font, bg=theme.BG_DEEP,
            fg=theme.TEXT, anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"],
               pady=(theme.SPACING["md"], 0))
        tk.Label(
            page,
            text="узлы — то, что ядро знает, хочет и пережило; связи — только записанные",
            font=self._ui_font, bg=theme.BG_DEEP, fg=theme.MUTED, anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(0, theme.SPACING["sm"]))

        body = tk.Frame(page, bg=theme.BG_DEEP)
        body.pack(fill=tk.BOTH, expand=True, padx=theme.SPACING["md"],
                  pady=(0, theme.SPACING["md"]))

        left = tk.Frame(body, bg=theme.BG_DEEP)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._graph_canvas = tk.Canvas(
            left, bg=theme.BG_CENTER, highlightthickness=1,
            highlightbackground=theme.BORDER, bd=0,
        )
        self._graph_canvas.pack(fill=tk.BOTH, expand=True)
        self._graph_canvas.bind("<Configure>", self._on_graph_resize)
        self._graph_canvas.bind("<Button-1>", self._on_graph_click)

        legend = tk.Frame(left, bg=theme.BG_DEEP)
        legend.pack(fill=tk.X, pady=(theme.SPACING["sm"], 0))
        for kind in ("concept", "intention", "value", "activity", "forgotten"):
            item = tk.Frame(legend, bg=theme.BG_DEEP)
            item.pack(side=tk.LEFT, padx=(0, theme.SPACING["md"]))
            swatch = tk.Canvas(
                item, width=18, height=18, bg=theme.BG_DEEP,
                highlightthickness=0,
            )
            swatch.pack(side=tk.LEFT)
            self._draw_node_shape(swatch, 9, 9, 5, kind)
            tk.Label(
                item, text=self._NODE_TYPE_LABELS[kind], font=self._ui_font,
                bg=theme.BG_DEEP, fg=theme.MUTED,
            ).pack(side=tk.LEFT, padx=(4, 0))

        detail = tk.Frame(
            body, bg=theme.SURFACE, width=310,
            highlightbackground=theme.BORDER, highlightthickness=1,
        )
        detail.pack(side=tk.RIGHT, fill=tk.Y, padx=(theme.SPACING["md"], 0))
        detail.pack_propagate(False)
        tk.Label(
            detail, text="УЗЕЛ", font=self._card_title_font, bg=theme.SURFACE,
            fg=theme.MUTED, anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"],
               pady=(theme.SPACING["sm"], 2))
        self._graph_detail = tk.Label(
            detail, text="Выберите узел на карте — покажу только то,\n"
                        "что ядро действительно записало.",
            font=self._ui_font, bg=theme.SURFACE, fg=theme.TEXT,
            anchor="nw", justify=tk.LEFT, wraplength=274,
        )
        self._graph_detail.pack(fill=tk.BOTH, expand=True,
                                padx=theme.SPACING["md"],
                                pady=(0, theme.SPACING["sm"]))
        self._graph_counter = tk.Label(
            detail, text="узлов: 0 · связей: 0", font=self._card_title_font,
            bg=theme.SURFACE, fg=theme.DIMMED, anchor="w",
        )
        self._graph_counter.pack(fill=tk.X, padx=theme.SPACING["md"],
                                 pady=(0, theme.SPACING["sm"]))
        return page

    def _draw_node_shape(self, canvas, x, y, radius, kind, *, tags=()):
        """Нарисовать узел формы и цвета, закреплённых за его типом."""
        color = theme.node_color(kind)
        shape = theme.node_shape(kind)
        if shape == "diamond":
            canvas.create_polygon(
                x, y - radius, x + radius, y, x, y + radius, x - radius, y,
                fill=color, outline=color, tags=tags,
            )
        elif shape == "hexagon":
            points = []
            for index in range(6):
                angle = math.pi / 3.0 * index - math.pi / 6.0
                points.extend((x + radius * math.cos(angle),
                               y + radius * math.sin(angle)))
            canvas.create_polygon(*points, fill=color, outline=color, tags=tags)
        elif shape == "ring":
            canvas.create_oval(
                x - radius, y - radius, x + radius, y + radius,
                fill=theme.BG_CENTER, outline=color, width=3, tags=tags,
            )
        elif shape == "outline":
            canvas.create_oval(
                x - radius, y - radius, x + radius, y + radius,
                fill="", outline=color, width=1, tags=tags,
            )
        else:
            canvas.create_oval(
                x - radius, y - radius, x + radius, y + radius,
                fill=color, outline=color, tags=tags,
            )

    def _on_graph_resize(self, event) -> None:
        size = (int(event.width), int(event.height))
        if size == self._graph_size:
            return
        self._graph_size = size
        canvas = self._graph_canvas
        if canvas is None:
            return
        # При перетаскивании окна Configure приходит десятки раз в секунду:
        # перерисовываем один раз после паузы, а не на каждый пиксель.
        if self._graph_render_job is not None:
            try:
                canvas.after_cancel(self._graph_render_job)
            except Exception:
                pass
        self._graph_render_job = canvas.after(100, self._render_after_resize)

    def _render_after_resize(self) -> None:
        self._graph_render_job = None
        self._render_graph()

    def _on_graph_click(self, event) -> None:
        canvas = self._graph_canvas
        if canvas is None:
            return
        for item in canvas.find_withtag("current"):
            for tag in canvas.gettags(item):
                node = self._graph_tag_nodes.get(tag)
                if node is not None:
                    self._graph_selected = node.get("id")
                    self._show_node_detail(node)
                    self._render_graph()
                    return
        edge = self._nearest_edge(event.x, event.y)
        if edge is not None:
            self._graph_selected = None
            self._show_edge_detail(edge)
            self._render_graph()

    @staticmethod
    def _distance_to_segment(point_x, point_y, start, end) -> float:
        """Расстояние от точки до отрезка — чтобы тонкую связь было легко поймать."""
        start_x, start_y = start
        end_x, end_y = end
        delta_x, delta_y = end_x - start_x, end_y - start_y
        length_sq = delta_x * delta_x + delta_y * delta_y
        if length_sq <= 0:
            return math.hypot(point_x - start_x, point_y - start_y)
        t = max(0.0, min(1.0, (
            (point_x - start_x) * delta_x + (point_y - start_y) * delta_y
        ) / length_sq))
        return math.hypot(
            point_x - (start_x + t * delta_x),
            point_y - (start_y + t * delta_y),
        )

    def _nearest_edge(self, x, y, *, max_distance: float = 7.0):
        """Ближайшая реальная связь под курсором (или None)."""
        best = None
        best_distance = max_distance
        for edge in self._graph_data.get("edges") or []:
            start = self._graph_positions.get(edge.get("source"))
            end = self._graph_positions.get(edge.get("target"))
            if not start or not end:
                continue
            distance = self._distance_to_segment(x, y, start, end)
            if distance <= best_distance:
                best_distance = distance
                best = edge
        return best

    def _show_edge_detail(self, edge: Dict[str, Any]) -> None:
        """Карточка связи: что именно записано, без домыслов о смысле."""
        if self._graph_detail is None:
            return
        nodes = {node.get("id"): node for node in self._graph_data.get("nodes") or []}
        source = nodes.get(edge.get("source")) or {}
        target = nodes.get(edge.get("target")) or {}
        kind = str(edge.get("kind") or "")
        lines = [
            f"{source.get('label', '—')} → {target.get('label', '—')}",
            "связь", "",
            f"тип: {edge.get('label') or kind or '—'}",
            f"основание: {self._EDGE_BASIS.get(kind, 'записано в Core')}",
        ]
        if kind == "association":
            lines.append(f"вес связи: {float(edge.get('weight') or 0.0):.2f}")
        self._graph_detail.configure(text="\n".join(lines))

    def _show_node_detail(self, node: Dict[str, Any]) -> None:
        """Показать карточку выбранного узла — только записанные поля."""
        if self._graph_detail is None:
            return
        kind = str(node.get("kind") or "")
        lines = [str(node.get("label") or "—"),
                 self._NODE_TYPE_LABELS.get(kind, "узел"), ""]
        detail = node.get("detail") or {}
        for key, value in detail.items():
            if isinstance(value, bool):
                value = "да" if value else "нет"
            elif value is None or value == "":
                value = "—"
            lines.append(f"{key}: {value}")
        if not detail:
            lines.append("Подробностей ядро пока не записало.")
        elif kind == "concept":
            lines.extend(["", "уверенность — мера доверия модели, а не факт."])
        self._graph_detail.configure(text="\n".join(lines))

    def _render_graph(self) -> None:
        """Перерисовать карту. Ошибка рисунка не должна рушить окно."""
        canvas = self._graph_canvas
        if canvas is None:
            return
        try:
            width = max(int(canvas.winfo_width()), 1)
            height = max(int(canvas.winfo_height()), 1)
            canvas.delete("all")
            self._graph_tag_nodes = {}
            if width < 80 or height < 80:
                return

            nodes = list(self._graph_data.get("nodes") or [])
            if not nodes:
                canvas.create_text(
                    width / 2, height / 2,
                    text="Пока нечего показать: ядро ещё не накопило\n"
                         "знаний, намерений и занятий для карты.",
                    fill=theme.MUTED, font=self._ui_font,
                    width=max(160, width - 80), justify=tk.CENTER,
                )
                return

            positions = graph_view.layout_nodes(nodes, width, height)
            self._graph_positions = positions
            for edge in self._graph_data.get("edges") or []:
                start = positions.get(edge.get("source"))
                end = positions.get(edge.get("target"))
                if not start or not end:
                    continue
                canvas.create_line(
                    start[0], start[1], end[0], end[1],
                    fill=theme.EDGE, width=1, tags=("edge",),
                )

            labels = graph_view.layout_labels(nodes, positions, width, height)
            for index, node in enumerate(nodes):
                position = positions.get(node.get("id"))
                if position is None:
                    continue
                x, y = position
                kind = str(node.get("kind") or "")
                weight = node.get("weight", 0.0)
                radius = graph_view.node_radius(weight, kind)
                tag = f"node-{index}"
                self._graph_tag_nodes[tag] = node
                tags = ("node", tag)
                if node.get("id") == self._graph_selected:
                    canvas.create_oval(
                        x - radius - 6, y - radius - 6,
                        x + radius + 6, y + radius + 6,
                        outline=theme.TEXT, width=1, tags=tags,
                    )
                self._draw_node_shape(canvas, x, y, radius, kind, tags=tags)

            for index, node in enumerate(nodes):
                label = labels.get(node.get("id"))
                if label is None:
                    continue
                label_x, label_y, anchor = label
                canvas.create_text(
                    label_x, label_y,
                    text=graph_view.short_label(node.get("label")),
                    anchor=anchor,
                    fill=theme.MUTED if node.get("kind") == "forgotten" else theme.TEXT,
                    font=self._ui_font, tags=("node", f"node-{index}"),
                )
        except Exception as exc:
            logger.debug("[MainWindow] graph render: %s", exc)

    def _apply_graph_data(self, graph: Dict[str, Any]) -> None:
        self._graph_data = dict(graph or {})
        nodes = self._graph_data.get("nodes") or []
        edges = self._graph_data.get("edges") or []
        if self._graph_counter is not None:
            text = f"узлов: {len(nodes)} · связей: {len(edges)}"
            if self._graph_data.get("truncated"):
                text += " · показаны не все"
            try:
                self._graph_counter.configure(text=text)
            except Exception:
                pass
        self._render_graph()

    def _build_page_diary(self, parent):
        """Дневник: лента автобиографических эпизодов из Delamain memory."""
        page = tk.Frame(parent, bg=theme.BG_DEEP)
        self._page_heading(page, "Дневник", "только записанные события жизни, от новых к старым")
        body = tk.Frame(page, bg=theme.BG_DEEP)
        body.pack(fill=tk.BOTH, expand=True, padx=theme.SPACING["md"], pady=(0, theme.SPACING["md"]))
        self._diary_list = tk.Listbox(
            body, width=32, font=self._ui_font, bg=theme.BG_CENTER,
            fg=theme.TEXT, selectbackground=theme.GLOW_CYAN,
            selectforeground=theme.TEXT, relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightbackground=theme.BORDER,
        )
        self._diary_list.pack(side=tk.LEFT, fill=tk.Y)
        self._diary_list.bind("<<ListboxSelect>>", self._on_diary_select)
        self._diary_detail = self._detail_panel(body, "ЭПИЗОД")
        return page

    def _build_page_activities(self, parent):
        """Каталог занятий: черновики и локальная партия, только чтение."""
        page = tk.Frame(parent, bg=theme.BG_DEEP)
        self._page_heading(page, "Занятия", "работы и партии, которые Core действительно создал")
        body = tk.Frame(page, bg=theme.BG_DEEP)
        body.pack(fill=tk.BOTH, expand=True, padx=theme.SPACING["md"], pady=(0, theme.SPACING["md"]))
        self._activity_list = tk.Listbox(
            body, width=32, font=self._ui_font, bg=theme.BG_CENTER,
            fg=theme.TEXT, selectbackground=theme.GLOW_AMBER,
            selectforeground=theme.TEXT, relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightbackground=theme.BORDER,
        )
        self._activity_list.pack(side=tk.LEFT, fill=tk.Y)
        self._activity_list.bind("<<ListboxSelect>>", self._on_activity_select)
        self._activity_detail = self._detail_panel(body, "ЗАНЯТИЕ")
        return page

    def _page_heading(self, page, title, subtitle):
        tk.Label(page, text=title, font=self._brand_font, bg=theme.BG_DEEP,
                 fg=theme.TEXT, anchor="w").pack(fill=tk.X, padx=theme.SPACING["md"],
                                                  pady=(theme.SPACING["md"], 0))
        tk.Label(page, text=subtitle, font=self._ui_font, bg=theme.BG_DEEP,
                 fg=theme.MUTED, anchor="w").pack(fill=tk.X, padx=theme.SPACING["md"],
                                                   pady=(0, theme.SPACING["sm"]))

    def _detail_panel(self, parent, title):
        panel = tk.Frame(parent, bg=theme.SURFACE, width=400,
                         highlightbackground=theme.BORDER, highlightthickness=1)
        panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(theme.SPACING["md"], 0))
        panel.pack_propagate(False)
        tk.Label(panel, text=title, font=self._card_title_font, bg=theme.SURFACE,
                 fg=theme.MUTED, anchor="w").pack(fill=tk.X, padx=theme.SPACING["md"],
                                                   pady=(theme.SPACING["md"], theme.SPACING["sm"]))
        label = tk.Label(panel, text="Выберите запись слева.", font=self._ui_font,
                         bg=theme.SURFACE, fg=theme.TEXT, anchor="nw", justify=tk.LEFT,
                         wraplength=500)
        label.pack(fill=tk.BOTH, expand=True, padx=theme.SPACING["md"], pady=(0, theme.SPACING["md"]))
        return label

    def _apply_diary_data(self, snapshot):
        if self._diary_list is None:
            return
        self._diary_entries = diary_view.diary_rows(snapshot)
        self._diary_list.delete(0, tk.END)
        for episode in self._diary_entries:
            self._diary_list.insert(tk.END, diary_view.episode_title(episode))
        if not self._diary_entries:
            self._diary_list.insert(tk.END, "Записей пока нет")
            self._diary_list.configure(state=tk.DISABLED)
        else:
            self._diary_list.configure(state=tk.NORMAL)

    def _apply_activity_data(self, snapshot):
        if self._activity_list is None:
            return
        self._activity_entries = diary_view.draft_rows(snapshot)
        self._activity_list.delete(0, tk.END)
        for draft in self._activity_entries:
            self._activity_list.insert(tk.END, f"Черновик · {draft.get('theme', 'без темы')}")
        game = (snapshot.get("activities") or {}).get("game")
        self._activity_game = game if isinstance(game, dict) else None
        if self._activity_game is not None:
            self._activity_list.insert(tk.END, "Партия · крестики-нолики")
        if not self._activity_entries and self._activity_game is None:
            self._activity_list.insert(tk.END, "Занятий пока нет")
            self._activity_list.configure(state=tk.DISABLED)
        else:
            self._activity_list.configure(state=tk.NORMAL)

    def _on_diary_select(self, _event=None):
        if self._diary_detail is None:
            return
        selection = self._diary_list.curselection()
        if selection and selection[0] < len(self._diary_entries):
            self._diary_detail.configure(text=diary_view.rows_text(
                diary_view.episode_rows(self._diary_entries[selection[0]])
            ))

    def _on_activity_select(self, _event=None):
        if self._activity_detail is None:
            return
        selection = self._activity_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index < len(self._activity_entries):
            rows = diary_view.draft_detail(self._activity_entries[index])
        elif self._activity_game is not None and index == len(self._activity_entries):
            rows = diary_view.game_detail(self._life_snapshot)
        else:
            return
        self._activity_detail.configure(text=diary_view.rows_text(rows))

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
            page, wrap=tk.WORD, width=60, height=20, font=self._card_body_font,
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
        if key == "graph" and self._graph_canvas is not None:
            self._render_graph()

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

        def button(text, command, *, bg=theme.SURFACE, fg=theme.TEXT,
                   padx=10):
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
                padx=padx,
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

        button("Сохранить", self._action_save, padx=8)

        tk.Label(
            frame, text="  ЖИЗНЬ", bg=theme.BG_DEEP, fg=theme.DIMMED,
            font=self._card_title_font,
        ).pack(side=tk.LEFT, padx=(12, 2))
        self._sleep_button = button("Сон", self._action_request_dream, padx=8)
        self._terminate_button = button(
            "Уйти", self._action_request_termination,
            fg=theme.DANGER, padx=8,
        )
        self._wake_button = button("Разбудить", self._action_wake,
                                   fg=theme.GREEN, padx=8)
        self._cancel_life_button = button(
            "Отменить запрос", self._action_cancel_life, padx=8
        )
        self._cancel_life_button.pack_forget()  # появляется только при запросе

        button("Выход", self._action_quit, fg=theme.MUTED, padx=8)

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