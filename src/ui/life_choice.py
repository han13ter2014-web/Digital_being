"""Окно выбора старой жизни. Показывает только реальные данные профиля."""

from __future__ import annotations

from src.app.life_choice import describe_life


def build_life_choice(lives):
    """Создать окно выбора, не запуская цикл событий.

    Возвращает ``(window, selected)``; после закрытия окна в ``selected``
    лежит имя выбранной жизни или None. Отделено от ``choose_life``, чтобы
    окно можно было показать в проверке интерфейса.
    """
    import tkinter as tk

    from src.ui import theme

    selected = {"name": None}
    window = tk.Tk()
    window.title("Digital Being — выбор жизни")
    window.configure(bg=theme.BG_DEEP)
    window.geometry("640x420")
    window.minsize(520, 340)
    try:
        window.attributes("-topmost", True)
    except tk.TclError:
        pass

    frame = tk.Frame(window, bg=theme.BG_DEEP, padx=24, pady=20)
    frame.pack(fill="both", expand=True)

    tk.Label(
        frame,
        text="Найдено несколько сохранённых жизней",
        bg=theme.BG_DEEP,
        fg=theme.TEXT,
        font=(theme.font_family(), 15, "bold"),
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        frame,
        text=(
            "Данные не изменены. Продолжить можно одну жизнь; остальные\n"
            "останутся на диске. Автоматический выбор здесь был бы догадкой."
        ),
        bg=theme.BG_DEEP,
        fg=theme.MUTED,
        font=(theme.font_family(), 10),
        justify="left",
        anchor="w",
    ).pack(fill="x", pady=(8, 16))

    listbox = tk.Listbox(
        frame,
        bg=theme.SURFACE,
        fg=theme.TEXT,
        selectbackground=theme.GLOW_CYAN,
        selectforeground=theme.TEXT,
        highlightthickness=1,
        highlightbackground=theme.BORDER,
        activestyle="none",
        font=(theme.font_family(), 10),
        height=min(8, max(3, len(lives))),
    )
    listbox.pack(fill="both", expand=True)
    for item in lives:
        listbox.insert("end", describe_life(item))
    listbox.selection_set(0)

    buttons = tk.Frame(frame, bg=theme.BG_DEEP)
    buttons.pack(fill="x", pady=(16, 0))

    def confirm(event=None):
        selection = listbox.curselection()
        if selection:
            selected["name"] = lives[int(selection[0])]["name"]
        window.destroy()

    def cancel(event=None):
        selected["name"] = None
        window.destroy()

    continue_button = tk.Button(
        buttons,
        text="Продолжить эту жизнь",
        command=confirm,
        bg=theme.GLOW_CYAN,
        fg=theme.TEXT,
        activebackground=theme.EDGE,
        activeforeground=theme.TEXT,
        relief=tk.FLAT,
        bd=0,
        padx=14,
        pady=6,
        font=(theme.font_family(), 10, "bold"),
    )
    continue_button.pack(side="right")
    cancel_button = tk.Button(
        buttons,
        text="Не сейчас",
        command=cancel,
        bg=theme.SURFACE,
        fg=theme.TEXT,
        activebackground=theme.BORDER,
        activeforeground=theme.TEXT,
        relief=tk.FLAT,
        bd=0,
        padx=14,
        pady=6,
        font=(theme.font_family(), 10),
    )
    cancel_button.pack(side="right", padx=(0, 8))
    listbox.bind("<Double-Button-1>", confirm)
    window.bind("<Return>", confirm)
    window.protocol("WM_DELETE_WINDOW", cancel)
    window.update_idletasks()
    window.focus_force()
    return window, selected


def choose_life(lives):
    """Вернуть имя выбранной жизни или None, если человек закрыл окно.

    Ничего не пишет на диск: решение сохранится только после успешного
    восстановления и первого сохранения.
    """
    window, selected = build_life_choice(lives)
    window.mainloop()
    return selected["name"]


__all__ = ["build_life_choice", "choose_life"]
