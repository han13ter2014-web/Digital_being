"""Необязательные read-only физические датчики без раскрытия деталей ОС.

Каждый канал возвращается независимо. Названия устройств, thermal-зон, UUID,
индексы GPU и тексты исключений не покидают этот модуль.
"""

from __future__ import annotations

import ctypes
import math
import os
from typing import Dict, Iterable, Optional


_PHYSICAL_CHANNELS = (
    "gpu_utilization",
    "gpu_memory",
    "gpu_temperature",
    "gpu_power",
    "cpu_temperature",
    "external_power",
    "battery_charge",
)
_NVML_CHANNELS = (
    "gpu_utilization",
    "gpu_memory",
    "gpu_temperature",
    "gpu_power",
)


def _unavailable(source: str) -> Dict:
    return {
        "available": False,
        "reason": "resource_source_unavailable",
        "source": source,
    }


def _available(value: float, source: str) -> Dict:
    return {"available": True, "value": float(value), "source": source}


def _empty(source: str) -> Dict[str, Dict]:
    return {name: _unavailable(source) for name in _PHYSICAL_CHANNELS}


def _finite(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


def _load_nvml() -> Optional[ctypes.CDLL]:
    candidates = (
        ("nvml.dll",) if os.name == "nt" else ("libnvidia-ml.so.1", "libnvidia-ml.so")
    )
    for candidate in candidates:
        try:
            return ctypes.CDLL(candidate)
        except (OSError, AttributeError):
            continue
    return None


def _call_nvml(library: ctypes.CDLL, name: str, *args) -> bool:
    try:
        function = getattr(library, name)
    except AttributeError:
        return False
    try:
        return int(function(*args)) == 0
    except (OSError, TypeError, ValueError):
        return False


def _nvml_maximums(library: ctypes.CDLL) -> Dict[str, list[float]]:
    values: Dict[str, list[float]] = {name: [] for name in _NVML_CHANNELS}
    count = ctypes.c_uint()
    if not _call_nvml(library, "nvmlDeviceGetCount_v2", ctypes.byref(count)):
        return values
    # Верхний предел защищает наблюдателя от повреждённого ответа библиотеки.
    for index in range(min(int(count.value), 64)):
        handle = ctypes.c_void_p()
        if not _call_nvml(
            library, "nvmlDeviceGetHandleByIndex_v2", index, ctypes.byref(handle)
        ):
            continue

        utilization = _NvmlUtilization()
        if _call_nvml(
            library,
            "nvmlDeviceGetUtilizationRates",
            handle,
            ctypes.byref(utilization),
        ):
            values["gpu_utilization"].append(float(utilization.gpu))

        memory = _NvmlMemory()
        if (
            _call_nvml(library, "nvmlDeviceGetMemoryInfo", handle, ctypes.byref(memory))
            and memory.total > 0
        ):
            values["gpu_memory"].append(float(memory.used) / float(memory.total))

        temperature = ctypes.c_uint()
        if _call_nvml(
            library,
            "nvmlDeviceGetTemperature",
            handle,
            0,  # NVML_TEMPERATURE_GPU; идентификатор устройства не публикуется.
            ctypes.byref(temperature),
        ):
            values["gpu_temperature"].append(float(temperature.value))

        power = ctypes.c_uint()
        limit = ctypes.c_uint()
        if (
            _call_nvml(library, "nvmlDeviceGetPowerUsage", handle, ctypes.byref(power))
            and _call_nvml(
                library,
                "nvmlDeviceGetPowerManagementLimit",
                handle,
                ctypes.byref(limit),
            )
            and limit.value > 0
        ):
            values["gpu_power"].append(float(power.value) / float(limit.value))
    return values


def _read_nvml() -> Dict[str, Dict]:
    result = {name: _unavailable("nvml") for name in _NVML_CHANNELS}
    library = _load_nvml()
    if library is None:
        return result
    initialized = False
    try:
        initialized = _call_nvml(library, "nvmlInit_v2")
        if not initialized:
            return result
        for name, values in _nvml_maximums(library).items():
            if values:
                result[name] = _available(max(values), "nvml")
        return result
    finally:
        if initialized:
            _call_nvml(library, "nvmlShutdown")


def _iter_cpu_temperatures(readings) -> Iterable[float]:
    if not isinstance(readings, dict):
        return
    allowed_groups = {"coretemp", "k10temp", "cpu_thermal", "cpu-thermal"}
    for group, entries in readings.items():
        group_name = str(group).lower()
        if not isinstance(entries, (list, tuple)):
            continue
        for entry in entries:
            label = str(getattr(entry, "label", "") or "").lower()
            is_cpu = group_name in allowed_groups or any(
                token in label for token in ("cpu", "package", "core")
            )
            current = getattr(entry, "current", None)
            if is_cpu and _finite(current) and 0.0 <= float(current) <= 150.0:
                yield float(current)


def _read_cpu_temperature() -> Dict:
    try:
        import psutil  # type: ignore
    except ImportError:
        return _unavailable("psutil")
    function = getattr(psutil, "sensors_temperatures", None)
    if function is None:
        return _unavailable("psutil")
    try:
        values = list(_iter_cpu_temperatures(function(False)))
    except Exception:
        return _unavailable("psutil")
    return _available(max(values), "psutil") if values else _unavailable("psutil")


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ac_line_status", ctypes.c_byte),
        ("battery_flag", ctypes.c_byte),
        ("battery_life_percent", ctypes.c_byte),
        ("system_status_flag", ctypes.c_byte),
        ("battery_life_time", ctypes.c_uint32),
        ("battery_full_life_time", ctypes.c_uint32),
    ]


def _read_windows_power() -> Dict[str, Dict]:
    result = {
        "external_power": _unavailable("windows"),
        "battery_charge": _unavailable("windows"),
    }
    status = _SystemPowerStatus()
    try:
        function = ctypes.windll.kernel32.GetSystemPowerStatus
        function.argtypes = [ctypes.POINTER(_SystemPowerStatus)]
        function.restype = ctypes.c_int
        if not function(ctypes.byref(status)):
            return result
    except (AttributeError, OSError, TypeError, ValueError):
        return result
    if status.ac_line_status in (0, 1):
        result["external_power"] = _available(status.ac_line_status, "windows")
    # 255 означает неизвестно; флаг 128 — батарея отсутствует.
    battery_flag = int(status.battery_flag) & 0xFF
    battery_percent = int(status.battery_life_percent) & 0xFF
    if battery_flag & 128 == 0 and 0 <= battery_percent <= 100:
        result["battery_charge"] = _available(battery_percent, "windows")
    return result


def _read_psutil_power() -> Dict[str, Dict]:
    result = {
        "external_power": _unavailable("psutil"),
        "battery_charge": _unavailable("psutil"),
    }
    try:
        import psutil  # type: ignore
    except ImportError:
        return result
    function = getattr(psutil, "sensors_battery", None)
    if function is None:
        return result
    try:
        battery = function()
    except Exception:
        return result
    if battery is None:
        return result
    percent = getattr(battery, "percent", None)
    if _finite(percent) and 0.0 <= float(percent) <= 100.0:
        result["battery_charge"] = _available(float(percent), "psutil")
    plugged = getattr(battery, "power_plugged", None)
    if isinstance(plugged, bool):
        result["external_power"] = _available(1.0 if plugged else 0.0, "psutil")
    return result


def read_physical_sensors() -> Dict[str, Dict]:
    """Прочитать независимые каналы; отказ одного источника не скрывает другие."""
    result = _empty("resource")
    result.update(_read_nvml())
    result["cpu_temperature"] = _read_cpu_temperature()
    result.update(_read_windows_power() if os.name == "nt" else _read_psutil_power())
    return result


__all__ = ["read_physical_sensors"]
