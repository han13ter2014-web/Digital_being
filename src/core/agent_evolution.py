"""Self-evolution implementations extracted from ``agent.py``.

Call timing stays outside this module: ``autonomous_tick`` calls the analysis
hook and ``agent_runner`` calls ``evolve``. Middleware and legacy paths remain
distinct, and all cross-contour behavior stays on the facade object.
"""

from typing import Dict, Optional

from config.simulation_config import LR_CONFIG
from src.core.buffered_logger import get_logger


def _evolution_tick_impl(self, cycle: int) -> Optional[Dict]:
    """«Эволюция-1»: глаз → рука → проба → голос.

    Раз в EVOLUTION_ANALYSIS_INTERVAL циклов существо меряет себя
    (SelfEvolutionAnalyzer). Сигнал, повторившийся подряд
    EVOLUTION_SIGNAL_THRESHOLD раз, дозревает до черновика
    изменения конфигурации (только белый список безопасных рычагов,
    честный diff из живого LR_CONFIG). Черновик проходит изолированную
    пробу в подпроцессе и только тогда становится предложением
    человеку. Применить его существо не может никогда: решение и
    внедрение — за человеком. Трекер сигналов и отметки циклов живут
    в памяти и не сериализуются: сон стирает след, как в охоте.
    """
    interval = int(getattr(LR_CONFIG, "EVOLUTION_ANALYSIS_INTERVAL", 150))
    if cycle <= 0 or cycle % max(1, interval) != 0:
        return None

    from src.evolution.self_coding import SignalTracker, draft_config_change
    from src.evolution.self_evolution_analyzer import SelfEvolutionAnalyzer

    analyzer = getattr(self, "_evolution_analyzer", None)
    if analyzer is None:
        analyzer = SelfEvolutionAnalyzer(self)
        self._evolution_analyzer = analyzer

    try:
        signals = analyzer.identify_improvements()
    except Exception as e:
        get_logger().log(f"[EVOLUTION] analysis error: {e}")
        return {"error": str(e)}

    report: Dict = {"signals": len(signals)}
    tracker = getattr(self, "_evolution_tracker", None)
    if tracker is None:
        tracker = SignalTracker(
            threshold=int(getattr(LR_CONFIG, "EVOLUTION_SIGNAL_THRESHOLD", 3))
        )
        self._evolution_tracker = tracker

    categories = [str(s["category"]) for s in signals if s.get("category")]
    ripe = tracker.observe(categories)
    if ripe is None:
        return report
    report["ripe_signal"] = ripe

    proposal_api = getattr(self, "architecture_proposal", None)
    if proposal_api is None:
        return report
    # Не более одного ожидающего предложения: человек не должен
    # тонуть в письмах. Следующее дозреет после решения.
    if proposal_api.list_pending():
        report["skipped"] = "есть ожидающее предложение"
        return report
    cooldown = int(getattr(LR_CONFIG, "EVOLUTION_PROPOSAL_COOLDOWN", 500))
    last_cycle = getattr(self, "_last_evolution_proposal_cycle", -cooldown)
    if cycle - last_cycle < cooldown:
        report["skipped"] = "кулдаун"
        return report

    draft = draft_config_change(ripe)
    if draft is None:
        report["no_safe_lever"] = ripe
        return report

    from src.evolution.proposal_verifier import verify_config_change

    verification = verify_config_change(draft["attr"], draft["new"])
    description = (
        f"Сигнал «{ripe}» повторялся {tracker.threshold} анализа подряд.\n"
        f"Обоснование: {draft['rationale']}\n"
        f"Проба в изолированном процессе: "
        f"{'пройдена' if verification.get('passed') else 'НЕ пройдена'} "
        f"({verification.get('cycles', 0)} тактов эволюции)."
    )
    created = self.propose_architecture_change(
        "config_change",
        draft["title"],
        description,
        code_snippet=draft["diff"],
    )
    if not created.get("created"):
        report["proposal_failed"] = created.get("reason")
        return report

    # Дописываем пробу в источник истины предложения (SQL у managed-жизни,
    # файл у standalone). Экспорт всегда синхронизируется из источника.
    proposal_id = created["proposal_id"]
    enriched = proposal_api.enrich(
        proposal_id,
        {"diff": draft["diff"], "verification": verification, "category": ripe},
    )
    if not enriched.get("enriched"):
        get_logger().log(f"[EVOLUTION] proposal enrich error: {enriched.get('reason')}")

    self._last_evolution_proposal_cycle = cycle
    report["proposal_id"] = proposal_id
    report["verification_passed"] = bool(verification.get("passed"))

    interaction = getattr(self, "user_interaction", None)
    if interaction is not None and hasattr(interaction, "send_message"):
        verdict = (
            "проверка в изолированной пробе пройдена"
            if verification.get("passed")
            else "проверка в пробе НЕ пройдена — честно говорю об этом"
        )
        interaction.send_message(
            content=(
                f"Я предлагаю изменение для себя: {draft['title']}. "
                f"{draft['rationale']} Проба: {verdict}. "
                f"Решение за тобой: «одобри {proposal_id}» "
                f"или «отклони {proposal_id}»."
            ),
            msg_type="evolution_proposal",
            tone="honest",
            urgency=0.6,
            context=f"evolution_proposal:{proposal_id}",
            cycle=cycle,
        )
    return report


def evolve_impl(self):
    """Эволюция агента на основе успеха и достижения целей.

    Реализована через middleware-пайплайн (src/core/evolve_pipeline.py).
    Каждая фаза — отдельный middleware: mental_models_tick → motivation
    → soul → attachment → concept_limit → force_forget → intelligence_growth.

    Чтобы добавить новую фазу (например, метрики), достаточно
    вызвать `get_default_pipeline().use("metrics", my_fn)`.
    Чтобы подключить кастомный пайплайн целиком, переопределите
    `self.evolve_pipeline` в подклассе.

    Шаг 1: разрежение тяжёлых «тиков» — использует watchdog.should_run_heavy_tick()
    для пропуска тяжёлых веток когда система под нагрузкой или цикл был долгим.
    """
    from src.core.evolve_pipeline import get_default_pipeline

    get_logger().log(
        f"Эволюция: успех={self.success_streak}, целей={self.completed_goals}"
    )
    # Получаем пайплайн (по умолчанию — стандартный; подклассы могут
    # переопределить через self.evolve_pipeline = MyPipeline()).
    pipeline = getattr(self, "evolve_pipeline", None) or get_default_pipeline()
    # Запускаем. Ошибки middleware изолированы и не ломают эволюцию.
    pipeline.run(self, self.cycle_count)
    return  # Совместимость со старыми callers (если кто-то ждёт None).


def _evolve_legacy_impl(self):
    """Legacy-реализация эволюции (pre-Этап 6 рефакторинга).

    Сохранена как метод `_evolve_legacy` для регрессионных тестов
    и сравнения поведения. **Не вызывайте напрямую** — используйте
    `evolve()`, которая делегирует в middleware-пайплайн.

    Шаг 1: разрежение тяжёлых «тиков» — использует watchdog.should_run_heavy_tick()
    для пропуска тяжёлых веток когда система под нагрузкой или цикл был долгим.
    """
    from src.core.watchdog import get_watchdog

    get_logger().log(
        f"Эволюция: успех={self.success_streak}, целей={self.completed_goals}"
    )

    # Тактуем кеш ментальных моделей (Шаг 4)
    if hasattr(self, "mental_models") and hasattr(self.mental_models, "tick_cycle"):
        self.mental_models.tick_cycle()

    wd = get_watchdog()
    run_heavy = wd.should_run_heavy_tick()

    # === МОТИВАЦИЯ: обновляем потребности и проверяем новые драйвы ===
    # Источник истины — UnifiedMotivationSystem (P0.6-P0.10); legacy
    # MotivationController — fallback только.
    motivation = getattr(self, "motivation_system", None) or getattr(
        self, "motivation", None
    )
    if motivation is not None and (
        not hasattr(motivation, "available") or motivation.available
    ):
        motivation_state = motivation.tick(
            {
                "unknown_concepts": [
                    name
                    for name, node in self.mental_models.concepts.items()
                    if node.confidence < 0.4
                ],
                "novel_areas": list(self.mental_models.concepts.keys())[:5],
                "weak_areas": ["reasoning", "metacognition"],
            }
        )
        # Если мотивация добавила новые цели — логируем
        if motivation_state.get("new_goals"):
            get_logger().log(
                f"🎯 Мотивация добавила {len(motivation_state['new_goals'])} новых целей"
            )

    # === ДУША: синхронный тик всех экзистенциальных систем ===
    # Шаг 1: тяжёлый soul.tick только раз в SOUL_TICK_INTERVAL циклов.
    soul_interval = getattr(LR_CONFIG, "SOUL_TICK_INTERVAL", 10)
    if (
        hasattr(self, "soul")
        and (self.cycle_count % max(1, soul_interval) == 0)
        and run_heavy
    ):
        soul_report = self.tick_soul(self.cycle_count)
        # Логируем квесты и сигналы
        if soul_report["soul"].get("systems", {}).get("meaning", {}).get("new_quest"):
            quest = soul_report["soul"]["systems"]["meaning"]["new_quest"]
            get_logger().flush_immediate(
                f"🌌 Новый экзистенциальный квест: {quest[:60]}"
            )
        if soul_report["embodiment"].get("state") in ("exhausted", "tired"):
            get_logger().log(
                f"😴 Embodiment: {soul_report['embodiment']['state']} "
                f"(fatigue={soul_report['embodiment']['fatigue']:.2f})"
            )
        if soul_report["mortality"].get("phase") in ("autumn", "finale"):
            get_logger().log(
                f"⏳ Mortality: фаза {soul_report['mortality']['phase']} "
                f"(anxiety={soul_report['mortality']['mortality_anxiety']:.2f})"
            )

    # Контакт записывается при принятии ответа, не при ожидании.

    # === Шаг 2: лимит ментальных моделей (вызывается периодически) ===
    if self.cycle_count % 50 == 0:
        try:
            forgotten = self.mental_models.apply_concept_limit()
            if forgotten > 0:
                get_logger().flush_immediate(
                    f"🧹 Лимит ментальных моделей: -{forgotten} слабых концепций"
                )
        except Exception as exc:
            get_logger().log(
                f"[{self.name}] Не удалось применить лимит концепций: {exc}"
            )

    # === Шаг 5: принудительное забывание под давлением памяти ===
    if wd.should_force_forget():
        forgotten = self.mental_models.apply_concept_limit()
        wd.mark_forced_forget(forgotten)
    wd.mark_heavy_tick_done()

    evolution_threshold = 3 + (self.intelligence - 1) * 2
    old_intelligence = self.intelligence

    if (
        self.success_streak >= evolution_threshold
        or self.completed_goals >= self.intelligence * 2
    ):
        self.intelligence += 1
        self.success_streak = 0
        self.energy += 20
        get_logger().flush_immediate(
            f"ЭВОЛЮЦИЯ! Интеллект {old_intelligence} -> {self.intelligence}"
        )
        get_logger().flush_immediate(
            f"[{self.name}] ИНТЕЛЛЕКТ ПОВЫШЕН! Уровень: {self.intelligence}"
        )
        self._save_knowledge_base()

        if self.intelligence % 2 == 0:
            self.set_goal(
                f"Достичь уровня {self.intelligence + 1}", difficulty=self.intelligence
            )

        # Удовлетворяем потребность self_improvement при росте интеллекта
        if hasattr(self, "motivation") and self.motivation.available:
            self.motivation.satisfy_need("competence", amount=0.2)
            self.motivation.satisfy_need("self_improvement", amount=0.15)

        # Удовлетворяем идентичность: укрепить core_self при росте интеллекта
        if hasattr(self, "soul") and self.soul.is_available("self"):
            try:
                core = self.soul.get("self")
                core.identity_stability_score = min(
                    1.0, core.identity_stability_score + 0.05
                )
            except Exception as exc:
                get_logger().log(f"[{self.name}] Не удалось укрепить core_self: {exc}")
