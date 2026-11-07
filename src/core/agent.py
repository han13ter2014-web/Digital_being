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
        # явные «ничего не делать»
        "wait": "wait",
        "none": "wait",
    }

    def __init__(self, name="Lucy", life_id=None, profile_managed=False):
        from src.core.life_identity import new_life_id, validate_life_id

        self.life_id = validate_life_id(life_id) if life_id else new_life_id()
        self.name = name
        # Управляемая приложением жизнь хранит данные по UUID. Прямое
        # использование DigitalBeing в старых инструментах остаётся
        # name-based, чтобы не потерять уже существующие файлы.
        self._profile_managed = bool(profile_managed)
        self.creation_time = datetime.now()
        # Инициализируем энергию ДО создания energy_subsystem.
        # Свойство self.energy читает/пишет через energy_subsystem, поэтому
        # до его создания храним в _legacy_energy.
        self._legacy_energy = 150  # Начинаем с 150 для более комфортного старта

        
        # Старая база знаний (для обратной совместимости).
        # Используем KnowledgeSubsystem.DEFAULT_KNOWLEDGE как единый
        # источник правды, чтобы базовые знания не дублировались и не
        # устаревали в двух местах.
        self.knowledge_base = dict(KnowledgeSubsystem.DEFAULT_KNOWLEDGE)
        
        # Новая система ментальных моделей (автономное понимание)
        self.mental_models = MentalModel(name=name)
        
        # Инициализируем active_goal ДО bootstrap (bootstrap обращается к нему)
        self.preferences = {}
        self.cycle_count = 0
        self.max_cycles = 1000000
        self.success_streak = 0
        self.intelligence = 1
        self.goals = []
        self.completed_goals = 0
        self.active_goal = None
        # Стоимость последнего оплаченного действия (для права на ошибку).
        self._last_action_cost = 0.0
        self.reflection_engine = ReflectionEngine()
        
        # === Загрузка родовых знаний (bootstrap) ===
        # Вызываем ДО загрузки чекпоинта, чтобы врожденные знания были базой
        load_initial_knowledge(self)

        # Отметка рождения: сколько концепций было при рождении.
        # Нужна для оценки зрелости: считать надо то, что агент нажил сам,
        # а не родовые знания. Без этой отметки «нажитое» не отличить от
        # унаследованного, и любой агент выглядел бы зрелым сразу.
        self._birth_concepts = len(self.mental_models.concepts)
        # И сколько из них уже имели собственную формулировку при рождении.
        # Родовые знания приходят готовыми — их нельзя засчитывать как
        # освоенное агентом.
        self._birth_defined = sum(
            1
            for node in self.mental_models.concepts.values()
            if len(str(getattr(node, "definition_hypothesis", "") or "")) > 10
        )
        
        # === Система внутренней мотивации ===
        self.internal_motivation = create_motivation_system(self)

        # Unified Motivation System (Needs + Drives) - НОВАЯ система (P0)
        self.motivation_system = create_unified_motivation_system(self)

        # DecisionArbitrator для выбора действий (P1.1)
        from src.core.subsystems.decision_arbitrator import DecisionArbitrator
        self.decision_arbitrator = DecisionArbitrator(agent_name=name)

        # === Новые системы (Этап 4) ===
        # Интероцептивная модель (иерархия: глюкоза → АТФ → митохондрии → усталость → поведение)
        self.interoception = create_interoceptive_model(self)
        
        # Непрерывное время / Event-Driven (retention/protension buffers)
        self.continuous_time = create_continuous_time_engine(self)
        
        # Мета-обучение гиперпараметров
        self.meta_learner = create_meta_learner(self)
        
        # Социальная клеточка (рекурсивное взаимное моделирование)
        self.social_cell = create_social_cell(self)
        
        # Риск смерти / Structural Integrity (checkpoint corruption = смерть)
        self.death_risk = create_death_risk_engine(self)
        
        # === Active Inference Engine ===
        self.active_inference = create_active_inference_engine(self)
        
        # Инициализация взаимодействия с пользователем
        self.user_interaction = UserInteraction(agent_name=name)
        self._user_cooldown = 0  # cooldown после последнего ответа пользователя
        
        # === Новые системы: прогресс, самопроверка, противоречия ===
        self._goal_progress = {}  # progress по целям {goal_id: percentage}
        self._learned_facts = set()  # Усвоенные факты (для отслеживания дубликатов)
        self._known_definitions = {}  # Известные определения {topic: definition}

        # Распределение реальных типов действий (hypothesis/decomposition/...).
        # Нужно, чтобы «смысл» действий был измерим, а не только строка "Ответ:".
        self._action_type_counts: Dict[str, int] = {}
        
        # === Адаптивные энергетические затраты ===
        self._action_costs = {  # Базовые затраты, которые адаптируются
            "default": 2,
            "hypothesis": 3,
            "decomposition": 4,
            "mental_model": 1,
            "know_answer": 1,
        }
        
        # === Креативность: счетчик успешных/неуспешных креативных действий ===
        self._creative_wins = 0  # Сколько раз креативный выбор привел к успеху
        self._creative_losses = 0
        
        # === История используемых концепций (для забывания) ===
        self._concept_usage_count = {}  # {concept_name: usage_count}

        # === Свобода воли: открытые вопросы (от пользователя или внутренние) ===
        # Агент САМ решает, когда думать над вопросом и когда переключиться.
        # Это противовес «туннельному» режиму рандомных стимулов в main.py.
        # Структура записи:
        #   {
        #       "text": str,            # текст вопроса
        #       "source": str,          # "user" / "self" / "soul" / "exploration"
        #       "started_at": int,      # cycle_count когда вопрос был поставлен
        #       "last_explored_at": int,# cycle_count последнего размышления
        #       "explorations": list,   # [{"cycle": int, "thought": str, "strategy": str}, ...]
        #       "max_explorations": int,# лимит размышлений (по умолчанию 5)
        #       "hint": Optional[str],  # подсказка от пользователя
        #       "answered": bool,       # нашёл ли агент ответ
        #       "answer": Optional[str],# найденный ответ
        #   }
        # === Открытые вопросы (Этап 4: вынесено в src/core/open_questions.py) ===
        # Вся логика очереди, стратегий и round-robin теперь в OpenQuestionsManager.
        # Старые атрибуты (_open_questions, _open_questions_max, _default_max_explorations,
        # _open_questions_strategy) сохранены как property/fallback для обратной
        # совместимости с кодом, который читает их напрямую (main.py, agent_runner.py).
        from src.core.open_questions import OpenQuestionsManager
        self._open_questions_manager = OpenQuestionsManager(
            cycle_provider=lambda: self.cycle_count,
            log_info=lambda msg: get_logger().log(msg),
            max_size=10,
            default_max_explorations=5,
            on_user_answer=self._on_user_answered_open_question,
        )
        # Алиасы (для кода, который использует старые имена).
        self._open_questions_max = self._open_questions_manager.max_size
        self._default_max_explorations = (
            self._open_questions_manager.default_max_explorations
        )
        self._open_questions_strategy = "round_robin"

        # === «Собеседник-2»: убеждения о человеке ===
        # Факты о пользователе (обещания, привычки, последний контакт).
        # Сериализуется в чекпоинт: обещания не забываются после рестарта.
        # Граница субъектности: сюда не пишутся ценности и мотивация.
        from src.core.user_model import UserModel

        self.user_model = UserModel()

        # === «Собеседник-3/5»: свидетельство пользователя — знание ===
        # {тема: cycle_count} — когда тема в последний раз закрыта
        # человеком: он объяснил её или попросил не переспрашивать
        # («уже отвечал»). Штамп не даёт возвращаться к теме; падает
        # в чекпоинт.
        self._user_explained_topics: Dict[str, int] = {}

        # === «Собеседник-4»: память диалога ===
        # {тема: cycle_count} — что уже рассказано человеку. Повтор одного
        # и того же — не общение, а шум; сериализуется в чекпоинт.
        self._shared_topics: Dict[str, int] = {}

        # === «Охота-1»: след неудачной охоты ===
        # {тема: cycle_count} — когда поиск в сети по теме промахнулся.
        # Кулдаун не даёт долбить одну тему каждый цикл. Намеренно НЕ
        # сериализуется: сон стирает след неудачной охоты, после
        # перезапуска существо может попробовать снова.
        self._hunt_misses: Dict[str, int] = {}

        # === «Источники-2»: след чтения новостей ===
        # {тема: cycle_count} — когда тема новостей последний раз
        # проверялась (прочитал или «не нашлось» — одинаково). Как и след
        # охоты, не сериализуется: сон стирает след, после перезапуска
        # ленту можно проверить снова.
        self._news_reads: Dict[str, int] = {}
        # «Интернет-1»: кулдаун прогулок по открытому вебу по теме.
        self._web_browses: Dict[str, int] = {}

        # === «Творчество+»: рисунки и вторая игра ===
        # Каталог рисунков и текущая работа — как у текстовых черновиков;
        # сериализуются в чекпоинт.
        self._art_catalog: Dict[str, Dict] = {}
        self._art_work: Optional[Dict] = None
        # «Музыка-1»: каталог мелодий и текущая работа — как у рисунков.
        self._music_catalog: Dict[str, Dict] = {}
        self._music_work: Optional[Dict] = None
        self._local_guess: Optional[Dict] = None

        # === «Собеседник-7»: саморазвитие диалоговых таблиц ===
        # Нераспознанные реплики копятся; повторные сущность уточняет у
        # человека и учит как маркеры (только social/about_self/request,
        # после статических таблиц). Сериализуется в чекпоинт.
        from src.core.dialogue_learning import DialogueLearning

        self.dialogue_learning = DialogueLearning()

        # === «Эмоции-1»: эмоциональный контур ===
        # Страх/счастье/грусть/покой с реальными причинами и затуханием.
        # Окрашивает жизнь (тон, care, статус), но не выбирает целей и
        # не пишет в ценности. Сериализуется в чекпоинт.
        from src.core.emotional_state import EmotionalState

        self.emotional_state = EmotionalState()

        os.makedirs(data_path('checkpoints'), exist_ok=True)
        os.makedirs(data_path('logs'), exist_ok=True)

        self.knowledge_file = data_path('knowledge_base.json')

        # Для умных чекпоинтов
        self._last_saved_intelligence = 0

        self._load_knowledge_base()

        # === ИНИЦИАЛИЗАЦИЯ ПОДСИСТЕМ (декларативно) ===
        # Вместо 200+ строк ручных присваиваний — один декларативный список.
        # Чтобы добавить/убрать подсистему, меняем только SUBSYSTEM_SPECS.
        # _init_subsystem() сам делает setattr и attach к PluginRegistry.
        self._init_subsystems_declaratively(name)

        # Метаданные (для awakending из семени)
        self.parent_seed: Optional[str] = None
        self.parent_name: Optional[str] = None
        self.parent_dream_time: Optional[str] = None

        # === Этап 2.5: WebSearcher (Wikipedia) ===
        # Создаём ДО ThinkingPipeline, чтобы передать ему ссылку.
        if LR_CONFIG.WEB_SEARCH_ENABLED:
            from src.perception.web_search import WebSearcher
            self.web_searcher = WebSearcher(
                lang=LR_CONFIG.WEB_SEARCH_LANG,
                timeout=LR_CONFIG.WEB_SEARCH_TIMEOUT,
                max_chars=LR_CONFIG.WEB_SEARCH_MAX_CHARS,
                rate_limit_sec=LR_CONFIG.WEB_SEARCH_RATE_LIMIT_SEC,
                user_agent=LR_CONFIG.WEB_SEARCH_USER_AGENT,
                cache_size=LR_CONFIG.WEB_SEARCH_CACHE_SIZE,
                fallback_to_en=LR_CONFIG.WEB_SEARCH_FALLBACK_TO_EN,
            )
        else:
            self.web_searcher = None

        # === МЫШЛЕНИЕ: вынесено в ThinkingPipeline (src/cognition/thinking_pipeline.py) ===
        # DigitalBeing остаётся тонким оркестратором. think() и связанные
        # методы (hypothesis, decompose, search и др.) живут в pipeline.
        # Этап 2.5: передаём web_searcher, чтобы Pipeline мог ходить в Wikipedia.
        self.thinking = ThinkingPipeline(self, web_searcher=self.web_searcher)

        # Применяем лимиты при инициализации
        self._apply_knowledge_limits()

        # Начальный тик Soul + Embodiment + Mortality
        self._soul_state = self.soul.tick(self.cycle_count, self)
        self._embodiment_signals = self.embodiment.tick(self.cycle_count)
        self._mortality_state = self.mortality.tick(self.cycle_count)

        # === Этап 3.5: PluginRegistry — регистрируем все подсистемы ===
        self.plugin_registry = PluginRegistry.get_global()
        self._register_all_subsystems_in_registry()
        # setup() для всех подсистем — после этого enabled=True → tick доступен.
        self.plugin_registry.setup_all({
            "agent_name": self.name,
            "agent": self,
            "registry": self.plugin_registry,
        })

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
        # === Пре-создание: long_term_memory (try/except) ===
        # LongTermMemory может упасть на legacy-импортах, оборачиваем в try.
        try:
            self.long_term_memory = LongTermMemory(
                agent_name=name,
                life_id=self.life_id if self._profile_managed else None,
            )
        except Exception:
            self.long_term_memory = None

        # === Шаг 1: создать все подсистемы через factories ===
        for spec in self.SUBSYSTEM_SPECS:
            attr_name, factory, post_init_key, priority = spec
            try:
                # thinking требует self (агента), остальные — name.
                if attr_name == "thinking":
                    instance = factory(self)
                else:
                    instance = factory(name)
                setattr(self, attr_name, instance)
            except Exception as e:
                # Не критично — пропускаем подсистему, но логируем.
                get_logger().log(f"⚠️ Не удалось создать {attr_name}: {e}")

        # === Шаг 2: post-init hooks ===
        self._run_post_init_hooks()

        # === Шаг 3: dependencies (подсистемы, которые ссылаются друг на друга) ===
        # Заполняем cross-references, которые нельзя было установить в фабрике.
        self._wire_subsystem_dependencies()

        # === Шаг 4: воля — 6 базовых модулей ===
        if hasattr(self, "will_registry"):
            self.right_to_refuse = RightToRefuse(self.will_registry)
            self.intentional_forgetting = IntentionalForgetting(self.will_registry)
            self.value_evolution = ValueEvolution(self.will_registry)
            # Отметка рождения ценностей: «изменение через опыт» считается
            # относительно того, с чем агент родился, а не абсолютно.
            self._birth_values = list(self.value_evolution.current_values)
            self.spontaneous_generator = SpontaneousGenerator(self.will_registry)
            self.will_to_risk = WillToRisk(self.will_registry)
            self.right_to_fail = RightToFail(self.will_registry)
        # ArchitectureProposal — без сложных зависимостей, можно создать здесь.
        if hasattr(self, "will_registry"):
            self.architecture_proposal = ArchitectureProposal(registry=self.will_registry)

    def _run_post_init_hooks(self) -> None:
        """Специфичная инициализация после создания подсистем."""
        # Защита жизни: единая точка решений о сне и уходе. Создаётся
        # ПЕРВОЙ, потому что состояние жизни читают и смысловые
        # подсистемы, и главный цикл.
        self.life_guard = LifeGuard(
            agent_name=self.name, name_provider=lambda: self.name
        )

        # Замыкание петли: учёт наблюдаемых результатов действий.
        # max_no_effect=3: после трёх бесплодных повторов действие
        # считается тупиковым и больше не выбирается.
        self.loop_closer = LoopCloser(
            max_no_effect=int(
                getattr(LR_CONFIG, "LOOP_MAX_NO_EFFECT", 3)
            )
        )
        self._last_action_outcome = None
        # Тело: цикл последнего такта и режим отдыха (гистерезис).
        self._rest_mode = False
        # Сон: накопленный «материал» для консолидации.
        self._sleep_units = 0.0
        self._consolidation_count = 0
        self._last_consolidation: Dict = {}

        # GoalSubsystem: генерируем цели и связываем с мотивацией.
        if hasattr(self, "goal_subsystem"):
            self.goals = self.goal_subsystem.generate_initial_goals(agent=self)
            self.active_goal = self.goal_subsystem.active_goal
            self.completed_goals = self.goal_subsystem.completed_goals
            self._goal_progress = self.goal_subsystem._goal_progress
        if hasattr(self, "motivation"):
            self.motivation.attach_goal_subsystem(self.goal_subsystem)

        # EnergySubsystem: применяем epsilon_greedy из конфига.
        if hasattr(self, "energy_subsystem"):
            self.energy_subsystem.epsilon_greedy = LR_CONFIG.EPSILON_GREEDY

        # Stage 19: одна бюджетная политика поверх существующей энергии.
        # Это не второй запас энергии: getter/setter читают и пишут тот же
        # ``self.energy`` (energy_subsystem). При выключенном флаге поведение
        # остаётся прежним, включая отсутствие резерва и лимита стоимости.
        self.action_budget = None
        if hasattr(self, "energy_subsystem"):
            self.action_budget = ActionBudget(
                get_energy=lambda: self.energy,
                set_energy=lambda value: setattr(self, "energy", value),
                max_energy=float(
                    getattr(LR_CONFIG, "ENERGY_MAX", 200.0)
                ),
                enabled=bool(
                    getattr(LR_CONFIG, "ACTION_BUDGET_ENABLED", False)
                ),
                min_reserve=float(
                    getattr(LR_CONFIG, "ACTION_BUDGET_MIN_RESERVE", 5.0)
                ),
                max_action_cost=float(
                    getattr(LR_CONFIG, "ACTION_BUDGET_MAX_ACTION_COST", 20.0)
                ),
            )

        # KnowledgeSubsystem: синхронизируем со старой knowledge_base.
        if hasattr(self, "knowledge_subsystem"):
            self.knowledge_subsystem.knowledge_base = dict(self.knowledge_base)
            self.knowledge_subsystem._known_definitions = dict(self._known_definitions)
            self.knowledge_subsystem.apply_limit()
            # Обратная совместимость — пишем обратно.
            self.knowledge_base = self.knowledge_subsystem.knowledge_base
            self._known_definitions = self.knowledge_subsystem._known_definitions

        # CheckpointSubsystem: инициализируем _last_saved_intelligence.
        if hasattr(self, "checkpoint_subsystem"):
            self._last_saved_intelligence = self.checkpoint_subsystem._last_saved_intelligence

        # ReflectionPipeline: alias для обратной совместимости.
        if hasattr(self, "reflection_pipeline"):
            self.reflection_engine = self.reflection_pipeline.engine

        # EmbodimentController: привязываем energy_subsystem.
        if hasattr(self, "embodiment") and hasattr(self, "energy_subsystem"):
            self.embodiment.energy_subsystem = self.energy_subsystem

        # MortalityAwareness: привязываем creation_time.
        if hasattr(self, "mortality"):
            self.mortality.creation_time = self.creation_time

        # SleepCycle: привязываем зависимости.
        if hasattr(self, "sleep_cycle"):
            self.sleep_cycle.long_term_memory = self.long_term_memory
            self.sleep_cycle.mental_models = self.mental_models
            self.sleep_cycle.knowledge_subsystem = self.knowledge_subsystem

        # MindDream: привязываем зависимости.
        if hasattr(self, "mind_dream"):
            self.mind_dream.registry = self.will_registry
            self.mind_dream.user_interaction = self.user_interaction
            self.mind_dream.life_guard = self.life_guard

        # SelfTermination: привязываем will_registry.
        if hasattr(self, "self_termination"):
            self.self_termination.will_registry = self.will_registry
            # Автоматический уход без семени запрещён политикой: агент
            # может лишь запросить подтверждение у человека.
            self.self_termination.life_guard = self.life_guard

        # ProactiveCommunication: привязываем зависимости.
        if hasattr(self, "proactive_communication"):
            self.proactive_communication.user_interaction = self.user_interaction
            self.proactive_communication.attachment = self.attachment

        # NamingDialogue: привязываем user_interaction.
        if hasattr(self, "naming_dialogue"):
            self.naming_dialogue.user_interaction = self.user_interaction

        # DecisionArbitrator: привязываем soul-системы.
        if hasattr(self, "decision_arbitrator") and hasattr(self, "soul"):
            if self.soul.is_available("self"):
                self.decision_arbitrator.attach_identity(self.soul.get("self"))
            if self.soul.is_available("immune"):
                self.decision_arbitrator.attach_immune_system(self.soul.get("immune"))
            if self.soul.is_available("survival"):
                self.decision_arbitrator.attach_survival_instincts(self.soul.get("survival"))
            if self.soul.is_available("meaning"):
                self.decision_arbitrator.attach_meaning_finder(self.soul.get("meaning"))

    def _wire_subsystem_dependencies(self) -> None:
        """Связывает подсистемы, которым нужны shared-объекты после создания."""
        # quiet_hours — alias для обратной совместимости.
        if hasattr(self, "user_interaction"):
            self.user_quiet_hours = self.user_interaction.user_quiet_hours

    def _register_all_subsystems_in_registry(self) -> None:
        """Регистрирует все подсистемы агента в PluginRegistry (Этап 3.5).

        Использует attach_existing_subsystem для оборачивания существующих
        подсистем в Subsystem-адаптер (без поломки обратной совместимости).
        Приоритеты:
        - маленькие числа = раньше (energy/goals сначала, soul/long-running позже).
        """
        # Низкие приоритеты — базовая инфраструктура
        attach_existing_subsystem(self, "goal_subsystem", priority=10)
        attach_existing_subsystem(self, "energy_subsystem", priority=20)
        attach_existing_subsystem(self, "knowledge_subsystem", priority=30)
        attach_existing_subsystem(self, "checkpoint_subsystem", priority=40)
        attach_existing_subsystem(self, "motivation", priority=50)
        attach_existing_subsystem(self, "reflection_pipeline", priority=60)
        # Средние приоритеты — душа
        attach_existing_subsystem(self, "embodiment", priority=70)
        attach_existing_subsystem(self, "mortality", priority=80)
        attach_existing_subsystem(self, "soul", priority=90)
        attach_existing_subsystem(self, "decision_arbitrator", priority=100)
        attach_existing_subsystem(self, "attachment", priority=110)
        attach_existing_subsystem(self, "sleep_cycle", priority=120)
        # Высокие приоритеты — свобода воли и коммуникация
        attach_existing_subsystem(self, "will_registry", priority=130)
        attach_existing_subsystem(self, "mind_dream", priority=140)
        attach_existing_subsystem(self, "self_termination", priority=150)
        attach_existing_subsystem(self, "proactive_communication", priority=160)
        attach_existing_subsystem(self, "naming_dialogue", priority=170)
        attach_existing_subsystem(self, "thinking", priority=180)
        # LongTermMemory регистрируем отдельно — может быть None (legacy fallback)
        if getattr(self, "long_term_memory", None) is not None:
            attach_existing_subsystem(self, "long_term_memory", priority=190)
        # === Внешние подсистемы (Этап 3.5: расширяемость через плагины) ===
        # Подключаем NurseryWatcher (Этап 3.3) — он сам зарегистрирует себя,
        # но если уже зарегистрирован через plugin-файл, повторная регистрация
        # вернёт False без ошибки.
        try:
            from src.core.subsystems.nursery_watcher import NurseryWatcher
            existing = self.plugin_registry.get("nursery_watcher")
            if existing is None:
                watcher = NurseryWatcher(agent_name=self.name, nursery_dir=data_path("nursery"))
                self.plugin_registry.register(watcher)
            # Подключаем агента для контекста
            w = self.plugin_registry.get("nursery_watcher")
            if w is not None and not getattr(w, "_agent_attached", False):
                w.attach_agent(self)
        except Exception as exc:
            # Если модуль ещё не импортирован / нет атрибута — не критично,
            # но ошибку полезно видеть в логе.
            get_logger().log(f"[{self.name}] NurseryWatcher не подключён: {exc}")
        # Health Dashboard (Этап 2: уже был) — теперь как плагин
        try:
            from src.core.health_dashboard import HealthDashboardSubsystem
            existing = self.plugin_registry.get("health_dashboard")
            if existing is None:
                self.plugin_registry.register(HealthDashboardSubsystem(agent_name=self.name))
        except Exception as exc:
            get_logger().log(f"[{self.name}] HealthDashboard не подключён: {exc}")
        # Delamain-local (этап 8): нативная Subsystem, выключена по умолчанию.
        # Регистрируем напрямую, без LegacySubsystemAdapter: у неё собственный
        # tick() и ленивый runtime.
        try:
            from src.delamain.subsystem import DelamainSubsystem

            existing = self.plugin_registry.get("delamain")
            if existing is None:
                self.delamain = DelamainSubsystem(agent_name=self.name)
                self.plugin_registry.register(self.delamain)
            else:
                self.delamain = existing
            # Stage 18A: expose the core-owned effector boundary. The adapter
            # is disabled by default and does not change the live agent loop.
            self.delamain_effector = getattr(self.delamain, "effector", None)
            # Stage 18B: in integrated mode the core invokes step() once per
            # cycle. Without the flag the old subsystem tick remains the sole
            # driver, so no default behavior changes.
            self.effector_driver = None
            if (
                self.delamain_effector is not None
                and getattr(self.delamain_effector, "core_driven", False)
            ):
                self.effector_driver = EffectorDriver(
                    self.delamain_effector,
                    enabled=True,
                )
        except Exception as exc:
            self.delamain = None
            self.delamain_effector = None
            self.effector_driver = None
            get_logger().log(f"[{self.name}] Delamain-local не подключён: {exc}")

    def get_subsystems_status(self) -> Dict:
        """Снимок всех подсистем для дашборда (Этап 3.5)."""
        status = self.plugin_registry.status_all()
        driver = getattr(self, "effector_driver", None)
        if driver is not None:
            status["effector_driver"] = driver.status()
        budget = getattr(self, "action_budget", None)
        if budget is not None:
            status["action_budget"] = budget.status()
        return status

    def tick_subsystems(self, cycle: int) -> Dict:
        """Вызвать tick() всех подсистем через PluginRegistry (Этап 3.5).

        Не заменяет основной evolve() — это лёгкий «параллельный» путь для
        плагинов, которые хотят tick() без полного цикла эволюции.

        Stage 18B: если включён core-driven режим, после реестра ядро делает
        ровно один шаг эффектора. Сам DelamainSubsystem в этом режиме не
        исполняет цели, поэтому второго tick-цикла не возникает.
        """
        report = self.plugin_registry.tick_all(cycle, {"agent": self})
        driver = getattr(self, "effector_driver", None)
        if driver is not None:
            report["effector"] = driver.tick(cycle)
            self._on_effector_result(report.get("effector"))
        return report

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
        if hasattr(self, "energy_subsystem") and self.energy_subsystem is not None:
            return self.energy_subsystem.energy
        return getattr(self, "_legacy_energy", 0)

    @energy.setter
    def energy(self, value: float) -> None:
        if hasattr(self, "energy_subsystem") and self.energy_subsystem is not None:
            self.energy_subsystem.energy = value
        else:
            self._legacy_energy = value

    # === Единый источник правды для knowledge_base ===
    # self.knowledge_base читается/пишется через knowledge_subsystem,
    # если он уже инициализирован. До инициализации — локальный dict.

    @property
    def knowledge_base(self) -> Dict[str, str]:
        if hasattr(self, "knowledge_subsystem") and self.knowledge_subsystem is not None:
            return self.knowledge_subsystem.knowledge_base
        return getattr(self, "_legacy_knowledge_base", {})

    @knowledge_base.setter
    def knowledge_base(self, value: Dict[str, str]) -> None:
        if hasattr(self, "knowledge_subsystem") and self.knowledge_subsystem is not None:
            self.knowledge_subsystem.knowledge_base = value
        else:
            self._legacy_knowledge_base = value

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
        from src.cognition.intention_payload import intention_target

        selected_target = intention_target(intention)
        creative_choice = None
        if DigitalBeing.ACTION_ALIASES.get(str(decision).strip().lower()) == "create_draft":
            from src.cognition.creative_catalog import creative_request

            creative_choice = creative_request(intention)
        world_before = capture(self)
        action = f"Ответ: {decision}"
        topic = ""

        # === Определяем тип действия и его стоимость ===
        decision_str = str(decision).lower()
        
        if "гипотеза" in decision_str:
            action_type = "hypothesis"
        elif "декомпозиц" in decision_str:
            action_type = "decomposition"
        elif ("ментальная модель" in decision_str
              or "знаю ответ" in decision_str
              or "нашел ответ" in decision_str
              or "нашёл ответ" in decision_str):
            action_type = "know_answer"
        elif ("не нашел" in decision_str
              or "не нашёл" in decision_str
              or "не найдено" in decision_str):
            action_type = "search_miss"
        elif "пользователь ответил" in decision_str:
            action_type = "user_answer"
        elif "repair" in decision_str or "ремонт" in decision_str:
            action_type = "repair"
        elif "deep_rest" in decision_str or "глубокий отдых" in decision_str:
            action_type = "deep_rest"
        elif "checkpoint" in decision_str:
            action_type = "checkpoint_now"
        elif decision_str.strip() in self.ACTION_ALIASES:
            # Действия от Active Inference / арбитра: «explore», «rest»,
            # «think_decompose», «synthesize», «ask_user».
            action_type = self.ACTION_ALIASES[decision_str.strip()]
        else:
            action_type = "default"

        self._action_type_counts[action_type] = (
            self._action_type_counts.get(action_type, 0) + 1
        )
        # Тип действия — в логе, иначе метрика «смысла» не восстанавливается
        # из истории после перезапуска.
        get_logger().log(f"Выполняет [{action_type}]: {action}")
        
        base_cost = self._get_adaptive_cost(action_type)
        
        # === Интероцепция: модулируем стоимость и проверяем возможность ===
        # Восстановительные и служебные действия (отдых, ремонт, чекпоинт)
        # не проверяются на усталость: запрещать отдых уставшему — значит
        # запирать его в истощении навсегда. Замер до правки: 243 отказа
        # «too_tired» на 400 попыток, включая сами попытки отдохнуть.
        if action_type in ESSENTIAL_ACTIONS:
            cost = 0.0 if action_type in RECOVERY_ACTIONS else base_cost
        elif hasattr(self, 'interoception') and self.interoception:
            cost = self.interoception.get_action_cost(base_cost)
            if not self.interoception.can_perform_action(base_cost, self.energy):
                get_logger().log(f"[INTEROCEPTION] Too exhausted for {action_type} (cost={cost:.1f}, energy={self.energy})")
                # Отказ — тоже исход: мир не изменился. Без записи
                # действие не гаснет и выбирается снова и снова.
                step_body(self, action_type, performed=False)
                record_denied_outcome(self, action_type, world_before, "too_tired")
                return f"Ответ: Слишком устала для {action_type}"
        else:
            cost = base_cost

        # === Stage 19: одно бюджетное решение на действие ===
        # Бюджет читает и пишет ту же энергию агента. При выключенном флаге
        # он лишь повторяет прежнее ``self.energy -= cost``.
        budget = getattr(self, "action_budget", None)
        if budget is not None:
            decision = budget.charge(
                action_type=action_type,
                cost=cost,
                source="core_act",
            )
            if not decision.allowed:
                get_logger().log(
                    f"[BUDGET] denied {action_type}: {decision.reason} "
                    f"(cost={decision.cost:.1f}, energy={decision.energy_before:.1f})"
                )
                step_body(self, action_type, performed=False)
                record_denied_outcome(self, action_type, world_before, "budget")
                return (
                    f"Ответ: Бюджет не разрешает {action_type}: "
                    f"{decision.reason}"
                )
            # Стоимость реально списана — запоминаем для права на ошибку.
            self._last_action_cost = float(decision.cost)
        else:
            self.energy -= cost
            self._last_action_cost = float(cost)

        expectation_trial = None
        expectations = None
        # Узкое доказательство результата для действий, чей полезный эффект
        # не выражается в общей подписи знаний. Заполняет только обработчик
        # после фактического изменения; сам вызов действия успехом не считается.
        confirmed_result = False
        result_description = ""
        if action_type in ("rest", "deep_rest") and getattr(self, "mental_models", None) is not None:
            from src.cognition.action_expectations import ActionExpectations

            expectations = getattr(self, "action_expectations", None)
            if expectations is None:
                expectations = self.action_expectations = ActionExpectations()
            expectation_trial = expectations.begin(
                self.mental_models, action_type, float(self.energy),
                float(getattr(LR_CONFIG, "ENERGY_MAX", 200)),
                fatigue=getattr(getattr(getattr(self, "interoception", None), "state", None), "fatigue", None),
            )

        # === Death Risk actions: выполняем реальную логику восстановления ===
        if action_type == "repair":
            if hasattr(self, 'death_risk') and self.death_risk:
                changes = self.death_risk.integrity.manual_repair(intensity=2.0)
                get_logger().flush_immediate(f"[DEATH_RISK] Manual repair: {changes}")
        elif action_type == "deep_rest":
            # Тело «живёт» этот такт централизованно, в конце act():
            # см. step_body(action_type). Здесь только восстановление
            # энергии агента и работа сна.
            recover = getattr(self, "_recover_energy", None)
            recovered = recover(deep=True) if recover else 0.0
            consolidate = getattr(self, "_accumulate_sleep", None)
            consolidated = consolidate(1.0) if consolidate else {}
            parts = []
            if recovered:
                confirmed_result = True
                result_description = f"энергия восстановлена на {recovered:.0f}"
                parts.append(
                    f"восстановила {recovered:.0f} энергии (теперь {self.energy:.0f})"
                )
            if consolidated:
                parts.append(
                    f"осмыслила накопленное: связей {consolidated.get('links', 0)}, "
                    f"формулировок {consolidated.get('definitions', 0)}"
                )
            if parts:
                action = "Ответ: " + "; ".join(parts)
        elif action_type == "checkpoint_now":
            if hasattr(self, 'death_risk') and self.death_risk:
                self.death_risk.force_checkpoint()
                get_logger().flush_immediate("[DEATH_RISK] Manual checkpoint created")
        # Обработчики действий вызываются через getattr: act() работает и в
        # лёгких объектах (тесты бюджета, заглушки), где их нет. Отсутствие
        # обработчика — не ошибка: действие остаётся без эффекта.
        elif action_type == "let_go":
            from src.cognition.intention_waiting import resolve_wait

            params = intention or {}
            values = params.get("params", {})
            decision = resolve_wait(self, values.get("action", "explore"), values.get("topic", ""),
                                    kind="forgotten", reason=values.get("reason", "сама решила отпустить"))
            action = f"Ответ: отпустила намерение '{values.get('topic', '')}' ({decision['status']})"
        elif action_type == "create_draft":
            from src.cognition.creative_catalog import perform_creative

            mode, identifier, reason = creative_choice
            draft = perform_creative(self, mode, identifier, reason)
            verb = "оставила" if mode == "leave" else "создала" if mode == "new" else "продолжила"
            action = f"Ответ: {verb} черновик «{draft['theme']}», версия {draft['revision']}"
        elif action_type == "play":
            from src.cognition.local_play import (
                guess_turn, new_game, new_guess_game, play_turn,
            )

            # Две игры. Выбор — та, где сыграно меньше партий: опыт
            # распределяется ровно, а не залипает на первой игре.
            ttt = getattr(self, "_local_play", None)
            guess = getattr(self, "_local_guess", None)
            ttt_rounds = (ttt or {}).get("round", 0)
            guess_rounds = (guess or {}).get("round", 0)
            if guess_rounds < ttt_rounds:
                if guess is None:
                    guess = self._local_guess = new_guess_game()
                turn = guess_turn(guess)
                self._last_play_result = turn
                action = (
                    f"Ответ: угадываю число — назвала {turn['guess']} "
                    f"({turn['hint']}), попытка {turn['attempts']}"
                )
                if turn["result"] is not None:
                    action += (
                        f"; партия {turn['round']} выиграна "
                        f"за {turn['attempts']} попыток"
                    )
            else:
                state = ttt
                if state is None:
                    state = self._local_play = new_game()
                turn = play_turn(state)
                self._last_play_result = turn
                action = f"Ответ: сыграла ход {turn['chosen_cell'] + 1}; поле {''.join(turn['board'])}"
                if turn["result"] is not None:
                    action += f"; партия завершена: {turn['result']}"
            # Вернувшийся ход уже изменил состояние выбранной игры. Исход
            # партии не требуется: проигрыш и ничья — тоже результат хода.
            confirmed_result = True
            result_description = f"выполнен игровой ход в партии {turn['round']}"
        elif action_type == "explore":
            # Раньше «explore» ничего не делал: тип «default», энергия
            # списывалась, мир не менялся. Теперь это настоящая работа —
            # выбрать слабое место в знаниях и поработать над ним.
            handler = getattr(self, "_act_explore", None)
            target = selected_target
            exploration = (handler(target=target) if target else handler()) if handler else None
            topic = (exploration or {}).get("target") or ""
            action = (exploration or {}).get("text") or action
        elif action_type == "rest":
            recover = getattr(self, "_recover_energy", None)
            recovered = recover(deep=False) if recover else 0.0
            consolidate = getattr(self, "_accumulate_sleep", None)
            consolidated = consolidate(0.5) if consolidate else {}
            parts = []
            if recovered:
                parts.append(
                    f"восстановила {recovered:.0f} энергии (теперь {self.energy:.0f})"
                )
            if consolidated:
                parts.append(
                    f"осмыслила накопленное: связей {consolidated.get('links', 0)}, "
                    f"формулировок {consolidated.get('definitions', 0)}"
                )
            if parts:
                action = "Ответ: " + "; ".join(parts)
        elif action_type == "synthesis":
            handler = getattr(self, "_act_synthesize", None)
            synthesis = (handler(target=selected_target) if selected_target else handler()) if handler else None
            topic = (synthesis or {}).get("target") or ""
            action = (synthesis or {}).get("text") or action
        elif action_type == "decomposition":
            handler = getattr(self, "_act_decompose", None)
            target = selected_target
            decomposition = (handler(target=target) if target else handler()) if handler else None
            topic = (decomposition or {}).get("target") or ""
            action = (decomposition or {}).get("text") or action
        elif action_type == "reflection":
            handler = getattr(self, "_act_reflect", None)
            reflection = handler() if handler else None
            action = (reflection or {}).get("text") or action
        elif action_type == "ask_user":
            handler = getattr(self, "_act_ask_user", None)
            asked = (handler(target=selected_target) if selected_target else handler()) if handler else None
            topic = (asked or {}).get("target") or ""
            action = (asked or {}).get("text") or action
        elif action_type == "communicate":
            handler = getattr(self, "_act_communicate", None)
            told = handler() if handler else None
            action = (told or {}).get("text") or action
        elif action_type == "web_search":
            handler = getattr(self, "_act_web_search", None)
            found = (handler(target=selected_target) if selected_target else handler()) if handler else None
            topic = (found or {}).get("target") or ""
            action = (found or {}).get("text") or action
        elif action_type == "read_news":
            handler = getattr(self, "_act_read_news", None)
            news = handler() if handler else None
            topic = (news or {}).get("target") or ""
            action = (news or {}).get("text") or action
        elif action_type == "browse_web":
            handler = getattr(self, "_act_browse_web", None)
            browsed = handler() if handler else None
            topic = (browsed or {}).get("target") or ""
            action = (browsed or {}).get("text") or action
        elif action_type == "draw":
            handler = getattr(self, "_act_draw", None)
            drawn = handler() if handler else None
            topic = (drawn or {}).get("target") or ""
            action = (drawn or {}).get("text") or action
        elif action_type == "compose_music":
            handler = getattr(self, "_act_compose_music", None)
            composed = handler() if handler else None
            topic = (composed or {}).get("target") or ""
            action = (composed or {}).get("text") or action
        elif action_type == "hypothesis":
            handler = getattr(self, "_act_hypothesis", None)
            guess = handler() if handler else None
            topic = (guess or {}).get("target") or ""
            action = (guess or {}).get("text") or action
        elif action_type == "set_own_goal":
            handler = getattr(self, "_act_set_own_goal", None)
            own = handler() if handler else None
            topic = (own or {}).get("target") or ""
            action = (own or {}).get("text") or action

        # === Замыкание петли: что изменилось в мире? ===
        # Не обязательно: act() используется и в лёгких тестовых объектах.
        loop_closer = getattr(self, "loop_closer", None)
        outcome = None
        if loop_closer is not None:
            outcome = loop_closer.observe_agent_action(
                self,
                action_type,
                world_before,
                topic=topic,
                confirmed_result=confirmed_result,
                result_description=result_description,
            )
            self._last_action_outcome = outcome

        if outcome is not None and outcome.had_effect:
            get_logger().log(
                f"[LOOP] {action_type} дал результат: {outcome.summary}"
            )
            # Прогресс цели засчитывается по доказанному результату, а не
            # по факту «пошевелился». Тема — то, над чем шла работа.
            if topic:
                credit = self._check_goal_progress(
                    topic, answered=True, evidence=outcome.delta
                )
                outcome_credit = credit.get("pct", 0)
                if outcome_credit:
                    get_logger().log(
                        f"[LOOP] Цель: {outcome_credit}% после '{topic}'"
                    )
        else:
            streak = (
                loop_closer.no_effect_streak(action_type)
                if loop_closer is not None
                else 0
            )
            if streak >= 2:
                get_logger().log(
                    f"[LOOP] {action_type} без результата "
                    f"({streak} раз подряд)"
                )

        # === Тело: прожить такт ===
        # Ровно один раз за действие, после того как оно выполнено.
        # Нагрузка зависит от типа: тяжёлая работа утомляет, отдых
        # восстанавливает. Отказы обрабатываются отдельно, до обработчика.
        # Модульная функция, а не метод: act() работает и в лёгких
        # объектах без тела (тесты бюджета, заглушки).
        step_body(self, action_type, performed=True)
        if expectations is not None:
            observation = expectations.finish(
                self.mental_models, expectation_trial, float(self.energy),
                fatigue_after=getattr(getattr(getattr(self, "interoception", None), "state", None), "fatigue", None),
            )
            if observation is not None:
                get_logger().log(
                    f"[EXPECTATION] {action_type}: delta={observation['delta']:.3f}, "
                    f"matched={observation['prediction_matched']}"
                )

        # === Мотивация: результат действия (P1.2 Valence Feedback) ===
        if hasattr(self, 'motivation_system'):
            # Успех — это факт исполнения, а не остаток энергии. Раньше
            # здесь стояло `self.energy > 10`: усталый агент не мог
            # удовлетворить ни одну потребность, любое действие считалось
            # неуспешным, и голод только рос — отсюда бесконечные вопросы.
            # Отказы (усталость, бюджет) выходят из act() раньше и сюда не
            # доходят. Качество исхода передаётся отдельно, в valence.
            success = action_type not in ("default", "wait")
            # Compute actual valence from result
            valence_context = {"energy": self.energy, "max_energy": getattr(self, "_legacy_energy", 150)}
            actual_valence = self.motivation_system.compute_actual_valence(
                action_type, action, success, valence_context
            )
            # Учебное действие, которое ничего не изменило в мире, не
            # должно удовлетворять любопытство. Раньше «изучил, но не
            # нашёл» получало положительную валентность (в тексте нет
            # слова error), и потребность закрывалась впустую — агент
            # «учился» вечно и никогда не шёл спрашивать.
            if (
                loop_closer is not None
                and outcome is not None
                and loop_closer.is_productive(action_type)
                and not outcome.had_effect
            ):
                actual_valence = min(actual_valence, -0.2)
            if action_type == "create_draft" and creative_choice[0] == "leave":
                actual_valence = 0.0
            self.motivation_system.on_action_result(action_type, success, actual_valence)
            get_logger().log(f"[ACT VALENCE] {action_type}: success={success}, valence={actual_valence:.3f}")
        elif hasattr(self, 'internal_motivation'):
            # Fallback to legacy internal_motivation
            success = self.energy > 10
            valence = 0.3 if success else -0.2
            self.internal_motivation.on_action_result(action_type, success, valence)
        
        # === Отслеживаем использование концепций (для забывания) ===
        if decision and isinstance(decision, str):
            self._concept_usage_count[decision] = self._concept_usage_count.get(decision, 0) + 1
        
        # gc.collect() периодически для контроля памяти
        if self.cycle_count % SIM_CONFIG.GC_INTERVAL == 0:
            gc.collect()
        
        return action

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
        """Backward-compat property: возвращает очередь OpenQuestionsManager.

        Позволяет существующему коду (``for q in self._open_questions:``,
        ``self._open_questions.append(...)``) работать без изменений.
        Изменения через этот property проксируются в manager.queue.
        """
        if not hasattr(self, "_open_questions_manager"):
            return []
        return self._open_questions_manager.queue

    @_open_questions.setter
    def _open_questions(self, value) -> None:
        """Backward-compat setter: заменяет очередь целиком.

        Используется в тестах для сброса (``a._open_questions = []``) и в
        legacy-коде, который не знает про OpenQuestionsManager. После
        присвоения все методы Open Questions будут работать с новой очередью.
        """
        if not hasattr(self, "_open_questions_manager"):
            return
        if value is None:
            self._open_questions_manager.queue = []
        else:
            self._open_questions_manager.queue = list(value)

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
        if not hasattr(self, "active_inference"):
            return
        try:
            obs_after = encode_observations(self)
            self.active_inference.record_experience(
                action=action,
                obs_before=obs_before or {},
                obs_after=obs_after,
                reward=float(valence or 0.0),
            )
            buffer = getattr(self.active_inference, "experience_buffer", None) or []
            batch_size = getattr(self.active_inference, "batch_size", None) or 32
            if len(buffer) >= batch_size:
                self.active_inference.learn_from_experience(batch_size=batch_size)
        except Exception as e:
            get_logger().log(f"[ACTIVE_INFERENCE] Experience recording error: {e}")

    def _ingest_motivation_goals(self, new_goals: List[dict]) -> None:
        """Этап 5: цели, сгенерированные мотивацией, → поток целей агента.

        Цели без executable-payload остаются когнитивными (честно); исполняемые
        цели проверяются через success predicate мостом Delamain.
        """
        if not new_goals:
            return
        existing_titles = {g.get("title") for g in self.goals if g.get("title")}
        for g in new_goals:
            title = str(g.get("title") or "")
            if not title or title in existing_titles:
                continue
            try:
                gid = self.set_goal(
                    title,
                    difficulty=int(g.get("difficulty") or 1),
                    success_predicate=str(g.get("success_predicate") or ""),
                )
                from src.cognition.activity_goals import attach_activity

                attach_activity(self, gid, g)
                existing_titles.add(title)
                get_logger().log(f"[MOTIVATION] Goal ingested: {title} (id={gid})")
            except Exception as e:
                get_logger().log(f"[MOTIVATION] Goal ingestion failed: {e}")

    def autonomous_tick(self) -> Dict:
        """Автономный тик жизни — вызывается каждый цикл независимо от стимулов.

        Это «сердцебиение» агента: спонтанность, сны, проактивность, телесность,
        осознание смертности, привязанности — всё, что делает его живым
        даже когда никто не пишет в чат.
        """
        cycle = self.cycle_count
        result = {
            "cycle": cycle,
            "subsystems": None,
            "will": None,
            "communication": None,
            "soul": None,
            "active_inference": None,
            "arbitrator": None,
        }

        use_arbitrator = getattr(SIM_CONFIG, 'USE_ARBITRATOR', True)
        candidates = []
        arbiter_context = {"energy": self.energy, "cycle": cycle, "intelligence": self.intelligence}
        ai_intention = None
        obs_before: Dict = {}
        if hasattr(self, "active_inference"):
            try:
                observations = encode_observations(self)
                obs_before = dict(observations)
                action_name, ai_info = self.active_inference.step(observations)
                self._active_inference_intention = action_name
                self._active_inference_info = ai_info
                result["active_inference"] = {"intention": action_name, "free_energy": ai_info.get("free_energy"), "beliefs": ai_info.get("beliefs"), "G_values": ai_info.get("G_values")}
                get_logger().log(f"[ACTIVE_INFERENCE] Cycle {cycle}: intention={action_name}, F={ai_info.get('free_energy', 0):.3f}")
                ai_intention = action_name
                if action_name and action_name != "think_known":
                    fe = ai_info.get("free_energy", 1.0)
                    strength = max(0.1, min(1.0, 1.0 - fe / 5.0))
                    candidates.append({"source": "active_inference", "action": action_name, "strength": strength, "params": {}, "free_energy": fe})
            except Exception as e:
                get_logger().log(f"[ACTIVE_INFERENCE] Error in autonomous_tick: {e}")

        from src.cognition.method_preferences import apply as apply_method_preferences
        candidates = apply_method_preferences(self, candidates)

        from src.cognition.activity_goals import activity_candidate

        own_activity = activity_candidate(self)
        if own_activity is not None:
            candidates.append(own_activity)

        pending_stimulus = getattr(self, "_attention_stimulus", None)
        if pending_stimulus is not None:
            candidates.append({"source": "external_attention", "action": "process_stimulus",
                               "strength": 0.85 if pending_stimulus["user_initiated"] else 0.3,
                               "params": {"user_initiated": pending_stimulus["user_initiated"]}})

        # 1. Motivation candidates
        if hasattr(self, "motivation_system"):
            try:
                motivation_candidates = self.motivation_system.get_action_candidates(arbiter_context)
                candidates.extend(motivation_candidates)
            except Exception as e:
                get_logger().log(f"[MOTIVATION_CANDIDATES] Error: {e}")

        # 2. Embodiment candidates
        # Раньше здесь читался ``self._interoception_status``, который
        # никто никогда не выставлял: ветка была мёртвой, и тело не
        # предлагало отдых даже при полном истощении. Теперь состояние
        # берётся напрямую у интероцепции, а «eat» (не существующее
        # действие) заменён на отдых.
        #
        # Отдых включается по усталости и выключается только после
        # восстановления (гистерезис): иначе агент возвращался к работе
        # на самом пороге и не успевал восполнить АТФ.
        resting = self._update_rest_mode()
        if hasattr(self, "interoception") and self.interoception is not None:
            try:
                intero_status = self.interoception.get_status()
                fatigue = float(intero_status.get("fatigue", 0.0) or 0.0)
                energy_ratio = (
                    float(self.energy) / float(LR_CONFIG.ENERGY_MAX or 1.0)
                )
                rest_threshold = float(
                    getattr(LR_CONFIG, "REST_FATIGUE_THRESHOLD", 0.6)
                )
                low_ratio = float(getattr(LR_CONFIG, "LOW_ENERGY_RATIO", 0.25))
                if resting or fatigue >= rest_threshold or energy_ratio <= low_ratio:
                    candidates.append({
                        "source": "embodiment",
                        "action": "deep_rest",
                        # Пока тело отдыхает — это главное дело. На входе
                        # в отдых сила растёт быстрее усталости (0.6 → 0.75),
                        # иначе отдых проигрывал обучению.
                        "strength": 1.0 if resting else min(
                            1.0,
                            max(fatigue, 1.0 - energy_ratio) * 1.25,
                        ),
                        "params": {
                            "reason": "resting" if resting else (
                                "tired" if fatigue >= rest_threshold else "low_energy"
                            ),
                            "fatigue": round(fatigue, 3),
                            "energy_ratio": round(energy_ratio, 3),
                        },
                    })
            except Exception as e:
                get_logger().log(f"[EMBODIMENT_CANDIDATES] Error: {e}")

        # 3. Social candidates: потребность в контакте и незакрытые вопросы.
        # Раньше здесь стоял `pass`: секция существовала, но ничего не
        # добавляла, поэтому общение никогда не попадало в выбор.
        try:
            candidates.extend(self._social_candidates(cycle))
        except Exception as e:
            get_logger().log(f"[SOCIAL_CANDIDATES] Error: {e}")

        # Собственная проверка — кандидат, а не приказ и не новая цель.
        from src.cognition.experiment_proposals import propose_experiment

        experimental = propose_experiment(
            self.mental_models, energy=float(self.energy),
            energy_max=float(LR_CONFIG.ENERGY_MAX),
            fatigue=getattr(getattr(getattr(self, "interoception", None), "state", None), "fatigue", None),
            cycle=cycle, last_cycle=getattr(self, "_last_experiment_cycle", None),
        )
        if experimental is not None:
            candidates.append(experimental)
            result["experiment_proposal"] = experimental

        from src.cognition.intention_continuation import continuation_candidate

        continuation = continuation_candidate(self)
        if continuation is not None:
            candidates.append(continuation)
            result["continuation_proposal"] = continuation

        from src.cognition.intention_fading import fading_assessment
        from src.cognition.intention_waiting import waiting_key

        for waiting in getattr(self, "_waiting_intentions", {}).values():
            assessment = fading_assessment(self, waiting)
            if assessment.get("eligible"):
                candidates.append({
                    "source": "self_fading",
                    "action": "let_go",
                    "strength": 0.4,
                    "params": {"action": waiting["action"], "topic": waiting["target"],
                               "reason": "повторные попытки без новых свидетельств",
                               "waiting_key": waiting_key(waiting["action"], waiting["target"])},
                })
                result.setdefault("fading_proposals", []).append(waiting["target"])
                break

        # === УСТАЛОСТЬ: тяжёлая работа хуже даётся ===
        # ``cognitive_throughput`` падает с усталостью (1 - 0.7*fatigue).
        # Раньше величина только считалась и сохранялась в чекпоинт —
        # на выбор она не влияла. Теперь она снижает тягу к тяжёлым
        # действиям: уставший агент сам выбирает отдых или лёгкое дело,
        # а не потому, что ему запретили работать.
        try:
            intero = getattr(self, "interoception", None)
            throughput = (
                float(intero.state.cognitive_throughput)
                if intero is not None
                else 1.0
            )
            if resting:
                # Пока тело отдыхает, тяжёлая работа не тянет: это не
                # запрет, а отсутствие желания работать через силу.
                throughput = min(throughput, 0.15)
            if throughput < 0.99:
                for candidate in candidates:
                    action_type = self._normalize_action(candidate.get("action"))
                    if action_type in HEAVY_ACTIONS:
                        candidate["strength"] = float(
                            candidate.get("strength", 0.5)
                        ) * max(0.2, throughput)
        except Exception as e:
            get_logger().log(f"[BODY] throughput damping error: {e}")

        from src.cognition.creative_choices import creative_choices

        expanded_candidates = []
        for candidate in candidates:
            if self._normalize_action(candidate.get("action")) == "create_draft":
                expanded_candidates.extend(creative_choices(self, candidate))
            else:
                expanded_candidates.append(candidate)
        candidates = expanded_candidates

        # === ФИЛЬТР ДОСТУПНОСТИ ===
        # Не предлагаем арбитру то, что сейчас физически нельзя выполнить:
        # вопрос при кулдауне, поиск при выключенной сети, действие при
        # нехватке энергии. Иначе действие выигрывает выбор, упирается в
        # отказ и сжигает цикл.
        #
        # Гасить силу уже выбранных действий пробовали — это приводило к
        # метанию между бесплодными вариантами. Дешевле не предлагать
        # невозможное вовсе.
        #
        # Отказы, ставшие неправдой (энергия вернулась), снимаются здесь же:
        # иначе отдых не возвращал бы агента к работе — действие навсегда
        # осталось бы помеченным как тупиковое.
        self._release_recovered_denials()
        candidates = [
            candidate
            for candidate in candidates
            if self._is_candidate_available(candidate)
        ]

        # Тело не может ничего из предложенного — но отдых доступен всегда.
        # Без этого арбитр получал пустой список и выбирал «wait», то есть
        # агент в истощении не отдыхал, а просто стоял.
        if not candidates and (self._body_needs_rest() or self._is_resting()):
            candidates = [{
                "source": "embodiment",
                "action": "deep_rest",
                "strength": 1.0,
                "params": {"reason": "nothing_affordable"},
            }]

        from src.cognition.method_feedback import prepare_candidates

        candidates, feedback = prepare_candidates(self, candidates)
        result["method_feedback"] = feedback
        if not candidates:
            if self._body_needs_rest() or self._is_resting():
                fallback = "deep_rest"
                reason = "body_needs_rest"
            else:
                fallback = "wait"
                reason = "no_working_method"
            candidates = [{"action": fallback, "source": "deliberate_pause",
                           "strength": 0.1, "params": {"reason": reason}}]

        # === ЭМОЦИОНАЛЬНЫЙ ОТТЕНОК ВЫБОРА (Эмоции-2) ===
        # Пережитое смещает тягу к занятиям: страх тянет к безопасному,
        # счастье — к творческому, грусть — к тихому. Это вес, не
        # команда: список кандидатов не меняется, цели и ценности не
        # трогаются, решает по-прежнему арбитр.
        try:
            emotional_bias = self._apply_emotional_bias(candidates)
            if emotional_bias:
                result["emotional_bias"] = emotional_bias
        except Exception as e:
            get_logger().log(f"[EMOTIONAL_BIAS] Error: {e}")

        # === ARBITRATION ===
        chosen_action = None
        arbitrator_result = None
        if use_arbitrator and hasattr(self, "decision_arbitrator"):
            try:
                arbitrator_result = self.decision_arbitrator.choose_action(candidates, arbiter_context)
                chosen_action = arbitrator_result.get("action")
                result["arbitrator"] = arbitrator_result
                get_logger().log(f"[ARBITRATOR] {arbitrator_result.get('reasoning', 'No reasoning')}")
            except Exception as e:
                get_logger().log(f"[ARBITRATOR] Error: {e}")
                if candidates:
                    chosen_action = candidates[0].get("action")
                    result["arbitrator"] = {"action": chosen_action, "source": "fallback_first_candidate", "verdict": "proceed", "reasoning": f"Arbitrator error: {e}"}
        else:
            chosen_action = ai_intention
            result["arbitrator"] = {"action": chosen_action, "source": "legacy_active_inference", "verdict": "proceed" if chosen_action else "stop", "reasoning": "USE_ARBITRATOR=False or no arbitrator available"}

        # === ВЫХОД ИЗ ТУПИКА ===
        # Если выбранное действие уже несколько раз подряд не давало
        # наблюдаемого результата, повторять его бессмысленно. Раньше агент
        # так и делал: бесконечно выбирал explore, потому что ничто не
        # мешало. Теперь берём первого кандидата, который не в тупике.
        #
        # Имя нормализуем: мотивация зовёт действие «exploration», а
        # арбитр — «explore». Без нормализации проверка тупика смотрела бы
        # на другое имя и никогда не срабатывала.
        result["initial_arbitration"] = dict(result.get("arbitrator") or {})
        arbitrator_data = result.get("arbitrator") or {}
        if arbitrator_data.get("verdict") == "stop":
            # Воля вместо молчания: либо осознанный риск ради значимой
            # цели, либо собственный отказ с записью в журнал воли.
            # Legacy-путь («нет арбитра») — состояние системы, а не воля,
            # поэтому он не порождает волевых актов.
            risk_entry = None
            will_applies = bool(chosen_action) and (
                arbitrator_data.get("source") != "legacy_active_inference"
            )
            if will_applies:
                risk_entry = self._consider_will_risk(
                    chosen_action,
                    str(arbitrator_data.get("reasoning", "stop")),
                )
            if risk_entry is not None:
                result["will_risk_taken"] = risk_entry
            else:
                result["action_refused"] = {"action": chosen_action,
                                            "reason": arbitrator_data.get("reasoning", "stop")}
                if will_applies:
                    result["will_refusal"] = self.defend_refusal(
                        topic=str(chosen_action),
                        reason=str(arbitrator_data.get("reasoning", "stop")),
                    )
                chosen_action = "wait"
        if chosen_action == "let_go":
            selected_intention = result.get("arbitrator") or {}
            result["autonomous_action"] = {"action": chosen_action,
                                            "result": self.act(chosen_action, intention=selected_intention)}
            return result
        chosen_type = self._normalize_action(chosen_action)
        if chosen_action and self.loop_closer.is_stuck(chosen_type):
            stopped_types = {
                self._normalize_action(entry.get("action"))
                for entry in result.get("arbitrator", {}).get("all_evaluations", [])
                if entry.get("verdict") == "stop"
            }
            ranked = sorted(
                [candidate for candidate in candidates
                 if self._normalize_action(candidate.get("action")) not in stopped_types],
                key=lambda c: float(c.get("strength", 0.0)),
                reverse=True,
            )
            # Запасной вариант тоже должен быть выполнимым и результативным:
            # если тело истощено, «think_decompose» — это ещё один отказ, а
            # если очередь вопросов полна — пустой ход.
            fallback = self._stuck_fallback()
            if self._normalize_action(fallback) in stopped_types:
                fallback = "wait"
            alternative = self.loop_closer.choose(
                ranked,
                fallback=fallback,
                normalize=self._normalize_action,
            )
            if alternative.get("action") != chosen_action:
                result["loop_escape"] = {
                    "from": chosen_action,
                    "to": alternative.get("action"),
                    "reason": "no observable effect",
                    "streak": self.loop_closer.no_effect_streak(chosen_type),
                    "denied_streak": self.loop_closer.denied_streak(chosen_type),
                    "had_effect_before": self.loop_closer.has_effect_history(chosen_type),
                    "fallback": alternative.get("reason") == "all_stuck",
                    "candidate_diagnostics": self.loop_closer.describe_candidates(ranked, normalize=self._normalize_action),
                }
                get_logger().log(
                    f"[LOOP] '{chosen_action}' не даёт результата "
                    f"({result['loop_escape']['streak']} раз) — "
                    f"переключаюсь на '{alternative.get('action')}'"
                )
                chosen_action = alternative.get("action")
                if arbitrator_result is not None:
                    arbitrator_result = dict(arbitrator_result)
                    arbitrator_result["action"] = chosen_action
                    arbitrator_result["source"] = "loop_closer"
                    arbitrator_result["params"] = dict(alternative.get("params") or {})
                    result["arbitrator"] = arbitrator_result

        # === EXECUTE ===
        # Для диагностики: что именно выбрал арбитр в этом цикле.
        self._last_arbitration = result.get("arbitrator")
        # P1.2: Valence Feedback Loop - predict valence before action
        valence_context = {
            "energy": self.energy,
            "max_energy": getattr(self, "_legacy_energy", 150),
            "cycle": cycle,
        }
        predicted_valence = 0.0
        if hasattr(self, "motivation_system") and chosen_action:
            try:
                predicted_valence = self.motivation_system.predict_valence(chosen_action, valence_context)
                result["predicted_valence"] = predicted_valence
                get_logger().log(f"[VALENCE] Predicted for {chosen_action}: {predicted_valence:.3f}")
            except Exception as e:
                get_logger().log(f"[VALENCE] Prediction error: {e}")

        if chosen_action == "process_stimulus":
            result["attention_selected"] = True
        if chosen_action and chosen_action not in ("think_known", "wait", "none", "process_stimulus"):
            from src.cognition.intention_history import begin_intention, finish_intention

            history_selection = dict(result.get("arbitrator") or {})
            history_selection["action"] = chosen_action
            intention_entry = begin_intention(self, history_selection)
            self._last_action_outcome = None
            # Прошлая стоимость не должна простить чужую ошибку: если
            # исключение случится до списания, прощать будет нечего.
            self._last_action_cost = 0.0
            try:
                experiment_selected = (
                    result.get("arbitrator", {}).get("source") == "self_experiment"
                    and experimental is not None
                    and chosen_action == experimental["action"]
                )
                selected_intention = result.get("arbitrator") or {}
                from copy import deepcopy

                activity_attrs = {"play": "_local_play", "create_draft": "_creative_draft",
                                  "draw": "_art_work", "compose_music": "_music_work"}
                activity_before = deepcopy(
                    getattr(self, activity_attrs.get(chosen_action, "_creative_draft"), None)
                )
                if self._normalize_action(chosen_action) in {"explore", "decomposition", "synthesis", "ask_user", "web_search", "create_draft"} and selected_intention.get("params"):
                    action_result = self.act(chosen_action, intention=selected_intention)
                else:
                    action_result = self.act(chosen_action)
                from src.cognition.method_preferences import observe as observe_method

                last = getattr(self, "_last_action_outcome", None)
                normalized_action = self._normalize_action(chosen_action)
                if normalized_action not in {"rest", "deep_rest", "wait", "checkpoint_now", "repair", "play", "create_draft", "draw", "compose_music"}:
                    generic_outcome = "performed"
                    if last is not None and last.reason.startswith("denied:"):
                        generic_outcome = "denied"
                    observe_method(self, normalized_action, outcome=generic_outcome,
                               had_effect=bool(last and last.had_effect),
                               emotional_valence=result.get("actual_valence", 0.0))
                if normalized_action in {"play", "create_draft", "draw", "compose_music"}:
                    activity_state = getattr(self, activity_attrs[normalized_action], None)
                    activity_outcome = "left" if activity_state and activity_state.get("status") == "left" else "performed"
                    if last is not None and last.reason.startswith("denied:"):
                        activity_outcome = "denied"
                    observe_method(self, chosen_action, outcome=activity_outcome,
                                   had_effect=bool(last and last.had_effect),
                                   emotional_valence=result.get("actual_valence", 0.0))
                if normalized_action in {"play", "create_draft", "draw", "compose_music"}:
                    from src.cognition.activity_goals import record_activity_step

                    activity_type = self._normalize_action(chosen_action)
                    activity_after = getattr(self, activity_attrs[activity_type], None)
                    record_activity_step(self, selected_intention, activity_type, activity_before, activity_after)
                finish_intention(intention_entry, getattr(self, "_last_action_outcome", None))
                self._record_core_life_episode(intention_entry)
                from src.cognition.intention_evidence import finish_evidence_goal

                finish_evidence_goal(self, intention_entry)
                result["intention_id"] = intention_entry["id"]
                result["executed_intention"] = {"action": chosen_action,
                                                "source": selected_intention.get("source"),
                                                "params": dict(selected_intention.get("params") or {})}
                if experiment_selected:
                    self._last_experiment_cycle = cycle
                    observed = getattr(getattr(self, "action_expectations", None), "last_trial", None)
                    result["experiment_result"] = {
                        "claim_id": experimental["params"]["claim_id"],
                        "observation": observed,
                    }
                result["autonomous_action"] = {"action": chosen_action, "result": action_result}
                get_logger().log(f"[AUTONOMOUS_ACTION] {action_result}")
                
                # P1.2: Compute actual valence and update motivation
                success = True
                if "error" in str(action_result).lower() or "fail" in str(action_result).lower():
                    success = False
                if not success:
                    # Право на ошибку: часть оплаченной стоимости — урок.
                    absolution = self._absorb_action_failure(
                        chosen_action, str(action_result)[:160]
                    )
                    if absolution:
                        result["will_fail_absolution"] = absolution
                
                if hasattr(self, "motivation_system"):
                    try:
                        actual_valence = self.motivation_system.compute_actual_valence(
                            chosen_action, str(action_result), success, valence_context
                        )
                        if (self._normalize_action(chosen_action) == "create_draft"
                                and selected_intention.get("params", {}).get("draft_mode") == "leave"):
                            actual_valence = 0.0
                        result["actual_valence"] = actual_valence
                        prediction_error = actual_valence - predicted_valence
                        result["valence_prediction_error"] = prediction_error
                        # Сам исход в потребности уже записал act(): он
                        # знает фактический тип действия. Второй вызов
                        # здесь удваивал удовлетворение (одно действие
                        # закрывало две доли дефицита), и потребности
                        # «залипали» сытыми.
                        get_logger().log(
                            f"[VALENCE] Actual for {chosen_action}: "
                            f"{actual_valence:.3f}, error: {prediction_error:.3f}"
                        )

                        # P2: Outcome loop — стимул -> действие -> результат -> валентность -> опыт
                        self._record_active_inference_experience(chosen_action, obs_before, actual_valence)
                    except Exception as e:
                        get_logger().log(f"[VALENCE] Feedback error: {e}")
                        
            except Exception as e:
                finish_intention(intention_entry, error=e)
                get_logger().log(f"[AUTONOMOUS_ACTION] Error: {e}")
                result["autonomous_action"] = {"action": chosen_action, "error": str(e)}
                absolution = self._absorb_action_failure(chosen_action, str(e))
                if absolution:
                    result["will_fail_absolution"] = absolution
                
                # P1.2: Failed action - negative valence
                if hasattr(self, "motivation_system"):
                    try:
                        actual_valence = self.motivation_system.compute_actual_valence(
                            chosen_action, str(e), False, valence_context
                        )
                        result["actual_valence"] = actual_valence
                        prediction_error = actual_valence - predicted_valence
                        result["valence_prediction_error"] = prediction_error
                        
                        self.motivation_system.on_action_result(chosen_action, False, actual_valence)
                        get_logger().log(f"[VALENCE] Failed action {chosen_action}: {actual_valence:.3f}")
                    except Exception as e:
                        get_logger().log(f"[VALENCE] Feedback error on failure: {e}")

        # === MOTIVATION SYSTEM TICK ===
        if hasattr(self, "motivation_system"):
            try:
                motivation_result = self.motivation_system.tick()
                result["motivation"] = motivation_result
                # P2: цели, сгенерированные мотивацией, в поток целей агента
                self._ingest_motivation_goals(motivation_result.get("new_goals") or [])
            except Exception as e:
                get_logger().log(f"[MOTIVATION_TICK] Error: {e}")
                result["motivation"] = {"error": str(e)}

        # 1. PluginRegistry
        # Stage 18B: если core_driven включён, tick_subsystems сам диспатчит
        # effector через EffectorDriver (не более одного шага эффектора за цикл).
        # См. DigitalBeing.tick_subsystems — там же дедуп по циклу.
        if hasattr(self, "plugin_registry"):
            result["subsystems"] = self.tick_subsystems(cycle)

        # 2. Will
        if hasattr(self, "tick_will"):
            result["will"] = self.tick_will(cycle)

        # 3. Communication
        if hasattr(self, "tick_communication"):
            result["communication"] = self.tick_communication(cycle)

        # 4. Soul
        if hasattr(self, "tick_soul"):
            result["soul"] = self.tick_soul(cycle)

        # 5. Death risk
        if hasattr(self, 'death_risk'):
            death_result = self.death_risk.step(dt=1.0)
            result["death_risk"] = death_result
            if not death_result['alive']:
                cause = death_result.get('cause') or death_result.get('death_cause')
                legacy = self.death_risk.legacy_package if hasattr(self.death_risk, 'legacy_package') else {}
                get_logger().flush_immediate(f"[DEATH] Agent died: {cause}")
                raise AgentDeadSignal(cause, legacy)
            # «Эмоции-2»: структура ниже порога предупреждения — реальная
            # причина страха. Кулдаун внутри EmotionalState не даёт
            # переживать один и тот же сигнал каждый цикл.
            self._emotions_from_death_risk(death_result)

        # 6. Эволюция — глаз/рука/проба/голос (периодически, внутри
        # свои пороги; None вне окна анализа).
        evolution = self._evolution_tick(cycle)
        if evolution is not None:
            result["evolution"] = evolution

        return result

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
