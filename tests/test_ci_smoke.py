"""Minimal cross-platform import smoke check for GitHub Actions."""


def test_core_public_imports():
    from src.core.agent import DigitalBeing
    from src.core.effector_port import EffectorPort, EffectorRequest, EffectorResult
    from src.core.subsystem_base import PluginRegistry, Subsystem

    assert DigitalBeing and EffectorPort and EffectorRequest and EffectorResult
    assert Subsystem and PluginRegistry
