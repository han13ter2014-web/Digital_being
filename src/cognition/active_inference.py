"""
Active Inference Engine — реализация принципа свободной энергии (Friston).

Агент минимизирует вариационную свободную энергию двумя путями:
1. PERCEPTION (восприятие): обновление убеждений о скрытых состояниях мира
2. ACTION (действие): выбор действий, минимизирующих ожидаемую свободную энергию
"""

import numpy as np
import random
from typing import Dict, List, Tuple
from dataclasses import dataclass, field
from collections import deque
from src.core.buffered_logger import get_logger

logger = get_logger()


# ============================================================
# CORE DATA STRUCTURES
# ============================================================

@dataclass
class HiddenState:
    """Скрытое состояние мира (latent variable)."""
    name: str
    dim: int = 1
    prior: np.ndarray = None
    posterior: np.ndarray = None
    transition: np.ndarray = None
    
    def __post_init__(self):
        if self.prior is None:
            self.prior = np.ones(self.dim) / self.dim
        if self.posterior is None:
            self.posterior = self.prior.copy()


@dataclass
class ObservationModality:
    """Модальность наблюдения (сенсорный канал)."""
    name: str
    dim: int
    # likelihood: {state_name: matrix[state_dim, obs_dim]}
    likelihood: Dict[str, np.ndarray] = field(default_factory=dict)
    preferences: np.ndarray = None
    
    def __post_init__(self):
        if self.preferences is None:
            self.preferences = np.zeros(self.dim)
    
    def get_likelihood(self, state_name: str, state_dim: int) -> np.ndarray:
        """Получает likelihood для конкретного состояния."""
        if state_name in self.likelihood:
            return self.likelihood[state_name]
        # Fallback: uniform
        return np.ones((state_dim, self.dim)) / self.dim


@dataclass
class Action:
    name: str
    transitions: Dict[str, np.ndarray] = field(default_factory=dict)
    cost: float = 1.0


# ============================================================
# GENERATIVE MODEL
# ============================================================

class GenerativeModel:
    def __init__(self, agent):
        self.agent = agent
        self.hidden_states: Dict[str, HiddenState] = {}
        self.observations: Dict[str, ObservationModality] = {}
        self.actions: Dict[str, Action] = {}
        self._build_model()
        logger.log(f"[ACTIVE_INFERENCE] Model: {len(self.hidden_states)} states, {len(self.observations)} modalities, {len(self.actions)} actions")
    
    def _build_model(self):
        self.hidden_states["topic_familiarity"] = HiddenState("topic_familiarity", 3, np.array([0.6, 0.3, 0.1]))
        self.hidden_states["user_intent"] = HiddenState("user_intent", 4, np.array([0.2, 0.4, 0.3, 0.1]))
        self.hidden_states["competence_level"] = HiddenState("competence_level", 3, np.array([0.3, 0.5, 0.2]))
        self.hidden_states["energy_reserve"] = HiddenState("energy_reserve", 3, np.array([0.2, 0.6, 0.2]))
        self.hidden_states["curiosity_drive"] = HiddenState("curiosity_drive", 3, np.array([0.2, 0.4, 0.4]))
        self.hidden_states["trust_level"] = HiddenState("trust_level", 3, np.array([0.3, 0.5, 0.2]))
        self.hidden_states["engagement"] = HiddenState("engagement", 3, np.array([0.2, 0.5, 0.3]))
        
        # NEW: Интероцептивные состояния
        self.hidden_states["fatigue_level"] = HiddenState("fatigue_level", 3, np.array([0.2, 0.6, 0.2]))
        self.hidden_states["atp_level"] = HiddenState("atp_level", 3, np.array([0.3, 0.5, 0.2]))
        self.hidden_states["mito_health"] = HiddenState("mito_health", 3, np.array([0.4, 0.4, 0.2]))
        
        # NEW: Социальные состояния
        self.hidden_states["social_trust"] = HiddenState("social_trust", 3, np.array([0.3, 0.5, 0.2]))
        self.hidden_states["social_precision"] = HiddenState("social_precision", 3, np.array([0.2, 0.6, 0.2]))
        
        # NEW: Структурная целостность
        self.hidden_states["structural_integrity"] = HiddenState("structural_integrity", 3, np.array([0.4, 0.5, 0.1]))
        
        # NEW: Субъективное время
        self.hidden_states["time_dilation"] = HiddenState("time_dilation", 3, np.array([0.2, 0.6, 0.2]))
        
        # OBSERVATION MODALITIES - likelihood per state [state_dim, obs_dim]
        # user_input_type: 5 categories (question, statement, command, answer, silence)
        self.observations["user_input_type"] = ObservationModality("user_input_type", 5, {
            "topic_familiarity": np.array([  # (3, 5)
                [0.4, 0.2, 0.1, 0.1, 0.2],
                [0.3, 0.3, 0.2, 0.2, 0.3],
                [0.1, 0.3, 0.4, 0.5, 0.3],
            ]),
            "user_intent": np.array([  # (4, 5)
                [0.5, 0.2, 0.1, 0.1, 0.1],
                [0.2, 0.3, 0.2, 0.2, 0.1],
                [0.1, 0.2, 0.3, 0.2, 0.2],
                [0.1, 0.1, 0.2, 0.4, 0.2],
            ]),
            "trust_level": np.array([  # (3, 5)
                [0.4, 0.3, 0.1, 0.1, 0.1],
                [0.2, 0.3, 0.2, 0.2, 0.1],
                [0.1, 0.2, 0.3, 0.2, 0.2],
            ]),
            "engagement": np.array([  # (3, 5)
                [0.4, 0.3, 0.1, 0.1, 0.1],
                [0.2, 0.3, 0.2, 0.2, 0.1],
                [0.1, 0.2, 0.3, 0.2, 0.2],
            ]),
        }, np.array([-1.0, -0.5, 0.0, 0.5, -0.2]))
        
        # thinking_outcome: 4 categories (success_known, success_learned, failure, decomposition)
        self.observations["thinking_outcome"] = ObservationModality("thinking_outcome", 4, {
            "topic_familiarity": np.array([  # (3, 4)
                [0.1, 0.2, 0.6, 0.1],
                [0.3, 0.4, 0.3, 0.0],
                [0.5, 0.3, 0.1, 0.1],
            ]),
            "competence_level": np.array([  # (3, 4)
                [0.1, 0.2, 0.6, 0.1],
                [0.3, 0.4, 0.3, 0.0],
                [0.5, 0.3, 0.1, 0.1],
            ]),
            "curiosity_drive": np.array([  # (3, 4)
                [0.1, 0.1, 0.2, 0.1],
                [0.2, 0.3, 0.5, 0.1],
                [0.6, 0.4, 0.3, 0.1],
            ]),
        }, np.array([1.0, 0.8, -1.0, 0.3]))
        
        # energy_level: 3 categories (low, medium, high)
        self.observations["energy_level"] = ObservationModality("energy_level", 3, {
            "energy_reserve": np.eye(3),  # (3, 3)
        }, np.array([-1.0, 0.0, 1.0]))
        
        # concept_confidence: 3 categories (low, medium, high)
        self.observations["concept_confidence"] = ObservationModality("concept_confidence", 3, {
            "competence_level": np.array([  # (3, 3)
                [0.6, 0.3, 0.1],
                [0.3, 0.5, 0.3],
                [0.1, 0.2, 0.6],
            ]),
        }, np.array([-0.5, 0.0, 1.0]))
        
        # social_feedback: 4 categories (positive, neutral, negative, teaching)
        self.observations["social_feedback"] = ObservationModality("social_feedback", 4, {
            "trust_level": np.array([  # (3, 4)
                [0.1, 0.4, 0.5, 0.0],
                [0.2, 0.5, 0.3, 0.0],
                [0.4, 0.4, 0.1, 0.1],
            ]),
            "engagement": np.array([  # (3, 4)
                [0.2, 0.2, 0.1, 0.1],
                [0.3, 0.4, 0.2, 0.1],
                [0.4, 0.3, 0.5, 0.2],
            ]),
        }, np.array([1.0, 0.0, -1.0, 0.5]))
        
        # NEW: Интероцепция — fatigue: 3 categories (low, medium, high)
        self.observations["interoception_fatigue"] = ObservationModality("interoception_fatigue", 3, {
            "fatigue_level": np.eye(3),
            "atp_level": np.array([
                [0.2, 0.5, 0.3],
                [0.1, 0.4, 0.5],
                [0.1, 0.3, 0.6],
            ]),
            "mito_health": np.array([
                [0.3, 0.4, 0.3],
                [0.2, 0.5, 0.3],
                [0.1, 0.3, 0.6],
            ]),
        }, np.array([1.0, 0.0, -1.0]))
        
        # NEW: Интероцепция — ATP: 3 categories (low, medium, high)
        self.observations["interoception_atp"] = ObservationModality("interoception_atp", 3, {
            "atp_level": np.eye(3),
            "fatigue_level": np.array([
                [0.6, 0.3, 0.1],
                [0.3, 0.5, 0.2],
                [0.1, 0.4, 0.5],
            ]),
        }, np.array([-1.0, 0.0, 1.0]))
        
        # NEW: Интероцепция — Mitochondrial Health: 3 categories
        self.observations["interoception_mito"] = ObservationModality("interoception_mito", 3, {
            "mito_health": np.eye(3),
            "fatigue_level": np.array([
                [0.6, 0.3, 0.1],
                [0.4, 0.4, 0.2],
                [0.2, 0.5, 0.3],
            ]),
        }, np.array([-0.5, 0.0, 1.0]))
        
        # NEW: Социальные наблюдения — предсказанная реакция
        self.observations["social_predicted_reaction"] = ObservationModality("social_predicted_reaction", 4, {
            "social_trust": np.array([
                [0.5, 0.3, 0.1, 0.1],
                [0.2, 0.5, 0.2, 0.1],
                [0.1, 0.2, 0.5, 0.2],
            ]),
            "social_precision": np.array([
                [0.4, 0.3, 0.2, 0.1],
                [0.2, 0.4, 0.3, 0.1],
                [0.1, 0.2, 0.4, 0.3],
            ]),
        }, np.array([1.0, 0.0, -1.0, 0.5]))  # trust, suspicion, betrayal, unknown
        
        # NEW: Социальные наблюдения — точность модели
        self.observations["social_model_precision"] = ObservationModality("social_model_precision", 3, {
            "social_precision": np.eye(3),
        }, np.array([-0.5, 0.0, 1.0]))
        
        # NEW: Структурная целостность
        self.observations["integrity_level"] = ObservationModality("integrity_level", 3, {
            "structural_integrity": np.eye(3),
            "energy_reserve": np.array([
                [0.5, 0.3, 0.2],
                [0.2, 0.5, 0.3],
                [0.1, 0.3, 0.6],
            ]),
        }, np.array([-1.0, 0.0, 1.0]))
        
        # NEW: Субъективное время — dilation
        self.observations["time_dilation_obs"] = ObservationModality("time_dilation_obs", 3, {
            "time_dilation": np.eye(3),
        }, np.array([-0.5, 0.0, 0.5]))
        
        # ACTIONS
        self.actions["think_known"] = Action("think_known", {
            "competence_level": np.array([[0.9, 0.1, 0.0], [0.0, 0.8, 0.2], [0.0, 0.1, 0.9]]),
            "topic_familiarity": np.array([[0.7, 0.3, 0.0], [0.0, 0.6, 0.4], [0.0, 0.0, 1.0]]),
        }, 2.0)
        self.actions["think_decompose"] = Action("think_decompose", {
            "topic_familiarity": np.array([[0.3, 0.6, 0.1], [0.0, 0.4, 0.6], [0.0, 0.2, 0.8]]),
            "curiosity_drive": np.array([[0.5, 0.4, 0.1], [0.1, 0.6, 0.3], [0.0, 0.3, 0.7]]),
        }, 4.0)
        self.actions["ask_user"] = Action("ask_user", {
            "topic_familiarity": np.array([[0.2, 0.5, 0.3], [0.0, 0.3, 0.7], [0.0, 0.1, 0.9]]),
            "trust_level": np.array([[0.6, 0.3, 0.1], [0.2, 0.6, 0.2], [0.1, 0.3, 0.6]]),
            "engagement": np.array([[0.3, 0.5, 0.2], [0.1, 0.4, 0.5], [0.0, 0.2, 0.8]]),
        }, 3.0)
        self.actions["synthesize"] = Action("synthesize", {
            "competence_level": np.array([[0.6, 0.4, 0.0], [0.1, 0.6, 0.3], [0.0, 0.2, 0.8]]),
            "topic_familiarity": np.array([[0.2, 0.5, 0.3], [0.0, 0.3, 0.7], [0.0, 0.0, 1.0]]),
        }, 5.0)
        self.actions["rest"] = Action("rest", {
            "energy_reserve": np.array([[0.3, 0.6, 0.1], [0.0, 0.4, 0.6], [0.0, 0.1, 0.9]]),
        }, 0.5)
        self.actions["explore"] = Action("explore", {
            "curiosity_drive": np.array([[0.4, 0.5, 0.1], [0.1, 0.5, 0.4], [0.0, 0.3, 0.7]]),
            "topic_familiarity": np.array([[0.5, 0.4, 0.1], [0.1, 0.5, 0.4], [0.0, 0.3, 0.7]]),
        }, 3.0)
        
        # NEW: Death Risk driven actions
        self.actions["repair"] = Action("repair", {
            "structural_integrity": np.array([[0.2, 0.5, 0.3], [0.0, 0.3, 0.7], [0.0, 0.1, 0.9]]),
            "energy_reserve": np.array([[0.3, 0.5, 0.2], [0.1, 0.4, 0.5], [0.0, 0.2, 0.8]]),
            "cognitive_coherence": np.array([[0.2, 0.4, 0.4], [0.0, 0.3, 0.7], [0.0, 0.1, 0.9]]),
        }, 8.0)
        
        self.actions["deep_rest"] = Action("deep_rest", {
            "fatigue_level": np.array([[0.1, 0.3, 0.6], [0.0, 0.2, 0.8], [0.0, 0.1, 0.9]]),
            "atp_level": np.array([[0.2, 0.5, 0.3], [0.0, 0.3, 0.7], [0.0, 0.1, 0.9]]),
            "mito_health": np.array([[0.2, 0.4, 0.4], [0.0, 0.3, 0.7], [0.0, 0.1, 0.9]]),
            "structural_integrity": np.array([[0.3, 0.4, 0.3], [0.1, 0.4, 0.5], [0.0, 0.2, 0.8]]),
        }, 5.0)
        
        self.actions["checkpoint_now"] = Action("checkpoint_now", {
            "structural_integrity": np.array([[0.4, 0.4, 0.2], [0.1, 0.4, 0.5], [0.0, 0.2, 0.8]]),
        }, 3.0)
    
    def update_preferences_from_agent(self):
        if not hasattr(self.agent, 'innate_values'):
            return
        v = self.agent.innate_values
        self.observations["thinking_outcome"].preferences[1] = 0.5 + v.get('curiosity', 0.5) * 0.5
        self.observations["thinking_outcome"].preferences[0] = 0.5 + v.get('learning', 0.5) * 0.5
        self.observations["social_feedback"].preferences[0] = 0.5 + v.get('connection', 0.5) * 0.5
        self.observations["energy_level"].preferences[2] = 1.0
        
        # NEW: Death Risk модуляция предпочтений (C-матрица)
        death_risk = getattr(self.agent, 'death_risk', None)
        if death_risk:
            integrity = death_risk.integrity.compute_overall_integrity()
            
            # integrity_level: 3 категории (low=0, medium=1, high=2)
            # При низкой целостности - сильнее предпочитаем высокую
            if integrity < 0.3:
                # Критическая: максимальное предпочтение восстановления
                self.observations["integrity_level"].preferences = np.array([-10.0, -2.0, 5.0])
            elif integrity < 0.5:
                # Опасная зона: сильно предпочитаем восстановление
                self.observations["integrity_level"].preferences = np.array([-5.0, 0.0, 3.0])
            elif integrity < 0.7:
                # Предупреждение: умеренное предпочтение
                self.observations["integrity_level"].preferences = np.array([-2.0, 0.0, 2.0])
            else:
                # Норма: базовое предпочтение
                self.observations["integrity_level"].preferences = np.array([-1.0, 0.0, 1.0])
            
            # Интероцепция: при низкой целостности - выше приоритет восстановления
            if integrity < 0.5:
                self.observations["interoception_fatigue"].preferences = np.array([3.0, 1.0, -2.0])  # предпочитаем низкую усталость
                self.observations["interoception_atp"].preferences = np.array([-3.0, 0.0, 3.0])  # высокий ATP
                self.observations["interoception_mito"].preferences = np.array([-2.0, 0.0, 2.0])  # здоровые митохондрии
            else:
                self.observations["interoception_fatigue"].preferences = np.array([1.0, 0.0, -1.0])
                self.observations["interoception_atp"].preferences = np.array([-1.0, 0.0, 1.0])
                self.observations["interoception_mito"].preferences = np.array([-0.5, 0.0, 1.0])
            
            # Социальные: при риске смерти снижаем доверие/исследование
            if integrity < 0.4:
                self.observations["social_predicted_reaction"].preferences = np.array([2.0, 0.0, -3.0, 0.0])  # избегаем betrayal
                self.observations["social_model_precision"].preferences = np.array([-1.0, 0.0, 2.0])  # точность модели


# ============================================================
# VARIATIONAL INFERENCE (PERCEPTION)
# ============================================================

class VariationalInference:
    def __init__(self, model: GenerativeModel):
        self.model = model
        self.free_energy_history = deque(maxlen=100)
    
    def update_beliefs(self, observations: Dict[str, int]) -> float:
        total_fe = 0.0
        for state_name, state in self.model.hidden_states.items():
            relevant_modalities = self._get_relevant_modalities(state_name)
            if not relevant_modalities:
                continue
            
            log_posterior = np.log(state.prior + 1e-10)
            for mod_name in relevant_modalities:
                if mod_name not in observations:
                    continue
                mod = self.model.observations[mod_name]
                obs_idx = observations[mod_name]
                # Use get_likelihood for state-specific matrix
                likelihood_matrix = mod.get_likelihood(state_name, state.dim)
                likelihood = likelihood_matrix[:, obs_idx] + 1e-10
                log_posterior += np.log(likelihood)
            
            posterior = np.exp(log_posterior - np.max(log_posterior))
            posterior = posterior / (posterior.sum() + 1e-10)
            
            alpha = 0.3
            state.posterior = (1 - alpha) * state.posterior + alpha * posterior
            
            kl = np.sum(state.posterior * (np.log(state.posterior + 1e-10) - np.log(state.prior + 1e-10)))
            expected_log_likelihood = 0.0
            for mod_name in relevant_modalities:
                if mod_name not in observations:
                    continue
                mod = self.model.observations[mod_name]
                obs_idx = observations[mod_name]
                likelihood_matrix = mod.get_likelihood(state_name, state.dim)
                expected_log_likelihood += np.sum(state.posterior * np.log(likelihood_matrix[:, obs_idx] + 1e-10))
            
            fe = kl - expected_log_likelihood
            total_fe += fe
        
        self.free_energy_history.append(total_fe)
        return total_fe
    
    def _get_relevant_modalities(self, state_name: str) -> List[str]:
        mapping = {
            "topic_familiarity": ["user_input_type", "thinking_outcome", "concept_confidence"],
            "user_intent": ["user_input_type"],
            "competence_level": ["thinking_outcome", "concept_confidence"],
            "energy_reserve": ["energy_level"],
            "curiosity_drive": ["thinking_outcome"],
            "trust_level": ["social_feedback", "user_input_type"],
            "engagement": ["user_input_type", "social_feedback"],
            # NEW states
            "fatigue_level": ["interoception_fatigue", "interoception_atp", "interoception_mito"],
            "atp_level": ["interoception_atp", "interoception_fatigue"],
            "mito_health": ["interoception_mito", "interoception_fatigue"],
            "social_trust": ["social_predicted_reaction", "social_feedback"],
            "social_precision": ["social_model_precision", "social_predicted_reaction"],
            "structural_integrity": ["integrity_level", "energy_level"],
            "time_dilation": ["time_dilation_obs"],
        }
        return mapping.get(state_name, [])
    
    def get_belief(self, state_name: str) -> np.ndarray:
        state = self.model.hidden_states.get(state_name)
        return state.posterior if state else np.array([1.0])
    
    def get_most_likely(self, state_name: str) -> Tuple[int, float]:
        belief = self.get_belief(state_name)
        idx = np.argmax(belief)
        return idx, belief[idx]
    
    def _entropy(self, dist: np.ndarray) -> float:
        dist = dist + 1e-10
        return -np.sum(dist * np.log(dist))


# ============================================================
# EXPECTED FREE ENERGY & ACTION SELECTION
# ============================================================

class ExpectedFreeEnergy:
    def __init__(self, model: GenerativeModel, inference: VariationalInference):
        self.model = model
        self.inference = inference
    
    def compute_G(self, action: Action, horizon: int = 1) -> Tuple[float, float, float]:
        beliefs = {name: state.posterior for name, state in self.model.hidden_states.items()}
        next_beliefs = self._predict_next_states(beliefs, action)
        expected_observations = self._predict_observations(next_beliefs)
        
        # Epistemic Value
        H_predicted = sum(self._entropy(pred) for pred in expected_observations.values())
        
        expected_H_conditional = 0.0
        for state_name, belief in next_beliefs.items():
            for mod_name in self.inference._get_relevant_modalities(state_name):
                mod = self.model.observations[mod_name]
                likelihood_matrix = mod.get_likelihood(state_name, len(belief))
                for s_idx, prob in enumerate(belief):
                    if prob > 0:
                        likelihood = likelihood_matrix[s_idx, :] + 1e-10
                        likelihood = likelihood / likelihood.sum()
                        expected_H_conditional += prob * self._entropy(likelihood)
        
        epistemic = H_predicted - expected_H_conditional
        
        # Pragmatic Value
        pragmatic = 0.0
        for mod_name, pred_dist in expected_observations.items():
            mod = self.model.observations[mod_name]
            pragmatic += np.sum(pred_dist * mod.preferences)
        
        cost = -action.cost * 0.1
        G_total = epistemic + pragmatic + cost
        
        return G_total, epistemic, pragmatic
    
    def _predict_next_states(self, beliefs: Dict, action: Action) -> Dict[str, np.ndarray]:
        next_beliefs = {}
        for state_name, belief in beliefs.items():
            if state_name in action.transitions:
                next_beliefs[state_name] = belief @ action.transitions[state_name]
            else:
                next_beliefs[state_name] = belief.copy()
        return next_beliefs
    
    def _predict_observations(self, beliefs: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        expected = {}
        for mod_name, mod in self.model.observations.items():
            relevant_states = [s for s in beliefs.keys() if mod_name in self.inference._get_relevant_modalities(s)]
            if not relevant_states:
                expected[mod_name] = np.ones(mod.dim) / mod.dim
                continue
            pred = np.zeros(mod.dim)
            for s_name in relevant_states:
                likelihood_matrix = mod.get_likelihood(s_name, len(beliefs[s_name]))
                pred += beliefs[s_name] @ likelihood_matrix
            pred = pred / len(relevant_states)
            expected[mod_name] = pred / (pred.sum() + 1e-10)
        return expected
    
    def _entropy(self, dist: np.ndarray) -> float:
        dist = dist + 1e-10
        return -np.sum(dist * np.log(dist))
    
    def select_action(self, available_actions: List[str] = None, temperature: float = 1.0) -> Tuple[str, Dict]:
        if available_actions is None:
            available_actions = list(self.model.actions.keys())
        
        G_values = {}
        epistemic_values = {}
        pragmatic_values = {}
        
        for a_name in available_actions:
            action = self.model.actions[a_name]
            G, epistemic, pragmatic = self.compute_G(action)
            G_values[a_name] = G
            epistemic_values[a_name] = epistemic
            pragmatic_values[a_name] = pragmatic
        
        action_names = list(G_values.keys())
        G_array = np.array([G_values[a] for a in action_names])
        G_shifted = (G_array - G_array.min()) / (temperature + 1e-6)
        probs = np.exp(-G_shifted)
        probs = probs / probs.sum()
        
        chosen_idx = np.random.choice(len(action_names), p=probs)
        chosen_action = action_names[chosen_idx]
        
        info = {
            "chosen": chosen_action,
            "probabilities": dict(zip(action_names, probs)),
            "G_values": G_values,
            "epistemic": epistemic_values,
            "pragmatic": pragmatic_values,
            "temperature": temperature
        }
        
        logger.log(f"[ACTIVE_INFERENCE] Action: {chosen_action} (G={G_values[chosen_action]:.3f}, E={epistemic_values[chosen_action]:.3f}, P={pragmatic_values[chosen_action]:.3f}, p={probs[chosen_idx]:.3f})")
        
        return chosen_action, info


# ============================================================
# ACTIVE INFERENCE ENGINE
# ============================================================

class ActiveInferenceEngine:
    def __init__(self, agent):
        self.agent = agent
        self.model = GenerativeModel(agent)
        self.inference = VariationalInference(self.model)
        self.planner = ExpectedFreeEnergy(self.model, self.inference)
        self.experience_buffer = deque(maxlen=1000)
        self.action_history = deque(maxlen=100)
        self.temperature = 1.0
        self.min_temperature = 0.3
        self.temperature_decay = 0.9995
        logger.log("[ACTIVE_INFERENCE] Engine initialized")
    
    def step(self, observations: Dict[str, int]) -> Tuple[str, Dict]:
        self.model.update_preferences_from_agent()
        fe = self.inference.update_beliefs(observations)
        
        # NEW: Temperature modulation based on Death Risk
        death_risk = getattr(self.agent, 'death_risk', None)
        if death_risk:
            integrity = death_risk.integrity.compute_overall_integrity()
            if integrity < 0.3:
                # Критическая: минимальная температура (детерминированное выживание)
                self.temperature = max(0.1, self.min_temperature)
            elif integrity < 0.5:
                # Опасная: снижаем температуру
                self.temperature = max(0.2, self.temperature * 0.95)
            elif integrity < 0.7:
                # Предупреждение: слегка снижаем
                self.temperature = max(0.3, self.temperature * 0.98)
        
        available_actions = self._get_available_actions()
        chosen_action, info = self.planner.select_action(available_actions, self.temperature)
        info["free_energy"] = fe
        info["beliefs"] = {n: s.posterior.tolist() for n, s in self.model.hidden_states.items()}
        self.action_history.append(info)
        self.temperature = max(self.min_temperature, self.temperature * self.temperature_decay)
        return chosen_action, info
    
    def _get_available_actions(self) -> List[str]:
        actions = ["think_known", "rest"]
        if self.agent.active_goal:
            actions.extend(["think_decompose", "synthesize"])
        energy_ratio = self.agent.energy / max(1, getattr(self.agent, 'energy_max', 150))
        if energy_ratio < 0.3:
            actions = ["rest", "think_known"]
        if hasattr(self.agent, 'internal_motivation'):
            c = self.agent.internal_motivation.needs.get("curiosity")
            if c and c.is_pressing():
                actions.extend(["explore", "ask_user"])
            c = self.agent.internal_motivation.needs.get("connection")
            if c and c.is_pressing():
                actions.append("ask_user")
        
        # NEW: Death Risk driven actions
        death_risk = getattr(self.agent, 'death_risk', None)
        if death_risk:
            integrity = death_risk.integrity.compute_overall_integrity()
            if integrity < 0.3:
                # Критическая: ТОЛЬКО восстановление
                actions = ["repair", "deep_rest", "checkpoint_now"]
            elif integrity < 0.5:
                # Опасная зона: добавляем восстановление, убираем explore
                actions = [a for a in actions if a != "explore"]
                actions.extend(["deep_rest", "checkpoint_now"])
            elif integrity < 0.7:
                # Предупреждение: доступно восстановление
                actions.extend(["checkpoint_now"])
        
        return list(dict.fromkeys(actions))
    
    def record_experience(self, action: str, obs_before: Dict, obs_after: Dict, reward: float):
        self.experience_buffer.append({
            "action": action, "obs_before": obs_before, "obs_after": obs_after,
            "reward": reward, "cycle": self.agent.cycle_count,
            "beliefs_before": {n: s.posterior.copy() for n, s in self.model.hidden_states.items()},
        })
    
    def learn_from_experience(self, batch_size: int = 32):
        if len(self.experience_buffer) < batch_size:
            return
        batch = random.sample(list(self.experience_buffer), batch_size)
        for exp in batch:
            action = exp["action"]
            if action not in self.model.actions:
                continue
            self.inference.update_beliefs(exp["obs_before"])
            b_before = {n: s.posterior.copy() for n, s in self.model.hidden_states.items()}
            self.inference.update_beliefs(exp["obs_after"])
            b_after = {n: s.posterior.copy() for n, s in self.model.hidden_states.items()}
            action_obj = self.model.actions[action]
            for state_name in action_obj.transitions:
                if state_name in b_before and state_name in b_after:
                    lr = 0.01
                    T = action_obj.transitions[state_name]
                    outer = np.outer(b_after[state_name], b_before[state_name])
                    T = (1 - lr) * T + lr * outer
                    T = T / (T.sum(axis=1, keepdims=True) + 1e-10)
                    action_obj.transitions[state_name] = T
        logger.log(f"[ACTIVE_INFERENCE] Model learning from {len(batch)} experiences")
    
    def get_state_summary(self) -> Dict:
        return {
            "beliefs": {n: {"most_likely": int(np.argmax(s.posterior)), "confidence": float(np.max(s.posterior)), 
                           "entropy": float(self.inference._entropy(s.posterior)), "distribution": s.posterior.tolist()}
                       for n, s in self.model.hidden_states.items()},
            "free_energy": self.inference.free_energy_history[-1] if self.inference.free_energy_history else 0,
            "temperature": self.temperature,
            "experience_buffer_size": len(self.experience_buffer),
        }


# ============================================================
# OBSERVATION ENCODER
# ============================================================

def encode_observations(agent) -> Dict[str, int]:
    obs = {}
    last_stimulus = getattr(agent, '_last_stimulus', '')
    if not last_stimulus:
        obs["user_input_type"] = 4
    elif '?' in last_stimulus or 'что' in last_stimulus.lower() or 'как' in last_stimulus.lower():
        obs["user_input_type"] = 0
    elif last_stimulus.startswith('команда'):
        obs["user_input_type"] = 2
    elif any(w in last_stimulus.lower() for w in ['да', 'нет', 'это', 'означает', 'есть']):
        obs["user_input_type"] = 3
    else:
        obs["user_input_type"] = 1
    
    last_thought = getattr(agent, '_last_thought', '')
    if 'Ментальная модель' in last_thought or 'Знаю ответ' in last_thought:
        obs["thinking_outcome"] = 0
    elif 'Гипотеза' in last_thought or 'Предполагаю' in last_thought:
        obs["thinking_outcome"] = 1
    elif 'декомпозиц' in last_thought.lower():
        obs["thinking_outcome"] = 3
    elif 'Не знаю' in last_thought or 'ошибк' in last_thought.lower():
        obs["thinking_outcome"] = 2
    else:
        obs["thinking_outcome"] = 1
    
    energy_ratio = agent.energy / max(1, getattr(agent, 'energy_max', 150))
    if energy_ratio < 0.3:
        obs["energy_level"] = 0
    elif energy_ratio < 0.7:
        obs["energy_level"] = 1
    else:
        obs["energy_level"] = 2
    
    if agent.mental_models.concepts:
        avg_conf = np.mean([n.confidence for n in agent.mental_models.concepts.values()])
    else:
        avg_conf = 0.0
    if avg_conf < 0.3:
        obs["concept_confidence"] = 0
    elif avg_conf < 0.7:
        obs["concept_confidence"] = 1
    else:
        obs["concept_confidence"] = 2
    
    last_interaction = getattr(agent, '_last_social_valence', 0.0)
    if last_interaction > 0.3:
        obs["social_feedback"] = 0
    elif last_interaction < -0.3:
        obs["social_feedback"] = 2
    elif 'объясни' in str(getattr(agent, '_last_stimulus', '')).lower():
        obs["social_feedback"] = 3
    else:
        obs["social_feedback"] = 1
    
    # NEW: Интероцептивные наблюдения
    intero = getattr(agent, 'interoception', None)
    if intero:
        s = intero.state
        # fatigue: 0=low, 1=medium, 2=high
        f = s.fatigue
        if f < 0.33:
            obs["interoception_fatigue"] = 0
        elif f < 0.66:
            obs["interoception_fatigue"] = 1
        else:
            obs["interoception_fatigue"] = 2
        
        # ATP ratio: 0=low, 1=medium, 2=high
        atp_ratio = s.atp / max(1.0, s.atp_max)
        if atp_ratio < 0.33:
            obs["interoception_atp"] = 0
        elif atp_ratio < 0.66:
            obs["interoception_atp"] = 1
        else:
            obs["interoception_atp"] = 2
        
        # Mito health: 0=low, 1=medium, 2=high
        m = s.mitochondrial_health
        if m < 0.33:
            obs["interoception_mito"] = 0
        elif m < 0.66:
            obs["interoception_mito"] = 1
        else:
            obs["interoception_mito"] = 2
    else:
        obs["interoception_fatigue"] = 0
        obs["interoception_atp"] = 2
        obs["interoception_mito"] = 2
    
    # NEW: Социальные наблюдения
    social = getattr(agent, 'social_cell', None)
    if social and hasattr(social, 'get_predicted_reaction'):
        # Получаем предсказанную реакцию для типичного действия
        pred = social.predict_reaction_to('user', 'cooperate')
        reaction = pred.get('predicted_reaction', 'unknown')
        if reaction == 'trust':
            obs["social_predicted_reaction"] = 0
        elif reaction == 'suspicion':
            obs["social_predicted_reaction"] = 1
        elif reaction == 'betrayal':
            obs["social_predicted_reaction"] = 2
        else:
            obs["social_predicted_reaction"] = 3
    else:
        obs["social_predicted_reaction"] = 3
    
    # Social model precision
    if social and hasattr(social, 'models') and 'user' in social.models:
        precision = social.models['user'].precision
        if precision < 0.4:
            obs["social_model_precision"] = 0
        elif precision < 0.7:
            obs["social_model_precision"] = 1
        else:
            obs["social_model_precision"] = 2
    else:
        obs["social_model_precision"] = 1
    
    # NEW: Структурная целостность
    death_risk = getattr(agent, 'death_risk', None)
    if death_risk:
        integrity = death_risk.integrity.compute_overall_integrity()
        if integrity < 0.5:
            obs["integrity_level"] = 0
        elif integrity < 0.8:
            obs["integrity_level"] = 1
        else:
            obs["integrity_level"] = 2
    else:
        obs["integrity_level"] = 2
    
    # NEW: Субъективное время — dilation
    cont_time = getattr(agent, 'continuous_time', None)
    if cont_time and hasattr(cont_time, 'subjective_time'):
        dilation = cont_time.subjective_time.dilation
        if dilation < 0.8:
            obs["time_dilation_obs"] = 0
        elif dilation < 1.2:
            obs["time_dilation_obs"] = 1
        else:
            obs["time_dilation_obs"] = 2
    else:
        obs["time_dilation_obs"] = 1
    
    return obs


# ============================================================
# INTEGRATION HELPER
# ============================================================

def create_active_inference_engine(agent) -> ActiveInferenceEngine:
    return ActiveInferenceEngine(agent)


def run_active_inference_step(engine: ActiveInferenceEngine, agent) -> str:
    observations = encode_observations(agent)
    action_name, info = engine.step(observations)
    action_map = {
        "think_known": "think", "think_decompose": "decompose",
        "ask_user": "ask_user", "synthesize": "synthesize",
        "rest": "rest", "explore": "explore",
        # NEW: Death Risk actions
        "repair": "repair", "deep_rest": "deep_rest", "checkpoint_now": "checkpoint",
    }
    agent_decision = action_map.get(action_name, "think")
    agent._last_active_inference_action = action_name
    agent._last_active_inference_info = info
    return agent_decision