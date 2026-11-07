"""Чистый установочный профиль: нет чужого имени, памяти и разрешений."""

import json
from pathlib import Path

from src.app.bootstrap import create_agent, start_naming_dialogue
from src.app.life_choice import resolve_startup_name
from src.app.paths import setup_environment
from src.core.subsystems.naming_dialogue import NamingDialogue


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_default_profile_is_unnamed_and_contains_only_seed_knowledge(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv("DIGITAL_BEING_NAME", raising=False)
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)

    import main

    name = resolve_startup_name(
        data_root=env.data_root,
        default_name=main._default_name(),
        interactive=False,
    )
    assert name == "Без имени"
    assert name not in {"Афродита", "Тэсс", "Alpha"}

    agent, report = create_agent(env, name)
    assert report["source"] == "new"
    assert agent.name == "Без имени"

    seed = json.loads(
        (PROJECT_ROOT / "data_bootstrap" / "knowledge_base.json").read_text(
            encoding="utf-8"
        )
    )
    stored = json.loads((tmp_path / "knowledge_base.json").read_text(encoding="utf-8"))
    assert len(seed) == 47
    assert stored == seed
    assert not (tmp_path / "active_profile.json").exists()
    assert not (tmp_path / "access_settings.json").exists()

    result = start_naming_dialogue(agent)
    assert result["status"] == "initiated"
    assert agent.naming_dialogue.phase == NamingDialogue.PHASE_AWAITING_NAME
    greeting = agent.user_interaction.message_history[-1]["content"]
    assert "У меня пока нет имени." in greeting
    assert "Сейчас меня зовут 'Без имени'" not in greeting


def test_immutable_resources_are_separate_from_live_data():
    from src.metrics.i18n import _DEFAULT_LOCALE_DIR

    assert Path(_DEFAULT_LOCALE_DIR) == PROJECT_ROOT / "data_bootstrap" / "i18n"
    assert (PROJECT_ROOT / "data_bootstrap" / "initial_knowledge.json").is_file()
    assert (PROJECT_ROOT / "data_bootstrap" / "i18n" / "ru.json").is_file()
    assert (PROJECT_ROOT / "data_bootstrap" / "i18n" / "en.json").is_file()
