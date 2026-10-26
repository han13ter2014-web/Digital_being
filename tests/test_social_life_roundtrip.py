"""Настоящий ответ меняет отношение один раз и переживает обычный запуск."""

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.evolve_pipeline import make_attachment_tick
from src.core.personal_continuity import capture_personal_state
from src.core.subsystem_base import PluginRegistry


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_real_question_answer_contact_and_restart(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "SocialLife", new=True)
        first.cycle_count = 100
        queued = first.user_interaction.ask_user("Что такое память?", cycle=100)
        assert queued["status"] == "queued"
        for cycle in range(20):
            make_attachment_tick()(first, cycle, {})
        assert not first.attachment._attachments
        result = first.thinking._process_user_answer("Память — способность сохранять и использовать опыт.")
        assert "Получен ответ" in result
        assert first.user_interaction.get_pending_question() is None
        relationship = first.attachment.get_or_create("user")
        assert relationship.interactions == 1
        assert len(relationship.history) == 1
        assert any(exp.get("source") == f"user:answer:{queued['id']}"
                   for node in first.mental_models.concepts.values() for exp in node.experiences)
        first.thinking._process_user_answer("Повтор ответа")
        assert relationship.interactions == 1
        personal = capture_personal_state(first)
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, report = create_agent(env, "SocialLife")
        assert report["source"] == "checkpoint"
        assert capture_personal_state(second) == personal
        restored = second.attachment.get_or_create("user")
        assert restored.interactions == 1
        second.thinking._process_user_answer("Повтор после запуска")
        assert restored.interactions == 1
        assert len(restored.history) == 1
    finally:
        PluginRegistry.reset_global()
