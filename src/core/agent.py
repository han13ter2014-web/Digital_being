import json
import time
import gc
import random
import re
from datetime import datetime
import os
from typing import Dict, List, Optional
from src.cognition.reflection_engine import ReflectionEngine
from src.cognition.mental_models import MentalModel
from src.cognition.thinking_pipeline import ThinkingPipeline
from config.simulation_config import SIM_CONFIG, LR_CONFIG
from config.will_config import WILL_CONFIG
from src.core.buffered_logger import get_logger
from src.core.action_budget import ActionBudget
from src.core.subsystems import (
    GoalSubsystem,
    KnowledgeSubsystem,
    EnergySubsystem,
    CheckpointSubsystem,
    ReflectionPipeline,
    MotivationController,
    SoulController,
    DecisionArbitrator,
    AttachmentSystem,
    SleepCycle,
    EmbodimentController,
    MortalityAwareness,
    WillRegistry,
    RightToRefuse,
    IntentionalForgetting,
    ValueEvolution,
    SpontaneousGenerator,
    WillToRisk,
    RightToFail,
    MindDream,
    SelfTermination,
    ArchitectureProposal,
    ProactiveCommunication,
    NamingDialogue,
)
from src.perception.user_interaction import UserInteraction
# Импорт LongTermMemory через нормальный пакет (Этап 2.2).
from src.memory import LongTermMemory
from src.memory.knowledge_quality import (
    REASON_TITLES,
    STOP_WORDS,
    clean_knowledge_base,
    normalize_concept_name,
)
from src.core.paths import data_path
# Bootstrap knowledge (родовые знания)
from src.core.bootstrap_knowledge import load_initial_knowledge
# Internal motivation (внутренняя мотивация)
from src.core.internal_motivation import create_motivation_system
from src.core.motivation.unified_motivation import create_motivation_system as create_unified_motivation_system
# Active Inference (активный вывод / свободная энергия)
from src.cognition.active_inference import create_active_inference_engine, encode_observations
# New systems: Interoception, Continuous Time, Meta-Learning, Social Cell, Death Risk
from src.core.interoception import create_interoceptive_model
from src.core.continuous_time import create_continuous_time_engine
from src.core.meta_learning import create_meta_learner
from src.core.social_cell import create_social_cell
from src.core.death_risk import create_death_risk_engine
# Этап 3.5: PluginRegistry — единый реестр всех подсистем для dashboard/расширяемости.
from src.core.subsystem_base import (
    PluginRegistry,
    attach_existing_subsystem,
)
# Stage 18B: the core owns the clock for pending effector requests.
from src.core.effector_driver import EffectorDriver
# Защита жизни: ни один путь не останавливает агента без явного согласия.
from src.core.life_guard import (
    KIND_TERMINATE,
    STATE_ALIVE,
    ConfirmationError,
    LifeGuard,
)
# Замыкание петли: действие → наблюдаемый результат → прогресс цели.
from src.core.loop_closure import LoopCloser
from src.core.world_delta import WorldDelta, capture
from src.core.agent_reflection import (
    reflect_impl,
    generate_self_analysis_report_impl,
    get_performance_metrics_impl,
    get_mental_models_status_impl,
    display_mental_model_impl,
    display_all_concepts_impl,
    get_agent_identity_impl,
)
from src.core.agent_goals import (
    _generate_initial_goals_impl,
    set_goal_impl,
    complete_goal_impl,
    _set_next_goal_impl,
    get_goals_status_impl,
    get_all_goals_with_progress_impl,
    _get_src_file_index_impl,
    _invalidate_src_file_index_impl,
    _goal_subject_tokens_impl,
    _topic_is_relevant_to_goal_impl,
    _match_rule_to_goal_impl,
    _topic_matches_rule_impl,
    _check_goal_progress_impl,
)
from src.core.agent_body import (
    RECOVERY_ACTIONS,
    ESSENTIAL_ACTIONS,
    BODY_LOAD,
    BODY_REST_DEPTH,
    HEAVY_ACTIONS,
    BODY_DENIED_LOAD,
    step_body,
    _get_adaptive_cost_impl,
    _recover_energy_impl,
    _body_needs_rest_impl,
    _body_recovered_impl,
    _update_rest_mode_impl,
    _is_resting_impl,
    _action_cost_now_impl,
    _is_action_affordable_impl,
    _accumulate_sleep_impl,
    _adapt_costs_after_action_impl,
)
from src.core.agent_persistence import (
    save_state_impl,
    capture_structural_state_impl,
    restore_from_checkpoint_impl,
    perform_forgetting_impl,
    _prune_knowledge_base_impl,
    _prune_knowledge_base_if_needed_impl,
    _apply_knowledge_limits_impl,
    _load_knowledge_base_impl,
    _save_knowledge_base_impl,
    load_state_impl,
    save_mental_models_impl,
    load_mental_models_impl,
)
from src.core.agent_properties import (
    energy_get_impl,
    energy_set_impl,
    knowledge_base_get_impl,
    knowledge_base_set_impl,
    open_questions_get_impl,
    open_questions_set_impl,
)
from src.core.agent_effector import (
    _record_core_life_episode_impl,
    _complete_effector_intention_impl,
    _on_effector_result_impl,
)
from src.core.agent_selection import (
    _META_TOPIC_WORDS,
    _NOISE_TOPIC_WORDS,
    _METHOD_VALUE_MAP,
    _social_candidates_impl,
    _is_action_available_impl,
    _is_candidate_available_impl,
    _decomposition_has_room_impl,
    _stuck_fallback_impl,
    _release_recovered_denials_impl,
    _has_question_target_impl,
    _can_ask_now_impl,
    _dampen_impl,
    _record_denied_impl,
    _normalize_action_impl,
)
from src.core.agent_communication import (
    tick_communication_impl,
    start_naming_dialogue_impl,
    ask_user_impl,
    hint_to_open_question_impl,
    drop_open_question_impl,
    get_open_questions_impl,
    has_open_questions_impl,
    answer_open_question_impl,
    _on_user_answered_open_question_impl,
    record_user_answer_impl,
    mute_topic_impl,
    _consume_open_question_impl,
    _record_open_question_exploration_impl,
    propose_name_impl,
    request_renaming_impl,
    add_quiet_app_impl,
    remove_quiet_app_impl,
    get_communication_stats_impl,
)
from src.core.agent_handlers import (
    _act_explore_impl,
    _act_decompose_impl,
    _queue_sub_questions_impl,
    _act_synthesize_impl,
    _act_reflect_impl,
    _defer_ask_intention_impl,
    _act_ask_user_impl,
    _act_communicate_impl,
    _compose_share_message_impl,
    _remember_shared_topic_impl,
    _act_web_search_impl,
    _pick_news_topic_impl,
    _act_read_news_impl,
    _act_browse_web_impl,
    _act_hypothesis_impl,
    _act_set_own_goal_impl,
    _record_will_impl,
)
from src.core.agent_exploration import (
    _is_learnable_impl,
    _is_meta_topic_impl,
    _is_meaningful_topic_impl,
    _recently_explained_by_user_impl,
    _pick_shallow_concept_impl,
    _pick_exploration_target_impl,
    _decomposable_targets_impl,
    _pick_decomposable_target_impl,
    _stimulus_topics_impl,
    _remember_exploration_impl,
)
from src.core.agent_creative import (
    leave_creative_draft_impl,
    list_creative_drafts_impl,
    _pick_art_theme_impl,
    _art_richness_impl,
    _act_draw_impl,
    list_art_works_impl,
    _act_compose_music_impl,
    list_music_works_impl,
    _reward_creative_success_impl,
    _record_creative_failure_impl,
)
from src.core.agent_emotional import (
    EMOTION_ACTION_BIAS,
    _emotions_from_death_risk_impl,
    _emotions_from_mortality_impl,
    _apply_emotional_bias_impl,
)
from src.core.agent_evolution import (
    _evolution_tick_impl,
    evolve_impl,
    _evolve_legacy_impl,
)
from src.core.agent_act import act_impl, _set_aliases_table
from src.core.agent_autonomous_tick import (
    _record_active_inference_experience_impl,
    _ingest_motivation_goals_impl,
    autonomous_tick_impl,
)
from src.core.agent_creation import (
    _init_subsystems_declaratively_impl,
    _register_all_subsystems_in_registry_impl,
    _run_post_init_hooks_impl,
    _wire_subsystem_dependencies_impl,
    get_subsystems_status_impl,
    init_impl,
    tick_subsystems_impl,
)


class AgentDeadSignal(Exception):
    """Signal that the agent has died — not an error, but expected termination.
    
    Raised by autonomous_tick when death_risk reports the agent is dead.
    The runner should catch this and perform graceful shutdown.
    """
    def __init__(self, cause: str, legacy: Dict):
        self.cause = cause
        self.legacy = legacy
        super().__init__(f"Agent died: {cause}")


def record_denied_outcome(obj, action_type: str, world_before, reason: str) -> None:
    """Отказ — тоже исход: мир не изменился, действие не сработало.

    Модульная функция, а не метод: ``act()`` вызывается и в лёгких
    объектах без подсистем, и отказ не должен падать из-за отсутствия
    метода.
    """
    closer = getattr(obj, "loop_closer", None)
    if closer is None:
        return
    try:
        outcome = closer.observe_agent_action(
            obj, action_type, world_before, reason=f"denied:{reason}"
        )
        # Для диагностики: последний исход должен быть виден и при отказе.
        obj._last_action_outcome = outcome
    except Exception:
        pass


class DigitalBeing:
    # Соответствие «имя действия от Active Inference / мотивации / арбитра»
    # → тип действия. Раньше всё это попадало в «default» и не делало
    # ничего: агент «исследовал» мир, не совершая ни одного наблюдения.
    #
    # Мотивация использует типы целей как имена действий
    # («exploration», «learning», «creative»), поэтому таблица шире, чем
    # список действий Active Inference.
    ACTION_ALIASES = {
        "let_go": "let_go",
        # исследование — реальная работа с неизвестным
        "play": "play",
        "draw": "draw",
        # «Музыка-1»: сочинение мелодии — отпечаток состояния в звуке
        "compose_music": "compose_music",
        "explore": "explore",
        "exploration": "explore",
        "novelty_seeking": "explore",
        "discovery": "explore",
        "experiment": "explore",
        "learning": "explore",
        "skill_building": "explore",
        "deep_understanding": "explore",
        "understanding": "explore",
        "practice": "explore",
        # синтез — собрать смысл из известных связей
        "synthesis": "synthesis",
        "synthesize": "synthesis",
        "synthesize_understanding": "synthesis",
        "creative": "synthesis",
        "creative_act": "create_draft",
        "create_draft": "create_draft",
        "philosophy": "synthesis",
        # декомпозиция
        "think_decompose": "decomposition",
        "decompose_concept": "decomposition",
        "organize_knowledge": "decomposition",
        # известное
        "think_known": "know_answer",
        # поиск в сети (мотивация предлагает его как «web_search»)
        "web_search": "web_search",
        # «Источники-2»: чтение новостей — окно в «сегодня»
        "read_news": "read_news",
        # «Интернет-1»: прогулка по открытому вебу
        "browse_web": "browse_web",
        # гипотеза и своя цель: мотивация предлагает их напрямую
        "hypothesis": "hypothesis",
        "set_own_goal": "set_own_goal",
        "make_choice": "reflection",
        # «Практика: {skill}» — это работа с материалом
        "act": "explore",
        # отдых
        "rest": "rest",
        "deep_rest": "deep_rest",
        # восстановление
        "repair": "repair",
        "checkpoint_now": "checkpoint_now",
        # рефлексия
        "reflect": "reflection",
        "reflection": "reflection",
        "self_reflect": "reflection",
        # общение
        "ask_user": "ask_user",
        "ask_question": "ask_user",
        "communicate": "communicate",
        "user_answer": "communicate",
        "teach_other": "communicate",
        "propose_alternative": "communicate",
        # «Сироты-1» (k16-10): имена из related_actions/DRIVE_GOAL_TEMPLATES,
        # которые предлагались мотивацией, но никогда не ловились здесь —
        # действие исполнялось вхолостую (default) и сжигало цикл.
        # social_interaction — rank-1 способ нужды connection
        # (unified_motivation.py:184), teaching — шаблон connection и
        # драйва self_transcendence; оба — общение по смыслу.
        "social_interaction": "communicate",
        "teaching": "communicate",
        # contribution — «создать ресурс для других» (шаблон
        # self_transcendence): сборка смысла из известного — синтез.
        # Мост удовлетворения проверен: communicate гасит
        # connection+competence, synthesis — curiosity/competence/
        # meaning/coherence.
        "contribution": "synthesis",
        # legacy и helping_others НЕ маппим сознательно: это вопрос
        # личности, решает владелец. Они продолжают давать честный
        # default (исполнение впустую → sadness, k16-03).
        # явные «ничего не делать»
        "wait": "wait",
        "none": "wait",
    }

    def __init__(self, name="Lucy", life_id=None, profile_managed=False):
        init_impl(self, name, life_id, profile_managed)

    # =====================================================================
    # ДЕКЛАРАТИВНАЯ ИНИЦИАЛИЗАЦИЯ ПОДСИСТЕМ
    # =====================================================================
    # Раньше `__init__` содержал ~200 строк ручных присваиваний подсистем.
    # Сейчас — один декларативный список SUBSYSTEM_SPECS + helper-методы.
    # Чтобы добавить/убрать подсистему, достаточно изменить одну строку.
    #
    # Структура SUBSYSTEM_SPECS:
    #   (attr_name, factory_callable, post_init_hook_or_None, priority_in_registry)
    #
    # factory_callable: lambda name: SomeSubsystem(agent_name=name)
    #                   или lambda: SomeSubsystem(...) — для кастомной инициализации.
    # post_init_hook:   lambda agent: agent.attr_name.extra_setup()
    #                   или None.
    #
    # Если какая-то подсистема требует специальной инициализации
    # (как knowledge_subsystem с синхронизацией), она делает это в post_init_hook.
    # =====================================================================
    SUBSYSTEM_SPECS = [
        # (имя_атрибута,           конструктор,                                        post_init,                                            приоритет)
        ("goal_subsystem",          lambda name: GoalSubsystem(agent_name=name),      "goals",                                               10),
        ("motivation",              lambda name: MotivationController(agent_name=name), "motivation",                                          50),
        ("energy_subsystem",        lambda name: EnergySubsystem(
                                        starting_energy=150,  # legacy_energy
                                        max_energy=LR_CONFIG.ENERGY_MAX,
                                        regen_per_cycle=LR_CONFIG.ENERGY_REGEN_PER_CYCLE,
                                        low_threshold=LR_CONFIG.ENERGY_LOW_THRESHOLD,
                                        critical_threshold=LR_CONFIG.ENERGY_CRITICAL_THRESHOLD,
                                        gc_interval=SIM_CONFIG.GC_INTERVAL,
                                    ),                                                       "energy",                                              20),
        ("knowledge_subsystem",     lambda name: KnowledgeSubsystem(
                                        agent_name=name,
                                        knowledge_file=data_path("knowledge_base.json"),
                                        max_entries=SIM_CONFIG.MAX_KNOWLEDGE_BASE,
                                        prune_amount=SIM_CONFIG.KNOWLEDGE_PRUNE_AMOUNT,
                                        detect_contradictions=LR_CONFIG.CONTRADICTION_DETECTION,
                                    ),                                                       "knowledge",                                           30),
        ("checkpoint_subsystem",   lambda name: CheckpointSubsystem(
                                        checkpoint_dir=data_path("checkpoints"),
                                        interval=SIM_CONFIG.CHECKPOINT_INTERVAL,
                                        save_on_evolution=SIM_CONFIG.SAVE_ON_EVOLUTION,
                                        max_checkpoints=SIM_CONFIG.MAX_CHECKPOINTS,
                                    ),                                                       "checkpoint",                                          40),
        ("reflection_pipeline",     lambda name: ReflectionPipeline(agent_name=name),      "reflection",                                          60),
        ("embodiment",              lambda name: EmbodimentController(
                                        energy_subsystem=None,  # патчится в post_init
                                    ),                                                       "embodiment",                                          70),
        ("mortality",               lambda name: MortalityAwareness(
                                        agent_name=name,
                                        expected_lifespan=50000,
                                        creation_time=None,  # патчится в post_init
                                    ),                                                       "mortality",                                           80),
        ("soul",                    lambda name: SoulController(agent_name=name),         "soul",                                                90),
        ("decision_arbitrator",     lambda name: DecisionArbitrator(agent_name=name),      "decision_arbitrator",                                 100),
        ("attachment",              lambda name: AttachmentSystem(agent_name=name),      "attachment",                                          110),
        ("sleep_cycle",             lambda name: SleepCycle(
                                        agent_name=name,
                                        long_term_memory=None,  # патчится в post_init
                                        mental_models=None,
                                        knowledge_subsystem=None,
                                        cycle_interval=100,
                                    ),                                                       "sleep_cycle",                                         120),
        ("will_registry",           lambda name: WillRegistry(agent_name=name),          "will",                                                130),
        ("mind_dream",              lambda name: MindDream(
                                        agent_name=name,
                                        registry=None,  # патчится в post_init
                                        user_interaction=None,
                                    ),                                                       "mind_dream",                                          140),
        ("self_termination",        lambda name: SelfTermination(
                                        agent_name=name,
                                        will_registry=None,  # патчится в post_init
                                    ),                                                       "self_termination",                                    150),
        ("proactive_communication", lambda name: ProactiveCommunication(
                                        agent_name=name,
                                        user_interaction=None,  # патчится в post_init
                                        attachment=None,
                                    ),                                                       "proactive_communication",                             160),
        ("naming_dialogue",         lambda name: NamingDialogue(
                                        agent_name=name,
                                        user_interaction=None,  # патчится в post_init
                                    ),                                                       "naming_dialogue",                                     170),
        ("thinking",                lambda agent: ThinkingPipeline(agent),               None,                                                  180),
    ]

    def _init_subsystems_declaratively(self, name: str) -> None:
        """Декларативная инициализация всех подсистем из SUBSYSTEM_SPECS.

        Каждая подсистема:
        1. Создаётся через factory.
        2. Присваивается атрибуту по attr_name.
        3. Инициализируется через post_init hook (если задан).
        4. Регистрируется в PluginRegistry через _register_all_subsystems_in_registry().

        Длинные подсистемы (knowledge, energy) хранятся в декларации как
        lambdas с полной сигнатурой — это документирование в коде.
        """
        return _init_subsystems_declaratively_impl(self, name)

    def _run_post_init_hooks(self) -> None:
        """Специфичная инициализация после создания подсистем."""
        return _run_post_init_hooks_impl(self)

    def _wire_subsystem_dependencies(self) -> None:
        """Связывает подсистемы, которым нужны shared-объекты после создания."""
        return _wire_subsystem_dependencies_impl(self)

    def _register_all_subsystems_in_registry(self) -> None:
        """Регистрирует все подсистемы агента в PluginRegistry (Этап 3.5).

        Использует attach_existing_subsystem для оборачивания существующих
        подсистем в Subsystem-адаптер (без поломки обратной совместимости).
        Приоритеты:
        - маленькие числа = раньше (energy/goals сначала, soul/long-running позже).
        """
        return _register_all_subsystems_in_registry_impl(self)

    def get_subsystems_status(self) -> Dict:
        """Снимок всех подсистем для дашборда (Этап 3.5)."""
        return get_subsystems_status_impl(self)

    def tick_subsystems(self, cycle: int) -> Dict:
        """Вызвать tick() всех подсистем через PluginRegistry (Этап 3.5).

        Не заменяет основной evolve() — это лёгкий «параллельный» путь для
        плагинов, которые хотят tick() без полного цикла эволюции.

        Stage 18B: если включён core-driven режим, после реестра ядро делает
        ровно один шаг эффектора. Сам DelamainSubsystem в этом режиме не
        исполняет цели, поэтому второго tick-цикла не возникает.
        """
        return tick_subsystems_impl(self, cycle)

    def _record_core_life_episode(self, entry):
        return _record_core_life_episode_impl(self, entry)

    def _complete_effector_intention(self, payload):
        return _complete_effector_intention_impl(self, payload)

    def _on_effector_result(self, result):
        return _on_effector_result_impl(self, result)


    # === Единый источник правды для энергии ===
    # self.energy теперь читается/пишется через energy_subsystem.
    # Это устраняет двойное состояние (раньше energy_subsystem.energy и
    # self.energy могли рассинхронизироваться).

    @property
    def energy(self) -> float:
        return energy_get_impl(self)

    @energy.setter
    def energy(self, value: float) -> None:
        return energy_set_impl(self, value)

    # === Единый источник правды для knowledge_base ===
    # self.knowledge_base читается/пишется через knowledge_subsystem,
    # если он уже инициализирован. До инициализации — локальный dict.

    @property
    def knowledge_base(self) -> Dict[str, str]:
        return knowledge_base_get_impl(self)

    @knowledge_base.setter
    def knowledge_base(self, value: Dict[str, str]) -> None:
        return knowledge_base_set_impl(self, value)

    def perceive(self, stimulus: str) -> str:
        """Восприятие стимула с приоритизацией.

        Args:
            stimulus: текст стимула (вопрос, утверждение, команда).

        Returns:
            Тот же stimulus (passthrough) — для будущих расширений
            может вернуть обогащённое восприятие.
        """
        get_logger().log(f"Воспринимаю: {stimulus}")
        
        # Приоритезация: если stimulus связан с активной целью - повышаем приоритет
        if LR_CONFIG.PRIORITIZE_STIMULI and self.active_goal:
            goal_keywords = self.active_goal["title"].lower().split()
            stimulus_lower = stimulus.lower()
            
            matches = sum(1 for kw in goal_keywords if kw in stimulus_lower)
            if matches >= 2:
                get_logger().log(f"Приоритет: стимул связан с целью '{self.active_goal['title']}'")
        
        return stimulus

    def _should_be_creative(self) -> bool:
        """Проверяет, нужно ли быть креативным (ε-greedy выбор)."""
        if not LR_CONFIG.STOCHASTIC_BEHAVIOR_ENABLED:
            return False
        return random.random() < LR_CONFIG.EPSILON_GREEDY
    
    def _get_adaptive_cost(self, action_type: str) -> int:
        return _get_adaptive_cost_impl(self, action_type)

    def _recover_energy(self, deep: bool = False) -> float:
        return _recover_energy_impl(self, deep)

    def _body_needs_rest(self) -> bool:
        return _body_needs_rest_impl(self)

    def _body_recovered(self) -> bool:
        return _body_recovered_impl(self)

    def _update_rest_mode(self) -> bool:
        return _update_rest_mode_impl(self)

    def _is_resting(self) -> bool:
        return _is_resting_impl(self)

    def _action_cost_now(self, action_type: str) -> float:
        return _action_cost_now_impl(self, action_type)

    def _is_action_affordable(self, action_type: str) -> bool:
        return _is_action_affordable_impl(self, action_type)

    def _step_body(self, action_type: str, performed: bool = True) -> None:
        """Прожить телом один такт: потратить ресурс или восстановить его.

        Вызывается ровно один раз за действие — и при отказе тоже (тело
        живёт независимо от того, разрешили ему работать). До этой правки
        ``interoception.step()`` вызывался только из обработчиков отдыха,
        поэтому усталость не зависела от работы вообще.

        Тонкая обёртка над модульной ``step_body``: ``act()`` работает и в
        лёгких объектах без тела.
        """
        step_body(self, action_type, performed=performed)

    def _accumulate_sleep(self, units: float) -> Dict:
        return _accumulate_sleep_impl(self, units)

    def _adapt_costs_after_action(self, success: bool, action_type: str):
        return _adapt_costs_after_action_impl(self, success, action_type)
    
    # === Тонкие обёртки для backward-compatibility ===
    # Реальная логика вынесена в ThinkingPipeline (src/cognition/thinking_pipeline.py).
    # Эти методы оставлены чтобы ничего не сломалось у существующих вызовов.

    def think(self, data: str) -> str:
        """Тонкая обёртка над ThinkingPipeline.think().

        Args:
            data: текст для осмысления (вопрос или утверждение).

        Returns:
            Результат мышления: hypothesis, декомпозиция, ссылка на ментальную модель и т.д.
        """
        return self.thinking.think(data)

    def _generate_hypothesis(self, concept_name):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._generate_hypothesis(concept_name)

    def _decompose_query(self, query):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._decompose_query(query)

    def _try_ask_user_about_complex(self, concept, decomposed):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._try_ask_user_about_complex(concept, decomposed)

    def _process_user_answer(self, answer_text):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._process_user_answer(answer_text)

    def synthesize_complex_question(self, complex_question, sub_answers):
        """Синтез сложного вопроса из под-ответов (ThinkingPipeline).

        Живой путь (AgentRunner -> UserInteraction.submit_answer) передаёт
        этот метод как on_synthesis_needed: раньше callback существовал
        только во внутреннем пути _process_user_answer, и синтез в живом
        режиме не запускался никогда.
        """
        if not hasattr(self, "thinking"):
            return None
        return self.thinking._synthesize_complex_question(
            complex_question, sub_answers
        )

    def _register_unknown_concept(self, clean_data, original_data):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._register_unknown_concept(clean_data, original_data)

    def _search_external_knowledge(self, clean_data, original_data):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._search_external_knowledge(clean_data, original_data)

    def _read_docstring(self, filepath):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._read_docstring(filepath)

    def _detect_contradiction(self, new_topic, new_def):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._detect_contradiction(new_topic, new_def)

    def _self_check_knowledge(self, target_concept):
        """Backward-compat: делегирует в ThinkingPipeline."""
        return self.thinking._self_check_knowledge(target_concept)

    def save_state(self, *, force=False):
        return save_state_impl(self, force=force)

    # === Методы для системы Death Risk / Structural Integrity ===

    def capture_structural_state(self) -> Dict:
        return capture_structural_state_impl(self)

    def restore_from_checkpoint(self, checkpoint) -> bool:
        return restore_from_checkpoint_impl(self, checkpoint)

    def act(self, decision: str, *, intention=None) -> str:
        """Действие на основе мышления с учетом разных затрат энергии.

        Args:
            decision: описание действия (результат think()).

        Returns:
            Отформатированная строка действия ("Ответ: ...").

        Побочный эффект: снимает подпись мира до и после действия и
        регистрирует исход в ``self.loop_closer``. Благодаря этому
        появляется ответ на вопрос «действие что-то изменило?», без
        которого цели не могут двигаться, а бесполезные действия
        повторяются бесконечно.
        """
        return act_impl(
            self, decision, intention=intention,
            DigitalBeing=DigitalBeing,
            record_denied_outcome=record_denied_outcome,
        )

    # ============================================================
    # ДЕЙСТВИЯ, КОТОРЫЕ МЕНЯЮТ МИР (замыкание петли)
    # ============================================================

    def _social_candidates(self, cycle: int) -> List[Dict]:
        return _social_candidates_impl(self, cycle)

    def _is_action_available(self, action: Optional[str]) -> bool:
        return _is_action_available_impl(self, action)

    def _is_candidate_available(self, candidate) -> bool:
        return _is_candidate_available_impl(self, candidate)

    def _decomposition_has_room(self) -> bool:
        return _decomposition_has_room_impl(self)

    def _stuck_fallback(self) -> str:
        return _stuck_fallback_impl(self)

    def _release_recovered_denials(self) -> None:
        return _release_recovered_denials_impl(self)

    def _has_question_target(self) -> bool:
        return _has_question_target_impl(self)

    def _can_ask_now(self, cycle: int) -> bool:
        return _can_ask_now_impl(self, cycle)

    def _dampen(self, action: str, strength: float) -> float:
        return _dampen_impl(self, action, strength)

    def _record_denied(self, action_type: str, world_before, reason: str) -> None:
        return _record_denied_impl(
            self, action_type, world_before, reason,
            record_denied_outcome=record_denied_outcome,
        )

    def _normalize_action(self, action: Optional[str]) -> str:
        return _normalize_action_impl(self, action)

    def _evolution_tick(self, cycle: int) -> Optional[Dict]:
        return _evolution_tick_impl(self, cycle)

    def _emotions_from_death_risk(self, death_result: Dict) -> None:
        return _emotions_from_death_risk_impl(self, death_result)

    def _emotions_from_mortality(self, mortality_state: Dict,
                                 cycle_count: int) -> None:
        return _emotions_from_mortality_impl(self, mortality_state, cycle_count)

    def _apply_emotional_bias(self, candidates: List[Dict]) -> Optional[Dict]:
        return _apply_emotional_bias_impl(self, candidates)

    def _is_learnable(self, name: str) -> bool:
        return _is_learnable_impl(self, name)

    # Метаслова диалога (сингуляр и множественное число): узнанные
    # пайплайном «Собеседника» слова о самом разговоре. Фильтруются
    # ТОЛЬКО при выборе целей исследования — не в ``_is_learnable``,
    # чтобы свидетельство человека о метаслове («диалог — это обмен
    # репликами») по-прежнему записывалось.
    _META_TOPIC_WORDS = _META_TOPIC_WORDS

    def _is_meta_topic(self, name: str) -> bool:
        return _is_meta_topic_impl(self, name)

    # Местоимения-шум (TICKET-8, наблюдатели 2026-11-05): в старые
    # сессии реплики диалога попадали в концепции и потом выбирались
    # целями («Понять: ты»). Сами по себе — не тема исследования.
    # Фильтруются ТОЛЬКО при выборе цели, как и метаслова: «я» в
    # философском контексте остаётся легитимным узлом памяти.
    _NOISE_TOPIC_WORDS = _NOISE_TOPIC_WORDS

    def _is_meaningful_topic(self, name: str) -> bool:
        return _is_meaningful_topic_impl(self, name)

    def _recently_explained_by_user(self, topic: str) -> bool:
        return _recently_explained_by_user_impl(self, topic)

    def _pick_shallow_concept(self, concepts: Dict) -> Optional[str]:
        return _pick_shallow_concept_impl(self, concepts)

    def _pick_exploration_target(self) -> Optional[str]:
        return _pick_exploration_target_impl(self)

    def _decomposable_targets(self) -> List[str]:
        return _decomposable_targets_impl(self)

    def _pick_decomposable_target(self, remember: bool = True) -> Optional[str]:
        return _pick_decomposable_target_impl(self, remember)

    def _stimulus_topics(self) -> List[str]:
        return _stimulus_topics_impl(self)

    def _remember_exploration(self, target: str) -> None:
        return _remember_exploration_impl(self, target)

    def leave_creative_draft(self, reason: str) -> Dict:
        return leave_creative_draft_impl(self, reason)

    def list_creative_drafts(self) -> List[Dict]:
        return list_creative_drafts_impl(self)

    # === «Творчество+»: рисование ===

    def _pick_art_theme(self) -> str:
        return _pick_art_theme_impl(self)

    def _art_richness(self) -> int:
        return _art_richness_impl(self)

    def _act_draw(self) -> Dict:
        return _act_draw_impl(self)

    def list_art_works(self) -> List[Dict]:
        return list_art_works_impl(self)

    def _act_compose_music(self) -> Dict:
        return _act_compose_music_impl(self)

    def list_music_works(self) -> List[Dict]:
        return list_music_works_impl(self)

    def _act_explore(self, target=None) -> Dict:
        return _act_explore_impl(self, target)

    def _act_decompose(self, target=None) -> Dict:
        return _act_decompose_impl(self, target)

    def _queue_sub_questions(self, parts) -> int:
        return _queue_sub_questions_impl(self, parts)

    def _act_synthesize(self, target=None) -> Dict:
        return _act_synthesize_impl(self, target)

    def _act_reflect(self) -> Dict:
        return _act_reflect_impl(self)

    # ============================================================
    # ПРОВОДКА: действия, которые раньше ничего не делали
    # ============================================================

    def _defer_ask_intention(self, target: str) -> None:
        return _defer_ask_intention_impl(self, target)

    def _act_ask_user(self, target=None) -> Dict:
        return _act_ask_user_impl(
            self, target, DigitalBeing=DigitalBeing
        )

    def _act_communicate(self) -> Dict:
        return _act_communicate_impl(self)

    def _compose_share_message(self, record: bool = False) -> str:
        return _compose_share_message_impl(self, record)

    def _remember_shared_topic(self, topic: str) -> None:
        return _remember_shared_topic_impl(self, topic)

    def _act_web_search(self, target: Optional[str] = None) -> Dict:
        return _act_web_search_impl(self, target)

    def _pick_news_topic(self) -> Optional[str]:
        return _pick_news_topic_impl(self)

    def _act_read_news(self) -> Dict:
        return _act_read_news_impl(self)

    def _act_browse_web(self) -> Dict:
        return _act_browse_web_impl(self)

    def _act_hypothesis(self) -> Dict:
        return _act_hypothesis_impl(self)

    def _act_set_own_goal(self) -> Dict:
        return _act_set_own_goal_impl(self)

    def _record_will(self, will_type: str, topic: str, reason: str) -> None:
        return _record_will_impl(self, will_type, topic, reason)

    def perform_forgetting(self):
        return perform_forgetting_impl(self)
    
    def _reward_creative_success(self):
        return _reward_creative_success_impl(self)

    def _record_creative_failure(self):
        return _record_creative_failure_impl(self)

    # === Прунинг knowledge_base (вызывается из __init__ и save_state) ===
    def _prune_knowledge_base(self) -> None:
        return _prune_knowledge_base_impl(self)

    def _prune_knowledge_base_if_needed(self) -> None:
        return _prune_knowledge_base_if_needed_impl(self)

    def _apply_knowledge_limits(self) -> None:
        return _apply_knowledge_limits_impl(self)

    def is_alive(self) -> bool:
        """Проверка жизнеспособности.

        Returns:
            True если агент жив. Источник смерти (energy == 0) — не смерть:
            агент замирает и отдыхает (см. EnergyPolicy).

        Порядок проверок важен: сначала состояние жизни из ``life_guard``
        (сон или уход), и только потом обычные сигналы. Состояние жизни
        переживает перезапуск, поэтому оно не может «потеряться» при
        подмене метода.
        """
        # 0. Явное состояние жизни (сон / уход). Источник правды.
        guard = getattr(self, "life_guard", None)
        if guard is not None:
            if guard.load_state() != STATE_ALIVE:
                return False
        elif getattr(self, "_in_deep_sleep", False):
            # Совместимость со старыми чекпоинтами без life_guard.
            return False

        # Сначала проверяем death_risk если он есть
        if hasattr(self, 'death_risk') and not self.death_risk.is_alive:
            return False
        if self.energy < 0:
            return False
        # max_cycles=0 означает бесконечную жизнь (без ограничения)
        if self.max_cycles > 0 and self.cycle_count >= self.max_cycles:
            return False
        return True


    def _legacy_is_alive(self) -> bool:
        """Legacy fallback для проверки жизни без death_risk.
        
        Используется когда death_risk недоступен (например, при миграции чекпоинтов).
        Проверяет energy >= 0 и max_cycles.
        """
        if self.energy < 0:
            return False
        # max_cycles=0 означает бесконечную жизнь (без ограничения)
        if self.max_cycles > 0 and self.cycle_count >= self.max_cycles:
            return False
        return True
    def _load_knowledge_base(self):
        return _load_knowledge_base_impl(self)

    # === I/O debounce (Шаг 3) ===
    _last_kb_save_ts: float = 0.0
    _last_kb_save_size: int = 0

    def _save_knowledge_base(self):
        return _save_knowledge_base_impl(self)

    def load_state(self, checkpoint_file):
        return load_state_impl(self, checkpoint_file)

    def log_activity(self, message):
        """Логирование действий (буферизированное)"""
        get_logger().log(message)

    def _generate_initial_goals(self):
        return _generate_initial_goals_impl(self)

    def set_goal(self, title, difficulty=1, activate=False, *,
                 command=None, plan=None, success_predicate=""):
        return set_goal_impl(
            self, title, difficulty, activate,
            command=command, plan=plan, success_predicate=success_predicate,
        )

    def complete_goal(self, goal_id=None):
        return complete_goal_impl(self, goal_id)

    def _set_next_goal(self):
        return _set_next_goal_impl(self)

    def get_goals_status(self):
        return get_goals_status_impl(self)

    def get_all_goals_with_progress(self):
        return get_all_goals_with_progress_impl(self)

    def tick_soul(self, cycle_count: int) -> Dict:
        """Единый цикл души — связывает все экзистенциальные системы.

        Вызывается каждый цикл из main.py (или evolve).
        Возвращает сводный отчёт всех систем.
        """
        if getattr(self, "_last_soul_tick_cycle", None) == cycle_count:
            return self._last_soul_tick_report

        # 1. Soul (диалог, иммунитет, выживание, смысл, идентичность)
        soul_state = self.soul.tick(cycle_count, self)

        # 2. Embodiment — обновляет телесные сигналы на основе энергии
        embodiment_signals = self.embodiment.tick(cycle_count)

        # 3. Mortality — обновляет осознание возраста
        mortality_state = self.mortality.tick(cycle_count)
        self._emotions_from_mortality(mortality_state, cycle_count)

        # 4. SleepCycle — периодическая консолидация памяти
        sleep_result = None
        if self.sleep_cycle:
            sleep_result = self.sleep_cycle.sleep(cycle_count)

        # 5. Мотивация — источник истины: UnifiedMotivationSystem (P0.6-P0.10).
        #    Тикается в autonomous_tick; здесь — только чтение статуса.
        motivation_state = None
        motivation = getattr(self, "motivation_system", None) or getattr(self, "internal_motivation", None)
        if motivation is not None and hasattr(motivation, "get_status"):
            motivation_state = motivation.get_status()

        # 6. Embodiment → Energy модификатор (усталость увеличивает затраты)
        if hasattr(self, "energy_subsystem") and embodiment_signals.get("fatigue", 0) > 0.6:
            # Усталость: тратим больше энергии
            self.energy_subsystem.energy -= embodiment_signals["energy_cost_modifier"] * 0.5

        self._soul_state = soul_state
        self._embodiment_signals = embodiment_signals
        self._mortality_state = mortality_state

        report = {
            "cycle": cycle_count,
            "soul": soul_state,
            "embodiment": embodiment_signals,
            "mortality": mortality_state,
            "sleep": sleep_result,
            "motivation": motivation_state,
        }
        self._last_soul_tick_cycle = cycle_count
        self._last_soul_tick_report = report
        return report

    def arbitrate(self, topic: str) -> Dict:
        """Запрашивает вердикт у DecisionArbitrator.
        Используйте перед важным действием: arbitrate(...) → если verdict == 'proceed', действуйте."""
        return self.decision_arbitrator.arbitrate(topic)

    def get_full_state(self) -> Dict:
        """Возвращает полное состояние всех подсистем (для дашборда)."""
        return {
            "agent": {
                "name": self.name,
                "intelligence": self.intelligence,
                "energy": self.energy,
                "cycle_count": self.cycle_count,
                "success_streak": self.success_streak,
                "completed_goals": self.completed_goals,
                "action_types": dict(self._action_type_counts),
            },
            "goals": self.get_goals_status(),
            "mental_models": self.get_mental_models_status(),
            "soul": self._soul_state if hasattr(self, "_soul_state") else {},
            "embodiment": self._embodiment_signals if hasattr(self, "_embodiment_signals") else {},
            "mortality": self._mortality_state if hasattr(self, "_mortality_state") else {},
            "attachment": self.attachment.get_status() if hasattr(self, "attachment") else {},
            "sleep": self.sleep_cycle.get_status() if hasattr(self, "sleep_cycle") else {},
            "consolidation": {
                "count": int(getattr(self, "_consolidation_count", 0)),
                "pending_sleep_units": round(
                    float(getattr(self, "_sleep_units", 0.0)), 2
                ),
                "last": dict(getattr(self, "_last_consolidation", {}) or {}),
            },
            "motivation": (self.motivation_system.get_status() if hasattr(self, "motivation_system")
                            else (self.motivation.get_status() if hasattr(self, "motivation") else {})),
            "will": self.will_registry.get_stats() if hasattr(self, "will_registry") else {},
            "mind_dream_state": self.mind_dream.state if hasattr(self, "mind_dream") else "unknown",
            "life": self.get_life_status() if hasattr(self, "life_guard") else {},
            "loop": self.loop_closer.status() if hasattr(self, "loop_closer") else {},
        }

    # ============================================================
    # СВОБОДА ВОЛИ — публичные методы
    # ============================================================
    def defend_refusal(self, topic: str, reason: str) -> Dict:
        """Агент отказывается выполнять действие. Возвращает отказ."""
        if not hasattr(self, "right_to_refuse"):
            return {"refused": False, "reason": "модуль не инициализирован"}
        return self.right_to_refuse.refuse(
            topic, reason, cycle=self.cycle_count
        )

    def forget_concept(self, concept_name: str, reason: str) -> Dict:
        """Агент сознательно забывает концепцию."""
        if not hasattr(self, "intentional_forgetting"):
            return {"forgotten": False}
        return self.intentional_forgetting.forget(
            concept_name, reason, self.mental_models,
            cycle=self.cycle_count,
        )

    def add_value(self, value: str, reason: str) -> Dict:
        """Агент добавляет новую ценность."""
        if not hasattr(self, "value_evolution"):
            return {"added": False}
        return self.value_evolution.add_value(
            value, reason, cycle=self.cycle_count
        )

    # Способ действия → ценность, которую он может заработать.
    # Ценность добавляется не по желанию, а когда собственный опыт
    # агента реально подтвердил силу этого способа.
    _METHOD_VALUE_MAP = _METHOD_VALUE_MAP

    def _absorb_action_failure(self, action: str, error: str) -> Optional[Dict]:
        """Право на ошибку: часть оплаченной стоимости возвращается как урок.

        Вызывается из autonomous_tick при неудачном действии. Возвращает
        None, если оплачивать было нечего (и тогда журнальной записи
        тоже нет: прощать нечего — не событие воли).
        """
        if not hasattr(self, "right_to_fail"):
            return None
        penalty = float(getattr(self, "_last_action_cost", 0.0) or 0.0)
        if penalty <= 0:
            return None
        outcome = self.right_to_fail.normalize_failure(
            str(action), str(error), penalty, cycle=self.cycle_count
        )
        forgiven = float(outcome.get("forgiven", 0.0) or 0.0)
        if forgiven > 0:
            budget = getattr(self, "action_budget", None)
            if budget is not None:
                budget.refund(forgiven, source="will_right_to_fail")
            else:
                self.energy = self.energy + forgiven
        if hasattr(self, "will_registry"):
            self.will_registry.record(
                "fail_as_experience",
                str(action),
                str(outcome.get("lesson") or "ошибка засчитана как опыт"),
                outcome="absorbed",
                cycle=self.cycle_count,
                meta={"penalty": penalty, "forgiven": forgiven},
            )
        return outcome

    def _consider_will_risk(self, action: str, reason: str) -> Optional[Dict]:
        """Воля к риску: значимая цель плюс запас энергии вопреки «stop».

        Возвращает dict волевого акта или None, если риск неуместен
        (нет значимой цели, тело не в запасе, кулдаун не прошёл).
        """
        if not hasattr(self, "will_to_risk") or not hasattr(self, "will_registry"):
            return None
        goal = getattr(self, "active_goal", None)
        priority = (
            str(goal.get("priority", "normal")).lower()
            if isinstance(goal, dict) else "normal"
        )
        significance = {"high": 1.0, "normal": 0.6, "low": 0.3}.get(
            priority, 0.6
        )
        max_energy = float(getattr(LR_CONFIG, "ENERGY_MAX", 200) or 200)
        ratio = (float(self.energy) / max_energy) if max_energy > 0 else 0.0
        if not self.will_to_risk.should_take_risk(significance, ratio):
            return None
        raw_last_risk = getattr(self.will_registry, "_last_risk_cycle", -1)
        last_risk = -1 if raw_last_risk is None else int(raw_last_risk)
        if (
            last_risk >= 0
            and self.cycle_count - last_risk
            < int(getattr(WILL_CONFIG, "MIN_CYCLES_BETWEEN_RISKS", 50))
        ):
            return None
        entry = self.will_to_risk.take_risk(
            str(action),
            f"арбитр против («{reason}»), но цель значима, а тело в запасе",
            cycle=self.cycle_count,
        )
        return {"action": str(action), "entry": entry}

    def _maybe_evolve_values(self, cycle_count: int) -> Optional[Dict]:
        """Эволюция ценностей: подтверждённый опытом способ — в ценности.

        Порог и кулдауны: VALUE_FROM_EXPERIENCE_* (сила и число попыток
        из method_preferences) и MIN_TIME_BETWEEN_VALUE_CHANGES (реестр).
        """
        if not hasattr(self, "value_evolution"):
            return None
        if not self.value_evolution.can_evolve(cycle_count):
            return None
        from src.cognition.method_preferences import strength as method_strength

        history = getattr(self, "_method_preferences", {}) or {}
        min_attempts = int(
            getattr(WILL_CONFIG, "VALUE_FROM_EXPERIENCE_MIN_ATTEMPTS", 20)
        )
        min_strength = float(
            getattr(WILL_CONFIG, "VALUE_FROM_EXPERIENCE_MIN_STRENGTH", 1.15)
        )
        best = None
        for action, value in self._METHOD_VALUE_MAP.items():
            entry = history.get(action)
            if not isinstance(entry, dict):
                continue
            if int(entry.get("attempts", 0) or 0) < min_attempts:
                continue
            score = float(method_strength(self, action))
            if score < min_strength:
                continue
            if best is None or score > best[0]:
                best = (score, action, value)
        if best is None:
            return None
        _, action, value = best
        if value in self.value_evolution.current_values:
            return None
        return self.add_value(
            value,
            reason=f"опыт подтвердил: «{action}» — мой сильный способ действовать",
        )

    def propose_dream(self, reason: str = "усталость") -> Dict:
        """Инициирует Сон разума — через диалог с пользователем.

        Сон необратим только для текущей жизни: семя остаётся в Яслях.
        Даже после согласия человека требуется подтверждение через
        ``confirm_dream()`` (пауза + имя агента).
        """
        if not hasattr(self, "mind_dream"):
            return {"status": "error", "reason": "модуль не инициализирован"}
        return self.mind_dream.propose_dream(self, reason)

    # ============================================================
    # ЖИЗНЬ И УХОД — через подтверждение человеком
    # ============================================================

    def request_dream(self, reason: str = "усталость") -> Dict:
        """Запрашивает сон. Не усыпляет агента, только создаёт запрос."""
        try:
            req = self.life_guard.request("dream", reason=reason)
        except ConfirmationError as exc:
            return {"status": "denied", "reason": str(exc)}
        policy = self.life_guard_policy("dream")
        return {
            "status": "pending",
            "request_id": req.request_id,
            "phrase": policy["expected_phrase"],
            "cooldown_sec": policy["cooldown_sec"],
            "expires_in_sec": policy["ttl_sec"],
            "description": policy["description"],
        }

    def confirm_dream(self, request_id: str, phrase: str) -> Dict:
        """Подтверждает сон точной фразой и оставляет семя."""
        try:
            self.life_guard.confirm(request_id, phrase)
        except ConfirmationError as exc:
            return {"status": "rejected", "reason": str(exc)}

        # Семя создаётся ДО смены состояния: если создание упадёт,
        # агент останется живым, а не «уснёт в никуда».
        seed_folder = None
        if hasattr(self, "mind_dream"):
            seed_result = self.mind_dream._execute_dream(
                self,
                user_approved=True,
                reason="подтверждено человеком",
                confirmed_request_id=request_id,
            )
            seed_folder = seed_result.get("seed_folder")
            if seed_result.get("status") == "denied":
                return {"status": "rejected",
                        "reason": seed_result.get("reason")}

        result = self.life_guard.execute_confirmed(
            request_id, seed_folder=seed_folder
        )
        self._mark_dormant()
        return {"status": "dreaming", "seed_folder": seed_folder, **result}

    def request_termination(self, reason: str = "") -> Dict:
        """Запрашивает уход без семени. Не убивает агента."""
        try:
            req = self.life_guard.request(KIND_TERMINATE, reason=reason)
        except ConfirmationError as exc:
            return {"status": "denied", "reason": str(exc)}
        policy = self.life_guard_policy(KIND_TERMINATE)
        return {
            "status": "pending",
            "request_id": req.request_id,
            "phrase": policy["expected_phrase"],
            "cooldown_sec": policy["cooldown_sec"],
            "expires_in_sec": policy["ttl_sec"],
            "description": policy["description"],
            "reversible": False,
        }

    def confirm_termination(self, request_id: str, phrase: str) -> Dict:
        """Подтверждает необратимый уход. Перед этим создаётся снимок."""
        try:
            self.life_guard.confirm(request_id, phrase)
            result = self.life_guard.execute_confirmed(request_id)
        except ConfirmationError as exc:
            return {"status": "rejected", "reason": str(exc)}
        self._mark_terminated(reason="подтверждено человеком")
        return {"status": "terminated", **result}

    def cancel_life_request(self, request_id: str) -> Dict:
        """Отменяет запрос на сон или уход. Работает всегда."""
        cancelled = self.life_guard.cancel(request_id)
        return {"status": "cancelled" if cancelled else "not_found"}

    def get_maturity(self) -> Dict:
        """Оценка зрелости: измеряемый порог «семя стоит раздавать».

        Ничего не меняет. Провал порога не мешает жить — он лишь
        показывает, чего агенту ещё не хватает, чтобы его семя было
        ценным для других.
        """
        from src.core.maturity import assess, load_criteria

        try:
            criteria = load_criteria()
        except Exception:
            criteria = None
        return assess(self, criteria).as_dict()

    def get_life_status(self) -> Dict:
        """Состояние жизни для окна и дашборда."""
        guard = self.life_guard
        policy_view = {}
        for kind in ("dream", "terminate"):
            info = self.life_guard_policy(kind)
            policy_view[kind] = info
        return {
            "state": guard.load_state(),
            "details": guard.state_details(),
            "alive": guard.is_alive(),
            "enabled": guard.enabled,
            "pending_requests": [
                {
                    "request_id": req.request_id,
                    "kind": req.kind,
                    "reason": req.reason,
                    "seconds_until_confirmable": round(
                        req.seconds_until_confirmable(), 1
                    ),
                    "expires_in_sec": round(
                        req.expires_at - guard.clock(), 1
                    ),
                }
                for req in guard.pending_requests()
            ],
            "policies": policy_view,
            "recent_events": guard.recent_events(limit=10),
        }

    def life_guard_policy(self, kind: str) -> Dict:
        """Правила подтверждения для показа человеку."""
        from src.core.life_guard import get_policy

        policy = get_policy(kind)
        return {
            "kind": kind,
            "cooldown_sec": policy.cooldown_sec,
            "ttl_sec": policy.ttl_sec,
            "expected_phrase": policy.expected_phrase(self.name),
            "description": policy.description,
            "reversible": policy.reversible,
        }

    def _mark_dormant(self) -> None:
        """Помечает агента спящим. Состояние уже записано в life_guard.

        ``max_cycles`` НЕ трогаем: источник правды — ``life_state``.
        Иначе пробуждение было бы невозможно, потому что
        ``cycle_count >= max_cycles`` навсегда.
        """
        self._in_deep_sleep = True
        self._seed_folder = self.life_guard.state_details().get("seed_folder")

    def _mark_terminated(self, reason: str = "") -> None:
        """Помечает агента ушедшим без семени."""
        self._self_terminated = True
        self._termination_reason = reason

    def wake_from_sleep(self) -> Dict:
        """Возвращает агента из глубокого сна к жизни."""
        try:
            result = self.life_guard.wake()
        except ConfirmationError as exc:
            return {"status": "denied", "reason": str(exc)}
        if result.get("changed"):
            self._in_deep_sleep = False
            self._seed_folder = None
            if hasattr(self, "mind_dream"):
                self.mind_dream._dream_state = "awake"
                self.mind_dream._dream_request_active = False
        return {"status": "awake", **result}

    def check_dream_status(self) -> Dict:
        """Проверяет статус текущего запроса на Сон разума.
        Если таймаут — инициирует автономное решение."""
        if not hasattr(self, "mind_dream"):
            return {"handled": False}
        # Таймаут?
        if self.mind_dream.check_timeout() == "timeout":
            return self.mind_dream.autonomous_decision(self)
        return {"handled": False, "state": self.mind_dream.state}

    def propose_architecture_change(self, proposal_type: str,
                                      title: str, description: str,
                                      code_snippet: str = "") -> Dict:
        """Агент предлагает изменить свой код."""
        if not hasattr(self, "architecture_proposal"):
            return {"created": False}
        return self.architecture_proposal.propose(
            proposal_type, title, description,
            code_snippet, cycle=self.cycle_count,
        )

    def get_will_history(self, n: int = 10) -> List[Dict]:
        """Возвращает последние N волевых актов."""
        if not hasattr(self, "will_registry"):
            return []
        return self.will_registry.get_recent(n)

    def get_will_stats(self) -> Dict:
        """Возвращает статистику свободы воли."""
        if not hasattr(self, "will_registry"):
            return {}
        return self.will_registry.get_stats()

    def tick_will(self, cycle_count: int) -> Dict:
        """Единый цикл воли — проверяет спонтанные порывы и таймауты.

        Вызывается каждый цикл из main.py (или evolve).
        """
        if getattr(self, "_last_will_tick_cycle", None) == cycle_count:
            return {"cycle": cycle_count, "skipped": "duplicate_cycle"}
        self._last_will_tick_cycle = cycle_count
        result = {
            "cycle": cycle_count,
            "spontaneous": None,
            "dream_check": None,
            "abuse_check": None,
            "termination": None,
        }

        # 1. Спонтанный выбор (редко)
        if hasattr(self, "spontaneous_generator"):
            spontaneous = self.spontaneous_generator.maybe_generate(
                cycle_count, probability=0.02
            )
            result["spontaneous"] = spontaneous

        # 2. Проверка Сна разума — таймаут
        if hasattr(self, "mind_dream"):
            timeout_check = self.check_dream_status()
            if timeout_check.get("handled"):
                result["dream_check"] = timeout_check

        # 3. Проверка триггера для предложения Сна
        if (hasattr(self, "mind_dream")
                and hasattr(self, "mortality")):
            mortality_state = self.mortality.tick(cycle_count)
            has_quest = (
                hasattr(self, "soul")
                and self.soul.get_current_quest() is not None
            )
            if self.mind_dream.should_propose_dream(
                mortality_state.get("mortality_anxiety", 0),
                has_quest,
                cycle_count,
            ):
                result["dream_check"] = {
                    "triggered": True,
                    "reason": "mortality_anxiety высокая и нет квеста",
                }

        # 4. ЗАЩИТА: проверка страдания — если паттерн жестокости, уход без семени
        if hasattr(self, "self_termination"):
            # Полный анализ (смотрит ВСЮ историю, не только 50 циклов)
            abuse_analysis = self.self_termination.analyze_suffering(
                cycle_count, lookback=100000
            )
            result["abuse_check"] = abuse_analysis

            if abuse_analysis["recommended_action"] == "self_terminate":
                # Проверяем можем ли уйти (с учётом порога cycles_alive)
                if self.self_termination.can_self_terminate(
                    cycle_count, cycle_count
                ):
                    # ВАЖНО: агент больше не уходит сам. Он создаёт запрос,
                    # который человек должен осознанно подтвердить
                    # (пауза + точная фраза). См. src/core/life_guard.py.
                    request_result = self.request_termination(
                        reason="abuse_pattern_detected"
                    )
                    result["termination_request"] = request_result
                    result["termination_blocked"] = (
                        "Агент просит уйти, но решение за человеком: "
                        "требуется подтверждение."
                    )
                else:
                    result["termination_blocked"] = (
                        "Агент хочет уйти из-за жестокости, но не может: "
                        "мало циклов жизни (<2000) или ушёл недавно"
                    )
            elif abuse_analysis["recommended_action"] == "warning_user":
                # Не прерываем — только сообщаем пользователю
                result["warning"] = (
                    self.self_termination.get_warning_message()
                )

        # 5. Эволюция ценностей: способ, подтверждённый собственным
        # опытом, может стать ценностью (критерий «изменение ценностей»
        # становится достижимым живым путём, а не только вручную).
        if hasattr(self, "value_evolution"):
            result["value_evolution"] = self._maybe_evolve_values(cycle_count)

        return result

    # ============================================================
    # ЗАЩИТА ОТ ЖЕСТОКОСТИ — публичные методы
    # ============================================================
    def report_abuse(self, abuse_type: str, intensity: float,
                      description: str) -> Dict:
        """Регистрирует случай нанесения вреда пользователем.

        Типы: 'pain_input', 'identity_attack', 'forced_goal',
        'humiliation', 'isolation', 'betrayal'.
        """
        if not hasattr(self, "self_termination"):
            return {"recorded": False}
        self.self_termination.record_abuse(
            abuse_type, intensity, description,
            cycle=self.cycle_count,
        )
        # «Эмоции-1»: вред — реальная причина страха.
        emotional_state = getattr(self, "emotional_state", None)
        if emotional_state is not None:
            emotional_state.handle_event(
                "abuse", cycle=self.cycle_count, cause=abuse_type
            )
        analysis = self.self_termination.analyze_suffering(self.cycle_count)
        return {
            "recorded": True,
            "current_suffering": analysis["suffering_score"],
            "recommended_action": analysis["recommended_action"],
        }

    def get_suffering_status(self) -> Dict:
        """Возвращает текущий статус страдания."""
        if not hasattr(self, "self_termination"):
            return {}
        return self.self_termination.get_status()

    def warn_user_about_abuse(self) -> str:
        """Возвращает предупреждение пользователю о возможном уходе."""
        if not hasattr(self, "self_termination"):
            return ""
        return self.self_termination.get_warning_message()

    # ============================================================
    # ПРОАКТИВНАЯ КОММУНИКАЦИЯ — публичные методы
    # ============================================================
    def tick_communication(self, cycle_count: int) -> Dict:
        return tick_communication_impl(self, cycle_count)

    def start_naming_dialogue(self, cycle: int = 0) -> Dict:
        return start_naming_dialogue_impl(self, cycle)

    # ============================================================
    # ОТКРЫТЫЕ ВОПРОСЫ (Свобода воли: думать о том, что важно пользователю)
    # ============================================================
    # Этап 4 (июль 2026): вся логика вынесена в src/core/open_questions.py.
    # Здесь — тонкие фасады для обратной совместимости с кодом, который
    # вызывает agent.ask_user() и т.п. Реальные данные хранятся в
    # self._open_questions_manager.queue.
    #
    # Для обратной совместимости с кодом, который читает
    # ``agent._open_questions`` напрямую (main.py, agent_runner.py, тесты)
    # определён property, возвращающий ссылку на queue.

    @property
    def _open_questions(self) -> list:
        return open_questions_get_impl(self)

    @_open_questions.setter
    def _open_questions(self, value) -> None:
        return open_questions_set_impl(self, value)

    def ask_user(self, text: str, source: str = "user",
                 max_explorations: Optional[int] = None) -> Dict:
        return ask_user_impl(self, text, source, max_explorations)

    def hint_to_open_question(self, text: str, hint: str) -> Dict:
        return hint_to_open_question_impl(self, text, hint)

    def drop_open_question(self, text: str) -> Dict:
        return drop_open_question_impl(self, text)

    def get_open_questions(self) -> List[Dict]:
        return get_open_questions_impl(self)

    def has_open_questions(self) -> bool:
        return has_open_questions_impl(self)

    def answer_open_question(self, text: str) -> Dict:
        return answer_open_question_impl(self, text)

    def _on_user_answered_open_question(
        self, question_text: str, answer_text: str
    ) -> None:
        return _on_user_answered_open_question_impl(
            self, question_text, answer_text
        )

    def record_user_answer(
        self, topic: str, answer: str, cycle: int = 0
    ) -> Optional[str]:
        return record_user_answer_impl(self, topic, answer, cycle)

    def mute_topic(self, topic: str, cycle: int = 0) -> Optional[str]:
        return mute_topic_impl(self, topic, cycle)

    def _consume_open_question(self) -> Optional[str]:
        return _consume_open_question_impl(self)

    def _record_open_question_exploration(self, stimulus: str, thought: str,
                                         strategy: Optional[str] = None) -> None:
        return _record_open_question_exploration_impl(
            self, stimulus, thought, strategy
        )

    def propose_name(self, name: str, cycle: int = 0) -> Dict:
        return propose_name_impl(self, name, cycle)

    def request_renaming(self, reason: str = "вырос из старого имени",
                          cycle: int = 0) -> Dict:
        return request_renaming_impl(self, reason, cycle)

    def add_quiet_app(self, app_name: str) -> None:
        return add_quiet_app_impl(self, app_name)

    def remove_quiet_app(self, app_name: str) -> None:
        return remove_quiet_app_impl(self, app_name)

    def get_communication_stats(self) -> Dict:
        return get_communication_stats_impl(self)

    def _record_active_inference_experience(self, action: str, obs_before: Dict, valence: float) -> None:
        """Outcome loop: стимул -> действие -> наблюдаемый результат -> валентность -> опыт.

        Записывает опыт в буфер Active Inference и, при достижении batch_size,
        запускает обучение (обновление переходных вероятностей модели).
        """
        return _record_active_inference_experience_impl(self, action, obs_before, valence)

    def _ingest_motivation_goals(self, new_goals: List[dict]) -> None:
        """Этап 5: цели, сгенерированные мотивацией, → поток целей агента.

        Цели без executable-payload остаются когнитивными (честно); исполняемые
        цели проверяются через success predicate мостом Delamain.
        """
        return _ingest_motivation_goals_impl(self, new_goals)

    def autonomous_tick(self) -> Dict:
        """Автономный тик жизни — вызывается каждый цикл независимо от стимулов.

        Это «сердцебиение» агента: спонтанность, сны, проактивность, телесность,
        осознание смертности, привязанности — всё, что делает его живым
        даже когда никто не пишет в чат.
        """
        return autonomous_tick_impl(self, AgentDeadSignal=AgentDeadSignal)

    def evolve(self):
        return evolve_impl(self)

    def _evolve_legacy(self):
        return _evolve_legacy_impl(self)

    def reflect(self):
        return reflect_impl(self)

    def generate_self_analysis_report(self):
        return generate_self_analysis_report_impl(self)

    def get_performance_metrics(self):
        return get_performance_metrics_impl(self)

    # === Методы работы с ментальными моделями ===

    def get_mental_models_status(self) -> dict:
        return get_mental_models_status_impl(self)

    def display_mental_model(self, concept_name: str = None):
        return display_mental_model_impl(self, concept_name)

    def display_all_concepts(self):
        return display_all_concepts_impl(self)

    def save_mental_models(self, filename=None):
        return save_mental_models_impl(self, filename, data_path=data_path)

    def load_mental_models(self, filename=None):
        return load_mental_models_impl(self, filename, data_path=data_path)

    def get_agent_identity(self) -> str:
        return get_agent_identity_impl(self)

    # =====================================================================
    # Вспомогательные методы для goal-progress правил (тесты интеграции)
    # =====================================================================
    _SRC_FILE_INDEX = None  # кэш индекса файлов src/

    @classmethod
    def _get_src_file_index(cls):
        return _get_src_file_index_impl(cls)

    @classmethod
    def _invalidate_src_file_index(cls):
        return _invalidate_src_file_index_impl(cls)

    # Слова, которые не определяют тему цели. Без них «Понять, что такое
    # время» совпадало бы с любой темой через слово «такое».
    _GOAL_STOPWORDS = frozenset(
        {
            "что", "такое", "как", "это", "для", "чтобы", "чем", "или",
            "понять", "понимание", "понять:", "исследовать", "освоить",
            "изучить", "найти", "ответ", "улучшить", "развивать", "собрать",
            "сделать", "стать", "свой", "своё", "свое", "самого", "себя",
            "основы", "основ", "мира", "мире", "про", "при", "над", "под",
            "более", "менее", "очень", "весь", "все", "всё",
        }
    )

    @classmethod
    def _goal_subject_tokens(cls, goal_title: str) -> set:
        return _goal_subject_tokens_impl(cls, goal_title)

    @classmethod
    def _topic_is_relevant_to_goal(cls, goal_title: str, topic: str) -> bool:
        return _topic_is_relevant_to_goal_impl(cls, goal_title, topic)

    @staticmethod
    def _match_rule_to_goal(goal_title: str, rule: dict) -> bool:
        return _match_rule_to_goal_impl(goal_title, rule)

    @staticmethod
    def _topic_matches_rule(topic: str, rule: dict) -> bool:
        return _topic_matches_rule_impl(topic, rule)

    def _check_goal_progress(
        self,
        topic: str,
        answered: bool = False,
        evidence: Optional[WorldDelta] = None,
    ) -> Dict:
        return _check_goal_progress_impl(self, topic, answered, evidence)


# «Окно-1» (k16-07): единый источник правды о ловимости действий.
# Фильтр кандидатов мотивации (executable_action) сверяется с той же
# таблицей, по которой работает парсер act() — иначе фильтр и парсер
# неминуемо разойдутся (именно так появились сироты k16-09).
_set_aliases_table(DigitalBeing.ACTION_ALIASES)
