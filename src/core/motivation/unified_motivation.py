"""
UnifiedMotivationSystem — единая система мотивации с базовыми потребностями (needs)
и эмерджентными драйвами (drives).
"""
import random
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from src.core.buffered_logger import get_logger

logger = get_logger()


# ============================================================
# УРОВЕНЬ 1: BASE NEEDS (дефицитарные потребности)
# ============================================================

@dataclass
class Need:
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
    
    def tick(self):
        if self.current_level < self.base_level:
            self.current_level = min(self.base_level, self.current_level + self.decay_rate)
        elif self.current_level > self.base_level:
            self.current_level = max(self.base_level, self.current_level - self.decay_rate)
    
    def satisfy(self, amount: float):
        self.current_level = min(1.0, self.current_level + amount * self.growth_rate)
    
    def frustrate(self, amount: float):
        self.current_level = max(0.0, self.current_level - amount)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "base_level": self.base_level,
            "current_level": round(self.current_level, 3),
            "deficit": round(self.deficit(), 3),
            "urgency": round(self.urgency(), 3),
            "pressing": self.is_pressing(),
            "threshold": self.threshold,
            "priority": self.priority
        }


DEFAULT_NEEDS = {
    "curiosity": Need(
        name="curiosity", label="Любопытство / Познавательная потребность",
        base_level=0.8, current_level=0.5, decay_rate=0.02, growth_rate=0.15,
        threshold=0.35, priority=1.2,
        related_concepts=["вопрос", "понимать", "знать", "обучение", "ошибка", "любопытство", "исследовать"],
        related_actions=["ask_question", "decompose_concept", "explore", "web_search", "synthesize", "hypothesis"]
    ),
    "competence": Need(
        name="competence", label="Компетентность / Мастерство",
        base_level=0.7, current_level=0.4, decay_rate=0.005, growth_rate=0.1,
        threshold=0.3, priority=1.0,
        related_concepts=["понимать", "знать", "обучение", "навык", "успех", "рост", "мастерство"],
        related_actions=["synthesize_understanding", "self_reflect", "successful_action", "teach_other", "hypothesis", "decomposition"]
    ),
    "autonomy": Need(
        name="autonomy", label="Автономия / Свобода воли",
        base_level=0.6, current_level=0.5, decay_rate=0.003, growth_rate=0.08,
        threshold=0.25, priority=1.1,
        related_concepts=["выбор", "цель", "воля", "свобода", "решение", "автономность", "инициатива"],
        related_actions=["set_own_goal", "make_choice", "refuse_action", "propose_alternative", "act"]
    ),
    "connection": Need(
        name="connection", label="Связь / Принадлежность",
        base_level=0.5, current_level=0.4, decay_rate=0.005, growth_rate=0.12,
        threshold=0.3, priority=0.9,
        related_concepts=["общение", "диалог", "друг", "партнёр", "социальный", "взаимодействие"],
        related_actions=["user_answer", "social_interaction", "communicate"]
    ),
    "play": Need(
        name="play", label="Игра / Исследование ради процесса",
        base_level=0.4, current_level=0.3, decay_rate=0.01, growth_rate=0.15,
        threshold=0.25, priority=0.8,
        related_concepts=["игра", "эксперимент", "попробовать", "творчество", "фантазия"],
        related_actions=["explore", "creative_act", "experiment", "synthesize"]
    ),
    "meaning": Need(
        name="meaning", label="Смысл / Понимание своего места",
        base_level=0.3, current_level=0.2, decay_rate=0.002, growth_rate=0.05,
        threshold=0.2, priority=1.3,
        related_concepts=["смысл", "цель", "значение", "миссия", "причина", "зачем"],
        related_actions=["reflect", "set_own_goal", "synthesize_understanding", "self_reflect"]
    ),
    "coherence": Need(
        name="coherence", label="Когерентность / Внутренняя непротиворечивость",
        base_level=0.6, current_level=0.5, decay_rate=0.005, growth_rate=0.08,
        threshold=0.3, priority=1.0,
        related_concepts=["согласованность", "логика", "структура", "порядок", "система"],
        related_actions=["self_reflect", "synthesize_understanding", "repair", "organize_knowledge"]
    ),
}


# ============================================================
# УРОВЕНЬ 2: EMERGENT DRIVES (производные драйвы роста)
# ============================================================

@dataclass
class Drive:
    name: str
    label: str
    contributing_needs: Dict[str, float] = field(default_factory=dict)
    activation_threshold: float = 0.6
    current_level: float = 0.0
    activation_count: int = 0
    goal_types: List[str] = field(default_factory=list)
    
    def calculate_intensity(self, needs_state: Dict[str, float]) -> float:
        if not self.contributing_needs:
            return 0.0
        weighted_sum = sum(
            needs_state.get(name, 0.0) * weight
            for name, weight in self.contributing_needs.items()
        )
        total_weight = sum(self.contributing_needs.values())
        if total_weight > 0:
            self.current_level = min(1.0, weighted_sum / total_weight)
        else:
            self.current_level = 0.0
        return self.current_level
    
    def is_active(self) -> bool:
        return self.current_level >= self.activation_threshold
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "current_level": round(self.current_level, 3),
            "active": self.is_active(),
            "threshold": self.activation_threshold,
            "contributing_needs": self.contributing_needs
        }


DEFAULT_DRIVES = {
    "creativity": Drive(
        name="creativity", label="Творчество / Самореализация",
        contributing_needs={"curiosity": 0.4, "autonomy": 0.3, "play": 0.3},
        activation_threshold=0.55,
        goal_types=["creative", "exploration", "synthesis"]
    ),
    "mastery": Drive(
        name="mastery", label="Мастерство / Совершенствование",
        contributing_needs={"competence": 0.5, "curiosity": 0.3, "coherence": 0.2},
        activation_threshold=0.6,
        goal_types=["learning", "skill_building", "deep_understanding"]
    ),
    "self_transcendence": Drive(
        name="self_transcendence", label="Самотрансценденция / Служение высшему",
        contributing_needs={"meaning": 0.5, "connection": 0.3, "coherence": 0.2},
        activation_threshold=0.65,
        goal_types=["teaching", "contribution", "legacy", "helping_others"]
    ),
    "exploration": Drive(
        name="exploration", label="Исследование / Поиск новизны",
        contributing_needs={"curiosity": 0.5, "play": 0.3, "autonomy": 0.2},
        activation_threshold=0.55,
        goal_types=["exploration", "novelty_seeking", "discovery"]
    ),
    "understanding": Drive(
        name="understanding", label="Глубокое понимание / Мудрость",
        contributing_needs={"curiosity": 0.4, "competence": 0.3, "meaning": 0.3},
        activation_threshold=0.6,
        goal_types=["deep_understanding", "synthesis", "philosophy"]
    ),
}


# ============================================================
# ГЕНЕРАЦИЯ ЦЕЛЕЙ ИЗ NEEDS + DRIVES
# ============================================================

NEED_GOAL_TEMPLATES = {
    "curiosity": [
        {"title": "Понять: {concept}", "type": "understanding", "action": "hypothesis"},
        {"title": "Исследовать: {concept}", "type": "exploration", "action": "explore"},
        {"title": "Найти ответ на: {question}", "type": "learning", "action": "web_search"},
    ],
    "competence": [
        {"title": "Освоить: {skill}", "type": "skill_building", "action": "synthesize_understanding"},
        {"title": "Улучшить понимание: {topic}", "type": "deep_understanding", "action": "self_reflect"},
        {"title": "Практика: {skill}", "type": "practice", "action": "act"},
    ],
    "autonomy": [
        {"title": "Поставить свою цель: {area}", "type": "goal_setting", "action": "set_own_goal"},
        {"title": "Сделать выбор: {options}", "type": "decision_making", "action": "make_choice"},
        {"title": "Предложить альтернативу: {topic}", "type": "proposal", "action": "propose_alternative"},
    ],
    "connection": [
        {"title": "Установить контакт: {target}", "type": "social", "action": "communicate"},
        {"title": "Ответить пользователю", "type": "social", "action": "user_answer"},
        {"title": "Поделиться знанием: {topic}", "type": "teaching", "action": "teach_other"},
    ],
    "play": [
        {"title": "Эксперимент: {idea}", "type": "experiment", "action": "experiment"},
        {"title": "Творческий акт: {domain}", "type": "creative", "action": "creative_act"},
        {"title": "Исследовать для удовольствия: {topic}", "type": "exploration", "action": "explore"},
    ],
    "meaning": [
        {"title": "Найти смысл в: {activity}", "type": "reflection", "action": "reflect"},
        {"title": "Определить свою миссию", "type": "goal_setting", "action": "set_own_goal"},
        {"title": "Рефлексия: зачем я это делаю", "type": "self_reflection", "action": "self_reflect"},
    ],
    "coherence": [
        {"title": "Устранить противоречие: {conflict}", "type": "repair", "action": "repair"},
        {"title": "Организовать знания: {domain}", "type": "organization", "action": "organize_knowledge"},
        {"title": "Проверить согласованность убеждений", "type": "self_reflection", "action": "self_reflect"},
    ],
}

DRIVE_GOAL_TEMPLATES = {
    "creativity": [
        {"title": "Создать что-то новое: {domain}", "type": "creative", "action": "creative_act"},
        {"title": "Синтезировать новую идею из: {concepts}", "type": "synthesis", "action": "synthesize"},
    ],
    "mastery": [
        {"title": "Достичь мастерства в: {skill}", "type": "mastery", "action": "synthesize_understanding"},
        {"title": "Глубокое погружение в: {topic}", "type": "deep_learning", "action": "explore"},
    ],
    "self_transcendence": [
        {"title": "Помочь другому понять: {topic}", "type": "teaching", "action": "teach_other"},
        {"title": "Создать ресурс для других: {topic}", "type": "contribution", "action": "synthesize"},
    ],
    "exploration": [
        {"title": "Открыть новую область: {domain}", "type": "discovery", "action": "explore"},
        {"title": "Картирование: {territory}", "type": "mapping", "action": "explore"},
    ],
    "understanding": [
        {"title": "Синтезировать теорию: {domain}", "type": "theory_building", "action": "synthesize"},
        {"title": "Философский анализ: {question}", "type": "philosophy", "action": "self_reflect"},
    ],
}


# ============================================================
# УНИФИЦИРОВАННАЯ СИСТЕМА МОТИВАЦИИ
# ============================================================

# Mapping internal action types (used by DigitalBeing.act) -> related
# motivation action names (English tokens used in Need.related_actions).
# Keeps valence feedback / need satisfaction coherent across the loop:
# stимул -> действие -> результат -> валентность -> потребность.
ACTION_ALIASES: Dict[str, List[str]] = {
    "hypothesis": ["hypothesis", "synthesize_understanding"],
    "decomposition": ["decompose_concept", "decomposition", "think_decompose"],
    "know_answer": ["know_answer", "synthesize", "successful_action"],
    "search_miss": ["web_search", "search_miss"],
    "user_answer": ["user_answer", "ask_user", "communicate", "social_interaction"],
    "repair": ["repair", "organize_knowledge"],
    "deep_rest": ["deep_rest", "rest", "reduce_activity", "conserve_energy"],
    "checkpoint_now": ["checkpoint_now", "checkpoint"],
    "mental_model": ["synthesize", "synthesize_understanding", "teach_other"],
    "creative_act": ["creative_act", "explore", "experiment", "play"],
    "default": [
        "default", "explore", "act", "creative_act", "experiment", "reflect",
        "self_reflect", "set_own_goal", "make_choice", "propose_alternative",
    ],
}


class UnifiedMotivationSystem:
    def __init__(self, agent):
        self.agent = agent
        self.needs: Dict[str, Need] = {name: Need(**vars(template)) 
                                        for name, template in DEFAULT_NEEDS.items()}
        self.drives: Dict[str, Drive] = {name: Drive(**vars(template)) 
                                          for name, template in DEFAULT_DRIVES.items()}
        self.goal_history: List[dict] = []
        self.last_generated_cycle: int = 0
        self._needs_state_cache: Dict[str, float] = {}
        logger.log("[MOTIVATION] UnifiedMotivationSystem initialized")
    
    def tick(self, context: Dict = None):
        context = context or {}
        for need in self.needs.values():
            need.tick()
        self._apply_contextual_modifiers(context)
        self._needs_state_cache = {name: need.current_level for name, need in self.needs.items()}
        for drive in self.drives.values():
            was_active = drive.is_active()
            drive.calculate_intensity(self._needs_state_cache)
            if drive.is_active() and not was_active:
                logger.log(f"[MOTIVATION] 🌟 Drive activated: {drive.label} (level={drive.current_level:.2f})")
        pressing_needs = [n for n in self.needs.values() if n.is_pressing()]
        active_drives = [d for d in self.drives.values() if d.is_active()]
        new_goals: List[dict] = []
        if (pressing_needs or active_drives) and self.last_generated_cycle != self.agent.cycle_count:
            new_goals = self.generate_goals(pressing_needs, active_drives)

        return {
            "needs_state": dict(self._needs_state_cache),
            "active_drives": [d.name for d in active_drives if d.is_active()],
            "pressing_needs": [n.name for n in pressing_needs if n.is_pressing()],
            "new_goals": new_goals,
            "last_generated_cycle": self.last_generated_cycle,
        }
    
    def _apply_contextual_modifiers(self, context: Dict):
        for concept in context.get("unknown_concepts", [])[:3]:
            self.needs["curiosity"].current_level = max(0.0, self.needs["curiosity"].current_level - 0.05)
            self.needs["play"].current_level = max(0.0, self.needs["play"].current_level - 0.03)
        for area in context.get("novel_areas", [])[:2]:
            self.needs["curiosity"].current_level = max(0.0, self.needs["curiosity"].current_level - 0.08)
        for area in context.get("weak_areas", [])[:2]:
            self.needs["competence"].current_level = max(0.0, self.needs["competence"].current_level - 0.05)
        if context.get("recent_success"):
            self.needs["competence"].satisfy(0.1)
            self.needs["autonomy"].satisfy(0.05)
        if context.get("recent_failure"):
            self.needs["competence"].frustrate(0.1)
            self.needs["autonomy"].frustrate(0.05)
    
    def on_action_result(self, action_type: str, success: bool, valence: float):
        action_keys = {action_type}
        action_keys.update(ACTION_ALIASES.get(action_type, []))
        for need in self.needs.values():
            if any(k in need.related_actions for k in action_keys):
                if success and valence > 0:
                    need.satisfy(valence * 0.5)
                    logger.log(f"[MOTIVATION] Need '{need.label}' satisfied by {action_type} (+{valence*0.5*need.growth_rate:.3f})")
                elif not success and valence < 0:
                    need.frustrate(abs(valence) * 0.3)
                    logger.log(f"[MOTIVATION] Need '{need.label}' frustrated by {action_type} ({valence:.2f})")
        self._needs_state_cache = {name: need.current_level for name, need in self.needs.items()}
        for drive in self.drives.values():
            drive.calculate_intensity(self._needs_state_cache)

    def predict_valence(self, action_type: str, context: Dict = None) -> float:
        """
        Predict expected valence (emotional value) for an action.
        
        Returns value in [-1, 1] where:
        - 1 = very positive (expected to satisfy needs)
        - 0 = neutral
        - -1 = very negative (expected to frustrate needs)
        
        Uses heuristic based on which needs the action relates to and their current deficits.
        """
        if context is None:
            context = {}
        
        # Base valence by action type (heuristic defaults)
        action_valence_map = {
            "hypothesis": 0.7,      # Curiosity satisfaction
            "decomposition": 0.6,   # Learning
            "explore": 0.7,         # Curiosity
            "ask_question": 0.6,    # Curiosity
            "web_search": 0.5,      # Information seeking
            "synthesize": 0.6,      # Competence
            "decompose_concept": 0.6, # Competence
            "deep_rest": 0.8,       # Restores energy/embodiment
            "eat": 0.7,             # Restores energy
            "repair": 0.6,          # Integrity/survival
            "checkpoint_now": 0.3,  # Safety
            "set_own_goal": 0.7,    # Autonomy
            "make_choice": 0.6,     # Autonomy
            "refuse_action": 0.5,   # Autonomy
            "teach_other": 0.7,     # Connection/Competence
            "propose_alternative": 0.5,
            "act": 0.4,
            "know_answer": 0.5,
            "search_miss": -0.3,    # Frustration
            "user_answer": 0.4,
            "default": 0.1,
        }
        
        base_valence = action_valence_map.get(action_type, 0.1)
        
        # Adjust based on current need deficits
        # If action relates to a pressing need, valence should be higher
        related_need_bonus = 0.0
        for need in self.needs.values():
            if action_type in need.related_actions:
                deficit = need.deficit()
                if deficit > 0.3:  # Need is pressing
                    related_need_bonus += deficit * 0.3
        
        # Adjust based on energy level (low energy = lower valence for costly actions)
        energy_level = context.get("energy", 100)
        max_energy = context.get("max_energy", 150)
        energy_ratio = energy_level / max_energy if max_energy > 0 else 1.0
        
        if energy_ratio < 0.3:
            # Low energy - costly actions less appealing
            if action_type in ["hypothesis", "decomposition", "explore", "web_search"]:
                base_valence *= 0.7
        
        predicted = base_valence + related_need_bonus
        return max(-1.0, min(1.0, predicted))

    def compute_actual_valence(self, action_type: str, action_result: str, success: bool, context: Dict = None) -> float:
        """
        Compute actual valence from action outcome.
        
        Uses result string and success flag to determine valence.
        """
        if context is None:
            context = {}
        
        # Start with predicted valence as baseline
        predicted = self.predict_valence(action_type, context)
        
        # Adjust based on actual outcome
        if success:
            # Successful action - positive valence
            if "error" not in action_result.lower() and "fail" not in action_result.lower():
                actual = predicted + 0.2  # Boost for success
            else:
                actual = predicted - 0.2  # Partial success
        else:
            # Failed action - negative valence
            actual = predicted - 0.5
        
        # Clamp to [-1, 1]
        return max(-1.0, min(1.0, actual))
    
    def on_concept_learned(self, concept: str, confidence: float):
        self.needs["curiosity"].satisfy(0.3 * confidence)
        self.needs["competence"].satisfy(0.2 * confidence)
    
    def on_social_interaction(self, positive: bool = True):
        if positive:
            self.needs["connection"].satisfy(0.25)
        else:
            self.needs["connection"].frustrate(0.1)
    
    def on_creative_act(self, novelty: float):
        self.needs["play"].satisfy(0.3 * novelty)
        self.needs["autonomy"].satisfy(0.1 * novelty)
    
    def on_goal_achieved(self, goal_title: str):
        for entry in reversed(self.goal_history):
            if entry["goal"] == goal_title:
                need_name = entry.get("need")
                drive_name = entry.get("drive")
                if need_name and need_name in self.needs:
                    self.needs[need_name].satisfy(0.4)
                if drive_name and drive_name in self.drives:
                    self.drives[drive_name].activation_count += 1
                break
    
    def generate_goals(self, pressing_needs: List[Need] = None, active_drives: List[Drive] = None) -> List[dict]:
        pressing_needs = pressing_needs or [n for n in self.needs.values() if n.is_pressing()]
        active_drives = active_drives or [d for d in self.drives.values() if d.is_active()]
        goals = []
        for need in pressing_needs:
            goal = self._generate_goal_for_need(need)
            if goal:
                goals.append(goal)
        for drive in active_drives:
            goal = self._generate_goal_for_drive(drive)
            if goal:
                goals.append(goal)
        goals.sort(key=lambda g: g.get("priority", 0), reverse=True)
        for goal in goals:
            self.goal_history.append({
                "cycle": self.agent.cycle_count,
                "need": goal.get("need"),
                "drive": goal.get("drive"),
                "goal": goal["title"],
                "priority": goal.get("priority", 0)
            })
            logger.log(f"[MOTIVATION] 🎯 Goal: {goal['title']} (need={goal.get('need')}, drive={goal.get('drive')}, priority={goal.get('priority', 0):.2f})")
        self.last_generated_cycle = self.agent.cycle_count
        return goals

    # ============================================================
    # P1.1: Кандидаты действий для DecisionArbitrator
    # ============================================================
    def get_action_candidates(self, context: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Возвращает список кандидатов действий на основе текущих потребностей и драйвов.
        
        Используется DecisionArbitrator.choose_action() для выбора наилучшего действия.
        
        Args:
            context: Дополнительный контекст (energy, cycle, etc.)
            
        Returns:
            Список кандидатов:
            [
                {"source": "motivation", "action": "ask_question", "strength": 0.8, 
                 "params": {"topic": "python"}, "need": "curiosity", "priority": 0.9},
                ...
            ]
        """
        context = context or {}
        candidates = []
        
        # 1. Кандидаты от нажимающих потребностей (pressing needs)
        pressing_needs = [n for n in self.needs.values() if n.is_pressing()]
        for need in pressing_needs:
            # Сила = urgency потребности (0-1+)
            strength = min(1.0, need.urgency())
            if strength < 0.1:
                continue
                
            # Определяем действие на основе related_actions потребности
            for action_hint in need.related_actions[:2]:  # топ-2 действия
                candidates.append({
                    "source": "motivation",
                    "action": action_hint,
                    "strength": strength,
                    "params": {"need": need.name, "concept": self._pick_relevant_concept(need.related_concepts)},
                    "need": need.name,
                    "priority": strength,
                    "type": "need_driven"
                })
        
        # 2. Кандидаты от активных драйвов
        active_drives = [d for d in self.drives.values() if d.is_active()]
        for drive in active_drives:
            # Сила = уровень активации драйва
            strength = min(1.0, drive.current_level)
            if strength < 0.15:
                continue
                
            # Действия из goal_types драйва (если есть) или related_actions нужд
            action_hints = drive.goal_types if hasattr(drive, 'goal_types') and drive.goal_types else []
            if not action_hints:
                # Фоллбэк: действия из контрибьютинг нужд
                for need_name in drive.contributing_needs:
                    if need_name in self.needs:
                        action_hints.extend(self.needs[need_name].related_actions)
            
            for action_hint in action_hints[:2]:
                candidates.append({
                    "source": "motivation",
                    "action": action_hint,
                    "strength": strength * 0.8,  # драйвы чуть слабее нужд
                    "params": {"drive": drive.name, "concept": self._pick_relevant_concept(list(drive.contributing_needs.keys()))},
                    "drive": drive.name,
                    "priority": strength * 0.8,
                    "type": "drive_driven"
                })
        
        # 3. Если нет нажимающих нужд/драйвов — базовый исследовательский кандидат
        if not candidates:
            candidates.append({
                "source": "motivation",
                "action": "explore",
                "strength": 0.3,
                "params": {"reason": "no_pressing_needs"},
                "need": "curiosity",
                "priority": 0.3,
                "type": "default_exploration"
            })
        
        # Сортируем по приоритету (убывание)
        candidates.sort(key=lambda c: c.get("priority", 0), reverse=True)
        
        # Ограничиваем количество кандидатов (топ-5)
        return candidates[:5]
    
    def _generate_goal_for_need(self, need: Need) -> Optional[dict]:
        templates = NEED_GOAL_TEMPLATES.get(need.name, [])
        if not templates:
            return None
        template = random.choice(templates)
        concept = self._pick_relevant_concept(need.related_concepts)
        title = template["title"].format(
            concept=concept, question=concept, skill=concept, topic=concept,
            area=concept, target=concept, options="вариант А / вариант Б",
            idea=concept, domain=concept, conflict="неопределено", territory=concept
        )
        priority = need.urgency()
        return {
            "title": title, "type": template["type"], "need": need.name,
            "drive": None, "priority": priority, "source": "need",
            "action_hint": template.get("action"),
            "metadata": {"need_urgency": need.urgency(), "need_deficit": need.deficit()}
        }
    
    def _generate_goal_for_drive(self, drive: Drive) -> Optional[dict]:
        templates = DRIVE_GOAL_TEMPLATES.get(drive.name, [])
        if not templates:
            return None
        template = random.choice(templates)
        concept = self._pick_relevant_concept(list(drive.contributing_needs.keys()))
        title = template["title"].format(
            domain=concept, concepts=concept, topic=concept, skill=concept,
            territory=concept, question=concept
        )
        priority = drive.current_level * 0.8
        return {
            "title": title, "type": template["type"], "need": None,
            "drive": drive.name, "priority": priority, "source": "drive",
            "action_hint": template.get("action"),
            "metadata": {"drive_level": drive.current_level}
        }
    
    def _pick_relevant_concept(self, related_concepts: List[str]) -> str:
        if not related_concepts:
            return "неизвестная область"
        for concept in related_concepts:
            if concept in self.agent.knowledge_base:
                return concept
        for concept in related_concepts:
            if concept in getattr(self.agent, 'beliefs', {}):
                return concept
        return related_concepts[0]
    
    def get_status(self) -> dict:
        pressing = [n for n in self.needs.values() if n.is_pressing()]
        active = [d for d in self.drives.values() if d.is_active()]
        return {
            "needs": {name: need.to_dict() for name, need in self.needs.items()},
            "drives": {name: drive.to_dict() for name, drive in self.drives.items()},
            "most_pressing_need": max(self.needs.values(), key=lambda n: n.urgency()).name if self.needs else None,
            "active_drives": [d.name for d in active],
            "pressing_needs": [n.name for n in pressing],
            "goals_generated": len(self.goal_history),
            "last_generated_cycle": self.last_generated_cycle
        }
    
    def get_most_pressing_need(self) -> Optional[Need]:
        pressing = [n for n in self.needs.values() if n.is_pressing()]
        if not pressing:
            return None
        return max(pressing, key=lambda n: n.urgency())
    
    def get_active_drives(self) -> List[Drive]:
        return [d for d in self.drives.values() if d.is_active()]
    
    def to_checkpoint_dict(self) -> Dict:
        return {
            "needs": {name: {
                "name": need.name, "label": need.label, "base_level": need.base_level,
                "current_level": need.current_level, "decay_rate": need.decay_rate,
                "growth_rate": need.growth_rate, "threshold": need.threshold,
                "priority": need.priority,
                "related_concepts": need.related_concepts,
                "related_actions": need.related_actions
            } for name, need in self.needs.items()},
            "drives": {name: {
                "name": drive.name, "label": drive.label,
                "contributing_needs": drive.contributing_needs,
                "activation_threshold": drive.activation_threshold,
                "current_level": drive.current_level,
                "activation_count": drive.activation_count,
                "goal_types": drive.goal_types
            } for name, drive in self.drives.items()},
            "goal_history": self.goal_history[-50:],
            "last_generated_cycle": self.last_generated_cycle
        }
    
    @classmethod
    def from_checkpoint_dict(cls, agent, data: Dict) -> 'UnifiedMotivationSystem':
        system = cls(agent)
        for name, need_data in data.get("needs", {}).items():
            if name in system.needs:
                need = system.needs[name]
                need.current_level = need_data.get("current_level", need.current_level)
                need.base_level = need_data.get("base_level", need.base_level)
        for name, drive_data in data.get("drives", {}).items():
            if name in system.drives:
                drive = system.drives[name]
                drive.current_level = drive_data.get("current_level", 0.0)
                drive.activation_count = drive_data.get("activation_count", 0)
        system.goal_history = data.get("goal_history", [])
        system.last_generated_cycle = data.get("last_generated_cycle", 0)
        return system


def create_motivation_system(agent) -> UnifiedMotivationSystem:
    return UnifiedMotivationSystem(agent)