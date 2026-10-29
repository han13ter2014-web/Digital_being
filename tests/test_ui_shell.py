"""Каркас окна версии 1.0: страницы, «Сейчас» и карта жизни без mainloop.

Тест создаёт Tk в тестовом процессе (на Windows это работает), строит UI и
проверяет связку. Если дисплея нет — тест пропускается, а не падает.
"""

import pytest

tk = pytest.importorskip("tkinter")

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


def test_shell_builds_and_switches_pages(root):
    win = _window(root)
    assert set(win._pages) == {"now", "graph", "access", "dialog"}
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
        "now": {"activity": {"action": "create_draft", "target": "тишина",
                             "source": "activity", "reason": "интерес сохранился"},
                "loop": {"last_action": "play", "last_effect": True}},
        "intentions": {"waiting": []},
        "activities": {"creative": {"drafts": [
            {"id": "a" * 32, "theme": "тишина", "revision": 3, "status": "active",
             "sha256": "b" * 64}]}},
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
    win.push_life_status({"life": {"state": "alive"}, "now": {"activity": None},
                          "intentions": {"waiting": [{"target": "память"}]},
                          "activities": {}, "access": {},
                          "effector": {"available": False, "counts": {}}})
    win._poll_incoming()
    root.update()

    assert "память" in win._now_headline.cget("text")


def test_life_map_renders_nodes_and_shows_real_details(root):
    win = _window(root)
    win._show_page("graph")
    root.geometry("1100x700")
    root.deiconify()
    root.update()

    graph = {
        "nodes": [
            {"id": "concept:память", "kind": "concept", "label": "память",
             "weight": 0.62, "detail": {"уверенность": 0.62, "свидетельств": 3}},
            {"id": "concept:внимание", "kind": "concept", "label": "внимание",
             "weight": 0.4, "detail": {"уверенность": 0.4}},
            {"id": "value:autonomy", "kind": "value", "label": "autonomy",
             "weight": 0.5, "detail": {"ценность ядра": True}},
        ],
        "edges": [
            {"source": "concept:память", "target": "concept:внимание",
             "kind": "association", "label": "связано с", "weight": 0.7},
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
