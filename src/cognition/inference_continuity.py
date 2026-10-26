"""Состояние обучения Active Inference, отдельно от неизменяемой структуры модели."""

from collections import deque
from copy import deepcopy
import math


def _plain(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [_plain(item) for item in value]
    return value


def capture_inference(engine):
    return {"version": 1,
            "states": {name: {"prior": state.prior.tolist(), "posterior": state.posterior.tolist()}
                       for name, state in engine.model.hidden_states.items()},
            "actions": {name: {key: matrix.tolist() for key, matrix in action.transitions.items()}
                        for name, action in engine.model.actions.items()},
            "temperature": engine.temperature, "min_temperature": engine.min_temperature,
            "temperature_decay": engine.temperature_decay,
            "experience_buffer": _plain(engine.experience_buffer),
            "action_history": _plain(engine.action_history),
            "free_energy_history": list(engine.inference.free_energy_history)}


def validate_inference(data, engine=None):
    import numpy as np

    def fail(field):
        raise ValueError(f"active_inference.{field}: несовместимые или некорректные данные")

    if not isinstance(data, dict) or data.get("version") != 1:
        fail("version")
    states, actions = data.get("states"), data.get("actions")
    if not isinstance(states, dict) or not isinstance(actions, dict):
        fail("model")
    if engine is not None and (set(states) != set(engine.model.hidden_states) or set(actions) != set(engine.model.actions)):
        fail("model.names")
    dimensions = {}
    for name, state in states.items():
        if not isinstance(state, dict):
            fail("states")
        for field in ("prior", "posterior"):
            try:
                vector = np.asarray(state[field], dtype=float)
            except (KeyError, TypeError, ValueError):
                fail(f"states.{name}.{field}")
            if vector.ndim != 1 or not vector.size or not np.isfinite(vector).all() or (vector < 0).any() or not np.isclose(vector.sum(), 1):
                fail(f"states.{name}.{field}")
            if name in dimensions and dimensions[name] != vector.size:
                fail(f"states.{name}.shape")
            dimensions[name] = vector.size
        if engine is not None and dimensions[name] != engine.model.hidden_states[name].dim:
            fail(f"states.{name}.shape")
    for name, transitions in actions.items():
        if not isinstance(transitions, dict):
            fail("actions")
        if engine is not None and set(transitions) != set(engine.model.actions[name].transitions):
            fail(f"actions.{name}.names")
        for key, values in transitions.items():
            try:
                matrix = np.asarray(values, dtype=float)
            except (TypeError, ValueError):
                fail(f"actions.{name}.{key}")
            # В исходной модели есть переход cognitive_coherence без
            # одноимённого hidden state. Сохраняем его без переинтерпретации,
            # при применении сверяем с конкретной структурой движка.
            dim = dimensions.get(key, matrix.shape[0] if matrix.ndim == 2 else 0)
            if engine is not None and matrix.shape != engine.model.actions[name].transitions[key].shape:
                fail(f"actions.{name}.{key}.shape")
            if not dim or matrix.shape != (dim, dim) or not np.isfinite(matrix).all() or (matrix < 0).any() or not np.allclose(matrix.sum(axis=1), 1):
                fail(f"actions.{name}.{key}")
    for field in ("temperature", "min_temperature", "temperature_decay"):
        value = data.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            fail(field)
    for field, limit in (("experience_buffer", 1000), ("action_history", 100), ("free_energy_history", 100)):
        if not isinstance(data.get(field), list) or len(data[field]) > limit:
            fail(field)
    for entry in data["experience_buffer"]:
        # Буфер содержит и действия вне генеративной модели; обучение
        # пропускает их, но это не делает само наблюдение повреждённым.
        if not isinstance(entry, dict) or not isinstance(entry.get("action"), str) or not entry["action"].strip():
            fail("experience_buffer.action")
        for field in ("obs_before", "obs_after", "beliefs_before"):
            if not isinstance(entry.get(field), dict):
                fail(f"experience_buffer.{field}")
        for field in ("obs_before", "obs_after"):
            for modality, index in entry[field].items():
                if not isinstance(modality, str) or isinstance(index, bool) or not isinstance(index, int) or index < 0:
                    fail(f"experience_buffer.{field}")
                if engine is not None and modality in engine.model.observations and index >= engine.model.observations[modality].dim:
                    fail(f"experience_buffer.{field}.{modality}")
        for name, belief in entry["beliefs_before"].items():
            try:
                vector = np.asarray(belief, dtype=float)
            except (TypeError, ValueError):
                fail("experience_buffer.beliefs_before")
            if name not in dimensions or vector.shape != (dimensions[name],) or not np.isfinite(vector).all() or (vector < 0).any() or not np.isclose(vector.sum(), 1):
                fail("experience_buffer.beliefs_before")
        value = entry.get("reward")
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            fail("experience_buffer.reward")
    for value in data["free_energy_history"]:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            fail("free_energy_history")


def restore_inference(engine, data):
    import numpy as np

    validate_inference(data, engine)
    for name, saved in data["states"].items():
        engine.model.hidden_states[name].prior = np.array(saved["prior"], dtype=float)
        engine.model.hidden_states[name].posterior = np.array(saved["posterior"], dtype=float)
    for name, transitions in data["actions"].items():
        engine.model.actions[name].transitions = {key: np.array(value, dtype=float) for key, value in transitions.items()}
    for field in ("temperature", "min_temperature", "temperature_decay"):
        setattr(engine, field, data[field])
    engine.experience_buffer = deque(deepcopy(data["experience_buffer"]), maxlen=1000)
    engine.action_history = deque(deepcopy(data["action_history"]), maxlen=100)
    engine.inference.free_energy_history = deque(data["free_energy_history"], maxlen=100)
