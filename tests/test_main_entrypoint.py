"""Console-script entry point сохраняет аргументы командной строки."""

import signal
from types import SimpleNamespace

import main


def test_console_entrypoint_forwards_cli_arguments(monkeypatch):
    captured = {}

    def fake_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(main, "main", fake_main)
    monkeypatch.setattr(
        main.sys,
        "argv",
        ["digital-being", "--ui", "console", "--interval", "5"],
    )

    assert main.run_long_living_agent() == 0
    assert captured["argv"] == ["--ui", "console", "--interval", "5"]


def test_headless_registers_available_termination_signals(monkeypatch):
    registered = {}
    monkeypatch.setattr(
        main.signal,
        "signal",
        lambda signum, handler: registered.setdefault(signum, handler),
    )
    runtime = SimpleNamespace(
        agent=SimpleNamespace(name="test"),
        start=lambda speed: None,
        finished=main.threading.Event(),
        request_shutdown=lambda: None,
        wait=lambda timeout: True,
        error=None,
    )
    runtime.finished.set()

    assert main.run_headless(runtime, SimpleNamespace(interval="5")) == 0

    expected = {signal.SIGINT, signal.SIGTERM}
    if hasattr(signal, "SIGBREAK"):
        expected.add(signal.SIGBREAK)
    assert expected <= registered.keys()


def test_console_shows_controls_hint_and_help_output(monkeypatch, capsys):
    answers = iter(["help", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    finished = main.threading.Event()
    agent = SimpleNamespace(
        name="test",
        cycle_count=0,
        intelligence=1,
        energy=100,
        mental_models=SimpleNamespace(concepts={}),
        get_goals_status=lambda: {"completed": 0, "total": 0},
        is_alive=lambda: True,
    )
    runtime = SimpleNamespace(
        agent=agent,
        bus=SimpleNamespace(_running=True),
        start=lambda speed: None,
        finished=finished,
        request_shutdown=finished.set,
        wait=lambda timeout: True,
        error=None,
    )

    assert main.run_console(runtime, SimpleNamespace(interval="5")) == 0

    output = capsys.readouterr().out
    assert "Доступные команды:" in output
    assert output.count("Управление консолью:") == 2
    assert "exit/q/quit" in output
    assert "Ctrl+C" in output
    assert "Ctrl+Shift+C" in output
