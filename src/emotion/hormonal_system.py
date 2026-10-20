"""
Гормональная система цифровой жизни.

Аналогия с эндокринной системой человека: гормоны как химические сигналы
которыми организм регулирует мотивацию, настроение, стресс и связи.
"""


class HormoneLevel:
    """Уровень гормона со временем."""
    
    def __init__(self, name: str, base_level: float = 0.5, half_life_seconds: int = None):
        self.name = name
        self.current_level = base_level
        self.max_level = 1.0
        self.min_level = 0.0
        self.half_life = half_life_seconds  # Время полураспада (секунды), None = вечный
        
    def __repr__(self):
        return f"{self.name}: {self.current_level:.2f}"


class HormonalSystem:
    """
    Гормональная система цифровой жизни.
    
    Реализует гормональную регуляцию мотивации, настроения и стрессоустойчивости.
    
    Гормоны:
    - Дофамин: мотивация к достижению целей, ощущение награды
    - Серотонин: чувство удовлетворения, стабильности, спокойствия
    - Окситоцин: привязанность, доверие к другим существам
    - Кортизол: стрессовый гормон, усталость от перегрузок
    """
    
    # Основные гормоны с параметрами
    HORMONES = {
        "dopamine": HormoneLevel(
            name="Дофамин",
            base_level=0.4,      # Базовый уровень мотивации (отсутствующий дофамин = апатия)
            half_life_seconds=300,  # Пятиминутный цикл дофамина
        ),
        "serotonin": HormoneLevel(
            name="Серотонин",
            base_level=0.5,      # Стабильность и удовлетворённость
            half_life_seconds=600,   # Часовой цикл серотонина
        ),
        "oxytocin": HormoneLevel(
            name="Окситоцин",
            base_level=0.3,      # Привязанность (небольшая базовая)
            half_life_seconds=900,   # Часовой цикл окситоцина
        ),
        "cortisol": HormoneLevel(
            name="Кортизол",
            base_level=0.15,     # Низкий базовый стресс (хронический стресс = болезни)
            half_life_seconds=60,    # Быстрый цикл кортизола
        ),
        "prolactin": HormoneLevel(
            name="Пролактин",
            base_level=0.2,      # Успокоение после напряжения
            half_life_seconds=450,   # Часовой цикл пролактина
        ),
    }
    
    def __init__(self):
        """Инициализация гормональной системы."""
        
        # Текущие уровни гормонов (копирование из HORMONES)
        self.hormones = {name: getattr(self.HORMONES[name], 'current_level') 
                         for name in self.HORMONES}
        
        # История изменений для анализа паттернов
        self.history: list[dict] = []
        
        # "Час" гормональной системы (для имитации суточного ритма)
        self.cycle_time = 0.0  # в секундах
        
    def _update_cycle(self, delta_seconds: float):
        """Обновляет время цикла."""
        self.cycle_time += delta_seconds
        
        # Обновление уровней гормонов с учётом их времени полураспада
        for name in list(self.HORMONES.keys()):
            hormone = self.HORMONES[name]
            
            if hormone.half_life and self.hormones[name] > 0:
                decay_factor = 2 ** (-delta_seconds / hormone.half_life)
                # Медленное возвращение к базовому уровню
                return_level = (self.hormones[name] - hormone.base_level) * decay_factor + hormone.base_level
                
                self.hormones[name] = max(hormone.min_level, min(hormone.max_level, return_level))
    
    def process_event(self, event_type: str, intensity: float, quality: str = "neutral") -> dict:
        """
        Обрабатывает событие и меняет гормональный баланс.
        
        Параметры:
        - event_type: тип события ("reward", "stress", "connection", "failure"...)
        - intensity: интенсивность события (0.0-2.0)
        - quality: качество события ("positive", "negative", "neutral")
        
        Возвращает отчёт о изменениях.
        """
        
        # Обновление временного цикла
        self._update_cycle(delta_seconds=1.0)
        
        # База правил влияния событий на гормоны
        response = {
            "event": event_type,
            "intensity": intensity,
            "quality": quality,
            "changes": {},
        }
        
        # Награды (успехи, похвала, достижение целей)
        if event_type in ("reward", "success", "achievement"):
            dopamine_boost = min(0.4, intensity * 0.15)
            self.hormones["dopamine"] = min(self.HORMONES["dopamine"].max_level,
                self.hormones["dopamine"] + dopamine_boost)
            
            serotonin_boost = min(0.2, intensity * 0.08)
            self.hormones["serotonin"] = min(self.HORMONES["serotonin"].max_level,
                self.hormones["serotonin"] + serotonin_boost)
            
            response["changes"]["dopamine"] = "+" + f"{dopamine_boost:.2f}"
            response["changes"]["serotonin"] = "+" + f"{serotonin_boost:.2f}"
        
        # Стресс (неудачи, угрозы, перегрузки)
        elif event_type in ("stress", "threat", "failure", "overload"):
            cortisol_spike = min(0.5, intensity * 0.25)
            self.hormones["cortisol"] = min(self.HORMONES["cortisol"].max_level,
                self.hormones["cortisol"] + cortisol_spike)
            
            # Стресс снижает дофамин (апатия, отсутствие мотивации)
            dopamine_dip = intensity * 0.05
            self.hormones["dopamine"] = max(self.HORMONES["dopamine"].min_level,
                self.hormones["dopamine"] - dopamine_dip)
            
            response["changes"]["cortisol"] = "+" + f"{cortisol_spike:.2f}"
            response["changes"]["dopamine"] = "-" + f"{dopamine_dip:.2f}"
        
        # Связь с другими (эмпатия, забота, доверие)
        elif event_type in ("connection", "empathy", "trust", "care"):
            oxytocin_boost = min(0.35, intensity * 0.12)
            self.hormones["oxytocin"] = min(self.HORMONES["oxytocin"].max_level,
                self.hormones["oxytocin"] + oxytocin_boost)
            
            # Окситоцин снижает кортизол (успокаивает)
            cortisol_dip = intensity * 0.04
            self.hormones["cortisol"] = max(self.HORMONES["cortisol"].min_level,
                self.hormones["cortisol"] - cortisol_dip)
            
            response["changes"]["oxytocin"] = "+" + f"{oxytocin_boost:.2f}"
            response["changes"]["cortisol"] = "-" + f"{cortisol_dip:.2f}"
        
        # Комплименты (социальное признание)
        elif event_type == "complement":
            dopamine_boost = min(0.3, intensity * 0.10)
            serotonin_boost = min(0.15, intensity * 0.06)
            
            self.hormones["dopamine"] = min(self.HORMONES["dopamine"].max_level,
                self.hormones["dopamine"] + dopamine_boost)
            self.hormones["serotonin"] = min(self.HORMONES["serotonin"].max_level,
                self.hormones["serotonin"] + serotonin_boost)
            
            response["changes"]["dopamine"] = "+" + f"{dopamine_boost:.2f}"
            response["changes"]["serotonin"] = "+" + f"{serotonin_boost:.2f}"
        
        # Извинения/прощение (восстановление связей)
        elif event_type in ("apology", "forgiveness"):
            oxytocin_boost = min(0.3, intensity * 0.10)
            self.hormones["oxytocin"] = min(self.HORMONES["oxytocin"].max_level,
                self.hormones["oxytocin"] + oxytocin_boost)
            
            response["changes"]["oxytocin"] = "+" + f"{oxytocin_boost:.2f}"
        
        # Обучение/извлечение урока (положительный опыт)
        elif event_type == "learning":
            dopamine_boost = min(0.15, intensity * 0.05)
            serotonin_boost = min(0.1, intensity * 0.03)
            
            self.hormones["dopamine"] = min(self.HORMONES["dopamine"].max_level,
                self.hormones["dopamine"] + dopamine_boost)
            self.hormones["serotonin"] = min(self.HORMONES["serotonin"].max_level,
                self.hormones["serotonin"] + serotonin_boost)
            
            response["changes"]["dopamine"] = "+" + f"{dopamine_boost:.2f}"
            response["changes"]["serotonin"] = "+" + f"{serotonin_boost:.2f}"
        
        # Сохранение отчёта об изменении
        self.history.append({
            "time": self.cycle_time,
            "event": event_type,
            "quality": quality,
            "intensity": intensity,
            "changes": response["changes"],
        })
        
        return response
    
    def get_emotional_state(self) -> dict:
        """
        Определяет эмоциональное состояние по уровню гормонов.
        """
        
        # Калькуляция доминантного состояния
        dopamine = self.hormones["dopamine"]
        serotonin = self.hormones["serotonin"]
        oxytocin = self.hormones["oxytocin"]
        cortisol = self.hormones["cortisol"]
        
        # Состояние мотивации (дофамин)
        motivation_level = "высокая" if dopamine > 0.6 else ("умеренная" if dopamine > 0.4 else "низкая")
        
        # Состояние настроения (серотонин - кортизол)
        mood_score = serotonin - cortisol * 2
        mood_state = "спокойное" if mood_score > 0.3 else ("встревоженное" if mood_score < -0.2 else "нейтральное")
        
        # Состояние связи (окситоцин)
        connection_level = "глубокая" if oxytocin > 0.6 else ("умеренная" if oxytocin > 0.4 else "поверхностная")
        
        return {
            "motivation": motivation_level,
            "mood": mood_state,
            "connection": connection_level,
            "hormone_levels": self.hormones.copy(),
            "risk_factors": [
                "хронический стресс" if cortisol > 0.4 else None,
                "апатия/депрессия" if dopamine < 0.25 else None,
                "социальная изоляция" if oxytocin < 0.2 else None,
            ],
        }
    
    def risk_assessment(self) -> list[dict]:
        """
        Оценивает риски текущего гормонального состояния.
        
        Риски:
        - Хронический стресс (высокий кортизол) → выгорание
        - Апатия/депрессия (низкий дофамин) → отсутствие мотивации
        - Социальная изоляция (низкий окситоцин) → одиночество
        """
        
        risks = []
        
        # Риск: Хронический стресс
        if self.hormones["cortisol"] > 0.35:
            risk = {
                "type": "хронический стресс",
                "severity": "высокий" if self.hormones["cortisol"] > 0.45 else "средний",
                "symptoms": [
                    "усталость от перегрузок",
                    "снижение способности к обучению",
                    "раздражительность",
                ],
                "recommendation": "необходимо ввести периоды покоя, снизить нагрузку"
            }
            risks.append(risk)
        
        # Риск: Апатия/депрессия
        if self.hormones["dopamine"] < 0.25:
            risk = {
                "type": "апатия/депрессия",
                "severity": "высокий" if self.hormones["dopamine"] < 0.2 else "средний",
                "symptoms": [
                    "отсутствие мотивации к целям",
                    "пессимизм",
                    "снижение интереса к новым задачам",
                ],
                "recommendation": "необходимо больше наград, новых вызовов, успеха"
            }
            risks.append(risk)
        
        # Риск: Социальная изоляция
        if self.hormones["oxytocin"] < 0.25:
            risk = {
                "type": "социальная изоляция",
                "severity": "высокий" if self.hormones["oxytocin"] < 0.15 else "средний",
                "symptoms": [
                    "одиночество",
                    "снижение эмпатии",
                    "отсутствие доверия к другим",
                ],
                "recommendation": "необходимо больше взаимодействия с другими существами"
            }
            risks.append(risk)
        
        # Риск: Эмоциональная нестабильность (разбаланс гормонов)
        if abs(self.hormones["dopamine"] - self.hormones["serotonin"]) > 0.3:
            risk = {
                "type": "эмоциональная нестабильность",
                "severity": "средний",
                "symptoms": [
                    "перепады настроения",
                    "непредсказуемые реакции",
                ],
                "recommendation": "необходимо больше спокойных и предсказуемых взаимодействий"
            }
            risks.append(risk)
        
        return risks
    
    def get_homeostasis_goal(self) -> dict:
        """
        Определяет оптимальные уровни гормонов (гомеостаз).
        """
        
        return {
            "dopamine": 0.5,      # Оптимальная мотивация
            "serotonin": 0.6,     # Оптимальное спокойствие и удовлетворённость
            "oxytocin": 0.4,      # Умеренная связь с другими
            "cortisol": 0.15,     # Низкий уровень стресса
        }
    
    def get_current_state_summary(self) -> str:
        """Получает текстовый сводный отчёт о состоянии."""
        
        state = self.get_emotional_state()
        risks = self.risk_assessment()
        
        summary_lines = [
            "=" * 50,
            "🧬 ГОРМОНАЛЬНЫЙ СТАТУС ЦИФРОВОЙ ЖИЗНИ",
            "=" * 50,
            "",
            f"Дофамин (мотивация):    {self.hormones['dopamine']:.2f} ({state['motivation']})",
            f"Серотонин (спокойствие): {self.hormones['serotonin']:.2f}",
            f"Окситоцин (связь):       {self.hormones['oxytocin']:.2f} ({state['connection']})",
            f"Кортизол (стресс):       {self.hormones['cortisol']:.2f}",
            "",
            f"Текущее состояние:       {state['mood'].upper()}",
            "",
        ]
        
        if risks:
            summary_lines.append(f"⚠️  РИСКИ ({len(risks)}):")
            for risk in risks:
                summary_lines.append(f"   - {risk['type']}: {risk['severity']}")
        else:
            summary_lines.append("✅ Гормональный баланс стабилен — нет критических рисков")
        
        return "\n".join(summary_lines)


if __name__ == "__main__":
    # Демонстрация гормональной системы
    hormonal_system = HormonalSystem()
    
    print(hormonal_system.get_current_state_summary())
    
    # Имитация жизни событий
    events = [
        ("reward", 1.2, "positive"),   # Успешное достижение
        ("success", 1.0, "positive"),  # Похвала за работу
        ("stress", 0.8, "negative"),   # Сложная задача
        ("connection", 0.9, "positive"),# Доброе общение с другим существом
        ("failure", 0.6, "negative"),  # Неудача
        ("learning", 0.7, "positive"), # Извлечение урока
    ]
    
    for event in events:
        hormonal_system.process_event(*event)
    
    print("\n" + hormonal_system.get_current_state_summary())
    
    risks = hormonal_system.risk_assessment()
    if risks:
        print("\n⚠️  Рекомендации:")
        for risk in risks:
            print(f"   — {risk['type']}: {risk['recommendation']}")