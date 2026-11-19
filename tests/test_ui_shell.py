"""Каркас окна версии 1.0: страницы, «Сейчас» и карта жизни без mainloop.

Тест создаёт Tk в тестовом процессе (на Windows это работает), строит UI и
проверяет связку. Если дисплея нет — тест пропускается, а не падает.
"""

import pytest

tk = pytest.importorskip("tkinter")

from src.core.emotional_state import EMOTIONS  # noqa: E402
from src.ui import diary_view, i18n, theme  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402


class RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, event, handler=None):
        return None

    def unsubscribe(self, *args, **kwargs):
        return None

    async def publish(self, *args, **kwargs):
        return None

    def publish_sync(self, event, data=None, **kwargs):
        self.published.append((event, data))


@pytest.fixture(autouse=True)
def russian_ui(monkeypatch):
    monkeypatch.setattr(i18n, "load_saved_language", lambda: "ru")
    monkeypatch.setattr(i18n, "save_language", lambda language: None)


@pytest.fixture()
def root():
    last_error = None
    # Tk на Windows изредка не находит tk.tcl при быстром пересоздании:
    # одна повторная попытка убирает случайный пропуск, не скрывая поломку.
    for _ in range(2):
        try:
            window = tk.Tk()
        except Exception as exc:  # pragma: no cover - зависит от окружения
            last_error = exc
            continue
        window.withdraw()
        yield window
        try:
            window.destroy()
        except Exception:
            pass
        return
    pytest.skip(f"нет дисплея: {last_error}")


def _window(root) -> MainWindow:
    win = MainWindow(RecordingBus(), "Alpha")
    win._root = root
    win._poll_running = True
    win._build_ui()
    return win


def _find_label(widget, needle: str):
    """Найти Label с подстрокой в дереве виджетов строки дневника."""
    for child in widget.winfo_children():
        if isinstance(child, tk.Label) and needle in str(child.cget("text")):
            return child
        found = _find_label(child, needle)
        if found is not None:
            return found
    return None


def _find_button(widget, caption: str):
    for child in widget.winfo_children():
        if isinstance(child, tk.Button) and str(child.cget("text")) == caption:
            return child
        found = _find_button(child, caption)
        if found is not None:
            return found
    return None


def test_shell_builds_and_switches_pages(root):
    win = _window(root)
    assert set(win._pages) == {
        "now",
        "graph",
        "diary",
        "activities",
        "tutor",
        "contacts",
        "access",
        "dialog",
    }
    assert win._current_page == "now"

    win._show_page("access")
    assert win._current_page == "access"

    # Виджеты, которых ждёт унаследованная логика, должны существовать.
    assert win._text is not None
    assert win._input_var is not None
    assert win._status_text is not None


def test_tutor_buttons_publish_commands_and_only_live_request_ids(root):
    from src.core.event_bus import Events

    bus = RecordingBus()
    win = MainWindow(bus, "Alpha")
    win._root = root
    win._poll_running = True
    win._build_ui()
    request_id = "request-0123456789abcdef"
    win._apply_life_data(
        {
            "tutor": {
                "available": True,
                "web_enabled": True,
                "approved_count": 1,
                "source_requests": [
                    {
                        "request_id": request_id,
                        "url": "https://example.test/lesson",
                        "reason": "Хочу проверить правило",
                        "cycle": 3,
                    }
                ],
            }
        }
    )
    root.update()

    win._tutor_url_var.set("https://example.test/manual")
    _find_button(win._pages["tutor"], "Разрешить").invoke()
    assert bus.published[-1] == (
        Events.USER_COMMAND,
        {"command": "tutor allow https://example.test/manual"},
    )
    _find_button(win._tutor_request_frame, "Разрешить и прочитать").invoke()
    assert bus.published[-1][1] == {"command": f"tutor approve_read {request_id}"}
    _find_button(win._tutor_request_frame, "Только разрешить").invoke()
    assert bus.published[-1][1] == {"command": f"tutor approve {request_id}"}
    _find_button(win._tutor_request_frame, "Отклонить").invoke()
    assert bus.published[-1][1] == {"command": f"tutor reject {request_id}"}

    before = len(bus.published)
    assert win._send_tutor_action("approve", "request-unknown") is False
    assert len(bus.published) == before
    assert "жираф" not in str(win._tutor_exercise.cget("text"))


def test_tutor_controls_respect_read_only_mode(root):
    bus = RecordingBus()
    win = MainWindow(bus, "Alpha", enabled_controls=False)
    win._root = root
    win._poll_running = True
    win._build_ui()
    win._tutor_url_var.set("https://example.test/manual")

    assert str(_find_button(win._pages["tutor"], "Разрешить").cget("state")) == (
        tk.DISABLED
    )
    assert win._send_tutor_action("allow") is False
    assert bus.published == []


def _external_snapshot(
    *, pending=False, can_manage=True, provider="manual", automation_state="idle"
):
    messages = [
        {
            "message_id": "inbound-1",
            "direction": "inbound",
            "claim_type": "external_ai_claim",
            "status": "quarantined",
            "text": "Внешняя реплика",
            "text_sha256": "a" * 64,
            "cycle": 4,
            "origin": "owner",
            "revision": 0,
            "error": None,
        }
    ]
    pending_draft = None
    if pending:
        pending_draft = {
            "message_id": "outbound-1",
            "direction": "outbound",
            "claim_type": "agent_draft",
            "status": "draft",
            "text": "Первый проект",
            "text_sha256": "b" * 64,
            "cycle": 5,
            "origin": "owner",
            "revision": 1,
            "error": None,
        }
        messages.append(pending_draft)
    return {
        "external_contacts": {
            "available": True,
            "can_manage": can_manage,
            "active": 1,
            "messages": len(messages),
            "pending_drafts": int(pending),
            "journal_limit": 12,
            "sessions": [
                {
                    "session_id": "session-1",
                    "profile_id": "profile-1",
                    "provider": provider,
                    "model": "rufp/default" if provider == "rufp" else None,
                    "external_id": "deepseek-web",
                    "topic": "тема",
                    "reason": "причина",
                    "status": "active",
                    "display_name": "DeepSeek",
                    "message_count": len(messages),
                    "messages": messages,
                    "pending_draft": pending_draft,
                    "automation": {
                        "state": automation_state,
                        "in_flight": automation_state in {"running", "pausing"},
                        "replies_sent": 1 if automation_state != "idle" else 0,
                        "max_replies": 3,
                        "tokens_used": 120 if automation_state != "idle" else 0,
                        "max_total_tokens": 1200,
                        "min_interval_sec": 2.0,
                        "usage": {},
                        "tokens_estimated": False,
                        "billing_receipts": [],
                        "last_error": None,
                        "automatic_resume": False,
                    },
                }
            ],
        }
    }


def test_external_buttons_publish_commands_and_only_live_session_ids(root):
    from src.core.event_bus import Events

    bus = RecordingBus()
    win = MainWindow(bus, "Alpha")
    win._root = root
    win._poll_running = True
    win._build_ui()
    win._apply_life_data(_external_snapshot())
    root.update()

    win._external_start_vars["name"].set("DeepSeek")
    win._external_start_vars["external_id"].set("deepseek-web")
    win._external_start_vars["topic"].set("тема")
    win._external_start_vars["reason"].set("причина")
    _find_button(win._pages["contacts"], "Создать сессию").invoke()
    assert bus.published[-1] == (
        Events.USER_COMMAND,
        {"command": "external start manual | DeepSeek | deepseek-web | тема | причина"},
    )

    win._external_ingest_text.insert("1.0", "  Привет | это карантин  ")
    _find_button(win._pages["contacts"], "Добавить в карантин").invoke()
    assert bus.published[-1][1] == {
        "command": "external ingest session-1 | Привет | это карантин"
    }
    _find_button(win._pages["contacts"], "Создать проект").invoke()
    assert bus.published[-1][1] == {"command": "external draft session-1"}

    win._apply_life_data(_external_snapshot(pending=True))
    root.update()
    win._external_edit_text.delete("1.0", tk.END)
    win._external_edit_text.insert("1.0", "Новая\nредакция | точно")
    _find_button(win._pages["contacts"], "Сохранить изменения").invoke()
    assert bus.published[-1][1] == {
        "command": "external edit session-1 | Новая\nредакция | точно"
    }
    _find_button(win._pages["contacts"], "Одобрить").invoke()
    assert bus.published[-1][1] == {"command": "external approve session-1"}

    approved = _external_snapshot(pending=True)
    approved["external_contacts"]["sessions"][0]["pending_draft"]["status"] = "approved"
    win._apply_life_data(approved)
    root.update()
    _find_button(win._pages["contacts"], "Отметить ручную передачу").invoke()
    assert bus.published[-1][1] == {"command": "external handoff session-1"}
    _find_button(win._pages["contacts"], "Остановить сессию").invoke()
    assert bus.published[-1][1] == {"command": "external stop session-1"}

    before = len(bus.published)
    win._external_selected_session_id = "session-unknown"
    assert win._send_external_action("stop") is False
    assert win._send_external_action("send") is False
    assert len(bus.published) == before


def test_external_automation_commands_limits_and_busy_state(root):
    bus = RecordingBus()
    win = MainWindow(bus, "Alpha")
    win._root = root
    win._poll_running = True
    win._build_ui()
    win._apply_life_data(_external_snapshot(provider="rufp"))
    root.update()

    win._external_start_vars["provider"].set("rufp")
    win._external_start_vars["name"].set("RUFP")
    win._external_start_vars["external_id"].set("rufp-api")
    win._external_start_vars["topic"].set("тема")
    win._external_start_vars["reason"].set("ограниченный диалог")
    win._external_start_vars["model"].set("rufp/default")
    _find_button(win._pages["contacts"], "Создать сессию").invoke()
    assert bus.published[-1][1] == {
        "command": (
            "external start rufp | RUFP | rufp-api | тема | "
            "ограниченный диалог | rufp/default"
        )
    }

    _find_button(win._pages["contacts"], "Запустить автообмен").invoke()
    assert bus.published[-1][1] == {"command": "external auto session-1 3 1200 2"}

    win._apply_life_data(
        _external_snapshot(provider="rufp", automation_state="running")
    )
    root.update()
    for caption in ("Запустить автообмен", "Добавить в карантин", "Удалить журнал"):
        assert str(_find_button(win._pages["contacts"], caption).cget("state")) == (
            tk.DISABLED
        )
    assert str(
        _find_button(win._pages["contacts"], "Остановить сессию").cget("state")
    ) == (tk.NORMAL)
    detail = str(win._external_session_detail.cget("text"))
    assert "rufp/default" in detail
    assert "реплики: 1/3" in detail
    assert "токены: 120/1200" in detail
    assert "запрос: выполняется" in detail
    _find_button(win._pages["contacts"], "Пауза").invoke()
    assert bus.published[-1][1] == {"command": "external pause session-1"}

    win._apply_life_data(_external_snapshot(provider="rufp", automation_state="paused"))
    root.update()
    _find_button(win._pages["contacts"], "Ручное вмешательство").invoke()
    assert bus.published[-1][1] == {"command": "external manual session-1"}
    _find_button(win._pages["contacts"], "Продолжить").invoke()
    assert bus.published[-1][1] == {"command": "external resume session-1"}

    win._apply_life_data(_external_snapshot(provider="rufp"))
    root.update()
    before = len(bus.published)
    for key, value in (
        ("max_replies", "0"),
        ("max_total_tokens", "256001"),
        ("min_interval_sec", "0"),
    ):
        original = win._external_auto_vars[key].get()
        win._external_auto_vars[key].set(value)
        assert win._send_external_action("auto") is False
        win._external_auto_vars[key].set(original)
    assert len(bus.published) == before


def test_external_controls_respect_read_only_mode_and_guest(root):
    bus = RecordingBus()
    win = MainWindow(bus, "Alpha", enabled_controls=False)
    win._root = root
    win._poll_running = True
    win._build_ui()
    win._apply_life_data(_external_snapshot(provider="rufp"))

    assert str(
        _find_button(win._pages["contacts"], "Создать сессию").cget("state")
    ) == (tk.DISABLED)
    assert win._send_external_action("start") is False
    assert win._send_external_action("draft") is False
    assert win._send_external_action("auto") is False

    guest = MainWindow(bus, "Alpha")
    guest._root = root
    guest._poll_running = True
    guest._build_ui()
    guest._apply_life_data(_external_snapshot(can_manage=False, provider="rufp"))
    assert (
        str(_find_button(guest._pages["contacts"], "Создать сессию").cget("state"))
        == tk.DISABLED
    )
    assert guest._send_external_action("ingest") is False
    assert guest._send_external_action("auto") is False
    assert bus.published == []


def test_external_editor_keeps_active_input_and_clear_requires_confirmation(
    root, monkeypatch
):
    from tkinter import messagebox

    bus = RecordingBus()
    win = MainWindow(bus, "Alpha")
    win._root = root
    win._poll_running = True
    win._build_ui()
    snapshot = _external_snapshot(pending=True)
    win._apply_life_data(snapshot)
    root.update()
    win._external_edit_text.focus_set()
    win._external_edit_text.delete("1.0", tk.END)
    win._external_edit_text.insert("1.0", "Моя незавершённая правка")

    win._apply_life_data(snapshot)
    root.update()
    assert win._external_edit_text.get("1.0", "end-1c") == "Моя незавершённая правка"

    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: False)
    _find_button(win._pages["contacts"], "Удалить журнал").invoke()
    assert bus.published == []
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)
    _find_button(win._pages["contacts"], "Удалить журнал").invoke()
    assert bus.published[-1][1] == {"command": "external clear session-1"}


def test_language_switch_retranslates_static_and_empty_states(root):
    win = _window(root)

    win._set_language("English")
    assert str(win._nav_buttons["diary"].cget("text")).endswith("Diary")
    assert win._diary_detail.cget("text") == "Select an entry on the left."
    assert "nodes: 0" in win._graph_counter.cget("text")

    win._set_language("中文")
    assert str(win._nav_buttons["diary"].cget("text")).endswith("日记")
    assert win._activity_detail.cget("text") == "请选择左侧的记录。"

    win._set_language("Русский")
    assert str(win._nav_buttons["diary"].cget("text")).endswith("Дневник")
    assert win._display_name_label.cget("text") == "Alpha"


def test_now_screen_renders_real_snapshot(root):
    win = _window(root)
    snapshot = {
        "life": {"state": "alive", "energy": 148.0, "fatigue": 0.2, "cycle": 12},
        "now": {
            "activity": {
                "action": "create_draft",
                "target": "тишина",
                "source": "activity",
                "reason": "интерес сохранился",
            },
            "loop": {"last_action": "play", "last_effect": True},
        },
        "intentions": {"waiting": []},
        "activities": {
            "creative": {
                "drafts": [
                    {
                        "id": "a" * 32,
                        "theme": "тишина",
                        "revision": 3,
                        "status": "active",
                        "sha256": "b" * 64,
                    }
                ]
            }
        },
        "preferences": {"create_draft": {"attempts": 2, "effects": 2, "failures": 0}},
        "access": {},
        "effector": {"available": True, "counts": {"queued": 1, "succeeded": 4}},
    }
    win._apply_life_data(snapshot)
    root.update()

    assert "черновик" in win._now_headline.cget("text").lower()
    assert "интерес сохранился" in win._now_choice.cget("text")
    assert "в очереди: 1" in win._effector_card.cget("text")
    assert "Не завершено" in win._effector_card.cget("text")


def test_now_screen_renders_full_emotion_palette_and_body(root):
    win = _window(root)
    levels = {name: (index % 10) / 10 for index, name in enumerate(EMOTIONS)}
    levels["joy"] = 0.64
    snapshot = {
        "life": {"state": "alive", "cycle": 12, "energy": 148.0},
        "emotions": {"levels": levels, "dominant": {"emotion": "joy"}},
        "body": {
            "fatigue": 0.2,
            "fatigue_level": "fresh",
            "atp": 87.5,
            "atp_ratio": 0.73,
            "glucose": 121.2,
            "mitochondrial_health": 0.91,
            "needs_rest": False,
        },
        "hardware": {
            "initialized": True,
            "observation": {
                "channels": {
                    "host_cpu": {
                        "status": "available",
                        "value": 95.0,
                        "unit": "percent",
                    },
                    "process_cpu": {"status": "unavailable", "value": None},
                    "data_storage": {"status": "stale", "value": 0.8},
                }
            },
            "latest_experience": {
                "own_load": {
                    "risk": 0.95,
                    "experienced": 0.85,
                    "expectedness": "familiar",
                }
            },
            "personal_profile": {
                "baseline": {},
                "adaptation": 0.4,
                "confidence": 0.8,
                "completed_episode_count": 3,
            },
            "shadow_strain": 0.85,
            "shadow_recovery": 0.0,
        },
    }
    win._apply_life_data(snapshot)
    root.update()

    assert set(win._now_emotion_labels) == set(EMOTIONS)
    assert win._now_emotion_labels["nostalgia"].cget("text") == "Ностальгия"
    assert win._now_emotion_values["joy"].cget("text") == "0.64"
    assert win._now_dominant.cget("text") == "Радость"
    body = win._now_body.cget("text")
    assert "АТФ: 87.50" in body
    assert "Глюкоза: 121.20" in body
    assert "Митохондрии: 0.91" in body
    hardware = win._now_hardware.cget("text")
    assert hardware != body
    assert "CPU среды: 95.0%" in hardware
    assert "CPU процесса: недоступно" in hardware
    assert "Свободное место data: устарело" in hardware
    assert "риск 95.0% · переживается 85.0%" in hardware
    assert "привычно, но риск сохраняется" in hardware
    assert "Личная норма: недостаточно опыта" in hardware

    win._set_language("English")
    root.update()
    assert win._now_emotion_labels["joy"].cget("text") == "Joy"
    assert win._now_emotion_values["joy"].cget("text") == "0.64"
    assert "ATP: 87.50" in win._now_body.cget("text")
    assert "Glucose: 121.20" in win._now_body.cget("text")
    hardware = win._now_hardware.cget("text")
    assert "Host CPU: 95.0%" in hardware
    assert "Process CPU: unavailable" in hardware
    assert "Free data storage: stale" in hardware
    assert "familiar, but the risk remains" in hardware
    assert "Personal baseline: insufficient experience" in hardware

    win._set_language("中文")
    root.update()
    assert win._now_emotion_labels["joy"].cget("text") == "喜悦"
    assert win._now_emotion_values["joy"].cget("text") == "0.64"
    hardware = win._now_hardware.cget("text")
    assert "主机 CPU: 95.0%" in hardware
    assert "进程 CPU: 不可用" in hardware
    assert "已经习惯，但风险依然存在" in hardware


def test_now_screen_has_honest_empty_emotion_state(root):
    win = _window(root)
    win._apply_life_data({})
    root.update()

    assert not win._now_emotion_labels
    assert win._now_emotion_empty.cget("text") == "Нет данных"
    assert win._now_dominant.cget("text") == "Нет данных"

    win._set_language("English")
    root.update()
    assert win._now_emotion_empty.cget("text") == "No data"
    assert win._now_dominant.cget("text") == "No data"


def test_status_snapshot_updates_details_and_pill(root):
    win = _window(root)
    win.push_status({"cycle": 42, "energy": 100, "life_state": "dormant"})
    win._poll_incoming()
    root.update()

    assert win._status_snapshot["cycle"] == 42
    assert win._state_pill.cget("text") == "спит"


def test_life_data_arrives_through_the_queue(root):
    win = _window(root)
    win.push_life_status(
        {
            "life": {"state": "alive"},
            "now": {"activity": None},
            "intentions": {"waiting": [{"target": "память"}]},
            "activities": {},
            "access": {},
            "effector": {"available": False, "counts": {}},
        }
    )
    win._poll_incoming()
    root.update()

    assert "память" in win._now_headline.cget("text")


def test_diary_and_activities_render_real_snapshot(root):
    win = _window(root)
    snapshot = {
        "diary": {
            "episodes": [
                {
                    "action": "play",
                    "args": {"target": "партия"},
                    "metadata": {"status": "performed"},
                }
            ]
        },
        "activities": {
            "creative": {
                "drafts": [{"theme": "тишина", "revision": 2, "status": "active"}]
            },
            "game": {"board": ["."] * 9, "turns": 0, "round": 1, "result": None},
        },
    }
    win._apply_life_data(snapshot)
    root.update()

    assert win._diary_titles() == ["партия «партия»"]
    assert win._activity_list.get(0) == "Черновик · тишина"
    assert win._activity_list.get(1) == "Партия · крестики-нолики"
    win._select_diary_index(0)
    root.update()
    assert "Статус: выполнено" in win._diary_detail.cget("text")
    win._activity_list.selection_set(1)
    win._on_activity_select()
    assert "Ходов: 0" in win._activity_detail.cget("text")


def test_diary_shows_explicit_empty_state(root):
    win = _window(root)
    win._apply_life_data({"diary": {"episodes": []}})
    root.update()

    assert win._diary_titles() == []
    texts = "\n".join(
        str(child.cget("text")) for child in win._diary_inner.winfo_children()
    )
    assert "Записей пока нет" in texts


def test_diary_folds_repeated_episodes_and_expands_on_click(root):
    win = _window(root)
    episodes = [
        {
            "action": "explore",
            "args": {"target": "туман"},
            "ok": True,
            "ts": f"2026-11-01T10:0{i}:00",
            "metadata": {"status": "performed"},
        }
        for i in range(4)
    ]
    win._apply_life_data({"diary": {"episodes": episodes}})
    root.update()

    # Серия из четырёх одинаковых записей подряд — одна строка с «×4».
    assert len(win._diary_titles()) == 1
    assert win._diary_rows_view[0]["count"] == 4

    win._select_diary_index(0)
    root.update()
    assert len(win._diary_titles()) == 4

    win._select_diary_index(2)
    root.update()
    assert "Статус: выполнено" in win._diary_detail.cget("text")
    assert win._diary_selected == 2


def test_diary_selection_has_amber_frame_and_preserves_action_stripe(root):
    win = _window(root)
    episodes = [
        {
            "action": "explore",
            "args": {"target": "память"},
            "ok": True,
            "ts": "2026-11-01T10:01:00",
            "metadata": {"status": "performed"},
        },
        {
            "action": "reflect",
            "ok": True,
            "ts": "2026-11-01T10:00:00",
            "metadata": {"status": "performed"},
        },
    ]
    win._apply_life_data({"diary": {"episodes": episodes}})
    first, second = win._diary_row_frames
    first_stripe = next(
        child
        for child in first.winfo_children()
        if getattr(child, "_preserve_bg", False)
    )
    second_stripe = next(
        child
        for child in second.winfo_children()
        if getattr(child, "_preserve_bg", False)
    )

    win._select_diary_index(0)
    assert first.cget("bg") == theme.SELECTION
    assert first.cget("highlightbackground") == theme.AMBER
    assert first_stripe.cget("bg") == theme.CYAN

    win._select_diary_index(1)
    assert first.cget("bg") == theme.BG_CENTER
    assert first.cget("highlightbackground") == theme.BORDER
    assert first_stripe.cget("bg") == theme.CYAN
    assert second.cget("bg") == theme.SELECTION
    assert second.cget("highlightbackground") == theme.AMBER
    assert second_stripe.cget("bg") == theme.VIOLET


def test_diary_keeps_rows_and_expansion_between_identical_snapshots(root):
    """Снимок жизни приходит дважды в секунду: без изменений список не трогаем."""
    win = _window(root)
    episodes = [
        {
            "action": "explore",
            "args": {"target": "туман"},
            "ok": True,
            "ts": f"2026-11-01T10:0{i}:00",
            "metadata": {"status": "performed"},
        }
        for i in range(4)
    ]
    win._apply_life_data({"diary": {"episodes": episodes}})
    win._select_diary_index(0)
    root.update()
    frames_before = list(win._diary_row_frames)

    win._apply_life_data({"diary": {"episodes": episodes}})
    root.update()

    assert len(win._diary_titles()) == 4
    assert win._diary_expanded == {diary_view.group_key(episodes[0])}
    assert win._diary_row_frames == frames_before


def test_diary_keeps_expansion_and_selection_when_series_grows(root):
    """Серия продолжилась новой записью: раскрытие и выбор не сбрасываются."""
    win = _window(root)
    episodes = [
        {
            "action": "explore",
            "args": {"target": "туман"},
            "ok": True,
            "ts": f"2026-11-01T10:0{i}:00",
            "metadata": {"status": "performed"},
        }
        for i in range(4)
    ]
    win._apply_life_data({"diary": {"episodes": episodes}})
    win._select_diary_index(0)
    win._select_diary_index(2)
    root.update()
    assert "Статус: выполнено" in win._diary_detail.cget("text")

    grown = [dict(episodes[0], ts="2026-11-01T10:04:00")] + episodes
    win._apply_life_data({"diary": {"episodes": grown}})
    root.update()

    assert len(win._diary_titles()) == 5
    assert win._diary_expanded == {diary_view.group_key(grown[0])}
    assert win._diary_rows_view[win._diary_selected]["episode"]["ts"] == (
        "2026-11-01T10:02:00"
    )
    assert "Статус: выполнено" in win._diary_detail.cget("text")


def test_diary_keeps_expansion_when_oldest_episode_leaves_window(root):
    """Окно истории сдвинулось тиком ядра: серия узнаётся по содержанию."""
    win = _window(root)
    episodes = [
        {
            "action": "explore",
            "args": {"target": "туман"},
            "ok": True,
            "ts": f"2026-11-01T10:0{i}:00",
            "metadata": {"status": "performed"},
        }
        for i in range(4)
    ]
    win._apply_life_data({"diary": {"episodes": episodes}})
    win._select_diary_index(0)
    root.update()

    shifted = episodes[1:] + [dict(episodes[0], ts="2026-11-01T10:04:00")]
    win._apply_life_data({"diary": {"episodes": shifted}})
    root.update()

    assert len(win._diary_titles()) == 4
    assert win._diary_expanded == {diary_view.group_key(shifted[0])}


def test_expanded_series_collapses_back_on_click(root):
    """«×N · свернуть» возвращает серию к одной строке с «×N · показать»."""
    win = _window(root)
    episodes = [
        {
            "action": "explore",
            "args": {"target": "туман"},
            "ok": True,
            "ts": f"2026-11-01T10:0{i}:00",
            "metadata": {"status": "performed"},
        }
        for i in range(4)
    ]
    win._apply_life_data({"diary": {"episodes": episodes}})
    win._select_diary_index(0)
    root.update()
    assert len(win._diary_titles()) == 4

    collapse = _find_label(win._diary_row_frames[0], "свернуть")
    assert collapse is not None
    collapse.event_generate("<Button-1>")
    root.update()

    assert len(win._diary_titles()) == 1
    assert win._diary_rows_view[0]["count"] == 4
    assert win._diary_expanded == set()
    assert _find_label(win._diary_row_frames[0], "показать") is not None

    win._select_diary_index(0)
    root.update()
    assert len(win._diary_titles()) == 4


def test_activity_list_keeps_selection_between_identical_snapshots(root):
    win = _window(root)
    snapshot = {
        "activities": {
            "creative": {
                "drafts": [{"theme": "тишина", "revision": 2, "status": "active"}]
            },
            "game": {"board": ["."] * 9, "turns": 0, "round": 1, "result": None},
        }
    }
    win._apply_life_data(snapshot)
    win._activity_list.selection_set(1)
    win._on_activity_select()
    assert "Ходов: 0" in win._activity_detail.cget("text")

    win._apply_life_data(snapshot)
    root.update()

    assert win._activity_list.curselection() == (1,)
    assert "Ходов: 0" in win._activity_detail.cget("text")


def test_activity_game_board_matches_recorded_cells_and_draft_hides_it(root):
    win = _window(root)
    snapshot = {
        "activities": {
            "creative": {
                "drafts": [{"theme": "тишина", "revision": 2, "status": "active"}]
            },
            "game": {
                "board": ["X", "O", "X", ".", "O", ".", "O", "X", "X"],
                "turns": 7,
                "round": 4,
                "result": "draw",
            },
        }
    }
    win._apply_life_data(snapshot)
    assert win._activity_list.itemcget(0, "fg") == theme.CYAN
    assert win._activity_list.itemcget(1, "fg") == theme.VIOLET

    win._activity_list.selection_set(1)
    win._on_activity_select()
    root.update()

    assert win._activity_board.winfo_manager() == "pack"
    assert [cell.cget("text") for cell in win._activity_board_cells] == [
        "X",
        "O",
        "X",
        "",
        "O",
        "",
        "O",
        "X",
        "X",
    ]
    assert win._activity_board_cells[0].cget("fg") == theme.CYAN
    assert win._activity_board_cells[1].cget("fg") == theme.VIOLET
    assert "Результат: ничья" in win._activity_detail.cget("text")
    assert "Поле:" not in win._activity_detail.cget("text")

    # Клик пользователя в режиме BROWSE сначала снимает прежнее выделение.
    win._activity_list.selection_clear(0, tk.END)
    win._activity_list.selection_set(0)
    win._on_activity_select()
    assert win._activity_list.curselection() == (0,)
    assert win._activity_board.winfo_manager() == ""
    assert "Что это:" in win._activity_detail.cget("text")


def test_activity_invalid_board_and_empty_state_do_not_fabricate_cells(root):
    win = _window(root)
    win._apply_life_data(
        {"activities": {"game": {"board": ["X", "O", "X"], "turns": 3, "round": 1}}}
    )
    win._activity_list.selection_set(0)
    win._on_activity_select()

    assert win._activity_board.winfo_manager() == ""
    assert all(cell.cget("text") == "" for cell in win._activity_board_cells)
    assert "Ходов: 3" in win._activity_detail.cget("text")

    win._apply_life_data({"activities": {}})
    assert str(win._activity_list.cget("state")) == tk.DISABLED
    assert win._activity_list.get(0) == "Занятий пока нет"
    assert win._activity_board.winfo_manager() == ""
    assert win._activity_detail.cget("text") == "Выберите запись слева."


class _FakeEvent:
    def __init__(self, x=0, y=0, delta=0):
        self.x = x
        self.y = y
        self.delta = delta


def test_dialog_composer_has_amber_action_and_word_wrap(root):
    win = _window(root)
    send = win._dialog_send_button

    assert send.cget("bg") == theme.AMBER
    assert send.cget("fg") == theme.BG_DEEP
    assert str(win._text.cget("wrap")) == tk.WORD
    assert win._input_entry.master is send.master
    assert send.master.pack_info()["side"] == "bottom"


def test_dialog_send_and_history_use_existing_message_flow(root):
    from src.core.event_bus import Events

    bus = RecordingBus()
    win = MainWindow(bus, "Alpha")
    win._root = root
    win._poll_running = True
    win._build_ui()
    win._input_var.set("  Расскажи о памяти  ")

    win._dialog_send_button.invoke()

    assert bus.published[-1] == (
        Events.USER_MESSAGE,
        {"text": "Расскажи о памяти"},
    )
    assert win._input_var.get() == ""
    assert win._history == ["Расскажи о памяти"]
    assert "Расскажи о памяти" in win._text.get("1.0", tk.END)

    win._on_history_up(None)
    assert win._input_var.get() == "Расскажи о памяти"
    win._on_history_down(None)
    assert win._input_var.get() == ""


def test_web_card_decodes_url_and_toggles_excerpt(root):
    win = _window(root)
    win._render_web_card(
        {
            "concept": "облако",
            "title": "Облако — Википедия",
            "extract": "О́блако — " + "длинный текст про облака " * 20,
            "url": "https://ru.wikipedia.org/wiki/%D0%9E%D0%B1%D0%BB%D0%B0%D0%BA%D0%BE",
        }
    )
    root.update()
    shown = win._text.get("1.0", tk.END)
    assert "ru.wikipedia.org" in shown
    assert "%D0" not in shown
    assert "развернуть статью ▾" in shown

    win._toggle_web_card("web0")
    root.update()
    assert "свернуть статью ▴" in win._text.get("1.0", tk.END)

    win._toggle_web_card("web0")
    root.update()
    assert "развернуть статью ▾" in win._text.get("1.0", tk.END)


def test_access_switches_reflect_real_state_and_publish_choice(root):
    bus = RecordingBus()
    win = MainWindow(bus, "Alpha")
    win._root = root
    win._poll_running = True
    win._build_ui()

    win._apply_life_data(
        {
            "access": {
                "network": {"enabled": True},
                "delamain": {"enabled": False},
                "effector": {"enabled": False},
            },
        }
    )
    assert win._access_vars["network"].get() is True
    assert win._access_vars["delamain"].get() is False

    # Переключатель не меняет Core напрямую: он отправляет решение агенту.
    win._access_vars["network"].set(False)
    win._on_access_toggle("network")
    event, data = bus.published[-1]
    assert data["command"] == "access network off"
    assert event == "user_command"

    # Клик по стилизованному переключателю ведёт себя как прежний чекбокс.
    win._toggle_access_var("delamain")
    assert win._access_vars["delamain"].get() is True
    event, data = bus.published[-1]
    assert data["command"] == "access delamain on"


def test_access_switch_visual_state_survives_language_change(root):
    win = _window(root)
    win._apply_life_data(
        {
            "access": {
                "network": {"enabled": True},
                "delamain": {"enabled": False},
                "effector": {"enabled": True},
                # «Присутствие» отсутствует в снимке: показываем выключенным.
            }
        }
    )
    network = win._access_switches["network"]
    delamain = win._access_switches["delamain"]
    assert win._access_status_labels["network"].cget("text") == "включено"
    assert win._access_status_labels["network"].cget("fg") == theme.CYAN
    assert network.itemcget(network.find_all()[0], "fill") == theme.AMBER
    assert win._access_status_labels["delamain"].cget("text") == "выключено"
    assert delamain.itemcget(delamain.find_all()[0], "fill") == theme.BORDER

    win._set_language("English")
    assert win._access_vars["network"].get() is True
    assert win._access_vars["delamain"].get() is False
    assert win._access_status_labels["network"].cget("text") == "enabled"
    assert win._access_status_labels["delamain"].cget("text") == "disabled"
    assert win._access_status_labels["presence"].cget("text") == "disabled"

    win._access_vars["network"].set(False)
    assert win._access_status_labels["network"].cget("text") == "disabled"
    assert network.itemcget(network.find_all()[0], "fill") == theme.BORDER
    assert str(win._status_text.cget("wrap")) == tk.WORD


def test_graph_counter_reports_hidden_service_records(root):
    win = _window(root)
    win._graph_counter.configure(text="")
    win._apply_graph_data(
        {
            "nodes": [
                {
                    "id": "concept:память",
                    "kind": "concept",
                    "label": "память",
                    "weight": 0.5,
                    "detail": {},
                },
            ],
            "edges": [],
            "truncated": False,
            "omitted": 0,
            "hidden_service": 4,
        }
    )
    text = win._graph_counter.cget("text")
    assert "служебных записей скрыто: 4" in text


def test_graph_detail_panel_fits_inside_the_window(root):
    """Панель подробностей и счётчик не должны уезжать за правый край."""
    win = _window(root)
    win._show_page("graph")
    root.geometry("1040x680")
    root.deiconify()
    root.update()
    win._apply_graph_data(
        {
            "nodes": [
                {
                    "id": "concept:память",
                    "kind": "concept",
                    "label": "память",
                    "weight": 0.5,
                    "detail": {},
                },
            ],
            "edges": [],
            "truncated": False,
            "hidden_service": 14,
        }
    )
    root.update()

    panel = win._graph_counter.master
    window_right = root.winfo_rootx() + root.winfo_width()
    assert panel.winfo_rootx() + panel.winfo_width() <= window_right
    # Счётчик переносится на две строки, а не обрезается.
    assert win._graph_counter.winfo_height() > 20


def test_life_map_renders_nodes_and_shows_real_details(root):
    win = _window(root)
    win._show_page("graph")
    root.geometry("1100x700")
    root.deiconify()
    root.update()

    graph = {
        "nodes": [
            {
                "id": "concept:память",
                "kind": "concept",
                "label": "память",
                "weight": 0.62,
                "detail": {"уверенность": 0.62, "свидетельств": 3},
            },
            {
                "id": "concept:внимание",
                "kind": "concept",
                "label": "внимание",
                "weight": 0.4,
                "detail": {"уверенность": 0.4},
            },
            {
                "id": "value:autonomy",
                "kind": "value",
                "label": "autonomy",
                "weight": 0.5,
                "detail": {"ценность ядра": True},
            },
        ],
        "edges": [
            {
                "source": "concept:память",
                "target": "concept:внимание",
                "kind": "association",
                "label": "связано с",
                "weight": 0.7,
            },
        ],
        "truncated": False,
        "omitted": 0,
    }
    win.push_graph(graph)
    win._poll_incoming()
    root.update()

    assert len(win._graph_tag_nodes) == 3
    assert "узлов: 3" in win._graph_counter.cget("text")
    assert "связей: 1" in win._graph_counter.cget("text")
    assert win._graph_canvas.find_withtag("graph-grid")
    assert win._graph_canvas.find_withtag("graph-orbits")
    assert win._graph_zoom_label.cget("text") == "100%"

    win._graph_selected = "concept:память"
    win._render_graph()
    assert win._graph_canvas.find_withtag("selected-node")
    assert win._graph_canvas.find_withtag("selected-edge")

    win._show_node_detail(graph["nodes"][0])
    detail = win._graph_detail.cget("text")
    assert "память" in detail
    assert "уверенность: 0.62" in detail
    assert "свидетельств: 3" in detail

    start = win._graph_positions["concept:память"]
    end = win._graph_positions["concept:внимание"]
    middle = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    edge = win._nearest_edge(*middle)
    assert edge is not None
    assert edge["kind"] == "association"

    win._show_edge_detail(edge)
    edge_text = win._graph_detail.cget("text")
    assert "основание" in edge_text
    assert "ментальной модели" in edge_text
    # Далеко от связей клик не выбирает ничего.
    assert win._nearest_edge(2, 2) is None


def test_life_map_says_when_there_is_nothing_yet(root):
    win = _window(root)
    win._show_page("graph")
    root.geometry("1100x700")
    root.deiconify()
    root.update()
    win.push_graph({"nodes": [], "edges": [], "truncated": False, "omitted": 0})
    win._poll_incoming()
    root.update()

    assert win._graph_tag_nodes == {}
    assert "узлов: 0" in win._graph_counter.cget("text")


def test_graph_filter_chips_narrow_the_map(root):
    win = _window(root)
    win._show_page("graph")
    root.geometry("1100x700")
    root.deiconify()
    root.update()
    graph = {
        "nodes": [
            {
                "id": "concept:память",
                "kind": "concept",
                "label": "память",
                "weight": 0.62,
                "detail": {},
            },
            {
                "id": "concept:внимание",
                "kind": "concept",
                "label": "внимание",
                "weight": 0.4,
                "detail": {},
            },
            {
                "id": "value:autonomy",
                "kind": "value",
                "label": "autonomy",
                "weight": 0.5,
                "detail": {},
            },
        ],
        "edges": [
            {
                "source": "concept:память",
                "target": "concept:внимание",
                "kind": "association",
                "label": "связано с",
                "weight": 0.7,
            },
        ],
        "truncated": False,
        "omitted": 0,
    }
    win.push_graph(graph)
    win._poll_incoming()
    root.update()

    win._toggle_graph_filter("value")
    root.update()
    ids = {node.get("id") for node in win._graph_tag_nodes.values()}
    assert ids == {"value:autonomy"}
    assert "узлов: 1 из 3" in win._graph_counter.cget("text")
    assert "фильтр: ценность ядра" in win._graph_counter.cget("text")

    win._on_graph_filter_all()
    root.update()
    assert len(win._graph_tag_nodes) == 3
    assert "узлов: 3" in win._graph_counter.cget("text")


def test_graph_wheel_zooms_within_bounds(root):
    win = _window(root)
    win._show_page("graph")
    root.update()

    for _ in range(30):
        win._on_graph_wheel(_FakeEvent(delta=-120))
    assert win._graph_zoom == pytest.approx(0.35)

    for _ in range(60):
        win._on_graph_wheel(_FakeEvent(delta=120))
    assert win._graph_zoom == pytest.approx(3.0)


def test_graph_drag_pans_without_selecting(root):
    win = _window(root)
    win._show_page("graph")
    root.geometry("1100x700")
    root.deiconify()
    root.update()
    win.push_graph(
        {
            "nodes": [
                {
                    "id": "concept:память",
                    "kind": "concept",
                    "label": "память",
                    "weight": 0.6,
                    "detail": {},
                }
            ],
            "edges": [],
            "truncated": False,
            "omitted": 0,
        }
    )
    win._poll_incoming()
    root.update()
    detail_before = win._graph_detail.cget("text")

    win._on_graph_press(_FakeEvent(x=100, y=100))
    win._on_graph_motion(_FakeEvent(x=160, y=90))
    win._on_graph_release(_FakeEvent(x=160, y=90))
    root.update()

    assert win._graph_offset != (0.0, 0.0)
    # Панорама — не выбор: карточка узла не открылась.
    assert win._graph_detail.cget("text") == detail_before
