"""
thinking_pipeline.py — вынесенный мыслительный процесс агента.

До этого момента think() и связанные методы (_generate_hypothesis,
_decompose_query, _try_ask_user_about_complex, _process_user_answer,
_register_unknown_concept, _search_external_knowledge, _read_docstring,
_detect_contradiction, _self_check_knowledge) жили прямо в DigitalBeing,
делая класс god-object-ом.

Теперь они вынесены в ThinkingPipeline — отдельный класс, который
получает ссылку на агента и работает с ним. Это:

- Уменьшает DigitalBeing (минус ~250 строк бизнес-логики)
- Делает мышление тестируемым отдельно
- Позволяет подменить стратегию (например, "наивное мышление" vs "глубокое")

Паттерн: композиция, не наследование. Pipeline хранит ссылку на агента.
"""

import os
import re
import random
from typing import Optional, List, Dict

from src.core.buffered_logger import get_logger
from config.simulation_config import SIM_CONFIG, LR_CONFIG


class ThinkingPipeline:
    """Пайплайн мышления агента.

    Принимает ссылку на DigitalBeing и работает с его mental_models,
    knowledge_base, user_interaction, energy_subsystem, config.
    """

    # Кэш имён файлов в src/ (для _search_external_knowledge)
    _SRC_FILE_INDEX: Optional[set] = None

    def __init__(self, agent, web_searcher=None):
        """
        Args:
            agent: экземпляр DigitalBeing.
            web_searcher: опциональный WebSearcher для поиска в Wikipedia.
                          None = интернет-поиск отключён.
        """
        self.agent = agent
        self.web_searcher = web_searcher

    # ============================================================
    # Главный метод — think()
    # ============================================================

    def think(self, data: str) -> str:
        """Мыслительный процесс: использует ментальные модели и базу знаний.

        Шаги:
        1. Проверяем ментальные модели (автономное понимание).
        2. Проверяем старую базу знаний.
        3. Генерируем гипотезу из известных концепций.
        4. Декомпозиция сложных запросов.
        5. Регистрируем неизвестную концепцию.
        6. Ищем информацию в файлах.
        """
        clean_data = data.replace("вопрос: ", "").strip()
        agent = self.agent

        # === Шаг 1: Ментальные модели ===
        if agent.mental_models.can_answer_about(clean_data):
            understanding = agent.mental_models.get_concept_understanding(clean_data)
            if understanding.get("can_define", False):
                thought = f"[Ментальная модель] '{clean_data}': {understanding['hypothesis']}"
                thought += f" (уверенность: {understanding['confidence']:.0%})"
                related = understanding.get("connections", [])
                if related:
                    top_related = related[:2]
                    thought += f"\n   Связано с: {[r['concept'] for r in top_related]}"
                agent.success_streak += 1
                agent._check_goal_progress(clean_data)
                return thought

        # === Шаг 2: База знаний ===
        if clean_data in agent.knowledge_base:
            thought = f"Знаю ответ: {agent.knowledge_base[clean_data]}"
            agent.success_streak += 1
            agent._check_goal_progress(clean_data)
            return thought

        # === Шаг 3: Гипотеза ===
        hypothesis = self._generate_hypothesis(clean_data)
        if hypothesis:
            thought = f"[Гипотеза] '{clean_data}': {hypothesis['text']} (исходная уверенность: {hypothesis['confidence']:.0%})"
            agent.mental_models.encounter_concept(
                clean_data,
                f"гипотеза_цикл_{agent.cycle_count}",
                hypothesis['text'][:80],
                hypothesis['confidence'] * 0.5,
            )
            agent.energy -= 2
            return thought

        # === Шаг 4: Декомпозиция ===
        decomposed = self._decompose_query(clean_data)
        if decomposed and len(decomposed) > 1:
            thought = f"[Декомпозиция] '{clean_data}' разбиваю на:"
            for i, part in enumerate(decomposed[:3], 1):
                thought += f"\n   {i}. {part}"
            self._try_ask_user_about_complex(clean_data, decomposed)
            return thought

        # === Шаг 5: Регистрация неизвестной концепции ===
        self._register_unknown_concept(clean_data, data)

        # === Шаг 6: Внешние источники ===
        return self._search_external_knowledge(clean_data, data)

    # ============================================================
    # Вспомогательные методы
    # ============================================================

    def _generate_hypothesis(self, concept_name: str) -> Optional[dict]:
        """Генерирует гипотезу о концепции на основе известных понятий."""
        if not LR_CONFIG.HYPOTHESIS_GENERATION_ENABLED:
            return None

        agent = self.agent
        related_nodes = agent.mental_models.find_related_concepts(
            concept_name, max_distance=1
        )
        connections = [{"concept": n.name, "weight": 0.5} for n in related_nodes]
        if not connections:
            return None

        known_facts = []
        for conn in connections[:5]:
            related_name = conn["concept"]
            node = agent.mental_models.concepts.get(related_name)
            if node and node.definition_hypothesis:
                known_facts.append(node.definition_hypothesis)
        if not known_facts:
            return None

        confidence = min(0.9, len(connections) * 0.2
                         + sum(c["weight"] for c in connections[:3]))

        if "что такое" in concept_name or concept_name.startswith("что"):
            template = ("Предполагаю что '{cn}' связано с: {facts}. "
                        "Вероятно имеет отношение к {conns}.")
        elif "как" in concept_name or concept_name.startswith("как"):
            template = ("Думаю '{cn}' работает через механизмы: {facts}. "
                        "Основано на опыте с: {conns}.")
        elif "почему" in concept_name or concept_name.startswith("почему"):
            template = ("Возможно '{cn}' объясняется через: {facts}. "
                        "Связано с причинами: {conns}.")
        else:
            template = ("Гипотеза: '{cn}' может быть понято через: {facts}. "
                        "Опирается на концепцию: {conns}.")

        hypothesis_text = template.format(
            cn=concept_name,
            facts='; '.join(known_facts[:2]),
            conns='/'.join(c['concept'] for c in connections[:2]),
        )

        return {
            "text": hypothesis_text,
            "confidence": max(0.1, confidence * 0.5),
            "based_on": [c["concept"] for c in connections[:3]],
            "type": "hypothesis",
        }

    def _decompose_query(self, query: str) -> Optional[list]:
        """Разбивает сложный запрос на более простые части."""
        decompositions = {
            "трансформер архитектура": [
                "что такое трансформер",
                "как устроена архитектура нейросети",
                "что такое механизм внимания",
            ],
            "обработка естественного языка": [
                "что такое естественный язык",
                "как компьютер обрабатывает текст",
                "что такое NLP",
            ],
            "глубокое обучение": [
                "что такое обучение нейросети",
                "что такое глубокая сеть",
                "как работает backpropagation",
            ],
            "сильный ИИ vs слабый ИИ": [
                "что такое сильный ИИ",
                "что такое слабый ИИ",
                "в чем разница между ИИ",
            ],
            "нейросеть архитектура": [
                "что такое нейрон",
                "как связаны слои нейросети",
                "что такое сверточный слой",
            ],
        }

        for key, parts in decompositions.items():
            if key.lower() in query.lower() or query.lower() in key.lower():
                return parts

        keywords = [w for w in query.split() if len(w) > 3]
        # Strip punctuation from keywords
        keywords = [kw.rstrip('?.!,') for kw in keywords]

        # Filter out pronouns and common words that aren't meaningful concepts
        pronouns = {'меня', 'тебя', 'себя', 'нас', 'вас', 'их', 'его', 'ее', 'их',
                    'мне', 'тебе', 'себе', 'нам', 'вам', 'им',
                    'мной', 'тобой', 'собой', 'нами', 'вами', 'ими',
                    'которой', 'которого', 'который', 'которые',
                    'что', 'кто', 'где', 'когда', 'как', 'почему',
                    'тут', 'там', 'здесь', 'там', 'сейчас', 'тогда',
                    'ты', 'я', 'он', 'она', 'оно', 'мы', 'вы', 'они'}
        # Keep only meaningful words (verbs, nouns, adjectives)
        meaningful = [kw for kw in keywords if kw.lower() not in pronouns]

        if len(meaningful) >= 2:
            # Prioritize verbs (often end in -ть, -ти, -ать, -еть, -ить, -уть, -ыть)
            # and longer words (more likely to be meaningful concepts)
            meaningful.sort(key=lambda w: (w.endswith(('ть', 'ти', 'ать', 'еть', 'ить', 'уть', 'ыть', 'сти')), len(w)), reverse=True)
            return [f"что такое {kw}" for kw in meaningful[:3]]
        elif len(keywords) >= 2:
            # Fallback: use original keywords but prioritize longer ones
            keywords.sort(key=len, reverse=True)
            return [f"что такое {kw}" for kw in keywords[:3]]
        return None

    def _try_ask_user_about_complex(self, concept: str, decomposed: list) -> None:
        """Пытается задать вопрос пользователю о сложной концепции."""
        agent = self.agent
        if agent._user_cooldown > 0:
            agent._user_cooldown -= 1
            return
        if not agent.user_interaction.can_ask_question(agent.cycle_count):
            return

        question = (f"Я изучаю концепцию '{concept}'. "
                    f"Мне сложно понять без внешней помощи. "
                    f"Можете кратко объяснить: {decomposed[0]}?")
        # Передаем ВСЕ под-вопросы для цепочки вопросов и последующего синтеза
        result = agent.user_interaction.ask_user(
            question=question,
            context=f"Концепция: {concept}, под-запросы: {'; '.join(decomposed[:3])}",
            cycle=agent.cycle_count,
            complex_question=concept,
            sub_questions=decomposed,
            sub_question_index=0
        )
        if result.get("status") == "queued":
            agent._user_cooldown = LR_CONFIG.USER_COOLDOWN_AFTER_ANSWER

    def _process_user_answer(self, answer_text: str) -> str:
        """Обрабатывает ответ пользователя и обновляет знания.

        Если это под-вопрос сложного вопроса — продолжает цепочку вопросов.
        Если все под-вопросы отвечены — запускает фазу синтеза.
        """
        agent = self.agent
        pending = agent.user_interaction.get_pending_question()
        if not pending:
            return "Нет ожидающих вопросов."

        # Callback для синтеза когда все под-вопросы отвечены
        def on_synthesis_needed(complex_question: str, sub_answers: dict):
            self._synthesize_complex_question(complex_question, sub_answers)

        result = agent.user_interaction.submit_answer(
            pending["id"], answer_text, on_synthesis_needed=on_synthesis_needed
        )

        concept_name = pending["question"]
        if "задаю" in concept_name or "объясни" in concept_name:
            match = re.search(
                r'(?:объясни|обьясни|расскажи о|что такое)\s+(.+?)[\.\?]',
                concept_name,
            )
            if match:
                concept_name = match.group(1).strip()

        node = agent.mental_models.encounter_concept(
            concept_name=concept_name,
            context=f"пользователь_ответ_цикл_{agent.cycle_count}",
            outcome=answer_text[:100],
            valence=0.8,
        )
        node.confidence = min(1.0, node.confidence + 0.3)

        agent.success_streak += 2
        agent.energy -= 3
        get_logger().log(
            f"Пользователь ответил на '{concept_name}': {answer_text[:50]}..."
        )
        
        # === Внутренняя мотивация: социальное взаимодействие ===
        if hasattr(agent, 'internal_motivation'):
            agent.internal_motivation.on_social_interaction(positive=True)

        # Если был запущен синтез — добавляем информацию в ответ
        synthesis_info = ""
        if result.get("synthesis_needed"):
            synthesis_info = f" [СИНТЕЗ запущен для: {result['complex_question']}]"
        elif result.get("next_sub_question"):
            synthesis_info = " [Следующий под-вопрос поставлен в очередь]"

        return (f"[Ответ агента] Получен ответ от пользователя. "
                f"Концепция '{concept_name}' обновлена "
                f"(уверенность: {node.confidence:.0%}){synthesis_info}")

    # === ФАЗА СИНТЕЗА: превращает под-ответы в понимание целого ===

    def _synthesize_complex_question(self, complex_question: str, sub_answers: dict) -> None:
        """Синтезирует понимание сложного вопроса из ответов на под-вопросы.

        Это КЛЮЧЕВОЙ метод: превращает набор изолированных фактов в целостное понимание.

        Args:
            complex_question: Оригинальный сложный вопрос (например, "Ты меня понимаешь?").
            sub_answers: Словарь {под-вопрос: ответ пользователя}.
        """
        agent = self.agent
        get_logger().log(f"[СИНТЕЗ] Начинаю синтез для: '{complex_question}'")
        get_logger().log(f"[СИНТЕЗ] Под-ответы: {sub_answers}")

        # 1. Собираем определения под-концептов из ментальных моделей
        sub_concepts = {}
        for sub_q, answer in sub_answers.items():
            # Под-вопрос может быть в формате "что такое X" или "что такое X?" или "Также для понимания '...': что такое X?"
            match = re.search(r'что такое\s+([^?]+)', sub_q.lower())
            if match:
                concept_key = match.group(1).strip().rstrip('?').strip()
                # Ищем в ментальных моделях
                node = agent.mental_models.concepts.get(concept_key)
                if node:
                    # Используем definition_hypothesis или последний опыт
                    definition = node.definition_hypothesis or (
                        node.experiences[-1]["outcome"] if node.experiences else ""
                    )
                    sub_concepts[concept_key] = definition
                    get_logger().log(f"[СИНТЕЗ] Найдено определение '{concept_key}': {definition[:80]}...")
                else:
                    get_logger().log(f"[СИНТЕЗ] Концепт '{concept_key}' не найден в ментальных моделях")
            else:
                get_logger().log(f"[СИНТЕЗ] Не удалось извлечь концепт из под-вопроса: {sub_q[:80]}")

        get_logger().log(f"[СИНТЕЗ] Собранные под-концепты: {list(sub_concepts.keys())}")

        # 2. Строим гипотезу о смысле сложного вопроса
        if sub_concepts:
            # Генерируем ответ на исходный вопрос, опираясь на под-концепты
            hypothesis = self._generate_synthesis_hypothesis(
                complex_question, sub_concepts
            )

            # 3. Самопроверка: пытаемся сгенерировать осмысленный ответ
            self_check = self._self_check_synthesis(complex_question, hypothesis, sub_concepts)

            if self_check:
                # УСПЕХ: агент ПОНИМАЕТ вопрос
                agent.mental_models.encounter_concept(
                    concept_name=complex_question,
                    context=f"synthesis_cycle_{agent.cycle_count}",
                    outcome=hypothesis,
                    valence=0.9,
                )
                # Увеличиваем уверенность — это ПОНИМАНИЕ, а не просто факт
                node = agent.mental_models.concepts.get(complex_question)
                if node:
                    node.confidence = min(1.0, node.confidence + 0.5)

                agent.success_streak += 5
                agent.intelligence += 2
                get_logger().log(f"[СИНТЕЗ УСПЕХ] '{complex_question}' -> '{hypothesis[:100]}...'")
                get_logger().log(f"[СИНТЕЗ] Интеллект +2, уверенность повышена")
                
                # === Внутренняя мотивация: концепт усвоен ===
                if hasattr(agent, 'internal_motivation'):
                    # Уверенность узла как мера качества усвоения
                    node = agent.mental_models.concepts.get(complex_question)
                    confidence = node.confidence if node else 0.5
                    agent.internal_motivation.on_concept_learned(complex_question, confidence)
                    # Синтез — это и творческий акт
                    agent.internal_motivation.on_creative_act(novelty=0.7)
            else:
                # Неудача: понимание не сложилось
                get_logger().log(f"[СИНТЕЗ НЕУДАЧА] Не смог синтезировать понимание для '{complex_question}'")
        else:
            get_logger().log(f"[СИНТЕЗ] Нет под-концептов для синтеза")

    def _generate_synthesis_hypothesis(self, complex_question: str, sub_concepts: dict) -> str:
        """Генерирует гипотезу-ответ на сложный вопрос на основе под-концептов."""
        parts = []
        for concept, definition in sub_concepts.items():
            parts.append(f"{concept} — {definition[:150]}")

        q_lower = complex_question.lower()
        if "понимаешь" in q_lower or "понимать" in q_lower:
            return (f"Понимать — значит интегрировать смысл сказанного в свою модель мира. "
                    f"На основе под-концептов: {'; '.join(parts)}")
        elif "что такое" in q_lower:
            return f"Синтез под-концептов: {'; '.join(parts)}"
        else:
            return f"На основе понимания под-частей: {'; '.join(parts)}"

    def _self_check_synthesis(self, complex_question: str, hypothesis: str, sub_concepts: dict) -> bool:
        """Самопроверка синтеза: пробует сгенерировать ответ и оценивает качество.

        Возвращает True если синтез кажется осмысленным.
        """
        hypothesis_lower = hypothesis.lower()
        key_words = set()
        for concept in sub_concepts:
            key_words.update(concept.split())

        matches = sum(1 for w in key_words if w in hypothesis_lower)
        # Минимум 2 ключевых слова из под-концептов должны присутствовать
        return matches >= 2

    def _register_unknown_concept(self, clean_data: str, original_data: str) -> None:
        """Регистрирует новую концепцию в ментальных моделях."""
        agent = self.agent
        context = f"цикл_{agent.cycle_count}_{clean_data}"
        keywords = [w for w in clean_data.split() if len(w) > 3]
        if keywords:
            outcome = f"Новая концепция, связана с: {'/'.join(keywords[:3])}"
        else:
            outcome = f"Неизвестный стимул: '{clean_data}'"
        valence = 0.0 if "вопрос" in original_data else 0.3
        node = agent.mental_models.encounter_concept(
            concept_name=clean_data,
            context=context,
            outcome=outcome,
            valence=valence,
        )
        get_logger().log(f"Новый концепт: '{clean_data}' (уверенность: {node.confidence:.0%})")

    def _search_external_knowledge(self, clean_data: str, original_data: str) -> str:
        """Этап 2.5: локальный поиск → web-фоллбэк через Wikipedia.

        1. Сначала ищем в файлах src/ (как раньше — docstring Python-файлов).
        2. Если не нашли — пробуем интернет через WebSearcher (Wikipedia API).
        3. Если и там пусто — признаёмся, что не знаем.
        """
        agent = self.agent
        thought = f"Не знаю ответа на '{original_data}'. Формирую гипотезу на основе структуры."
        get_logger().log(f"Поиск: {clean_data}")

        keywords = clean_data.split()
        search_terms = [w for w in keywords
                        if w not in ("команда", "вопрос", "что", "такое")]

        # === Этап 1: локальный поиск в src/ ===
        index = self._get_src_file_index()
        filepath = None
        for term in search_terms:
            for candidate in (f"{term}.py", f"{term}_command.py"):
                if candidate in index:
                    filepath = f"src/{candidate}"
                    break
            if filepath:
                break

        if filepath:
            docstring = self._read_docstring(filepath)
            if docstring:
                contradictions = self._detect_contradiction(clean_data, docstring)
                if contradictions:
                    warning = "\n  ⚠️ Обнаружены возможные противоречия с известными:"
                    for c in contradictions[:2]:
                        warning += (f"\n     - '{c['known_topic']}': {c['known_def'][:40]}..."
                                    f" (конфликт: {c['conflict_ratio']:.0%})")
                    get_logger().log(warning)

                agent._known_definitions[clean_data] = docstring
                agent._prune_knowledge_base_if_needed()
                agent.knowledge_base[clean_data] = docstring
                agent._save_knowledge_base()

                context = f"поиск_в_файле:{filepath}"
                outcome = docstring[:80]
                agent.mental_models.encounter_concept(clean_data, context, outcome, 0.5)

                thought = f"Нашел ответ в файле {filepath}: {docstring[:100]}..."
                agent.success_streak += 1
                agent._check_goal_progress(clean_data)
                return thought
            thought = f"Файл {filepath} найден, но не содержит документации"
        else:
            thought = (f"Не нашел файл для '{clean_data}'. "
                       f"Концепт записан для дальнейшего изучения.")
            agent.preferences[clean_data] = "unknown"

        # === Этап 2: web-фоллбэк (Wikipedia) ===
        # Срабатывает, если локально не нашли (или файл пустой).
        if self.web_searcher and self.web_searcher.is_enabled:
            web_result = self._search_web(clean_data)
            if web_result.get("found"):
                return self._apply_web_result(clean_data, web_result, thought)

        # === Этап 3: не нашли нигде ===
        agent.success_streak = 0
        return thought

    def _search_web(self, clean_data: str) -> dict:
        """Безопасный вызов WebSearcher.search с try/except."""
        try:
            return self.web_searcher.search(clean_data)
        except Exception as e:
            get_logger().log(f"WebSearcher упал: {e}")
            return {"found": False, "error": "exception"}

    def _apply_web_result(self, clean_data: str, web_result: dict, fallback_thought: str) -> str:
        """Применяет web-результат: сохраняет в KB, публикует событие, возвращает мысль.

        Args:
            clean_data: имя концепции.
            web_result: словарь от WebSearcher.search().
            fallback_thought: что вернуть, если web-результат не применим.

        Returns:
            Текст мысли для логирования и EventBus.
        """
        agent = self.agent
        extract = web_result["extract"]
        title = web_result["title"]
        url = web_result["url"]
        lang = web_result.get("lang", self.web_searcher.lang)

        # 1. Сохранить в knowledge_base и mental_models.
        agent._known_definitions[clean_data] = extract
        agent._prune_knowledge_base_if_needed()
        agent.knowledge_base[clean_data] = extract
        agent._save_knowledge_base()

        # 2. ЧЕСТНОЕ ОБУЧЕНИЕ: проверки перед закреплением
        
        # 2a. Найти противоречия с уже известным
        contradictions = self._detect_contradiction(clean_data, extract)
        
        # 2b. Найти связанные концепции в mental_models
        related = agent.mental_models.find_related_concepts(clean_data, max_distance=2)
        related_info = [
            {"concept": n.name, "confidence": n.confidence}
            for n in related
        ]
        
        # 2c. Самопроверка: "Действительно ли я это понимаю?"
        self_check = self._self_check_knowledge(clean_data)
        
        # 2d. Вычислить обоснованную уверенность (не жёсткие 0.7)
        # Базовая уверенность от веба
        base_confidence = 0.7
        # Бонус за связанные высокоуверенные концепции
        related_bonus = min(0.2, len([n for n in related if n.confidence > 0.6]) * 0.05)
        # Штраф за противоречия
        contradiction_penalty = min(0.3, len(contradictions) * 0.15)
        # Бонус за прохождение самопроверки
        self_check_bonus = 0.1 if self_check.get("can_apply") else 0.0
        
        final_confidence = max(0.1, min(0.95, base_confidence + related_bonus - contradiction_penalty + self_check_bonus))

        # 3. Зарегистрировать в mental_models с обоснованной уверенностью
        agent.mental_models.encounter_concept(
            clean_data,
            f"web:{lang}_wikipedia",
            extract[:80],
            final_confidence,
        )
        
        # 4. Сохранить метаданные обучения для анализа
        if not hasattr(agent, "_learning_metadata"):
            agent._learning_metadata = {}
        agent._learning_metadata[clean_data] = {
            "source": f"web:{lang}_wikipedia",
            "title": title,
            "url": url,
            "final_confidence": final_confidence,
            "contradictions": contradictions,
            "related_concepts": related_info,
            "self_check": self_check,
            "cycle": agent.cycle_count,
        }

        # 5. Увеличиваем success_streak ТОЛЬКО если обучение выглядит надёжным
        # (нет тяжёлых противоречий, самопроверка пройдена или есть связи)
        learning_quality_ok = (
            len(contradictions) == 0 or max((c.get("conflict_ratio", 0) for c in contradictions), default=0) < 0.5
        ) and (self_check.get("can_apply") or len(related) > 0)
        
        if learning_quality_ok:
            agent.success_streak += 1
        else:
            # Плохое качество обучения — сбрасываем стрик
            agent.success_streak = max(0, agent.success_streak - 1)
            
        agent._check_goal_progress(clean_data)

        # 6. Публикуем событие в EventBus (обогащённое метаданными)
        self._publish_web_result(clean_data, title, extract, url, lang, {
            "final_confidence": final_confidence,
            "contradictions_count": len(contradictions),
            "related_count": len(related),
            "self_check_passed": self_check.get("can_apply", False),
            "learning_quality_ok": learning_quality_ok,
        })

        # 7. Формируем мысль с честной оценкой
        thought_parts = [f"🌐 Нашёл в интернете (Wikipedia/{lang}): '{title}'"]
        thought_parts.append(f"{extract[:300]}{'…' if len(extract) > 300 else ''}")
        thought_parts.append(f"Источник: {url}")
        thought_parts.append(f"Уверенность: {final_confidence:.0%}")
        if related_info:
            top_related = [r["concept"] for r in related_info[:3]]
            thought_parts.append(f"Связано с: {top_related}")
        if contradictions:
            thought_parts.append(f"⚠️ Противоречий: {len(contradictions)}")
        if self_check.get("can_apply"):
            thought_parts.append("✅ Самопроверка пройдена")
        else:
            thought_parts.append("❓ Самопроверка: недостаточно связей для уверенного применения")
        
        return "\n".join(thought_parts)

    def _publish_web_result(self, concept: str, title: str, extract: str,
                            url: str, lang: str, metadata: dict = None) -> None:
        """Публикует событие AGENT_WEB_RESULT в EventBus.

        Использует user_interaction._publish — тот же приватный метод, что
        используют ask_user / send_message. Ничего не делает, если bus не
        привязан (терминальный режим main.py).
        """
        ui = getattr(self.agent, "user_interaction", None)
        if ui is None:
            return
        try:
            from src.core.event_bus import Events
            payload = {
                "concept": concept,
                "title": title,
                "extract": extract[:500],  # не спамим чат
                "url": url,
                "lang": lang,
                "agent_name": getattr(self.agent, "name", "Agent"),
            }
            if metadata:
                payload.update(metadata)
            ui._publish(
                Events.AGENT_WEB_RESULT,
                payload,
                priority=1,
            )
        except Exception:
            pass  # GUI не критичен — событие просто не дойдёт до ChatWindow

    def _read_docstring(self, filepath: str) -> Optional[str]:
        """Извлекает docstring (первый встреченный) из Python-файла."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            for quote in ('"""', "'''"):
                start = content.find(quote)
                if start == -1:
                    continue
                end = content.find(quote, start + 3)
                if end == -1:
                    continue
                docstring = content[start + 3:end].strip()
                return docstring if docstring else None
        except Exception:
            return None
        return None

    def _detect_contradiction(self, new_topic: str, new_def: str) -> List[dict]:
        """Обнаруживает противоречия между новым знанием и существующим."""
        agent = self.agent
        if not LR_CONFIG.CONTRADICTION_DETECTION:
            return []
        contradictions = []
        new_words = set(new_def.lower().split())
        for known_topic, known_def in agent._known_definitions.items():
            known_words = set(known_def.lower().split())
            topic_similarity = (
                len(set(new_topic.lower().split()) & set(known_topic.lower().split()))
                / max(len(set(new_topic.lower().split())), 1)
            )
            if topic_similarity > 0.3:
                diff_new = new_words - known_words
                diff_known = known_words - new_words
                if (len(diff_new) / max(len(new_words), 1) > 0.5
                        or len(diff_known) / max(len(known_words), 1) > 0.5):
                    contradictions.append({
                        "known_topic": known_topic,
                        "known_def": known_def[:80],
                        "new_def": new_def[:80],
                        "similarity": topic_similarity,
                        "conflict_ratio": (
                            max(len(diff_new), len(diff_known))
                            / max(len(new_words | known_words), 1)
                        ),
                    })
        return contradictions

    def _self_check_knowledge(self, target_concept: str) -> dict:
        """Самопроверяет уровень знаний по концепции перед применением."""
        agent = self.agent
        if not LR_CONFIG.SELF_CHECK_ENABLED:
            return {"can_apply": False, "reason": "Самопроверка отключена"}
        related = agent.mental_models.find_related_concepts(
            target_concept, max_distance=1
        )
        known_count = sum(1 for n in related if n.confidence > 0.5)
        can_apply = known_count >= LR_CONFIG.SELF_CHECK_MIN_CONCEPTS

        closest_match = None
        best_similarity = 0
        for known_topic, def_text in agent._known_definitions.items():
            words1 = set(target_concept.lower().split())
            words2 = set(known_topic.lower().split())
            similarity = len(words1 & words2) / max(len(words1 | words2), 1)
            if similarity > best_similarity:
                best_similarity = similarity
                closest_match = known_topic

        return {
            "can_apply": can_apply,
            "related_concepts_count": len(related),
            "high_confidence_concepts": known_count,
            "closest_known": closest_match,
            "similarity": best_similarity,
            "confidence_score": min(
                1.0, (known_count / max(LR_CONFIG.SELF_CHECK_MIN_CONCEPTS, 1))
            ),
        }

    # ============================================================
    # Кэш файлов (для оптимизации поиска)
    # ============================================================

    @classmethod
    def _get_src_file_index(cls) -> set:
        """Возвращает кэш имён файлов в src/."""
        if cls._SRC_FILE_INDEX is None:
            cls._SRC_FILE_INDEX = set()
            try:
                for root, _dirs, files in os.walk("src"):
                    for f in files:
                        if f.endswith(".py"):
                            rel = os.path.relpath(
                                os.path.join(root, f), "src"
                            ).replace("\\", "/")
                            cls._SRC_FILE_INDEX.add(rel)
            except Exception:
                pass
        return cls._SRC_FILE_INDEX

    @classmethod
    def _invalidate_src_file_index(cls) -> None:
        """Сброс кэша файлов."""
        cls._SRC_FILE_INDEX = None

# ============================================================
# Public API
# ============================================================
__all__ = [
    # Классы
    "ThinkingPipeline",
]
