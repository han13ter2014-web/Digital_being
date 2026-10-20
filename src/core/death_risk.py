"""
Риск смерти — необратимость потери структуры.
Смерть = checkpoint corruption (необратимая потеря когнитивной структуры).
"""

import numpy as np
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
from src.core.buffered_logger import get_logger

logger = get_logger()


class DeathCause(Enum):
    STRUCTURAL_COLLAPSE = "structural_collapse"
    CHECKPOINT_CORRUPTION = "checkpoint_corruption"
    COGNITIVE_FRAGMENTATION = "cognitive_fragmentation"
    METABOLIC_FAILURE = "metabolic_failure"
    EXISTENTIAL_VOID = "existential_void"


@dataclass
class Checkpoint:
    timestamp: float
    step: int
    structural_hash: str
    cognitive_state_hash: str
    memory_hash: str
    personality_hash: str
    integrity_score: float
    metadata: Dict = field(default_factory=dict)
    
    def verify(self, current_agent) -> Dict:
        current = current_agent.capture_structural_state()
        return {
            'structural_match': current['structural_hash'] == self.structural_hash,
            'cognitive_match': current['cognitive_state_hash'] == self.cognitive_state_hash,
            'memory_match': current['memory_hash'] == self.memory_hash,
            'personality_match': current['personality_hash'] == self.personality_hash,
            'integrity_drift': self.integrity_score - current['integrity_score'],
            'corrupted': False
        }


@dataclass
class StructuralDamage:
    timestamp: float
    damage_type: str
    severity: float
    affected_component: str
    description: str
    repaired: bool = False
    repair_timestamp: Optional[float] = None


class StructuralIntegrity:
    def __init__(self, agent):
        self.agent = agent
        self.cognitive_coherence = 1.0
        self.memory_consistency = 1.0
        self.value_stability = 1.0
        self.metabolic_viability = 1.0
        self.social_coherence = 1.0
        self.damage_log: List[StructuralDamage] = []
        self.critical_threshold = 0.2
        self.warning_threshold = 0.5
        self.repair_threshold = 0.7
        self.corruption_accumulator = 0.0
        self.corruption_rate = 0.0001
        self.checkpoints: List[Checkpoint] = []
        self.checkpoint_interval = 100
        self.max_checkpoints = 50
        self.last_checkpoint_step = 0
        logger.log("[DEATH_RISK] Structural Integrity initialized")
    
    def compute_overall_integrity(self) -> float:
        components = [
            self.cognitive_coherence,
            self.memory_consistency,
            self.value_stability,
            self.metabolic_viability,
            self.social_coherence
        ]
        return float(np.prod(components) ** (1.0 / len(components)))
    
    def step(self, dt: float = 1.0):
        self.corruption_accumulator += self.corruption_rate * dt
        decay = self.corruption_accumulator * 0.01
        self.cognitive_coherence = max(0.0, self.cognitive_coherence - decay)
        self.memory_consistency = max(0.0, self.memory_consistency - decay * 0.5)
        self.value_stability = max(0.0, self.value_stability - decay * 0.3)
        
        if hasattr(self.agent, 'interoception'):
            ic = self.agent.interoception
            mito_health = ic.state.mitochondrial_health
            self.metabolic_viability = np.clip(mito_health / 1.5, 0.0, 1.0)
        
        if hasattr(self.agent, 'social_cell'):
            sc = self.agent.social_cell
            if sc.agent_models:
                avg_precision = np.mean([m.model_precision for m in sc.agent_models.values()])
                self.social_coherence = avg_precision
        
        self._maybe_checkpoint()
        
        if self.compute_overall_integrity() > self.repair_threshold:
            self._auto_repair(dt)
        
        return self.get_status()
    
    def _maybe_checkpoint(self):
        current_step = getattr(self.agent, 'cycle_count', 0)
        if current_step - self.last_checkpoint_step >= self.checkpoint_interval:
            self.create_checkpoint()
            self.last_checkpoint_step = current_step
    
    def create_checkpoint(self) -> Checkpoint:
        state = self.agent.capture_structural_state()
        cp = Checkpoint(
            timestamp=time.time(),
            step=getattr(self.agent, 'cycle_count', 0),
            structural_hash=state['structural_hash'],
            cognitive_state_hash=state['cognitive_state_hash'],
            memory_hash=state['memory_hash'],
            personality_hash=state['personality_hash'],
            integrity_score=self.compute_overall_integrity(),
            metadata={
                'energy': self.agent.energy,
                'intelligence': self.agent.intelligence,
                'goals_count': len(self.agent.goals),
                'beliefs_count': len(getattr(self.agent, 'beliefs', {}))
            }
        )
        self.checkpoints.append(cp)
        if len(self.checkpoints) > self.max_checkpoints:
            self.checkpoints.pop(0)
        logger.log(f"[DEATH_RISK] Checkpoint created at step {cp.step}, integrity={cp.integrity_score:.3f}")
        return cp
    
    def verify_latest_checkpoint(self) -> Dict:
        if not self.checkpoints:
            return {'verified': False, 'reason': 'no_checkpoints'}
        latest = self.checkpoints[-1]
        verification = latest.verify(self.agent)
        any_mismatch = not (verification['structural_match'] and 
                           verification['cognitive_match'] and 
                           verification['memory_match'] and 
                           verification['personality_match'])
        verification['corrupted'] = any_mismatch
        verification['checkpoint_step'] = latest.step
        verification['integrity_at_checkpoint'] = latest.integrity_score
        verification['current_integrity'] = self.compute_overall_integrity()
        if any_mismatch:
            self.record_damage(
                damage_type="checkpoint_corruption",
                severity=0.3,
                affected_component="structural_verification",
                description=f"Checkpoint verification failed: structural={verification['structural_match']}, "
                           f"cognitive={verification['cognitive_match']}, "
                           f"memory={verification['memory_match']}, "
                           f"personality={verification['personality_match']}"
            )
            logger.log(f"[DEATH_RISK] CHECKPOINT CORRUPTION DETECTED at step {latest.step}")
        return verification
    
    def record_damage(self, damage_type: str, severity: float, 
                     affected_component: str, description: str):
        damage = StructuralDamage(
            timestamp=time.time(),
            damage_type=damage_type,
            severity=severity,
            affected_component=affected_component,
            description=description
        )
        self.damage_log.append(damage)
        self._apply_damage(damage)
        logger.log(f"[DEATH_RISK] Damage recorded: {damage_type} severity={severity:.2f} "
                   f"component={affected_component}")
    
    def _apply_damage(self, damage: StructuralDamage):
        severity = damage.severity
        if damage.affected_component == "cognitive":
            self.cognitive_coherence = max(0.0, self.cognitive_coherence - severity)
        elif damage.affected_component == "memory":
            self.memory_consistency = max(0.0, self.memory_consistency - severity)
        elif damage.affected_component == "values":
            self.value_stability = max(0.0, self.value_stability - severity)
        elif damage.affected_component == "metabolic":
            self.metabolic_viability = max(0.0, self.metabolic_viability - severity)
        elif damage.affected_component == "social":
            self.social_coherence = max(0.0, self.social_coherence - severity)
        elif damage.affected_component == "structural_verification":
            for attr in ['cognitive_coherence', 'memory_consistency', 
                        'value_stability', 'metabolic_viability', 'social_coherence']:
                current = getattr(self, attr)
                setattr(self, attr, max(0.0, current - severity * 0.5))
    
    def repair_damage(self, damage_index: int, repair_amount: float = 0.2) -> bool:
        if 0 <= damage_index < len(self.damage_log):
            damage = self.damage_log[damage_index]
            if not damage.repaired:
                damage.repaired = True
                damage.repair_timestamp = time.time()
                self._apply_repair(damage.affected_component, repair_amount)
                logger.log(f"[DEATH_RISK] Repaired damage {damage_index}: {damage.damage_type}")
                return True
        return False
    
    def _apply_repair(self, component: str, amount: float):
        if component == "cognitive":
            self.cognitive_coherence = min(1.0, self.cognitive_coherence + amount)
        elif component == "memory":
            self.memory_consistency = min(1.0, self.memory_consistency + amount)
        elif component == "values":
            self.value_stability = min(1.0, self.value_stability + amount)
        elif component == "metabolic":
            self.metabolic_viability = min(1.0, self.metabolic_viability + amount)
        elif component == "social":
            self.social_coherence = min(1.0, self.social_coherence + amount)
    
    def _auto_repair(self, dt: float):
        repair_rate = 0.001 * dt
        for attr in ['cognitive_coherence', 'memory_consistency', 
                    'value_stability', 'social_coherence']:
            current = getattr(self, attr)
            if current < 1.0:
                setattr(self, attr, min(1.0, current + repair_rate))
        self.corruption_accumulator = max(0.0, self.corruption_accumulator - repair_rate * 10)

    def manual_repair(self, intensity: float = 1.0) -> Dict:
        """Принудительное восстановление целостности (вызывается действием repair).
        
        Args:
            intensity: сила восстановления (1.0 = базовое)
            
        Returns:
            Словарь с изменениями по компонентам
        """
        repair_rate = 0.05 * intensity  # 5% за раз, намного сильнее auto_repair
        changes = {}
        for attr in ['cognitive_coherence', 'memory_consistency',
                    'value_stability', 'metabolic_viability', 'social_coherence']:
            current = getattr(self, attr)
            if current < 1.0:
                new_val = min(1.0, current + repair_rate)
                changes[attr] = new_val - current
                setattr(self, attr, new_val)
        
        # Также снижаем коррупцию
        old_corruption = self.corruption_accumulator
        self.corruption_accumulator = max(0.0, self.corruption_accumulator - repair_rate * 5)
        changes['corruption_accumulator'] = old_corruption - self.corruption_accumulator
        
        logger.log(f"[DEATH_RISK] Manual repair: {changes}")
        return changes
    
    def check_death(self) -> Optional[DeathCause]:
        integrity = self.compute_overall_integrity()
        if integrity < self.critical_threshold:
            return DeathCause.STRUCTURAL_COLLAPSE
        if self.checkpoints:
            verification = self.verify_latest_checkpoint()
            if verification.get('corrupted', False):
                return DeathCause.CHECKPOINT_CORRUPTION
        if self.cognitive_coherence < 0.1 and self.memory_consistency < 0.1:
            return DeathCause.COGNITIVE_FRAGMENTATION
        if self.metabolic_viability < 0.05:
            return DeathCause.METABOLIC_FAILURE
        if (len(self.agent.goals) == 0 and 
            self.value_stability < 0.1 and 
            getattr(self.agent, 'intelligence', 0) < 0.5):
            return DeathCause.EXISTENTIAL_VOID
        return None
    
    def get_status(self) -> Dict:
        integrity = self.compute_overall_integrity()
        return {
            'overall_integrity': integrity,
            'components': {
                'cognitive_coherence': self.cognitive_coherence,
                'memory_consistency': self.memory_consistency,
                'value_stability': self.value_stability,
                'metabolic_viability': self.metabolic_viability,
                'social_coherence': self.social_coherence
            },
            'thresholds': {
                'critical': self.critical_threshold,
                'warning': self.warning_threshold,
                'repair': self.repair_threshold
            },
            'corruption_accumulator': self.corruption_accumulator,
            'damage_count': len(self.damage_log),
            'unrepaired_damage': sum(1 for d in self.damage_log if not d.repaired),
            'checkpoints': len(self.checkpoints),
            'last_checkpoint_step': self.last_checkpoint_step,
            'death_risk': self._compute_death_risk(integrity),
            'status': self._integrity_status(integrity)
        }
    
    def _compute_death_risk(self, integrity: float) -> float:
        if integrity < self.critical_threshold:
            return 1.0
        elif integrity < self.warning_threshold:
            return (self.warning_threshold - integrity) / (self.warning_threshold - self.critical_threshold)
        else:
            return 0.0
    
    def _integrity_status(self, integrity: float) -> str:
        if integrity < self.critical_threshold:
            return "CRITICAL — DEATH IMMINENT"
        elif integrity < self.warning_threshold:
            return "WARNING — structural degradation"
        elif integrity < self.repair_threshold:
            return "DEGRADED — repair needed"
        else:
            return "HEALTHY"
    
    def attempt_recovery_from_checkpoint(self, checkpoint_index: int = -1) -> bool:
        if not self.checkpoints:
            return False
        cp = self.checkpoints[checkpoint_index]
        verification = cp.verify(self.agent)
        if not verification['corrupted']:
            self.agent.restore_from_checkpoint(cp)
            logger.log(f"[DEATH_RISK] Recovery from checkpoint step {cp.step} successful")
            return True
        else:
            logger.log(f"[DEATH_RISK] Checkpoint {cp.step} corrupted, cannot recover")
            return False
    
    def get_legacy_package(self) -> Dict:
        return {
            'final_integrity': self.compute_overall_integrity(),
            'total_lifetime_steps': getattr(self.agent, 'cycle_count', 0),
            'completed_goals': getattr(self.agent, 'completed_goals', 0),
            'intelligence_achieved': getattr(self.agent, 'intelligence', 0),
            'unique_beliefs': len(getattr(self.agent, 'beliefs', {})),
            'social_bonds': len(getattr(self.agent, 'social_cell', {}).agent_models) 
                           if hasattr(self.agent, 'social_cell') else 0,
            'checkpoints_survived': len(self.checkpoints),
            'damages_survived': len(self.damage_log),
            'cause_of_death': None,
            'structural_hash': self.agent.capture_structural_state()['structural_hash'],
            'personality_hash': self.agent.capture_structural_state()['personality_hash']
        }


class DeathRiskEngine:
    def __init__(self, agent):
        self.agent = agent
        self.integrity = StructuralIntegrity(agent)
        self.is_alive = True
        self.death_cause: Optional[DeathCause] = None
        self.death_timestamp: Optional[float] = None
        self.legacy_package: Optional[Dict] = None
        logger.log("[DEATH_RISK] Death Risk Engine initialized")
    
    def step(self, dt: float = 1.0) -> Dict:
        if not self.is_alive:
            return {'alive': False, 'cause': self.death_cause.value if self.death_cause else 'unknown'}
        integrity_status = self.integrity.step(dt)
        cause = self.integrity.check_death()
        if cause:
            self._die(cause)
        return {
            'alive': self.is_alive,
            'integrity': integrity_status,
            'death_cause': cause.value if cause else None
        }
    
    def _die(self, cause: DeathCause):
        self.is_alive = False
        self.death_cause = cause
        self.death_timestamp = time.time()
        self.legacy_package = self.integrity.get_legacy_package()
        self.legacy_package['cause_of_death'] = cause.value
        self.legacy_package['death_timestamp'] = self.death_timestamp
        logger.log(f"[DEATH_RISK] ═══ DEATH ═══")
        logger.log(f"[DEATH_RISK] Cause: {cause.value}")
        logger.log(f"[DEATH_RISK] Lifetime steps: {self.legacy_package['total_lifetime_steps']}")
        logger.log(f"[DEATH_RISK] Legacy prepared for inheritance")
    
    def record_external_damage(self, damage_type: str, severity: float, 
                              component: str, description: str):
        self.integrity.record_damage(damage_type, severity, component, description)
    
    def force_checkpoint(self) -> Checkpoint:
        return self.integrity.create_checkpoint()
    
    def verify_integrity(self) -> Dict:
        return self.integrity.verify_latest_checkpoint()
    
    def get_status(self) -> Dict:
        return {
            'alive': self.is_alive,
            'death_cause': self.death_cause.value if self.death_cause else None,
            'death_timestamp': self.death_timestamp,
            'integrity': self.integrity.get_status(),
            'legacy': self.legacy_package
        }
    
    def inject_corruption(self, amount: float, component: str = "cognitive"):
        self.integrity.record_damage(
            damage_type="external_corruption",
            severity=amount,
            affected_component=component,
            description=f"Injected corruption: {amount:.2f}"
        )


def create_death_risk_engine(agent) -> DeathRiskEngine:
    return DeathRiskEngine(agent)