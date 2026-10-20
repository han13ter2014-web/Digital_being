"""
Интероцептивная модель — иерархическая модель тела агента.

Уровни (снизу вверх):
1. Глюкоза (Glucose) — сырье, поступает от "еды" (внешних ресурсов/знаний)
2. АТФ (ATP) — валюта энергии, производится в митохондриях
3. Митохондрии (Mitochondria) — производственные мощности, деградируют со временем
4. Усталость (Fatigue) — субъективное переживание дефицита АТФ
5. Поведение (Behavior) — действие, модулируемое усталостью
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List
from collections import deque
from src.core.buffered_logger import get_logger

logger = get_logger()


@dataclass
class InteroceptiveState:
    glucose: float = 5.0
    glucose_max: float = 10.0
    glucose_absorption_rate: float = 0.1
    
    atp: float = 5.0
    atp_max: float = 8.0
    atp_production_rate: float = 0.5
    atp_basal_consumption: float = 0.1
    
    mitochondrial_health: float = 1.0
    mitochondrial_biogenesis: float = 0.001
    mitochondrial_damage_rate: float = 0.0005
    mitophagy_threshold: float = 0.3
    
    fatigue: float = 0.0
    fatigue_integration_tau: float = 10.0
    fatigue_threshold_rest: float = 0.6
    fatigue_threshold_critical: float = 0.9
    
    action_cost_multiplier: float = 1.0
    cognitive_throughput: float = 1.0
    exploration_drive: float = 1.0
    
    history: deque = field(default_factory=lambda: deque(maxlen=1000))


class InteroceptiveModel:
    def __init__(self, agent):
        self.agent = agent
        self.state = InteroceptiveState()
        self.dt = 1.0
        self.glucose_to_atp_efficiency = 0.4
        self.atp_to_fatigue_sensitivity = 2.0
        self.mito_stress_response = 0.1
        self.predicted_fatigue_horizon = 10
        self.predicted_atp_trajectory: List[float] = []
        self.predicted_fatigue_trajectory: List[float] = []
        logger.log("[INTEROCEPTION] Hierarchical model initialized")
    
    def step(self, dt: float = 1.0, cognitive_load: float = 0.0,
             stress: float = 0.0, food_intake: float = 0.0,
             rest_depth: float = 0.0) -> Dict:
        self.dt = dt
        s = self.state
        
        glucose_consumption = (s.atp_basal_consumption + cognitive_load * 0.5) * dt
        glucose_absorption = food_intake * s.glucose_absorption_rate * dt
        s.glucose = np.clip(s.glucose - glucose_consumption + glucose_absorption, 0.0, s.glucose_max)
        
        atp_production = (s.glucose / s.glucose_max) * s.mitochondrial_health * \
                         s.atp_production_rate * self.glucose_to_atp_efficiency * dt
        atp_consumption = (s.atp_basal_consumption + cognitive_load * 0.8 + stress * 0.5) * dt
        s.atp = np.clip(s.atp + atp_production - atp_consumption, 0.0, s.atp_max)
        
        mito_damage = atp_production * s.mitochondrial_damage_rate * dt
        mito_growth = cognitive_load * s.mitochondrial_biogenesis * self.mito_stress_response * dt
        if s.mitochondrial_health < s.mitophagy_threshold:
            mito_growth += 0.002 * dt
        s.mitochondrial_health = np.clip(s.mitochondrial_health - mito_damage + mito_growth, 0.05, 1.5)
        
        atp_deficit = 1.0 - (s.atp / s.atp_max)
        fatigue_drive = atp_deficit * self.atp_to_fatigue_sensitivity
        tau = s.fatigue_integration_tau
        s.fatigue += (fatigue_drive - s.fatigue) * (dt / tau)
        s.fatigue = np.clip(s.fatigue, 0.0, 1.0)
        if rest_depth > 0:
            s.fatigue *= (1.0 - rest_depth * 0.1 * dt)
        
        s.action_cost_multiplier = 1.0 + s.fatigue * 3.0
        s.cognitive_throughput = 1.0 - s.fatigue * 0.7
        s.exploration_drive = (1.0 - s.fatigue) * (s.atp / s.atp_max)
        
        self._predict_trajectory(cognitive_load, stress, food_intake, rest_depth)
        
        s.history.append({
            'glucose': s.glucose, 'atp': s.atp, 'mito': s.mitochondrial_health,
            'fatigue': s.fatigue, 'cognitive_load': cognitive_load
        })
        
        return self.get_status()
    
    def _predict_trajectory(self, cognitive_load: float, stress: float,
                           food_intake: float, rest_depth: float):
        h = self.predicted_fatigue_horizon
        atp_traj = []
        fatigue_traj = []
        
        sim_atp = self.state.atp
        sim_fatigue = self.state.fatigue
        sim_mito = self.state.mitochondrial_health
        sim_glucose = self.state.glucose
        
        for _ in range(h):
            prod = (sim_glucose / self.state.glucose_max) * sim_mito * \
                   self.state.atp_production_rate * self.glucose_to_atp_efficiency
            cons = self.state.atp_basal_consumption + cognitive_load * 0.8 + stress * 0.5
            sim_atp = np.clip(sim_atp + prod - cons, 0.0, self.state.atp_max)
            
            atp_def = 1.0 - (sim_atp / self.state.atp_max)
            sim_fatigue += (atp_def * self.atp_to_fatigue_sensitivity - sim_fatigue) * (1.0 / self.state.fatigue_integration_tau)
            sim_fatigue = np.clip(sim_fatigue, 0.0, 1.0)
            
            atp_traj.append(sim_atp)
            fatigue_traj.append(sim_fatigue)
        
        self.predicted_atp_trajectory = atp_traj
        self.predicted_fatigue_trajectory = fatigue_traj
    
    def get_status(self) -> Dict:
        s = self.state
        return {
            'glucose': s.glucose,
            'glucose_ratio': s.glucose / s.glucose_max,
            'atp': s.atp,
            'atp_ratio': s.atp / s.atp_max,
            'mitochondrial_health': s.mitochondrial_health,
            'fatigue': s.fatigue,
            'fatigue_level': self._fatigue_level(s.fatigue),
            'action_cost_multiplier': s.action_cost_multiplier,
            'cognitive_throughput': s.cognitive_throughput,
            'exploration_drive': s.exploration_drive,
            'needs_rest': s.fatigue > s.fatigue_threshold_rest,
            'critical_fatigue': s.fatigue > s.fatigue_threshold_critical,
            'predicted_atp': self.predicted_atp_trajectory[:5],
            'predicted_fatigue': self.predicted_fatigue_trajectory[:5],
        }
    
    def _fatigue_level(self, fatigue: float) -> str:
        if fatigue < 0.2: return "fresh"
        elif fatigue < 0.4: return "normal"
        elif fatigue < 0.6: return "tired"
        elif fatigue < 0.8: return "exhausted"
        else: return "critical"
    
    def get_action_cost(self, base_cost: float) -> float:
        return base_cost * self.state.action_cost_multiplier
    
    def can_perform_action(self, base_cost: float, energy: float) -> bool:
        return energy >= self.get_action_cost(base_cost)
    
    def inject_glucose(self, amount: float):
        self.state.glucose = min(self.state.glucose_max, self.state.glucose + amount)
    
    def inject_atp_direct(self, amount: float):
        self.state.atp = min(self.state.atp_max, self.state.atp + amount)
        self.state.mitochondrial_health *= 0.995
    
    def deep_rest(self, duration: float = 1.0):
        self.step(dt=duration, cognitive_load=0.0, stress=0.0, food_intake=0.1, rest_depth=1.0)


def create_interoceptive_model(agent) -> InteroceptiveModel:
    return InteroceptiveModel(agent)