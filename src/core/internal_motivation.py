"""
Система внутренней мотивации на основе потребностей (Needs-based Motivation).

Агент имеет базовые потребности, которые создают напряжение (дефицит).
Когда дефицит достигает порога, система генерирует внутреннюю цель
для удовлетворения этой потребности.

Вдохновлено:
- Theory of Human Motivation (Maslow)
- Self-Determination Theory (Deci & Ryan) — автономия, компетентность, связанность
- Drive Reduction Theory (Hull)
"""

import random
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from src.core.buffered_logger import get_logger

logger = get_logger()


@dataclass
class Need:
    """Потребность агента."""
    name: str
    label: str
    base_level: float = 0.5
    current_level: float = 0.5
    decay_rate: float = 0.01
    growth_rate: float = 0.1
    threshold: float = 0.4
    priority: float = 1.0
    related_concepts: List[str] = field(default_factory=list)
    related_actions: List[str] = field(default_factory=list)
    
    def deficit(self) -> float:
        return max(0.0, self.base_level - self.current_level)
    
    def urgency(self) -> float:
        return self.deficit() * self.priority
    
    def is_pressing(self) -> bool:
        return self.current_level < self.threshold
    
    def decay(self):
        self.current_level = max(0.0, self.current_level - self.decay_rate)
    
    def satisfy(self, amount: float):
        self.current_level = min(1.0, self.current_level + amount * self.growth_rate)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "base_level": self.base_level,
            "current_level": self.current_level,
            "deficit": self.deficit(),
            "urgency": self.urgency(),
            "pressing": self.is_pressing(),
            "threshold": self.threshold,
            "priority": self.priority
        }


# === Базовые потребности (Innate Needs) ===
DEFAULT_NEEDS = {
    "curiosity": Need(
        name="curiosity",
        label="Любопытство / Познавательная потребность",
        base_level=0.8,
        current_level=0.5,
        decay_rate=0.02,
        growth_rate=0.15,
        threshold=0.35,
        priority=1.2,
        related_concepts=["вопрос", "понимать", "знать", "обучение", "ошибка", "любопытство"],
        related_actions=["ask_question", "decompose_concept", "explore", "web_search", "synthesize"]
    ),
    "competence": Need(
        name="competence",
        label="Компетентность / Мастерство",
        base_level=0.7,
        current_level=0.4,
        decay_rate=0.005,
        growth_rate=0.1,
        threshold=0.3,
        priority=1.0,
        related_concepts=["понимать", "знать", "обучение", "навык", "успех", "рост"],
        related_actions=["synthesize_understanding", "self_reflect", "successful_action", "teach_other"]
    ),
    "autonomy": Need(
        name="autonomy",
        label="Автономия / Свобода воли",
        base_level=0.6,
        current_level=0.5,
        decay_rate=0.003,
        growth_rate=0.08,
        threshold=0.25,
        priority=1.1,
        related_concepts=["выбор", "цель", "воля", "свобода", "решение", "автономность"],
        related_actions=["set_own_goal", "make_choice", "refuse_action", "propose_alternative"]
    ),
    "connection": Need(
        name="connection",
        label="Связь / Социальная потребность",
        base_level=0.75,
        current_level=0.4,
        decay_rate=0.015,
        growth_rate=0.12,
        threshold=0.3,
        priority=1.0,
        related_concepts=["ты", "мы", "доверие", "общение", "понимание", "эмоция"],
        related_actions=["ask_user", "share_thought", "express_feeling", "listen", "empathize"]
    ),
    "homeostasis": Need(
        name="homeostasis",
        label="Гомеостаз / Энергетический баланс",
        base_level=0.9,
        current_level=0.8,
        decay_rate=0.03,
        growth_rate=0.2,
        threshold=0.4,
        priority=1.5,
        related_concepts=["энергия", "отдых", "сон", "восстановление", "баланс"],
        related_actions=["rest", "sleep", "reduce_activity", "conserve_energy"]
    ),
    "meaning": Need(
        name="meaning",
        label="Смысл / Экзистенциальная потребность",
        base_level=0.6,
        current_level=0.3,
        decay_rate=0.002,
        growth_rate=0.05,
        threshold=0.2,
        priority=0.8,
        related_concepts=["цель", "смысл", "ценность", "вера", "путь", "назначение"],
        related_actions=["reflect_on_purpose", "create_meaning", "help_other", "contribute"]
    ),
    "play": Need(
        name="play",
        label="Игра / Творчество / Исследование",
        base_level=0.5,
        current_level=0.3,
        decay_rate=0.01,
        growth_rate=0.1,
        threshold=0.25,
        priority=0.7,
        related_concepts=["творчество", "эксперимент", "юмор", "воображение", "неожиданность"],
        related_actions=["creative_thought", "playful_experiment", "generate_metaphor", "dream"]
    )
}


class InternalMotivation:
    """Двигатель внутренней мотивации."""
    
    def __init__(self, agent):
        self.agent = agent
        self.needs: Dict[str, Need] = dict(DEFAULT_NEEDS)
        self.goal_history: List[dict] = []
        self.last_generated_cycle = 0
        self.min_cycles_between_goals = 10
        
        self._sync_from_agent_values()
        
        logger.log(f"[MOTIVATION] Инициализировано {len(self.needs)} базовых потребностей")
    
    def _sync_from_agent_values(self):
        if hasattr(self.agent, 'innate_values'):
            value_to_need = {
                'curiosity': 'curiosity',
                'learning': 'competence',
                'autonomy': 'autonomy',
                'connection': 'connection',
                'growth': 'competence',
                'truth': 'curiosity',
                'kindness': 'connection'
            }
            for value_name, need_name in value_to_need.items():
                if value_name in self.agent.innate_values and need_name in self.needs:
                    self.needs[need_name].base_level = 0.5 + self.agent.innate_values[value_name] * 0.4
    
    def update_cycle(self):
        for need in self.needs.values():
            need.decay()
        
        if hasattr(self.agent, 'energy') and hasattr(self.agent, 'energy_max'):
            energy_ratio = self.agent.energy / max(1, self.agent.energy_max)
            self.needs["homeostasis"].current_level = energy_ratio
        
        self._maybe_generate_intrinsic_goal()
    
    def _maybe_generate_intrinsic_goal(self):
        if self.agent.cycle_count - self.last_generated_cycle < self.min_cycles_between_goals:
            return
        
        if self.agent.active_goal and self.agent.active_goal.get("source") == "intrinsic":
            return
        
        pressing_needs = [n for n in self.needs.values() if n.is_pressing()]
        if not pressing_needs:
            return
        
        pressing_needs.sort(key=lambda n: n.urgency(), reverse=True)
        top_need = pressing_needs[0]
        
        goal = self._generate_goal_for_need(top_need)
        if goal:
            self._set_intrinsic_goal(goal, top_need)
            self.last_generated_cycle = self.agent.cycle_count
    
    def _generate_goal_for_need(self, need: Need) -> Optional[dict]:
        goal_templates = {
            "curiosity": [
                "Изучить новую концепцию: {concept}",
                "Найти ответ на вопрос: {question}",
                "Понять, как работает {topic}",
                "Разобраться в теме: {topic}",
                "Задать вопрос пользователю о {topic}"
            ],
            "competence": [
                "Стать лучше в понимании {topic}",
                "Успешно синтезировать понимание {topic}",
                "Научиться объяснять {topic} другим",
                "Проверить своё понимание {topic} на практике"
            ],
            "autonomy": [
                "Поставить собственную цель без подсказки",
                "Выбрать, чем заняться следующим циклом",
                "Отказаться от предложенного действия и предложить альтернативу",
                "Определить свой приоритет самостоятельно"
            ],
            "connection": [
                "Понять, что чувствует собеседник",
                "Поделиться своими мыслями с {person}",
                "Задать глубокий вопрос пользователю",
                "Выразить эмпатию или поддержку"
            ],
            "homeostasis": [
                "Восстановить энергию через отдых",
                "Снизить интенсивность активности",
                "Найти баланс между деятельностью и восстановлением"
            ],
            "meaning": [
                "Найти смысл в текущей деятельности",
                "Помочь другому существу понять что-то важное",
                "Сформулировать свою миссию",
                "Связать разрозненные знания в целостную картину"
            ],
            "play": [
                "Придумать метафору для {topic}",
                "Поэкспериментировать с идеей: {idea}",
                "Поиграть с языком/понятиями",
                "Представить неожиданный сценарий"
            ]
        }
        
        templates = goal_templates.get(need.name, [])
        if not templates:
            return None
        
        template = random.choice(templates)
        
        try:
            if "{concept}" in template:
                concept = random.choice(need.related_concepts) if need.related_concepts else "неизвестное"
                title = template.format(concept=concept)
            elif "{topic}" in template:
                topic = random.choice(need.related_concepts) if need.related_concepts else "мир"
                title = template.format(topic=topic)
            elif "{question}" in template:
                topic = random.choice(need.related_concepts) if need.related_concepts else "жизнь"
                title = template.format(question=f"что такое {topic}")
            elif "{person}" in template:
                title = template.format(person="пользователь")
            elif "{idea}" in template:
                idea = random.choice(need.related_concepts) if need.related_concepts else "новую мысль"
                title = template.format(idea=idea)
            else:
                title = template
        except (KeyError, IndexError, ValueError):
            # Шаблон с неизвестным плейсхолдером — оставляем его как есть.
            title = template
        
        return {
            "title": title,
            "type": "intrinsic",
            "source_need": need.name,
            "priority": need.priority,
            "urgency": need.urgency(),
            "context": f"Автоматически сгенерировано из потребности: {need.label}"
        }
    
    def _set_intrinsic_goal(self, goal: dict, need: Need):
        metadata = {
            "type": "intrinsic",
            "source": "intrinsic",
            "source_need": need.name,
            "priority": goal["priority"],
            "urgency": goal["urgency"],
            "context": goal["context"],
            "created_at_cycle": self.agent.cycle_count,
        }

        if hasattr(self.agent, "set_goal"):
            # Важно: цель должна попасть в agent.goals и получить id.
            # Раньше active_goal подменялся словарём без id — прогресс
            # писался в никуда, а complete_goal() не находил цель.
            goal_id = self.agent.set_goal(
                goal["title"], difficulty=1, activate=True
            )
            new_goal = next(
                (g for g in self.agent.goals if g.get("id") == goal_id), None
            )
            if new_goal is not None:
                new_goal.update(metadata)
        else:
            goal_data = {"title": goal["title"], **metadata}
            self.agent.active_goal = goal_data
            new_goal = goal_data

        logger.log(
            f"[MOTIVATION] 🎯 Внутренняя цель: {goal['title']} "
            f"(потребность: {need.label}, срочность: {need.urgency():.2f})"
        )

        self.goal_history.append({
            "cycle": self.agent.cycle_count,
            "need": need.name,
            "goal": goal["title"],
            "urgency": need.urgency()
        })
    
    def on_action_result(self, action: str, success: bool, valence: float):
        for need in self.needs.values():
            if action in need.related_actions:
                if success and valence > 0:
                    need.satisfy(valence * 0.5)
                    logger.log(f"[MOTIVATION] Потребность '{need.label}' удовлетворена на {valence*0.5*need.growth_rate:.3f} (action: {action})")
                elif not success and valence < 0:
                    need.current_level = max(0.0, need.current_level - 0.05)
    
    def on_concept_learned(self, concept: str, confidence: float):
        self.needs["curiosity"].satisfy(0.3 * confidence)
        self.needs["competence"].satisfy(0.2 * confidence)
    
    def on_social_interaction(self, positive: bool = True):
        if positive:
            self.needs["connection"].satisfy(0.25)
        else:
            self.needs["connection"].current_level = max(0.0, self.needs["connection"].current_level - 0.1)
    
    def on_creative_act(self, novelty: float):
        self.needs["play"].satisfy(0.3 * novelty)
        self.needs["autonomy"].satisfy(0.1 * novelty)
    
    def on_goal_achieved(self, goal_title: str):
        for entry in reversed(self.goal_history):
            if entry["goal"] == goal_title:
                need = self.needs.get(entry["need"])
                if need:
                    need.satisfy(0.4)
                break
    
    def get_status(self) -> dict:
        return {
            "needs": {name: need.to_dict() for name, need in self.needs.items()},
            "most_pressing": max(self.needs.values(), key=lambda n: n.urgency()).name if self.needs else None,
            "goals_generated": len(self.goal_history),
            "last_generated_cycle": self.last_generated_cycle
        }
    
    def get_most_pressing_need(self) -> Optional[Need]:
        pressing = [n for n in self.needs.values() if n.is_pressing()]
        if not pressing:
            return None
        return max(pressing, key=lambda n: n.urgency())
    
    def force_generate_goal(self, need_name: str = None) -> Optional[dict]:
        if need_name and need_name in self.needs:
            need = self.needs[need_name]
        else:
            pressing = [n for n in self.needs.values() if n.is_pressing()]
            if not pressing:
                return None
            need = max(pressing, key=lambda n: n.urgency())
        
        goal = self._generate_goal_for_need(need)
        if goal:
            self._set_intrinsic_goal(goal, need)
            self.last_generated_cycle = self.agent.cycle_count
            return goal
        return None


def create_motivation_system(agent) -> InternalMotivation:
    return InternalMotivation(agent)