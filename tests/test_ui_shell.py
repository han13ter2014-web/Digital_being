"""Каркас окна версии 1.0: страницы, «Сейчас» и карта жизни без mainloop.

Тест создаёт Tk в тестовом процессе (на Windows это работает), строит UI и
проверяет связку. Если дисплея нет — тест пропускается, а не падает.
"""

import pytest

tk = pytest.importorskip("tkinter")

from src.ui import diary_view  # noqa: E402
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


def test_shell_builds_and_switches_pages(root):
    win = _window(root)
    assert set(win._pages) == {
        "now",
        "graph",
        "diary",
        "activities",
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


class _FakeEvent:
    def __init__(self, x=0, y=0, delta=0):
        self.x = x
        self.y = y
        self.delta = delta


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
