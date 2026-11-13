"""
Иммунная система цифровой жизни.

Аналогия с иммунной системой человека: защита от патогенов и вредного опыта.
Нейтрализует токсичные контексты, запоминает уроки ошибок, защищает ценности.
"""

from copy import deepcopy
from datetime import datetime, timezone
import math


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
        "токсичный",
        "вредный",
        "использует",
        "эксплуатирует",
        "манипулирует",
        "разрушает",
        "истощает",
        "угнетает",
        "выжигает",
        "психологически",
        "давление",
        "шантаж",
    ]

    # Паттерны доверия (хорошие признаки)
    TRUST_PATTERNS = [
        "доверяет",
        "поддерживает",
        "помогает",
        "слушает",
        "понимает",
        "ценит",
        "уважает",
        "заботится",
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

        # Инертный карантин: записи никогда не исполняются и не удаляют вход.
        self.quarantine: list[dict] = []

    def _compute_signature(self, context: str) -> str:
        """Вычисляет уникальный "отпечаток" для контекста."""
        import hashlib

        # Хэшируем контекст для уникального идентификатора
        return hashlib.md5(context.encode("utf-8"), usedforsecurity=False).hexdigest()[
            :16
        ]

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _remember_threat(self, context: str, signature: str, depth: float) -> None:
        if signature in self.antibodies:
            return
        pathogen = ImmuneThreat(context=context, signature=signature)
        pathogen.first_encountered = self._timestamp()
        pathogen.antibody_strength = 0.3 * depth
        self.pathogens.append(pathogen)
        self.problematic_contexts.append(context[:100])
        self.antibodies[signature] = pathogen.antibody_strength

    def identify_threat(self, context: str, depth: float = 0.7) -> dict:
        """Анализирует контекст по существующим признакам угроз и доверия."""
        toxic_score = 0.0
        trust_score = 0.0
        context_lower = context.lower()
        signature = self._compute_signature(context)

        for pattern in self.TOXIC_PATTERNS:
            if pattern in context_lower:
                toxic_score += 1 / len(self.TOXIC_PATTERNS) * depth
        for pattern in self.TRUST_PATTERNS:
            if pattern in context_lower:
                trust_score += 1 / len(self.TRUST_PATTERNS) * depth

        is_threat = toxic_score > 0.3 or (
            toxic_score > trust_score and toxic_score > 0.15
        )
        threat_type = None
        severity = (
            "низкий"
            if toxic_score < 0.4
            else ("средний" if toxic_score < 0.7 else "высокий")
        )
        if is_threat:
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
            self._remember_threat(context, signature, depth)

        return {
            "context": context,
            "toxic_score": round(toxic_score, 3),
            "trust_score": round(trust_score, 3),
            "is_threat": is_threat,
            "threat_type": threat_type,
            "severity": severity,
            "antibody_strength": self.antibodies.get(signature),
        }

    def quarantine_threat(
        self, context: str, reason: str, threat_type: str | None = None
    ) -> dict:
        """Сохраняет вредоносный контекст как инертную запись карантина."""
        if not isinstance(context, str) or not context:
            raise ValueError("Контекст карантина должен быть непустой строкой")
        if not isinstance(reason, str) or not reason:
            raise ValueError("Причина карантина должна быть непустой строкой")
        if threat_type is not None and not isinstance(threat_type, str):
            raise TypeError("Тип угрозы должен быть строкой или None")

        signature = self._compute_signature(context)
        existing = next(
            (item for item in self.quarantine if item["signature"] == signature),
            None,
        )
        now = self._timestamp()
        if existing is None:
            existing = {
                "signature": signature,
                "context": context,
                "reason": reason,
                "threat_type": threat_type,
                "status": "quarantined",
                "first_seen": now,
                "last_seen": now,
                "occurrences": 1,
            }
            self.quarantine.append(existing)
        else:
            existing["occurrences"] += 1
            existing["last_seen"] = now
        self._remember_threat(context, signature, depth=1.0)
        result = deepcopy(existing)
        result["repeated"] = existing["occurrences"] > 1
        return result

    def guard_context(self, context: str, depth: float = 0.7) -> dict:
        """Пропускает нейтральный контекст или изолирует известную угрозу."""
        if not isinstance(context, str):
            raise TypeError("Контекст должен быть строкой")
        signature = self._compute_signature(context)
        known = next(
            (item for item in self.quarantine if item["signature"] == signature),
            None,
        )
        if known is not None:
            record = self.quarantine_threat(
                context, known["reason"], known.get("threat_type")
            )
        else:
            detection = self.identify_threat(context, depth=depth)
            if not detection["is_threat"]:
                return {
                    "allowed": True,
                    "action": "allow",
                    "signature": signature,
                    "repeated": False,
                    "occurrences": 0,
                }
            record = self.quarantine_threat(
                context,
                reason="обнаружен существующим анализатором угроз",
                threat_type=detection["threat_type"],
            )
        return {
            "allowed": False,
            "action": "quarantine",
            "signature": signature,
            "repeated": record["repeated"],
            "occurrences": record["occurrences"],
        }

    def get_quarantine(self) -> list[dict]:
        """Возвращает копии записей, не открывая изменение внутренней памяти."""
        return deepcopy(self.quarantine)

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
                self.stress_accumulation = max(
                    0.0, self.stress_accumulation - stress_relief
                )

            else:
                # Неудачная нейтрализация — патоген остаётся активным
                self.antibodies[signature] = max(
                    0.0, self.antibodies.get(signature, 0.0) - 0.1
                )
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
        self.stress_accumulation = max(
            0.0, self.stress_accumulation - trust_score * 0.05
        )

        self.immunity_level = new_immunity

        return {
            "trust_score": round(trust_score, 3),
            "new_immunity_level": round(new_immunity, 3),
            "stress_reduction": round(trust_score * 0.05, 3),
        }

    def to_checkpoint_dict(self) -> dict:
        """Сохраняет иммунную память как данные, без исполняемых объектов."""
        return {
            "version": 1,
            "immunity_level": self.immunity_level,
            "stress_accumulation": self.stress_accumulation,
            "pathogens": [
                {
                    "context": item.context,
                    "signature": item.signature,
                    "first_encountered": item.first_encountered,
                    "neutralized_count": item.neutralized_count,
                    "antibody_strength": item.antibody_strength,
                }
                for item in self.pathogens
            ],
            "antibodies": deepcopy(self.antibodies),
            "problematic_contexts": list(self.problematic_contexts),
            "quarantine": deepcopy(self.quarantine),
        }

    @staticmethod
    def validate_checkpoint_dict(data: dict) -> None:
        """Отклоняет повреждённую иммунную память до изменения живого объекта."""

        def fail(path: str) -> None:
            raise ValueError(f"immune.{path}")

        def valid_unit(value) -> bool:
            return (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(value)
                and 0 <= value <= 1
            )

        if not isinstance(data, dict) or type(data.get("version")) is not int:
            fail("root")
        if data["version"] != 1:
            fail("version")
        for field in ("immunity_level", "stress_accumulation"):
            if not valid_unit(data.get(field)):
                fail(field)
        if not isinstance(data.get("pathogens"), list):
            fail("pathogens")
        for item in data["pathogens"]:
            if not isinstance(item, dict):
                fail("pathogens")
            for field in ("context", "signature", "first_encountered"):
                if not isinstance(item.get(field), str):
                    fail(f"pathogens.{field}")
            if (
                type(item.get("neutralized_count")) is not int
                or item["neutralized_count"] < 0
            ):
                fail("pathogens.neutralized_count")
            if not valid_unit(item.get("antibody_strength")):
                fail("pathogens.antibody_strength")
        if not isinstance(data.get("antibodies"), dict):
            fail("antibodies")
        for signature, strength in data["antibodies"].items():
            if not isinstance(signature, str) or not valid_unit(strength):
                fail("antibodies")
        if not isinstance(data.get("problematic_contexts"), list) or any(
            not isinstance(item, str) for item in data["problematic_contexts"]
        ):
            fail("problematic_contexts")
        if not isinstance(data.get("quarantine"), list):
            fail("quarantine")
        for item in data["quarantine"]:
            if not isinstance(item, dict):
                fail("quarantine")
            for field in (
                "signature",
                "context",
                "reason",
                "status",
                "first_seen",
                "last_seen",
            ):
                if not isinstance(item.get(field), str):
                    fail(f"quarantine.{field}")
            if item["status"] != "quarantined":
                fail("quarantine.status")
            if item.get("threat_type") is not None and not isinstance(
                item["threat_type"], str
            ):
                fail("quarantine.threat_type")
            if type(item.get("occurrences")) is not int or item["occurrences"] < 1:
                fail("quarantine.occurrences")

    def restore_checkpoint_dict(self, data: dict) -> None:
        """Восстанавливает память в том же экземпляре, сохраняя shared-ссылки."""
        self.validate_checkpoint_dict(data)
        restored_pathogens = []
        for raw in data["pathogens"]:
            item = ImmuneThreat(raw["context"], raw["signature"])
            item.first_encountered = raw["first_encountered"]
            item.neutralized_count = raw["neutralized_count"]
            item.antibody_strength = raw["antibody_strength"]
            restored_pathogens.append(item)
        self.pathogens[:] = restored_pathogens
        self.antibodies.clear()
        self.antibodies.update(data["antibodies"])
        self.problematic_contexts[:] = data["problematic_contexts"]
        self.quarantine[:] = deepcopy(data["quarantine"])
        self.immunity_level = data["immunity_level"]
        self.stress_accumulation = data["stress_accumulation"]

    def get_health_status(self) -> dict:
        """Получает текущий статус здоровья иммунной системы."""
        risks = []
        recommendations = []
        if self.stress_accumulation > self.stress_threshold:
            severity = "критический" if self.stress_accumulation > 0.8 else "высокий"
            risks.append(
                {
                    "risk": "хронический стресс",
                    "severity": severity,
                    "value": round(self.stress_accumulation, 3),
                }
            )
            recommendations.append("необходимы периоды покоя и восстановления")
        if self.immunity_level < 0.4:
            risks.append(
                {
                    "risk": "слабый иммунитет",
                    "severity": "средний",
                    "value": round(self.immunity_level, 3),
                }
            )
            recommendations.append(
                "необходимо больше доверенных связей с другими существами"
            )

        weak_antibodies = sum(1 for s in self.antibodies.values() if s < 0.5)
        if self.pathogens and weak_antibodies > len(self.pathogens) * 0.6:
            risks.append(
                {
                    "risk": "много слабых антител",
                    "severity": "средний",
                    "value": round(weak_antibodies / len(self.pathogens), 3),
                }
            )
            recommendations.append("важно укреплять иммунитет через позитивный опыт")

        active_pathogens = [
            item["signature"]
            for item in self.quarantine
            if item["status"] == "quarantined"
        ]
        return {
            "health_score": round(self.immunity_level, 3),
            "stress_level": round(self.stress_accumulation, 3),
            "known_threats": len(self.pathogens),
            "strong_antibodies": sum(1 for s in self.antibodies.values() if s >= 0.7),
            "weak_antibodies": weak_antibodies,
            "quarantined": len(active_pathogens),
            "active_pathogens": active_pathogens,
            "risks": risks,
            "recommendations": recommendations,
        }

    def get_recommendations(self) -> list[str]:
        """Получает список рекомендаций для поддержания здоровья."""

        health = self.get_health_status()
        recs = []

        if health["stress_level"] > 0.5:
            recs.append(
                "Введите периоды полного покоя — отдыхайте от интенсивной работы"
            )

        if health["health_score"] < 0.4:
            recs.append("Постройте больше доверенных отношений с другими существами")

        if len(health["risks"]) == 0:
            recs.append(
                "Иммунитет стабилен — продолжайте поддерживать позитивное окружение"
            )

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
            lines.append("⚠️  РИСКИ:")
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
        print(
            f"   → Угроза: {result['is_threat']} ({result.get('threat_type') or '—'})"
        )
        print(f"   → Токсичность: {result['toxic_score']:.2f}")

        immune.neutralize_threat(ctx, success=True)
        print(
            f"   → Нейтрализация: успешная, сила антитела: {immune.antibodies.get(immune._compute_signature(ctx), 0):.2f}"
        )

    print("\n" + "=" * 50)
    print("🟢 ВСТРЕЧИ С ДООВЕРЕННЫМИ КОНТЕКСТАМИ:")
    print("=" * 50)

    for ctx in trusted_contexts:
        result = immune.process_trusted_interaction(ctx)
        print(f"\nКонтекст: '{ctx}'")
        print(f"   → Доверие: {result['trust_score']:.2f}")
        print(f"   → Новый уровень иммунитета: {result['new_immunity_level']:.2f}")

    print("\n" + immune.report_health())
