"""Выбор старой жизни: без догадок, только реальные данные профиля."""

import pytest

from src.app.bootstrap import RecoveryRequiredError
from src.app.legacy_profile import legacy_lives
from src.app.life_choice import describe_life, resolve_startup_name


def _write_life(root, name, cycle, payload=None):
    import json

    checkpoints = root / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    path = checkpoints / f"{name}_cycle_{cycle}.json"
    path.write_text(
        json.dumps(payload or {"name": name, "cycle_count": cycle}), encoding="utf-8"
    )
    return path


def test_legacy_lives_lists_names_by_cycles(tmp_path):
    _write_life(tmp_path, "Alpha", 28)
    _write_life(tmp_path, "Малютка", 494)
    _write_life(tmp_path, "Малютка", 484)
    lives = legacy_lives(tmp_path)
    assert [item["name"] for item in lives] == ["Малютка", "Alpha"]
    assert lives[0]["cycles"] == 494
    assert lives[0]["checkpoints"] == 2


def test_describe_life_is_human_readable(tmp_path):
    _write_life(tmp_path, "Малютка", 494)
    text = describe_life(legacy_lives(tmp_path)[0])
    assert text.startswith("Малютка — 494 цикла")
    assert "снимков: 1" in text


def test_resolve_with_single_life_needs_no_question(tmp_path):
    _write_life(tmp_path, "Одна", 5)
    assert (
        resolve_startup_name(
            data_root=str(tmp_path),
            default_name="Alpha",
            interactive=True,
            ask=lambda lives: pytest.fail("не должен спрашивать"),
        )
        == "Одна"
    )


def test_resolve_asks_when_several_lives(tmp_path):
    _write_life(tmp_path, "Alpha", 28)
    _write_life(tmp_path, "Малютка", 494)
    asked = {}

    def ask(lives):
        asked["names"] = [item["name"] for item in lives]
        return "Малютка"

    chosen = resolve_startup_name(
        data_root=str(tmp_path), default_name="Alpha", interactive=True, ask=ask
    )
    assert chosen == "Малютка"
    assert asked["names"] == ["Малютка", "Alpha"]


def test_resolve_without_window_stops_but_keeps_data(tmp_path):
    _write_life(tmp_path, "Alpha", 28)
    _write_life(tmp_path, "Малютка", 494)
    with pytest.raises(RecoveryRequiredError):
        resolve_startup_name(
            data_root=str(tmp_path), default_name="Alpha", interactive=False
        )
    assert (tmp_path / "checkpoints" / "Малютка_cycle_494.json").exists()


def test_resolve_rejects_unknown_choice(tmp_path):
    _write_life(tmp_path, "Alpha", 28)
    _write_life(tmp_path, "Малютка", 494)
    with pytest.raises(RecoveryRequiredError):
        resolve_startup_name(
            data_root=str(tmp_path),
            default_name="Alpha",
            interactive=True,
            ask=lambda lives: "Чужая",
        )


def test_corrupt_pointer_is_not_hidden_by_chooser(tmp_path):
    _write_life(tmp_path, "Alpha", 28)
    _write_life(tmp_path, "Малютка", 494)
    (tmp_path / "active_profile.json").write_text("{битый", encoding="utf-8")
    with pytest.raises(RecoveryRequiredError):
        resolve_startup_name(
            data_root=str(tmp_path),
            default_name="Alpha",
            interactive=True,
            ask=lambda lives: pytest.fail("повреждённый указатель нельзя обходить"),
        )


def test_explicit_name_skips_pointer(tmp_path):
    _write_life(tmp_path, "Alpha", 28)
    assert (
        resolve_startup_name(
            name="Alpha",
            data_root=str(tmp_path),
            default_name="X",
            interactive=True,
        )
        == "Alpha"
    )


def test_build_runtime_writes_pointer_immediately(tmp_path, monkeypatch):
    """Следующий запуск не должен снова искать жизнь по имени."""
    import json
    import main
    from src.app.paths import setup_environment

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    args = main.parse_args(["--ui", "headless", "--name", "Alpha", "--new"])
    runtime = main.build_runtime(args, env)

    payload = json.loads((tmp_path / "active_profile.json").read_text(encoding="utf-8"))
    assert payload["name"] == "Alpha"
    assert payload["life_id"] == runtime.agent.life_id


def test_second_writer_on_selected_profile_is_rejected(tmp_path, monkeypatch):
    import main
    import pytest
    from src.app.paths import setup_environment
    from src.core.subsystem_base import PluginRegistry

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    args = main.parse_args(["--ui", "headless"])
    PluginRegistry.reset_global()
    runtimes = []
    try:
        first = main.build_runtime(args, env)
        runtimes.append(first)
        assert first.runner.save_now()
        with pytest.raises(RuntimeError, match="уже используется"):
            second = main.build_runtime(args, env)
            runtimes.append(second)
    finally:
        for runtime in runtimes:
            lock = getattr(runtime, "profile_lock", None)
            if lock is not None:
                lock.release()
            runtime.agent.plugin_registry.teardown_all()
        PluginRegistry.reset_global()


def test_build_runtime_releases_profile_lock_when_setup_fails(tmp_path, monkeypatch):
    import main
    import src.app.profile_lock as profile_lock_module
    from src.app.paths import setup_environment
    from src.core.subsystem_base import PluginRegistry

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    args = main.parse_args(["--ui", "headless", "--name", "Alpha", "--new"])
    created_locks = []
    real_lock = profile_lock_module.ProfileWriterLock

    def tracked_lock(profile_dir):
        lock = real_lock(profile_dir)
        created_locks.append(lock)
        return lock

    def fail_controller(*_args):
        raise RuntimeError("injected post-lock setup failure")

    monkeypatch.setattr(profile_lock_module, "ProfileWriterLock", tracked_lock)
    monkeypatch.setattr("src.app.life_controller.LifeController", fail_controller)
    PluginRegistry.reset_global()
    try:
        with pytest.raises(RuntimeError, match="injected post-lock setup failure"):
            main.build_runtime(args, env)

        assert len(created_locks) == 1
        assert not created_locks[0].acquired
    finally:
        for lock in created_locks:
            lock.release()
        PluginRegistry.reset_global()
