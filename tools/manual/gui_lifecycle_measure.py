"""Настоящее Tk-окно и Runtime; временный профиль, автоматический запрос выхода."""

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--tray", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="db_gui_lifecycle_") as directory:
        os.environ["DIGITAL_BEING_DATA_DIR"] = directory
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        from config.simulation_config import LR_CONFIG
        LR_CONFIG.WEB_SEARCH_ENABLED = False
        from src.app.paths import setup_environment
        from src.app.bootstrap import latest_checkpoint
        from src.core.checkpoint_serializer import CheckpointSerializer
        from src.core.event_bus import Events
        from main import build_runtime, parse_args, run_gui, _start_tray

        env = setup_environment(chdir=False, console=False)
        options = parse_args(["--new", "--ui", "tray" if args.tray else "gui", "--interval", "step"])
        runtime = build_runtime(options, env)
        if args.tray:
            _start_tray(runtime)
        original = runtime.window._build_ui

        def build():
            original()
            runtime.window._root.after(600, lambda: runtime.bus.publish_sync(Events.USER_OPENED_CHAT, source="measure"))
            runtime.window._root.after(1200, runtime.request_shutdown)

        runtime.window._build_ui = build
        exit_code = run_gui(runtime, options)
        checkpoint = latest_checkpoint(runtime.agent.name, runtime.agent.checkpoint_dir)
        state = CheckpointSerializer().load(checkpoint) if checkpoint else None
        result = {"exit_code": exit_code, "runtime_finished": runtime.finished.is_set(),
                  "root_destroyed": runtime.window._root is None,
                  "saved_on_stop": runtime.saved_on_stop,
                  "checkpoint_readable": state is not None,
                  "tray_requested": args.tray,
                  "tray_created": hasattr(runtime, "tray"), "error": runtime.error}
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        logging.shutdown()
        if exit_code or not all(result[key] for key in ("runtime_finished", "root_destroyed", "saved_on_stop", "checkpoint_readable")):
            raise SystemExit(1)
