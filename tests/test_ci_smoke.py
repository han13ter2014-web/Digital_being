"""Portable import smoke checks used by GitHub Actions."""


def test_core_and_dashboard_imports():
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
    from src.ui.web_dashboard import AIOHTTP_AVAILABLE, WebDashboard

    assert Subsystem and PluginRegistry
    assert all((
        GoalSubsystem, KnowledgeSubsystem, EnergySubsystem, SleepCycle,
        EmbodimentController, MortalityAwareness, WillRegistry, MindDream,
        SelfTermination, NurseryWatcher,
    ))
    assert WebDashboard and isinstance(AIOHTTP_AVAILABLE, bool)
