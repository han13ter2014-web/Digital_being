"""Локальная episodic/semantic/procedural память с ограниченным recall.

Алгоритмы decay, consolidation и associations адаптированы из LongTermMemory
Digital Being. Модуль не импортирует код сущности и не использует её data/.
Записи добавляются только явно; вызывающая сторона не должна сохранять секреты.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import threading
from typing import Dict, List, Optional, Set
from uuid import uuid4


_MEMORY_TYPES = {"episodic", "semantic", "procedural"}
_STORES = {"short_term", "long_term", "episodic"}
_MEMORY_ID = re.compile(r"mem_[a-f0-9]{32}\Z")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_RUSSIAN_SUFFIXES = (
    "ирования",
    "ированию",
    "ированием",
    "ировании",
    "ирование",
    "ениями",
    "ением",
    "ения",
    "ению",
    "ении",
    "ение",
    "ировать",
    "овать",
    "евать",
    "ывать",
    "ивать",
    "ать",
    "ять",
    "еть",
    "ить",
    "уть",
    "ыть",
    "ами",
    "ями",
    "ого",
    "его",
    "ому",
    "ему",
    "ыми",
    "ими",
    "ая",
    "яя",
    "ые",
    "ие",
    "ой",
    "ей",
    "ым",
    "им",
    "ов",
    "ев",
    "а",
    "я",
    "ы",
    "и",
    "у",
    "ю",
    "е",
    "о",
    "й",
    "ь",
)
_MAX_CONTENT_CHARS = 12_000
_MAX_CONTEXT_CHARS = 2_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _stem(word: str) -> str:
    """Снять один распространённый русский суффикс без угадывания смысла."""
    normalized = word.lower().replace("ё", "е")
    if len(normalized) < 5:
        return normalized
    for suffix in _RUSSIAN_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 4:
            return normalized[: -len(suffix)]
    return normalized


def _words(text: str) -> Set[str]:
    return {_stem(word) for word in _WORD.findall(text)}


def _truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    return text[: limit - 1].rstrip() + "…"


@dataclass
class MemoryTrace:
    """Отдельный след памяти с decay и историей обращений."""

    content: str
    importance: float
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0
    context: str = ""
    associations: Set[str] = field(default_factory=set)
    memory_type: str = "episodic"

    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("Память: пустое содержимое")
        if len(self.content) > _MAX_CONTENT_CHARS:
            raise ValueError("Память: слишком длинное содержимое")
        if not isinstance(self.context, str) or len(self.context) > _MAX_CONTEXT_CHARS:
            raise ValueError("Память: некорректный контекст")
        if (
            isinstance(self.importance, bool)
            or not isinstance(self.importance, (int, float))
            or not math.isfinite(float(self.importance))
        ):
            raise ValueError("Память: некорректная важность")
        self.importance = _clamp(self.importance)
        if self.memory_type not in _MEMORY_TYPES:
            raise ValueError("Память: неизвестный тип")
        if isinstance(self.access_count, bool) or not isinstance(
            self.access_count, int
        ):
            raise ValueError("Память: некорректный счётчик обращений")
        if self.access_count < 0:
            raise ValueError("Память: отрицательный счётчик обращений")
        if self.created_at.tzinfo is None or self.last_accessed.tzinfo is None:
            raise ValueError("Память: время должно содержать часовой пояс")
        self.associations = set(self.associations)

    def decay_strength(self, current_time: datetime, decay_rate: float = 0.95) -> float:
        """Сила следа: суточный decay, важность и частые обращения."""
        elapsed = max(0.0, (current_time - self.created_at).total_seconds())
        days = elapsed / (24 * 3600)
        base_decay = decay_rate**days
        importance_factor = 1.0 - self.importance * 0.5
        access_bonus = min(0.3, self.access_count * 0.05)
        return _clamp(base_decay * importance_factor + access_bonus)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "importance": self.importance,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "access_count": self.access_count,
            "context": self.context,
            "associations": sorted(self.associations),
            "memory_type": self.memory_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryTrace":
        if not isinstance(data, dict):
            raise ValueError("Память: след должен быть объектом")
        return cls(
            content=data["content"],
            importance=data["importance"],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_accessed=datetime.fromisoformat(data["last_accessed"]),
            access_count=data.get("access_count", 0),
            context=data.get("context", ""),
            associations=set(data.get("associations", [])),
            memory_type=data.get("memory_type", "episodic"),
        )


class AssistantMemory:
    """Персистентная память ассистента с явным бюджетом выдачи."""

    def __init__(
        self,
        storage_dir: Optional[str | Path] = None,
        *,
        decay_rate: float = 0.95,
        consolidation_threshold: float = 0.7,
        max_episodic: int = 5_000,
        max_memories: int = 10_000,
        autosave: bool = True,
    ) -> None:
        configured = storage_dir or os.environ.get("ASSISTANT_MEMORY_DIR")
        self.storage_dir = Path(configured or Path.cwd() / "assistant_memory_data")
        self.storage_dir = self.storage_dir.expanduser().resolve()
        self.memory_file = self.storage_dir / "memory.json"
        if not 0.0 < decay_rate < 1.0:
            raise ValueError("decay_rate должен быть между 0 и 1")
        if not 0.0 <= consolidation_threshold <= 1.0:
            raise ValueError("consolidation_threshold должен быть от 0 до 1")
        if max_episodic < 1 or max_memories < 1 or max_episodic > max_memories:
            raise ValueError("Некорректные лимиты памяти")
        self.decay_rate = float(decay_rate)
        self.consolidation_threshold = float(consolidation_threshold)
        self.max_episodic = int(max_episodic)
        self.max_memories = int(max_memories)
        self.autosave = bool(autosave)
        self._traces: Dict[str, MemoryTrace] = {}
        self._stores: Dict[str, str] = {}
        self._episodic_ids: List[str] = []
        self._consolidation_count = 0
        self._decay_events_count = 0
        self._lock = threading.RLock()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._load()

    def store(
        self,
        content: str,
        importance: float = 0.5,
        context: str = "",
        memory_type: str = "episodic",
    ) -> str:
        """Добавить явную запись и при необходимости сразу консолидировать её."""
        with self._lock:
            now = _now()
            memory_id = f"mem_{uuid4().hex}"
            trace = MemoryTrace(
                content=content.strip(),
                importance=importance,
                created_at=now,
                last_accessed=now,
                context=context.strip(),
                memory_type=memory_type,
            )
            self._traces[memory_id] = trace
            self._stores[memory_id] = "short_term"
            if memory_type == "episodic":
                self._episodic_ids.append(memory_id)
            self._link_similar(memory_id)
            self._apply_limits(now)
            if trace.importance > self.consolidation_threshold:
                self._consolidate(memory_id)
            if self.autosave:
                self.save()
            return memory_id

    def recall(
        self,
        query: str,
        *,
        threshold: float = 0.1,
        max_results: int = 5,
        max_chars: int = 4_000,
        min_relevance: float = 0.1,
    ) -> List[Dict]:
        """Найти записи; max_chars ограничивает суммарный возвращаемый контент."""
        if max_results < 1 or max_chars < 1:
            return []
        with self._lock:
            query_words = _words(query)
            if not query_words:
                return []
            now = _now()
            candidates = []
            for memory_id, trace in self._traces.items():
                strength = trace.decay_strength(now, self.decay_rate)
                if strength < threshold:
                    continue
                trace_words = _words(f"{trace.context} {trace.content}")
                relevance = len(query_words & trace_words) / max(
                    len(query_words | trace_words), 1
                )
                if relevance >= min_relevance:
                    candidates.append((memory_id, trace, relevance, strength))
            candidates.sort(
                key=lambda item: (
                    item[2],
                    item[3],
                    item[1].importance,
                    item[1].created_at,
                ),
                reverse=True,
            )
            results = []
            remaining = max_chars
            for memory_id, trace, relevance, strength in candidates[:max_results]:
                if remaining <= 0:
                    break
                content = _truncate(trace.content, remaining)
                remaining -= len(content)
                trace.last_accessed = now
                trace.access_count += 1
                results.append(
                    {
                        "id": memory_id,
                        "content": content,
                        "context": trace.context,
                        "memory_type": trace.memory_type,
                        "importance": trace.importance,
                        "strength": strength,
                        "relevance": relevance,
                        "access_count": trace.access_count,
                        "truncated": len(content) < len(trace.content),
                    }
                )
            if results and self.autosave:
                self.save()
            return results

    def recall_context(
        self, query: str, *, max_results: int = 4, max_chars: int = 2_000
    ) -> str:
        """Текст для контекста модели, строго ограниченный по символам."""
        results = self.recall(
            query, max_results=max_results, max_chars=max_chars, threshold=0.0
        )
        lines = []
        for result in results:
            prefix = f"- [{result['memory_type']}] "
            suffix = f" (контекст: {result['context']})" if result["context"] else ""
            lines.append(f"{prefix}{result['content']}{suffix}")
        return _truncate("\n".join(lines), max_chars)

    def trigger_decay(self) -> None:
        """Забыть слабые рабочие следы и консолидировать устойчивые."""
        with self._lock:
            now = _now()
            for memory_id, store in list(self._stores.items()):
                if store != "short_term":
                    continue
                trace = self._traces[memory_id]
                strength = trace.decay_strength(now, self.decay_rate)
                if strength < 0.05:
                    if memory_id in self._episodic_ids:
                        self._stores[memory_id] = "episodic"
                    else:
                        self._delete(memory_id)
                    self._decay_events_count += 1
                elif strength > self.consolidation_threshold:
                    self._consolidate(memory_id)
            if self.autosave:
                self.save()

    def forget(self, memory_id: str) -> bool:
        """Явно удалить запись и все ссылки на неё."""
        with self._lock:
            if memory_id not in self._traces:
                return False
            self._delete(memory_id)
            self._decay_events_count += 1
            if self.autosave:
                self.save()
            return True

    def get_recent_episodes(self, days: int = 7, count: int = 10) -> List[Dict]:
        cutoff = _now() - timedelta(days=days)
        with self._lock:
            ids = [
                memory_id
                for memory_id in reversed(self._episodic_ids)
                if self._traces[memory_id].created_at > cutoff
            ][:count]
            return [self._public_trace(memory_id) for memory_id in ids]

    def get_most_important(self, count: int = 5) -> List[Dict]:
        now = _now()
        with self._lock:
            ids = sorted(
                self._traces,
                key=lambda memory_id: (
                    self._traces[memory_id].importance,
                    self._traces[memory_id].decay_strength(now, self.decay_rate),
                ),
                reverse=True,
            )[:count]
            return [self._public_trace(memory_id) for memory_id in ids]

    def get_memory_stats(self) -> Dict:
        with self._lock:
            stores = self._stores.values()
            long_term = [
                self._traces[key]
                for key, store in self._stores.items()
                if store == "long_term"
            ]
            return {
                "short_term_count": sum(store == "short_term" for store in stores),
                "long_term_count": len(long_term),
                "episodic_count": len(self._episodic_ids),
                "total_memories": len(self._traces),
                "avg_importance": (
                    sum(trace.importance for trace in long_term) / len(long_term)
                    if long_term
                    else 0.0
                ),
                "consolidation_count": self._consolidation_count,
                "decay_events": self._decay_events_count,
                "decay_rate": self.decay_rate,
                "consolidation_threshold": self.consolidation_threshold,
            }

    def save(self) -> None:
        """Атомарно заменить JSON, сохраняя прежний файл при ошибке записи."""
        with self._lock:
            data = {
                "schema_version": 1,
                "traces": {key: trace.to_dict() for key, trace in self._traces.items()},
                "stores": dict(self._stores),
                "episodic": list(self._episodic_ids),
                "metadata": {
                    "consolidation_count": self._consolidation_count,
                    "decay_events_count": self._decay_events_count,
                    "saved_at": _now().isoformat(),
                },
            }
            temporary = self.memory_file.with_suffix(".json.tmp")
            try:
                with temporary.open("w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.memory_file)
            finally:
                if temporary.exists():
                    temporary.unlink()

    def _load(self) -> None:
        if not self.memory_file.exists():
            return
        try:
            data = json.loads(self.memory_file.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1:
                raise ValueError("неподдерживаемая схема")
            traces = {
                key: MemoryTrace.from_dict(raw) for key, raw in data["traces"].items()
            }
            stores = dict(data["stores"])
            episodic = list(data["episodic"])
            if set(traces) != set(stores) or any(
                _MEMORY_ID.fullmatch(key) is None for key in traces
            ):
                raise ValueError("некорректные идентификаторы")
            if any(store not in _STORES for store in stores.values()):
                raise ValueError("неизвестное хранилище")
            if len(episodic) != len(set(episodic)) or not set(episodic) <= set(traces):
                raise ValueError("некорректный порядок эпизодов")
            for memory_id, trace in traces.items():
                if not all(isinstance(key, str) for key in trace.associations):
                    raise ValueError("некорректная ассоциация")
                trace.associations.intersection_update(traces)
                trace.associations.discard(memory_id)
            metadata = data.get("metadata", {})
            consolidation_count = metadata.get("consolidation_count", 0)
            decay_events_count = metadata.get("decay_events_count", 0)
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in (consolidation_count, decay_events_count)
            ):
                raise ValueError("некорректные счётчики")
        except Exception as exc:
            raise ValueError("Не удалось прочитать память ассистента") from exc
        self._traces = traces
        self._stores = stores
        self._episodic_ids = episodic
        self._consolidation_count = consolidation_count
        self._decay_events_count = decay_events_count

    def _public_trace(self, memory_id: str) -> Dict:
        trace = self._traces[memory_id]
        return {
            "id": memory_id,
            "content": trace.content,
            "importance": trace.importance,
            "created_at": trace.created_at.isoformat(),
            "context": trace.context,
            "memory_type": trace.memory_type,
        }

    def _consolidate(self, memory_id: str) -> None:
        if self._stores.get(memory_id) == "short_term":
            self._stores[memory_id] = "long_term"
            self._consolidation_count += 1

    def _link_similar(self, memory_id: str, max_links: int = 3) -> None:
        trace = self._traces[memory_id]
        words = _words(f"{trace.context} {trace.content}")
        candidates = []
        for other_id, other in self._traces.items():
            if other_id == memory_id:
                continue
            other_words = _words(f"{other.context} {other.content}")
            similarity = len(words & other_words) / max(len(words | other_words), 1)
            if similarity > 0.2:
                candidates.append((other_id, similarity))
        candidates.sort(key=lambda item: item[1], reverse=True)
        for other_id, _ in candidates[:max_links]:
            trace.associations.add(other_id)
            self._traces[other_id].associations.add(memory_id)

    def _apply_limits(self, now: datetime) -> None:
        if len(self._episodic_ids) > self.max_episodic:
            ordered = sorted(
                self._episodic_ids,
                key=lambda key: (
                    self._traces[key].importance,
                    self._traces[key].created_at,
                ),
            )
            remove = set(ordered[: len(self._episodic_ids) - self.max_episodic])
            self._episodic_ids = [
                key for key in self._episodic_ids if key not in remove
            ]
            self._decay_events_count += len(remove)
        if len(self._traces) > self.max_memories:
            ordered = sorted(
                self._traces,
                key=lambda key: (
                    self._traces[key].importance,
                    self._traces[key].decay_strength(now, self.decay_rate),
                    self._traces[key].created_at,
                ),
            )
            for memory_id in ordered[: len(self._traces) - self.max_memories]:
                self._delete(memory_id)
                self._decay_events_count += 1

    def _delete(self, memory_id: str) -> None:
        self._traces.pop(memory_id, None)
        self._stores.pop(memory_id, None)
        self._episodic_ids = [key for key in self._episodic_ids if key != memory_id]
        for trace in self._traces.values():
            trace.associations.discard(memory_id)


__all__ = ["AssistantMemory", "MemoryTrace"]
