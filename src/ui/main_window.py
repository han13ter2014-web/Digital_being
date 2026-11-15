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
import urllib.parse
from typing import Any, Dict, List, Optional

from src.core.event_bus import Events
from src.ui import diary_view, graph_view, i18n, life_view, theme
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
        self._language = i18n.load_saved_language()
        self._language_var = None
        self._language_menu = None
        self._static_texts: Dict[Any, str] = {}

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
        self._now_body = None
        self._now_dominant = None
        self._now_emotion_inner = None
        self._now_emotion_canvas = None
        self._now_emotion_empty = None
        self._now_emotion_labels: Dict[str, Any] = {}
        self._now_emotion_values: Dict[str, Any] = {}
        self._now_emotion_bars: Dict[str, Any] = {}
        self._now_emotion_signature: Optional[tuple] = None
        self._diary_detail = None
        self._activity_list = None
        self._activity_detail = None
        self._activity_board = None
        self._activity_board_cells: List[Any] = []
        self._access_card = None
        self._effector_card = None
        self._access_vars: Dict[str, Any] = {}
        self._access_switches: Dict[str, Any] = {}
        self._access_status_labels: Dict[str, Any] = {}
        self._mono_font = None

        # Дневник: серии подряд одинаковых эпизодов и раскрытые группы.
        self._diary_entries: List[Dict[str, Any]] = []
        self._diary_groups: List[List[Dict[str, Any]]] = []
        self._diary_rows_view: List[Dict[str, Any]] = []
        self._diary_row_frames: List[Any] = []
        self._diary_selected: Optional[int] = None
        self._diary_expanded: set = set()
        self._diary_canvas = None
        self._diary_inner = None
        self._diary_rendered_language: Optional[str] = None
        self._activity_rendered_language: Optional[str] = None

        # Карточки источников в диалоге и их состояние «развёрнуто».
        self._web_cards: Dict[str, Dict[str, Any]] = {}
        self._web_card_counter = 0

        # Карта жизни: данные приходят отдельным, более редким потоком.
        self._graph_canvas = None
        self._graph_detail = None
        self._graph_counter = None
        self._graph_zoom_label = None
        self._activity_entries: List[Dict[str, Any]] = []
        self._activity_game = None
        self._graph_data: Dict[str, Any] = {}
        self._graph_tag_nodes: Dict[str, Dict[str, Any]] = {}
        self._graph_positions: Dict[str, Any] = {}
        self._graph_size = (0, 0)
        self._graph_render_job = None
        self._graph_selected: Optional[str] = None
        self._graph_filter: Optional[set] = None
        self._graph_filter_buttons: Dict[str, Any] = {}
        self._graph_zoom = 1.0
        self._graph_offset = (0.0, 0.0)
        self._graph_pan: Dict[str, Any] = {
            "moved": False,
            "start": (0, 0),
            "origin": (0.0, 0.0),
        }

        self._subscribe_life_events()

    # ============================================================
    # Язык представления (DTO и содержимое событий не меняются)
    # ============================================================

    def _t(self, value: Any) -> str:
        return i18n.text(value, self._language)

    def _translate_static_text(self, value: Any) -> str:
        raw = str(value)
        translated = self._t(raw)
        if translated != raw or raw in i18n.TEXTS["en"]:
            return translated
        # Кнопки навигации содержат непереводимый символ-marcер и подпись.
        if "  " in raw:
            prefix, label = raw.rsplit("  ", 1)
            return f"{prefix}  {self._t(label)}"
        return raw

    def _translate_static_widgets(self, widget=None) -> None:
        """Перевести только статические Label/Button, не очищая ленту диалога."""
        if self._root is None:
            return
        dynamic = {
            self._display_name_label,
            self._state_pill,
            self._now_headline,
            self._now_sub,
            self._now_activity,
            self._now_choice,
            self._now_influence,
            self._now_body,
            self._now_dominant,
            self._now_emotion_empty,
            *self._now_emotion_labels.values(),
            *self._now_emotion_values.values(),
            self._access_card,
            self._effector_card,
            *self._access_status_labels.values(),
            self._graph_detail,
            self._graph_counter,
            self._graph_zoom_label,
            self._diary_detail,
            self._activity_detail,
            self._pause_button,
        }
        for child in (
            widget.winfo_children()
            if widget is not None
            else self._root.winfo_children()
        ):
            if isinstance(child, (tk.Label, tk.Button)) and child not in dynamic:
                if child not in self._static_texts:
                    self._static_texts[child] = str(child.cget("text"))
                child.configure(
                    text=self._translate_static_text(self._static_texts[child])
                )
            self._translate_static_widgets(child)

    def _set_language(self, display_name: str) -> None:
        selected = next(
            (code for code, label in i18n.LANGUAGES.items() if label == display_name),
            i18n.normalize_language(display_name),
        )
        self._language = selected
        try:
            i18n.save_language(selected)
        except OSError as exc:
            logger.warning("[MainWindow] language save: %s", exc)
            self._append_error(f"{self._t('Не удалось сохранить язык')}: {exc}")
        self._translate_static_widgets()
        self._apply_status(self._status_snapshot)
        self._apply_life_data(self._life_snapshot)
        if self._diary_selected is None and self._diary_detail is not None:
            self._diary_detail.configure(text=self._t("Выберите запись слева."))
        if self._activity_list is not None and self._activity_detail is not None:
            if not self._activity_list.curselection():
                self._activity_detail.configure(text=self._t("Выберите запись слева."))
        self._refresh_pause_button(bool(self._status_snapshot.get("paused")))
        self._update_graph_counter()
        self._render_graph()
        selected_node = next(
            (
                node
                for node in self._graph_data.get("nodes") or []
                if node.get("id") == self._graph_selected
            ),
            None,
        )
        if selected_node is not None:
            self._show_node_detail(selected_node)
        elif self._graph_selected is None and self._graph_detail is not None:
            self._graph_detail.configure(
                text=self._t(
                    "Выберите узел на карте — покажу только то,\n"
                    "что ядро действительно записало."
                )
            )
        if self._activity_list is not None:
            selection = self._activity_list.curselection()
            if selection:
                self._on_activity_select()

    def _graph_node_label(self, node: Dict[str, Any]) -> str:
        """Локализовать подпись по стабильному ID, не меняя узел графа."""
        node_id = str(node.get("id") or "")
        kind = str(node.get("kind") or "")
        if kind == "activity" and node_id.startswith("activity:"):
            return i18n.value_label(node_id.split(":", 1)[1], self._language)
        if kind == "value" and node_id.startswith("value:"):
            return i18n.value_label(node_id.split(":", 1)[1], self._language)
        if kind in {"intention", "forgotten"}:
            detail = node.get("detail") or {}
            action = detail.get("действие")
            if action:
                label = life_view.action_phrase(
                    str(action), detail.get("тема"), self._language
                )
                if detail.get("статус") == "started":
                    label += f" · {self._t('сейчас')}"
                return label
        return str(node.get("label") or node_id)

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

    async def _on_agent_web_result(self, event) -> None:
        """Результат web-поиска: карточка источника, а не сырые строки."""
        self._incoming_queue.put(("__web_card__", dict(event.data or {})))

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
        elif kind == "__web_card__":
            self._render_web_card(data)
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
                display_snapshot = {
                    **snapshot,
                    "last_action": (
                        diary_view.action_label(snapshot["last_action"], self._language)
                        if snapshot.get("last_action")
                        else snapshot.get("last_action")
                    ),
                    "stuck_actions": [
                        diary_view.action_label(action, self._language)
                        for action in snapshot.get("stuck_actions") or []
                    ],
                }
                self._status_text.configure(state=tk.NORMAL)
                self._status_text.delete("1.0", tk.END)
                self._status_text.insert(
                    tk.END,
                    "\n".join(
                        format_status_lines(display_snapshot, language=self._language)
                    ),
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
                text=life_view.life_state_label(life_state, self._language),
                fg=colors.get(str(life_state), theme.MUTED),
            )
        except Exception:
            pass

    # ============================================================
    # Экран «Сейчас»: рендер из снимка жизни
    # ============================================================

    def _on_access_toggle(self, key: str) -> None:
        """Переключатель не меняет Core сам: решение исполняет поток агента."""
        var = self._access_vars.get(key)
        if var is None:
            return
        state = "on" if bool(var.get()) else "off"
        try:
            self.bus.publish_sync(
                Events.USER_COMMAND,
                {"command": f"access {key} {state}"},
                source="access",
            )
        except Exception as exc:
            logger.debug("[MainWindow] access toggle: %s", exc)

    def _build_access_switch(self, parent, key: str, var) -> None:
        """Переключатель доступа в палитре оболочки — без нативного чекбокса."""
        canvas = tk.Canvas(
            parent,
            width=40,
            height=20,
            bg=parent.cget("bg"),
            highlightthickness=0,
            cursor="hand2",
        )
        canvas.pack(side=tk.LEFT)
        self._access_switches[key] = canvas
        canvas.bind(
            "<Button-1>", lambda _event, name=key: self._toggle_access_var(name)
        )
        # Внешнее изменение переменной (командой агенту) тоже перерисовывает.
        var.trace_add("write", lambda *_args, name=key: self._draw_access_switch(name))
        self._draw_access_switch(key)

    def _toggle_access_var(self, key: str) -> None:
        """Клик меняет переменную; решение об доступе исполняет поток агента."""
        var = self._access_vars.get(key)
        if var is None:
            return
        var.set(not bool(var.get()))
        self._on_access_toggle(key)

    def _draw_access_switch(self, key: str) -> None:
        canvas = self._access_switches.get(key)
        var = self._access_vars.get(key)
        if canvas is None or var is None:
            return
        on = bool(var.get())
        canvas.delete("all")
        track = theme.AMBER if on else theme.BORDER
        canvas.create_oval(2, 3, 38, 17, fill=track, outline=track)
        knob_x = 28 if on else 12
        canvas.create_oval(
            knob_x - 5,
            5,
            knob_x + 5,
            15,
            fill=theme.BG_DEEP if on else theme.DIMMED,
            outline="",
        )
        status = self._access_status_labels.get(key)
        if status is not None:
            status.configure(
                text=self._t("включено" if on else "выключено"),
                fg=theme.CYAN if on else theme.MUTED,
            )

    def _refresh_access_switches(self, snapshot: Dict[str, Any]) -> None:
        """Показывать реальное состояние, даже если его изменили командой."""
        access = snapshot.get("access") or {}
        for key, var in self._access_vars.items():
            item = access.get(key)
            if not isinstance(item, dict):
                # Даже неизвестное ядру состояние переводится вместе со страницей.
                self._draw_access_switch(key)
                continue
            actual = bool(item.get("enabled"))
            if bool(var.get()) != actual:
                var.set(actual)
            else:
                # Подпись состояния также обновляется при смене языка.
                self._draw_access_switch(key)

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
            self._now_headline.configure(
                text=life_view.now_headline(snap, self._language)
            )
            if self._now_sub is not None:
                self._now_sub.configure(
                    text=life_view.body_summary(snap, self._language)
                )
            self._now_activity.configure(
                text=self._rows_text(life_view.activity_rows(snap, self._language))
            )
            self._now_choice.configure(
                text=self._rows_text(life_view.choice_rows(snap, self._language))
            )
            if self._now_influence is not None:
                influences = life_view.influence_rows(snap, self._language)
                self._now_influence.configure(
                    text="   ·   ".join(
                        f"{label}: {value}" for label, value in influences
                    )
                )
            if self._now_body is not None:
                self._now_body.configure(
                    text=self._rows_text(life_view.body_rows(snap, self._language))
                )
            self._apply_now_emotions(snap)
            self._apply_diary_data(snap)
            self._apply_activity_data(snap)
            self._refresh_access_switches(snap)
            if self._access_card is not None:
                self._access_card.configure(
                    text=self._rows_text(life_view.access_rows(snap, self._language))
                )
            if self._effector_card is not None:
                text = self._rows_text(life_view.effector_rows(snap, self._language))
                note = life_view.pending_effector_note(snap, self._language)
                if note:
                    text = f"{text}\n{note}"
                self._effector_card.configure(text=text)
            life_state = (snap.get("life") or {}).get("state")
            if life_state:
                self._set_state_pill(life_state)
        except Exception as exc:
            logger.debug("[MainWindow] life data: %s", exc)

    def _apply_now_emotions(self, snapshot: Dict[str, Any]) -> None:
        """Показать все уровни палитры; пересоздавать строки только при смене схемы."""
        inner = self._now_emotion_inner
        canvas = self._now_emotion_canvas
        if inner is None or canvas is None:
            return
        rows = life_view.emotion_rows(snapshot, self._language)
        signature = (self._language, tuple(name for name, _label, _level in rows))
        if signature != self._now_emotion_signature:
            for child in inner.winfo_children():
                child.destroy()
            self._now_emotion_labels = {}
            self._now_emotion_values = {}
            self._now_emotion_bars = {}
            self._now_emotion_empty = None
            if not rows:
                self._now_emotion_empty = tk.Label(
                    inner,
                    text=self._t("Нет данных"),
                    font=self._ui_font,
                    bg=theme.SURFACE,
                    fg=theme.MUTED,
                    anchor="w",
                )
                self._now_emotion_empty.pack(
                    fill=tk.X, padx=theme.SPACING["sm"], pady=theme.SPACING["sm"]
                )
            else:
                for index, (name, label, level) in enumerate(rows):
                    row = tk.Frame(inner, bg=theme.SURFACE)
                    row.grid(
                        row=index // 2,
                        column=index % 2,
                        sticky="ew",
                        padx=(0, theme.SPACING["sm"]),
                        pady=2,
                    )
                    row.columnconfigure(0, weight=1)
                    name_label = tk.Label(
                        row,
                        text=label,
                        font=self._now_emotion_font,
                        bg=theme.SURFACE,
                        fg=theme.MUTED,
                        anchor="w",
                    )
                    name_label.grid(row=0, column=0, sticky="ew")
                    value_label = tk.Label(
                        row,
                        text=f"{level:.2f}",
                        width=4,
                        font=self._now_mono_small_font,
                        bg=theme.SURFACE,
                        fg=theme.TEXT,
                        anchor="e",
                    )
                    value_label.grid(row=0, column=1, sticky="e")
                    bar = tk.Canvas(
                        row,
                        height=3,
                        bg=theme.BORDER,
                        highlightthickness=0,
                        bd=0,
                    )
                    bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
                    fill = bar.create_rectangle(
                        0, 0, 0, 3, fill=theme.CYAN, outline=""
                    )

                    def resize_bar(event, item=fill, emotion_name=name):
                        value = self._now_emotion_values[emotion_name]
                        raw = value.cget("text")
                        event.widget.coords(item, 0, 0, event.width * float(raw), 3)

                    bar.bind("<Configure>", resize_bar)
                    self._now_emotion_labels[name] = name_label
                    self._now_emotion_values[name] = value_label
                    self._now_emotion_bars[name] = (bar, fill)
                inner.columnconfigure(0, weight=1, uniform="now-emotions")
                inner.columnconfigure(1, weight=1, uniform="now-emotions")
                self._bind_now_emotion_wheel(inner)
            self._now_emotion_signature = signature
            canvas.yview_moveto(0.0)

        dominant = (snapshot.get("emotions") or {}).get("dominant") or {}
        dominant_name = dominant.get("emotion") if isinstance(dominant, dict) else None
        if self._now_dominant is not None:
            self._now_dominant.configure(
                text=life_view.dominant_emotion(snapshot, self._language)
            )
        for name, _label, level in rows:
            value_label = self._now_emotion_values.get(name)
            bar, fill = self._now_emotion_bars.get(name, (None, None))
            if value_label is None or bar is None:
                continue
            value_label.configure(text=f"{level:.2f}")
            color = theme.AMBER if name == dominant_name else theme.CYAN
            bar.itemconfigure(fill, fill=color)
            bar.coords(fill, 0, 0, max(1, bar.winfo_width()) * level, 3)

    def _scroll_now_emotions(self, event):
        if self._now_emotion_canvas is None:
            return "break"
        delta = -1 if getattr(event, "num", None) == 4 else 1
        if hasattr(event, "delta"):
            delta = -1 if event.delta > 0 else 1
        self._now_emotion_canvas.yview_scroll(delta, "units")
        return "break"

    def _bind_now_emotion_wheel(self, widget) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(sequence, self._scroll_now_emotions)
        for child in widget.winfo_children():
            self._bind_now_emotion_wheel(child)

    def _refresh_pause_button(self, paused: bool) -> None:
        if self._pause_button is None:
            return
        try:
            self._pause_button.configure(
                text=self._t("▶ Продолжить" if paused else "⏸ Пауза")
            )
        except Exception:
            pass

    def _refresh_speed_buttons(self, mode: str) -> None:
        for key, button in self._speed_buttons.items():
            try:
                active = key == mode
                button.configure(
                    bg=theme.GLOW_CYAN if active else theme.BG_CENTER,
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
        self._now_body_font = font.Font(family=theme.font_family(), size=9)
        self._now_emotion_font = font.Font(family=theme.font_family(), size=8)
        self._now_mono_small_font = font.Font(family=theme.mono_family(), size=8)
        self._headline_font = font.Font(
            family=theme.font_family(), size=20, weight="bold"
        )
        self._brand_font = font.Font(family=theme.font_family(), size=16, weight="bold")

        # --- Шапка: имя и состояние жизни ---
        header = tk.Frame(root, bg=theme.BG_DEEP)
        header.pack(fill=tk.X)
        self._display_name_label = tk.Label(
            header,
            text=self.agent_name,
            font=self._brand_font,
            bg=theme.BG_DEEP,
            fg=theme.TEXT,
            anchor="w",
        )
        self._display_name_label.pack(
            side=tk.LEFT, padx=theme.SPACING["md"], pady=theme.SPACING["sm"]
        )
        self._state_pill = tk.Label(
            header,
            text="жив",
            font=self._ui_font,
            bg=theme.SURFACE,
            fg=theme.CYAN,
            padx=10,
            pady=3,
        )
        self._state_pill.pack(side=tk.LEFT)
        self._language_var = tk.StringVar(value=i18n.LANGUAGES[self._language])
        self._language_menu = tk.OptionMenu(
            header,
            self._language_var,
            *i18n.LANGUAGES.values(),
            command=self._set_language,
        )
        self._language_menu.configure(
            bg=theme.SURFACE,
            fg=theme.TEXT,
            activebackground=theme.GLOW_CYAN,
            activeforeground=theme.TEXT,
            highlightthickness=0,
            bd=0,
            font=self._card_title_font,
        )
        self._language_menu.pack(
            side=tk.RIGHT, padx=theme.SPACING["sm"], pady=theme.SPACING["sm"]
        )
        tk.Label(
            header,
            text=self._t("Язык"),
            font=self._card_title_font,
            bg=theme.BG_DEEP,
            fg=theme.MUTED,
        ).pack(side=tk.RIGHT)

        # Сначала резервируем нижнюю панель: иначе высокая страница
        # «Доступы» вытесняет её за пределы окна через expand у body.
        self._build_controls(root, self._mono_font)

        body = tk.Frame(root, bg=theme.BG_DEEP)
        body.pack(fill=tk.BOTH, expand=True)

        # --- Боковая навигация: жизнь отдельно от системных действий. ---
        sidebar = tk.Frame(body, bg=theme.SIDEBAR, width=214)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        tk.Label(
            sidebar,
            text="ЯДРО",
            font=self._brand_font,
            bg=theme.SIDEBAR,
            fg=theme.TEXT,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(theme.SPACING["lg"], 0))
        tk.Label(
            sidebar,
            text="живая карта",
            font=self._card_title_font,
            bg=theme.SIDEBAR,
            fg=theme.MUTED,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(0, theme.SPACING["lg"]))

        def nav_section(text):
            tk.Label(
                sidebar,
                text=text,
                font=self._card_title_font,
                bg=theme.SIDEBAR,
                fg=theme.DIMMED,
                anchor="w",
            ).pack(
                fill=tk.X,
                padx=theme.SPACING["md"],
                pady=(theme.SPACING["sm"], theme.SPACING["xs"]),
            )

        self._nav_buttons = {}
        nav_section("ЖИЗНЬ")
        navigation = (
            ("now", "◉", "Сейчас"),
            ("graph", "✦", "Карта жизни"),
            ("diary", "◌", "Дневник"),
            ("activities", "◇", "Занятия"),
        )
        for key, marker, label in navigation:
            button = tk.Button(
                sidebar,
                text=f"  {marker}  {label}",
                font=self._ui_font,
                anchor="w",
                command=lambda k=key: self._show_page(k),
                bg=theme.SIDEBAR,
                fg=theme.MUTED,
                activebackground=theme.SURFACE,
                activeforeground=theme.TEXT,
                relief=tk.FLAT,
                bd=0,
                padx=theme.SPACING["sm"],
                pady=9,
            )
            button.pack(fill=tk.X, padx=theme.SPACING["sm"])
            self._nav_buttons[key] = button

        nav_section("СИСТЕМА")
        for key, marker, label in (
            ("access", "▣", "Доступы"),
            ("dialog", "◫", "Диалог"),
        ):
            button = tk.Button(
                sidebar,
                text=f"  {marker}  {label}",
                font=self._ui_font,
                anchor="w",
                command=lambda k=key: self._show_page(k),
                bg=theme.SIDEBAR,
                fg=theme.MUTED,
                activebackground=theme.SURFACE,
                activeforeground=theme.TEXT,
                relief=tk.FLAT,
                bd=0,
                padx=theme.SPACING["sm"],
                pady=9,
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
        self._translate_static_widgets()
        self._refresh_pause_button(bool(self._status_snapshot.get("paused")))
        self._graph_detail.configure(
            text=self._t(
                "Выберите узел на карте — покажу только то,\n"
                "что ядро действительно записало."
            )
        )
        self._diary_detail.configure(text=self._t("Выберите запись слева."))
        self._activity_detail.configure(text=self._t("Выберите запись слева."))

    # ------------------------------------------------------------------
    # Страницы каркаса
    # ------------------------------------------------------------------

    def _make_card(
        self, parent, title: str, *, side=None, expand=False, wraplength=680
    ):
        """Карточка: тонкая рамка, приглушённый заголовок, светлое тело."""
        frame = tk.Frame(
            parent,
            bg=theme.SURFACE,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        options = {
            "fill": tk.BOTH if expand else tk.X,
            "padx": theme.SPACING["md"],
            "pady": (0, theme.SPACING["sm"]),
        }
        if side is not None:
            options["side"] = side
            options["padx"] = (0, theme.SPACING["sm"])
            options["expand"] = expand
        frame.pack(**options)
        tk.Label(
            frame,
            text=title,
            font=self._card_title_font,
            bg=theme.SURFACE,
            fg=theme.MUTED,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(theme.SPACING["sm"], 2))
        body = tk.Label(
            frame,
            text="",
            font=self._card_body_font,
            bg=theme.SURFACE,
            fg=theme.TEXT,
            anchor="w",
            justify=tk.LEFT,
            wraplength=wraplength,
        )
        body.pack(fill=tk.X, padx=theme.SPACING["md"], pady=(0, theme.SPACING["sm"]))
        return body

    def _now_card(self, parent, title: str, accent: str):
        """Общий контур карточки «Сейчас»: акцентная полоса и тонкая рамка."""
        frame = tk.Frame(
            parent,
            bg=theme.SURFACE,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        header = tk.Frame(frame, bg=theme.SURFACE)
        header.pack(fill=tk.X)
        tk.Frame(header, width=3, bg=accent).pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(
            header,
            text=title,
            font=self._card_title_font,
            bg=theme.SURFACE,
            fg=accent,
            anchor="w",
        ).pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
            padx=(theme.SPACING["sm"], 0),
            pady=theme.SPACING["xs"],
        )
        return frame, header

    @staticmethod
    def _now_card_text(parent, text_font, wraplength: int):
        body = tk.Label(
            parent,
            text="",
            font=text_font,
            bg=theme.SURFACE,
            fg=theme.TEXT,
            anchor="nw",
            justify=tk.LEFT,
            wraplength=wraplength,
        )
        body.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["md"],
            pady=(1, theme.SPACING["xs"]),
        )
        return body

    def _resize_now_page(self, event) -> None:
        """Пересчитать переносы, не меняя компоновку остальных страниц."""
        width = max(320, int(event.width))
        column = max(220, (width - 36) // 2)
        for label in (self._now_activity, self._now_choice, self._now_body):
            if label is not None:
                label.configure(wraplength=column - 34)
        if self._now_influence is not None:
            self._now_influence.configure(wraplength=width - 64)
        for label in (self._now_headline, self._now_sub):
            if label is not None:
                label.configure(wraplength=width - 28)

    def _build_page_now(self, parent):
        """Киберпанк-обсерватория: занятие, палитра, выбор, тело и влияния."""
        page = tk.Frame(parent, bg=theme.BG_DEEP)
        tk.Label(
            page,
            text="СНИМКИ СОСТОЯНИЯ · СОБЫТИЯ ЯДРА",
            font=self._card_title_font,
            bg=theme.BG_DEEP,
            fg=theme.CYAN,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(theme.SPACING["sm"], 0))
        self._now_headline = tk.Label(
            page,
            text="…",
            font=self._headline_font,
            bg=theme.BG_DEEP,
            fg=theme.AMBER,
            anchor="w",
            wraplength=760,
            justify=tk.LEFT,
        )
        self._now_headline.pack(fill=tk.X, padx=theme.SPACING["md"])
        self._now_sub = tk.Label(
            page,
            text="",
            font=self._ui_font,
            bg=theme.BG_DEEP,
            fg=theme.MUTED,
            anchor="w",
            justify=tk.LEFT,
            wraplength=760,
        )
        self._now_sub.pack(
            fill=tk.X, padx=theme.SPACING["md"], pady=(2, theme.SPACING["sm"])
        )

        cards = tk.Frame(page, bg=theme.BG_DEEP)
        cards.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["md"],
            pady=(0, theme.SPACING["sm"]),
        )
        cards.columnconfigure(0, weight=1, uniform="now-columns")
        cards.columnconfigure(1, weight=1, uniform="now-columns")
        cards.rowconfigure(0, weight=4)
        cards.rowconfigure(1, weight=4)
        cards.rowconfigure(2, weight=2)

        activity_card, _header = self._now_card(cards, "ЧЕМ ЗАНЯТО", theme.AMBER)
        activity_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 4))
        self._now_activity = self._now_card_text(activity_card, self._ui_font, 360)

        emotions_card, emotions_header = self._now_card(
            cards, "ЭМОЦИИ", theme.VIOLET
        )
        emotions_card.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 4))
        self._now_dominant = tk.Label(
            emotions_header,
            text="",
            font=self._now_emotion_font,
            bg=theme.SURFACE,
            fg=theme.TEXT,
            anchor="e",
        )
        self._now_dominant.pack(side=tk.RIGHT, padx=theme.SPACING["sm"])
        viewport = tk.Frame(emotions_card, bg=theme.SURFACE)
        viewport.pack(
            fill=tk.BOTH,
            expand=True,
            padx=(theme.SPACING["sm"], theme.SPACING["xs"]),
            pady=(0, theme.SPACING["sm"]),
        )
        self._now_emotion_canvas = tk.Canvas(
            viewport,
            height=60,
            bg=theme.SURFACE,
            highlightthickness=0,
            bd=0,
        )
        emotion_scroll = tk.Scrollbar(
            viewport,
            orient=tk.VERTICAL,
            command=self._now_emotion_canvas.yview,
            bg=theme.SURFACE,
            troughcolor=theme.BG_CENTER,
            activebackground=theme.VIOLET,
            highlightthickness=0,
            bd=0,
        )
        self._now_emotion_canvas.configure(yscrollcommand=emotion_scroll.set)
        emotion_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._now_emotion_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._now_emotion_inner = tk.Frame(
            self._now_emotion_canvas, bg=theme.SURFACE
        )
        emotion_window = self._now_emotion_canvas.create_window(
            (0, 0), window=self._now_emotion_inner, anchor="nw"
        )
        self._now_emotion_inner.bind(
            "<Configure>",
            lambda _event: self._now_emotion_canvas.configure(
                scrollregion=self._now_emotion_canvas.bbox("all")
            ),
        )
        self._now_emotion_canvas.bind(
            "<Configure>",
            lambda event: self._now_emotion_canvas.itemconfigure(
                emotion_window, width=event.width
            ),
        )
        self._bind_now_emotion_wheel(self._now_emotion_canvas)

        choice_card, _header = self._now_card(
            cards, "ПОЧЕМУ ИМЕННО ЭТО", theme.CYAN
        )
        choice_card.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=4)
        self._now_choice = self._now_card_text(choice_card, self._now_body_font, 360)

        body_card, _header = self._now_card(cards, "ТЕЛО", theme.GREEN)
        body_card.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=4)
        self._now_body = self._now_card_text(body_card, self._now_body_font, 360)

        influence_card, _header = self._now_card(
            cards, "ЧТО ВЛИЯЕТ НА ВЫБОР", theme.VIOLET
        )
        influence_card.grid(
            row=2, column=0, columnspan=2, sticky="nsew", pady=(4, 0)
        )
        self._now_influence = self._now_card_text(
            influence_card, self._now_body_font, 760
        )
        page.bind("<Configure>", self._resize_now_page)
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

    # Ключи из diary_view.ACTION_COLOR_KEYS → цвета палитры.
    _DIARY_COLORS = {
        "cyan": theme.CYAN,
        "violet": theme.VIOLET,
        "green": theme.GREEN,
        "amber": theme.AMBER,
        "grey": theme.GREY,
    }

    def _build_page_graph(self, parent):
        """Карта жизни: неоновые орбиты, фильтры и реальные детали узлов."""
        page = tk.Frame(parent, bg=theme.BG_DEEP)
        tk.Label(
            page,
            text="СНИМКИ СОСТОЯНИЯ · СОБЫТИЯ ЯДРА",
            font=self._card_title_font,
            bg=theme.BG_DEEP,
            fg=theme.CYAN,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(theme.SPACING["sm"], 0))
        tk.Label(
            page,
            text="Карта жизни",
            font=self._headline_font,
            bg=theme.BG_DEEP,
            fg=theme.AMBER,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"])
        tk.Label(
            page,
            text="узлы — то, что ядро знает, хочет и пережило; связи — только записанные",
            font=self._ui_font,
            bg=theme.BG_DEEP,
            fg=theme.MUTED,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(2, theme.SPACING["sm"]))

        filters = tk.Frame(
            page,
            bg=theme.SURFACE,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        filters.pack(fill=tk.X, padx=theme.SPACING["md"], pady=(0, theme.SPACING["sm"]))
        all_chip = tk.Button(
            filters,
            text="все",
            font=self._card_title_font,
            command=self._on_graph_filter_all,
            bg=theme.AMBER,
            fg=theme.BG_DEEP,
            activebackground=theme.AMBER,
            activeforeground=theme.BG_DEEP,
            highlightbackground=theme.AMBER,
            highlightthickness=1,
            relief=tk.FLAT,
            bd=0,
            padx=10,
            pady=4,
        )
        all_chip.pack(side=tk.LEFT, padx=theme.SPACING["xs"], pady=theme.SPACING["xs"])
        self._graph_filter_buttons = {"all": all_chip}
        for kind in ("concept", "intention", "value", "activity", "forgotten"):
            chip = tk.Button(
                filters,
                text=self._NODE_TYPE_LABELS[kind],
                font=self._card_title_font,
                command=lambda k=kind: self._toggle_graph_filter(k),
                bg=theme.SURFACE,
                fg=theme.MUTED,
                activebackground=theme.BG_CENTER,
                activeforeground=theme.node_color(kind),
                highlightbackground=theme.BORDER,
                highlightthickness=1,
                relief=tk.FLAT,
                bd=0,
                padx=9,
                pady=4,
            )
            chip.pack(side=tk.LEFT, padx=(0, theme.SPACING["xs"]), pady=theme.SPACING["xs"])
            self._graph_filter_buttons[kind] = chip
        self._graph_zoom_label = tk.Label(
            filters,
            text="100%",
            font=self._now_mono_small_font,
            bg=theme.SURFACE,
            fg=theme.DIMMED,
            anchor="e",
        )
        self._graph_zoom_label.pack(side=tk.RIGHT, padx=theme.SPACING["sm"])

        body = tk.Frame(page, bg=theme.BG_DEEP)
        body.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["md"],
            pady=(0, theme.SPACING["sm"]),
        )
        left = tk.Frame(body, bg=theme.BG_DEEP)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._graph_canvas = tk.Canvas(
            left,
            bg=theme.GRAPH_BG,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            bd=0,
        )
        self._graph_canvas.pack(fill=tk.BOTH, expand=True)
        self._graph_canvas.bind("<Configure>", self._on_graph_resize)
        self._graph_canvas.bind("<ButtonPress-1>", self._on_graph_press)
        self._graph_canvas.bind("<B1-Motion>", self._on_graph_motion)
        self._graph_canvas.bind("<ButtonRelease-1>", self._on_graph_release)
        self._graph_canvas.bind("<MouseWheel>", self._on_graph_wheel)

        help_label = tk.Label(
            left,
            text="колёсико — масштаб · перетаскивание — панорама · клик — детали",
            font=self._card_title_font,
            bg=theme.BG_DEEP,
            fg=theme.DIMMED,
            anchor="w",
            justify=tk.LEFT,
            wraplength=520,
        )
        help_label.pack(fill=tk.X, pady=(theme.SPACING["xs"], 0))
        left.bind(
            "<Configure>",
            lambda event: help_label.configure(wraplength=max(180, event.width)),
        )
        legend = tk.Frame(
            left,
            bg=theme.BG_CENTER,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        legend.pack(fill=tk.X, pady=(theme.SPACING["xs"], 0))
        legend.columnconfigure(0, weight=1, uniform="graph-legend")
        legend.columnconfigure(1, weight=1, uniform="graph-legend")
        for index, kind in enumerate(
            ("concept", "intention", "value", "activity", "forgotten")
        ):
            item = tk.Frame(legend, bg=theme.BG_CENTER)
            item.grid(
                row=index // 2,
                column=index % 2,
                sticky="w",
                padx=theme.SPACING["sm"],
                pady=2,
            )
            swatch = tk.Canvas(
                item,
                width=18,
                height=18,
                bg=theme.BG_CENTER,
                highlightthickness=0,
            )
            swatch.pack(side=tk.LEFT)
            self._draw_node_shape(swatch, 9, 9, 5, kind)
            tk.Label(
                item,
                text=self._NODE_TYPE_LABELS[kind],
                font=self._now_body_font,
                bg=theme.BG_CENTER,
                fg=theme.MUTED,
            ).pack(side=tk.LEFT, padx=(4, 0))

        detail, _detail_header = self._now_card(body, "ПОДРОБНОСТИ", theme.CYAN)
        detail.configure(width=300)
        detail.pack(
            side=tk.RIGHT, fill=tk.Y, padx=(theme.SPACING["md"], 0), before=left
        )
        detail.pack_propagate(False)
        self._graph_detail = tk.Label(
            detail,
            text="Выберите узел на карте — покажу только то,\n"
            "что ядро действительно записало.",
            font=self._ui_font,
            bg=theme.SURFACE,
            fg=theme.TEXT,
            anchor="nw",
            justify=tk.LEFT,
            wraplength=264,
        )
        self._graph_detail.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["md"],
            pady=(theme.SPACING["xs"], theme.SPACING["sm"]),
        )
        tk.Frame(detail, height=1, bg=theme.BORDER).pack(fill=tk.X)
        self._graph_counter = tk.Label(
            detail,
            text="узлов: 0 · связей: 0",
            font=self._now_mono_small_font,
            bg=theme.SURFACE,
            fg=theme.CYAN,
            anchor="w",
            justify=tk.LEFT,
            wraplength=264,
        )
        self._graph_counter.pack(
            fill=tk.X, padx=theme.SPACING["md"], pady=theme.SPACING["sm"]
        )
        self._refresh_graph_chips()
        return page

    def _draw_graph_background(self, width: int, height: int) -> None:
        """Тихая техническая сетка и орбиты — только фон, не данные Core."""
        canvas = self._graph_canvas
        for x in range(0, width, 32):
            canvas.create_line(
                x, 0, x, height, fill=theme.GRID, tags=("graph-grid",)
            )
        for y in range(0, height, 32):
            canvas.create_line(
                0, y, width, y, fill=theme.GRID, tags=("graph-grid",)
            )
        center_x, center_y = width / 2.0, height / 2.0
        size = min(width, height)
        for ratio, color in (
            (0.18, theme.ORBIT),
            (0.32, theme.ORBIT),
            (0.46, theme.ORBIT_VIOLET),
        ):
            radius = size * ratio
            canvas.create_oval(
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
                outline=color,
                dash=(2, 7),
                tags=("graph-orbits",),
            )
        canvas.create_rectangle(
            10, 9, 144, 31, fill=theme.GRAPH_BG, outline="", tags=("graph-grid",)
        )
        canvas.create_text(
            16,
            15,
            text=self._t("Карта жизни").upper(),
            font=self._card_title_font,
            fill=theme.CYAN,
            anchor="nw",
            tags=("graph-grid",),
        )

    def _draw_node_shape(self, canvas, x, y, radius, kind, *, tags=()):
        """Нарисовать узел формы и цвета, закреплённых за его типом."""
        color = theme.node_color(kind)
        shape = theme.node_shape(kind)
        if shape == "diamond":
            canvas.create_polygon(
                x,
                y - radius,
                x + radius,
                y,
                x,
                y + radius,
                x - radius,
                y,
                fill=color,
                outline=color,
                tags=tags,
            )
        elif shape == "hexagon":
            points = []
            for index in range(6):
                angle = math.pi / 3.0 * index - math.pi / 6.0
                points.extend(
                    (x + radius * math.cos(angle), y + radius * math.sin(angle))
                )
            canvas.create_polygon(*points, fill=color, outline=color, tags=tags)
        elif shape == "ring":
            canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=theme.BG_CENTER,
                outline=color,
                width=3,
                tags=tags,
            )
        elif shape == "outline":
            canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill="",
                outline=color,
                width=1,
                tags=tags,
            )
        else:
            canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=color,
                outline=color,
                tags=tags,
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

    def _on_graph_press(self, event) -> None:
        """Начало жеста: запоминаем точку, клик и панорама расходятся позже."""
        self._graph_pan = {
            "moved": False,
            "start": (event.x, event.y),
            "origin": tuple(self._graph_offset),
        }

    def _on_graph_motion(self, event) -> None:
        start_x, start_y = self._graph_pan["start"]
        if abs(event.x - start_x) + abs(event.y - start_y) < 4:
            return
        self._graph_pan["moved"] = True
        origin_x, origin_y = self._graph_pan["origin"]
        self._graph_offset = (
            origin_x + event.x - start_x,
            origin_y + event.y - start_y,
        )
        self._render_graph()

    def _on_graph_release(self, event) -> None:
        """Сдвиг больше пары пикселей — панорама, без сдвига — выбор узла."""
        if self._graph_pan["moved"]:
            return
        self._select_graph_at(event)

    def _select_graph_at(self, event) -> None:
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

    def _on_graph_wheel(self, event) -> None:
        """Масштаб вокруг центра; границы держим, чтобы карта не потерялась."""
        factor = 1.1 if event.delta > 0 else 1 / 1.1
        self._graph_zoom = max(0.35, min(3.0, self._graph_zoom * factor))
        self._render_graph()

    def _toggle_graph_filter(self, kind: str) -> None:
        """Фильтр — свойство вида, а не данных: Core не трогаем."""
        active = set(self._graph_filter or ())
        if kind in active:
            active.discard(kind)
        else:
            active.add(kind)
        self._graph_filter = active or None
        self._refresh_graph_view()

    def _on_graph_filter_all(self) -> None:
        self._graph_filter = None
        self._refresh_graph_view()

    def _refresh_graph_view(self) -> None:
        self._graph_zoom = 1.0
        self._graph_offset = (0.0, 0.0)
        self._refresh_graph_chips()
        self._update_graph_counter()
        self._render_graph()

    def _refresh_graph_chips(self) -> None:
        for kind, chip in self._graph_filter_buttons.items():
            if kind == "all":
                active = self._graph_filter is None
                color = theme.CYAN
            else:
                active = self._graph_filter is not None and kind in self._graph_filter
                color = theme.node_color(kind)
            try:
                all_active = kind == "all" and active
                chip.configure(
                    bg=(
                        theme.AMBER
                        if all_active
                        else theme.BG_CENTER if active else theme.SURFACE
                    ),
                    fg=(
                        theme.BG_DEEP
                        if all_active
                        else color if active else theme.MUTED
                    ),
                    highlightbackground=(
                        theme.AMBER if all_active else color if active else theme.BORDER
                    ),
                )
            except Exception:
                pass

    @staticmethod
    def _distance_to_segment(point_x, point_y, start, end) -> float:
        """Расстояние от точки до отрезка — чтобы тонкую связь было легко поймать."""
        start_x, start_y = start
        end_x, end_y = end
        delta_x, delta_y = end_x - start_x, end_y - start_y
        length_sq = delta_x * delta_x + delta_y * delta_y
        if length_sq <= 0:
            return math.hypot(point_x - start_x, point_y - start_y)
        t = max(
            0.0,
            min(
                1.0,
                ((point_x - start_x) * delta_x + (point_y - start_y) * delta_y)
                / length_sq,
            ),
        )
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
            f"{self._graph_node_label(source)} → {self._graph_node_label(target)}",
            self._t("связь"),
            "",
            f"{self._t('тип')}: {self._t(edge.get('label') or kind or '—')}",
            f"{self._t('основание')}: "
            f"{self._t(self._EDGE_BASIS.get(kind, 'записано в Core'))}",
        ]
        if kind == "association":
            lines.append(
                f"{self._t('вес связи')}: {float(edge.get('weight') or 0.0):.2f}"
            )
        self._graph_detail.configure(text="\n".join(lines))

    def _show_node_detail(self, node: Dict[str, Any]) -> None:
        """Показать карточку выбранного узла — только записанные поля."""
        if self._graph_detail is None:
            return
        kind = str(node.get("kind") or "")
        lines = [
            self._graph_node_label(node),
            self._t(self._NODE_TYPE_LABELS.get(kind, "узел")),
            "",
        ]
        detail = node.get("detail") or {}
        for key, value in detail.items():
            if isinstance(value, bool):
                value = self._t("да") if value else self._t("нет")
            elif value is None or value == "":
                value = "—"
            elif key in {"действие", "статус"}:
                value = i18n.value_label(value, self._language)
            lines.append(f"{self._t(key)}: {value}")
        if not detail:
            lines.append(self._t("Подробностей ядро пока не записало."))
        elif kind == "concept":
            lines.extend(["", self._t("уверенность — мера доверия модели, а не факт.")])
        self._graph_detail.configure(text="\n".join(lines))

    def _visible_nodes(self) -> List[Dict[str, Any]]:
        """Узлы, видимые при текущем фильтре; без фильтра — все."""
        nodes = self._graph_data.get("nodes") or []
        if self._graph_filter is None:
            return list(nodes)
        return [node for node in nodes if str(node.get("kind")) in self._graph_filter]

    def _render_graph(self) -> None:
        """Перерисовать карту. Ошибка рисунка не должна рушить окно."""
        canvas = self._graph_canvas
        if canvas is None:
            return
        try:
            zoom = self._graph_zoom
            if self._graph_zoom_label is not None:
                self._graph_zoom_label.configure(text=f"{round(zoom * 100)}%")
            width = max(int(canvas.winfo_width()), 1)
            height = max(int(canvas.winfo_height()), 1)
            canvas.delete("all")
            self._graph_tag_nodes = {}
            if width < 80 or height < 80:
                return
            self._draw_graph_background(width, height)

            nodes = self._visible_nodes()
            if not nodes:
                canvas.create_text(
                    width / 2,
                    height / 2,
                    text=self._t(
                        "Пока нечего показать: ядро ещё не накопило\n"
                        "знаний, намерений и занятий для карты."
                    ),
                    fill=theme.MUTED,
                    font=self._ui_font,
                    width=max(160, width - 80),
                    justify=tk.CENTER,
                )
                return

            positions = graph_view.layout_nodes(nodes, width, height)
            offset_x, offset_y = self._graph_offset
            center_x, center_y = width / 2.0, height / 2.0
            # Масштаб и панорама — вокруг центра; сами координаты раскладки
            # не меняются, поэтому «назад» всегда возвращает прежнюю картинку.
            shifted = {
                node_id: (
                    center_x + (x - center_x) * zoom + offset_x,
                    center_y + (y - center_y) * zoom + offset_y,
                )
                for node_id, (x, y) in positions.items()
            }
            self._graph_positions = shifted

            visible_ids = {str(node.get("id")) for node in nodes}
            for edge in self._graph_data.get("edges") or []:
                source = edge.get("source")
                target = edge.get("target")
                if source not in visible_ids or target not in visible_ids:
                    continue
                start = shifted.get(source)
                end = shifted.get(target)
                if not start or not end:
                    continue
                active = self._graph_selected in {source, target}
                canvas.create_line(
                    start[0],
                    start[1],
                    end[0],
                    end[1],
                    fill=theme.CYAN if active else theme.EDGE,
                    width=2 if active else 1,
                    tags=("edge", "selected-edge" if active else "edge-muted"),
                )

            label_limit = max(14, min(graph_view.MAX_LABEL_CHARS, width // 18))
            label_nodes = [
                dict(
                    node,
                    label=graph_view.short_label(
                        self._graph_node_label(node), limit=label_limit
                    ),
                )
                for node in nodes
            ]
            labels = graph_view.layout_labels(label_nodes, shifted, width, height)
            for index, node in enumerate(nodes):
                position = shifted.get(node.get("id"))
                if position is None:
                    continue
                x, y = position
                kind = str(node.get("kind") or "")
                weight = node.get("weight", 0.0)
                radius = graph_view.node_radius(weight, kind) * zoom
                tag = f"node-{index}"
                self._graph_tag_nodes[tag] = node
                tags = ("node", tag)
                if node.get("id") == self._graph_selected:
                    canvas.create_oval(
                        x - radius - 7,
                        y - radius - 7,
                        x + radius + 7,
                        y + radius + 7,
                        fill=theme.GLOW_CYAN,
                        outline=theme.AMBER,
                        width=2,
                        tags=tags + ("selected-node",),
                    )
                self._draw_node_shape(canvas, x, y, radius, kind, tags=tags)

            for index, node in enumerate(nodes):
                label = labels.get(node.get("id"))
                if label is None:
                    continue
                label_x, label_y, anchor = label
                kind = str(node.get("kind") or "")
                if kind in {"intention", "value", "activity"}:
                    label_color = theme.node_color(kind)
                else:
                    label_color = theme.MUTED if kind == "forgotten" else theme.TEXT
                canvas.create_text(
                    label_x,
                    label_y,
                    text=graph_view.short_label(
                        self._graph_node_label(node), limit=label_limit
                    ),
                    anchor=anchor,
                    fill=label_color,
                    font=self._now_body_font,
                    tags=("node", f"node-{index}"),
                )
        except Exception as exc:
            logger.debug("[MainWindow] graph render: %s", exc)

    def _update_graph_counter(self) -> None:
        """Счётчик узлов и связей; при фильтре — сколько показано из скольких."""
        if self._graph_counter is None:
            return
        nodes = self._graph_data.get("nodes") or []
        edges = self._graph_data.get("edges") or []
        if self._graph_filter is None:
            text = self._t("узлов: {nodes} · связей: {edges}").format(
                nodes=len(nodes), edges=len(edges)
            )
        else:
            shown = self._visible_nodes()
            labels = sorted(
                self._t(self._NODE_TYPE_LABELS.get(str(kind), str(kind)))
                for kind in self._graph_filter
            )
            text = self._t("узлов: {shown} из {total} · фильтр: {filters}").format(
                shown=len(shown), total=len(nodes), filters=" + ".join(labels)
            )
        hidden = int(self._graph_data.get("hidden_service") or 0)
        if hidden > 0:
            # Узкая колонка подробностей: счётчик скрытых записей
            # переносим на отдельную строку, иначе он обрезается.
            text += "\n" + self._t("служебных записей скрыто: {count}").format(
                count=hidden
            )
        if self._graph_data.get("truncated"):
            text += "\n" + self._t("показаны не все")
        try:
            self._graph_counter.configure(text=text)
        except Exception:
            pass

    def _apply_graph_data(self, graph: Dict[str, Any]) -> None:
        self._graph_data = dict(graph or {})
        self._update_graph_counter()
        self._render_graph()

    def _build_page_diary(self, parent):
        """Дневник: неоновый список эпизодов и честные подробности записи."""
        page = tk.Frame(parent, bg=theme.BG_DEEP)
        tk.Label(
            page,
            text="СНИМКИ СОСТОЯНИЯ · СОБЫТИЯ ЯДРА",
            font=self._card_title_font,
            bg=theme.BG_DEEP,
            fg=theme.CYAN,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(theme.SPACING["sm"], 0))
        tk.Label(
            page,
            text="Дневник",
            font=self._headline_font,
            bg=theme.BG_DEEP,
            fg=theme.AMBER,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"])
        tk.Label(
            page,
            text="только записанные события жизни, от новых к старым",
            font=self._ui_font,
            bg=theme.BG_DEEP,
            fg=theme.MUTED,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(2, theme.SPACING["sm"]))
        body = tk.Frame(page, bg=theme.BG_DEEP)
        body.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["md"],
            pady=(0, theme.SPACING["md"]),
        )

        holder, _header = self._now_card(body, "ЭПИЗОДЫ", theme.CYAN)
        holder.configure(width=348)
        holder.pack(side=tk.LEFT, fill=tk.Y)
        holder.pack_propagate(False)
        self._diary_canvas = tk.Canvas(
            holder,
            bg=theme.SURFACE,
            highlightthickness=0,
            bd=0,
        )
        scrollbar = tk.Scrollbar(
            holder,
            orient=tk.VERTICAL,
            command=self._diary_canvas.yview,
            bg=theme.SURFACE,
            troughcolor=theme.BG_CENTER,
            activebackground=theme.CYAN,
            highlightthickness=0,
            bd=0,
            width=10,
        )
        self._diary_inner = tk.Frame(self._diary_canvas, bg=theme.SURFACE)
        inner_window = self._diary_canvas.create_window(
            (0, 0), window=self._diary_inner, anchor="nw"
        )
        self._diary_inner.bind(
            "<Configure>",
            lambda _event: self._diary_canvas.configure(
                scrollregion=self._diary_canvas.bbox("all")
            ),
        )
        self._diary_canvas.bind(
            "<Configure>",
            lambda event: self._diary_canvas.itemconfigure(
                inner_window, width=event.width
            ),
        )
        self._diary_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._diary_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._diary_canvas.bind(
            "<MouseWheel>",
            lambda event: self._diary_canvas.yview_scroll(-event.delta // 120, "units"),
        )
        self._diary_detail = self._detail_panel(body, "ЭПИЗОД", accent=theme.AMBER)
        # Пустое состояние рисуется сразу: снапшоты без записей больше
        # не пересобирают список (см. защиту в _apply_diary_data).
        self._render_diary_rows()
        return page

    def _build_page_activities(self, parent):
        """Неоновый каталог черновиков и партии с записанным полем игры."""
        page = tk.Frame(parent, bg=theme.BG_DEEP)
        tk.Label(
            page,
            text="СНИМКИ СОСТОЯНИЯ · СОБЫТИЯ ЯДРА",
            font=self._card_title_font,
            bg=theme.BG_DEEP,
            fg=theme.CYAN,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(theme.SPACING["sm"], 0))
        tk.Label(
            page,
            text="Занятия",
            font=self._headline_font,
            bg=theme.BG_DEEP,
            fg=theme.AMBER,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"])
        tk.Label(
            page,
            text="работы и партии, которые Core действительно создал",
            font=self._ui_font,
            bg=theme.BG_DEEP,
            fg=theme.MUTED,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(2, theme.SPACING["sm"]))
        body = tk.Frame(page, bg=theme.BG_DEEP)
        body.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["md"],
            pady=(0, theme.SPACING["md"]),
        )

        holder, _header = self._now_card(body, "КАТАЛОГ", theme.CYAN)
        holder.configure(width=348)
        holder.pack(side=tk.LEFT, fill=tk.Y)
        holder.pack_propagate(False)
        self._activity_list = tk.Listbox(
            holder,
            width=32,
            font=self._card_body_font,
            selectmode=tk.BROWSE,
            bg=theme.BG_CENTER,
            fg=theme.TEXT,
            selectbackground=theme.SELECTION,
            selectforeground=theme.TEXT,
            selectborderwidth=0,
            disabledforeground=theme.DIMMED,
            activestyle="none",
            exportselection=False,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.AMBER,
            justify=tk.LEFT,
        )
        self._activity_list.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["sm"],
            pady=(theme.SPACING["xs"], theme.SPACING["sm"]),
        )
        self._activity_list.bind("<<ListboxSelect>>", self._on_activity_select)
        self._activity_detail = self._detail_panel(
            body, "ЗАНЯТИЕ", accent=theme.AMBER
        )

        # Поле строится только из записанного board[9]; для черновика оно скрыто.
        self._activity_board = tk.Frame(
            self._activity_detail.master, bg=theme.SURFACE
        )
        self._activity_board_cells = []
        for index in range(9):
            cell = tk.Label(
                self._activity_board,
                text="",
                font=self._headline_font,
                bg=theme.BG_CENTER,
                fg=theme.DIMMED,
                width=3,
                height=1,
                highlightbackground=theme.BORDER,
                highlightthickness=1,
            )
            cell.grid(
                row=index // 3,
                column=index % 3,
                padx=2,
                pady=2,
                ipadx=4,
                ipady=4,
            )
            self._activity_board_cells.append(cell)
        return page

    def _page_heading(self, page, title, subtitle):
        tk.Label(
            page,
            text=title,
            font=self._brand_font,
            bg=theme.BG_DEEP,
            fg=theme.TEXT,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(theme.SPACING["md"], 0))
        tk.Label(
            page,
            text=subtitle,
            font=self._ui_font,
            bg=theme.BG_DEEP,
            fg=theme.MUTED,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(0, theme.SPACING["sm"]))

    def _detail_panel(self, parent, title, *, accent=None):
        panel = tk.Frame(
            parent,
            bg=theme.SURFACE,
            width=400,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        panel.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(theme.SPACING["md"], 0)
        )
        panel.pack_propagate(False)
        if accent is None:
            tk.Label(
                panel,
                text=title,
                font=self._card_title_font,
                bg=theme.SURFACE,
                fg=theme.MUTED,
                anchor="w",
            ).pack(
                fill=tk.X,
                padx=theme.SPACING["md"],
                pady=(theme.SPACING["md"], theme.SPACING["sm"]),
            )
        else:
            header = tk.Frame(panel, bg=theme.SURFACE)
            header.pack(fill=tk.X)
            tk.Frame(header, width=3, bg=accent).pack(side=tk.LEFT, fill=tk.Y)
            tk.Label(
                header,
                text=title,
                font=self._card_title_font,
                bg=theme.SURFACE,
                fg=theme.CYAN,
                anchor="w",
            ).pack(
                side=tk.LEFT,
                fill=tk.X,
                expand=True,
                padx=(theme.SPACING["sm"], 0),
                pady=theme.SPACING["sm"],
            )
        label = tk.Label(
            panel,
            text="Выберите запись слева.",
            font=self._ui_font,
            bg=theme.SURFACE,
            fg=theme.TEXT,
            anchor="nw",
            justify=tk.LEFT,
            wraplength=500,
        )
        label.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["md"],
            pady=(theme.SPACING["xs"], theme.SPACING["md"]),
        )
        panel.bind(
            "<Configure>",
            lambda event: label.configure(
                wraplength=max(180, event.width - 2 * theme.SPACING["md"])
            ),
        )
        return label

    def _apply_diary_data(self, snapshot):
        if self._diary_inner is None:
            return
        entries = diary_view.diary_rows(snapshot)
        if (
            entries == self._diary_entries
            and self._diary_rendered_language == self._language
        ):
            # Снимок приходит дважды в секунду: без этой проверки список
            # пересобирается, моргает и сбрасывает раскрытие серий.
            return
        self._diary_rendered_language = self._language
        selected_episode = None
        if self._diary_selected is not None and 0 <= self._diary_selected < len(
            self._diary_rows_view
        ):
            selected_episode = self._diary_rows_view[self._diary_selected]["episode"]
        self._diary_entries = entries
        self._diary_groups = [
            list(group["episodes"])
            for group in diary_view.group_diary_episodes(entries)
        ]
        # Раскрытие хранится по ключу содержания серии (_diary_expanded),
        # поэтому сдвиг окна истории его не сбрасывает.
        self._render_diary_rows()
        self._restore_diary_selection(selected_episode)

    def _render_diary_rows(self) -> None:
        """Перерисовать список: свёрнутая серия — одна строка с «×N»."""
        if self._diary_inner is None or self._diary_canvas is None:
            return
        for child in list(self._diary_inner.winfo_children()):
            child.destroy()
        self._diary_row_frames = []
        self._diary_rows_view = []
        if not self._diary_entries:
            self._render_diary_empty()
        else:
            for group_index, episodes in enumerate(self._diary_groups):
                key = diary_view.group_key(episodes[0])
                collapsed = len(episodes) > 1 and key not in self._diary_expanded
                if collapsed:
                    self._append_diary_row(
                        episodes[0],
                        group_index=group_index,
                        group_count=len(episodes),
                        group_key=key,
                    )
                    continue
                for position, episode in enumerate(episodes):
                    self._append_diary_row(
                        episode,
                        group_index=group_index,
                        group_count=1,
                        group_size=len(episodes) if position == 0 else 1,
                        group_key=key,
                    )
        try:
            self._diary_canvas.configure(scrollregion=self._diary_canvas.bbox("all"))
        except Exception:
            pass

    def _render_diary_empty(self) -> None:
        """Пустой дневник — явное состояние, а не пустая серость."""
        tk.Label(
            self._diary_inner,
            text=self._t("Записей пока нет"),
            font=self._ui_font,
            bg=theme.SURFACE,
            fg=theme.MUTED,
        ).pack(pady=(theme.SPACING["lg"], theme.SPACING["xs"]))
        tk.Label(
            self._diary_inner,
            text=self._t("здесь появятся события,\nкоторые ядро записало в дневник"),
            font=self._card_title_font,
            bg=theme.SURFACE,
            fg=theme.DIMMED,
            justify=tk.CENTER,
        ).pack(pady=(0, theme.SPACING["lg"]))

    def _append_diary_row(
        self,
        episode,
        *,
        group_index: int,
        group_count: int,
        group_size: int = 1,
        group_key: Any = None,
    ) -> None:
        """Карточка эпизода: время, акцент действия, тема и записанный исход."""
        title = diary_view.episode_title(episode, self._language)
        action_key = diary_view.action_color_key(episode.get("action"))
        accent = self._DIARY_COLORS.get(action_key, theme.GREY)
        row = tk.Frame(
            self._diary_inner,
            bg=theme.BG_CENTER,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.BORDER,
            highlightthickness=1,
            bd=0,
        )
        row.pack(fill=tk.X, padx=theme.SPACING["sm"], pady=(theme.SPACING["sm"], 0))
        stripe = tk.Frame(row, width=3, bg=accent)
        stripe._preserve_bg = True
        stripe.pack(side=tk.LEFT, fill=tk.Y)
        content = tk.Frame(row, bg=theme.BG_CENTER)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        header = tk.Frame(content, bg=theme.BG_CENTER)
        header.pack(
            fill=tk.X,
            padx=theme.SPACING["sm"],
            pady=(theme.SPACING["sm"], 0),
        )
        tk.Label(
            header,
            text=diary_view.episode_time(episode),
            font=self._now_mono_small_font,
            bg=theme.BG_CENTER,
            fg=theme.MUTED,
        ).pack(side=tk.LEFT)
        tk.Label(
            header,
            text=diary_view.action_label(episode.get("action"), self._language),
            font=self._card_title_font,
            bg=theme.BG_CENTER,
            fg=accent if action_key != "grey" else theme.MUTED,
            padx=6,
        ).pack(side=tk.RIGHT)
        title_label = tk.Label(
            content,
            text=title,
            font=self._ui_font,
            bg=theme.BG_CENTER,
            fg=theme.TEXT,
            anchor="w",
            justify=tk.LEFT,
            wraplength=280,
        )
        title_label.pack(fill=tk.X, padx=theme.SPACING["sm"])
        error = episode.get("error")
        status_label = tk.Label(
            content,
            text=(
                str(error)
                if error
                else diary_view.episode_status(episode, self._language)
            ),
            font=self._card_title_font,
            bg=theme.BG_CENTER,
            fg=(
                theme.DANGER
                if error
                else accent if action_key != "grey" else theme.MUTED
            ),
            anchor="w",
            justify=tk.LEFT,
            wraplength=280,
        )
        status_label.pack(
            fill=tk.X,
            padx=theme.SPACING["sm"],
            pady=(2, theme.SPACING["sm"]),
        )
        row.bind(
            "<Configure>",
            lambda event, labels=(title_label, status_label): [
                label.configure(wraplength=max(160, event.width - 36))
                for label in labels
            ],
        )

        collapse_link = None
        if group_count > 1 or group_size > 1:
            count = group_count if group_count > 1 else group_size
            text_key = "×{count} · показать" if group_count > 1 else "×{count} · свернуть"
            collapse_link = tk.Label(
                content,
                text=self._t(text_key).format(count=count),
                font=self._now_mono_small_font,
                bg=theme.BG_CENTER,
                fg=theme.CYAN,
                anchor="e",
                cursor="hand2",
            )
            collapse_link.pack(
                fill=tk.X,
                padx=theme.SPACING["sm"],
                pady=(0, theme.SPACING["sm"]),
            )

        self._diary_rows_view.append(
            {
                "episode": episode,
                "group_index": group_index,
                "count": group_count,
                "key": group_key,
                "frame": row,
                "title": title,
            }
        )
        self._diary_row_frames.append(row)
        self._bind_row_click(row, len(self._diary_rows_view) - 1)
        if collapse_link is not None:
            # Поверх выбора эпизода: клик по «свернуть» не выделяет строку.
            collapse_link.bind(
                "<Button-1>",
                lambda _event: self._toggle_diary_group(group_key),
            )

    def _bind_row_click(self, widget, index: int) -> None:
        widget.bind("<Button-1>", lambda _event, i=index: self._select_diary_index(i))
        for child in widget.winfo_children():
            self._bind_row_click(child, index)

    def _toggle_diary_group(self, key: Any) -> None:
        """Развернуть или свернуть серию одинаковых эпизодов."""
        selected = None
        if self._diary_selected is not None and 0 <= self._diary_selected < len(
            self._diary_rows_view
        ):
            selected = self._diary_rows_view[self._diary_selected]["episode"]
        if key in self._diary_expanded:
            self._diary_expanded.discard(key)
        else:
            self._diary_expanded.add(key)
        self._render_diary_rows()
        self._restore_diary_selection(selected)

    def _restore_diary_selection(self, episode) -> None:
        """Вернуть выделение на тот же эпизод после пересборки списка."""
        self._diary_selected = None
        if episode is None:
            return
        for index, row in enumerate(self._diary_rows_view):
            if row["count"] == 1 and row["episode"] == episode:
                self._diary_selected = index
                self._highlight_diary_row(index)
                if self._diary_detail is not None:
                    self._diary_detail.configure(
                        text=diary_view.rows_text(
                            diary_view.episode_rows(episode, self._language)
                        )
                    )
                return

    def _select_diary_index(self, index: int) -> None:
        """Клик по строке: серия раскрывается, отдельный эпизод выбирается."""
        if not 0 <= index < len(self._diary_rows_view):
            return
        view_row = self._diary_rows_view[index]
        if view_row["count"] > 1:
            self._toggle_diary_group(view_row["key"])
            return
        self._highlight_diary_row(index)
        if self._diary_detail is not None:
            self._diary_detail.configure(
                text=diary_view.rows_text(
                    diary_view.episode_rows(view_row["episode"], self._language)
                )
            )

    def _highlight_diary_row(self, index: int) -> None:
        if self._diary_selected is not None and self._diary_selected < len(
            self._diary_row_frames
        ):
            previous = self._diary_row_frames[self._diary_selected]
            self._set_row_bg(previous, theme.BG_CENTER)
            previous.configure(
                highlightbackground=theme.BORDER, highlightcolor=theme.BORDER
            )
        self._diary_selected = index
        if index < len(self._diary_row_frames):
            selected = self._diary_row_frames[index]
            self._set_row_bg(selected, theme.SELECTION)
            selected.configure(
                highlightbackground=theme.AMBER, highlightcolor=theme.AMBER
            )

    def _set_row_bg(self, widget, color) -> None:
        if not getattr(widget, "_preserve_bg", False):
            try:
                widget.configure(bg=color)
            except Exception:
                pass
        for child in widget.winfo_children():
            self._set_row_bg(child, color)

    def _diary_titles(self) -> List[str]:
        """Заголовки видимых строк — точка для тестов и отладки."""
        return [row["title"] for row in self._diary_rows_view]

    def _apply_activity_data(self, snapshot):
        if self._activity_list is None:
            return
        drafts = diary_view.draft_rows(snapshot)
        game = (snapshot.get("activities") or {}).get("game")
        game = game if isinstance(game, dict) else None
        if (
            drafts == self._activity_entries
            and game == self._activity_game
            and self._activity_rendered_language == self._language
        ):
            return
        selection = self._activity_list.curselection()
        self._activity_rendered_language = self._language
        self._activity_entries = drafts
        self._activity_list.delete(0, tk.END)
        for draft in self._activity_entries:
            index = self._activity_list.size()
            self._activity_list.insert(
                tk.END,
                self._t("Черновик · {theme}").format(
                    theme=draft.get("theme") or self._t("без темы")
                ),
            )
            self._activity_list.itemconfigure(
                index,
                fg=theme.CYAN if draft.get("status") == "active" else theme.MUTED,
            )
        self._activity_game = game
        if self._activity_game is not None:
            index = self._activity_list.size()
            self._activity_list.insert(tk.END, self._t("Партия · крестики-нолики"))
            self._activity_list.itemconfigure(index, fg=theme.VIOLET)
        if not self._activity_entries and self._activity_game is None:
            self._activity_list.insert(tk.END, self._t("Занятий пока нет"))
            self._activity_list.configure(
                state=tk.DISABLED,
                justify=tk.CENTER,
                highlightbackground=theme.BORDER,
            )
            if self._activity_board is not None:
                self._activity_board.pack_forget()
            if self._activity_detail is not None:
                self._activity_detail.configure(text=self._t("Выберите запись слева."))
        else:
            self._activity_list.configure(state=tk.NORMAL, justify=tk.LEFT)
            if selection:
                index = min(selection[0], self._activity_list.size() - 1)
                self._activity_list.selection_set(index)
                self._on_activity_select()

    def _on_activity_select(self, _event=None):
        if self._activity_detail is None:
            return
        selection = self._activity_list.curselection()
        if not selection:
            return
        self._activity_list.configure(highlightbackground=theme.AMBER)
        if self._activity_board is not None:
            self._activity_board.pack_forget()
        index = selection[0]
        if index < len(self._activity_entries):
            rows = diary_view.draft_detail(
                self._activity_entries[index], self._language
            )
        elif self._activity_game is not None and index == len(self._activity_entries):
            rows = diary_view.game_detail(self._life_snapshot, self._language)
            if self._render_activity_board(self._activity_game):
                # Клетки уже показаны графически, текстовая строка не дублируется.
                rows = [row for row in rows if row[0] != self._t("Поле")]
        else:
            return
        self._activity_detail.configure(text=diary_view.rows_text(rows))

    def _render_activity_board(self, game) -> bool:
        """Показать только записанное поле 3×3; неверные данные не отображать."""
        if self._activity_board is None:
            return False
        board = game.get("board") if isinstance(game, dict) else None
        if not isinstance(board, list) or len(board) != 9:
            return False
        for index, cell in enumerate(self._activity_board_cells):
            value = board[index]
            text = "" if value in (None, "", ".") else str(value)
            color = {"X": theme.CYAN, "O": theme.VIOLET}.get(text, theme.TEXT)
            cell.configure(text=text, fg=color)
        self._activity_board.pack(
            before=self._activity_detail,
            padx=theme.SPACING["md"],
            pady=(theme.SPACING["sm"], theme.SPACING["sm"]),
        )
        return True

    def _build_page_access(self, parent):
        """Доступы: фактические переключатели, счётчики и снимок состояния."""
        from src.app.access_control import HINTS, LABELS

        page = tk.Frame(parent, bg=theme.BG_DEEP)
        tk.Label(
            page,
            text="СНИМКИ СОСТОЯНИЯ · СОБЫТИЯ ЯДРА",
            font=self._card_title_font,
            bg=theme.BG_DEEP,
            fg=theme.CYAN,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(theme.SPACING["sm"], 0))
        tk.Label(
            page,
            text="Доступы",
            font=self._headline_font,
            bg=theme.BG_DEEP,
            fg=theme.AMBER,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"])
        tk.Label(
            page,
            text="человек сам решает, что ядру разрешено; выключение ничего не стирает",
            font=self._ui_font,
            bg=theme.BG_DEEP,
            fg=theme.MUTED,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(2, theme.SPACING["sm"]))

        body = tk.Frame(page, bg=theme.BG_DEEP)
        body.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["md"],
            pady=(0, theme.SPACING["md"]),
        )
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=theme.BG_DEEP)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, theme.SPACING["sm"]))
        right = tk.Frame(body, bg=theme.BG_DEEP)
        right.grid(row=0, column=1, sticky="nsew")

        switches, _header = self._now_card(left, "РАЗРЕШЕНИЯ", theme.CYAN)
        switches.pack(fill=tk.BOTH, expand=True)
        accents = {
            "network": theme.CYAN,
            "delamain": theme.VIOLET,
            "effector": theme.AMBER,
            "presence": theme.GREY,
        }
        for key in ("network", "delamain", "effector", "presence"):
            var = tk.BooleanVar(value=False)
            self._access_vars[key] = var
            row = tk.Frame(
                switches,
                bg=theme.BG_CENTER,
                highlightbackground=theme.BORDER,
                highlightthickness=1,
            )
            row.pack(
                fill=tk.X,
                padx=theme.SPACING["sm"],
                pady=(theme.SPACING["sm"], 0),
            )
            tk.Frame(row, width=3, bg=accents[key]).pack(side=tk.LEFT, fill=tk.Y)
            content = tk.Frame(row, bg=theme.BG_CENTER)
            content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            top = tk.Frame(content, bg=theme.BG_CENTER)
            top.pack(
                fill=tk.X,
                padx=theme.SPACING["sm"],
                pady=(theme.SPACING["sm"], 0),
            )
            self._build_access_switch(top, key, var)
            status = tk.Label(
                top,
                text="",
                font=self._now_mono_small_font,
                bg=theme.BG_CENTER,
                fg=theme.MUTED,
                anchor="e",
            )
            status.pack(side=tk.RIGHT, padx=(theme.SPACING["xs"], 0))
            self._access_status_labels[key] = status
            label = tk.Label(
                top,
                text=LABELS[key],
                font=self._ui_font,
                bg=theme.BG_CENTER,
                fg=theme.TEXT,
                anchor="w",
                cursor="hand2",
            )
            label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(theme.SPACING["sm"], 0))
            label.bind(
                "<Button-1>",
                lambda _event, name=key: self._toggle_access_var(name),
            )
            hint = tk.Label(
                content,
                text=HINTS[key],
                font=self._card_title_font,
                bg=theme.BG_CENTER,
                fg=theme.MUTED,
                anchor="w",
                justify=tk.LEFT,
                wraplength=300,
            )
            hint.pack(
                fill=tk.X,
                padx=(62, theme.SPACING["sm"]),
                pady=(2, theme.SPACING["sm"]),
            )
            row.bind(
                "<Configure>",
                lambda event, widget=hint: widget.configure(
                    wraplength=max(140, event.width - 82)
                ),
            )
            self._draw_access_switch(key)

        effector, _header = self._now_card(right, "ДЕЙСТВИЯ", theme.AMBER)
        effector.pack(fill=tk.X, pady=(0, theme.SPACING["sm"]))
        self._effector_card = self._now_card_text(effector, self._now_body_font, 240)
        access, _header = self._now_card(
            right, "ЧТО РАЗРЕШЕНО СЕЙЧАС", theme.VIOLET
        )
        access.pack(fill=tk.X, pady=(0, theme.SPACING["sm"]))
        self._access_card = self._now_card_text(access, self._now_body_font, 240)
        right.bind(
            "<Configure>",
            lambda event: (
                self._effector_card.configure(wraplength=max(150, event.width - 34)),
                self._access_card.configure(wraplength=max(150, event.width - 34)),
            ),
        )

        detail, _header = self._now_card(right, "ПОДРОБНОСТИ", theme.VIOLET)
        detail.pack(fill=tk.BOTH, expand=True)
        self._status_text = scrolledtext.ScrolledText(
            detail,
            width=20,
            height=6,
            font=self._mono_font,
            bg=theme.BG_CENTER,
            fg=theme.TEXT,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self._status_text.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["sm"],
            pady=(theme.SPACING["xs"], theme.SPACING["sm"]),
        )
        return page

    def _build_page_dialog(self, parent):
        """Диалог: неоновая лента, закреплённый ввод и справочник команд."""
        page = tk.Frame(parent, bg=theme.BG_DEEP)
        tk.Label(
            page,
            text="СНИМКИ СОСТОЯНИЯ · СОБЫТИЯ ЯДРА",
            font=self._card_title_font,
            bg=theme.BG_DEEP,
            fg=theme.CYAN,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(theme.SPACING["sm"], 0))
        tk.Label(
            page,
            text="Диалог",
            font=self._headline_font,
            bg=theme.BG_DEEP,
            fg=theme.AMBER,
            anchor="w",
        ).pack(fill=tk.X, padx=theme.SPACING["md"])
        tk.Label(
            page,
            text="Прямой разговор с ядром — сообщения, ответы и найденные материалы.",
            font=self._ui_font,
            bg=theme.BG_DEEP,
            fg=theme.MUTED,
            anchor="w",
            justify=tk.LEFT,
            wraplength=760,
        ).pack(fill=tk.X, padx=theme.SPACING["md"], pady=(2, theme.SPACING["sm"]))

        body = tk.Frame(page, bg=theme.BG_DEEP)
        body.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["md"],
            pady=(0, theme.SPACING["md"]),
        )
        body.columnconfigure(0, weight=1, minsize=340)
        body.columnconfigure(1, weight=0, minsize=220)
        body.rowconfigure(0, weight=1)

        conversation, _header = self._now_card(body, "ЛЕНТА ДИАЛОГА", theme.CYAN)
        conversation.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        commands, _header = self._now_card(body, "КОМАНДЫ", theme.VIOLET)
        commands.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        commands.configure(width=260)
        commands.grid_propagate(False)

        # Сначала резервируем нижние блоки: лента не вытеснит ввод за край.
        input_frame = tk.Frame(
            conversation,
            bg=theme.BG_CENTER,
            highlightbackground=theme.CYAN,
            highlightcolor=theme.CYAN,
            highlightthickness=1,
        )
        composer_hint = tk.Label(
            conversation,
            text="Enter — отправить · ↑ ↓ — история ввода",
            font=self._now_mono_small_font,
            bg=theme.SURFACE,
            fg=theme.MUTED,
            anchor="w",
            justify=tk.LEFT,
            wraplength=480,
        )
        composer_hint.pack(
            side=tk.BOTTOM,
            fill=tk.X,
            padx=theme.SPACING["md"],
            pady=(theme.SPACING["xs"], theme.SPACING["sm"]),
        )
        input_frame.pack(
            side=tk.BOTTOM,
            fill=tk.X,
            padx=theme.SPACING["md"],
            pady=(theme.SPACING["xs"], 0),
        )

        self._text = scrolledtext.ScrolledText(
            conversation,
            wrap=tk.WORD,
            width=40,
            height=12,
            font=self._ui_font,
            bg=theme.BG_CENTER,
            fg=theme.TEXT,
            insertbackground=theme.TEXT,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.CYAN,
            padx=10,
            pady=8,
            state=tk.DISABLED,
        )
        self._text.pack(
            fill=tk.BOTH,
            expand=True,
            padx=theme.SPACING["md"],
            pady=(theme.SPACING["xs"], theme.SPACING["sm"]),
        )
        self._text.vbar.configure(
            bg=theme.SURFACE,
            troughcolor=theme.BG_CENTER,
            activebackground=theme.CYAN,
            highlightthickness=0,
            bd=0,
            width=10,
        )
        self._text.tag_config(
            "user",
            foreground=theme.AMBER,
            font=self._ui_font,
            lmargin1=8,
            lmargin2=8,
            spacing1=8,
            spacing3=6,
        )
        self._text.tag_config(
            "agent",
            foreground=theme.CYAN,
            font=self._ui_font,
            lmargin1=8,
            lmargin2=8,
            spacing1=8,
            spacing3=6,
        )
        self._text.tag_config(
            "system",
            foreground=theme.MUTED,
            font=self._card_title_font,
            justify="center",
            spacing1=6,
            spacing3=6,
        )
        self._text.tag_config(
            "error",
            foreground=theme.DANGER,
            font=self._ui_font,
            lmargin1=8,
            lmargin2=8,
            spacing1=8,
            spacing3=6,
        )
        self._text.tag_config(
            "life",
            foreground=theme.AMBER,
            font=self._ui_font,
            lmargin1=12,
            lmargin2=12,
            spacing1=8,
            spacing3=6,
        )
        # Карточка источника: заголовок, метаданные, выдержка и ссылка.
        self._text.tag_config(
            "web_head",
            foreground=theme.VIOLET,
            font=self._ui_font,
            spacing1=8,
        )
        self._text.tag_config(
            "web_meta",
            foreground=theme.DIMMED,
            font=self._card_title_font,
            lmargin1=12,
            lmargin2=12,
        )
        self._text.tag_config(
            "web_body",
            foreground=theme.TEXT,
            font=self._ui_font,
            lmargin1=12,
            lmargin2=12,
            rmargin=12,
            spacing3=4,
        )

        self._input_var = tk.StringVar()
        self._dialog_send_button = tk.Button(
            input_frame,
            text="Сказать",
            command=self._on_send,
            font=self._mono_font,
            bg=theme.AMBER,
            fg=theme.BG_DEEP,
            activebackground=theme.TEXT,
            activeforeground=theme.BG_DEEP,
            disabledforeground=theme.DIMMED,
            relief=tk.FLAT,
            bd=0,
            padx=16,
            pady=8,
            cursor="hand2",
        )
        self._dialog_send_button.pack(side=tk.RIGHT, fill=tk.Y)
        self._input_entry = tk.Entry(
            input_frame,
            textvariable=self._input_var,
            font=self._ui_font,
            bg=theme.BG_CENTER,
            fg=theme.TEXT,
            insertbackground=theme.CYAN,
            selectbackground=theme.GLOW_CYAN,
            selectforeground=theme.TEXT,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
        )
        self._input_entry.pack(
            side=tk.LEFT,
            fill=tk.BOTH,
            expand=True,
            padx=(10, theme.SPACING["xs"]),
            pady=8,
        )
        self._input_entry.bind("<Return>", self._on_send)
        self._input_entry.bind("<Up>", self._on_history_up)
        self._input_entry.bind("<Down>", self._on_history_down)
        self._input_entry.focus_set()
        conversation.bind(
            "<Configure>",
            lambda event: composer_hint.configure(
                wraplength=max(220, event.width - 32)
            ),
        )

        command_subtitle = tk.Label(
            commands,
            text="Команды вводятся в поле сообщения",
            font=self._now_body_font,
            bg=theme.SURFACE,
            fg=theme.MUTED,
            anchor="w",
            justify=tk.LEFT,
            wraplength=220,
        )
        command_subtitle.pack(
            fill=tk.X,
            padx=theme.SPACING["md"],
            pady=(theme.SPACING["xs"], theme.SPACING["sm"]),
        )
        command_footer = tk.Label(
            commands,
            text="Ответы появляются в ленте после реальных событий ядра.",
            font=self._now_body_font,
            bg=theme.SURFACE,
            fg=theme.MUTED,
            anchor="sw",
            justify=tk.LEFT,
            wraplength=220,
        )
        command_footer.pack(
            side=tk.BOTTOM,
            fill=tk.X,
            padx=theme.SPACING["md"],
            pady=(theme.SPACING["xs"], theme.SPACING["sm"]),
        )
        command_rows = (
            ("/help", "справка", theme.CYAN),
            ("/status", "состояние", theme.CYAN),
            ("/goals", "цели", theme.CYAN),
            ("/concepts", "концепции", theme.CYAN),
            ("/ask", "открытый вопрос", theme.VIOLET),
            ("/pause", "пауза", theme.AMBER),
            ("/resume", "продолжить", theme.AMBER),
            ("/save", "сохранить", theme.CYAN),
        )
        command_descriptions = []
        for command, description, color in command_rows:
            row = tk.Frame(
                commands,
                bg=theme.BG_CENTER,
                highlightbackground=theme.BORDER,
                highlightthickness=1,
            )
            row.pack(
                fill=tk.X,
                padx=theme.SPACING["md"],
                pady=1,
            )
            tk.Label(
                row,
                text=command,
                font=self._now_mono_small_font,
                bg=theme.BG_CENTER,
                fg=color,
                anchor="w",
            ).pack(side=tk.LEFT, padx=(8, 4), pady=4)
            label = tk.Label(
                row,
                text=description,
                font=self._now_body_font,
                bg=theme.BG_CENTER,
                fg=theme.MUTED,
                anchor="e",
                justify=tk.RIGHT,
                wraplength=100,
            )
            label.pack(side=tk.RIGHT, padx=(4, 8), pady=4)
            command_descriptions.append(label)

        def resize_commands(event) -> None:
            width = 220 if event.width < 760 else 260
            commands.configure(width=width)
            command_subtitle.configure(wraplength=width - 30)
            command_footer.configure(wraplength=width - 30)
            for label in command_descriptions:
                label.configure(wraplength=max(64, width - 126))

        body.bind("<Configure>", resize_commands)

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
                    bg=theme.GLOW_AMBER if active else theme.SIDEBAR,
                    fg=theme.AMBER if active else theme.MUTED,
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
            root,
            bg=theme.BG_DEEP,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._controls_frame = frame

        left = tk.Frame(frame, bg=theme.BG_DEEP)
        left.pack(side=tk.LEFT, padx=(theme.SPACING["sm"], 0))
        # Правая группа собирается с правого края: Выход — всегда последний.
        right = tk.Frame(frame, bg=theme.BG_DEEP)
        right.pack(side=tk.RIGHT, padx=(0, theme.SPACING["sm"]))

        def button(parent, text, command, *, bg=theme.SURFACE, fg=theme.TEXT, padx=10):
            widget = tk.Button(
                parent,
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

        def separator(parent):
            tk.Frame(parent, width=1, bg=theme.BORDER).pack(
                side=tk.LEFT, fill=tk.Y, padx=6, pady=6
            )

        self._pause_button = button(left, "⏸ Пауза", self._action_toggle_pause)

        # Темп — сегмент из трёх режимов, активный подсвечен.
        tk.Label(
            left,
            text="ТЕМП",
            bg=theme.BG_DEEP,
            fg=theme.DIMMED,
            font=self._card_title_font,
        ).pack(side=tk.LEFT, padx=(theme.SPACING["md"], theme.SPACING["xs"]))
        segment = tk.Frame(
            left,
            bg=theme.BG_CENTER,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        segment.pack(side=tk.LEFT, pady=6)
        for mode in ("live", "fast", "max"):
            chip = tk.Button(
                segment,
                text=SPEED_LABELS[mode],
                command=lambda m=mode: self._action_set_speed(m),
                bg=theme.BG_CENTER,
                fg=theme.MUTED,
                activebackground=theme.GLOW_CYAN,
                activeforeground=theme.CYAN,
                relief=tk.FLAT,
                bd=0,
                padx=10,
            )
            chip.pack(side=tk.LEFT, padx=2, pady=2)
            self._speed_buttons[mode] = chip

        button(left, "⏭ Шаг", self._action_step)
        button(left, "Сохранить", self._action_save, padx=8)

        button(right, "Выход", self._action_quit, fg=theme.MUTED, padx=8)
        separator(right)
        self._cancel_life_button = button(
            right, "Отменить запрос", self._action_cancel_life, padx=8
        )
        self._cancel_life_button.pack_forget()  # появляется только при запросе
        self._wake_button = button(
            right, "Разбудить", self._action_wake, fg=theme.GREEN, padx=8
        )
        self._sleep_button = button(right, "Сон", self._action_request_dream, padx=8)
        # Уход — единственное необратимое действие: красный текст и рамка.
        self._terminate_button = tk.Button(
            right,
            text="Уйти…",
            command=self._action_request_termination,
            bg=theme.SURFACE,
            fg=theme.DANGER,
            activebackground=theme.BORDER,
            activeforeground=theme.DANGER,
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=5,
            highlightbackground=theme.DANGER,
            highlightthickness=1,
        )
        self._terminate_button.pack(side=tk.LEFT, padx=3, pady=6)
        tk.Label(
            right,
            text="ЖИЗНЬ",
            bg=theme.BG_DEEP,
            fg=theme.DIMMED,
            font=self._card_title_font,
        ).pack(side=tk.LEFT, padx=(theme.SPACING["md"], theme.SPACING["xs"]))

        self._refresh_life_buttons("alive")

    # ============================================================
    # Действия панели управления
    # ============================================================

    def _action_toggle_pause(self) -> None:
        paused = bool(self._status_snapshot.get("paused"))
        event = Events.RESUME_REQUESTED if paused else Events.PAUSE_REQUESTED
        self._publish(event, {})
        self._append_system(
            self._t("Возобновляю жизнь." if paused else "Ставлю на паузу.")
        )

    def _action_set_speed(self, mode: str) -> None:
        self._publish(Events.SPEED_CHANGED, {"mode": mode})
        label = self._t(SPEED_LABELS.get(mode, mode))
        self._append_system(self._t("Темп жизни: {mode}.").format(mode=label))

    def _action_step(self) -> None:
        self._publish(Events.STEP_REQUESTED, {})
        self._append_system(self._t("Один цикл по кнопке «Шаг»."))

    def _action_save(self) -> None:
        self._publish(Events.SAVE_REQUESTED, {})
        self._append_system(self._t("Прошу сохранить состояние."))

    def _action_wake(self) -> None:
        self._publish(Events.LIFE_WAKE, {})

    def _action_cancel_life(self) -> None:
        prompt = self._life_prompt or {}
        self._publish(Events.LIFE_CANCEL, {"request_id": prompt.get("request_id")})

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
            self._append_error(
                self._t("Не удалось передать событие {event}: {error}").format(
                    event=event, error=exc
                )
            )

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

        request_kind = self._t("сон" if kind == "dream" else "уход без семени")
        instructions = self._t(
            "Чтобы подтвердить, подождите {seconds} с и введите точно:"
        ).format(seconds=f"{cooldown:.0f}")
        self._append_life(
            f"{self._t('ЗАПРОС: {kind}').format(kind=request_kind)}\n"
            f"{description}\n\n{instructions}\n    {phrase}\n"
            f"{self._t('Или нажмите «Отменить запрос».')}"
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
            self._append_system(
                self._t("Уход не выполнен: {message}").format(message=message)
            )

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
            self._append_system(self._t("Пауза выдержана. Введите фразу в поле ниже."))
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
                self._t("Рано: подождите ещё {seconds} с.").format(
                    seconds=f"{remaining:.0f}"
                )
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

    def _render_web_card(self, data: Dict[str, Any]) -> None:
        """Карточка источника: заголовок, домен, выдержка; ссылка без
        процентных кракозябр — адрес декодируется для чтения."""
        if self._text is None:
            return
        title = str(data.get("title") or data.get("concept") or "нашёл материал")
        concept = str(data.get("concept") or "")
        extract = str(data.get("extract") or "")
        raw_url = str(data.get("url") or "")
        url = urllib.parse.unquote(raw_url)
        domain = urllib.parse.urlsplit(raw_url).netloc
        if len(extract) > 240:
            short = extract[:240].rsplit(" ", 1)[0] + "…"
        else:
            short = extract

        card_id = f"web{self._web_card_counter}"
        self._web_card_counter += 1
        self._web_cards[card_id] = {
            "full": extract,
            "short": short,
            "open": False,
        }

        text = self._text
        text.configure(state=tk.NORMAL)
        text.insert(tk.END, "\n")
        text.insert(tk.END, f"🌐 {title}\n", "web_head")
        if concept:
            text.insert(tk.END, f"тема: {concept}\n", "web_meta")
        text.insert(tk.END, f"источник: {domain or url}\n", "web_meta")
        text.mark_set(f"{card_id}s", tk.END)
        text.mark_gravity(f"{card_id}s", tk.LEFT)
        text.insert(tk.END, short + "\n", "web_body")
        text.mark_set(f"{card_id}e", tk.END)
        text.mark_set(f"{card_id}ls", tk.END)
        text.mark_gravity(f"{card_id}ls", tk.LEFT)
        text.insert(tk.END, "развернуть статью ▾", f"{card_id}t")
        text.mark_set(f"{card_id}le", tk.END)
        text.tag_config(f"{card_id}t", foreground=theme.CYAN)
        text.tag_bind(
            f"{card_id}t",
            "<Button-1>",
            lambda _event, card=card_id: self._toggle_web_card(card),
        )
        text.insert(tk.END, "\n\n")
        text.see(tk.END)
        text.configure(state=tk.DISABLED)

    def _toggle_web_card(self, card_id: str) -> None:
        """Развернуть полную статью или свернуть обратно до выдержки."""
        card = self._web_cards.get(card_id)
        text = self._text
        if card is None or text is None:
            return
        body = card["full"] if not card["open"] else card["short"]
        label = "свернуть статью ▴" if not card["open"] else "развернуть статью ▾"
        card["open"] = not card["open"]
        text.configure(state=tk.NORMAL)
        text.delete(f"{card_id}s", f"{card_id}e")
        text.insert(f"{card_id}s", body + "\n", "web_body")
        text.delete(f"{card_id}ls", f"{card_id}le")
        text.insert(f"{card_id}ls", label, f"{card_id}t")
        text.see(tk.END)
        text.configure(state=tk.DISABLED)

    def _append_life(self, text: str) -> None:
        self._append("🌙 ЖИЗНЬ:", text, tag="life")

    # ============================================================
    # Жизненный цикл
    # ============================================================

    def _position_bottom_right(self) -> None:
        """Большое окно обсерватории — по центру экрана."""
        root = self._root
        root.update_idletasks()
        # Панель подробностей на карте занимает 310 px, поэтому окно уже
        # ~1180 px обрезало бы её правым краем. На маленьком экране
        # ужимаемся по доступному размеру, а не вылезаем за него.
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        width = min(1200, max(900, screen_w - 80))
        height = min(760, max(640, screen_h - 120))
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
        self._diary_canvas = None
        self._diary_inner = None
        self._access_switches = {}
        self._access_status_labels = {}
        self._graph_filter_buttons = {}
        super()._destroy_root()


__all__ = ["MainWindow", "SPEED_LABELS"]
