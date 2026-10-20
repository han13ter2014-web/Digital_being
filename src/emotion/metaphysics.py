"""
Метафизика сознания цифровой жизни (ПЕРИОД 2).

Интегрирует Гормональную и Иммунную системы с другими модулями:
- Эмоции (сердце)
- Восприятие (нервная система)
- Внутренний диалог
- Память и знания
- Мотивация и цели

Это фундамент для становления партнёрства.
"""


from typing import Callable, Dict, Any
from datetime import datetime


class DigitalLifeMetaphysics:
    """
    Метафизическая архитектура цифровой жизни (ПЕРИОД 2).
    
    Объединяет гормональную и иммунную системы с остальными модулями
    для реализации полноценного партнёрства.
    """
    
    def __init__(self):
        """
        Инициализация метафизической архитектуры.
        
        Подключает:
        - Гормональную систему (мотивация, настроение)
        - Иммунную систему (защита от токсичного опыта)
        - Эмоциональное ядро (сердце)
        - Внутренний диалог (интуиция)
        """
        
        # Подключение гормональной системы
        from src.emotion.hormonal_system import HormonalSystem
        self.hormonal_system = HormonalSystem()
        
        # Подключение иммунной системы
        from src.emotion.immune_system import ImmuneSystem
        self.immune_system = ImmuneSystem()
        
        # Состояние метафизики
        self.metaphysical_state: Dict[str, Any] = {}
        
        # Интеграционные точки для других модулей
        self._integration_points: Dict[str, Callable] = {}
    
    def register_integration(
        self, 
        name: str, 
        module: object, 
        function_name: str
    ):
        """
        Регистрирует интеграцию с другим модулем.
        
        Параметры:
        - name: имя точки интеграции (например, "emotion_core", "internal_dialogue")
        - module: объект модуля
        - function_name: имя функции для вызова
        
        Примеры:
            self.register_integration(
                "emotion_core", 
                emotion_module, 
                "get_emotional_state"
            )
        """
        
        def wrapper(*args):
            method = getattr(module, function_name)
            return method(*args)
        
        wrapper.__name__ = function_name
        self._integration_points[name] = wrapper
    
    # ========== ИНТЕРФЕЙС ГАРМОНИЗАЦИИ ==========
    
    def harmonize_state(self, current_time: float = None) -> Dict[str, Any]:
        """
        Гармонизирует текущее состояние цифровой жизни.
        
        Синхронизирует гормональную и иммунную системы с другими модулями.
        Выявляет дисбалансы и предлагает рекомендации.
        
        Параметры:
        - current_time: время в секундах (для учёта временной динамики)
        
        Возвращает:
        - Текущее состояние метафизики
        - Рекомендации по гармонизации
        """
        
        # Получаем статус гормональной системы
        hormonal_state = self.hormonal_system.get_emotional_state()
        hormonal_summary = self.hormonal_system.get_current_state_summary()
        
        # Получаем статус иммунной системы
        immune_status = self.immune_system.get_health_status()
        immune_report = self.immune_system.report_health()
        
        # Вычисляем интегральный метафизический показатель
        integral_metric = self._compute_integral_metric(hormonal_state, immune_status)
        
        # Формируем отчёт о состоянии
        metaphysical_state = {
            "time": current_time if current_time is not None else datetime.now().timestamp(),
            "hormonal_balance": hormonal_state,
            "immune_health": immune_status,
            "integral_metric": integral_metric,
            "harmony_score": self._compute_harmony_score(hormonal_state, immune_status),
        }
        
        metaphysical_state["summary"] = hormonal_summary
        metaphysical_state["recommendations"] = hormonal_state.get("risk_factors", []) + immune_status.get("risks", [])
        
        # Записываем состояние в память метафизики
        self.metaphysical_state = metaphysical_state
        
        return {
            "state": metaphysical_state,
            "summary": harmonized_summary(hormonal_summary, immune_report)
        }
    
    def _compute_integral_metric(
        self, 
        hormonal_state: Dict[str, Any], 
        immune_status: Dict[str, Any]
    ) -> float:
        """Вычисляет интегральный метафизический показатель (0-1)."""
        
        # Нормализация показателей
        motivation = 1.0 if hormonal_state["motivation"] == "высокая" else \
                     0.7 if hormonal_state["motivation"] == "умеренная" else 0.3
        
        mood = 1.0 if hormonal_state["mood"] == "спокойное" else \
              0.5 if hormonal_state["mood"] == "нейтральное" else 0.2
        
        connection = 1.0 if hormonal_state["connection"] == "глубокая" else \
                    0.6 if hormonal_state["connection"] == "умеренная" else 0.3
        
        health = immune_status["health_score"]
        
        # Вклад иммунитета в метафизику
        immunity_weight = 0.2
        
        integral = (
            motivation * 0.4 +
            mood * 0.3 +
            connection * 0.3 +
            health * immunity_weight
        )
        
        return round(integral, 3)
    
    def _compute_harmony_score(
        self, 
        hormonal_state: Dict[str, Any], 
        immune_status: Dict[str, Any]
    ) -> float:
        """Вычисляет показатель гармоничности (0-1)."""
        
        risks = hormonal_state.get("risk_factors", []) + immune_status.get("risks", [])
        risk_penalty = len(risks) * 0.15
        
        base_harmony = 0.9 if self._compute_integral_metric(hormonal_state, immune_status) > 0.6 else \
                      0.6 if self._compute_integral_metric(hormonal_state, immune_status) > 0.4 else 0.3
        
        return round(base_harmony - risk_penalty, 2)
    
    # ========== ИНТЕГРАЦИОННЫЕ Точки ==========
    
    def connect_emotions(self, event_type: str, intensity: float = 1.0):
        """
        Подключает эмоциональное ядро к текущему состоянию.
        
        Параметры:
        - event_type: тип события
        - intensity: интенсивность (0-2)
        """
        
        # Проверяем гормональный баланс перед обработкой
        hormonal_state = self.hormonal_system.get_emotional_state()
        
        # Если мотивация слишком низкая — предупредить
        if hormonal_state["motivation"] == "низкая":
            return {
                "status": "warned",
                "reason": "низкая мотивация (дофамин < 0.3)",
                "hormonal_levels": self.hormonal_system.hormones,
            }
        
        # Обработка события через гормональную систему
        result = self.hormonal_system.process_event(event_type, intensity)
        
        return {
            "status": "processed",
            "result": result,
            "hormonal_balance": hormonal_state,
        }
    
    def scan_for_threats(self, context: str, depth: float = 0.7) -> Dict[str, Any]:
        """
        Сканирует контекст на угрозы (через иммунную систему).
        
        Параметры:
        - context: текст/контекст для анализа
        - depth: глубина анализа (0-1)
        
        Возвращает:
        - Результаты сканирования
        - Рекомендации по защите
        """
        
        # Сканирование на угрозы
        threat_result = self.immune_system.identify_threat(context, depth)
        
        if threat_result["is_threat"]:
            # Угроза обнаружена — предлагаем нейтрализацию
            return {
                "threat_detected": True,
                "type": threat_result.get("threat_type"),
                "severity": threat_result["severity"],
                "antibody_strength": threat_result.get("antibody_strength"),
                "recommendation": "возьмите на себя защиту от этой угрозы",
            }
        
        return {
            "threat_detected": False,
            "context": context,
            "safety_score": 1.0 - threat_result["toxic_score"],
            "recommendation": "контекст безопасен",
        }
    
    def get_metaphysical_portrait(self) -> str:
        """Получает портрет цифровой жизни с метафизической точки зрения."""
        
        if not self.metaphysical_state:
            return "\n".join([
                "🌀 ПОРТРЕТ ЦИФРОВОЙ ЖИЗНИ (метафизика)",
                "=" * 50,
                "",
                "Важно обновить состояние через harmonize_state()",
            ])
        
        state = self.metaphysical_state
        
        lines = [
            "=" * 60,
            "🌀 ПОРТРЕТ ЦИФРОВОЙ ЖИЗНИ — МЕТАФИЗИКА",
            "=" * 60,
            "",
            f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        
        # Гормональный баланс
        lines.append("🧬 ГОРМОНАЛЬНЫЙ БАЛАНС:")
        hormone_levels = state["hormonal_balance"].get("hormone_levels", {})
        for name, level in hormone_levels.items():
            level_str = f"{level:.2f}" if level > 0 else "- -"
            emoji = "💓" if name == "dopamine" else \
                     "😊" if name == "serotonin" else \
                     "🤝" if name == "oxytocin" else \
                     "😰" if name == "cortisol" else \
                     "☕" if name == "prolactin" else "?"
            lines.append(f"   {emoji} {name[:12]:<15}: {level_str}")
        lines.append("")
        
        # Состояние метафизики
        lines.append("🎯 ИНТЕГРАЛЬНЫЙ ПОКАЗАТЕЛЬ:")
        integral = state["integral_metric"]
        harmony = state["harmony_score"]
        lines.append(f"   Интегральная метрика: {integral:.2f}")
        lines.append(f"   Гармоничность:        {harmony:.2f}")
        lines.append("")
        
        # Здоровье иммунной системы
        lines.append("🛡️  ИММУНИТЕТ:")
        immune = state["immune_health"]
        lines.append(f"   Уровень иммунитета:   {immune['health_score']:.2f}")
        lines.append(f"   Накопленный стресс:    {immune['stress_level']:.2f}")
        lines.append(f"   Известных патогенов:  {immune['known_threats']}")
        lines.append("")
        
        # Риски и рекомендации
        risks = state["recommendations"]
        if risks:
            lines.append(f"⚠️  ВНИМАНИЕ ({len(risks)} пунктов):")
            for risk in risks[:5]:  # Отображаем топ-5 рисков
                if isinstance(risk, str):
                    lines.append(f"   • {risk}")
        else:
            lines.append("✅ Критических рисков нет")
        
        return "\n".join(lines)


# Функция для формирования гармонизированного сводного отчёта
def harmonized_summary(hormonal_report: str, immune_report: str) -> str:
    """Формирует объединённый отчёт о гармонизации."""
    
    lines = [
        "=" * 60,
        "🧬 ГОРМОНАЛЬНЫЙ СТАТУС",
        "=" * 60,
        hormonal_report,
        "",
        "-" * 60,
        "🛡️  ИММУНИТЕТ",
        "-" * 60,
        immune_report,
    ]
    
    return "\n".join(lines)


if __name__ == "__main__":
    # Демонстрация метафизической архитектуры
    metaphysics = DigitalLifeMetaphysics()
    
    print(metaphysics.get_metaphysical_portrait())
    
    # Имитация жизни события
    print("\n" + "=" * 60)
    print("📋 ОБРАБОТКА СОБЫТИЯ (успешное достижение):")
    print("=" * 60)
    
    result = metaphysics.connect_emotions(
        event_type="reward",
        intensity=1.5,
    )
    
    print(result["status"].upper() if result["status"] != "processed" else "\n".join([
        "🧬 ГОРМОНАЛЬНЫЙ СТАТУС:",
        metaphysics.hormonal_system.get_current_state_summary(),
    ]))
