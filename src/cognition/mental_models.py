"""
Система ментальных моделей для автономного формирования понимания мира.

Агент формирует собственные ментальные модели понятий через:
- Встречу с концепциями в разных контекстах
- Анализ связей между концепциями
- Формирование гипотез о значении
- Обновление уверенности на основе опыта

Оптимизации (Шаг 2, 4):
- Мягкий лимит MAX_CONCEPTS (LR_CONFIG) с приоритетным забыванием.
- Кеш find_related_concepts с TTL по cycle_count.
"""

from collections import defaultdict, Counter
from typing import Dict, Tuple
from datetime import datetime


def _lr_config():
    """Ленивый импорт LR_CONFIG чтобы избежать циклов."""
    try:
        from config.simulation_config import LR_CONFIG
        return LR_CONFIG
    except Exception:
        return None


def _mentions(text_lower: str, name_lower: str) -> bool:
    """Есть ли ``name`` в тексте как отдельное слово, а не часть другого.

    Нужно, чтобы «время» не совпало с «временной», а «цель» — с
    «цельностью»: иначе сон начнёт связывать концепции по случайным
    вхождениям букв.
    """
    if not name_lower:
        return False
    index = text_lower.find(name_lower)
    while index != -1:
        before = text_lower[index - 1] if index > 0 else " "
        end = index + len(name_lower)
        after = text_lower[end] if end < len(text_lower) else " "
        if not before.isalnum() and not after.isalnum():
            return True
        index = text_lower.find(name_lower, index + 1)
    return False


_REFLEXIVE_CONCEPTS = frozenset({"я", "ты", "мы"})


# ============================================================
# Уверенность как функция свидетельств
# ============================================================
#
# Раньше уверенность считалась так:
#
#     confidence = 0.1 + 0.7 * (встреч с |valence| > 0.3) / (всего встреч)
#
# У этой формулы три порока, и все три проявились в замерах:
#
# 1. **Обрыв на границе.** При valence ровно 0.3 (а именно это значение
#    пишет путь гипотезы: ``hypothesis['confidence'] * 0.5``) условие
#    ``> 0.3`` ложно, и уверенность остаётся 0.1 навсегда. При 0.31 —
#    сразу 0.8. Сотая доля разницы решала, «знает» агент или «не знает».
#    Замер: 8 встреч, определение 108 символов, уверенность 0.100.
# 2. **Нет объёма.** Одна встреча с 0.8 и десять встреч с 0.8 давали
#    одинаковые 0.8. Количество подтверждений не влияло ни на что.
# 3. **Нет различения силы.** Слабая догадка (0.3) и найденный источник
#    (0.7) весили одинаково — как только перешли порог.
#
# Теперь уверенность — это накопленная сила независимых свидетельств,
# взвешенная их согласованностью. Эмоция valence хранится отдельно;
# старое описание выше объясняет историю формулы, а не текущую семантику.
#
#     сила = сумма evidence_strength по независимым источникам выше порога
#     объём = min(1, сила / EVIDENCE_FULL)
#     согласие = |сумма strength * evidence_direction| / сила
#     confidence = 0.1 + 0.8 * объём * согласие
#
# Свойства (проверены тестами):
#   * одна встреча 0.3 → 0.30 — «видел, но не знаю»;
#   * две встречи 0.3 → 0.50 — уже можно ответить;
#   * четыре встречи 0.3 → 0.90 — потолок;
#   * один найденный источник 0.7 → 0.57;
#   * противоречия снижают: 2×0.3 и 1×−0.3 → 0.30.
#
# Порог намеренно включающий (``>=``): значение 0.3 — рабочее, а не
# граничное, и не должно попадать в «мёртвую зону».

EVIDENCE_MIN = 0.25
EVIDENCE_FULL = 1.2
CONFIDENCE_BASE = 0.1
CONFIDENCE_RANGE = 0.8
CONFIDENCE_MAX = 0.9



class ConceptNode:
    """Узел ментальной модели - представляет одну концепцию."""
    
    def __init__(self, name: str):
        self.name = name
        self.definition_hypothesis = ""  # Собственная гипотеза о значении
        self.experiences = []  # Опыт взаимодействия с концепцией
        self.connections = {}  # Связи с другими концепциями {название: вес}
        self.confidence = 0.1  # Уверенность в определении (0.0 - 1.0)
        self.usage_examples = []  # Примеры использования
        self.contexts_encountered = set()  # Контексты где встречалась
        self.created_at = datetime.now()
        self.last_updated = datetime.now()
    
    def add_experience(
        self, context: str, outcome: str, emotional_valence: float = 0.0,
        *, evidence_strength: float = 0.0, evidence_kind: str = "exposure",
        source: str = "", evidence_direction: int = 1,
    ):
        """Записать переживание; эмоция не является подтверждением знания."""
        import math

        strength = float(evidence_strength)
        if not math.isfinite(strength) or not 0.0 <= strength <= 1.0:
            raise ValueError("evidence_strength должен быть в диапазоне 0..1")
        if evidence_kind not in {"exposure", "hypothesis", "observation", "testimony", "innate", "legacy"}:
            raise ValueError("Неизвестный вид опыта")
        if evidence_direction not in (-1, 1):
            raise ValueError("evidence_direction должен быть -1 или 1")
        if strength and (not source or evidence_kind in {"exposure", "hypothesis", "legacy"}):
            raise ValueError("Свидетельству нужны происхождение и наблюдение/сообщение")
        experience = {
            "context": context,
            "outcome": outcome,
            "valence": emotional_valence,
            "evidence_strength": strength,
            "evidence_kind": evidence_kind,
            "source": source,
            "evidence_direction": evidence_direction,
            "timestamp": datetime.now().isoformat()
        }
        self.experiences.append(experience)
        self.contexts_encountered.add(context)
        self.last_updated = datetime.now()

        self.recompute_confidence()

    # ------------------------------------------------------------------
    # Уверенность из свидетельств
    # ------------------------------------------------------------------

    def evidence(self) -> tuple[float, float]:
        """Сила независимых свидетельств и согласованность направлений.

        Эмоциональная валентность не участвует. Повторение источника,
        собственная гипотеза и старый опыт без происхождения не добавляют
        независимых подтверждений. Направление относится к утверждению,
        а не к приятности переживания.
        """
        import math

        # Повторное чтение того же источника — не независимое подтверждение.
        sources = {}
        for experience in self.experiences:
            if experience.get("evidence_kind") not in {"observation", "testimony", "innate"}:
                continue
            source = experience.get("source")
            if not isinstance(source, str) or not source.strip():
                continue
            try:
                strength = float(experience.get("evidence_strength", 0.0))
                direction = experience.get("evidence_direction", 1)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(strength) or not EVIDENCE_MIN <= strength <= 1.0 or direction not in (-1, 1):
                continue
            key = (source, direction)
            sources[key] = max(sources.get(key, 0.0), strength)
        total = sum(sources.values())
        signed = sum(strength * direction for (_, direction), strength in sources.items())
        agreement = (abs(signed) / total) if total > 0 else 0.0
        return total, agreement

    def evidence_direction(self) -> int:
        sources = {}
        for exp in self.experiences:
            if exp.get("evidence_kind") not in {"observation", "testimony", "innate"}:
                continue
            source = exp.get("source")
            if not source:
                continue
            try:
                strength = float(exp.get("evidence_strength", 0.0))
                direction = exp.get("evidence_direction", 1)
            except (TypeError, ValueError):
                continue
            if EVIDENCE_MIN <= strength <= 1.0 and direction in (-1, 1):
                key = (source, direction)
                sources[key] = max(sources.get(key, 0.0), strength)
        signed = sum(strength * direction for (_, direction), strength in sources.items())
        return 1 if signed > 0 else -1 if signed < 0 else 0

    def recompute_confidence(self) -> float:
        """Пересчитать уверенность из накопленных свидетельств.

        Единственный источник истины: и новая встреча, и сон, и синтез
        определения ведут сюда. Иначе получается то, что было до правки —
        три разных формулы, две из которых давали несовместимые числа.
        """
        strength, agreement = self.evidence()
        volume = min(1.0, strength / EVIDENCE_FULL) if EVIDENCE_FULL > 0 else 0.0
        self.confidence = min(
            CONFIDENCE_MAX,
            CONFIDENCE_BASE + CONFIDENCE_RANGE * volume * agreement,
        )
        return self.confidence

    def to_storage_dict(self) -> dict:
        data = self.to_dict()
        data.update({
            "experiences": [dict(exp) for exp in self.experiences],
            "connections": dict(self.connections),
            "contexts": sorted(self.contexts_encountered),
            "usage_examples": list(self.usage_examples),
            "schema_version": 2,
            "source": getattr(self, "source", ""),
            "tags": list(getattr(self, "tags", [])),
            "legacy_confidence": getattr(self, "legacy_confidence", None),
        })
        return data

    @classmethod
    def from_dict(cls, data: dict):
        node = cls(data["name"])
        node.definition_hypothesis = data.get("definition_hypothesis", "")
        node.connections = dict(data.get("connections", {}))
        node.experiences = [dict(exp) for exp in data.get("experiences", [])]
        for exp in node.experiences:
            # Валентность старых записей неоднозначна: не выдаём эмоцию за факт.
            exp.setdefault("evidence_kind", "legacy")
            exp.setdefault("evidence_strength", 0.0)
            exp.setdefault("source", "")
            exp.setdefault("evidence_direction", 1)
        node.contexts_encountered = set(data.get("contexts", []))
        node.contexts_encountered.update(exp.get("context", "") for exp in node.experiences)
        node.usage_examples = list(data.get("usage_examples", []))
        node.source = data.get("source", "")
        node.tags = list(data.get("tags", []))
        for field in ("created_at", "last_updated"):
            if data.get(field):
                setattr(node, field, datetime.fromisoformat(data[field]))
        if data.get("schema_version", 1) < 2:
            node.legacy_confidence = data.get("confidence", CONFIDENCE_BASE)
        elif data.get("legacy_confidence") is not None:
            node.legacy_confidence = data["legacy_confidence"]
        node.recompute_confidence()
        return node

    def connect_to(self, other_concept: str, weight: float = 0.5):
        """Создает связь с другой концепцией."""
        self.connections[other_concept] = max(self.connections.get(other_concept, 0.0), weight)
    
    def strengthen_connection(self, other_concept: str, delta: float = 0.1):
        """Усиливает существующую связь."""
        if other_concept in self.connections:
            self.connections[other_concept] = min(1.0, self.connections[other_concept] + delta)
    
    def get_related_concepts(self, min_weight: float = 0.3) -> list[dict]:
        """Возвращает связанные концепции с весом выше порога."""
        return [
            {"concept": c, "weight": w}
            for c, w in self.connections.items()
            if w >= min_weight
        ]
    
    def to_dict(self) -> dict:
        """Серилизует узел в словарь."""
        return {
            "name": self.name,
            "definition_hypothesis": self.definition_hypothesis,
            "confidence": round(self.confidence, 3),
            "experience_count": len(self.experiences),
            "connection_count": len(self.connections),
            "contexts": list(self.contexts_encountered)[:10],  # Топ-10 контекстов
            "usage_examples": self.usage_examples[:5],
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat()
        }


class MentalModel:
    """Система ментальных моделей для формирования понимания концепций."""

    def __init__(self, name: str = "default"):
        self.name = name
        self.concepts: dict[str, ConceptNode] = {}  # {название: ConceptNode}
        self.claims = {}
        self.association_memory = []  # История ассоциаций между концепциями
        self.metadata = {
            "created_at": datetime.now().isoformat(),
            "total_concepts_encountered": 0,
            "total_associations": 0,
            "forgotten_count": 0,
        }
        # === Кеш (Шаг 4) ===
        # Структура: {(concept, max_distance): (cycle_count, result)}
        self._related_cache: Dict[Tuple[str, int], Tuple[int, list]] = {}
        self._cycle_counter: int = 0

    def tick_cycle(self) -> None:
        """Увеличить счётчик циклов (для инвалидации кеша)."""
        self._cycle_counter += 1

    # ============================================================
    # Консолидация (сон)
    # ============================================================

    def consolidate(
        self,
        *,
        link_delta: float = 0.05,
        max_links: int = 400,
        max_definitions: int = 25,
        confidence_bonus: float = 0.02,
        scan_batch: int = 400,
    ) -> dict:
        """Осмыслить накопленное: связи, формулировки, уверенность.

        Это работа с текущим графом знаний — то, что происходит во сне.
        Не путать с ``SleepCycle``: тот архивирует значимые концепции в
        долговременную память по таймеру циклов, а здесь меняется сама
        модель (рёбра, формулировки, уверенность). Два разных дела, и
        оба нужны: архив без понимания — склад, понимание без архива —
        забывается при перезапуске.

        Зачем это отдельный шаг, а не часть ``encounter_concept``: во время
        работы агент только записывает опыт. Превращать записи в понимание
        нужно отдельно — иначе «сон» был бы ритуалом, а не работой.

        Три операции, каждая с проверяемым результатом:

        1. **Связи.** Определения содержат имена других концепций
           («X связано с A -> B»). Если концепция A упомянута в
           формулировке X, между ними есть отношение — усиливаем его.
           Раньше связи создавались один раз с весом 0.1 и не укреплялись
           никогда: контексты встреч уникальны (``гипотеза_цикл_12``), их
           пересечение всегда пусто.
        2. **Формулировки.** Концепция с двумя и более встречами, но без
           собственного определения, получает его из накопленного опыта.
           Уже существующая формулировка уточняется по окрепшим связям:
           вместо сырых результатов встреч в ней появляются концепции, с
           которыми связь подкреплена.
        3. **Уверенность.** Пересчитывается из независимых свидетельств.
           Сон не является новым подтверждением и не добавляет бонус.

        Обрабатывается не всё сразу, а порция (``scan_batch``) с
        продвижением курсора: у долгой жизни тысячи концепций, и полный
        перебор на каждом проходе был бы квадратичным.

        Returns:
            Отчёт: сколько связей усилено, сколько определений создано,
            сколько уверенностей стабилизировано.
        """
        names = list(self.concepts)
        total = len(names)
        if total == 0:
            return {
                "links": 0,
                "definitions": 0,
                "confidence": 0,
                "scanned": 0,
                "concepts": 0,
            }

        batch = max(1, int(scan_batch))
        cursor = int(getattr(self, "_consolidation_cursor", 0)) % total
        window = [names[(cursor + offset) % total] for offset in range(min(batch, total))]
        self._consolidation_cursor = (cursor + len(window)) % total

        links = 0
        definitions = 0
        refined = 0
        stabilized = 0

        for name in window:
            node = self.concepts.get(name)
            if node is None:
                continue

            # 1. Связи из собственной формулировки.
            if links < max_links:
                links += self._links_from_definition(
                    name, node, names, link_delta, max_links - links
                )

            # 2. Определение из накопленного опыта.
            if definitions < max_definitions:
                if (
                    len(node.experiences) >= 2
                    and len(str(node.definition_hypothesis or "")) <= 10
                ):
                    self._synthesize_definition(name)
                    if len(str(node.definition_hypothesis or "")) > 10:
                        definitions += 1

            # 2b. Уточнение формулировки по окрепшим связям.
            refined += self._refine_definition(name, node)

            # 3. Стабилизация уверенности.
            before = node.confidence
            node.recompute_confidence()
            if node.confidence != before:
                stabilized += 1

        if links or definitions or refined or stabilized:
            # Граф изменился — кеш обходов устарел.
            self._related_cache.clear()

        return {
            "links": links,
            "definitions": definitions,
            "refined": refined,
            "confidence": stabilized,
            "scanned": len(window),
            "concepts": total,
        }

    def _refine_definition(
        self, name: str, node: ConceptNode, min_weight: float = 0.4
    ) -> int:
        """Переписать формулировку через окрепшие связи.

        Рабочее определение собирается из сырых результатов встреч
        («'X' — текст1 -> текст2») — это ещё не понимание. После того как
        сон укрепил связи, у концепции появляются настоящие соседи, и
        формулировка может опираться на них.

        Ничего не выдумывается: в текст попадают только концепции, с
        которыми уже есть подкреплённая связь (вес ≥ ``min_weight``).
        Рефлексивные примитивы («я», «ты», «мы») исключаются: их связь
        с произвольной темой — общий контекст встречи при рождении, а
        не смысл, и в формулировке они выглядят как «связано с я, ты».
        """
        if len(node.experiences) < 2 or not any(
            exp.get("evidence_kind") in {"hypothesis", "observation", "testimony", "innate"}
            for exp in node.experiences
        ):
            return 0
        strong = [
            other
            for other, weight in sorted(
                node.connections.items(), key=lambda item: item[1], reverse=True
            )
            if weight >= min_weight and other in self.concepts
            and str(other).strip().lower() not in _REFLEXIVE_CONCEPTS
        ][:3]
        if len(strong) < 2:
            return 0
        text = (
            f"По опыту ({len(node.experiences)} встреч): "
            f"'{name}' связано с: {', '.join(strong)}"
        )
        if text == node.definition_hypothesis:
            return 0
        node.definition_hypothesis = text
        return 1

    def _links_from_definition(
        self,
        name: str,
        node: ConceptNode,
        names: list,
        delta: float,
        budget: int,
    ) -> int:
        """Усиливает связи с концепциями, упомянутыми в определении."""
        text = str(node.definition_hypothesis or "")
        if len(text) <= 10 or budget <= 0:
            return 0
        low = text.lower()
        made = 0
        for other in names:
            if made >= budget:
                break
            if other == name:
                continue
            # Короткие имена дают ложные совпадения внутри слов.
            if len(other) < 4:
                continue
            other_node = self.concepts.get(other)
            if other_node is None:
                continue
            if not _mentions(low, other.lower()):
                continue
            current = float(node.connections.get(other, 0.0))
            # Формулировка — уже осмысленное утверждение, а не случайное
            # упоминание: первая связь из неё весит больше, чем связь из
            # беглого упоминания в результате (0.2).
            base = current if current > 0.0 else 0.2
            updated = min(1.0, base + delta)
            if updated <= current:
                continue
            node.connections[other] = updated
            # Связь двусторонняя: упоминание в одну сторону всё равно
            # означает отношение между концепциями.
            other_node.connections[name] = max(
                float(other_node.connections.get(name, 0.0)), updated
            )
            made += 1
        return made

    @staticmethod
    def _has_consistent_experience(node: ConceptNode) -> bool:
        """Опыт согласован: свидетельства есть и указывают в одну сторону.

        Порог тот же, что у уверенности: без него сон «закреплял» бы
        концепции, о которых агент ничего не узнал (одна встреча без
        сигнала), и уверенность росла бы из воздуха.
        """
        strength, agreement = node.evidence()
        return strength >= EVIDENCE_FULL * 0.5 and agreement >= 0.75

    def _invalidate_cache_if_needed(self) -> None:
        """Инвалидирует кеш по TTL."""
        cfg = _lr_config()
        ttl = getattr(cfg, "RELATED_CONCEPTS_CACHE_TTL", 50) if cfg else 50
        if self._cycle_counter % max(1, ttl) == 0:
            self._related_cache.clear()

    def apply_concept_limit(self) -> int:
        """Мягкое ограничение количества концепций (Шаг 2).

        Возвращает количество забытых концепций.
        При превышении MAX_CONCEPTS забывает FORGET_PCT_PER_PASS процентов
        самых слабых (по confidence).
        """
        cfg = _lr_config()
        max_concepts = getattr(cfg, "MAX_CONCEPTS", 20000) if cfg else 20000
        forget_pct = getattr(cfg, "FORGET_PCT_PER_PASS", 5) if cfg else 5

        if len(self.concepts) <= max_concepts:
            return 0

        # Считаем сколько забыть (но не больше, чем превышение)
        over = len(self.concepts) - max_concepts
        target_forget = max(over, int(max_concepts * forget_pct / 100))
        target_forget = min(target_forget, over)

        if target_forget <= 0:
            return 0

        # Сортируем по confidence (по возрастанию — самые слабые первые)
        sorted_nodes = sorted(
            self.concepts.items(),
            key=lambda x: (x[1].confidence, x[1].last_updated),
        )
        forgotten = 0
        for name, _node in sorted_nodes:
            if forgotten >= target_forget:
                break
            del self.concepts[name]
            forgotten += 1

        self.metadata["forgotten_count"] = self.metadata.get("forgotten_count", 0) + forgotten
        # Инвалидируем кеш (связи могли измениться)
        self._related_cache.clear()
        return forgotten

    def encounter_concept(
        self, concept_name: str, context: str, outcome: str, valence: float = 0.0,
        *, evidence_strength: float = 0.0, evidence_kind: str = "exposure",
        source: str = "", evidence_direction: int = 1,
    ) -> ConceptNode:
        """Агент встречает концепцию в определенном контексте."""

        if concept_name not in self.concepts:
            # Новая концепция - создаем узел
            node = ConceptNode(concept_name)
            node.add_experience(
                context, outcome, valence, evidence_strength=evidence_strength,
                evidence_kind=evidence_kind, source=source,
                evidence_direction=evidence_direction,
            )
            self.concepts[concept_name] = node
            self.metadata["total_concepts_encountered"] += 1

            # Ищет связи с существующими концепциями
            self._find_initial_associations(node)
            self._synthesize_definition(concept_name)

            return node
        else:
            # Уже известная концепция - обновляем опыт
            node = self.concepts[concept_name]
            node.add_experience(
                context, outcome, valence, evidence_strength=evidence_strength,
                evidence_kind=evidence_kind, source=source,
                evidence_direction=evidence_direction,
            )

            # Обновляет связи с другими концепциями в этом контексте
            self._update_associations(node)

            # Формирует/обновляет гипотезу определения
            self._synthesize_definition(concept_name)

            return node
    
    def _find_initial_associations(self, new_node: ConceptNode):
        """Находит потенциальные связи для новой концепции.

        Раньше здесь создавалась связь с КАЖДОЙ существующей концепцией
        (вес 0.1) — «на всякий случай». На 80 концепциях это 6320 рёбер,
        и граф превращался в шум: обход в ширину возвращал всё подряд, а
        синтез «находил связи» между случайными темами. Теперь связь
        появляется только по свидетельству — общий контекст встречи или
        упоминание в результате (см. ``_update_associations``).
        """
        if len(self.concepts) < 2:
            return

        for existing_name, existing_node in self.concepts.items():
            if existing_name == new_node.name:
                continue

            common_contexts = new_node.contexts_encountered & existing_node.contexts_encountered
            if common_contexts:
                weight = min(0.7, len(common_contexts) * 0.25)
                new_node.connect_to(existing_name, weight)
                existing_node.connect_to(new_node.name, weight)
                self._record_association(new_node.name, existing_name, weight)
    
    def _update_associations(self, updated_node: ConceptNode):
        """Обновляет ассоциации на основе нового опыта.

        Раньше здесь проверялось пересечение контекстов встреч, но
        контексты уникальны по построению (``гипотеза_цикл_12``,
        ``синтез_цикл_57``): их пересечение всегда пусто, и связи никогда
        не усиливались. Второй сигнал — упоминание другой концепции в
        результате встречи — работает и виден в данных.

        Вес одной встречи намеренно невелик (0.2): одно упоминание — это
        наблюдение, а не знание. До устойчивой связи его доводит сон
        (``consolidate``), когда видит отношение повторно.
        """
        for other_name, other_node in self.concepts.items():
            if other_name == updated_node.name:
                continue

            shared_context = any(
                exp["context"] in other_node.contexts_encountered
                for exp in updated_node.experiences
            )
            mentioned = len(other_name) >= 4 and any(
                _mentions(
                    str(exp.get("outcome") or "").lower(),
                    other_name.lower(),
                )
                for exp in updated_node.experiences
            )
            if not (shared_context or mentioned):
                continue

            weight = 0.4 if shared_context else 0.2
            # Связь создаётся, а не только усиливается: после отказа от
            # «связей со всеми» её может ещё не быть.
            updated_node.connect_to(other_name, weight)
            other_node.connect_to(updated_node.name, weight)
            self._record_association(
                updated_node.name, other_name,
                updated_node.connections.get(other_name, weight),
            )
    
    def _synthesize_definition(self, concept_name: str):
        """Синтезирует гипотезу определения на основе опыта."""
        node = self.concepts[concept_name]
        
        material = [
            exp for exp in node.experiences
            if exp.get("evidence_kind") in {"hypothesis", "observation", "testimony", "innate"}
        ]
        if not material:
            return

        # Содержательное свидетельство важнее собственной догадки.
        supported = [exp for exp in material if exp.get("evidence_strength", 0.0) >= EVIDENCE_MIN]
        if supported:
            material = supported
        context_patterns = defaultdict(list)
        for exp in material:
            # Извлекает ключевые слова из контекста
            keywords = [w for w in exp["context"].split() if len(w) > 3]
            for kw in keywords:
                context_patterns[kw].append(exp)
        
        # Находит наиболее часто встречающиеся паттерны
        most_common = max(context_patterns.items(), key=lambda x: len(x[1])) if context_patterns else (None, [])

        if most_common[0] and len(most_common[1]) >= 2:
            # Формирует гипотезу определения
            common_outcomes = [e["outcome"] for e in most_common[1]]
            outcome_counter = Counter(common_outcomes)
            most_frequent = outcome_counter.most_common(3)
            
            if len(most_frequent) > 0:
                hypothesis_parts = [p[0] for p in most_frequent if p[1] >= 1]
                if hypothesis_parts:
                    node.definition_hypothesis = f"По опыту ({len(node.experiences)} встреч): '{concept_name}' связано с: {' -> '.join(hypothesis_parts[:3])}"
        else:
            # Контексты у разных встреч могут не пересекаться (например,
            # «гипотеза_цикл_12» и «гипотеза_цикл_57»). Раньше в этом
            # случае определение не формировалось НИКОГДА, хотя агент уже
            # дважды сталкивался с концепцией. Теперь собираем определение
            # из самих результатов встреч.
            outcomes = [
                str(e.get("outcome") or "").strip()
                for e in material
                if str(e.get("outcome") or "").strip()
            ]
            if outcomes:
                unique = list(dict.fromkeys(o[:80] for o in outcomes))
                node.definition_hypothesis = (
                    f"По опыту ({len(node.experiences)} встреч): "
                    f"'{concept_name}' — {' -> '.join(unique[:3])}"
                )
        
        # Обновляет уверенность. Формула одна на всю систему: см.
        # ConceptNode.recompute_confidence. Раньше здесь считалась своя
        # (0.3 + (1-дисперсия)*0.5 + встречи*0.05), и она перетирала
        # значение из add_experience — два источника истины давали
        # несовместимые числа.
        node.recompute_confidence()
    
    def _record_association(self, concept1: str, concept2: str, weight: float):
        """Записывает ассоциацию в память."""
        self.association_memory.append({
            "concept1": concept1,
            "concept2": concept2,
            "weight": weight,
            "timestamp": datetime.now().isoformat()
        })
        self.metadata["total_associations"] += 1
    
    def find_concepts_by_context(self, context: str, min_confidence: float = 0.1) -> list[ConceptNode]:
        """Находит концепции связанные с данным контекстом."""
        relevant = []
        for name, node in self.concepts.items():
            # Проверяет пересечение контекстов
            common = len(node.contexts_encountered & set(context.split()))
            if common > 0 or any(ctx in context for ctx in node.contexts_encountered):
                if node.confidence >= min_confidence:
                    relevant.append(node)
        return sorted(relevant, key=lambda n: n.confidence, reverse=True)
    
    def find_related_concepts(self, concept_name: str, max_distance: int = 2) -> list[ConceptNode]:
        """Находит связанные концепции через граф (BFS) с кешированием (Шаг 4)."""
        if concept_name not in self.concepts:
            return []

        self._invalidate_cache_if_needed()
        cache_key = (concept_name, max_distance)
        cached = self._related_cache.get(cache_key)
        if cached is not None:
            cached_cycle, cached_result = cached
            if (self._cycle_counter - cached_cycle) < (
                getattr(_lr_config(), "RELATED_CONCEPTS_CACHE_TTL", 50) or 50
            ):
                return cached_result

        visited = set()
        queue = [(self.concepts[concept_name], 0)]
        result = []

        while queue:
            node, distance = queue.pop(0)

            if node.name in visited or distance > max_distance:
                continue

            visited.add(node.name)
            if node != self.concepts[concept_name]:
                result.append(node)

            for related_name in node.connections:
                if related_name not in visited and related_name in self.concepts:
                    queue.append((self.concepts[related_name], distance + 1))

        result = sorted(result, key=lambda n: n.confidence, reverse=True)
        # Сохраняем в кеш (но не больше MAX_SIMILARITY_CACHE записей)
        cfg = _lr_config()
        max_cache = getattr(cfg, "MAX_SIMILARITY_CACHE", 1000) if cfg else 1000
        if len(self._related_cache) >= max_cache:
            # Простой FIFO: удаляем первый ключ
            try:
                first_key = next(iter(self._related_cache))
                del self._related_cache[first_key]
            except StopIteration:
                pass
        self._related_cache[cache_key] = (self._cycle_counter, result)
        return result
    
    def get_concept_understanding(self, concept_name: str) -> dict:
        """Возвращает полное понимание концепции агентом."""
        if concept_name not in self.concepts:
            return {"unknown": True, "concept": concept_name}
        
        node = self.concepts[concept_name]
        return {
            "concept": concept_name,
            "hypothesis": node.definition_hypothesis,
            "confidence": node.confidence,
            "experience_count": len(node.experiences),
            "evidence_direction": node.evidence_direction(),
            "connections": node.get_related_concepts(),
            "experiences": node.experiences[-5:],  # Последние 5 опытов
            "can_define": node.confidence > 0.5 and len(node.definition_hypothesis) > 10
        }
    
    def can_answer_about(self, concept_name: str) -> bool:
        """Проверяет может ли агент дать осмысленный ответ о концепции."""
        if concept_name not in self.concepts:
            return False
        
        node = self.concepts[concept_name]
        return (node.confidence > 0.4 and 
                len(node.experiences) >= 2 and 
                len(node.definition_hypothesis) > 10)
    
    def to_dict(self) -> dict:
        """Серилизует всю систему ментальных моделей."""
        return {
            "name": self.name,
            "metadata": self.metadata,
            "concepts": {name: node.to_dict() for name, node in self.concepts.items()},
            "recent_associations": self.association_memory[-10:]
        }
    
    def to_storage_dict(self) -> dict:
        data = self.to_dict()
        data["concepts"] = {name: node.to_storage_dict() for name, node in self.concepts.items()}
        data["claims"] = {key: claim.to_dict() for key, claim in self.claims.items()}
        return data

    def print_model_tree(self, concept_name: str = None, indent: int = 0):
        """Визуально отображает ментальную модель."""
        if concept_name:
            if concept_name not in self.concepts:
                print(f"  Концепция '{concept_name}' не найдена в модели")
                return
            
            node = self.concepts[concept_name]
            self._print_node(node, indent)
        else:
            for name, node in self.concepts.items():
                if indent == 0:
                    print(f"\n{'─' * 40}")
                    print(f"  🧠 Ментальная модель: {self.name}")
                    print(f"  Концепций: {len(self.concepts)}")
                    print(f"{'─' * 40}")
                self._print_node(node, indent)
    
    def _print_node(self, node: ConceptNode, indent: int):
        """Визуально отображает один узел с связями."""
        prefix = "  " * indent
        icon = "💡" if node.confidence > 0.7 else "🔍" if node.confidence > 0.4 else "❓"
        
        print(f"{prefix}{icon} {node.name}")
        if node.definition_hypothesis:
            print(f"{prefix}   📝 '{node.definition_hypothesis[:60]}...'")
        print(f"{prefix}   Уверенность: {node.confidence:.1%} | Опыт: {len(node.experiences)} встреч")
        
        if node.connections:
            top_connections = sorted(node.connections.items(), key=lambda x: x[1], reverse=True)[:3]
            for conn_name, weight in top_connections:
                print(f"{prefix}   ↔ {conn_name} ({weight:.1%})")

# ============================================================
# Public API
# ============================================================
__all__ = [
    # Классы
    "ConceptNode",
    "MentalModel",
]
