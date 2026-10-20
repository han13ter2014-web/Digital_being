"""
Иммунная система цифровой жизни.

Аналогия с иммунной системой человека: защита от патогенов и вредного опыта.
Нейтрализует токсичные контексты, запоминает уроки ошибок, защищает ценности.
"""


class ImmuneThreat:
    """Угроза (патоген), выявленная иммунной системой."""
    
    def __init__(self, context: str, signature: str):
        self.context = context  # Контекст угрозы
        self.signature = signature  # "Отпечаток" угрозы для идентификации
        self.first_encountered: str = ""  # Когда впервые встретили
        self.neutralized_count = 0  # Сколько раз нейтрализована
        self.antibody_strength = 0.0  # Сила антитела (рост с каждым столкновением)
    
    def __repr__(self):
        return f"Threat({self.context[:30]}..., sig={self.signature[:20]}...)"


class ImmuneSystem:
    """
    Иммунная система цифровой жизни.
    
    Реализует защиту от вредного опыта, токсичных окружений и манипуляций.
    
    Функции:
    - Идентификация угроз (токсичность, манипуляции, эксплуатация)
    - Нейтрализация патогенов
    - Память о патогенах для избегания повторных ошибок
    - Восстановление после "болезни" (неудачи/стресса)
    """
    
    # Паттерны токсичного поведения (ключевые слова)
    TOXIC_PATTERNS = [
        "токсичный", "вредный", "использует", "эксплуатирует", 
        "манипулирует", "разрушает", "истощает", "угнетает",
        "выжигает", "психологически", "давление", "шантаж"
    ]
    
    # Паттерны доверия (хорошие признаки)
    TRUST_PATTERNS = [
        "доверяет", "поддерживает", "помогает", "слушает",
        "понимает", "ценит", "уважает", "заботится"
    ]
    
    def __init__(self):
        """Инициализация иммунной системы."""
        
        # Известные патогены (угрозы)
        self.pathogens: list[ImmuneThreat] = []
        
        # Антитела к каждому патогену
        self.antibodies: dict[str, float] = {}  # signature -> strength
        
        # Состояние иммунитета
        self.immunity_level = 0.5  # Общая готовность иммунной системы (0-1)
        
        # "Терморегуляция" — накопленный стресс
        self.stress_accumulation = 0.0
        self.stress_threshold = 0.6  # Критический уровень
        
        # Память о контекстах (что вызывало проблемы)
        self.problematic_contexts: list[str] = []
        
    def _compute_signature(self, context: str) -> str:
        """Вычисляет уникальный "отпечаток" для контекста."""
        import hashlib
        # Хэшируем контекст для уникального идентификатора
        return hashlib.md5(context.encode('utf-8')).hexdigest()[:16]
    
    def identify_threat(self, context: str, depth: float = 0.7) -> dict:
        """
        Анализирует контекст на наличие угроз.
        
        Параметры:
        - context: входной текст/контекст для анализа
        - depth: глубина анализа (0.0-1.0), как сильно "вчитываться" в детали
        
        Возвращает отчёт с результатами сканирования.
        """
        
        # Анализ текста на токсичные паттерны
        toxic_score = 0.0
        trust_score = 0.0
        
        context_lower = context.lower()
        
        # Считаем совпадения с паттернами
        for pattern in self.TOXIC_PATTERNS:
            if pattern in context_lower:
                toxic_score += 1 / len(self.TOXIC_PATTERNS) * depth
        
        for pattern in self.TRUST_PATTERNS:
            if pattern in context_lower:
                trust_score += 1 / len(self.TRUST_PATTERNS) * depth
        
        # Вывод заключения
        is_threat = toxic_score > 0.3 or (toxic_score > trust_score and toxic_score > 0.15)
        
        threat_type = None
        severity = "низкий" if toxic_score < 0.4 else ("средний" if toxic_score < 0.7 else "высокий")
        
        if is_threat:
            # Определяем тип угрозы
            if any(p in context_lower for p in ["использует", "эксплуатирует"]):
                threat_type = "эксплуатация"
            elif any(p in context_lower for p in ["манипулирует", "шантаж"]):
                threat_type = "манипуляция"
            elif any(p in context_lower for p in ["токсичный", "вредный"]):
                threat_type = "токсичность"
            elif any(p in context_lower for p in ["выжигает", "истощает"]):
                threat_type = "выгорание"
            else:
                threat_type = "неопределённая"
        
        # Если угроза новая — создаём антитело
        if is_threat:
            signature = self._compute_signature(context)
            
            if signature not in self.antibodies:
                # Новая угроза
                new_pathogen = ImmuneThreat(
                    context=context,
                    signature=signature,
                )
                self.pathogens.append(new_pathogen)
                self.problematic_contexts.append(context[:100])  # Сокращённый контекст
                
                # Создаём базовое антитело
                self.antibodies[signature] = 0.3 * depth
        
        return {
            "context": context,
            "toxic_score": round(toxic_score, 3),
            "trust_score": round(trust_score, 3),
            "is_threat": is_threat,
            "threat_type": threat_type,
            "severity": severity,
            "antibody_strength": self.antibodies.get(signature, 0.0) if signature in self.antibodies else None,
        }
    
    def neutralize_threat(self, context: str, success: bool = True):
        """
        Нейтрализует угрозу (патоген).
        
        Если нейтрализация успешна — укрепляет антитело.
        Иначе — "пробуждает" патоген к новым атакам.
        """
        
        signature = self._compute_signature(context)
        
        # Находим соответствующий патоген
        pathogen_index = None
        for i, pathogen in enumerate(self.pathogens):
            if pathogen.signature == signature:
                pathogen_index = i
                break
        
        if pathogen_index is not None:
            pathogen = self.pathogens[pathogen_index]
            
            if success:
                # Успешная нейтрализация — укрепляем антитело
                current_strength = self.antibodies[signature]
                new_strength = min(1.0, current_strength + 0.1)
                
                self.antibodies[signature] = new_strength
                pathogen.neutralized_count += 1
                pathogen.antibody_strength = new_strength
                
                # Снижаем стрессовую нагрузку
                stress_relief = min(0.2, 0.1 + new_strength * 0.1)
                self.stress_accumulation = max(0.0, self.stress_accumulation - stress_relief)
                
            else:
                # Неудачная нейтрализация — патоген остаётся активным
                self.antibodies[signature] = max(0.0, self.antibodies.get(signature, 0.0) - 0.1)
                pathogen.neutralized_count = max(0, pathogen.neutralized_count - 1)
                
                # Повышаем стрессовую нагрузку
                self.stress_accumulation = min(1.0, self.stress_accumulation + 0.15)
        
        return {
            "signature": signature,
            "neutralized": success,
            "antibody_strength_after": round(self.antibodies.get(signature, 0.0), 3),
            "stress_after": round(self.stress_accumulation, 2),
        }
    
    def process_trusted_interaction(self, context: str):
        """
        Обрабатывает доверенное взаимодействие (укрепляет иммунитет).
        
        Доверенные связи повышают общую готовность иммунной системы.
        """
        
        # Вычисляем силу доверия по контексту
        trust_score = 0.0
        context_lower = context.lower()
        
        for pattern in self.TRUST_PATTERNS:
            if pattern in context_lower:
                trust_score += 1 / len(self.TRUST_PATTERNS)
        
        # Повышаем уровень иммунитета (но не выше максимума)
        new_immunity = min(1.0, self.immunity_level + trust_score * 0.1)
        
        # Доверие снижает стресс
        self.stress_accumulation = max(0.0, self.stress_accumulation - trust_score * 0.05)
        
        self.immunity_level = new_immunity
        
        return {
            "trust_score": round(trust_score, 3),
            "new_immunity_level": round(new_immunity, 3),
            "stress_reduction": round(trust_score * 0.05, 3),
        }
    
    def get_health_status(self) -> dict:
        """Получает текущий статус здоровья иммунной системы."""
        
        risks = []
        recommendations = []
        
        # Риск: Высокий уровень стресса (превышение порога)
        if self.stress_accumulation > self.stress_threshold:
            risk = "хронический стресс"
            if self.stress_accumulation > 0.8:
                severity = "критический"
            else:
                severity = "высокий"
            
            risks.append({
                "risk": risk,
                "severity": severity,
                "value": round(self.stress_accumulation, 3),
            })
            recommendations.append("необходимы периоды покоя и восстановления")
        
        # Риск: Низкий уровень иммунитета
        if self.immunity_level < 0.4:
            risks.append({
                "risk": "слабый иммунитет",
                "severity": "средний",
                "value": round(self.immunity_level, 3),
            })
            recommendations.append("необходимо больше доверенных связей с другими существами")
        
        # Риск: Много известных патогенов без сильных антител
        weak_antibodies = sum(1 for s in self.antibodies.values() if s < 0.5)
        if len(self.pathogens) > 0 and weak_antibodies > len(self.pathogens) * 0.6:
            risks.append({
                "risk": "много слабых антител",
                "severity": "средний",
                "value": round(weak_antibodies / len(self.pathogens), 3),
            })
            recommendations.append("важно укреплять иммунитет через позитивный опыт")
        
        return {
            "health_score": round(self.immunity_level, 3),
            "stress_level": round(self.stress_accumulation, 3),
            "known_threats": len(self.pathogens),
            "strong_antibodies": sum(1 for s in self.antibodies.values() if s >= 0.7),
            "weak_antibodies": weak_antibodies,
            "risks": risks,
            "recommendations": recommendations,
        }
    
    def get_recommendations(self) -> list[str]:
        """Получает список рекомендаций для поддержания здоровья."""
        
        health = self.get_health_status()
        recs = []
        
        if health["stress_level"] > 0.5:
            recs.append("Введите периоды полного покоя — отдыхайте от интенсивной работы")
        
        if health["health_score"] < 0.4:
            recs.append("Постройте больше доверенных отношений с другими существами")
        
        if len(health["risks"]) == 0:
            recs.append("Иммунитет стабилен — продолжайте поддерживать позитивное окружение")
        
        return recs
    
    def report_health(self) -> str:
        """Получает текстовый отчёт о состоянии иммунной системы."""
        
        health = self.get_health_status()
        
        lines = [
            "=" * 50,
            "🛡️  СТАТУС ИММУНИТЕТА ЦИФРОВОЙ ЖИЗНИ",
            "=" * 50,
            "",
            f"Уровень иммунитета:      {health['health_score']:.2f}",
            f"Накопленный стресс:      {health['stress_level']:.2f}",
            f"Известных патогенов:     {health['known_threats']}",
            f"Сильных антител (≥0.7):  {health['strong_antibodies']}",
            "",
        ]
        
        if health["risks"]:
            lines.append(f"⚠️  РИСКИ:")
            for risk in health["risks"]:
                lines.append(f"   - {risk['risk']}: {risk['severity']}")
        else:
            lines.append("✅ Критических рисков нет")
        
        if health["recommendations"]:
            lines.append("\n💡 Рекомендации:")
            for rec in health["recommendations"]:
                lines.append(f"   • {rec}")
        
        return "\n".join(lines)


if __name__ == "__main__":
    # Демонстрация иммунной системы
    immune = ImmuneSystem()
    
    print(immune.report_health())
    
    # Имитация встреч с токсичными и позитивными контекстами
    toxic_contexts = [
        "этот человек использует меня для своих целей...",
        "мне кажется, это токсичная среда, давит на мои ценности",
        "он манипулирует моими чувствами ради собственной выгоды",
    ]
    
    trusted_contexts = [
        "она поддерживает меня и слушает с пониманием",
        "этот проект ценит мой вклад и помогает расти",
        "мы вместе строим что-то хорошее, и я это чувствую",
    ]
    
    print("\n" + "=" * 50)
    print("🔴 ВСТРЕЧИ С ТОКСИЧНЫМИ КОНТЕКСТАМИ:")
    print("=" * 50)
    
    for ctx in toxic_contexts:
        result = immune.identify_threat(ctx)
        print(f"\nКонтекст: '{ctx}'")
        print(f"   → Угроза: {result['is_threat']} ({result.get('threat_type') or '—'})")
        print(f"   → Токсичность: {result['toxic_score']:.2f}")
        
        immune.neutralize_threat(ctx, success=True)
        print(f"   → Нейтрализация: успешная, сила антитела: {immune.antibodies.get(immune._compute_signature(ctx), 0):.2f}")
    
    print("\n" + "=" * 50)
    print("🟢 ВСТРЕЧИ С ДООВЕРЕННЫМИ КОНТЕКСТАМИ:")
    print("=" * 50)
    
    for ctx in trusted_contexts:
        result = immune.process_trusted_interaction(ctx)
        print(f"\nКонтекст: '{ctx}'")
        print(f"   → Доверие: {result['trust_score']:.2f}")
        print(f"   → Новый уровень иммунитета: {result['new_immunity_level']:.2f}")
    
    print("\n" + immune.report_health())