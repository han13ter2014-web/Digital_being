"""Физические датчики: агрегаты NVML, независимость источников и приватность."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace
import sys

from src.core import hardware_sensors


class _FakeNvml:
    def __init__(self):
        self.shutdown_called = False

    def nvmlInit_v2(self):
        return 0

    def nvmlShutdown(self):
        self.shutdown_called = True
        return 0

    def nvmlDeviceGetCount_v2(self, pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint)).contents.value = 2
        return 0

    def nvmlDeviceGetHandleByIndex_v2(self, index, pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p)).contents.value = index + 1
        return 0

    def nvmlDeviceGetUtilizationRates(self, handle, pointer):
        entry = ctypes.cast(
            pointer, ctypes.POINTER(hardware_sensors._NvmlUtilization)
        ).contents
        entry.gpu = 20 if handle.value == 1 else 80
        entry.memory = 0
        return 0

    def nvmlDeviceGetMemoryInfo(self, handle, pointer):
        entry = ctypes.cast(
            pointer, ctypes.POINTER(hardware_sensors._NvmlMemory)
        ).contents
        entry.total = 100
        entry.used = 25 if handle.value == 1 else 75
        entry.free = 100 - entry.used
        return 0

    def nvmlDeviceGetTemperature(self, handle, _sensor, pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint)).contents.value = (
            40 if handle.value == 1 else 70
        )
        return 0

    def nvmlDeviceGetPowerUsage(self, handle, pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint)).contents.value = (
            50 if handle.value == 1 else 90
        )
        return 0

    def nvmlDeviceGetPowerManagementLimit(self, _handle, pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint)).contents.value = 100
        return 0


def test_nvml_returns_only_bounded_maximum_aggregates_and_shuts_down(monkeypatch):
    fake = _FakeNvml()
    monkeypatch.setattr(hardware_sensors, "_load_nvml", lambda: fake)

    result = hardware_sensors._read_nvml()

    assert result["gpu_utilization"]["value"] == 80.0
    assert result["gpu_memory"]["value"] == 0.75
    assert result["gpu_temperature"]["value"] == 70.0
    assert result["gpu_power"]["value"] == 0.9
    assert {item["source"] for item in result.values()} == {"nvml"}
    assert fake.shutdown_called is True
    assert "handle" not in str(result)
    assert "index" not in str(result)


def test_missing_nvml_does_not_invent_zeroes(monkeypatch):
    monkeypatch.setattr(hardware_sensors, "_load_nvml", lambda: None)
    result = hardware_sensors._read_nvml()
    assert all(item["available"] is False for item in result.values())
    assert all("value" not in item for item in result.values())


def test_cpu_temperature_filters_other_thermal_zones(monkeypatch):
    fake = SimpleNamespace(
        sensors_temperatures=lambda _fahrenheit: {
            "secret motherboard name": [SimpleNamespace(label="ambient", current=90.0)],
            "coretemp": [
                SimpleNamespace(label="Package id 0", current=65.0),
                SimpleNamespace(label="Core 0", current=70.0),
            ],
        }
    )
    monkeypatch.setitem(sys.modules, "psutil", fake)

    result = hardware_sensors._read_cpu_temperature()

    assert result == {"available": True, "value": 70.0, "source": "psutil"}
    assert "secret motherboard name" not in str(result)


def test_physical_sources_remain_independent(monkeypatch):
    monkeypatch.setattr(
        hardware_sensors,
        "_read_nvml",
        lambda: {
            name: {"available": False, "reason": "source_error", "source": "nvml"}
            for name in hardware_sensors._NVML_CHANNELS
        },
    )
    monkeypatch.setattr(
        hardware_sensors,
        "_read_cpu_temperature",
        lambda: {"available": False, "reason": "source_error", "source": "psutil"},
    )
    power = {
        "external_power": {"available": True, "value": 1.0, "source": "test"},
        "battery_charge": {
            "available": False,
            "reason": "resource_source_unavailable",
            "source": "test",
        },
    }
    monkeypatch.setattr(hardware_sensors, "_read_windows_power", lambda: power)
    monkeypatch.setattr(hardware_sensors, "_read_psutil_power", lambda: power)

    result = hardware_sensors.read_physical_sensors()

    assert result["gpu_utilization"]["available"] is False
    assert result["external_power"]["value"] == 1.0
    assert result["battery_charge"]["available"] is False
