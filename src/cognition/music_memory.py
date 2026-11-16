"""Ограниченная память о реально воспринятых собственных мелодиях.

Новизна и личная значимость разделены: нейтральные прослушивания повышают
знакомство, а significance меняется только после фактического эпизода из
EmotionalState. Подробная история редакций ограничена; агрегаты работы при её
вытеснении сохраняются. Компонент не создаёт эмоций, целей или кандидатов.
"""

from __future__ import annotations

from copy import deepcopy
import math

from src.core.emotional_state import EMOTIONS, EVENT_EMOTIONS


SCHEMA_VERSION = 1
MAX_WORKS = 16
MAX_RECENT_REVISIONS = 12
MAX_ASSOCIATIONS = 16
FAMILIARITY_LEARNING_RATE = 0.15
SIGNIFICANCE_LEARNING_RATE = 0.25

_FEATURE_KEYS = {
    "mode",
    "tempo_bpm",
    "note_count",
    "rest_count",
    "note_density",
    "pause_ratio",
    "pitch_low",
    "pitch_high",
    "pitch_span",
    "repeated_note_ratio",
    "phrase_change_ratio",
}
_WORK_KEYS = {
    "work_id",
    "theme",
    "listen_count",
    "first_listened_cycle",
    "last_listened_cycle",
    "familiarity",
    "personal_significance",
    "last_revision",
    "last_sha256",
    "last_features",
    "recent_revisions",
    "associations",
    "last_response_by_kind",
}


def _keys(value, expected, path):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{path}: ожидались ровно поля {sorted(expected)}")


def _integer(value, path, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path}: ожидалось целое число")
    if value < (1 if positive else 0):
        raise ValueError(f"{path}: число вне допустимого диапазона")
    return value


def _number(value, path, *, low=0.0, high=1.0, include_low=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}: ожидалось конечное число")
    if not math.isfinite(value):
        raise ValueError(f"{path}: ожидалось конечное число")
    number = float(value)
    lower_invalid = number < low if include_low else number <= low
    if lower_invalid or number > high:
        raise ValueError(f"{path}: число вне допустимого диапазона")
    return number


def _work_id(value, path="work_id"):
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{path}: невалидный идентификатор работы")
    return value


def _sha256(value, path="sha256"):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{path}: невалидный SHA-256")
    return value


def _features(value, path="features"):
    _keys(value, _FEATURE_KEYS, path)
    if not isinstance(value["mode"], str) or not value["mode"]:
        raise ValueError(f"{path}.mode: ожидалась непустая строка")
    _number(value["tempo_bpm"], f"{path}.tempo_bpm", high=1000.0, include_low=False)
    notes = _integer(value["note_count"], f"{path}.note_count")
    rests = _integer(value["rest_count"], f"{path}.rest_count")
    total = notes + rests
    if total < 1:
        raise ValueError(f"{path}: пустая музыкальная структура")
    density = _number(value["note_density"], f"{path}.note_density")
    pauses = _number(value["pause_ratio"], f"{path}.pause_ratio")
    if abs(density - notes / total) > 1e-9 or abs(pauses - rests / total) > 1e-9:
        raise ValueError(f"{path}: доли не соответствуют числу событий")
    _number(value["repeated_note_ratio"], f"{path}.repeated_note_ratio")
    _number(value["phrase_change_ratio"], f"{path}.phrase_change_ratio")
    pitches = (value["pitch_low"], value["pitch_high"], value["pitch_span"])
    if notes == 0:
        if any(pitch is not None for pitch in pitches):
            raise ValueError(f"{path}: у структуры без нот не должно быть высоты")
    else:
        low = _integer(pitches[0], f"{path}.pitch_low")
        high = _integer(pitches[1], f"{path}.pitch_high")
        span = _integer(pitches[2], f"{path}.pitch_span")
        if low > 127 or high > 127 or low > high or span != high - low:
            raise ValueError(f"{path}: невалидный диапазон высот")
    return deepcopy(value)


def _observation(value):
    _keys(
        value,
        {"schema_version", "work_id", "theme", "revision", "sha256", "features"},
        "observation",
    )
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("observation.schema_version: неподдерживаемая версия")
    _work_id(value["work_id"], "observation.work_id")
    if not isinstance(value["theme"], str) or not value["theme"]:
        raise ValueError("observation.theme: ожидалась непустая строка")
    _integer(value["revision"], "observation.revision", positive=True)
    _sha256(value["sha256"], "observation.sha256")
    _features(value["features"], "observation.features")
    return value


def _revision(value, path):
    _keys(value, {"revision", "sha256", "listen_count", "last_listened_cycle"}, path)
    _integer(value["revision"], f"{path}.revision", positive=True)
    _sha256(value["sha256"], f"{path}.sha256")
    _integer(value["listen_count"], f"{path}.listen_count", positive=True)
    _integer(value["last_listened_cycle"], f"{path}.last_listened_cycle")


def _association(value, path):
    _keys(
        value,
        {"cycle", "event", "emotion", "intensity", "revision", "sha256"},
        path,
    )
    _integer(value["cycle"], f"{path}.cycle")
    event = value["event"]
    emotion = value["emotion"]
    if event not in EVENT_EMOTIONS or emotion not in EMOTIONS:
        raise ValueError(f"{path}: неизвестное эмоциональное событие")
    if EVENT_EMOTIONS[event][0] != emotion:
        raise ValueError(f"{path}: эмоция не соответствует событию")
    _number(value["intensity"], f"{path}.intensity", include_low=False)
    _integer(value["revision"], f"{path}.revision", positive=True)
    _sha256(value["sha256"], f"{path}.sha256")


def _work(value, path):
    _keys(value, _WORK_KEYS, path)
    identifier = _work_id(value["work_id"], f"{path}.work_id")
    if not isinstance(value["theme"], str) or not value["theme"]:
        raise ValueError(f"{path}.theme: ожидалась непустая строка")
    count = _integer(value["listen_count"], f"{path}.listen_count", positive=True)
    first = _integer(value["first_listened_cycle"], f"{path}.first_listened_cycle")
    last = _integer(value["last_listened_cycle"], f"{path}.last_listened_cycle")
    if first > last:
        raise ValueError(f"{path}: нарушен порядок циклов прослушивания")
    _number(value["familiarity"], f"{path}.familiarity")
    _number(value["personal_significance"], f"{path}.personal_significance")
    last_revision = _integer(
        value["last_revision"], f"{path}.last_revision", positive=True
    )
    last_sha256 = _sha256(value["last_sha256"], f"{path}.last_sha256")
    _features(value["last_features"], f"{path}.last_features")
    revisions = value["recent_revisions"]
    if (
        not isinstance(revisions, list)
        or not 1 <= len(revisions) <= MAX_RECENT_REVISIONS
    ):
        raise ValueError(f"{path}.recent_revisions: невалидный ограниченный журнал")
    for index, revision in enumerate(revisions):
        _revision(revision, f"{path}.recent_revisions[{index}]")
        if revision["last_listened_cycle"] > last:
            raise ValueError(f"{path}.recent_revisions[{index}]: цикл новее работы")
    if sum(revision["listen_count"] for revision in revisions) > count:
        raise ValueError(f"{path}: счётчики редакций превышают счётчик работы")
    if (last_revision, last_sha256) != (
        revisions[-1]["revision"],
        revisions[-1]["sha256"],
    ):
        raise ValueError(f"{path}: последняя версия не совпадает с журналом")
    associations = value["associations"]
    if not isinstance(associations, list) or len(associations) > MAX_ASSOCIATIONS:
        raise ValueError(f"{path}.associations: невалидный ограниченный журнал")
    for index, association in enumerate(associations):
        _association(association, f"{path}.associations[{index}]")
        if association["cycle"] > last:
            raise ValueError(f"{path}.associations[{index}]: цикл новее прослушивания")
    responses = value["last_response_by_kind"]
    if not isinstance(responses, dict):
        raise ValueError(f"{path}.last_response_by_kind: ожидался словарь")
    for event, cycle in responses.items():
        if event not in EVENT_EMOTIONS:
            raise ValueError(f"{path}.last_response_by_kind: неизвестное событие")
        if _integer(cycle, f"{path}.last_response_by_kind.{event}") > last:
            raise ValueError(f"{path}.last_response_by_kind: цикл новее прослушивания")
    return identifier


def validate_music_memory(data):
    """Проверить checkpoint целиком, не изменяя входной объект."""
    if data == {}:
        return
    _keys(data, {"schema_version", "works"}, "music_memory")
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("music_memory.schema_version: неподдерживаемая версия")
    works = data["works"]
    if not isinstance(works, dict) or len(works) > MAX_WORKS:
        raise ValueError("music_memory.works: невалидный ограниченный каталог")
    for key, work in works.items():
        path = f"music_memory.works.{key}"
        if _work_id(key, path) != _work(work, path):
            raise ValueError(f"{path}: ключ не совпадает с work_id")


class MusicMemory:
    """Владелец музыкальных агрегатов и ограниченных журналов."""

    def __init__(self):
        self._works = {}

    def get_work(self, work_id):
        _work_id(work_id)
        work = self._works.get(work_id)
        return deepcopy(work) if work is not None else None

    def has_listened(self, work_id, revision, sha256):
        work = self.get_work(work_id)
        return work is not None and any(
            item["revision"] == revision and item["sha256"] == sha256
            for item in work["recent_revisions"]
        )

    def record_observation(self, observation, cycle):
        """Записать завершённое прослушивание; нейтральный повтор не даёт значимости."""
        _observation(observation)
        _integer(cycle, "cycle")
        identifier = observation["work_id"]
        work = self._works.get(identifier)
        if work is not None:
            if cycle < work["last_listened_cycle"]:
                raise ValueError("cycle: прослушивание старше сохранённого состояния")
            if cycle == work["last_listened_cycle"]:
                if (
                    observation["revision"] == work["last_revision"]
                    and observation["sha256"] == work["last_sha256"]
                ):
                    return deepcopy(work)
                raise ValueError("cycle: две версии одной работы в одном цикле")
        else:
            if len(self._works) >= MAX_WORKS:
                oldest = min(
                    self._works,
                    key=lambda key: (
                        self._works[key]["last_listened_cycle"],
                        key,
                    ),
                )
                del self._works[oldest]
            work = {
                "work_id": identifier,
                "theme": observation["theme"],
                "listen_count": 0,
                "first_listened_cycle": cycle,
                "last_listened_cycle": cycle,
                "familiarity": 0.0,
                "personal_significance": 0.0,
                "last_revision": observation["revision"],
                "last_sha256": observation["sha256"],
                "last_features": deepcopy(observation["features"]),
                "recent_revisions": [],
                "associations": [],
                "last_response_by_kind": {},
            }
            self._works[identifier] = work

        work["listen_count"] += 1
        work["last_listened_cycle"] = cycle
        work["familiarity"] += (1.0 - work["familiarity"]) * FAMILIARITY_LEARNING_RATE
        work["last_revision"] = observation["revision"]
        work["last_sha256"] = observation["sha256"]
        work["last_features"] = deepcopy(observation["features"])
        revisions = work["recent_revisions"]
        current = None
        for item in revisions:
            if (
                item["revision"] == observation["revision"]
                and item["sha256"] == observation["sha256"]
            ):
                current = dict(item)
                revisions.remove(item)
                break
        if current is None:
            current = {
                "revision": observation["revision"],
                "sha256": observation["sha256"],
                "listen_count": 0,
                "last_listened_cycle": cycle,
            }
        current["listen_count"] += 1
        current["last_listened_cycle"] = cycle
        revisions.append(current)
        del revisions[:-MAX_RECENT_REVISIONS]
        return deepcopy(work)

    def record_affect(self, observation, episode):
        """Связать реальный episode EmotionalState с последним прослушиванием."""
        _observation(observation)
        _keys(episode, {"cycle", "event", "emotion", "intensity"}, "episode")
        identifier = observation["work_id"]
        work = self._works.get(identifier)
        if work is None or not self.has_listened(
            identifier, observation["revision"], observation["sha256"]
        ):
            raise ValueError("episode: музыкальная версия ещё не прослушана")
        if (
            observation["revision"] != work["last_revision"]
            or observation["sha256"] != work["last_sha256"]
            or episode["cycle"] != work["last_listened_cycle"]
        ):
            raise ValueError("episode: аффект не относится к последнему прослушиванию")
        association = {
            "cycle": episode["cycle"],
            "event": episode["event"],
            "emotion": episode["emotion"],
            "intensity": episode["intensity"],
            "revision": observation["revision"],
            "sha256": observation["sha256"],
        }
        _association(association, "episode")
        if association in work["associations"]:
            return deepcopy(work)
        work["associations"].append(association)
        del work["associations"][:-MAX_ASSOCIATIONS]
        intensity = float(association["intensity"])
        work["personal_significance"] += (
            (1.0 - work["personal_significance"])
            * SIGNIFICANCE_LEARNING_RATE
            * intensity
        )
        work["last_response_by_kind"][association["event"]] = association["cycle"]
        return deepcopy(work)

    def to_checkpoint(self):
        return {"schema_version": SCHEMA_VERSION, "works": deepcopy(self._works)}

    @classmethod
    def from_checkpoint(cls, data):
        if data is None or data == {}:
            return cls()
        validate_music_memory(data)
        restored = cls()
        restored._works = deepcopy(data["works"])
        return restored


__all__ = [
    "MAX_ASSOCIATIONS",
    "MAX_RECENT_REVISIONS",
    "MAX_WORKS",
    "MusicMemory",
    "validate_music_memory",
]
