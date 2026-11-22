"""Отдельное Tk-окно ручной разметки; создаётся только по явной команде."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from src.core.response_annotation import AnnotationError
from src.ui import theme

_INTENT_LABELS = {
    "ASK_SELF_STATE": "Вопрос о состоянии",
    "ASK_SELF_ACTIVITY": "Вопрос о занятии",
    "UNKNOWN_OR_OTHER": "Другое",
    "ABSTAIN": "Не уверен",
}


class AnnotationReviewWindow:
    """Небольшая оболочка над AnnotationReviewSession без доступа к runtime."""

    def __init__(self, session) -> None:
        self.session = session
        self._root = None

    @staticmethod
    def _label(parent, text: str, *, size=11, color=None):
        return tk.Label(
            parent,
            text=text,
            bg=theme.SURFACE,
            fg=color or theme.TEXT,
            font=(theme.font_family(), size),
            anchor="w",
            justify="left",
            wraplength=900,
        )

    @staticmethod
    def _entry(parent, textvariable, width=18):
        return tk.Entry(
            parent,
            textvariable=textvariable,
            width=width,
            bg=theme.BG_CENTER,
            fg=theme.TEXT,
            insertbackground=theme.TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            font=(theme.font_family(), 11),
        )

    @staticmethod
    def _button(parent, text: str, command, *, accent=False):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=theme.AMBER if accent else theme.BG_CENTER,
            fg=theme.BG_DEEP if accent else theme.TEXT,
            activebackground=theme.SELECTION,
            activeforeground=theme.TEXT,
            relief="flat",
            bd=0,
            padx=14,
            pady=9,
            font=(theme.font_family(), 10, "bold"),
            cursor="hand2",
        )

    @staticmethod
    def _readonly_text(parent, height: int):
        return tk.Text(
            parent,
            height=height,
            wrap=tk.WORD,
            bg=theme.BG_CENTER,
            fg=theme.TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            padx=12,
            pady=10,
            font=(theme.font_family(), 12),
            state=tk.DISABLED,
        )

    def build(self, root) -> None:
        self._root = root
        root.title("Разметка ответов — песочница")
        root.configure(bg=theme.SURFACE)
        root.minsize(820, 700)
        body = tk.Frame(root, bg=theme.SURFACE, padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        self._label(
            body,
            "Ручная разметка ответов",
            size=20,
            color=theme.CYAN,
        ).pack(fill=tk.X)
        self._label(
            body,
            "Работа идёт только с копией в песочнице. Тэсс не меняется, обучение не запускается.",
            color=theme.MUTED,
        ).pack(fill=tk.X, pady=(4, 10))
        self._progress_label = self._label(body, "", color=theme.AMBER)
        self._progress_label.pack(fill=tk.X, pady=(0, 12))

        self._input_label = self._label(body, "Сообщение человека", color=theme.VIOLET)
        self._input_label.pack(fill=tk.X)
        self._input_text = self._readonly_text(body, 2)
        self._input_text.pack(fill=tk.X, pady=(4, 10))
        self._response_label = self._label(body, "Ответ Тэсс", color=theme.VIOLET)
        self._response_label.pack(fill=tk.X)
        self._response_text = self._readonly_text(body, 3)
        self._response_text.pack(fill=tk.X, pady=(4, 12))

        self._intent_var = tk.StringVar()
        self._label(body, "О чём спросил человек?", size=12).pack(fill=tk.X)
        choices = tk.Frame(body, bg=theme.SURFACE)
        choices.pack(fill=tk.X, pady=(4, 10))
        for value, caption in _INTENT_LABELS.items():
            tk.Radiobutton(
                choices,
                text=caption,
                value=value,
                variable=self._intent_var,
                bg=theme.SURFACE,
                fg=theme.TEXT,
                selectcolor=theme.BG_CENTER,
                activebackground=theme.SURFACE,
                activeforeground=theme.CYAN,
                font=(theme.font_family(), 10),
                anchor="w",
            ).pack(side=tk.LEFT, padx=(0, 14))

        facts = tk.LabelFrame(
            body,
            text=" Факты в ответе (если нужно исправить) ",
            bg=theme.SURFACE,
            fg=theme.MUTED,
            bd=1,
            relief="solid",
            font=(theme.font_family(), 10),
            padx=10,
            pady=8,
        )
        facts.pack(fill=tk.X, pady=(0, 10))
        self._energy_var = tk.StringVar()
        self._activity_status_var = tk.StringVar(value="none")
        self._activity_kind_var = tk.StringVar()
        self._activity_cycle_var = tk.StringVar()
        self._completed_kind_var = tk.StringVar()
        self._completed_cycle_var = tk.StringVar()
        rows = (
            ("Энергия (число)", self._energy_var),
            ("Текущее занятие (код)", self._activity_kind_var),
            ("Цикл начала занятия", self._activity_cycle_var),
            ("Завершённое занятие (код)", self._completed_kind_var),
            ("Цикл завершения", self._completed_cycle_var),
        )
        for row, (caption, variable) in enumerate(rows):
            self._label(facts, caption, size=10, color=theme.MUTED).grid(
                row=row, column=0, sticky="w", pady=3, padx=(0, 12)
            )
            self._entry(facts, variable).grid(row=row, column=1, sticky="ew", pady=3)
        self._label(facts, "Занятие сейчас", size=10, color=theme.MUTED).grid(
            row=0, column=2, sticky="w", pady=3, padx=(22, 8)
        )
        status = tk.OptionMenu(
            facts,
            self._activity_status_var,
            "none",
            "current",
        )
        status.configure(
            bg=theme.BG_CENTER,
            fg=theme.TEXT,
            activebackground=theme.SELECTION,
            activeforeground=theme.TEXT,
            highlightthickness=0,
            relief="flat",
            font=(theme.font_family(), 10),
        )
        status.grid(row=0, column=3, sticky="ew", pady=3)
        self._label(
            facts,
            "Код занятия — например, draw или compose_music. Пустые необязательные поля означают «факта нет».",
            size=9,
            color=theme.DIMMED,
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))
        facts.columnconfigure(1, weight=1)

        navigation = tk.Frame(body, bg=theme.SURFACE)
        navigation.pack(
            fill=tk.X,
            side=tk.BOTTOM,
            pady=(0, 8),
            before=body.winfo_children()[0],
        )
        self._previous_button = self._button(navigation, "← Назад", self._previous)
        self._previous_button.pack(side=tk.LEFT)
        self._next_button = self._button(navigation, "Вперёд →", self._next)
        self._next_button.pack(side=tk.LEFT, padx=8)
        self._status_label = self._label(navigation, "", size=10, color=theme.MUTED)
        self._status_label.pack(side=tk.LEFT, padx=12, fill=tk.X, expand=True)

        controls = tk.Frame(body, bg=theme.SURFACE)
        # Сначала резервируем действия: длинные тексты не вытеснят кнопки.
        controls.pack(
            fill=tk.X,
            side=tk.BOTTOM,
            pady=(8, 0),
            before=navigation,
        )
        self._confirm_button = self._button(
            controls, "Подтвердить исходный вариант", self._confirm, accent=True
        )
        self._confirm_button.pack(side=tk.LEFT)
        self._correction_button = self._button(
            controls, "Сохранить исправление", self._save_correction
        )
        self._correction_button.pack(side=tk.LEFT, padx=8)
        self._abstain_button = self._button(controls, "Не уверен", self._abstain)
        self._abstain_button.pack(side=tk.LEFT)
        self._plan_abstain_button = self._button(
            controls, "Факты неясны", self._abstain_plan
        )
        self._plan_abstain_button.pack(side=tk.LEFT, padx=8)
        self._intent_var.trace_add("write", self._on_intent_change)
        self._render()

    @staticmethod
    def _set_text(widget, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state=tk.DISABLED)

    def _fill_plan(self, plan) -> None:
        plan = plan or {}
        activity = plan.get("activity") or {}
        completed = plan.get("last_completed_action") or {}
        energy = plan.get("energy")
        self._energy_var.set("" if energy is None else str(energy))
        self._activity_status_var.set(activity.get("status", "none"))
        self._activity_kind_var.set(activity.get("kind") or "")
        started = activity.get("started_cycle")
        self._activity_cycle_var.set("" if started is None else str(started))
        self._completed_kind_var.set(completed.get("kind") or "")
        cycle = completed.get("cycle")
        self._completed_cycle_var.set("" if cycle is None else str(cycle))

    def _render(self) -> None:
        progress = self.session.progress()
        self._progress_label.configure(
            text=(
                f"Пример {min(self.session.position + 1, progress['total'])} из {progress['total']}"
                f" · размечено: {progress['annotated']} · осталось: {progress['remaining']}\n"
                f"Надёжных меток смысла: {progress['resolved_intent']}"
                f" · фактов: {progress['resolved_plan']}"
            )
        )
        self._previous_button.configure(
            state=tk.NORMAL if self.session.position > 0 else tk.DISABLED
        )
        self._next_button.configure(
            state=(
                tk.NORMAL
                if self.session.position + 1 < progress["total"]
                else tk.DISABLED
            )
        )
        if not self.session.candidates:
            self._set_text(self._input_text, "Нет подходящих примеров.")
            self._set_text(self._response_text, "")
            for button in (
                self._confirm_button,
                self._correction_button,
                self._abstain_button,
                self._plan_abstain_button,
            ):
                button.configure(state=tk.DISABLED)
            return
        draft = self.session.draft()
        self._set_text(self._input_text, self.session.current.input_text)
        self._set_text(self._response_text, self.session.current.response_text)
        self._intent_var.set(draft["intent"] or "ABSTAIN")
        self._fill_plan(draft["semantic_plan"])

    def _plan_from_fields(self, intent: str):
        if intent not in {"ASK_SELF_STATE", "ASK_SELF_ACTIVITY"}:
            return None
        current_draft = self.session.draft()
        source = (
            current_draft["semantic_plan"] or self.session.current.suggested_plan or {}
        )
        energy_text = self._energy_var.get().strip()
        energy = float(energy_text) if energy_text else None
        completed = None
        completed_kind = self._completed_kind_var.get().strip()
        completed_cycle = self._completed_cycle_var.get().strip()
        if completed_kind or completed_cycle:
            if not completed_kind or not completed_cycle:
                raise ValueError("У завершённого занятия заполните и код, и цикл.")
            completed = {"kind": completed_kind, "cycle": int(completed_cycle)}
        activity = None
        if intent == "ASK_SELF_ACTIVITY":
            if self._activity_status_var.get() == "current":
                activity = {
                    "status": "current",
                    "kind": self._activity_kind_var.get().strip(),
                    "started_cycle": int(self._activity_cycle_var.get()),
                }
            else:
                activity = {"status": "none", "kind": None, "started_cycle": None}
        claims = []
        if intent == "ASK_SELF_STATE" and energy is not None:
            claims.append("state.energy")
        if activity is not None:
            if activity["status"] == "none":
                claims.append("activity.none")
            else:
                claims.append(f"activity.current:{activity['kind']}")
        if completed is not None:
            claims.append(f"activity.completed:{completed['kind']}")
        return {
            "schema_version": 1,
            "language": source.get("language", "ru"),
            "activity": activity,
            "last_completed_action": completed,
            "energy": energy if intent == "ASK_SELF_STATE" else None,
            "allowed_claims": claims,
        }

    def _show_error(self, error: Exception) -> None:
        self._status_label.configure(
            text="Не сохранено. Проверьте поля.", fg=theme.DANGER
        )
        messagebox.showerror("Разметка не сохранена", str(error), parent=self._root)

    def _saved(self) -> None:
        self._status_label.configure(
            text="Сохранено как новая ревизия.", fg=theme.GREEN
        )
        self.session.next()
        self._render()

    def _confirm(self) -> None:
        try:
            self.session.confirm_current()
        except (AnnotationError, ValueError) as error:
            self._show_error(error)
            return
        self._saved()

    def _save_correction(self) -> None:
        intent = self._intent_var.get()
        try:
            if intent == "ABSTAIN":
                self.session.abstain_current()
            else:
                self.session.correct_current(
                    intent, semantic_plan=self._plan_from_fields(intent)
                )
        except (AnnotationError, ValueError) as error:
            self._show_error(error)
            return
        self._saved()

    def _abstain(self) -> None:
        try:
            self.session.abstain_current()
        except (AnnotationError, ValueError) as error:
            self._show_error(error)
            return
        self._saved()

    def _update_intent_controls(self) -> None:
        is_self_intent = self._intent_var.get() in {
            "ASK_SELF_STATE",
            "ASK_SELF_ACTIVITY",
        }
        self._plan_abstain_button.configure(
            state=tk.NORMAL if is_self_intent else tk.DISABLED
        )

    def _on_intent_change(self, *_args) -> None:
        self._update_intent_controls()

    def _abstain_plan(self) -> None:
        intent = self._intent_var.get()
        if intent not in {"ASK_SELF_STATE", "ASK_SELF_ACTIVITY"}:
            return
        try:
            self.session.correct_current(
                intent,
                semantic_plan=None,
                plan_review="abstained",
                plan_uncertainties=("plan_facts",),
            )
        except (AnnotationError, ValueError) as error:
            self._show_error(error)
            return
        self._saved()

    def _previous(self) -> None:
        self.session.previous()
        self._render()

    def _next(self) -> None:
        self.session.next()
        self._render()


def run_annotation_review(session) -> None:
    """Запустить отдельное окно и гарантированно закрыть только его журнал."""
    root = tk.Tk()
    try:
        window = AnnotationReviewWindow(session)
        window.build(root)
        root.geometry("1000x820")
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
    finally:
        session.close()
        try:
            root.destroy()
        except tk.TclError:
            pass
