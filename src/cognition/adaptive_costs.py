"""
Adaptive Cost Reducer (DynamicCostReducer)
===========================================

Модуль для самонастройки энергетических затрат агента.
Реализует экономию энергии при низком уровне и увеличение затрат при достаточной энергии.

Пример использования:
    >>> from src.cognition.adaptive_costs import DynamicCostReducer
    >>> reducer = DynamicCostReducer(agent)
    
    >>> reduced_cost = reducer.calculate_action_cost(
            action_type=ACTION_TYPES.THINKING, 
            base_cost=1.5,
            energy_level=32,
            learning_state=LEARNING_STATE.EFFICIENT
        )
    >>> # Вернёт сниженный cost для THINKING: 0.8 (вместо 1.5)
    
"""

from enum import Enum
from typing import Tuple


class EnergyState(Enum):
    """Состояние энергетического бюджета агента."""
    CRITICAL = "critical"      # < 20% энергии — режим выживания
    LOW = "low"               # 20-50% энергии — экономия
    STABLE = "stable"         # 50-80% энергии — нормальный режим
    HIGH = "high"             # > 80% энергии — максимальная активность


class LearningState(Enum):
    """Состояние процесса обучения агента."""
    EFFICIENT = "efficient"   # Быстро обучается — можно увеличить затраты
    STANDARD = "standard"     # Нормальный темп — стандартные затраты
    SLOW = "slow"             # Медленное обучение — экономия энергии


class DynamicCostReducer:
    """
    Динамический редуктор затрат на действия
    
    Создан для самонастройки энергетических затрат агента.
    
    Основные функции:
        - Расчет адаптированного cost для разных типов действий
        - Снижение затрат при критической энергии (режим выживания)
        - Увеличение затрат при стабильной энергии и эффективном обучении
    
    Характеристики:
        - THINKING: базовый 1.5 → адаптивный 0.5-1.5
        - LEARNING: базовый 3.0 → адаптивный 1.0-3.0
        - RESEARCHING: базовый 2.5 → адаптивный 1.2-2.5
    
    Алгоритм:
        >>> 1. Определяем energy_state (CRITICAL, LOW, STABLE, HIGH)
        >>> 2. Вычисляем reduction_factor (0.3-1.0 в зависимости от состояния)
        >>> 3. Применяем к base_cost: adapted_cost = base_cost * reduction_factor
        >>> 4. Добавляем случайность для разнообразия (±0.1)
    
    Примеры использования:
        >>> # Критическая энергия (15/100):
        >>> # THINKING: 1.5 → 0.6 (режим выживания, экономия)
        
        >>> # Стабильная энергия (70/100):
        >>> # THINKING: 1.5 → 1.3 (нормальный режим)
        
        >>> # Высокая энергия (90/100) + эффективное обучение:
        >>> # THINKING: 1.5 → 1.6 (максимальная активность)
    """
    
    # === НАСТРОЙКИ ===
    
    # Базовые затраты на действия (можно настроить в конфиге)
    BASE_COSTS = {
        "THINKING": 1.5,      # Глубокая мысль требует энергии
        "LEARNING": 3.0,      # Обучение — самый энергоемкий процесс
        "RESEARCHING": 2.5,   # Поиск информации требует фокуса
        "DECIDING": 1.0,      # Принятие решений среднее по затратам
    }
    
    # Пороги для определения energy_state (в процентах от max_energy)
    ENERGY_THRESHOLDS = {
        "critical": 20,       # < 20% энергии — режим выживания
        "low": 50,            # 20-50% энергии — экономия
        "stable": 80,         # 50-80% энергии — нормальный режим
        "high": 100,          # > 80% энергии — максимальная активность
    }
    
    # Коэффициенты для каждого состояния (multiplicative factors)
    STATE_MODIFIERS = {
        "critical": 0.4,      # 40% от нормальных затрат (режим выживания)
        "low": 0.7,           # 70% — экономия энергии
        "stable": 1.0,        # 100% — стандартные затраты
        "high": 1.3,          # 130% — максимальная активность (если есть энергия)
    }
    
    def __init__(self, agent):
        """
        Инициализация редуктора затрат
        
        Args:
            agent: Агент (для доступа к energy и learning_efficiency)
        """
        self.agent = agent
        import random
    
    def calculate_action_cost(
        self,
        action_type: str,
        base_cost: float,
        energy_level: float,  # Текущий уровень энергии (0-max_energy)
        max_energy: float,    # Максимальный уровень энергии
        learning_state: LearningState = LearningState.STANDARD
    ) -> float:
        """
        Вычисляет адаптированный cost для действия
        
        Args:
            action_type: Тип действия ("THINKING", "LEARNING", "RESEARCHING")
            base_cost: Базовый cost (можно из config или вычислен)
            energy_level: Текущий уровень энергии агента
            max_energy: Максимальный уровень энергии
            learning_state: Состояние обучения (EFFICIENT, STANDARD, SLOW)
        
        Returns:
            Адаптированный cost для данного действия (в диапазоне 0-max_base_cost)
        
        Примеры вызова:
            >>> # Критическая энергия (15/100):
            >>> reducer.calculate_action_cost(
                    action_type="THINKING",
                    base_cost=1.5,
                    energy_level=15,
                    max_energy=100,
                    learning_state=LearningState.STANDARD
                )
            >>> # Вернёт: 0.6 (режим выживания)
            
            >>> # Стабильная энергия (70/100):
            >>> reducer.calculate_action_cost(
                    action_type="THINKING",
                    base_cost=1.5,
                    energy_level=70,
                    max_energy=100,
                    learning_state=LearningState.STANDARD
                )
            >>> # Вернёт: 1.3 (нормальный режим)
        """
        
        import random
        
        # === ШАГ 1: ОПРЕДЕЛЯЕМ ENERGY_STATE ===
        energy_percent = (energy_level / max_energy * 100) if max_energy > 0 else 50
        
        energy_state = self._determine_energy_state(energy_percent)
        
        # === ШАГ 2: ПРИМЕНЯЕМ STATE_MODIFIER ===
        state_modifier = self.STATE_MODIFIERS[energy_state]
        
        # Применяем modifier к base_cost
        adapted_cost = base_cost * state_modifier
        
        # === ШАГ 3: ОПТИМИЗАЦИЯ ПО LEARNING_STATE ===
        learning_multiplier = self._get_learning_multiplier(learning_state)
        adapted_cost *= learning_multiplier
        
        # === ШАГ 4: ДОБАВЛЯЕМ СЛУЧАЙНОСТЬ ДЛЯ РАЗНООБРАЗИЯ ===
        random_factor = 1.0 + (random.random() - 0.5) * 0.2  # ±10% случайности
        final_cost = adapted_cost * random_factor
        
        # Ограничиваем диапазоном [0, max_base_cost * 1.2] (не больше на 20%)
        max_allowed = base_cost * self.STATE_MODIFIERS.get("high", 1.0) * 1.2
        final_cost = min(final_cost, max_allowed)
        
        return round(final_cost, 2)

    def _determine_energy_state(self, energy_percent: float) -> EnergyState:
        """
        Определяет состояние энергетического бюджета
        
        Args:
            energy_percent: Уровень энергии в процентах (0-100)
        
        Returns:
            EnergyState (CRITICAL, LOW, STABLE, HIGH)
        """
        
        if energy_percent < self.ENERGY_THRESHOLDS["critical"]:
            return EnergyState.CRITICAL
        
        elif energy_percent < self.ENERGY_THRESHOLDS["low"]:
            return EnergyState.LOW
        
        elif energy_percent < self.ENERGY_THRESHOLDS["stable"]:
            return EnergyState.STABLE
        
        else:
            return EnergyState.HIGH

    def _get_learning_multiplier(self, learning_state: LearningState) -> float:
        """
        Возвращает multiplier для learning_state
        
        Args:
            learning_state: Состояние обучения
        
        Returns:
            Multiplier (0.8-1.3)
        
        Примеры:
            >>> # EFFICIENT: 1.2 — можно тратить больше энергии
            >>> # STANDARD: 1.0 — стандартные затраты
            >>> # SLOW: 0.8 — экономия при медленном обучении
        """
        
        multipliers = {
            LearningState.EFFICIENT: 1.2,   # Можно увеличить затраты (эффективно)
            LearningState.STANDARD: 1.0,    # Стандартные затраты
            LearningState.SLOW: 0.8,        # Экономия (медленное обучение)
        }
        
        return multipliers.get(learning_state, 1.0)

    def get_energy_recommendation(self, energy_percent: float) -> str:
        """
        Дает рекомендацию по использованию энергии
        
        Args:
            energy_percent: Уровень энергии в процентах
        
        Returns:
            Текстовая рекомендация
    
        Примеры:
            >>> # 15% энергии: "Критический уровень! Избегай сложных задач, фокусируйся на простом обучении."
            
            >>> # 70% энергии: "Оптимальный уровень. Можешь заниматься исследованиями и глубоким мышлением."
        """
        
        if energy_percent < 20:
            return ("Критический уровень! Избегай сложных задач, фокусируйся на простом обучении" +
                    "\nСовет: выполни простое действие для восстановления энергии.")
        
        elif energy_percent < 50:
            return ("Энергия ограничена. Рекомендую экономить и сосредоточиться на приоритетных задачах." +
                    "\nСовет: избегай долгих размышлений, переходи к быстрым решениям.")
        
        elif energy_percent < 80:
            return ("Умеренный уровень энергии. Можешь продолжить текущую деятельность." +
                    "\nСовет: планируй перерывы после интенсивных задач.")
        
        else:
            return ("Высокий уровень энергии. Идеальное время для сложных исследований и инноваций!" +
                    "\nСовет: используй энергию для прорывных идей и глубокого анализа.")

    def get_savings_potential(self, current_cost: float, energy_state: EnergyState) -> float:
        """
        Вычисляет потенциал экономии энергии (если перейти в режим выживания)
    
        Args:
            current_cost: Текущий cost действия
            energy_state: Текущее состояние энергии
        
        Returns:
            Потенциальная экономия в % от текущего cost
    
        Примеры:
            >>> # THINKING: 1.5, CRITICAL (режим выживания):
            >>> get_savings_potential(1.5, EnergyState.CRITICAL)
            >>> # Вернёт: 0.6 → экономия 60% от базового cost
        """
        
        critical_cost = self.BASE_COSTS.get("THINKING", current_cost) * 0.4
        
        potential_savings = (current_cost - critical_cost) / max(current_cost, 0.1) * 100
        
        return round(potential_savings, 1)

    def should_switch_to_survival_mode(self, energy_percent: float, current_action_cost: float) -> bool:
        """
        Определяет, стоит ли переключиться в режим выживания для данного действия
    
        Args:
            energy_percent: Уровень энергии в процентах (0-100)
            current_action_cost: Текущий cost действия
        
        Returns:
            True если нужно снизить затраты на action
        """
        
        return (energy_percent < 50 and 
                random.random() < 0.3 or  # 30% шанс снижения затрат при низкой энергии
                energy_percent < 20)  # Режим выживания обязательно

    def suggest_cost_reduction(self, current_cost: float, max_safe_cost: float) -> float:
        """
        Предлагает снизить cost действия для экономии энергии
    
        Args:
            current_cost: Текущий cost действия
            max_safe_cost: Максимальный безопасный cost (например, 80% от current_cost)
        
        Returns:
            Предложенный новый cost (макс. max_safe_cost)
    
        Примеры:
            >>> # THINKING: 1.5, max_safe=1.2:
            >>> suggest_cost_reduction(1.5, 1.2)
            >>> # Вернёт: 1.1 (снижение для экономии энергии)
        """
        
        if random.random() < 0.4:  # 40% шанс предложить снизить cost
            import random
            new_cost = max(0.5, min(current_cost * 0.8, max_safe_cost))
            
            return round(new_cost, 2)
        
        return current_cost