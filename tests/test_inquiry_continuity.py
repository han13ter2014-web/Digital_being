"""После запуска вопрос продолжается, а не повторяет уже пройденную попытку."""

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent
from src.core.subsystem_base import PluginRegistry


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_inquiry_resumes_next_strategy_after_startup(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "InquiryLife", new=True)
        first.ask_user("как устроена память", source="self", max_explorations=3)
        stimulus = first._consume_open_question()
        first._record_open_question_exploration(stimulus, "Не знаю, пока нет свидетельств")
        expected = first._consume_open_question()
        assert "попытка 2/3" in expected
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, _ = create_agent(env, "InquiryLife")
        assert second._consume_open_question() == expected
        assert second._open_questions == first._open_questions
        second._record_open_question_exploration(expected, "Не знаю")
        third = second._consume_open_question()
        assert "попытка 3/3" in third
        second._record_open_question_exploration(third, "Не знаю")
        assert second._consume_open_question() is None
    finally:
        PluginRegistry.reset_global()


def test_reapplying_snapshot_does_not_duplicate_questions():
    from src.core.agent import DigitalBeing

    agent = DigitalBeing(name="InquiryReplay")
    agent.ask_user("почему", source="self")
    state = build_state_from_agent(agent)
    apply_state_to_agent(agent, state)
    apply_state_to_agent(agent, state)
    assert len(agent._open_questions) == 1
