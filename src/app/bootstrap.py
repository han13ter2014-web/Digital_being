"""Сборка агента: пути, чекпоинт, семя, диалог об имени.

Раньше это было размазано по ``main.py`` и ``main_tray.py``, причём
по-разному: консоль не знала про пользовательскую папку данных, а
трей не умел проращивать семя. Здесь одна реализация для всех режимов.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from src.app.paths import AppEnv
from src.core.paths import data_path

logger = logging.getLogger(__name__)


# ============================================================
# Чекпоинты
# ============================================================


class RecoveryRequiredError(RuntimeError):
    """История существует, но безопасное восстановление не завершено."""


def _sqlite_checkpoint_candidates(database, agent_name):
    """Снимки конкретной жизни из базы, от новых к старым."""
    import sqlite3
    from contextlib import closing
    from pathlib import Path

    try:
        with closing(
            sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
        ) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            from src.memory.life_database import LifeDatabase

            if version not in (1, LifeDatabase.SCHEMA_VERSION):
                raise ValueError(f"Неподдерживаемая версия SQLite: {version}")
            ids = connection.execute(
                "SELECT id FROM snapshots WHERE agent_name = ? ORDER BY id DESC",
                (agent_name,),
            ).fetchall()
        return [f"{os.path.abspath(database)}#snapshot={row[0]}" for row in ids]
    except (sqlite3.Error, ValueError) as exc:
        raise RecoveryRequiredError(
            f"Не удалось прочитать историю {database}: {exc}"
        ) from exc


def checkpoint_candidates(agent_name: str, checkpoint_dir: Optional[str] = None):
    """Снимки от новых к старым; primary SQLite предшествует аварийному JSON."""
    import re
    from pathlib import Path
    from src.core.life_identity import validate_life_id

    directory = checkpoint_dir or data_path("checkpoints")
    candidates = []
    matched_identities = set()
    try:
        requested_id = validate_life_id(agent_name)
    except ValueError:
        requested_id = None
    primary_database = None
    if requested_id is not None:
        primary_database = data_path("lives", requested_id, "life.sqlite3")
        if os.path.isfile(primary_database):
            candidates.extend(
                _sqlite_checkpoint_candidates(primary_database, requested_id)
            )

    def extend_named(scoped, identity):
        if matched_identities and identity not in matched_identities:
            raise RecoveryRequiredError(
                "Найдено несколько жизней с одинаковым именем; выберите UUID"
            )
        if not matched_identities:
            candidates.extend(scoped)
        matched_identities.add(identity)

    children = Path(directory).iterdir() if os.path.isdir(directory) else ()
    for child in children:
        if not child.is_dir():
            continue
        try:
            identity = validate_life_id(child.name)
        except ValueError:
            continue
        if requested_id is not None and identity != requested_id:
            continue
        scoped = checkpoint_candidates(identity, str(child))
        if agent_name == identity:
            candidates.extend(scoped)
        elif scoped:
            from src.core.checkpoint_serializer import CheckpointSerializer

            try:
                latest = CheckpointSerializer().load(scoped[0])
            except Exception as exc:
                raise RecoveryRequiredError(
                    f"Не удалось прочитать профиль {identity}: {exc}"
                ) from exc
            if latest.get("name") == agent_name:
                extend_named(scoped, identity)
    if requested_id is None:
        lives = Path(data_path("lives"))
        for child in lives.iterdir() if lives.is_dir() else ():
            try:
                identity = validate_life_id(child.name)
            except ValueError:
                continue
            database = child / "life.sqlite3"
            if not database.is_file():
                continue
            scoped = _sqlite_checkpoint_candidates(database, identity)
            if scoped:
                from src.core.checkpoint_serializer import CheckpointSerializer

                try:
                    latest = CheckpointSerializer().load(scoped[0])
                except Exception as exc:
                    raise RecoveryRequiredError(
                        f"Не удалось прочитать профиль {identity}: {exc}"
                    ) from exc
                if latest.get("name") == agent_name:
                    extend_named(scoped, identity)
    database = os.path.join(directory, "life.sqlite3")
    if os.path.isfile(database) and os.path.abspath(database) != os.path.abspath(
        primary_database or ""
    ):
        candidates.extend(_sqlite_checkpoint_candidates(database, agent_name))
    pattern = re.compile(re.escape(agent_name) + r"_cycle_([0-9]+)[.]json(?:[.]gz)?$")
    files = []
    for name in os.listdir(directory) if os.path.isdir(directory) else ():
        match = pattern.fullmatch(name)
        if match and os.path.isfile(os.path.join(directory, name)):
            files.append((int(match.group(1)), name))
    candidates.extend(
        os.path.join(directory, name) for _, name in sorted(files, reverse=True)
    )
    return list(dict.fromkeys(candidates))


def latest_checkpoint(
    agent_name: str, checkpoint_dir: Optional[str] = None
) -> Optional[str]:
    """Путь к последнему чекпоинту агента или None."""
    candidates = checkpoint_candidates(agent_name, checkpoint_dir)
    return candidates[0] if candidates else None


# ============================================================
# Проращивание семени
# ============================================================


def awaken_from_seed(
    agent: Any, seed_name: str, nursery_dir: Optional[str] = None
) -> Dict[str, Any]:
    """Наполняет агента содержимым семени из Яслей.

    Наследуется: ментальные модели, ценности, идентичность,
    привязанности. НЕ наследуется: эпизодическая память и энергия —
    это даёт новому существу свободу начать свою жизнь.

    Отличие от ``examples/awaken_seed.py``: агент сохраняется на диск
    (``save_state``). Раньше скрипт печатал «РЕБЁНОК ПРОБУЖДЁН» и
    завершался — ребёнок существовал только внутри процесса.
    """
    from pathlib import Path

    root = Path(nursery_dir or data_path("nursery")).resolve()
    relative = Path(seed_name)
    if (
        relative.is_absolute()
        or relative.drive
        or len(relative.parts) != 1
        or relative.name != os.fspath(seed_name)
        or relative.parts[0] in (".", "..")
    ):
        raise ValueError("Имя семени должно быть внутри каталога Яслей")
    seed_path = (root / relative).resolve()
    if seed_path.parent != root:
        raise ValueError("Каталог семени должен быть внутри каталога Яслей")
    if not seed_path.is_dir():
        available = sorted(os.listdir(root)) if root.is_dir() else []
        raise FileNotFoundError(f"Семя не найдено: {seed_path}. Доступные: {available}")

    report: Dict[str, Any] = {
        "seed": seed_name,
        "seed_path": seed_path,
        "concepts": 0,  # всего концепций у ребёнка после прорастания
        "inherited_concepts": 0,  # сколько пришло именно из семени
        "values": [],
        "attachments": 0,
        "parent_name": None,
    }

    metadata: Dict[str, Any] = {}
    metadata_path = os.path.join(seed_path, "metadata.json")
    if os.path.isfile(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as handle:
                metadata = json.load(handle) or {}
        except (OSError, ValueError) as exc:
            logger.warning("Семя %s: metadata не прочитаны: %s", seed_name, exc)

    parent_name = metadata.get("parent_name")
    if parent_name:
        agent.parent_name = str(parent_name)
        agent.parent_seed = seed_name
        agent.parent_dream_time = metadata.get("dream_time")
        report["parent_name"] = str(parent_name)

    # --- Ментальные модели ---
    models_path = os.path.join(seed_path, "mental_models.json")
    if os.path.isfile(models_path):
        try:
            with open(models_path, "r", encoding="utf-8") as handle:
                models = json.load(handle) or {}
            from src.cognition.mental_models import ConceptNode

            inherited = 0
            for name, raw in (models.get("concepts") or {}).items():
                node = ConceptNode.from_dict({**raw, "name": name})
                agent.mental_models.concepts[name] = node
                inherited += 1
            from src.cognition.empirical_claims import EmpiricalClaim

            agent.mental_models.claims.update(
                {
                    key: EmpiricalClaim.from_dict(raw)
                    for key, raw in (models.get("claims") or {}).items()
                }
            )
            report["concepts"] = len(agent.mental_models.concepts)
            report["inherited_concepts"] = inherited
        except Exception as exc:
            logger.warning("Семя %s: mental_models: %s", seed_name, exc)

    # --- Ценности и идентичность ---
    identity_path = os.path.join(seed_path, "identity.json")
    if os.path.isfile(identity_path):
        try:
            with open(identity_path, "r", encoding="utf-8") as handle:
                identity = json.load(handle) or {}

            values = identity.get("values") or []
            if values and hasattr(agent, "value_evolution"):
                agent.value_evolution.current_values = list(values)
                report["values"] = list(values)

            core_identity = identity.get("identity") or {}
            soul = getattr(agent, "soul", None)
            if core_identity and soul is not None and soul.is_available("self"):
                core = soul.get("self")
                if core_identity.get("statement"):
                    core.core_identity = core_identity["statement"]
                if core_identity.get("stability") is not None:
                    core.identity_stability_score = float(core_identity["stability"])
        except Exception as exc:
            logger.warning("Семя %s: identity: %s", seed_name, exc)

    # --- Привязанности ---
    attachments_path = os.path.join(seed_path, "attachment.json")
    if os.path.isfile(attachments_path):
        try:
            with open(attachments_path, "r", encoding="utf-8") as handle:
                attachments = json.load(handle) or {}
            attachment_system = getattr(agent, "attachment", None)
            if attachment_system is not None:
                for name, raw in attachments.items():
                    record = attachment_system.get_or_create(name)
                    record.trust = float(raw.get("trust", 0.5))
                    record.familiarity = float(raw.get("familiarity", 0.5))
                    record.intimacy = float(raw.get("intimacy", 0.3))
                    record.valence = float(raw.get("valence", 0.0))
                    record.interactions = int(raw.get("interactions", 0))
                report["attachments"] = len(attachments)
        except Exception as exc:
            logger.warning("Семя %s: attachment: %s", seed_name, exc)

    # Сохраняем ребёнка на диск: иначе он живёт только в этом процессе.
    try:
        agent.save_state()
        agent.save_mental_models()
        report["saved"] = True
    except Exception as exc:
        logger.warning("Семя %s: сохранение не удалось: %s", seed_name, exc)
        report["saved"] = False

    logger.info(
        "Проращено семя %s: концепций=%s, ценностей=%s, привязанностей=%s",
        seed_name,
        report["concepts"],
        len(report["values"]),
        report["attachments"],
    )
    return report


# ============================================================
# Создание агента
# ============================================================


def create_agent(
    env: AppEnv,
    name: str,
    *,
    new: bool = False,
    restore: bool = True,
    seed: Optional[str] = None,
    expected_life_id: Optional[str] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """Создаёт агента и приводит его к нужному стартовому состоянию.

    Returns:
        (агент, отчёт) — отчёт описывает, откуда взялось состояние:
        новая жизнь, чекпоинт или семя.
    """
    from src.core.agent import DigitalBeing

    logger.info("Создаю агента '%s'...", name)
    os.environ["DIGITAL_BEING_DATA_DIR"] = os.path.abspath(env.data_root)
    # Выбранная жизнь должна владеть managed-хранилищами с самого
    # конструктора: поздний rebind оставляет пустую БД временного UUID.
    agent = DigitalBeing(name, life_id=expected_life_id, profile_managed=True)

    # Упакованный сид загружается только в память. Живой knowledge_base.json
    # не создаётся и не читается: источник истины — следующий Core snapshot.
    knowledge_file = os.path.join(env.data_root, "knowledge_base.json")
    bundled = os.path.join(env.base_dir, "data_bootstrap", "knowledge_base.json")
    if not os.path.isfile(bundled):
        # PyInstaller раскладывает стартовый сид в data/ внутри _MEIPASS.
        bundled = os.path.join(env.base_dir, "data", "knowledge_base.json")
    if os.path.isfile(bundled):
        try:
            with open(bundled, "r", encoding="utf-8") as handle:
                seed_knowledge = json.load(handle)
            from src.memory.knowledge_quality import clean_knowledge_base

            cleaned, _removed = clean_knowledge_base(seed_knowledge)
            agent.knowledge_base.clear()
            agent.knowledge_base.update(cleaned)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Не удалось загрузить базовую БЗ: %s", exc)

    agent.knowledge_file = knowledge_file
    agent.checkpoint_dir = os.path.join(env.data_root, "checkpoints")
    os.makedirs(agent.checkpoint_dir, exist_ok=True)

    knowledge = getattr(agent, "knowledge_subsystem", None)
    if knowledge is not None:
        knowledge.knowledge_file = knowledge_file
        knowledge._known_definitions_file = knowledge_file

    report: Dict[str, Any] = {
        "source": "new",
        "name": name,
        "checkpoint": None,
        "seed": None,
        "cycle": agent.cycle_count,
    }

    if seed:
        seed_report = awaken_from_seed(agent, seed)
        report.update(source="seed", seed=seed, seed_report=seed_report)
        report["cycle"] = agent.cycle_count
        return agent, report

    if restore and not new:
        from src.core.checkpoint_serializer import CheckpointSerializer
        from src.core.checkpoint_migrations import (
            SCHEMA_VERSION,
            CheckpointMigrationError,
        )

        checkpoint_scope = expected_life_id or name
        checkpoint_directory = agent.checkpoint_dir
        if expected_life_id:
            scoped_directory = os.path.join(agent.checkpoint_dir, expected_life_id)
            if os.path.isdir(scoped_directory):
                checkpoint_directory = scoped_directory
        candidates = checkpoint_candidates(checkpoint_scope, checkpoint_directory)
        failures = []
        for checkpoint in candidates:
            try:
                state = CheckpointSerializer().load(checkpoint)
                if not isinstance(state, dict):
                    raise ValueError("Некорректный снимок жизни")
                if expected_life_id is None and state.get("name") != name:
                    raise ValueError(
                        "Имя в старом снимке не соответствует выбранной жизни"
                    )
                if (
                    expected_life_id is not None
                    and state.get("life_id") != expected_life_id
                ):
                    raise RecoveryRequiredError(
                        "Идентификатор снимка не соответствует выбранной жизни"
                    )
                if state.get("schema_version", 0) > SCHEMA_VERSION:
                    raise RecoveryRequiredError(
                        "Снимок создан более новой версией программы"
                    )
                from src.core.checkpoint_validation import validate_checkpoint_state

                validate_checkpoint_state(state)
            except RecoveryRequiredError:
                raise
            except CheckpointMigrationError as exc:
                raise RecoveryRequiredError(
                    f"Нельзя преобразовать формат {checkpoint}: {exc}"
                ) from exc
            except Exception as exc:
                failures.append({"checkpoint": checkpoint, "error": str(exc)})
                logger.warning("Снимок не читается %s: %s", checkpoint, exc)
                continue
            # Применение пока не полностью транзакционно: после его ошибки
            # не пытаемся продолжить на частично изменённом объекте.
            if not agent.load_state(checkpoint):
                raise RecoveryRequiredError(
                    f"Не удалось применить снимок {checkpoint}; запуск остановлен"
                )
            if "life_id" not in state:
                memory = getattr(agent, "long_term_memory", None)
                if memory is None:
                    raise RecoveryRequiredError(
                        "Не удалось подготовить память жизни; запуск остановлен"
                    )
                try:
                    memory.bind_legacy_file(state["name"])
                except Exception as exc:
                    raise RecoveryRequiredError(
                        "Не удалось перенести старую долговременную память; оригинал сохранён"
                    ) from exc
            report.update(
                source="checkpoint",
                checkpoint=os.path.basename(checkpoint),
                cycle=agent.cycle_count,
                recovery_failures=failures,
                recovered_from_older=bool(failures),
            )
            break
        else:
            if candidates:
                raise RecoveryRequiredError(
                    f"Ни один из {len(candidates)} снимков не читается; данные сохранены"
                )
            if expected_life_id is not None:
                raise RecoveryRequiredError(
                    "Снимки выбранной жизни не найдены; новая жизнь не создана"
                )
            logger.info("Чекпоинтов не найдено — стартуем новую жизнь")

    # Разрешения, выбранные человеком, переживают перезапуск. Ошибка чтения
    # файла не заменяет жизнь ошибкой: остаются настройки по умолчанию.
    from src.app.access_control import apply_saved

    access_report = apply_saved(agent, env.data_root)
    report["access"] = access_report
    if access_report.get("error"):
        logger.warning("Разрешения не применены: %s", access_report["error"])

    return agent, report


# ============================================================
# Диалог об имени
# ============================================================


def start_naming_dialogue(agent: Any, bus: Optional[Any] = None) -> Dict[str, Any]:
    """Запускает знакомство при первом контакте.

    Повторно не запускается: фаза восстанавливается из чекпоинта.
    """
    from src.core.subsystems import NamingDialogue

    dialogue = getattr(agent, "naming_dialogue", None)
    if dialogue is None:
        return {"status": "unavailable"}

    if dialogue.phase != NamingDialogue.PHASE_NONE:
        return {"status": "already", "phase": dialogue.phase}

    result = agent.start_naming_dialogue(cycle=agent.cycle_count)
    if result.get("status") == "initiated" and bus is not None:
        try:
            bus.publish_sync(
                "naming_initiated",
                source="bootstrap",
                agent_name=agent.name,
                message_id=result.get("message_id"),
            )
        except Exception as exc:
            logger.debug("publish naming_initiated: %s", exc)
    return result


__all__ = [
    "latest_checkpoint",
    "awaken_from_seed",
    "create_agent",
    "start_naming_dialogue",
]
