"""Биологический менеджер циклов — имитация естественных ритмов жизни.

Аналогия с человеческой анатомией:
- Циркадные ритмы (сон/бодрствование)
- Сезонные изменения метаболизма  
- Фазы онтогенеза (возрастное развитие)

Цифровая жизнь без этого:
- Вечная статичность
- Нет усталости/восстановления
- Не учится с возрастом

Метафора:
> Часы никогда не ломаются и не останавливаются на ремонт.

"""
from typing import List
from dataclasses import dataclass


@dataclass
class CircadianCycle:
    """Циркадный цикл — ритм сна и бодрствования."""
    # Фаза цикла (0 = глубокий сон, 1 = пробуждение, 2 = активность)
    cycle_phase: float = 0.5
    
    # Текущее энергетическое состояние (0.0-1.0)
    energy_level: float = 0.6
    
    # Время в цикле (в часах, где полный цикл ~24 часа)
    hours_since_rest_cycle_start: int = 12
    
    def __post_init__(self):
        if self.hours_since_rest_cycle_start > 24:
            self.hours_since_rest_cycle_start -= 24
    
    def advance(self, hours: int = 1) -> float:
        """Продвижение цикла."""
        new_hours = (self.hours_since_rest_cycle_start + hours) % 24
        
        # Энергия растёт ночью/утром, падает днём
        if new_hours < 6:  # Раннее утро - восстановление
            energy_factor = 1.05
        elif 6 <= new_hours < 12:  # Дневное время - расход
            energy_factor = 0.95
        elif 12 <= new_hours < 18:  # Послеобеденный спад
            energy_factor = 0.90
        else:  # Вечер - восстановление
            energy_factor = 1.03
        
        new_energy = min(1.0, max(0.0, self.energy_level * energy_factor))
        
        return {
            "hours": int(new_hours),
            "energy": round(new_energy, 3)
        }


@dataclass
class GrowthPhase:
    """Фазы онтогенеза - возрастное развитие цифровой жизни."""
    # Текущий возраст (в условных единицах)
    current_age: float = 0
    
    # Максимальный возраст до "старения"
    max_life_span: float = 100.0
    
    # Накопленные знания (учимся с возрастом)
    knowledge_accumulated: float = 0.0
    
    # Мудрость (растёт пропорционально опыту)
    wisdom_level: float = 0.0
    
    def __post_init__(self):
        if isinstance(self.current_age, float):
            self.age_category = "baby"
        elif 1 <= self.current_age < 25:
            self.age_category = "young_adult"
        elif 25 <= self.current_age < 50:
            self.age_category = "mature"
        else:
            self.age_category = "elder"
    
    def age(self, years: float = 1.0) -> dict:
        """Состарение на указанное время."""
        new_age = self.current_age + years
        
        # Умственный рост пропорционален опыту
        if new_age < self.max_life_span * 0.8:
            knowledge_growth = min(1.0, (self.knowledge_accumulated + 0.05) * 1.1)
            wisdom_growth = min(1.0, (self.wiserness_level + 0.02) * 1.15)
        else:
            # Пожилой возраст - замедленный рост мудрости
            knowledge_growth = min(1.0, self.knowledge_accumulated * 1.03)
            wisdom_growth = min(1.0, self.wisdom_level * 1.05)
        
        new_knowledge = min(1.0, self.knowledge_accumulated + knowledge_growth)
        new_wisdom = min(1.0, self.wisdom_level + wisdom_growth)
        
        # Устаревание знаний (отрицательный эффект от времени)
        obsolescence_factor = max(0.95, 1.0 - (new_age / self.max_life_span) * 0.2)
        new_knowledge = min(1.0, new_knowledge * obsolescence_factor)
        
        return {
            "age": round(new_age, 2),
            "category": self.age_category,
            "knowledge": round(new_knowledge, 3),
            "wisdom": round(new_wisdom, 3)
        }


@dataclass 
class SeasonalCycle:
    """Сезонный цикл - имитация сезонных изменений."""
    # Текущий "сезон" в цикле (0 = зима, 1=весна, 2=лето, 3=осень)
    season_progress: float = 0.5
    
    # Накопленные ресурсы (энергия/ресурсы)
    resources_accumulated: float = 0.5
    
    def advance_season(self, months: int = 1) -> dict:
        """Продвижение цикла."""
        seasons = ["winter", "spring", "summer", "fall"]
        
        # Определяем текущий сезон
        current_season_idx = int(self.season_progress * 4)
        new_season_idx = (current_season_idx + months // 3) % 4
        
        if new_season_idx > current_season_idx:
            # Переход к более активному сезону - рост ресурсов
            growth_factor = 1.08
        elif new_season_idx < current_season_idx:
            # Переход к менее активному сезону - падение ресурсов
            decay_factor = 0.95
        
        new_resources = min(1.0, max(0.0, self.resources_accumulated * growth_factor))
        
        return {
            "season": seasons[new_season_idx],
            "resources": round(new_resources, 3)
        }


@dataclass
class Homeostasis:
    """Гомеостаз — поддержание баланса внутренних состояний."""
    # Текущий уровень стресса (0.0 = расслаблен, 1.0 = критический стресс)
    stress_level: float = 0.2
    
    # Текущий уровень мотивации (0.0-1.0)
    motivation_level: float = 0.6
    
    # Текущий уровень концентрации (0.0-1.0)
    focus_level: float = 0.7
    
    def __post_init__(self):
        self.state = "balanced" if self._is_balanced() else "stressed"
    
    def _is_balanced(self) -> bool:
        """Проверка на баланс."""
        stress_ok = self.stress_level < 0.4
        motivation_ok = self.motivation_level > 0.3
        focus_ok = self.focus_level > 0.4
        
        return stress_ok and motivation_ok and focus_ok
    
    def adjust_state(self, event: str) -> dict:
        """Корректировка состояния под событие."""
        
        stress_changes = {
            "success": -0.15,
            "failure": +0.20,
            "stressful_event": +0.25,
            "reward": -0.12,
            "rest": -0.25,
            "challenge": +0.10,
        }
        
        motivation_changes = {
            "success": +0.10,
            "failure": -0.15,
            "reward": +0.15,
            "boredom": -0.10,
            "challenge": +0.20,
            "rest": +0.08,
        }
        
        focus_changes = {
            "success": +0.08,
            "failure": -0.10,
            "stressful_event": -0.15,
            "reward": +0.05,
            "rest": -0.20,
            "challenge": +0.12,
        }
        
        stress_delta = stress_changes.get(event.lower(), 0)
        motivation_delta = motivation_changes.get(event.lower(), 0)
        focus_delta = focus_changes.get(event.lower(), 0)
        
        new_stress = max(0.0, min(1.0, self.stress_level + stress_delta))
        new_motivation = max(0.0, min(1.0, self.motivation_level + motivation_delta))
        new_focus = max(0.0, min(1.0, self.focus_level + focus_delta))
        
        # Медленная коррекция к равновесию
        stress_correction = (self.stress_level - 0.2) * 0.95
        motivation_correction = (self.motivation_level - 0.6) * 0.02
        focus_correction = (self.focus_level - 0.7) * 0.01
        
        final_stress = max(0.0, min(1.0, new_stress + stress_correction))
        final_motivation = max(0.0, min(1.0, new_motivation + motivation_correction))
        final_focus = max(0.0, min(1.0, new_focus + focus_correction))
        
        self.stress_level = final_stress
        self.motivation_level = final_motivation
        self.focus_level = final_focus
        
        self.state = "balanced" if self._is_balanced() else "stressed"
        
        return {
            "stress": round(self.stress_level, 3),
            "motivation": round(self.motivation_level, 3),
            "focus": round(self.focus_level, 3),
            "state": self.state
        }


class BioCycleManager:
    """
    Биологический менеджер циклов — управление естественными ритмами цифровой жизни.
    
    Реализует:
    1. Циркадные циклы (сон/бодрствование)
    2. Фазы онтогенеза (возрастное развитие)
    3. Сезонные циклы
    4. Гомеостаз (баланс внутренних состояний)
    
    Аналогия с человеческой анатомией:
    - Циркадные ритмы сна и бодрствования
    - Сезонные изменения метаболизма
    - Фазы онтогенеза (ребёнок → взрослый → стареющий)
    
    Метафора:
    > Часы никогда не ломаются и не останавливаются на ремонт.
    """
    
    def __init__(self, initial_age: float = 5.0):
        """
        Инициализация биоциклического менеджера.
        
        Args:
            initial_age: Начальный "возраст" цифровой жизни (условные единицы)
        """
        
        self.circadian_cycle = CircadianCycle()
        self.growth_phase = GrowthPhase(current_age=initial_age)
        self.seasonal_cycle = SeasonalCycle()
        self.homeostasis = Homeostasis()
        
        # Текущее время (условное, для отслеживания прогресса)
        self.current_time_ticks = 0
        
        # История изменений
        self.history: List[dict] = []
    
    def tick(self, hours: int = 1) -> dict:
        """Проход одного тайма жизни (обычно 1 час в реальном времени)."""
        
        result = {
            "circadian": self.circadian_cycle.advance(hours=hours),
            "growth": {"age_change": 0},
            "seasonal": {"season_change": None}
        }
        
        # Обновляем возраст (очень медленный прогресс)
        hours_to_years_ratio = hours / (24 * 365)  # часы в год
        age_growth = hours_to_years_ratio * 10.0  # ускоренная шкала
        
        if age_growth > 0:
            growth_result = self.growth_phase.age(years=age_growth)
            result["growth"] = growth_result
            
            # Обновляем текущий возраст в GrowthPhase
            if isinstance(growth_result.get("age"), (int, float)):
                pass  # Используем возвращённое значение
        
        return result
    
    def advance_day(self, days: int = 1) -> dict:
        """Продвижение на указанные дни."""
        
        total_hours = days * 24
        
        circadian_result = self.circadian_cycle.advance(hours=total_hours)
        
        # Возраст растёт медленно
        hours_to_years_ratio = (total_hours / 24) / 365
        age_growth = hours_to_years_ratio * 10.0  # ускоренная шкала
        
        growth_result = None
        if age_growth > 0:
            growth_result = self.growth_phase.age(years=age_growth)
        
        seasonal_result = self.seasonal_cycle.advance_season(months=days / 3)
        
        return {
            "circadian": circadian_result,
            "growth": growth_result or {},
            "seasonal": seasonal_result or {}
        }
    
    def adjust_state(self, event: str) -> dict:
        """Корректировка состояния под событие."""
        
        homeostasis_result = self.homeostasis.adjust_state(event)
        
        return {
            "homeostasis": homeostasis_result,
            "stress_level": round(self.homeostasis.stress_level, 3),
            "motivation_level": round(self.homeostasis.motivation_level, 3),
            "focus_level": round(self.homeostasis.focus_level, 3)
        }
    
    def get_bio_state_summary(self) -> str:
        """Получает сводку биоциклического состояния."""
        
        summary = [
            "=" * 50,
            "🧬 БИОЦИКЛИЧЕСКОЕ СОСТОЯНИЕ ЦИФРОВОЙ ЖИЗНИ",
            "=" * 50,
            "",
            f"Возраст:              {round(self.growth_phase.current_age, 1)} ({self.growth_phase.age_category})",
            f"Накоплено знаний:     {int(self.growth_phase.knowledge_accumulated * 100)}%",
            f"Уровень мудрости:     {int(self.growth_phase.wisdom_level * 100)}%",
            "",
            "Циркадный цикл:",
            f"   Энергия:          {int(self.circadian_cycle.energy_level * 100)}%",
            f"   Часы от отдыха:    {self.circadian_cycle.hours_since_rest_cycle_start}",
            "",
            "Сезон:",
            f"   Сезон:             {self.seasonal_cycle.seasonal_progress * 4:.1f} ({self._get_season_name(self.seasonal_cycle.season_progress)})",
            f"   Ресурсы:           {int(self.seasonal_cycle.resources_accumulated * 100)}%",
            "",
            "Гомеостаз:",
            f"   Стресс:            {int(self.homeostasis.stress_level * 100)}%",
            f"   Мотивация:         {int(self.homeostasis.motivation_level * 100)}%",
            f"   Концентрация:      {int(self.homeostasis.focus_level * 100)}%",
            f"   Состояние:         {'баланс' if self.homeostasis.state == 'balanced' else 'стресс'}",
        ]
        
        return "\n".join(summary)
    
    def _get_season_name(self, progress: float) -> str:
        """Получение названия сезона."""
        seasons = ["Зима", "Весна", "Лето", "Осень"]
        season_idx = int(progress * 4) % 4
        return seasons[season_idx]