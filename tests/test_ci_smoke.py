"""Portable smoke checks used by GitHub Actions.

The base project must import without optional services. The web dashboard and
tray are exercised by their own tests when their optional dependencies exist;
they must not make the minimal core smoke test fail.
"""


def test_core_imports():
    from src.core.agent import DigitalBeing
    from src.core.subsystem_base import PluginRegistry, Subsystem
    from src.core.subsystems import (
        EmbodimentController,
        EnergySubsystem,
        GoalSubsystem,
        KnowledgeSubsystem,
        MindDream,
        MortalityAwareness,
        NurseryWatcher,
        SelfTermination,
        SleepCycle,
        WillRegistry,
    )

    assert Subsystem and PluginRegistry and DigitalBeing
    assert all((
        GoalSubsystem, KnowledgeSubsystem, EnergySubsystem, SleepCycle,
        EmbodimentController, MortalityAwareness, WillRegistry, MindDream,
        SelfTermination, NurseryWatcher,
    ))


def test_optional_dashboard_import_is_non_blocking():
    from src.ui import web_dashboard

    assert hasattr(web_dashboard, "WebDashboard")
    assert isinstance(web_dashboard.AIOHTTP_AVAILABLE, bool)
