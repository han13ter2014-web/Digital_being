"""Ошибка восстановления видна и без консоли; никаких автоматических действий."""

import logging

logger = logging.getLogger(__name__)


def show_recovery_notice(message: str) -> bool:
    root = None
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Digital Being — восстановление остановлено", message, parent=root)
        return True
    except Exception as exc:
        logger.warning("Не удалось показать окно восстановления: %s", exc)
        return False
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
