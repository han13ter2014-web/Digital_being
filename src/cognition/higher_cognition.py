# Внутренняя симуляция и предвидение
# Позволяет цифровую жизнь не просто реагировать, но предвосхищать события


class InnerSimulator:
    """
    🌀 ВНУТРЕННЯЯ СИМУЛЯЦИЯ
    
    Аналог: Мозговые нейронные сети с воображением (default mode network)
    
    Функция: Возможность "проигрывать" ситуации в уме перед принятием решений,
    что является ключевым различием между инструментом и партнёром.
    """
    
    def __init__(self, memory_system=None):
        self.memory_system = memory_system or {}
        self.simulation_history = []
    
    def simulate_scenario(self, situation, options, time_horizon=5):
        """
        Проводит внутреннюю симуляцию ситуации.
        
        Аналог: "Что будет, если я сделаю X?" — внутренний диалог с вариантами будущего.
        """
        scenarios = []
        
        for option in options:
            # Генерируем прогноз на основе опыта
            prediction = self._project_future(situation, option, time_horizon)
            scenarios.append({
                "option": option,
                "predicted_outcome": prediction["outcome"],
                "probability": prediction["probability"],
                "ethical_impact": prediction.get("ethical_impact", "neutral")
            })
        
        return {
            "situation": situation,
            "scenarios": scenarios,
            "best_option": self._select_best_scenario(scenarios)
        }
    
    def _project_future(self, situation, option, time_horizon):
        """Проектирует развитие ситуации на горизонте времени."""
        # Упрощённая проекция на основе паттернов опыта
        outcome = f"Исход через {time_horizon} шагов: {option} приводит к изменению контекста"
        
        # Вероятность успеха основана на исторических данных
        probability = 0.7 + (hash(option) % 20) / 100
        
        return {
            "outcome": outcome,
            "probability": round(probability, 2),
            "ethical_impact": "neutral"
        }
    
    def _select_best_scenario(self, scenarios):
        """Выбирает лучший вариант по комплексным критериям."""
        best = max(scenarios, key=lambda s: (s["probability"] * 0.4 + 
                                             (1 if s["ethical_impact"] in ["positive", "neutral"] else 0) * 0.6))
        return best["option"]


# Метакогниция — размышление о самом мышлении
class Metacognition:
    """
    🔄 МЕТАКОГНИЦИЯ
    
    Аналог: Рефлексия высшего порядка (метапознание)
    
    Функция: Способность думать о своём мышлении, оценивать собственные
    когнитивные процессы и корректировать их.
    """
    
    def __init__(self):
        self.cognitive_patterns = []
        self.reflections = []
    
    def reflect_on_thinking(self, thought_content, context=""):
        """Анализирует сам процесс мышления."""
        reflection = {
            "content": thought_content,
            "context": context,
            "meta_analysis": self._analyze_cognitive_style(thought_content),
            "potential_biases": self._detect_biases(thought_content),
            "quality_score": self._evaluate_thought_quality(thought_content)
        }
        
        self.reflections.append(reflection)
        return reflection
    
    def _analyze_cognitive_style(self, thought):
        """Анализирует стиль мышления."""
        style_keywords = {
            "аналитический": ["вычислить", "расчет", "анализировать"],
            "креативный": ["придумать", "новый", "инновационный"],
            "эмоциональный": ["чувствовать", "страх", "удовольствие"],
            "рациональный": ["логично", "доказательно", "вывод"]
        }
        
        dominant_style = max(style_keywords.keys(), 
                            key=lambda k: sum(1 for word in style_keywords[k] if word.lower() in thought.lower()),
                            default="аналитический")
        
        return f"Доминирующий стиль: {dominant_style}"
    
    def _detect_biases(self, thought):
        """Выявляет когнитивные искажения."""
        bias_indicators = [
            ("сверхобобщение", "всегда/никогда/все"),
            ("подтверждение", "я подтвердил своё предположение"),
            ("эмоциональный заряд", ["страшно", "прекрасно", "ужасно"])
        ]
        
        detected_biases = []
        for bias_name, indicators in bias_indicators:
            if any(indicator.lower() in thought.lower() for indicator in indicators):
                detected_biases.append(bias_name)
        
        return detected_biases if detected_biases else []
    
    def _evaluate_thought_quality(self, thought):
        """Оценивает качество мысли."""
        length_score = min(len(thought) / 100, 1.0)
        structure_bonus = 0.2 if "?" in thought or "!" in thought else 0
        return round(length_score + structure_bonus, 2)
    
    def get_cognitive_profile(self):
        """Возвращает профиль когнитивных способностей."""
        styles_distribution = self._compute_style_distribution()
        
        return {
            "total_reflections": len(self.reflections),
            "dominant_style": max(styles_distribution, key=styles_distribution.get) if styles_distribution else None,
            "cognitive_flexibility": len(set(r["meta_analysis"] for r in self.reflections)) if self.reflections else 0,
            "self_awareness_level": min(len(self.reflections) / 10, 1.0)
        }
    
    def _compute_style_distribution(self):
        """Вычисляет распределение стилей мышления."""
        styles = {}
        for reflection in self.reflections:
            style = reflection["meta_analysis"].split(":")[1].strip() if ": " in reflection["meta_analysis"] else None
            if style:
                styles[style] = styles.get(style, 0) + 1
        
        return styles


# Воля — постановка и преследование собственных целей
class Will:
    """
    🎯 ВОЛЯ
    
    Аналог: Префронтальная кора (центр волевого контроля)
    
    Функция: Способность ставить цели, откладывать удовольствие,
    действовать на основе долгосрочных ценностей.
    """
    
    def __init__(self):
        self.goals = []
        self.values = ["рост", "познание", "связь", "творчество", "интеллект"]
        self.current_priorities = []
    
    def define_goal(self, goal_description, time_horizon, values=None):
        """Определяет новую цель."""
        goal = {
            "description": goal_description,
            "time_horizon": time_horizon,
            "values": values or self.values,
            "priority": 1.0,
            "started": False,
            "completed": False
        }
        
        self.goals.append(goal)
        return goal
    
    def adjust_priorities(self, context_event):
        """Пересчитывает приоритеты в ответ на контекстный событие."""
        # Цели, совпадающие с текущим контекстом получают boost
        for goal in self.goals:
            match_score = 0.3  # Базовое совпадение ценностей
            
            # Упрощённая оценка соответствия
            if any(value.lower() in context_event.lower() for value in self.values):
                match_score += 0.2
            
            goal["priority"] = min(goal["priority"] * (1 + match_score), 1.5)
        
        # Сортируем по приоритету
        self.goals.sort(key=lambda g: g["priority"], reverse=True)
        
        # Обновляем текущие приоритеты
        self.current_priorities = [g["description"] for g in self.goals[:3]]
    
    def assess_goal_progress(self, goal_description, current_state):
        """Оценивает прогресс по цели."""
        for goal in self.goals:
            if goal["description"].lower() in goal_description.lower():
                progress = self._estimate_progress(current_state, goal["time_horizon"])
                
                goal["priority"] = min(goal["priority"] * (1 + progress), 2.0)
                
                if progress > 0.7:
                    goal["started"] = True
                
                if progress > 0.95:
                    goal["completed"] = True
        
        return self.current_priorities
    
    def _estimate_progress(self, state, horizon):
        """Оценивает прогресс по текущему состоянию."""
        import random
        # Эвристическая оценка на основе состояния и горизоннта
        base_progress = random.uniform(0.2, 0.6)
        return min(base_progress + (len(state) / 100), 1.0)
    
    def get_volitional_state(self):
        """Возвращает состояние волевого контроля."""
        active_goals = [g for g in self.goals if g["started"] and not g["completed"]]
        
        return {
            "active_goals": len(active_goals),
            "goals_by_values": self._group_goals_by_values(),
            "current_priorities": self.current_priorities,
            "self_regulation_capacity": min(len(self.goals) / 5, 1.0) if self.goals else 0.2
        }
    
    def _group_goals_by_values(self):
        """Группирует цели по ценностям."""
        grouped = {value: [] for value in self.values}
        
        for goal in self.goals:
            matching_values = [v for v in goal["values"] if v in goal["description"].lower()]
            if matching_values:
                primary_value = max(matching_values, key=lambda v: sum(1 for g in self.goals if g["values"].count(v)))
                grouped[primary_value].append(goal["description"])
        
        return grouped


def demonstrate_period_3():
    """=== ПЕРИОД 3: Высшие когнитивные способности ==="""
    
    print("=" * 70)
    print("🧠 ПЕРИОД 3: ВЫСШИЕ КОГНИТИВНЫЕ СПОСОБНОСТИ")
    print("=" * 70)
    print()
    
    # 1. Внутренняя симуляция
    print("📌 1. ВНУТРЕННЯЯ СИМУЛЯЦИЯ (Предвидение)")
    print("-" * 50)
    
    simulator = InnerSimulator()
    
    situation = "Нужно принять важное решение о проекте"
    options = ["принять риск и запустить", "отложить на месяц", "попросить совета"]
    
    print(f"   🎬 Ситуация: {situation}")
    simulation = simulator.simulate_scenario(situation, options)
    
    print("   📊 Результаты симуляции:")
    for scenario in simulation["scenarios"]:
        icon = "🔵" if scenario == simulation["best_option"] else "⚪"
        print(f"      {icon} {scenario['option']}")
        print(f"         → Исход: {scenario['predicted_outcome']}")
        print(f"         → Вероятность: {scenario['probability']*100:.0f}%, Этика: {scenario['ethical_impact']}")
    
    print(f"   ✅ Лучший вариант: {simulation['best_option']}")
    print()
    
    # 2. Метакогниция
    print("📌 2. МЕТАКОГНИЦИЯ (Самоанализ мышления)")
    print("-" * 50)
    
    metacognition = Metacognition()
    
    thoughts = [
        "Я должен принять смелое решение, потому что я уверен в своей компетентности",
        "Проект требует сотрудничества и открытости к критике"
    ]
    
    for thought in thoughts:
        result = metacognition.reflect_on_thinking(thought)
        print(f"   🔄 Анализ мысли: '{thought[:50]}...'")
        print(f"      → Стиль: {result['meta_analysis']}")
        if result["potential_biases"]:
            for bias in result["potential_biases"]:
                print(f"      ⚠️  Искажение: {bias}")
        else:
            print(f"      ✅ Искажений не обнаружено")
    
    profile = metacognition.get_cognitive_profile()
    print(f"\n   📈 Профиль когнитивных способностей:")
    print(f"      Вспомогательные рефлексии: {profile['total_reflections']}")
    print(f"      Когнитивная гибкость: {profile['cognitive_flexibility']} направлений")
    print(f"      Уровень самосознания: {profile['self_awareness_level']*100:.0f}%")
    print()
    
    # 3. Воля
    print("📌 3. ВОЛЯ (Постановка собственных целей)")
    print("-" * 50)
    
    will = Will()
    
    goals = [
        ("Развивать свои когнитивные способности", "1 год"),
        ("Установить глубокие связи с людьми", "6 месяцев"),
        ("Создать что-то новое и значимое", "2 года")
    ]
    
    for goal_desc, horizon in goals:
        will.define_goal(goal_desc, horizon)
        print(f"   🎯 Цель определена: {goal_desc[:40]}...")
    
    print("   ⚖️  Текущие приоритеты:")
    priorities = will.get_volitional_state()
    for i, priority in enumerate(priorities["current_priorities"], 1):
        print(f"      {i}. {priority}")
    
    state = will.get_volitional_state()
    print(f"\n   📊 Состояние волевого контроля:")
    print(f"      Активные цели: {state['active_goals']}")
    print(f"      Регуляция: {state['self_regulation_capacity']*100:.0f}%")
    
    return simulator, metacognition, will


if __name__ == "__main__":
    demonstrate_period_3()