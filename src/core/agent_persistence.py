"""Persistence, knowledge pruning and forgetting from ``agent.py``.

The public ``DigitalBeing`` facade keeps its signatures. Mental-model helpers
receive ``data_path`` from that facade to preserve its late-binding contract;
``save_state`` retains its original local import.
"""

import json
import os
import time
from typing import Dict

from config.simulation_config import LR_CONFIG, SIM_CONFIG
from src.core.buffered_logger import get_logger
from src.memory.knowledge_quality import REASON_TITLES, clean_knowledge_base


def save_state_impl(self, *, force=False):
    """Сохранение состояния (умные чекпоинты).

    Этап 2.3: state.json содержит поле schema_version. При изменении
    структуры state нужно поднять ``SCHEMA_VERSION`` в
    ``src/core/checkpoint_migrations.py`` и написать миграцию.

    Этап 4.5: фактическая сериализация и прунинг вынесены в
    ``src.core.checkpoint_serializer`` (фасад).
    """
    should_save = bool(force)

    # 1. Сохраняем при эволюции
    if (
        SIM_CONFIG.SAVE_ON_EVOLUTION
        and self.intelligence > self._last_saved_intelligence
    ):
        should_save = True

    # 2. Сохраняем по интервалу
    if self.cycle_count % SIM_CONFIG.CHECKPOINT_INTERVAL == 0:
        should_save = True

    if not should_save:
        return

    from src.core.checkpoint_serializer import (
        CheckpointSerializer,
        build_state_from_agent,
    )

    state = build_state_from_agent(self)
    from pathlib import Path
    from src.core.paths import data_path

    directory = getattr(self, "checkpoint_dir", None)
    storage_key = self.name
    backend = getattr(SIM_CONFIG, "CHECKPOINT_BACKEND", "sqlite")
    if getattr(self, "_profile_managed", False):
        if backend == "sqlite":
            directory = str(data_path("lives", self.life_id))
        else:
            directory = str(Path(directory or data_path("checkpoints")) / self.life_id)
        storage_key = self.life_id
    mirror_path = None
    mirror_life_id = None
    if backend != "sqlite" and getattr(SIM_CONFIG, "CHECKPOINT_SQLITE_MIRROR", False):
        if not getattr(self, "_profile_managed", False):
            raise ValueError("SQLite-зеркало разрешено только для жизни с UUID")
        mirror_path = data_path("lives", self.life_id, "life.sqlite3")
        mirror_life_id = self.life_id
    ser = CheckpointSerializer(
        checkpoint_dir=directory,
        max_checkpoints=SIM_CONFIG.MAX_CHECKPOINTS,
        backend=getattr(SIM_CONFIG, "CHECKPOINT_BACKEND", "sqlite"),
        sqlite_mirror_path=mirror_path,
        sqlite_mirror_life_id=mirror_life_id,
    )
    filename = ser.save(state, storage_key, self.cycle_count)
    if getattr(self, "_profile_managed", False):
        memory = getattr(self, "long_term_memory", None)
        if memory is not None:
            # Снимок Core не сериализует LongTermMemory: сохраняем её таблицы
            # при каждом успешном checkpoint, включая штатное завершение.
            memory.save()

    self._last_saved_intelligence = self.intelligence
    return filename


def capture_structural_state_impl(self) -> Dict:
    """
    Захватывает текущее структурное состояние агента для чекпоинта.

    Возвращает хеши ключевых компонентов для верификации целостности.
    """
    import hashlib
    import json

    # Структурный хеш: архитектура, параметры, топология
    structural_data = {
        "intelligence": self.intelligence,
        "cycle_count": self.cycle_count,
        "energy": self.energy,
        "goals_count": len(self.goals),
        "completed_goals": self.completed_goals,
        "knowledge_base_size": len(self.knowledge_base),
        "beliefs": dict(getattr(self, "beliefs", {})),
        "preferences": self.preferences,
        "mental_models_concepts": list(
            getattr(self, "mental_models", {}).concepts.keys()
        )
        if hasattr(self, "mental_models")
        else [],
    }
    structural_hash = hashlib.sha256(
        json.dumps(structural_data, sort_keys=True).encode()
    ).hexdigest()[:32]

    # Когнитивный хеш: текущие убеждения, активные цели, рабочая память
    cognitive_data = {
        "active_goal": str(self.active_goal) if self.active_goal else None,
        "goals": [str(g) for g in self.goals[:10]],
        "internal_motivation": self.internal_motivation.get_status()
        if hasattr(self, "internal_motivation")
        else {},
        "active_inference_beliefs": self._active_inference_info.get("beliefs", {})
        if hasattr(self, "_active_inference_info")
        else {},
    }
    cognitive_state_hash = hashlib.sha256(
        json.dumps(cognitive_data, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]

    # Память: long-term memory + knowledge base
    memory_data = {
        "knowledge_base_keys": list(self.knowledge_base.keys())[:100],
        "ltm_size": len(getattr(self, "long_term_memory", {})._episodic)
        if hasattr(self, "long_term_memory")
        else 0,
    }
    memory_hash = hashlib.sha256(
        json.dumps(memory_data, sort_keys=True).encode()
    ).hexdigest()[:32]

    # Личность: ценности, привязанности, стиль
    personality_data = {
        "values": getattr(self, "values", {}),
        "attachment": self.attachment.get_status()
        if hasattr(self, "attachment")
        else {},
        "communication_style": getattr(self, "communication_style", "neutral"),
        "name": self.name,
    }
    personality_hash = hashlib.sha256(
        json.dumps(personality_data, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]

    # Общая целостность
    if hasattr(self, "death_risk") and hasattr(self.death_risk, "integrity"):
        integrity_score = self.death_risk.integrity.compute_overall_integrity()
    else:
        integrity_score = 1.0

    return {
        "structural_hash": structural_hash,
        "cognitive_state_hash": cognitive_state_hash,
        "memory_hash": memory_hash,
        "personality_hash": personality_hash,
        "integrity_score": integrity_score,
        "timestamp": time.time(),
        "cycle": self.cycle_count,
    }


def restore_from_checkpoint_impl(self, checkpoint) -> bool:
    """
    Восстанавливает состояние агента из чекпоинта (rollback).

    ВНИМАНИЕ: Это необратимая операция — текущее состояние теряется.
    """
    try:
        # Восстанавливаем базовые параметры
        if hasattr(checkpoint, "metadata"):
            meta = checkpoint.metadata
            self.energy = meta.get("energy", self.energy)
            self.intelligence = meta.get("intelligence", self.intelligence)

        # Восстанавливаем хеши (помечаем как восстановленные)
        self._restored_from_checkpoint = True
        self._restored_checkpoint_step = checkpoint.step

        get_logger().log(f"[RESTORE] Restored from checkpoint step {checkpoint.step}")
        return True
    except Exception as e:
        get_logger().log(f"[RESTORE] Failed to restore from checkpoint: {e}")
        return False


def perform_forgetting_impl(self):
    """Приоритетное забывание неиспользуемых концепций с низкой уверенностью."""
    if not LR_CONFIG.FORGETTING_ENABLED:
        return

    # Проверяем, пора ли забывать
    if self.cycle_count % LR_CONFIG.FORGETTING_INTERVAL != 0:
        return

    # Находим концепции для забывания (низкая уверенность + мало использования)
    to_remove = []
    for concept_name, node in list(self.mental_models.concepts.items()):
        if node.confidence < LR_CONFIG.MIN_CONFIDENCE_FOR_RETENTION:
            usage = self._concept_usage_count.get(concept_name, 0)
            if usage <= 1:  # Использовалась 0-1 раз
                to_remove.append(concept_name)

    # Не забываем больше MAX_FORGET_PCT концепций за раз
    max_forget = int(len(self.mental_models.concepts) * LR_CONFIG.MAX_FORGET_PCT / 100)
    if len(to_remove) > max_forget:
        to_remove = to_remove[:max_forget]

    if to_remove:
        for name in to_remove:
            del self.mental_models.concepts[name]
            self._concept_usage_count.pop(name, None)
        get_logger().flush_immediate(
            f"🧠 Приоритетное забывание: -{len(to_remove)} концепций (низкая уверенность)"
        )


def _prune_knowledge_base_impl(self) -> None:
    """Удаляет некачественные записи, затем прунит до лимита.

    Фильтр качества лечит базу, даже если мусор пришёл из старого
    чекпоинта или файла: запись не переживёт ближайшее сохранение.
    """
    _, removed = clean_knowledge_base(self.knowledge_base)
    if removed:
        for key in removed:
            self.knowledge_base.pop(key, None)
        preview = "; ".join(
            f"'{key}' ({REASON_TITLES.get(reason, reason)})"
            for key, reason in list(removed.items())[:5]
        )
        suffix = "" if len(removed) <= 5 else f" и ещё {len(removed) - 5}"
        get_logger().log(
            f"KB: удалено некачественных записей: {len(removed)} — {preview}{suffix}"
        )

    max_kb = SIM_CONFIG.MAX_KNOWLEDGE_BASE
    if len(self.knowledge_base) <= max_kb:
        return
    keys_to_remove = list(self.knowledge_base.keys())[
        : SIM_CONFIG.KNOWLEDGE_PRUNE_AMOUNT
    ]
    for key in keys_to_remove:
        del self.knowledge_base[key]


def _prune_knowledge_base_if_needed_impl(self) -> None:
    """Алиас для _prune_knowledge_base (для совместимости с ThinkingPipeline)."""
    self._prune_knowledge_base()


def _apply_knowledge_limits_impl(self) -> None:
    """Применяет лимиты при инициализации (вызывается из __init__)."""
    self._prune_knowledge_base()


def _load_knowledge_base_impl(self):
    """Standalone загружает JSON; managed жизнь восстанавливается из снимка."""
    if getattr(self, "_profile_managed", False):
        return
    if os.path.exists(self.knowledge_file):
        try:
            with open(self.knowledge_file, "r", encoding="utf-8") as f:
                saved_kb = json.load(f)
                cleaned, removed = clean_knowledge_base(saved_kb)
                self.knowledge_base.update(cleaned)
                message = f"База знаний загружена: {len(cleaned)} записей"
                if removed:
                    message += f", отброшено некачественных: {len(removed)}"
                get_logger().flush_immediate(message)
        except Exception as e:
            get_logger().log(f"Ошибка при загрузке базы знаний: {e}")


def _save_knowledge_base_impl(self):
    """Standalone сохраняет JSON с debounce; managed — только Core snapshot."""
    import time as _time

    self._prune_knowledge_base()
    if getattr(self, "_profile_managed", False):
        return

    now = _time.time()
    last = getattr(self, "_last_kb_save_ts", 0.0)
    debounce_sec = getattr(LR_CONFIG, "KNOWLEDGE_SAVE_DEBOUNCE_SEC", 30)
    min_delta = getattr(LR_CONFIG, "KNOWLEDGE_SAVE_MIN_DELTA", 10)
    size_delta = abs(len(self.knowledge_base) - self._last_kb_save_size)

    if (now - last) < debounce_sec and size_delta < min_delta:
        # Пропускаем запись — debounce
        return

    try:
        with open(self.knowledge_file, "w", encoding="utf-8") as f:
            json.dump(self.knowledge_base, f, indent=2, ensure_ascii=False)
        self._last_kb_save_ts = now
        self._last_kb_save_size = len(self.knowledge_base)
    except Exception as e:
        get_logger().log(f"Ошибка при сохранении БЗ: {e}")


def load_state_impl(self, checkpoint_file):
    """Восстанавливает состояние из checkpoint.

    Этап 2.3: применяет миграции из src/core/checkpoint_migrations.py
    если schema_version файла ниже текущей.

    Этап 4.5: фактическая десериализация вынесена в
    ``src.core.checkpoint_serializer`` (фасад). Логика и формат не
    изменились — старые чекпоинты читаются как раньше.
    """
    from src.core.checkpoint_serializer import (
        CheckpointSerializer,
        apply_state_to_agent,
    )

    ser = CheckpointSerializer()
    state = ser.load(checkpoint_file)
    if state is None:
        get_logger().log(
            f"[{self.name}] Не удалось загрузить чекпоинт: {checkpoint_file}"
        )
        return False
    try:
        apply_state_to_agent(self, state)
        get_logger().flush_immediate(
            f"Состояние восстановлено из {os.path.basename(checkpoint_file)}"
        )
        return True
    except Exception as e:
        get_logger().log(f"[{self.name}] Ошибка при загрузке состояния: {e}")
        return False


def save_mental_models_impl(self, filename=None, *, data_path):
    """Сохраняет ментальные модели в файл."""
    filename = filename or data_path("mind", "mental_models.json")
    try:
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                self.mental_models.to_storage_dict(), f, indent=2, ensure_ascii=False
            )
        get_logger().log(f"[{self.name}] Ментальные модели сохранены: {filename}")
    except Exception as e:
        get_logger().log(f"[{self.name}] Ошибка сохранения: {e}")


def load_mental_models_impl(self, filename=None, *, data_path):
    """Загружает ментальные модели из файла."""
    filename = filename or data_path("mind", "mental_models.json")
    try:
        if not os.path.exists(filename):
            get_logger().log(
                f"[{self.name}] Файл ментальных моделей не найден: {filename}"
            )
            return

        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        from src.cognition.mental_models import ConceptNode

        for name, node_data in data.get("concepts", {}).items():
            self.mental_models.concepts[name] = ConceptNode.from_dict(
                {**node_data, "name": name}
            )

        from src.cognition.empirical_claims import EmpiricalClaim

        self.mental_models.claims = {
            key: EmpiricalClaim.from_dict(raw)
            for key, raw in (data.get("claims") or {}).items()
        }
        self.mental_models.name = data.get("name", self.mental_models.name)
        self.mental_models.metadata.update(data.get("metadata") or {})
        self.mental_models.association_memory = data.get("recent_associations", [])
        self.mental_models._related_cache.clear()

        get_logger().log(
            f"[{self.name}] Ментальные модели загружены: {len(self.mental_models.concepts)} концепций"
        )
    except Exception as e:
        get_logger().log(f"[{self.name}] Ошибка загрузки: {e}")
