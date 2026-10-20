"""
NurseryWatcher — наблюдатель за data/nursery/ (Этап 3.3).

Этап 3.3: подсистема мониторит директорию data/nursery/ — «Ясли», куда
MindDream оставляет «семена» (seeds) умерших/уснувших агентов. Когда в Яслях
появляется новый seed, watcher:

1. Фиксирует появление нового seed (с метаданными).
2. Уведомляет агента через EventBus (если подключена) или через свой callback.
3. Обновляет свой статус для dashboard (количество seeds, последний seed).
4. Не «воскрешает» автоматически — это решение пользователя/оператора.

Watcher унаследован от Subsystem (Этап 3.5), поэтому регистрируется в
PluginRegistry и попадает в общий tick() по priority.

Безопасность:
- Не импортирует seed-код (только читает метаданные).
- Не запускает awakener — только информирует.
- Если структура seed повреждена — записывает ошибку в _last_error и
  переходит к следующему.
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.subsystem_base import Subsystem


logger = logging.getLogger(__name__)


class NurseryWatcher(Subsystem):
    """Наблюдатель за директорией data/nursery/.

    Атрибуты:
        nursery_dir (str): путь к Яслям (по умолчанию data/nursery/).
        _known_seeds (set): set(dir_name) известных seed-ов, чтобы не
            повторять события при каждом тике.
        _seed_history (list): [{name, mtime, metadata, cycle, ts}, ...].
        _last_change_ts (float): timestamp последнего изменения.
        _agent (DigitalBeing|None): агент, к которому привязан watcher.
        _agent_attached (bool): защита от двойного attach_agent().
    """

    name = "nursery_watcher"
    priority = 200  # позже других (наблюдение — фоновая задача)
    version = "0.1.0"

    # Имена файлов, которые должны быть у «полного» seed-а (по аналогии с
    # data/nursery/OldSage_seed_*/).
    REQUIRED_SEED_FILES = (
        "metadata.json",
        "identity.json",
        "mental_models.json",
        "personality_signature.json",
        "README.md",
    )

    def __init__(self, agent_name: str = "unknown",
                 nursery_dir: Optional[str] = None) -> None:
        super().__init__(agent_name=agent_name)
        self.nursery_dir = nursery_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)
            )))),
            "data",
            "nursery",
        )
        self._known_seeds: set = set()
        self._seed_history: List[Dict[str, Any]] = []
        self._last_change_ts: float = 0.0
        self._agent: Any = None
        self._agent_attached: bool = False
        # Последний обнаруженный seed (для быстрого доступа).
        self._latest_seed: Optional[Dict[str, Any]] = None
        # Кэш read ошибок, чтобы не спамить лог.
        self._silent_errors: set = set()

    # ----------------------------------------------------------------
    # Конфигурация
    # ----------------------------------------------------------------

    def attach_agent(self, agent: Any) -> None:
        """Привязать агента (для уведомлений и контекста)."""
        if self._agent_attached:
            return
        self._agent = agent
        self._agent_attached = True

    # ----------------------------------------------------------------
    # Жизненный цикл (Этап 3.5: Subsystem-контракт)
    # ----------------------------------------------------------------

    def setup(self, context: Dict[str, Any]) -> None:
        super().setup(context)
        # Убедимся, что директория существует (мягко — не создаём Ясли).
        if not os.path.isdir(self.nursery_dir):
            logger.debug(f"[{self.name}] nursery не существует: {self.nursery_dir}")
            return
        # Инициализируем known_seeds при старте — чтобы не сыпать события
        # о seed-ах, которые уже были до первого тика.
        try:
            self._known_seeds = self._scan_existing_seeds()
            logger.info(f"[{self.name}] инициализирован, известно seed-ов: {len(self._known_seeds)}")
        except Exception as e:
            self._record_error(e)

    def tick(self, cycle: int, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Проверяет Ясли на новые seed-ы.

        Возвращает:
            {"events": [{"name": "nursery.new_seed", "data": {...}}, ...]}
            если есть новые. Иначе None.
        """
        if not os.path.isdir(self.nursery_dir):
            return None
        try:
            current = self._scan_existing_seeds()
        except Exception as e:
            self._record_error(e)
            return None

        new_seeds = current - self._known_seeds
        if not new_seeds:
            # Если что-то пропало — тоже фиксируем (агент мог удалить seed).
            removed = self._known_seeds - current
            if removed:
                for name in removed:
                    self._emit_removed(name)
                self._known_seeds = current
            return None

        events: List[Dict[str, Any]] = []
        for seed_name in sorted(new_seeds):
            payload = self._inspect_seed(seed_name)
            if payload is None:
                continue
            self._seed_history.append(payload)
            self._latest_seed = payload
            events.append({
                "name": "nursery.new_seed",
                "data": payload,
            })
            self._emit_new_seed(payload)

        # Ограничиваем размер истории.
        if len(self._seed_history) > 100:
            self._seed_history = self._seed_history[-100:]

        self._known_seeds = current
        self._last_change_ts = time.time()

        return {"events": events} if events else None

    def teardown(self) -> None:
        super().teardown()
        self._known_seeds.clear()

    # ----------------------------------------------------------------
    # Диагностика
    # ----------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        base = super().status()
        base.update({
            "nursery_dir": self.nursery_dir,
            "nursery_exists": os.path.isdir(self.nursery_dir),
            "known_seeds_count": len(self._known_seeds),
            "known_seeds": sorted(self._known_seeds),
            "history_count": len(self._seed_history),
            "latest_seed": self._latest_seed,
            "last_change_ts": self._last_change_ts,
            "agent_attached": self._agent_attached,
        })
        return base

    # ----------------------------------------------------------------
    # Утилиты для внешнего использования
    # ----------------------------------------------------------------

    def list_seeds(self) -> List[Dict[str, Any]]:
        """Возвращает список всех seed-ов (включая метаданные)."""
        if not os.path.isdir(self.nursery_dir):
            return []
        result = []
        for entry in sorted(os.listdir(self.nursery_dir)):
            full = os.path.join(self.nursery_dir, entry)
            if not os.path.isdir(full):
                continue
            if not entry.endswith(tuple(f"_{ts}" for ts in [""])):  # any dir
                pass
            payload = self._inspect_seed(entry, include_full_metadata=True)
            if payload is not None:
                result.append(payload)
        return result

    def get_seed(self, name: str) -> Optional[Dict[str, Any]]:
        """Получить полную информацию о seed-е по имени директории."""
        return self._inspect_seed(name, include_full_metadata=True)

    # ----------------------------------------------------------------
    # Внутренние хелперы
    # ----------------------------------------------------------------

    def _scan_existing_seeds(self) -> set:
        """Возвращает set имён директорий в Яслях (без рекурсии)."""
        if not os.path.isdir(self.nursery_dir):
            return set()
        out = set()
        for entry in os.listdir(self.nursery_dir):
            full = os.path.join(self.nursery_dir, entry)
            if os.path.isdir(full) and not entry.startswith("."):
                out.add(entry)
        return out

    def _inspect_seed(self, seed_name: str,
                       include_full_metadata: bool = False) -> Optional[Dict[str, Any]]:
        """Читает метаданные seed-а. Возвращает None если невалидный."""
        seed_path = os.path.join(self.nursery_dir, seed_name)
        if not os.path.isdir(seed_path):
            return None

        payload: Dict[str, Any] = {
            "name": seed_name,
            "path": seed_path,
            "files": sorted(os.listdir(seed_path)),
            "mtime": 0.0,
            "size_bytes": 0,
            "is_complete": False,
            "metadata": None,
            "identity": None,
            "personality_signature": None,
            "inspected_at": datetime.now().isoformat(),
        }

        try:
            stat = os.stat(seed_path)
            payload["mtime"] = stat.st_mtime
        except Exception:
            pass

        # Суммарный размер файлов.
        try:
            total = 0
            for root, _, files in os.walk(seed_path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            payload["size_bytes"] = total
        except Exception:
            pass

        # Проверяем «полноту» (есть ли обязательные файлы).
        present = set(payload["files"])
        missing = [f for f in self.REQUIRED_SEED_FILES if f not in present]
        payload["is_complete"] = not missing
        payload["missing_files"] = missing

        if include_full_metadata:
            for fname, key in (
                ("metadata.json", "metadata"),
                ("identity.json", "identity"),
                ("personality_signature.json", "personality_signature"),
                ("last_will.md", "last_will"),
            ):
                full = os.path.join(seed_path, fname)
                if not os.path.exists(full):
                    continue
                try:
                    if fname.endswith(".json"):
                        with open(full, "r", encoding="utf-8") as f:
                            payload[key] = json.load(f)
                    else:
                        with open(full, "r", encoding="utf-8") as f:
                            payload[key] = f.read()[:4096]  # cap до 4KB
                except Exception as e:
                    payload[f"{key}_error"] = str(e)
                    if seed_name not in self._silent_errors:
                        logger.warning(f"[{self.name}] {seed_name}/{fname}: {e}")
                        self._silent_errors.add(seed_name)

        return payload

    def _emit_new_seed(self, payload: Dict[str, Any]) -> None:
        """Уведомить подписчиков и агента о новом seed-е."""
        logger.info(
            f"[{self.name}] новый seed в Яслях: {payload['name']} "
            f"({payload['size_bytes']} байт, complete={payload['is_complete']})"
        )
        # Через EventBus (если подключена).
        try:
            bus = getattr(self._context.get("registry"), "_global_event_bus", None) \
                if self._context else None
            if bus is not None:
                bus.publish_sync("nursery.new_seed", payload, source="nursery_watcher")
        except Exception:
            pass
        # Через агента (если есть совместимый метод).
        if self._agent is not None:
            notify = getattr(self._agent, "on_nursery_new_seed", None)
            if callable(notify):
                try:
                    notify(payload)
                except Exception as e:
                    logger.debug(f"[{self.name}] agent.on_nursery_new_seed ошибка: {e}")

    def _emit_removed(self, seed_name: str) -> None:
        """Уведомить об удалении seed-а."""
        logger.info(f"[{self.name}] seed удалён из Яслей: {seed_name}")
        try:
            bus = getattr(self._context.get("registry"), "_global_event_bus", None) \
                if self._context else None
            if bus is not None:
                bus.publish_sync(
                    "nursery.seed_removed",
                    {"name": seed_name},
                    source="nursery_watcher",
                )
        except Exception:
            pass


__all__ = ["NurseryWatcher"]