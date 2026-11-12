"""Чистый установочный профиль: нет чужого имени, памяти и разрешений."""

import json
from pathlib import Path

from src.app.bootstrap import create_agent, start_naming_dialogue
from src.app.life_choice import resolve_startup_name
from src.app.paths import setup_environment
from src.core.subsystems.naming_dialogue import NamingDialogue


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_default_profile_is_unnamed_and_contains_only_seed_knowledge(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("DIGITAL_BEING_NAME", raising=False)
    # В полном CI Settings уже импортирован с DIGITAL_BEING_NAME=TestAgent.
    # Воспроизводим свежий процесс без переменной, не меняя runtime-контур.
    from config.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "DEFAULT_AGENT_NAME", "Без имени")
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)

    import main

    name = resolve_startup_name(
        data_root=env.data_root,
        default_name=main._default_name(),
        interactive=False,
    )
    assert name == "Без имени"

    agent, report = create_agent(env, name)
    assert report["source"] == "new"
    assert agent.name == "Без имени"

    seed = json.loads(
        (PROJECT_ROOT / "data_bootstrap" / "knowledge_base.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(seed) == 47
    assert agent.knowledge_base == seed
    assert not (tmp_path / "knowledge_base.json").exists()
    assert not (tmp_path / "active_profile.json").exists()
    assert not (tmp_path / "access_settings.json").exists()

    result = start_naming_dialogue(agent)
    assert result["status"] == "initiated"
    assert agent.naming_dialogue.phase == NamingDialogue.PHASE_AWAITING_NAME
    greeting = agent.user_interaction.message_history[-1]["content"]
    assert "У меня пока нет имени." in greeting
    assert "Сейчас меня зовут 'Без имени'" not in greeting


def test_managed_knowledge_ignores_legacy_json_and_restores_from_snapshot(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    legacy = tmp_path / "knowledge_base.json"
    legacy.write_text(
        json.dumps({"посторонняя тема": "не должна попасть в managed Core"}),
        encoding="utf-8",
    )
    before = legacy.read_bytes()

    agent, _ = create_agent(env, "ManagedKB", new=True)
    assert "посторонняя тема" not in agent.knowledge_base
    agent.knowledge_base["собственная тема"] = "сохраняется только в снимке"
    agent._save_knowledge_base()
    assert legacy.read_bytes() == before

    agent.save_state()
    restored, report = create_agent(env, "ManagedKB", expected_life_id=agent.life_id)
    assert report["source"] == "checkpoint"
    assert restored.knowledge_base["собственная тема"] == "сохраняется только в снимке"
    assert "посторонняя тема" not in restored.knowledge_base
    assert legacy.read_bytes() == before


def test_immutable_resources_are_separate_from_live_data():
    from src.metrics.i18n import _DEFAULT_LOCALE_DIR

    assert Path(_DEFAULT_LOCALE_DIR) == PROJECT_ROOT / "data_bootstrap" / "i18n"
    assert (PROJECT_ROOT / "data_bootstrap" / "initial_knowledge.json").is_file()
    assert (PROJECT_ROOT / "data_bootstrap" / "i18n" / "ru.json").is_file()
    assert (PROJECT_ROOT / "data_bootstrap" / "i18n" / "en.json").is_file()
