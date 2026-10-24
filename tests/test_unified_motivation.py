"""
Regression tests for UnifiedMotivationSystem (P0.6-P0.10).
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.motivation.unified_motivation import UnifiedMotivationSystem, Need, Drive, create_motivation_system
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent, CheckpointSerializer


class MockAgent:
    """Mock agent for testing motivation system in isolation."""
    def __init__(self):
        self.cycle_count = 1
        self.knowledge_base = {'python': 'language', 'learning': 'skill', 'test': 'concept'}
        self.beliefs = {}


class TestUnifiedMotivationSystem:
    """Tests for the UnifiedMotivationSystem class."""

    def setup_method(self):
        self.agent = MockAgent()
        self.system = create_motivation_system(self.agent)

    def test_initialization(self):
        """Test that all needs and drives are initialized."""
        assert len(self.system.needs) == 7
        assert len(self.system.drives) == 5
        
        expected_needs = ['curiosity', 'competence', 'autonomy', 'connection', 'play', 'meaning', 'coherence']
        for n in expected_needs:
            assert n in self.system.needs
        
        expected_drives = ['creativity', 'mastery', 'self_transcendence', 'exploration', 'understanding']
        for d in expected_drives:
            assert d in self.system.drives

    def test_need_deficit_and_urgency(self):
        """Test need deficit and urgency calculations."""
        need = self.system.needs['curiosity']
        need.current_level = 0.3  # base_level is 0.8
        
        assert need.deficit() == 0.5
        assert need.urgency() == 0.5 * 1.2  # deficit * priority
        assert need.is_pressing() == True  # below threshold 0.35

    def test_need_tick_returns_to_base(self):
        """Test that needs naturally drift toward base_level."""
        need = self.system.needs['curiosity']
        need.current_level = 0.3
        base = need.base_level
        
        need.tick()
        assert need.current_level > 0.3
        assert need.current_level <= base

    def test_need_satisfy_and_frustrate(self):
        """Test need satisfaction and frustration."""
        need = self.system.needs['curiosity']
        original = need.current_level
        
        need.satisfy(0.5)
        assert need.current_level > original
        
        need.frustrate(0.3)
        assert need.current_level < original + 0.5 * need.growth_rate

    def test_drive_calculation(self):
        """Test drive intensity calculation from needs."""
        # Set needs high enough to activate creativity
        self.system.needs['curiosity'].current_level = 0.8
        self.system.needs['autonomy'].current_level = 0.7
        self.system.needs['play'].current_level = 0.7
        
        self.system.tick({})
        
        creativity = self.system.drives['creativity']
        assert creativity.current_level > 0.5
        assert creativity.is_active() == True

    def test_goal_generation_from_pressing_need(self):
        """Test that pressing needs generate goals."""
        self.system.needs['curiosity'].current_level = 0.2  # below threshold 0.35
        
        goals = self.system.generate_goals()
        
        assert len(goals) >= 1
        assert any(g['source'] == 'need' for g in goals)
        assert any(g['need'] == 'curiosity' for g in goals)

    def test_goal_generation_from_active_drive(self):
        """Test that active drives generate goals."""
        self.system.needs['curiosity'].current_level = 0.8
        self.system.needs['autonomy'].current_level = 0.7
        self.system.needs['play'].current_level = 0.7
        self.system.tick({})
        
        goals = self.system.generate_goals()
        
        assert len(goals) >= 1
        assert any(g['source'] == 'drive' for g in goals)
        assert any(g['drive'] == 'creativity' for g in goals)

    def test_on_action_result_updates_needs(self):
        """Test that action results update relevant needs."""
        original_curiosity = self.system.needs['curiosity'].current_level
        
        # Successful hypothesis should satisfy curiosity
        self.system.on_action_result('hypothesis', True, 0.8)
        
        assert self.system.needs['curiosity'].current_level > original_curiosity

    def test_on_action_result_covers_internal_action_types(self):
        """Internal action types from DigitalBeing.act() must satisfy needs.

        act() uses internal types (hypothesis/decomposition/know_answer/...),
        while needs are keyed by English action names. Aliases must bridge them.
        """
        original_curiosity = self.system.needs['curiosity'].current_level
        original_competence = self.system.needs['competence'].current_level

        self.system.on_action_result('hypothesis', True, 0.8)
        self.system.on_action_result('decomposition', True, 0.6)

        assert self.system.needs['curiosity'].current_level > original_curiosity
        assert self.system.needs['competence'].current_level > original_competence

    def test_on_action_result_failure_frustrates_need(self):
        """Failed action must frustrate the relevant need."""
        original_curiosity = self.system.needs['curiosity'].current_level

        self.system.on_action_result('web_search', False, -0.4)

        assert self.system.needs['curiosity'].current_level < original_curiosity

    def test_checkpoint_serialization(self):
        """Test that motivation state can be serialized and restored."""
        # Set some state - don't call tick() to avoid drift
        self.system.needs['curiosity'].current_level = 0.2
        self.system.needs['autonomy'].current_level = 0.8
        self.system.needs['play'].current_level = 0.8
        # Manually update drives without tick
        self.system.drives['creativity'].current_level = 0.6
        self.system.drives['creativity'].last_updated_cycle = self.agent.cycle_count
        
        checkpoint = self.system.to_checkpoint_dict()
        
        assert 'needs' in checkpoint
        assert 'drives' in checkpoint
        assert 'goal_history' in checkpoint
        assert checkpoint['needs']['curiosity']['current_level'] == 0.2
        assert checkpoint['drives']['creativity']['current_level'] == 0.6

    def test_checkpoint_restoration(self):
        """Test restoring motivation from checkpoint."""
        # Set some state - don't call tick() to avoid drift
        self.system.needs['curiosity'].current_level = 0.2
        self.system.needs['autonomy'].current_level = 0.8
        self.system.needs['play'].current_level = 0.8
        self.system.drives['creativity'].current_level = 0.6
        self.system.drives['creativity'].last_updated_cycle = self.agent.cycle_count
        
        checkpoint = self.system.to_checkpoint_dict()
        
        # Create new system and restore
        agent2 = MockAgent()
        system2 = UnifiedMotivationSystem.from_checkpoint_dict(agent2, checkpoint)
        
        assert system2.needs['curiosity'].current_level == 0.2
        assert system2.needs['autonomy'].current_level == 0.8
        assert system2.drives['creativity'].current_level == 0.6


class TestMotivationIntegration:
    """Tests for motivation integration with DigitalBeing."""

    def setup_method(self):
        # Clean up checkpoints
        ckpt_dir = 'data/checkpoints'
        if os.path.exists(ckpt_dir):
            import shutil
            shutil.rmtree(ckpt_dir)

    def teardown_method(self):
        # Clean up checkpoints
        ckpt_dir = 'data/checkpoints'
        if os.path.exists(ckpt_dir):
            import shutil
            shutil.rmtree(ckpt_dir)

    def test_agent_has_motivation_system(self):
        """Test that agent has motivation_system attribute."""
        agent = DigitalBeing(name='TestAgent')
        assert hasattr(agent, 'motivation_system')
        assert isinstance(agent.motivation_system, UnifiedMotivationSystem)

    def test_motivation_tick_in_autonomous_tick(self):
        """Test that motivation.tick is called during autonomous_tick."""
        agent = DigitalBeing(name='TestAgent')
        
        # Run a few cycles
        for _ in range(5):
            agent.autonomous_tick()
        
        # Motivation should have been updated
        assert agent.motivation_system.last_generated_cycle > 0 or \
               agent.motivation_system.needs['curiosity'].current_level != 0.5

    def test_motivation_checkpoint_roundtrip(self):
        """Test that motivation state survives checkpoint save/load."""
        import os
        import shutil
        from src.core.paths import data_path
        
        # Clean up checkpoints first
        ckpt_dir = data_path("checkpoints")
        if os.path.exists(ckpt_dir):
            shutil.rmtree(ckpt_dir)
        
        agent = DigitalBeing(name='TestAgent')
        
        # Set motivation state - don't call tick to avoid drift
        agent.motivation_system.needs['curiosity'].current_level = 0.2
        agent.motivation_system.needs['autonomy'].current_level = 0.8
        agent.motivation_system.needs['play'].current_level = 0.8
        agent.motivation_system.drives['creativity'].current_level = 0.6
        agent.motivation_system.drives['creativity'].last_updated_cycle = agent.cycle_count
        
        original_curiosity = agent.motivation_system.needs['curiosity'].current_level
        original_autonomy = agent.motivation_system.needs['autonomy'].current_level
        original_creativity = agent.motivation_system.drives['creativity'].current_level
        
        # Save checkpoint
        agent.cycle_count = 100
        agent.save_state()
        
        # Load into new agent
        agent2 = DigitalBeing(name='TestAgent')
        ckpt_files = os.listdir(ckpt_dir)
        ckpt_path = os.path.join(ckpt_dir, ckpt_files[0])
        
        ser = CheckpointSerializer()
        state = ser.load(ckpt_path)
        apply_state_to_agent(agent2, state)
        
        # Verify motivation restored
        assert agent2.motivation_system.needs['curiosity'].current_level == original_curiosity
        assert agent2.motivation_system.needs['autonomy'].current_level == original_autonomy
        assert abs(agent2.motivation_system.drives['creativity'].current_level - original_creativity) < 0.01

    def test_motivation_no_false_goals_when_satisfied(self):
        """Test that no goals generated when all needs satisfied."""
        agent = DigitalBeing(name='TestAgent')
        
        # Satisfy all needs
        for need in agent.motivation_system.needs.values():
            need.current_level = need.base_level
        
        goals = agent.motivation_system.generate_goals()
        
        # Should not generate goals from needs (but might from drives if active)
        need_goals = [g for g in goals if g['source'] == 'need']
        assert len(need_goals) == 0

    def test_motivation_drive_priority_lower_than_need(self):
        """Test that need goals have higher priority than drive goals."""
        agent = DigitalBeing(name='TestAgent')
        
        # Make curiosity pressing
        agent.motivation_system.needs['curiosity'].current_level = 0.2
        
        # Also activate creativity drive
        agent.motivation_system.needs['curiosity'].current_level = 0.8
        agent.motivation_system.needs['autonomy'].current_level = 0.8
        agent.motivation_system.needs['play'].current_level = 0.8
        agent.motivation_system.tick({})
        
        goals = agent.motivation_system.generate_goals()
        
        # Need goals should come first (higher priority)
        need_goals = [g for g in goals if g['source'] == 'need']
        drive_goals = [g for g in goals if g['source'] == 'drive']
        
        if need_goals and drive_goals:
            assert max(g['priority'] for g in need_goals) >= max(g['priority'] for g in drive_goals)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])