"""Read-only аппаратная интероцепция и её теневая эндокринная проекция.

Наблюдатель отделяет ресурсы процесса от давления хоста. Он не выбирает
действия, не меняет потребности, канонические эмоции, энергию или награды.
Единственный внешний эффект — типизированные события для ``HormonalSystem``.
"""

from __future__ import annotations

from copy import deepcopy
import math
import shutil
from typing import Dict, Optional

from src.core.buffered_logger import get_logger
from src.core.hardware_personal_profile import (
    HardwarePersonalProfile,
    validate_personal_experience,
)
from src.core.hardware_sensors import read_physical_sensors
from src.core.paths import data_dir


_HISTORY_LIMIT = 200
_EVENT_LIMIT = 50
_STRAIN_THRESHOLD = 0.85
_RECOVERY_THRESHOLD = 0.6
_STRAIN_AFTER_CYCLES = 5
_RECOVERY_AFTER_CYCLES = 5
_STATE_NAMES = (
    "own_load",
    "environmental_pressure",
    "memory_pressure",
    "storage_risk",
    "physical_strain",
    "recovery",
    "reserve",
)
_RESOURCE_CHANNELS = {
    "host_cpu": ("host_cpu_percent", 0.0, 100.0, "percent"),
    "process_cpu": ("process_cpu_percent", 0.0, None, "percent"),
    "host_memory": ("host_memory_percent", 0.0, 100.0, "percent"),
    "process_rss": ("process_rss_mb", 0.0, None, "mb"),
    "process_rss_ratio": ("process_rss_ratio", 0.0, None, "ratio"),
    "cycle_duration": ("cycle_duration_ms", 0.0, None, "ms"),
}
_PHYSICAL_CHANNELS = {
    "gpu_utilization": (0.0, 100.0, "percent"),
    "gpu_memory": (0.0, 1.0, "ratio"),
    "gpu_temperature": (0.0, 150.0, "celsius"),
    "gpu_power": (0.0, 2.0, "ratio"),
    "cpu_temperature": (0.0, 150.0, "celsius"),
    "external_power": (0.0, 1.0, "ratio"),
    "battery_charge": (0.0, 100.0, "percent"),
}
_CHANNEL_SOURCES = {
    "data_storage": "shutil.disk_usage",
    "gpu_utilization": "nvml",
    "gpu_memory": "nvml",
    "gpu_temperature": "nvml",
    "gpu_power": "nvml",
    "cpu_temperature": "psutil",
    "external_power": "windows",
    "battery_charge": "windows",
}
_DIAGNOSTIC_REASONS = {
    "source_error",
    "resource_source_unavailable",
    "invalid_or_missing_measurement",
    "storage_unavailable",
    "waiting_for_fresh_observation_after_restart",
    "sensor_disabled",
}
_DIAGNOSTIC_SOURCES = {
    "watchdog",
    "psutil",
    "shutil.disk_usage",
    "nvml",
    "windows",
    "test",
}


def _finite_number(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _diagnostic_reason(value, default: str = "source_error") -> str:
    reason = str(value or default)
    return reason if reason in _DIAGNOSTIC_REASONS else default


def _diagnostic_source(value, default: str) -> str:
    source = str(value or default)
    return source if source in _DIAGNOSTIC_SOURCES else default


def _unavailable(reason: str, source: str) -> Dict:
    return {
        "status": "unavailable",
        "value": None,
        "reason": _diagnostic_reason(reason),
        "source": _diagnostic_source(source, "watchdog"),
    }


def _resource_channel(raw: Dict, key: str, field: str, low, high, unit: str) -> Dict:
    source = _diagnostic_source(raw.get("source"), "watchdog")
    if raw.get("available") is not True:
        return _unavailable(
            _diagnostic_reason(
                raw.get("reason"), default="resource_source_unavailable"
            ),
            source,
        )
    value = raw.get(field)
    if (
        not _finite_number(value)
        or float(value) < low
        or (high is not None and float(value) > high)
    ):
        return _unavailable("invalid_or_missing_measurement", source)
    return {
        "status": "available",
        "value": float(value),
        "unit": unit,
        "reason": "",
        "source": source,
    }


def read_data_storage() -> Dict:
    """Прочитать только агрегаты раздела с изменяемыми данными проекта."""
    try:
        usage = shutil.disk_usage(data_dir())
        return {
            "available": True,
            "total_bytes": int(usage.total),
            "free_bytes": int(usage.free),
            "source": "shutil.disk_usage",
        }
    except Exception:
        # Текст исключения ОС может содержать путь; наружу уходит только код.
        return {
            "available": False,
            "reason": "source_error",
            "source": "shutil.disk_usage",
        }


def _storage_channel(raw: Dict) -> Dict:
    source = _diagnostic_source(raw.get("source"), "shutil.disk_usage")
    if raw.get("available") is not True:
        return _unavailable(
            _diagnostic_reason(raw.get("reason"), default="storage_unavailable"),
            source,
        )
    total = raw.get("total_bytes")
    free = raw.get("free_bytes")
    if (
        not _finite_number(total)
        or not _finite_number(free)
        or float(total) <= 0.0
        or float(free) < 0.0
        or float(free) > float(total)
    ):
        return _unavailable("invalid_or_missing_measurement", source)
    return {
        "status": "available",
        "value": float(free) / float(total),
        "free_bytes": int(free),
        "total_bytes": int(total),
        "unit": "free_ratio",
        "reason": "",
        "source": source,
    }


def _physical_channel(raw: Dict, name: str, low, high, unit: str) -> Dict:
    source = _diagnostic_source(
        raw.get("source"), _CHANNEL_SOURCES.get(name, "resource")
    )
    if raw.get("available") is not True:
        return _unavailable(
            _diagnostic_reason(
                raw.get("reason"), default="resource_source_unavailable"
            ),
            source,
        )
    value = raw.get("value")
    if (
        not _finite_number(value)
        or float(value) < low
        or (high is not None and float(value) > high)
    ):
        return _unavailable("invalid_or_missing_measurement", source)
    return {
        "status": "available",
        "value": float(value),
        "unit": unit,
        "reason": "",
        "source": source,
    }


def _unknown_state(reason: str) -> Dict:
    return {
        "value": None,
        "confidence": 0.0,
        "reason": reason,
        "origin": "unknown",
        "expectedness": "unknown",
        "evidence": [],
    }


def _state(
    value: float,
    confidence: float,
    reason: str,
    origin: str,
    evidence: list,
) -> Dict:
    return {
        "value": _clamp(value),
        "confidence": _clamp(confidence),
        "reason": reason,
        "origin": origin,
        "expectedness": "unknown",
        "evidence": list(evidence)[:8],
    }


def _available(observation: Dict, name: str) -> Optional[float]:
    channel = (observation.get("channels") or {}).get(name) or {}
    if channel.get("status") != "available" or not _finite_number(channel.get("value")):
        return None
    return float(channel["value"])


class HardwareInteroception:
    """Per-life состояние аппаратного опыта с ограниченной историей."""

    def __init__(self):
        self.latest_observation: Dict = {}
        self.states: Dict = {
            name: _unknown_state("no_observation") for name in _STATE_NAMES
        }
        self.history = []
        self.events = []
        self.last_cycle: Optional[int] = None
        self.sustained_pressure_cycles = 0
        self.low_pressure_cycles = 0
        self.strain_active = False
        self.personal = HardwarePersonalProfile()

    def observe(
        self,
        resource_status: Optional[Dict],
        *,
        cycle: int,
        storage_status: Optional[Dict] = None,
        physical_status: Optional[Dict] = None,
    ) -> Dict:
        cycle = int(cycle)
        if self.last_cycle == cycle:
            return {
                "mode": "shadow",
                "skipped": "duplicate_cycle",
                "endocrine_events": [],
            }

        raw = resource_status if isinstance(resource_status, dict) else {}
        channels = {
            name: _resource_channel(raw, name, *spec)
            for name, spec in _RESOURCE_CHANNELS.items()
        }
        storage_raw = (
            storage_status if isinstance(storage_status, dict) else read_data_storage()
        )
        channels["data_storage"] = _storage_channel(storage_raw)
        physical_raw = (
            physical_status
            if isinstance(physical_status, dict)
            else read_physical_sensors()
        )
        for name, spec in _PHYSICAL_CHANNELS.items():
            channel_raw = physical_raw.get(name)
            channels[name] = _physical_channel(
                channel_raw if isinstance(channel_raw, dict) else {}, name, *spec
            )
        observation = {"cycle": cycle, "channels": channels}

        states = self._derive_states(observation)
        events = self._advance_slow_state(observation, states)
        personal_report = self.personal.observe(
            states,
            raw,
            cycle=cycle,
            events=events,
            strain_active=self.strain_active,
        )
        for name, experience in self.personal.latest_experience.items():
            states[name]["expectedness"] = experience["expectedness"]
        experienced = [
            item["experienced"]
            for item in self.personal.latest_experience.values()
            if item["experienced"] is not None
        ]
        for event in events:
            if event["type"] == "hardware_strain" and experienced:
                event["intensity"] = max(experienced)
        if events:
            states["recovery"] = (
                _state(
                    1.0,
                    1.0,
                    "confirmed_recovery",
                    "mixed",
                    ["sustained_fresh_low_pressure"],
                )
                if any(event["type"] == "hardware_recovery" for event in events)
                else states["recovery"]
            )

        self.latest_observation = observation
        self.states = states
        self.last_cycle = cycle
        self.events.extend(deepcopy(events))
        self.events = self.events[-_EVENT_LIMIT:]
        self.history.append(
            {
                "cycle": cycle,
                "states": deepcopy(states),
                "events": deepcopy(events),
            }
        )
        self.history = self.history[-_HISTORY_LIMIT:]
        return {
            "mode": "shadow",
            "observation": deepcopy(observation),
            "states": deepcopy(states),
            "personal_experience": personal_report,
            "endocrine_events": deepcopy(events),
        }

    def _derive_states(self, observation: Dict) -> Dict:
        states = {name: _unknown_state("channel_unavailable") for name in _STATE_NAMES}
        process_cpu = _available(observation, "process_cpu")
        process_rss = _available(observation, "process_rss_ratio")
        host_cpu = _available(observation, "host_cpu")
        host_memory = _available(observation, "host_memory")

        own_parts = []
        own_evidence = []
        if process_cpu is not None:
            own_parts.append((_clamp(process_cpu / 100.0), 0.7))
            own_evidence.append(f"process_cpu={process_cpu:.3f}")
        if process_rss is not None:
            own_parts.append((_clamp(process_rss), 0.3))
            own_evidence.append(f"process_rss_ratio={process_rss:.3f}")
        if own_parts:
            weight = sum(weight for _, weight in own_parts)
            states["own_load"] = _state(
                sum(value * weight for value, weight in own_parts) / weight,
                1.0 if len(own_parts) == 2 else 0.6,
                "observed_process_load",
                "own",
                own_evidence,
            )

        host_parts = []
        host_evidence = []
        if host_cpu is not None:
            host_parts.append(_clamp(host_cpu / 100.0))
            host_evidence.append(f"host_cpu={host_cpu:.3f}")
        if host_memory is not None:
            host_parts.append(_clamp(host_memory / 100.0))
            host_evidence.append(f"host_memory={host_memory:.3f}")
        if host_parts:
            states["environmental_pressure"] = _state(
                max(host_parts),
                1.0 if len(host_parts) == 2 else 0.6,
                "observed_host_pressure",
                "external",
                host_evidence,
            )

        memory_parts = []
        memory_evidence = []
        if host_memory is not None:
            memory_parts.append(_clamp(host_memory / 100.0))
            memory_evidence.append(f"host_memory={host_memory:.3f}")
        if process_rss is not None:
            memory_parts.append(_clamp(process_rss))
            memory_evidence.append(f"process_rss_ratio={process_rss:.3f}")
        if memory_parts:
            origin = (
                "mixed"
                if len(memory_parts) == 2
                else ("external" if host_memory is not None else "own")
            )
            states["memory_pressure"] = _state(
                max(memory_parts),
                1.0 if len(memory_parts) == 2 else 0.6,
                "observed_memory_pressure",
                origin,
                memory_evidence,
            )

        free_ratio = _available(observation, "data_storage")
        if free_ratio is not None:
            previous = _available(self.latest_observation, "data_storage")
            risk = _clamp((0.25 - free_ratio) / 0.25)
            evidence = [f"data_free_ratio={free_ratio:.3f}"]
            confidence = 0.8
            if previous is not None:
                drop = max(0.0, previous - free_ratio)
                risk = max(risk, _clamp(drop * 2.0))
                evidence.append(f"data_free_ratio_drop={drop:.3f}")
                confidence = 1.0
            states["storage_risk"] = _state(
                risk, confidence, "observed_data_storage", "unknown", evidence
            )

        physical_parts = []
        physical_evidence = []
        for name in (
            "gpu_utilization",
            "gpu_memory",
            "gpu_temperature",
            "gpu_power",
            "cpu_temperature",
        ):
            value = _available(observation, name)
            if value is None:
                continue
            if name in {"gpu_temperature", "cpu_temperature"}:
                risk = _clamp((value - 60.0) / 40.0)
            elif name == "gpu_utilization":
                risk = _clamp(value / 100.0)
            else:
                risk = _clamp(value)
            physical_parts.append(risk)
            physical_evidence.append(f"{name}={value:.3f}")
        if physical_parts:
            states["physical_strain"] = _state(
                max(physical_parts),
                min(1.0, len(physical_parts) / 3.0),
                "observed_physical_channels",
                "unknown",
                physical_evidence,
            )

        pressure_parts = [
            states[name]
            for name in ("own_load", "environmental_pressure", "storage_risk")
            if states[name]["value"] is not None
        ]
        core_complete = all(
            states[name]["value"] is not None
            for name in ("own_load", "environmental_pressure")
        )
        if core_complete:
            strongest = max(pressure_parts, key=lambda item: item["value"])
            states["reserve"] = _state(
                1.0 - strongest["value"],
                min(item["confidence"] for item in pressure_parts),
                "estimated_from_available_channels",
                "mixed",
                ["available_pressure_channels"],
            )

        if self.strain_active:
            states["recovery"] = (
                _state(0.0, 1.0, "recovery_not_confirmed", "mixed", [])
                if core_complete
                else _unknown_state("recovery_not_verifiable")
            )
        elif core_complete:
            states["recovery"] = _state(
                0.0, 1.0, "no_preceding_sustained_strain", "mixed", []
            )
        return states

    def _advance_slow_state(self, observation: Dict, states: Dict) -> list:
        pressure_states = [
            states[name]
            for name in ("own_load", "environmental_pressure", "storage_risk")
            if states[name]["value"] is not None
        ]
        pressure = max((item["value"] for item in pressure_states), default=0.0)
        core_complete = all(
            states[name]["value"] is not None
            for name in ("own_load", "environmental_pressure")
        )
        # Один спокойный вторичный канал не доказывает восстановление,
        # пока основные датчики собственной и внешней нагрузки недоступны.
        if not core_complete and pressure < _STRAIN_THRESHOLD:
            self.sustained_pressure_cycles = 0
            self.low_pressure_cycles = 0
            return []
        strongest = max(pressure_states, key=lambda item: item["value"])

        if pressure >= _STRAIN_THRESHOLD:
            self.sustained_pressure_cycles += 1
            self.low_pressure_cycles = 0
            if (
                self.sustained_pressure_cycles >= _STRAIN_AFTER_CYCLES
                and not self.strain_active
            ):
                self.strain_active = True
                return [
                    {
                        "type": "hardware_strain",
                        "intensity": pressure,
                        "quality": "negative",
                        "reason": "sustained_resource_pressure",
                        "origin": strongest["origin"],
                        "expectedness": "unknown",
                        "evidence": list(strongest["evidence"]),
                        "duration_cycles": self.sustained_pressure_cycles,
                    }
                ]
            return []

        self.sustained_pressure_cycles = 0
        if pressure > _RECOVERY_THRESHOLD:
            self.low_pressure_cycles = 0
            return []
        if not self.strain_active:
            self.low_pressure_cycles = 0
            return []

        self.low_pressure_cycles += 1
        if self.low_pressure_cycles < _RECOVERY_AFTER_CYCLES:
            return []
        duration = self.low_pressure_cycles
        self.strain_active = False
        self.low_pressure_cycles = 0
        return [
            {
                "type": "hardware_recovery",
                "intensity": 1.0 - pressure,
                "quality": "positive",
                "reason": "confirmed_recovery",
                "origin": strongest["origin"],
                "expectedness": "unknown",
                "evidence": ["sustained_fresh_low_pressure"],
                "duration_cycles": duration,
            }
        ]

    def status(self) -> Dict:
        return {
            "mode": "shadow",
            "observation": deepcopy(self.latest_observation),
            "states": deepcopy(self.states),
            "strain_active": self.strain_active,
            "sustained_pressure_cycles": self.sustained_pressure_cycles,
            "low_pressure_cycles": self.low_pressure_cycles,
            "history_count": len(self.history),
            "recent_events": deepcopy(self.events[-10:]),
            **self.personal.status(),
        }

    def to_checkpoint(self) -> Dict:
        return {
            "schema_version": 3,
            "latest_observation": deepcopy(self.latest_observation),
            "states": deepcopy(self.states),
            "history": deepcopy(self.history),
            "events": deepcopy(self.events),
            "last_cycle": self.last_cycle,
            "sustained_pressure_cycles": self.sustained_pressure_cycles,
            "low_pressure_cycles": self.low_pressure_cycles,
            "strain_active": self.strain_active,
            **self.personal.to_checkpoint(),
        }

    @classmethod
    def from_checkpoint(cls, data: Dict) -> "HardwareInteroception":
        validate_hardware_interoception(data)
        restored = cls()
        restored.latest_observation = deepcopy(data.get("latest_observation") or {})
        channels = restored.latest_observation.get("channels") or {}
        if data["schema_version"] < 3 and channels:
            for name in _PHYSICAL_CHANNELS:
                channels[name] = {
                    "status": "unavailable",
                    "value": None,
                    "unit": _PHYSICAL_CHANNELS[name][2],
                    "reason": "resource_source_unavailable",
                    "source": _CHANNEL_SOURCES[name],
                }
        for name, channel in channels.items():
            default_source = _CHANNEL_SOURCES.get(name, "watchdog")
            channel["source"] = _diagnostic_source(
                channel.get("source"), default_source
            )
            if channel.get("status") == "available":
                channel["status"] = "stale"
                channel["reason"] = "waiting_for_fresh_observation_after_restart"
            else:
                channel["reason"] = _diagnostic_reason(channel.get("reason"))
        restored.states = {
            name: _unknown_state("waiting_for_fresh_observation_after_restart")
            for name in _STATE_NAMES
        }
        restored.history = deepcopy(list(data.get("history") or []))[-_HISTORY_LIMIT:]
        restored.events = deepcopy(list(data.get("events") or []))[-_EVENT_LIMIT:]
        restored.last_cycle = data.get("last_cycle")
        restored.sustained_pressure_cycles = data.get("sustained_pressure_cycles", 0)
        restored.low_pressure_cycles = data.get("low_pressure_cycles", 0)
        restored.strain_active = bool(data.get("strain_active", False))
        if data["schema_version"] in {2, 3}:
            restored.personal = HardwarePersonalProfile.from_checkpoint(data)
        return restored


def _validation_number(value, path: str, *, low=0.0, high=1.0) -> None:
    if (
        not _finite_number(value)
        or float(value) < low
        or (high is not None and float(value) > high)
    ):
        raise ValueError(f"{path}: expected a finite number in range")


def _validation_states(states, path: str) -> None:
    if not isinstance(states, dict) or set(states) != set(_STATE_NAMES):
        raise ValueError(f"{path}: unknown or missing state")
    for name, state in states.items():
        state_path = f"{path}.{name}"
        if not isinstance(state, dict):
            raise ValueError(f"{state_path}: expected dictionary")
        value = state.get("value")
        if value is not None:
            _validation_number(value, f"{state_path}.value")
        _validation_number(state.get("confidence"), f"{state_path}.confidence")
        if state.get("origin") not in {"own", "external", "mixed", "unknown"}:
            raise ValueError(f"{state_path}.origin: unknown origin")
        if not isinstance(state.get("reason"), str) or not isinstance(
            state.get("expectedness"), str
        ):
            raise ValueError(f"{state_path}: expected textual reason and expectedness")
        evidence = state.get("evidence")
        if (
            not isinstance(evidence, list)
            or len(evidence) > 8
            or not all(isinstance(item, str) for item in evidence)
        ):
            raise ValueError(f"{state_path}.evidence: expected a bounded string list")


def _validation_observation(observation, path: str, schema_version: int) -> None:
    if not isinstance(observation, dict):
        raise ValueError(f"{path}: expected dictionary")
    if not observation:
        return
    cycle = observation.get("cycle")
    if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 0:
        raise ValueError(f"{path}.cycle: expected a nonnegative integer")
    channels = observation.get("channels")
    expected = set(_RESOURCE_CHANNELS) | {"data_storage"}
    if schema_version >= 3:
        expected |= set(_PHYSICAL_CHANNELS)
    if not isinstance(channels, dict) or set(channels) != expected:
        raise ValueError(f"{path}.channels: unknown or missing channel")
    for name, channel in channels.items():
        channel_path = f"{path}.channels.{name}"
        if not isinstance(channel, dict):
            raise ValueError(f"{channel_path}: expected dictionary")
        if channel.get("status") not in {"available", "unavailable", "stale"}:
            raise ValueError(f"{channel_path}.status: unknown status")
        value = channel.get("value")
        if value is not None:
            high = _PHYSICAL_CHANNELS.get(name, (0.0, None, ""))[1]
            _validation_number(value, f"{channel_path}.value", high=high)
        for field in ("reason", "source"):
            if not isinstance(channel.get(field), str):
                raise ValueError(f"{channel_path}.{field}: expected a string")
        for field in ("free_bytes", "total_bytes"):
            if field in channel and (
                isinstance(channel[field], bool)
                or not isinstance(channel[field], int)
                or channel[field] < 0
            ):
                raise ValueError(
                    f"{channel_path}.{field}: expected a nonnegative integer"
                )


def _validation_events(events, path: str, limit: int) -> None:
    if not isinstance(events, list) or len(events) > limit:
        raise ValueError(f"{path}: expected a bounded list")
    for index, event in enumerate(events):
        event_path = f"{path}[{index}]"
        if not isinstance(event, dict) or event.get("type") not in {
            "hardware_strain",
            "hardware_recovery",
        }:
            raise ValueError(f"{event_path}: unknown hardware event")
        _validation_number(event.get("intensity"), f"{event_path}.intensity")
        if event.get("origin") not in {"own", "external", "mixed", "unknown"}:
            raise ValueError(f"{event_path}.origin: unknown origin")
        duration = event.get("duration_cycles")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            raise ValueError(
                f"{event_path}.duration_cycles: expected nonnegative integer"
            )
        evidence = event.get("evidence")
        if (
            not isinstance(evidence, list)
            or len(evidence) > 8
            or not all(isinstance(item, str) for item in evidence)
        ):
            raise ValueError(f"{event_path}.evidence: expected a bounded string list")


def validate_hardware_interoception(state: Dict) -> None:
    if not isinstance(state, dict) or state.get("schema_version") not in {1, 2, 3}:
        raise ValueError("hardware_interoception.schema_version: unsupported")
    if state["schema_version"] in {2, 3}:
        validate_personal_experience(state)
    _validation_observation(
        state.get("latest_observation"),
        "hardware_interoception.latest_observation",
        state["schema_version"],
    )
    _validation_states(state.get("states"), "hardware_interoception.states")
    history = state.get("history")
    if not isinstance(history, list) or len(history) > _HISTORY_LIMIT:
        raise ValueError("hardware_interoception.history: expected a bounded list")
    for index, entry in enumerate(history):
        path = f"hardware_interoception.history[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: expected dictionary")
        cycle = entry.get("cycle")
        if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 0:
            raise ValueError(f"{path}.cycle: expected a nonnegative integer")
        _validation_states(entry.get("states"), f"{path}.states")
        _validation_events(entry.get("events"), f"{path}.events", 2)
    _validation_events(
        state.get("events"), "hardware_interoception.events", _EVENT_LIMIT
    )
    last_cycle = state.get("last_cycle")
    if last_cycle is not None and (
        isinstance(last_cycle, bool)
        or not isinstance(last_cycle, int)
        or last_cycle < 0
    ):
        raise ValueError(
            "hardware_interoception.last_cycle: expected nonnegative integer"
        )
    for field in ("sustained_pressure_cycles", "low_pressure_cycles"):
        value = state.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                f"hardware_interoception.{field}: expected nonnegative integer"
            )
    if not isinstance(state.get("strain_active"), bool):
        raise ValueError("hardware_interoception.strain_active: expected boolean")


def initialize_hardware_interoception(agent) -> HardwareInteroception:
    observer = HardwareInteroception()
    agent.hardware_interoception = observer
    return observer


def observe_hardware_interoception(
    agent, resource_status: Optional[Dict], cycle: int
) -> Optional[Dict]:
    observer = getattr(agent, "hardware_interoception", None)
    if observer is None:
        return None
    try:
        report = observer.observe(resource_status, cycle=int(cycle))
    except Exception as exc:
        get_logger().log(f"[HARDWARE_INTEROCEPTION] observation error: {exc}")
        return {"mode": "shadow", "error": str(exc)}

    hormones = getattr(agent, "hormonal_system", None)
    processed = 0
    for event in report.get("endocrine_events") or []:
        if hormones is None:
            break
        try:
            hormones.process_event(event["type"], event["intensity"], event["quality"])
            processed += 1
        except Exception as exc:
            get_logger().log(f"[HARDWARE_INTEROCEPTION] projection error: {exc}")
    report["projection"] = {"mode": "shadow", "processed_events": processed}
    return report


__all__ = [
    "HardwareInteroception",
    "initialize_hardware_interoception",
    "observe_hardware_interoception",
    "read_data_storage",
    "validate_hardware_interoception",
]
