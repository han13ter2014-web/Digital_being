"""
P0 Regression Tests: Death and Life

Tests for the death risk system:
1. "100 cycles of life without false death" - agent learns, grows, checkpoints created, is_alive() == True
2. "After death, will doesn't tick but process exits gracefully" - inject corruption → death_risk.is_alive=False → autonomous_tick stops → runner exits cleanly
"""

import pytest
import tempfile
import os
import asyncio
from unittest.mock import Mock, patch, MagicMock

from src.core.agent import DigitalBeing, AgentDeadSignal
from src.core.death_risk import DeathCause, create_death_risk_engine
from src.core.agent_runner import AgentRunner
from src.core.event_bus import EventBus


@pytest.fixture
def temp_checkpoint_dir():
    """Временная директория для чекпоинтов.
    
    Патчит data_path в всех модулях, которые его используют.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        import src.core.paths as paths_module
        import src.core.checkpoint_serializer as serializer_module
        import src.core.agent_runner as runner_module
        import src.core.agent as agent_module
        import src.core.buffered_logger as logger_module
        
        original_data_path = paths_module.data_path
        
        def mock_data_path(subdir: str = "") -> str:
            if subdir == "checkpoints":
                return tmpdir
            return original_data_path(subdir)
        
        # Патчим во всех модулях
        paths_module.data_path = mock_data_path
        serializer_module.data_path = mock_data_path
        runner_module.data_path = mock_data_path
        agent_module.data_path = mock_data_path
        logger_module.data_path = mock_data_path
        
        yield tmpdir
        
        # Восстанавливаем
        paths_module.data_path = original_data_path
        serializer_module.data_path = original_data_path
        runner_module.data_path = original_data_path
        agent_module.data_path = original_data_path
        logger_module.data_path = original_data_path


class TestDeathLifeRegression:
    """Регрессионные тесты для системы смерти и жизни (P0)."""

    def test_100_cycles_no_false_death(self, temp_checkpoint_dir):
        """
        P0.5 Test 1: 100 циклов жизни без ложной смерти.
        
        Агент учится, растёт, чекпоинты создаются, is_alive() == True.
        Используем упрощённый цикл для скорости теста.
        """
        agent = DigitalBeing("TestAgent")
        
        assert agent.is_alive() is True
        assert agent.death_risk.is_alive is True
        
        # Упрощаем: только autonomous_tick + save_state (без полного perceive/think/act/evolve)
        # save_state вызывается каждые 10 циклов через SIM_CONFIG.CHECKPOINT_INTERVAL
        # но autonomous_tick не инкрементирует cycle_count (это делает evolve)
        # Поэтому вызываем save_state вручную каждые 10 итераций
        for cycle in range(100):
            report = agent.autonomous_tick()
            
            assert agent.is_alive(), f"False death at cycle {cycle}"
            assert agent.death_risk.is_alive, f"False death at cycle {cycle}: death_risk"
            
            # Save checkpoint every 10 cycles (simulating CHECKPOINT_INTERVAL)
            if cycle % 10 == 0:
                agent.cycle_count = cycle  # simulate cycle progression
                agent.save_state()
                checkpoint_files = [f for f in os.listdir(temp_checkpoint_dir) 
                                  if f.startswith("TestAgent_cycle_")]
                assert len(checkpoint_files) > 0, f"No checkpoint at cycle {cycle}"
        
        assert agent.is_alive() is True
        assert agent.death_risk.is_alive is True

    def test_death_stops_tick_gracefully(self, temp_checkpoint_dir):
        """
        P0.5 Test 2: После смерти воля не тикает, процесс корректно завершается.
        """
        agent = DigitalBeing("TestAgentDeath")
        
        agent.death_risk.inject_corruption(1.0, "cognitive")
        
        with pytest.raises(AgentDeadSignal) as exc_info:
            agent.autonomous_tick()
        
        assert exc_info.value.cause is not None
        assert exc_info.value.legacy is not None
        assert 'cause_of_death' in exc_info.value.legacy
        
        assert agent.is_alive() is False
        assert agent.death_risk.is_alive is False

    @pytest.mark.asyncio
    async def test_runner_graceful_shutdown_on_death(self, temp_checkpoint_dir):
        """
        P0.5 Test 3: Runner gracefully shuts down when agent dies.
        """
        agent = DigitalBeing("TestAgentRunner")
        
        bus = Mock(spec=EventBus)
        bus.publish_sync = Mock()
        bus.publish = Mock(return_value=asyncio.Future())
        bus.publish.return_value.set_result(None)
        
        runner = AgentRunner(agent, bus)
        
        # Need to call start() to initialize _pending_user_messages
        await runner.start()
        
        agent.death_risk.inject_corruption(1.0, "cognitive")
        
        try:
            await runner._one_iteration()
        except AgentDeadSignal:
            pass
        
        assert runner._stop_requested is True or not runner._running

    def test_checkpoint_file_corruption_detected(self, temp_checkpoint_dir):
        """
        P0.5 Test 4: Реальная коррупция ФАЙЛА чекпоинта детектируется.
        """
        agent = DigitalBeing("TestAgentCorrupt")
        agent.save_state()
        
        checkpoint_files = [f for f in os.listdir(temp_checkpoint_dir) 
                          if f.startswith("TestAgentCorrupt_cycle_")]
        assert len(checkpoint_files) > 0
        checkpoint_path = os.path.join(temp_checkpoint_dir, checkpoint_files[0])
        
        with open(checkpoint_path, 'w') as f:
            f.write("{ this is not valid json }")
        
        verification = agent.death_risk.verify_checkpoint_file_integrity(checkpoint_path)
        assert verification['file_corrupted'] is True

    def test_structural_drift_not_corruption(self, temp_checkpoint_dir):
        """
        P0.5 Test 5: Структурный дрифт (обучение/рост) НЕ считается коррупцией.
        
        Проверяем, что verify_latest_checkpoint возвращает structural_drift с drift info,
        а не corrupted=True.
        """
        agent = DigitalBeing("TestAgentDrift")
        
        # Создаём первый чекпоинт
        cp1 = agent.death_risk.force_checkpoint()
        integrity_at_cp1 = agent.death_risk.integrity.compute_overall_integrity()
        
        # Имитируем изменение состояния (увеличиваем intelligence)
        agent.intelligence = 10
        agent.cycle_count = 5
        
        # Создаём второй чекпоинт с другим состоянием
        cp2 = agent.death_risk.force_checkpoint()
        
        verification = agent.death_risk.integrity.verify_latest_checkpoint()
        
        # Не должно быть corrupted (это был нормальный рост)
        assert verification.get('corrupted') is False, f"Growth incorrectly marked as corruption: {verification}"
        assert 'structural_drift' in verification
        # Проверяем, что есть информация о дрифте
        drift = verification['structural_drift']
        assert 'integrity_drift' in drift
        print(f"Drift info: {drift}")

    def test_legacy_is_alive_fallback(self, temp_checkpoint_dir):
        """
        P0.5 Test 6: Fallback к _legacy_is_alive когда death_risk не инициализирован.
        
        Примечание: energy setter клампит к [0, max_energy], поэтому energy < 0 невозможно.
        Старая логика energy < 0 была для pre-energy_subsystem версий.
        """
        agent = DigitalBeing("TestAgentLegacy")
        delattr(agent, 'death_risk')
        
        assert agent.is_alive() is True
        assert agent._legacy_is_alive() is True
        
        # max_cycles limit работает
        agent.max_cycles = 10
        agent.cycle_count = 10
        assert agent._legacy_is_alive() is False
        
        agent.cycle_count = 9
        assert agent._legacy_is_alive() is True
        
        # energy == 0 — не смерть (агент просто замедляется)
        agent.energy = 0
        agent.cycle_count = 0
        agent.max_cycles = 0
        assert agent._legacy_is_alive() is True
        
        # energy > 0 — жив
        agent.energy = 50
        assert agent._legacy_is_alive() is True


class TestCheckpointVerification:
    """Тесты верификации чекпоинтов (P0.3)."""

    def test_verify_before_apply(self, temp_checkpoint_dir):
        """При загрузке чекпоинта должна происходить верификация файла."""
        agent = DigitalBeing("TestAgentVerify")
        agent.cycle_count = 0
        agent.save_state()
        
        checkpoint_files = [f for f in os.listdir(temp_checkpoint_dir) 
                          if f.startswith("TestAgentVerify_cycle_")]
        checkpoint_path = os.path.join(temp_checkpoint_dir, checkpoint_files[0])
        
        with open(checkpoint_path, 'w') as f:
            f.write("corrupted data")
        
        from src.core.checkpoint_serializer import CheckpointCorruptedError
        with pytest.raises(CheckpointCorruptedError):
            agent.load_state(checkpoint_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])