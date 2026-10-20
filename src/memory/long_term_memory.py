import json
import math
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Set
import os


def _lr_config():
    """Ленивый импорт LR_CONFIG (избегаем циклов)."""
    try:
        from config.simulation_config import LR_CONFIG
        return LR_CONFIG
    except Exception:
        return None


@dataclass
class MemoryTrace:
    """Отдельный след памяти с decay-функцией."""
    content: str
    importance: float  # 0.0-1.0
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0
    context: str = ""
    associations: Set[str] = None  # Связанные следы памяти

    def __post_init__(self):
        if self.associations is None:
            self.associations = set()

    def decay_strength(self, current_time: datetime, decay_rate: float = 0.95) -> float:
        """Вычисляет силу памяти с экспоненциальным decay.

        decay_rate = 0.95 означает что память теряет 5% силы за каждый цикл времени.
        """
        time_passed = (current_time - self.created_at).total_seconds()
        cycles = time_passed / (24 * 3600)  # Циклы по суткам

        # Экспоненциальный decay с модификацией по importance
        base_decay = decay_rate ** cycles

        # Важные воспоминания забываются медленнее
        importance_factor = 1.0 - (self.importance * 0.5)
        adjusted_decay = base_decay * importance_factor

        # Частый доступ усиливает память
        access_bonus = min(0.3, self.access_count * 0.05)

        return max(0.0, min(1.0, adjusted_decay + access_bonus))

    def is_strong_enough(self, threshold: float = 0.1) -> bool:
        """Проверяет достаточно ли сильна память для активации."""
        return self.decay_strength(datetime.now()) >= threshold

    def to_dict(self) -> dict:
        """Сериализует в dict."""
        return {
            'content': self.content,
            'importance': self.importance,
            'created_at': self.created_at.isoformat(),
            'last_accessed': self.last_accessed.isoformat(),
            'access_count': self.access_count,
            'context': self.context,
            'associations': list(self.associations)
        }

    @staticmethod
    def from_dict(data: dict) -> 'MemoryTrace':
        """Десериализует из dict."""
        return MemoryTrace(
            content=data['content'],
            importance=data['importance'],
            created_at=datetime.fromisoformat(data['created_at']),
            last_accessed=datetime.fromisoformat(data['last_accessed']),
            access_count=data.get('access_count', 0),
            context=data.get('context', ''),
            associations=set(data.get('associations', []))
        )


class LongTermMemory:
    """Система долгосрочной памяти с экспоненциальным decay."""

    def __init__(self, agent_name: str, decay_rate: float = 0.95,
                 consolidation_threshold: float = 0.7):
        """
        Args:
            agent_name: Имя агента для сохранения памяти
            decay_rate: Базовый коэффициент decay (0.95 = 5% потери за цикл)
            consolidation_threshold: Порог для консолидации (перевода в долгий storage)
        """
        self.agent_name = agent_name
        self.decay_rate = decay_rate
        self.consolidation_threshold = consolidation_threshold

        # Структура памяти
        self._short_term: Dict[str, MemoryTrace] = {}  # Активная память
        self._long_term: Dict[str, MemoryTrace] = {}   # Консолидированная память
        self._episodic: List[MemoryTrace] = []         # Эпизодическая память (события в порядке)

        # Метаданные
        self._access_patterns: Dict[str, int] = {}     # Частотность доступа
        self._similarity_cache: Dict[str, List[str]] = {}  # Кэш похожих воспоминаний
        self._consolidation_count = 0
        self._decay_events_count = 0

        self.memory_file = f'data/memory/{agent_name}_long_term.json'
        os.makedirs('data/memory', exist_ok=True)

        self._load_from_disk()

    def store(self, content: str, importance: float = 0.5, context: str = "",
              memory_type: str = "episodic") -> str:
        """Сохраняет новое воспоминание.

        Args:
            content: Текст воспоминания
            importance: Важность (0.0-1.0)
            context: Контекст (цель, переживание и т.д.)
            memory_type: 'episodic' | 'semantic' | 'procedural'

        Returns:
            ID воспоминания
        """
        memory_id = self._generate_id(content)

        trace = MemoryTrace(
            content=content,
            importance=min(1.0, max(0.0, importance)),
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            context=context,
            associations=set()
        )

        # Добавляем в краткосрочную память
        self._short_term[memory_id] = trace

        # Добавляем в эпизодическую память
        if memory_type == "episodic":
            self._episodic.append(trace)
            # === Лимит эпизодов (Шаг 2) ===
            self._apply_episodic_limit()

        # Ищем и связываем похожие воспоминания
        self._link_similar_memories(memory_id)

        # Проверяем консолидацию
        self._try_consolidate(memory_id, trace)

        return memory_id

    def _apply_episodic_limit(self) -> int:
        """Мягкое ограничение эпизодов (Шаг 2).

        Возвращает количество забытых эпизодов.
        FIFO + приоритет: сначала удаляются наименее важные.
        """
        cfg = _lr_config()
        max_episodic = getattr(cfg, "MAX_EPISODIC_MEMORIES", 5000) if cfg else 5000

        if len(self._episodic) <= max_episodic:
            return 0

        # Сортируем по (importance ↑, created_at ↑) — наименее важные/старые первые
        sorted_eps = sorted(
            self._episodic,
            key=lambda t: (t.importance, t.created_at),
        )
        over = len(self._episodic) - max_episodic
        forgotten_traces = sorted_eps[:over]
        forgotten_ids = set(id(t) for t in forgotten_traces)
        self._episodic = [t for t in self._episodic if id(t) not in forgotten_ids]
        return len(forgotten_traces)

    def recall(self, query: str, threshold: float = 0.1,
               max_results: int = 5) -> List[Dict]:
        """Вспоминает воспоминания релевантные запросу.

        Args:
            query: Поисковый запрос
            threshold: Минимальная сила памяти для возврата
            max_results: Максимум результатов

        Returns:
            Список релевантных воспоминаний с метаданными
        """
        results = []
        query_words = set(query.lower().split())

        # Ищем в долгосрочной памяти (более консолидированная)
        for memory_id, trace in self._long_term.items():
            strength = trace.decay_strength(datetime.now(), self.decay_rate)

            if strength < threshold:
                continue

            # Вычисляем релевантность
            memory_words = set(trace.content.lower().split())
            relevance = len(query_words & memory_words) / max(len(query_words | memory_words), 1)

            if relevance > 0.1:
                trace.last_accessed = datetime.now()
                trace.access_count += 1

                results.append({
                    'content': trace.content,
                    'importance': trace.importance,
                    'strength': strength,
                    'relevance': relevance,
                    'age_days': (datetime.now() - trace.created_at).days,
                    'access_count': trace.access_count,
                    'context': trace.context
                })

        # Добавляем из краткосрочной памяти если есть место
        if len(results) < max_results:
            for memory_id, trace in self._short_term.items():
                strength = trace.decay_strength(datetime.now(), self.decay_rate)

                if strength < threshold:
                    continue

                memory_words = set(trace.content.lower().split())
                relevance = len(query_words & memory_words) / max(len(query_words | memory_words), 1)

                if relevance > 0.1 and memory_id not in [r.get('id') for r in results]:
                    trace.last_accessed = datetime.now()
                    trace.access_count += 1

                    results.append({
                        'content': trace.content,
                        'importance': trace.importance,
                        'strength': strength,
                        'relevance': relevance,
                        'age_days': (datetime.now() - trace.created_at).days,
                        'access_count': trace.access_count,
                        'context': trace.context
                    })

                if len(results) >= max_results:
                    break

        # Сортируем по релевантности и силе
        results.sort(key=lambda x: (x['relevance'], x['strength']), reverse=True)
        return results[:max_results]

    def trigger_decay(self):
        """Запускает процесс забывания для всех воспоминаний.

        Удаляет слишком слабые воспоминания и консолидирует сильные.
        """
        to_remove_short = []
        to_promote = []

        # Процесс забывания в краткосрочной памяти
        for memory_id, trace in list(self._short_term.items()):
            strength = trace.decay_strength(datetime.now(), self.decay_rate)

            if strength < 0.05:  # Слишком слабая
                to_remove_short.append(memory_id)
            elif strength > self.consolidation_threshold and memory_id not in self._long_term:
                # Консолидируем в долгосрочную память
                to_promote.append((memory_id, trace))

        # Удаляем забытые
        for memory_id in to_remove_short:
            del self._short_term[memory_id]
            self._decay_events_count += 1

        # Консолидируем
        for memory_id, trace in to_promote:
            self._long_term[memory_id] = trace
            del self._short_term[memory_id]
            self._consolidation_count += 1

    def get_most_important(self, count: int = 5) -> List[Dict]:
        """Возвращает самые важные воспоминания."""
        all_memories = []

        for memory_id, trace in self._long_term.items():
            strength = trace.decay_strength(datetime.now(), self.decay_rate)
            all_memories.append({
                'content': trace.content,
                'importance': trace.importance,
                'strength': strength,
                'age_days': (datetime.now() - trace.created_at).days,
                'context': trace.context
            })

        all_memories.sort(key=lambda x: (x['importance'], x['strength']), reverse=True)
        return all_memories[:count]

    def get_recent_episodes(self, days: int = 7, count: int = 10) -> List[Dict]:
        """Возвращает недавние эпизоды (события)."""
        cutoff = datetime.now() - timedelta(days=days)

        recent = [
            {
                'content': trace.content,
                'created_at': trace.created_at.isoformat(),
                'importance': trace.importance,
                'age_days': (datetime.now() - trace.created_at).days,
                'context': trace.context
            }
            for trace in reversed(self._episodic)
            if trace.created_at > cutoff
        ]

        return recent[:count]

    def get_memory_stats(self) -> Dict:
        """Возвращает статистику памяти."""
        total_short = len(self._short_term)
        total_long = len(self._long_term)
        total_episodic = len(self._episodic)

        avg_importance = 0
        if total_long > 0:
            avg_importance = sum(t.importance for t in self._long_term.values()) / total_long

        total_memory_size = total_short + total_long

        return {
            'short_term_count': total_short,
            'long_term_count': total_long,
            'episodic_count': total_episodic,
            'total_memories': total_memory_size,
            'avg_importance': avg_importance,
            'consolidation_count': self._consolidation_count,
            'decay_events': self._decay_events_count,
            'decay_rate': self.decay_rate,
            'consolidation_threshold': self.consolidation_threshold
        }

    def _link_similar_memories(self, memory_id: str, max_links: int = 3):
        """Связывает похожие воспоминания."""
        trace = self._short_term.get(memory_id)
        if not trace:
            return

        trace_words = set(trace.content.lower().split())

        candidates = []
        for other_id, other_trace in list(self._short_term.items()) + list(self._long_term.items()):
            if other_id == memory_id:
                continue

            other_words = set(other_trace.content.lower().split())
            similarity = len(trace_words & other_words) / max(len(trace_words | other_words), 1)

            if similarity > 0.2:
                candidates.append((other_id, similarity))

        candidates.sort(key=lambda x: x[1], reverse=True)
        for other_id, _ in candidates[:max_links]:
            trace.associations.add(other_id)

    def _try_consolidate(self, memory_id: str, trace: MemoryTrace):
        """Пытается консолидировать воспоминание в долгосрочную память."""
        if memory_id in self._long_term:
            return

        # Если очень важное - сразу консолидируем
        if trace.importance > self.consolidation_threshold:
            self._long_term[memory_id] = self._short_term.pop(memory_id)
            self._consolidation_count += 1

    def _generate_id(self, content: str) -> str:
        """Генерирует ID для воспоминания."""
        timestamp = int(datetime.now().timestamp() * 1000)
        content_hash = hash(content) % 10000
        return f"mem_{timestamp}_{content_hash}"

    def _save_to_disk(self):
        """Сохраняет память на диск."""
        try:
            data = {
                'short_term': {k: v.to_dict() for k, v in self._short_term.items()},
                'long_term': {k: v.to_dict() for k, v in self._long_term.items()},
                'episodic': [t.to_dict() for t in self._episodic],
                'metadata': {
                    'consolidation_count': self._consolidation_count,
                    'decay_events_count': self._decay_events_count,
                    'saved_at': datetime.now().isoformat()
                }
            }

            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"Ошибка сохранения памяти: {e}")

    def _load_from_disk(self):
        """Загружает память с диска."""
        if not os.path.exists(self.memory_file):
            return

        try:
            with open(self.memory_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._short_term = {k: MemoryTrace.from_dict(v) for k, v in data.get('short_term', {}).items()}
            self._long_term = {k: MemoryTrace.from_dict(v) for k, v in data.get('long_term', {}).items()}
            self._episodic = [MemoryTrace.from_dict(t) for t in data.get('episodic', [])]

            metadata = data.get('metadata', {})
            self._consolidation_count = metadata.get('consolidation_count', 0)
            self._decay_events_count = metadata.get('decay_events_count', 0)
        except Exception as e:
            print(f"Ошибка загрузки памяти: {e}")

    def save(self):
        """Сохраняет состояние памяти."""
        self._save_to_disk()

    def cleanup_weak_memories(self, strength_threshold: float = 0.1):
        """Очищает слишком слабые воспоминания."""
        to_remove = []

        for memory_id, trace in self._short_term.items():
            if trace.decay_strength(datetime.now(), self.decay_rate) < strength_threshold:
                to_remove.append(memory_id)

        for memory_id in to_remove:
            del self._short_term[memory_id]
            self._decay_events_count += 1
