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
