"""
checkpoint_serializer.py — сериализация/десериализация состояния агента.

Вынесено из ``DigitalBeing.save_state/load_state`` (Этап 4.5) для:
1. Снижения размера ``agent.py`` (God Module: 1845 → 1700 строк).
2. Изоляции формата чекпоинтов от бизнес-логики — тестируемо отдельно.
3. Поддержки миграций версий (``schema_version`` + ``migrate_state``).
4. Безопасного «best-effort» восстановления (если одна секция побита — не теряем всё).

Формат файла (data/checkpoints/<agent_name>_cycle_<N>.json):
    {
      "schema_version": <int>,
      "name": <str>,
      "energy": <float>,
      "cycle_count": <int>,
      "knowledge_base": <dict>,
      "intelligence": <int>,
      "completed_goals": <int>,
      "goals": <list>,
      "active_goal": <str | None>,       # title активной цели
      "success_streak": <int>,
      "saved_at": <iso datetime>,
      "_goal_progress": <dict>,
      "_learned_facts": <list>,
      "_known_definitions": <dict>,
      "naming_dialogue_phase": <str>,
      "naming_dialogue_history": <list>,
      "open_questions": <list>,
      "user_interaction": <dict | None>,  # история и ожидающие вопросы диалога
    }

Использование:
    from src.core.checkpoint_serializer import (
        CheckpointSerializer, build_state_from_agent, apply_state_to_agent,
    )

    state = build_state_from_agent(agent)
    CheckpointSerializer.save(state, agent.name, agent.cycle_count)
    ...
    state = CheckpointSerializer.load(checkpoint_path)
    apply_state_to_agent(agent, state)
"""
from __future__ import annotations

from copy import deepcopy
import gzip
import json
import logging
import os
import threading
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.buffered_logger import get_logger
from src.core.checkpoint_migrations import migrate_state
from src.core.paths import data_path

logger = logging.getLogger(__name__)


class CheckpointCorruptedError(Exception):
    """Raised when checkpoint file is corrupted (disk error, bit rot, truncation).
    
    This is DIFFERENT from structural drift - the agent's state has evolved normally,
    but the saved file itself is unreadable or invalid.
    """
    pass


# ============================================================
# Дефолтное имя директории чекпоинтов.
# ============================================================
DEFAULT_CHECKPOINT_DIR = "data/checkpoints"


# ============================================================
# Построение / применение state-словаря
# ============================================================
def build_state_from_agent(agent) -> Dict[str, Any]:
    """Собрать словарь state из агента.

    Args:
        agent: экземпляр DigitalBeing.

    Returns:
        Словарь, готовый для сериализации в JSON.
    """
    from src.core.checkpoint_migrations import SCHEMA_VERSION
    from src.core.personal_continuity import capture_personal_state
    from src.cognition.inference_continuity import capture_inference

    return {
        "personal_state": capture_personal_state(agent),
        "active_inference": (
            capture_inference(agent.active_inference)
            if getattr(agent, "active_inference", None) is not None else None
        ),
        "schema_version": SCHEMA_VERSION,
        **({"life_id": agent.life_id} if getattr(agent, "life_id", None) else {}),
        "name": agent.name,
        "energy": agent.energy,
        "cycle_count": agent.cycle_count,
        "knowledge_base": agent.knowledge_base,
        # Память и тело относятся к одному моменту сохранения. Отдельный
        # mind/mental_models.json — экспорт, а не источник поверх чекпоинта.
        "mental_models": (
            agent.mental_models.to_storage_dict()
            if getattr(agent, "mental_models", None) is not None else None
        ),
        "intelligence": agent.intelligence,
        "completed_goals": agent.completed_goals,
        "goals": agent.goals,
        "active_goal": agent.active_goal["title"] if agent.active_goal else None,
        "success_streak": agent.success_streak,
        "saved_at": datetime.now().isoformat(),
        # Цели и самоконтроль
        "_goal_progress": {
            k: {
                "matched_concepts": list(v.get("matched_concepts", [])),
                "percentage": int(v.get("percentage", 0)),
                "last_update_cycle": int(v.get("last_update_cycle", 0)),
            }
            for k, v in agent._goal_progress.items()
        },
        "_learned_facts": list(agent._learned_facts),
        "_known_definitions": agent._known_definitions,
        # Имя (сохраняем фазу, чтобы после рестарта не здороваться повторно)
        "naming_dialogue_phase": getattr(agent.naming_dialogue, "phase", "none"),
        "naming_dialogue_history": getattr(agent.naming_dialogue, "_name_history", []),
        # Открытые вопросы (метаданные + краткий explorations_count)
        "open_questions": [
            {
                "text": q["text"],
                "source": q["source"],
                "started_at": q["started_at"],
                "last_explored_at": q["last_explored_at"],
                "explorations_count": len(q["explorations"]),
                "explorations": [dict(entry) for entry in q["explorations"]],
                "max_explorations": q["max_explorations"],
                "hint": q.get("hint"),
                "answered": q["answered"],
                "answer": q["answer"],
            }
            for q in getattr(agent, "_open_questions", [])
        ],
        # «Собеседник-2»: убеждения о человеке. Без них после рестарта
        # сущность забывает обещания («не переживай, если молчу»).
        "user_model": (
            agent.user_model.to_dict()
            if getattr(agent, "user_model", None) is not None else None
        ),
        # «Собеседник-3»: штампы «тема объяснена пользователем в цикле N».
        # После рестарта сущность не переспрашивает объяснённое.
        "user_explained_topics": dict(
            getattr(agent, "_user_explained_topics", {}) or {}
        ),
        # «Собеседник-4»: темы, уже рассказанные человеку, — после
        # рестарта сущность не начинает повторяться.
        "shared_topics": dict(
            getattr(agent, "_shared_topics", {}) or {}
        ),
        # «Собеседник»: диалоговое состояние — история вопросов-ответов
        # и ожидающие вопросы с полями цепочек сложных вопросов. Без
        # них после рестарта сущность забывает разговор, а синтез
        # цепочки ломается на середине.
        "user_interaction": (
            agent.user_interaction.to_checkpoint_dict()
            if getattr(agent, "user_interaction", None) is not None
            else None
        ),
        # NEW: Интероцепция
        "interoception": getattr(agent, 'interoception', None) and {
            "glucose": agent.interoception.state.glucose,
            "atp": agent.interoception.state.atp,
            "mitochondrial_health": agent.interoception.state.mitochondrial_health,
            "fatigue": agent.interoception.state.fatigue,
            "action_cost_multiplier": agent.interoception.state.action_cost_multiplier,
            "cognitive_throughput": agent.interoception.state.cognitive_throughput,
            "exploration_drive": agent.interoception.state.exploration_drive,
        } or {},
        # NEW: Непрерывное время
        "continuous_time": getattr(agent, 'continuous_time', None) and {
            "total_objective_time": agent.continuous_time.total_objective_time,
            "total_subjective_time": agent.continuous_time.total_subjective_time,
            "subjective_time_dilation": agent.continuous_time.subjective_time.dilation,
        } or {},
        # NEW: Мета-обучение
        "meta_learning": getattr(agent, 'meta_learner', None) and {
            "current_config": agent.meta_learner._get_current_config(),
            "current_fitness": agent.meta_learner.fitness_history[-1] if agent.meta_learner.fitness_history else 0.0,
            "best_config": agent.meta_learner.best_config,
            "best_fitness": (
                agent.meta_learner.best_fitness
                if agent.meta_learner.best_fitness != float("-inf") else None
            ),
            "population": agent.meta_learner.population,
            "cycle_counter": agent.meta_learner.cycle_counter,
        } or {},
        # NEW: Социальная клеточка
        "social_cell": getattr(agent, 'social_cell', None) and {
            "agent_models": {
                agent_id: {
                    "agent_id": model.agent_id,
                    "tom_level": int(model.tom_level),
                    "believed_goals": model.believed_goals,
                    "believed_beliefs": model.believed_beliefs,
                    "believed_intentions": model.believed_intentions,
                    "believed_emotional_state": model.believed_emotional_state,
                    "believed_model_of_self": model.believed_model_of_self,
                    "model_precision": model.model_precision,
                    "interaction_history": list(model.interaction_history)[-10:],
                }
                for agent_id, model in agent.social_cell.agent_models.items()
            },
            "self_model_as_seen_by_others": agent.social_cell.self_model_as_seen_by_others,
            "current_tom_level": int(agent.social_cell.current_tom_level),
        } or {},
        # NEW: Риск смерти
        "death_risk": getattr(agent, 'death_risk', None) and {
            "cognitive_coherence": agent.death_risk.integrity.cognitive_coherence,
            "memory_consistency": agent.death_risk.integrity.memory_consistency,
            "value_stability": agent.death_risk.integrity.value_stability,
            "metabolic_viability": agent.death_risk.integrity.metabolic_viability,
            "social_coherence": agent.death_risk.integrity.social_coherence,
            "corruption_accumulator": agent.death_risk.integrity.corruption_accumulator,
            "last_checkpoint_step": agent.death_risk.integrity.last_checkpoint_step,
            "checkpoints": [
                {
                    "timestamp": cp.timestamp,
                    "step": cp.step,
                    "structural_hash": cp.structural_hash,
                    "cognitive_state_hash": cp.cognitive_state_hash,
                    "memory_hash": cp.memory_hash,
                    "personality_hash": cp.personality_hash,
                    "integrity_score": cp.integrity_score,
                }
                for cp in agent.death_risk.integrity.checkpoints[-5:]  # последние 5
            ],
        } or {},
        # NEW: Unified Motivation (needs + drives)
        "motivation": getattr(agent, 'motivation_system', None) and agent.motivation_system.to_checkpoint_dict() or {},
        # Замыкание петли: тупики не должны исчезать после рестарта,
        # иначе агент снова начнёт повторять бесполезное действие.
        "loop_closure": (
            agent.loop_closer.to_checkpoint_dict()
            if getattr(agent, "loop_closer", None) is not None
            else {}
        ),
        # Изученные темы: чтобы исследование продолжалось, а не начиналось
        # с той же концепции после перезапуска.
        "creative_catalog": deepcopy(getattr(agent, "_creative_catalog", {})),
        "creative_draft": deepcopy(getattr(agent, "_creative_draft", None)),
        "local_play": deepcopy(getattr(agent, "_local_play", None)),
        "waiting_intentions": deepcopy(getattr(agent, "_waiting_intentions", {})),
        "method_preferences": deepcopy(getattr(agent, "_method_preferences", {})),
        "intention_history": deepcopy(getattr(agent, "_intention_history", [])),
        "pending_user_messages": list(getattr(agent, "_pending_message_texts", []) or []),
        "deferred_stimulus": getattr(agent, "_deferred_stimulus", None),
        "method_information_context": getattr(agent, "_method_information_context", None),
        "last_experiment_cycle": getattr(agent, "_last_experiment_cycle", None),
        "exploration_history": list(
            getattr(agent, "_exploration_history", [])[-200:]
        ),
        # Отметки рождения: без них после рестарта нельзя отличить
        # нажитое от родового, и оценка зрелости станет невозможной.
        "birth_concepts": getattr(agent, "_birth_concepts", None),
        "birth_defined": getattr(agent, "_birth_defined", None),
        "birth_values": list(getattr(agent, "_birth_values", []) or []),
        # Сон: счётчик проходов консолидации и недонакопленный материал.
        # Без этого после перезапуска «сколько раз агент осмыслял
        # накопленное» начиналось бы с нуля, а недоспанные единицы
        # терялись бы.
        "consolidation": {
            "count": int(getattr(agent, "_consolidation_count", 0)),
            "sleep_units": float(getattr(agent, "_sleep_units", 0.0)),
        },
    }


def apply_state_to_agent(agent, state: Dict[str, Any]) -> None:
    """Восстановить состояние агента из state-словаря.

    Args:
        agent: экземпляр DigitalBeing.
        state: словарь, полученный из ``build_state_from_agent``.
    """
    from src.core.checkpoint_validation import validate_checkpoint_state

    validate_checkpoint_state(state)
    inference_data = state.get("active_inference")
    if inference_data is not None:
        from src.cognition.inference_continuity import validate_inference

        if getattr(agent, "active_inference", None) is None:
            raise ValueError("active_inference: подсистема недоступна для восстановления")
        validate_inference(inference_data, agent.active_inference)
    saved_models = state.get("mental_models")
    if saved_models is not None and getattr(agent, "mental_models", None) is not None:
        from src.cognition.mental_models import ConceptNode

        # Сначала разобрать всё; повреждённая секция не должна частично
        # подменить память уже созданного существа.
        restored_nodes = {
            name: ConceptNode.from_dict({**raw, "name": name})
            for name, raw in saved_models["concepts"].items()
        }
        from src.cognition.empirical_claims import EmpiricalClaim

        restored_claims = {
            key: EmpiricalClaim.from_dict(raw)
            for key, raw in (saved_models.get("claims") or {}).items()
        }
        model = agent.mental_models
        model.claims = restored_claims
        model.concepts = restored_nodes
        model.name = saved_models.get("name", model.name)
        model.metadata = dict(saved_models.get("metadata") or {})
        model.association_memory = list(saved_models.get("recent_associations") or [])
        model._related_cache.clear()
        model._cycle_counter = state.get("cycle_count", 0)
    for marker in ("_last_soul_tick_cycle", "_last_will_tick_cycle", "_last_communication_tick_cycle"):
        if hasattr(agent, marker):
            setattr(agent, marker, None)
    # Прежняя незавершённая попытка не является наблюдением. Следующее
    # ожидание строится из восстановленного опыта, а не из pending trial.
    if hasattr(agent, "action_expectations"):
        from src.cognition.action_expectations import ActionExpectations

        agent.action_expectations = ActionExpectations()

    if "life_id" in state:
        agent.life_id = state["life_id"]
        # Прямое legacy-использование DigitalBeing хранит память по имени:
        # UUID в снимке не должен переключать её на другой файл.
        if getattr(agent, "_profile_managed", False):
            memory = getattr(agent, "long_term_memory", None)
            if memory is None:
                # Рождение само по себе память не теряет: None здесь значит,
                # что чтение UUID-файла не удалось. Не выдаём это за пустоту.
                raise ValueError("Память жизни недоступна; восстановление остановлено")
            if getattr(memory, "life_id", None) != agent.life_id:
                # Объект памяти не заменяем: на него уже ссылаются sleep_cycle
                # и другие подсистемы, созданные при рождении агента.
                memory.rebind(agent.life_id)
    if isinstance(state.get("name"), str):
        agent.name = state["name"]
    agent.energy = state.get("energy", 150)
    agent.cycle_count = state.get("cycle_count", 0)
    agent.knowledge_base.update(state.get("knowledge_base", {}))
    agent.intelligence = state.get("intelligence", 1)
    agent.completed_goals = state.get("completed_goals", 0)
    agent.goals = state.get("goals", agent.goals)
    agent.success_streak = state.get("success_streak", 0)

    active_goal_title = state.get("active_goal")
    if active_goal_title:
        for goal in agent.goals:
            if goal["title"] == active_goal_title:
                agent.active_goal = goal
                break

    # Восстанавливаем прогресс по целям
    gp_data = state.get("_goal_progress", {})
    for k, v in gp_data.items():
        goal_id = int(k) if isinstance(k, str) else k
        if isinstance(v, dict):
            matched = v.get("matched_concepts", [])
            percentage = int(v.get("percentage", 0))
            last_cycle = int(v.get("last_update_cycle", agent.cycle_count))
        else:
            # Старый формат: только список совпавших тем.
            matched = v
            percentage = 0
            last_cycle = agent.cycle_count
        agent._goal_progress[goal_id] = {
            "matched_concepts": set(matched or []),
            "percentage": percentage,
            "last_update_cycle": last_cycle,
        }

    # GoalSubsystem хранит те же цели/прогресс. После загрузки чекпоинта
    # списки могли разъехаться — синхронизируем, иначе complete_goal()
    # будет менять старый список и счётчик.
    if hasattr(agent, "goal_subsystem"):
        agent.goal_subsystem.goals = agent.goals
        agent.goal_subsystem.active_goal = agent.active_goal
        agent.goal_subsystem.completed_goals = agent.completed_goals
        agent.goal_subsystem._goal_progress = agent._goal_progress

    # Замыкание петли: восстанавливаем счётчики тупиков и историю
    # исследования, чтобы после рестарта не повторять бесполезное действие
    # и не изучать ту же тему заново.
    if getattr(agent, "loop_closer", None) is not None:
        agent.loop_closer.restore_from_checkpoint(state.get("loop_closure"))
    from src.cognition.intention_history import restore_history

    agent._creative_catalog = deepcopy(state.get("creative_catalog", {}))
    agent._creative_draft = deepcopy(state.get("creative_draft"))
    agent._local_play = deepcopy(state.get("local_play"))
    agent._waiting_intentions = deepcopy(state.get("waiting_intentions", {}))
    from src.cognition.method_preferences import validate as validate_method_preferences

    validate_method_preferences(state.get("method_preferences", {}))
    agent._method_preferences = deepcopy(state.get("method_preferences", {}))
    agent._intention_history = restore_history(state.get("intention_history", []))
    agent._pending_message_texts = list(state.get("pending_user_messages", []))
    agent._deferred_stimulus = state.get("deferred_stimulus")
    agent._method_information_context = state.get("method_information_context")
    last_experiment = state.get("last_experiment_cycle")
    agent._last_experiment_cycle = last_experiment if isinstance(last_experiment, int) and 0 <= last_experiment <= agent.cycle_count else None
    saved_history = state.get("exploration_history")
    if isinstance(saved_history, list):
        agent._exploration_history = [str(item) for item in saved_history]

    # Сон: счётчик консолидаций и недонакопленный материал.
    saved_sleep = state.get("consolidation")
    if isinstance(saved_sleep, dict):
        count = saved_sleep.get("count")
        if isinstance(count, (int, float)) and count >= 0:
            agent._consolidation_count = int(count)
        units = saved_sleep.get("sleep_units")
        if isinstance(units, (int, float)) and units >= 0:
            agent._sleep_units = float(units)

    # Отметки рождения: восстанавливаем как есть. Если в чекпоинте их нет
    # (старый формат), оставляем текущие — но не выдумываем нули.
    saved_birth = state.get("birth_concepts")
    if isinstance(saved_birth, int) and saved_birth >= 0:
        agent._birth_concepts = saved_birth
    saved_birth_defined = state.get("birth_defined")
    if isinstance(saved_birth_defined, int) and saved_birth_defined >= 0:
        agent._birth_defined = saved_birth_defined
    saved_birth_values = state.get("birth_values")
    if isinstance(saved_birth_values, list):
        agent._birth_values = [str(item) for item in saved_birth_values]

    agent._learned_facts = set(state.get("_learned_facts", []))
    agent._known_definitions.update(state.get("_known_definitions", {}))

    # Восстанавливаем фазу naming-диалога
    if hasattr(agent, "naming_dialogue"):
        saved_phase = state.get("naming_dialogue_phase")
        if saved_phase:
            agent.naming_dialogue.phase = saved_phase
        saved_history = state.get("naming_dialogue_history") or []
        if saved_history:
            existing = list(getattr(agent.naming_dialogue, "_name_history", []))
            agent.naming_dialogue._name_history = list(saved_history) + existing

    # «Собеседник-2»: убеждения о человеке переживают рестарт —
    # обещания («не переживай, если молчу») не забываются.
    saved_user_model = state.get("user_model")
    if (
        isinstance(saved_user_model, dict)
        and getattr(agent, "user_model", None) is not None
    ):
        agent.user_model.load_from(saved_user_model)

    # «Собеседник-3»: штампы объяснённых тем переживают рестарт.
    saved_explained = state.get("user_explained_topics")
    if isinstance(saved_explained, dict) and hasattr(
        agent, "_user_explained_topics"
    ):
        restored = {}
        for topic, cycle in list(saved_explained.items())[:50]:
            if isinstance(cycle, (int, float)) and not isinstance(cycle, bool):
                restored[str(topic)] = int(cycle)
        agent._user_explained_topics = restored

    # «Собеседник-4»: память «что уже рассказано» переживает рестарт.
    saved_shared = state.get("shared_topics")
    if isinstance(saved_shared, dict) and hasattr(agent, "_shared_topics"):
        restored_shared = {}
        for topic, cycle in list(saved_shared.items())[:50]:
            if isinstance(cycle, (int, float)) and not isinstance(cycle, bool):
                restored_shared[str(topic)] = int(cycle)
        agent._shared_topics = restored_shared

    # «Собеседник»: диалоговое состояние переживает рестарт — сущность
    # помнит разговор, ожидающие вопросы дожидаются ответа, а цепочка
    # сложного вопроса продолжается с места остановки.
    saved_interaction = state.get("user_interaction")
    if (
        isinstance(saved_interaction, dict)
        and getattr(agent, "user_interaction", None) is not None
    ):
        agent.user_interaction.restore_from_checkpoint(saved_interaction)

    # История попыток нужна для продолжения стратегии, а не нового старта.
    saved_questions = state.get("open_questions") or []
    if "open_questions" in state and hasattr(agent, "_open_questions"):
        agent._open_questions.clear()
        for q_data in saved_questions:
            agent._open_questions.append({
                "text": q_data.get("text", ""),
                "source": q_data.get("source", "user"),
                "started_at": q_data.get("started_at", agent.cycle_count),
                "last_explored_at": q_data.get(
                    "last_explored_at", agent.cycle_count
                ),
                "explorations": [dict(entry) for entry in q_data.get("explorations", [])],
                "max_explorations": q_data.get("max_explorations", 5),
                "hint": q_data.get("hint"),
                "answered": q_data.get("answered", False),
                "answer": q_data.get("answer"),
            })
        if agent._open_questions:
            get_logger().flush_immediate(
                f"[OpenQ] Восстановлено {len(agent._open_questions)} открытых вопросов"
            )
    
    # NEW: Восстанавливаем Интероцепцию
    intero_state = state.get("interoception", {})
    if intero_state and hasattr(agent, 'interoception') and agent.interoception:
        s = agent.interoception.state
        s.glucose = intero_state.get("glucose", s.glucose)
        s.atp = intero_state.get("atp", s.atp)
        s.mitochondrial_health = intero_state.get("mitochondrial_health", s.mitochondrial_health)
        s.fatigue = intero_state.get("fatigue", s.fatigue)
        s.action_cost_multiplier = intero_state.get("action_cost_multiplier", s.action_cost_multiplier)
        s.cognitive_throughput = intero_state.get("cognitive_throughput", s.cognitive_throughput)
        s.exploration_drive = intero_state.get("exploration_drive", s.exploration_drive)
        # Пересчитываем производные величины без проживания ещё одного
        # такта: раньше здесь вызывался step(), и загрузка чекпоинта
        # тратила глюкозу и АТФ.
        agent.interoception._refresh_derived()
    
    # NEW: Восстанавливаем Непрерывное время
    ct_state = state.get("continuous_time", {})
    if ct_state and hasattr(agent, 'continuous_time') and agent.continuous_time:
        agent.continuous_time.total_objective_time = ct_state.get("total_objective_time", 0.0)
        agent.continuous_time.total_subjective_time = ct_state.get("total_subjective_time", 0.0)
        if hasattr(agent.continuous_time, 'subjective_time'):
            agent.continuous_time.subjective_time.dilation = ct_state.get("subjective_time_dilation", 1.0)
    
    # NEW: Восстанавливаем Мета-обучение
    ml_state = state.get("meta_learning", {})
    if ml_state and hasattr(agent, 'meta_learner') and agent.meta_learner:
        # Применяем сохраненную конфигурацию к гиперпараметрам
        saved_config = ml_state.get("current_config", {})
        for name, value in saved_config.items():
            if name in agent.meta_learner.hyperparams:
                agent.meta_learner.hyperparams[name].value = value
        agent.meta_learner.best_config = ml_state.get("best_config", agent.meta_learner.best_config)
        if ml_state.get("best_fitness") is not None:
            agent.meta_learner.best_fitness = ml_state["best_fitness"]
        agent.meta_learner.population = ml_state.get("population", agent.meta_learner.population)
        agent.meta_learner.cycle_counter = ml_state.get("cycle_counter", agent.meta_learner.cycle_counter)
    
    # NEW: Восстанавливаем Социальную клеточку
    sc_state = state.get("social_cell", {})
    if sc_state and hasattr(agent, 'social_cell') and agent.social_cell:
        from src.core.social_cell import AgentModel, ToMLevel
        for agent_id, model_data in sc_state.get("agent_models", {}).items():
            model = AgentModel(agent_id=model_data.get("agent_id", agent_id))
            model.tom_level = ToMLevel(model_data.get("tom_level", 1))
            model.believed_goals = model_data.get("believed_goals", {})
            model.believed_beliefs = model_data.get("believed_beliefs", {})
            model.believed_intentions = model_data.get("believed_intentions", {})
            model.believed_emotional_state = model_data.get("believed_emotional_state", {})
            model.believed_model_of_self = model_data.get("believed_model_of_self", {})
            model.model_precision = model_data.get("model_precision", 0.5)
            model.interaction_history = deque(model_data.get("interaction_history", []), maxlen=200)
            agent.social_cell.agent_models[agent_id] = model
        
        agent.social_cell.self_model_as_seen_by_others = sc_state.get("self_model_as_seen_by_others", {})
        agent.social_cell.current_tom_level = ToMLevel(sc_state.get("current_tom_level", 2))
    
    # NEW: Восстанавливаем Риск смерти
    dr_state = state.get("death_risk", {})
    if dr_state and hasattr(agent, 'death_risk') and agent.death_risk:
        integ = agent.death_risk.integrity
        integ.cognitive_coherence = dr_state.get("cognitive_coherence", integ.cognitive_coherence)
        integ.memory_consistency = dr_state.get("memory_consistency", integ.memory_consistency)
        integ.value_stability = dr_state.get("value_stability", integ.value_stability)
        integ.metabolic_viability = dr_state.get("metabolic_viability", integ.metabolic_viability)
        integ.social_coherence = dr_state.get("social_coherence", integ.social_coherence)
        integ.corruption_accumulator = dr_state.get("corruption_accumulator", integ.corruption_accumulator)
        integ.last_checkpoint_step = dr_state.get("last_checkpoint_step", integ.last_checkpoint_step)
        # Чекпоинты не восстанавливаем полностью - только хеши для верификации
        # Они будут пересозданы при следующих шагах


    # NEW: Unified Motivation (needs + drives)
    mot_state = state.get("motivation", {})
    if mot_state and hasattr(agent, 'motivation_system') and agent.motivation_system:
        from src.core.motivation.unified_motivation import UnifiedMotivationSystem
        agent.motivation_system = UnifiedMotivationSystem.from_checkpoint_dict(agent, mot_state)

    if inference_data is not None:
        from src.cognition.inference_continuity import restore_inference

        restore_inference(agent.active_inference, inference_data)
    if "personal_state" in state:
        from src.core.personal_continuity import restore_personal_state

        restore_personal_state(agent, state["personal_state"])

# ============================================================
# Сериализатор (I/O)
# ============================================================
class CheckpointSerializer:
    """Сохраняет/загружает состояние агента в JSON-файлы.

    Файлы лежат в ``<checkpoint_dir>/<agent_name>_cycle_<N>.json``
    (или ``.json.gz`` если включено gzip-сжатие).
    При превышении лимита старые чекпоинты удаляются.

    Поддержка gzip:
    - При ``compress=True`` файлы сохраняются как ``.json.gz`` с уровнем 6.
    - Сжатие типично уменьшает размер на 60-80% (на больших knowledge_base).
    - Загрузчик автоматически определяет формат по расширению файла.
    - Старые ``.json`` файлы читаются без изменений (обратная совместимость).
    """

    # Процессный lock на сохранение: два параллельных save (например,
    # завершающий runner.stop() и повторный при выходе) не должны
    # гоняться за один и тот же tmp/replace и прунинг старых чекпоинтов.
    _save_lock = threading.Lock()

    def __init__(
        self,
        checkpoint_dir: str = None,
        max_checkpoints: int = 20,
        compress: bool = False,
        compress_level: int = 6,
        backend: str = "json",
    ) -> None:
        """
        Args:
            checkpoint_dir: директория для чекпоинтов.
            max_checkpoints: максимум файлов на диске.
            compress: использовать ли gzip-сжатие (Этап 5 оптимизации).
            compress_level: уровень сжатия 1-9 (по умолчанию 6 — хороший баланс).
        """
        if backend not in {"json", "sqlite"}:
            raise ValueError("Неизвестный backend чекпоинтов")
        self.backend = backend
        self.checkpoint_dir = checkpoint_dir or data_path("checkpoints")
        self.max_checkpoints = max_checkpoints
        self.compress = compress
        self.compress_level = max(1, min(9, compress_level))

    # ---------------- Сохранение ----------------

    def save(self, state: Dict[str, Any], agent_name: str, cycle_count: int) -> str:
        """Сохранить state в файл.

        Args:
            state: словарь (результат ``build_state_from_agent``).
            agent_name: имя агента (для имени файла).
            cycle_count: текущий номер цикла (для имени файла и сортировки).

        Returns:
            Полный путь к сохранённому файлу.
        """
        with CheckpointSerializer._save_lock:
            return self._save_locked(state, agent_name, cycle_count)

    def _save_locked(self, state: Dict[str, Any], agent_name: str, cycle_count: int) -> str:
        """Тело ``save()`` под процессным lock (см. ``_save_lock``)."""
        if self.backend == "sqlite":
            from src.memory.checkpoint_store import SQLiteCheckpointStore

            database = os.path.abspath(os.path.join(self.checkpoint_dir, "life.sqlite3"))
            snapshot_id = SQLiteCheckpointStore(database).save(
                json.loads(json.dumps(state, ensure_ascii=False, allow_nan=False)),
                agent_name, cycle_count, max_checkpoints=self.max_checkpoints,
            )
            return f"{database}#snapshot={snapshot_id}"
        import tempfile

        os.makedirs(self.checkpoint_dir, exist_ok=True)
        filename = self._checkpoint_path(agent_name, cycle_count)
        json_text = json.dumps(state, indent=2, ensure_ascii=False)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=os.path.dirname(filename),
                prefix=f".{os.path.basename(filename)}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = temporary_file.name
            if self.compress:
                with gzip.open(temporary_path, "wt", encoding="utf-8", compresslevel=self.compress_level) as f:
                    f.write(json_text)
            else:
                with open(temporary_path, "w", encoding="utf-8") as f:
                    f.write(json_text)
            os.replace(temporary_path, filename)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    os.remove(temporary_path)
                except FileNotFoundError:
                    pass

        self._prune_old_checkpoints(agent_name)

        get_logger().flush_immediate(
            f"Состояние сохранено: {os.path.basename(filename)}"
        )
        return filename

    # ---------------- Загрузка ----------------

    def load(self, checkpoint_file: str) -> Optional[Dict[str, Any]]:
        """Загрузить state из файла с применением миграций.

        Автоматически определяет формат по расширению:
        - ``.json.gz`` — gzip-сжатый JSON (Этап 5)
        - ``.json`` — обычный JSON (обратная совместимость)

        Args:
            checkpoint_file: путь к файлу чекпоинта.

        Returns:
            Словарь state или ``None``, если файл не найден.
            
        Raises:
            CheckpointCorruptedError: если файл чекпоинта повреждён (невалидный JSON, 
                отсутствуют обязательные поля и т.д.)
        """
        checkpoint_file = str(checkpoint_file)
        if "#snapshot=" in checkpoint_file:
            from src.memory.checkpoint_store import SQLiteCheckpointStore

            database, snapshot_id = checkpoint_file.rsplit("#snapshot=", 1)
            if not os.path.isfile(database):
                return None
            try:
                state = SQLiteCheckpointStore(database).load(int(snapshot_id))
            except (ValueError, KeyError) as exc:
                raise CheckpointCorruptedError(f"Повреждён снимок SQLite: {exc}") from exc
            return migrate_state(state)
        if not os.path.exists(checkpoint_file):
            logger.warning(f"Чекпоинт не найден: {checkpoint_file}")
            return None

        # P0.3: Verify file integrity BEFORE parsing (catches corruption early)
        file_verification = self._verify_checkpoint_file_integrity(checkpoint_file)
        if file_verification.get('file_corrupted', False):
            raise CheckpointCorruptedError(
                f"Checkpoint file corrupted: {file_verification.get('reason')} "
                f"(path: {file_verification.get('path')})"
            )

        is_gzip = checkpoint_file.endswith(".gz")
        try:
            if is_gzip:
                with gzip.open(checkpoint_file, "rt", encoding="utf-8") as f:
                    state = json.load(f)
            else:
                with open(checkpoint_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
        except (json.JSONDecodeError, OSError, gzip.BadGzipFile) as e:
            # Should not happen since we verified above, but defense in depth
            logger.exception(f"Ошибка чтения чекпоинта {checkpoint_file}: {e}")
            raise CheckpointCorruptedError(f"Failed to parse checkpoint: {e}")

        # Применяем миграции (no-op если версия актуальна)
        state = migrate_state(state)
        return state

    def _verify_checkpoint_file_integrity(self, checkpoint_file: str) -> Dict:
        """Verify checkpoint FILE integrity (readable, valid JSON, required fields).
        
        This is a lightweight check that doesn't require an agent instance.
        """
        try:
            is_gzip = checkpoint_file.endswith(".gz")
            if is_gzip:
                with gzip.open(checkpoint_file, "rt", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                with open(checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            
            # Verify required fields exist
            required_fields = ['schema_version', 'name', 'cycle_count', 'energy']
            missing = [f for f in required_fields if f not in data]
            if missing:
                return {'file_corrupted': True, 'reason': f'missing_fields: {missing}', 'path': checkpoint_file}
            
            return {'file_corrupted': False, 'path': checkpoint_file}
        except (json.JSONDecodeError, gzip.BadGzipFile, OSError, UnicodeDecodeError) as e:
            return {'file_corrupted': True, 'reason': str(e), 'path': checkpoint_file}

    def load_latest(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """Загрузить последний чекпоинт агента (по номеру цикла).

        Args:
            agent_name: имя агента.

        Returns:
            Словарь state или ``None``, если чекпоинтов нет.
        """
        path = self.get_latest_path(agent_name)
        if not path:
            return None
        return self.load(path)

    def apply_to_agent(self, agent, state: Dict[str, Any], checkpoint_path: Optional[str] = None) -> None:
        """Применить state к агенту (обёртка над ``apply_state_to_agent``).
        
        Args:
            agent: агент для восстановления
            state: словарь состояния
            checkpoint_path: путь к файлу чекпоинта (для верификации целостности файла)
        """
        # NEW: Verify checkpoint FILE integrity before applying (P0.3)
        # This detects actual file corruption (disk errors, bit rot), NOT structural drift
        if checkpoint_path and hasattr(agent, 'death_risk') and agent.death_risk:
            file_verification = agent.death_risk.verify_checkpoint_file_integrity(checkpoint_path)
            if file_verification.get('file_corrupted', False):
                raise CheckpointCorruptedError(
                    f"Checkpoint file corrupted: {file_verification.get('reason')} "
                    f"(path: {file_verification.get('path')})"
                )
        
        apply_state_to_agent(agent, state)

    # ---------------- Поиск/служебные ----------------

    def get_latest_path(self, agent_name: str) -> Optional[str]:
        """Путь к самому свежему чекпоинту агента. None если нет.

        Поддерживает и ``.json``, и ``.json.gz`` (Этап 5: gzip).
        """
        if not os.path.exists(self.checkpoint_dir):
            return None
        prefix = f"{agent_name}_cycle_"
        checkpoints = [
            f for f in os.listdir(self.checkpoint_dir)
            if f.startswith(prefix)
            and (f.endswith(".json") or f.endswith(".json.gz"))
        ]
        if not checkpoints:
            return None
        checkpoints.sort(
            key=lambda x: int(_extract_cycle_number(x, prefix))
        )
        return os.path.join(self.checkpoint_dir, checkpoints[-1])

    def list_checkpoints(self, agent_name: str) -> List[str]:
        """Список путей ко всем чекпоинтам агента (отсортирован по циклу).

        Поддерживает и ``.json``, и ``.json.gz``.
        """
        if not os.path.exists(self.checkpoint_dir):
            return []
        prefix = f"{agent_name}_cycle_"
        files = [
            f for f in os.listdir(self.checkpoint_dir)
            if f.startswith(prefix)
            and (f.endswith(".json") or f.endswith(".json.gz"))
        ]
        files.sort(key=lambda x: int(_extract_cycle_number(x, prefix)))
        return [os.path.join(self.checkpoint_dir, f) for f in files]

    def _checkpoint_path(self, agent_name: str, cycle_count: int) -> str:
        """Полный путь к чекпоинту.

        Если ``self.compress=True`` — расширение ``.json.gz``, иначе ``.json``.
        """
        ext = ".json.gz" if self.compress else ".json"
        return os.path.join(
            self.checkpoint_dir,
            f"{agent_name}_cycle_{cycle_count}{ext}",
        )

    def _prune_old_checkpoints(
        self, agent_name: str, keep_after_save: int = 0
    ) -> int:
        """Удалить старые чекпоинты сверх лимита.

        Args:
            agent_name: имя агента.
            keep_after_save: если > 0 — считается, что новый файл ещё не
                создан, но будет (используется в ``save()``). Прунинг
                оставляет ровно ``keep_after_save`` файлов после записи.
                Если 0 — оставляет ``max_checkpoints`` (для совместимости
                с прямым вызовом без последующего save).

        Returns:
            Количество удалённых файлов.
        """
        checkpoints = self.list_checkpoints(agent_name)
        target = keep_after_save if keep_after_save > 0 else self.max_checkpoints
        if len(checkpoints) <= target:
            return 0
        to_remove = checkpoints[:len(checkpoints) - target]
        removed = 0
        for old in to_remove:
            try:
                os.remove(old)
                removed += 1
            except OSError as e:
                logger.warning(f"Не удалось удалить {old}: {e}")
        return removed


def _extract_cycle_number(filename: str, prefix: str) -> str:
    """Извлечь номер цикла из имени файла чекпоинта.

    Поддерживает оба варианта расширения:
    - ``Alpha_cycle_42.json`` -> ``42``
    - ``Alpha_cycle_42.json.gz`` -> ``42``

    Args:
        filename: имя файла.
        prefix: префикс (например, ``Alpha_cycle_``).

    Returns:
        Строковое представление номера цикла.
    """
    rest = filename[len(prefix):]
    # Убираем .json или .json.gz
    if rest.endswith(".json.gz"):
        rest = rest[:-len(".json.gz")]
    elif rest.endswith(".json"):
        rest = rest[:-len(".json")]
    return rest


__all__ = [
    "CheckpointSerializer",
    "DEFAULT_CHECKPOINT_DIR",
    "build_state_from_agent",
    "apply_state_to_agent",
]
