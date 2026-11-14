"""Console-script entry point сохраняет аргументы командной строки."""

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
