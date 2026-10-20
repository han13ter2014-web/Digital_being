"""
Социальная клеточка — рекурсивное взаимное моделирование.

"Я моделирую, как ты моделируешь меня, моделируя тебя..."
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from collections import deque
from enum import Enum, IntEnum
from src.core.buffered_logger import get_logger

logger = get_logger()


class ToMLevel(IntEnum):
    ZERO = 0
    FIRST = 1
    SECOND = 2
    THIRD = 3
    META = 4


@dataclass
class AgentModel:
    agent_id: str
    tom_level: ToMLevel = ToMLevel.FIRST
    believed_goals: Dict[str, float] = field(default_factory=dict)
    believed_beliefs: Dict[str, float] = field(default_factory=dict)
    believed_intentions: Dict[str, float] = field(default_factory=dict)
    believed_emotional_state: Dict[str, float] = field(default_factory=dict)
    believed_model_of_self: Dict[str, float] = field(default_factory=dict)
    model_precision: float = 0.5
    interaction_history: deque = field(default_factory=lambda: deque(maxlen=200))
    behavior_predictor: Dict = field(default_factory=dict)


class SocialCell:
    def __init__(self, agent, max_recursion_depth: int = 3):
        self.agent = agent
        self.max_recursion_depth = max_recursion_depth
        self.agent_models: Dict[str, AgentModel] = {}
        self.self_model_as_seen_by_others: Dict[str, Dict] = {}
        self.current_tom_level = ToMLevel.SECOND
        self.learning_rate = 0.1
        self.forgetting_rate = 0.01
        self.precision_decay = 0.99
        self.social_preferences = {
            'cooperation': 0.7,
            'reciprocity': 0.8,
            'trust_baseline': 0.5,
            'fairness': 0.6,
            'curiosity_about_others': 0.7
        }
        logger.log(f"[SOCIAL_CELL] Initialized with max recursion depth {max_recursion_depth}")
    
    def register_agent(self, agent_id: str, initial_beliefs: Dict = None) -> AgentModel:
        model = AgentModel(agent_id=agent_id)
        
        if initial_beliefs:
            model.believed_goals = initial_beliefs.get('goals', {})
            model.believed_beliefs = initial_beliefs.get('beliefs', {})
            model.believed_intentions = initial_beliefs.get('intentions', {})
            model.believed_emotional_state = initial_beliefs.get('emotions', {})
        
        model.believed_model_of_self = {
            'competence': 0.5,
            'benevolence': 0.5,
            'predictability': 0.5,
            'openness': 0.5
        }
        
        self.agent_models[agent_id] = model
        logger.log(f"[SOCIAL_CELL] Registered agent: {agent_id}")
        return model
    
    def observe_interaction(self, agent_id: str, observation: Dict):
        if agent_id not in self.agent_models:
            self.register_agent(agent_id)
        
        model = self.agent_models[agent_id]
        model.interaction_history.append({
            'timestamp': observation.get('timestamp', 0),
            'observation': observation
        })
        
        if model.tom_level >= ToMLevel.FIRST:
            self._update_goals(model, observation)
            self._update_beliefs(model, observation)
            self._update_intentions(model, observation)
        
        if model.tom_level >= ToMLevel.SECOND:
            self._update_model_of_self(model, observation)
        
        if model.tom_level >= ToMLevel.THIRD:
            self._update_recursive_model(model, observation)
        
        self._update_model_precision(model, observation)
        self._update_behavior_predictor(model, observation)
    
    def _update_goals(self, model: AgentModel, obs: Dict):
        action = obs.get('action', '')
        if action:
            goal_key = f"goal_{action}"
            current = model.believed_goals.get(goal_key, 0.0)
            model.believed_goals[goal_key] = current * 0.9 + 0.1
        for k in list(model.believed_goals.keys()):
            model.believed_goals[k] *= (1.0 - self.forgetting_rate)
            if model.believed_goals[k] < 0.05:
                del model.believed_goals[k]
    
    def _update_beliefs(self, model: AgentModel, obs: Dict):
        pass
    
    def _update_intentions(self, model: AgentModel, obs: Dict):
        action = obs.get('action', '')
        if action:
            intent_key = f"intent_{action}"
            current = model.believed_intentions.get(intent_key, 0.0)
            model.believed_intentions[intent_key] = current * 0.8 + 0.2
    
    def _update_model_of_self(self, model: AgentModel, obs: Dict):
        reaction = obs.get('reaction_to_us', '')
        if reaction == 'trust':
            model.believed_model_of_self['benevolence'] = \
                model.believed_model_of_self.get('benevolence', 0.5) * 0.9 + 0.1
            model.believed_model_of_self['trustworthiness'] = \
                model.believed_model_of_self.get('trustworthiness', 0.5) * 0.9 + 0.1
        elif reaction == 'suspicion':
            model.believed_model_of_self['benevolence'] = \
                model.believed_model_of_self.get('benevolence', 0.5) * 0.9 - 0.1
        elif reaction == 'confusion':
            model.believed_model_of_self['predictability'] = \
                model.believed_model_of_self.get('predictability', 0.5) * 0.9 - 0.1
        for k in model.believed_model_of_self:
            model.believed_model_of_self[k] = np.clip(model.believed_model_of_self[k], 0.0, 1.0)
    
    def _update_recursive_model(self, model: AgentModel, obs: Dict):
        pass
    
    def _update_model_precision(self, model: AgentModel, obs: Dict):
        predicted = self.predict_behavior(model.agent_id)
        actual = obs.get('action', '')
        if predicted and actual:
            match = 1.0 if predicted == actual else 0.0
            model.model_precision = model.model_precision * self.precision_decay + \
                                   (1.0 - self.precision_decay) * match
        else:
            model.model_precision *= self.precision_decay
        model.model_precision = np.clip(model.model_precision, 0.1, 1.0)
    
    def _update_behavior_predictor(self, model: AgentModel, obs: Dict):
        action = obs.get('action', '')
        if not action:
            return
        history = list(model.interaction_history)
        if len(history) >= 2:
            prev2 = history[-3].get('observation', {}).get('action', '') if len(history) >= 3 else ''
            prev1 = history[-2].get('observation', {}).get('action', '') if len(history) >= 2 else ''
            key = (prev2, prev1)
            if key not in model.behavior_predictor:
                model.behavior_predictor[key] = {}
            model.behavior_predictor[key][action] = \
                model.behavior_predictor[key].get(action, 0) + 1
    
    def predict_behavior(self, agent_id: str, context: Dict = None) -> Optional[str]:
        if agent_id not in self.agent_models:
            return None
        model = self.agent_models[agent_id]
        history = list(model.interaction_history)
        if len(history) >= 2:
            prev2 = history[-3].get('observation', {}).get('action', '') if len(history) >= 3 else ''
            prev1 = history[-2].get('observation', {}).get('action', '') if len(history) >= 2 else ''
            key = (prev2, prev1)
            if key in model.behavior_predictor:
                dist = model.behavior_predictor[key]
                return max(dist, key=dist.get)
        if model.believed_intentions:
            return max(model.believed_intentions, key=model.believed_intentions.get).replace('intent_', '')
        return None
    
    def predict_reaction_to(self, agent_id: str, our_action: str) -> Dict:
        if agent_id not in self.agent_models:
            return {'predicted_reaction': 'unknown', 'confidence': 0.0}
        
        model = self.agent_models[agent_id]
        trust = model.believed_model_of_self.get('trustworthiness', 0.5)
        predictability = model.believed_model_of_self.get('predictability', 0.5)
        
        if our_action in ['cooperate', 'help', 'share']:
            if trust > 0.6:
                return {'predicted_reaction': 'positive_reciprocity', 'confidence': trust}
            else:
                return {'predicted_reaction': 'suspicion', 'confidence': 1.0 - trust}
        elif our_action in ['defect', 'attack', 'deceive']:
            return {'predicted_reaction': 'retaliation', 'confidence': 0.8}
        elif our_action in ['ask', 'query']:
            if predictability > 0.5:
                return {'predicted_reaction': 'informative', 'confidence': predictability}
            else:
                return {'predicted_reaction': 'evasive', 'confidence': 1.0 - predictability}
        
        return {'predicted_reaction': 'neutral', 'confidence': 0.3}
    
    def choose_action_social(self, agent_id: str, available_actions: List[str]) -> str:
        if agent_id not in self.agent_models:
            return available_actions[0] if available_actions else 'wait'
        
        model = self.agent_models[agent_id]
        best_action = None
        best_value = -float('inf')
        
        for action in available_actions:
            reaction = self.predict_reaction_to(agent_id, action)
            value = self._compute_social_value(action, reaction, model)
            epistemic = self._compute_epistemic_value(action, model)
            total_value = value + 0.3 * epistemic
            
            if total_value > best_value:
                best_value = total_value
                best_action = action
        
        return best_action or available_actions[0]
    
    def _compute_social_value(self, action: str, reaction: Dict, model: AgentModel) -> float:
        prefs = self.social_preferences
        reaction_type = reaction.get('predicted_reaction', 'neutral')
        confidence = reaction.get('confidence', 0.5)
        
        values = {
            'cooperate': prefs['cooperation'],
            'help': prefs['cooperation'] * 1.2,
            'share': prefs['fairness'],
            'ask': prefs['curiosity_about_others'],
            'defect': -prefs['reciprocity'],
            'attack': -1.0,
            'deceive': -prefs['trust_baseline']
        }
        
        base = values.get(action, 0.0)
        
        reaction_mod = {
            'positive_reciprocity': 1.5,
            'informative': 1.2,
            'neutral': 1.0,
            'suspicion': 0.5,
            'evasive': 0.5,
            'retaliation': -1.0
        }
        
        return base * reaction_mod.get(reaction_type, 1.0) * confidence
    
    def _compute_epistemic_value(self, action: str, model: AgentModel) -> float:
        info_actions = ['ask', 'probe', 'test', 'observe']
        if action in info_actions:
            return (1.0 - model.model_precision) * self.social_preferences['curiosity_about_others']
        return 0.0
    
    def get_mutual_model_state(self, agent_id: str) -> Dict:
        if agent_id not in self.agent_models:
            return {}
        
        model = self.agent_models[agent_id]
        return {
            'agent_id': agent_id,
            'tom_level': model.tom_level.name,
            'model_precision': model.model_precision,
            'believed_goals': dict(list(model.believed_goals.items())[:5]),
            'believed_intentions': dict(list(model.believed_intentions.items())[:5]),
            'model_of_self': model.believed_model_of_self,
            'predicted_next_action': self.predict_behavior(agent_id),
            'interaction_count': len(model.interaction_history)
        }
    
    def get_status(self) -> Dict:
        return {
            'num_modeled_agents': len(self.agent_models),
            'current_tom_level': self.current_tom_level.name,
            'models': {aid: self.get_mutual_model_state(aid) for aid in self.agent_models},
            'social_preferences': self.social_preferences
        }
    
    def set_tom_level(self, level: ToMLevel):
        self.current_tom_level = level
        for model in self.agent_models.values():
            model.tom_level = level
        logger.log(f"[SOCIAL_CELL] ToM level set to {level.name}")


def create_social_cell(agent, max_recursion_depth: int = 3) -> SocialCell:
    return SocialCell(agent, max_recursion_depth)