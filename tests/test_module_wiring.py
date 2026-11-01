"""Целостность подключения модулей (программистская приёмка).

1. Каждый модуль под src/ импортируется (нет битых/циклических импортов).
2. Живая сборка рантайма через main.build_runtime: все подсистемы из
   SUBSYSTEM_SPECS действительно прикреплены, шина и user_interaction
   прошиты так, как ожидает UI и AgentRunner.
3. Фасады DigitalBeing делегируют в живые подсистемы.
4. Деградация без naming_dialogue не роняет живые двери.
"""

import importlib
import inspect
import pkgutil
from unittest.mock import Mock

import pytest

import src
from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.event_bus import EventBus
from src.core.subsystems.naming_dialogue import NamingDialogue


def _collect_src_modules():
    for mod in pkgutil.walk_packages(src.__path__, prefix="src."):
        if mod.ispkg:
            continue
        yield mod.name


def test_all_src_modules_import():
    """Ни один модуль не должен падать при импорте."""
    failures = []
    for name in _collect_src_modules():
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 — собираем все причины
            failures.append(f"{name}: {exc!r}")
    assert not failures, "Битые импорты:\n" + "\n".join(failures)


class _WiringRuntime:
    """Headless-сборка настоящего рантайма (та же, что у main.py)."""

    def __init__(self, name):
        from src.app.paths import setup_environment
        from main import parse_args, build_runtime

        self.env = setup_environment(console=True)
        args = parse_args(["--name", name, "--ui", "headless"])
        self.runtime = build_runtime(args, self.env)

    def __enter__(self):
        return self.runtime

    def __exit__(self, *exc):
        runtime = self.runtime
        runtime.request_shutdown()
        runtime.wait(timeout=20)
        return False


def test_subsystem_specs_all_attached():
    """Каждая подсистема из SUBSYSTEM_SPECS есть на живом агенте."""
    with _WiringRuntime("WiringSpecs") as runtime:
        agent = runtime.agent
        missing = [
            attr for attr, _factory, _post, _prio in DigitalBeing.SUBSYSTEM_SPECS
            if not hasattr(agent, attr)
        ]
        assert not missing, f"Не прикреплены: {missing}"
        # Вне декларации, но обязательные для диалогового контура:
        for attr in (
            "user_interaction", "long_term_memory", "user_model",
            "mental_models", "_open_questions_manager",
        ):
            assert hasattr(agent, attr), attr


def test_runtime_bus_wiring():
    """Шина: подписки раннера, user_interaction у диалоговых подсистем."""
    with _WiringRuntime("WiringBus") as runtime:
        agent, bus, runner = runtime.agent, runtime.bus, runtime.runner

        subscribed = set(bus._subscribers.keys())
        expected = {
            "user_message", "user_command", "pause_requested",
            "resume_requested", "shutdown_requested", "save_requested",
            "speed_changed", "step_requested",
        }
        missing = expected - subscribed
        assert not missing, f"Раннер не подписан: {missing}"

        ui = agent.user_interaction
        assert ui._bus is bus, "user_interaction не привязан к шине"
        for attr in ("naming_dialogue", "proactive_communication", "mind_dream"):
            subsystem = getattr(agent, attr)
            assert subsystem.user_interaction is ui, (
                f"{attr} держит чужой user_interaction"
            )
        assert runner.agent is agent
        assert runtime.window is None  # headless


def test_dialogue_facades_delegate_to_live_subsystems(monkeypatch):
    """Фасады агента работают на настоящих подсистемах, не на заглушках."""
    import random as _random

    monkeypatch.setattr(_random, "random", lambda: 0.99)  # без 30% ветки
    with _WiringRuntime("WiringFacade") as runtime:
        agent = runtime.agent
        agent.start_naming_dialogue(cycle=0)
        assert agent.naming_dialogue.phase == "awaiting_name"

        result = agent.propose_name("Мирка", cycle=1)
        assert result["status"] == "accepted"
        assert agent.name == "Мирка"
        assert agent.user_interaction.agent_name == "Мирка"

        agent.thinking._synthesize_complex_question = Mock()
        agent.synthesize_complex_question(
            "глиф и тумелость", {"что такое глиф": "знак"}
        )
        agent.thinking._synthesize_complex_question.assert_called_once_with(
            "глиф и тумелость", {"что такое глиф": "знак"}
        )


@pytest.mark.asyncio
async def test_runner_degrades_without_naming_dialogue():
    """Нет подсистемы именования — двери живут, фасад честно отказывает."""
    agent = DigitalBeing(name="WiringNoNaming")
    del agent.naming_dialogue

    assert agent.propose_name("Х", cycle=1) == {"status": "no_naming_dialogue"}
    assert agent.start_naming_dialogue() == {"status": "no_naming_dialogue"}

    runner = AgentRunner.__new__(AgentRunner)
    runner.name = agent.name
    runner.agent = agent
    runner.bus = EventBus()
    assert await runner._handle_naming_phase(None, "Пусть тебя зовут Х") is False


def test_runner_hint_uses_public_contract_only():
    """Гейт именования знает все перехватываемые фазы NamingDialogue
    (PHASE_NONE сознательно не упоминается: неизвестная фаза — провал
    сквозь гейт) и зовёт публичные методы диалога, а не внутренние поля."""
    phases = {
        NamingDialogue.PHASE_AWAITING_NAME,
        NamingDialogue.PHASE_CONSIDERING,
        NamingDialogue.PHASE_COMPLETED,
        NamingDialogue.PHASE_RENAMING_PENDING,
    }
    runner_source = inspect.getsource(AgentRunner._handle_naming_phase)
    for phase in phases:
        assert f'"{phase}"' in runner_source, phase
    dialogue_source = inspect.getsource(AgentRunner)
    for method in (
        "confirm_rename", "cancel_rename", "accept_alternative",
        "decline_alternative", "classify_confirmation",
    ):
        assert method in dialogue_source, method
