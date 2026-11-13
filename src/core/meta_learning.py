"""
Meta-Learning гиперпараметров — агент учится учиться.
"""

import numpy as np
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import deque
from src.core.buffered_logger import get_logger

logger = get_logger()


@dataclass
class HyperParameter:
    name: str
    value: float
    min_val: float
    max_val: float
    learning_rate: float = 0.01
    history: List[float] = field(default_factory=list)
    gradient_estimate: float = 0.0

    def mutate(self, scale: float = 1.0):
        noise = np.random.randn() * self.learning_rate * scale
        self.value = np.clip(self.value + noise, self.min_val, self.max_val)
        self.history.append(self.value)

    def gradient_step(self, gradient: float):
        self.value = np.clip(
            self.value + self.learning_rate * gradient, self.min_val, self.max_val
        )
        self.history.append(self.value)

    def get_status(self) -> Dict:
        return {
            "name": self.name,
            "value": self.value,
            "range": [self.min_val, self.max_val],
            "recent_mean": np.mean(self.history[-10:]) if self.history else self.value,
            "recent_std": np.std(self.history[-10:]) if len(self.history) > 1 else 0.0,
        }


class MetaLearner:
    """Саморазвитие и гомеостаз в реальных условиях хоста.

    Ресурсное давление — самостоятельный драйвер адаптации, а не компонент
    абстрактного fitness. При высокой загрузке хоста или собственном росте RSS
    существо увеличивает ``cycle_interval_scale`` и реже выполняет жизненный
    цикл. Пока давление сохраняется, экономный режим не откатывается: общий CPU
    может оставаться занятым внешней программой. Возврат к более активной жизни
    происходит постепенно и только после устойчивого окна низкого давления.

    Это первый контур адаптации к среде. Он не доказывает причинную эффективность
    других гиперпараметров и не запускает их случайную мутацию в основном цикле.
    """

    def __init__(self, agent):
        self.agent = agent
        self.hyperparams: Dict[str, HyperParameter] = {}
        self.population: List[Dict[str, float]] = []
        self.population_size = 8
        self.elite_fraction = 0.25
        self.mutation_rate = 0.1
        self.eval_window = 100
        self.cycle_counter = 0
        self.best_config: Optional[Dict] = None
        self.best_fitness = -float("inf")
        self.fitness_history: deque = deque(maxlen=50)
        self.resource_high_threshold = 0.85
        self.resource_low_threshold = 0.6
        self.resource_recovery_cycles = 100
        self.resource_low_pressure_cycles = 0
        self.resource_adaptation_history: deque = deque(maxlen=50)
        self.last_resource_status: Dict = {}

        self._register_default_hyperparams()
        self._init_population()

        logger.log(
            f"[META_LEARNING] Initialized with {len(self.hyperparams)} hyperparameters"
        )

    def _register_default_hyperparams(self):
        self.register("need_decay_base", 0.01, 0.001, 0.05)
        self.register("need_growth_base", 0.02, 0.005, 0.1)
        self.register("ai_learning_rate", 0.05, 0.005, 0.2)
        self.register("ai_temperature", 1.0, 0.1, 3.0)
        self.register("ai_temperature_decay", 0.9995, 0.99, 0.9999)
        self.register("ai_policy_length", 3, 1, 10)
        self.register("fatigue_tau", 30.0, 2.0, 50.0)
        self.register("glucose_to_atp_eff", 0.6, 0.1, 0.8)
        self.register("mito_stress_response", 0.1, 0.01, 0.5)
        self.register("retention_compression", 0.95, 0.8, 0.99)
        self.register("protension_horizon", 30.0, 5.0, 120.0)
        self.register("time_dilation_novelty", 0.8, 0.2, 2.0)
        self.register("cycle_interval_scale", 1.0, 1.0, 8.0)

    def register(
        self,
        name: str,
        value: float,
        min_val: float,
        max_val: float,
        learning_rate: float = 0.01,
    ):
        self.hyperparams[name] = HyperParameter(
            name, value, min_val, max_val, learning_rate
        )

    def _init_population(self):
        for _ in range(self.population_size):
            config = {}
            for name, hp in self.hyperparams.items():
                if hp.max_val / hp.min_val > 10:
                    log_min, log_max = np.log(hp.min_val), np.log(hp.max_val)
                    config[name] = np.exp(np.random.uniform(log_min, log_max))
                else:
                    config[name] = np.random.uniform(hp.min_val, hp.max_val)
            self.population.append(config)
        self.population[0] = self._get_current_config()

    def _get_current_config(self) -> Dict[str, float]:
        return {name: hp.value for name, hp in self.hyperparams.items()}

    def _apply_config(self, config: Dict[str, float]):
        for name, value in config.items():
            if name in self.hyperparams:
                self.hyperparams[name].value = value
        self._push_to_subsystems()

    def _push_to_subsystems(self):
        hp = self.hyperparams

        if hasattr(self.agent, "internal_motivation"):
            im = self.agent.internal_motivation
            im.need_decay_base = hp.get(
                "need_decay_base", HyperParameter("", 0.01, 0, 0)
            ).value
            im.need_growth_base = hp.get(
                "need_growth_base", HyperParameter("", 0.02, 0, 0)
            ).value

        if hasattr(self.agent, "active_inference"):
            ai = self.agent.active_inference
            ai.learning_rate = hp.get(
                "ai_learning_rate", HyperParameter("", 0.05, 0, 0)
            ).value
            ai.temperature = hp.get(
                "ai_temperature", HyperParameter("", 1.0, 0, 0)
            ).value
            ai.temperature_decay = hp.get(
                "ai_temperature_decay", HyperParameter("", 0.9995, 0, 0)
            ).value
            ai.policy_length = int(
                hp.get("ai_policy_length", HyperParameter("", 3, 0, 0)).value
            )

        if hasattr(self.agent, "interoception"):
            ic = self.agent.interoception
            ic.state.fatigue_integration_tau = hp.get(
                "fatigue_tau", HyperParameter("", 30.0, 0, 0)
            ).value
            ic.glucose_to_atp_efficiency = hp.get(
                "glucose_to_atp_eff", HyperParameter("", 0.6, 0, 0)
            ).value
            ic.mito_stress_response = hp.get(
                "mito_stress_response", HyperParameter("", 0.1, 0, 0)
            ).value

        if hasattr(self.agent, "continuous_time"):
            ct = self.agent.continuous_time
            ct.retention.compression_rate = hp.get(
                "retention_compression", HyperParameter("", 0.95, 0, 0)
            ).value
            ct.protension.horizon = hp.get(
                "protension_horizon", HyperParameter("", 30.0, 0, 0)
            ).value
            ct.subjective_time.dilation = hp.get(
                "time_dilation_novelty", HyperParameter("", 0.8, 0, 0)
            ).value

    def step(
        self,
        fitness_signal: float = None,
        *,
        adapt: bool = True,
        resource_status: Optional[Dict] = None,
    ):
        """Сохранить опыт и адаптировать темп к наблюдаемым ресурсам.

        ``adapt=False`` остаётся режимом наблюдения. При ``adapt=True`` основной
        контур выполняет только ограниченную ресурсную регуляцию, а не случайную
        эволюцию всех подсистем. Отсутствие метрик не означает ни опасность, ни
        безопасность и потому не меняет конфигурацию.
        """
        self.cycle_counter += 1
        if fitness_signal is not None:
            self.fitness_history.append(float(fitness_signal))
        if adapt and resource_status is not None:
            self._adapt_to_resources(resource_status)
        if self.cycle_counter % self.eval_window == 0:
            current_fitness = self._compute_fitness()
            if current_fitness > self.best_fitness:
                self.best_fitness = current_fitness
                self.best_config = self._get_current_config().copy()

    def _adapt_to_resources(self, status: Dict) -> None:
        if not isinstance(status, dict) or not status.get("available", False):
            return
        score = status.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            return
        if not np.isfinite(score) or not 0.0 <= score <= 1.0:
            return
        score = float(score)
        self.last_resource_status = dict(status, score=score)

        hp = self.hyperparams["cycle_interval_scale"]
        current = float(hp.value)
        if score >= self.resource_high_threshold:
            self.resource_low_pressure_cycles = 0
            if current < hp.max_val:
                self._change_cycle_interval_scale(
                    min(hp.max_val, max(hp.min_val, current) * 2.0),
                    score,
                    "conserve",
                )
            return

        if score > self.resource_low_threshold or current <= hp.min_val:
            self.resource_low_pressure_cycles = 0
            return

        self.resource_low_pressure_cycles += 1
        if self.resource_low_pressure_cycles >= self.resource_recovery_cycles:
            self._change_cycle_interval_scale(
                max(hp.min_val, current / 2.0), score, "recover"
            )
            self.resource_low_pressure_cycles = 0

    def _change_cycle_interval_scale(
        self, value: float, pressure: float, response: str
    ) -> None:
        hp = self.hyperparams["cycle_interval_scale"]
        previous = float(hp.value)
        hp.value = float(np.clip(value, hp.min_val, hp.max_val))
        hp.history.append(hp.value)
        event = {
            "cycle": self.cycle_counter,
            "response": response,
            "pressure": pressure,
            "previous_scale": previous,
            "new_scale": hp.value,
        }
        self.resource_adaptation_history.append(event)
        logger.log(
            f"[META_LEARNING] Resource {response}: cycle scale "
            f"{previous:.2f} -> {hp.value:.2f}, pressure={pressure:.2f}"
        )

    def _evaluate_and_evolve(self):
        current_fitness = self._compute_fitness()

        if current_fitness > self.best_fitness:
            self.best_fitness = current_fitness
            self.best_config = self._get_current_config().copy()
            logger.log(f"[META_LEARNING] New best fitness: {current_fitness:.4f}")

        fitness_scores = []
        for config in self.population:
            sim = self._config_similarity(
                config, self.best_config or self.population[0]
            )
            div = self._config_diversity(config, self.population)
            fitness = current_fitness * sim + 0.1 * div
            fitness_scores.append(fitness)

        ranked = sorted(zip(fitness_scores, self.population), key=lambda x: -x[0])
        n_elite = max(1, int(self.population_size * self.elite_fraction))
        elite = [c for _, c in ranked[:n_elite]]

        new_population = elite[:]
        while len(new_population) < self.population_size:
            parent = random.choice(elite)
            child = self._mutate_config(parent)
            new_population.append(child)

        self.population = new_population

        if random.random() < 0.3:
            self._apply_config(self.best_config or elite[0])
        else:
            current = self._get_current_config()
            mutated = self._mutate_config(current, scale=0.5)
            self._apply_config(mutated)

        logger.log(
            f"[META_LEARNING] Evolution step: best_fitness={self.best_fitness:.4f}, "
            f"pop_diversity={self._population_diversity():.4f}"
        )

    def _compute_fitness(self) -> float:
        # Unified Motivation — активный источник состояния. Старый контур
        # остаётся fallback для лёгких/legacy-объектов, а не второй правдой.
        motivation = getattr(self.agent, "motivation_system", None) or getattr(
            self.agent, "internal_motivation", None
        )
        needs = list(getattr(motivation, "needs", {}).values())
        if not needs:
            return 0.0
        levels = [float(n.current_level) for n in needs]

        # В обеих моделях current_level — удовлетворённость, а не дефицит.
        need_satisfaction = np.mean(levels)
        energy_ratio = self.agent.energy / max(
            1, getattr(self.agent, "energy_max", 150)
        )
        intelligence = self.agent.intelligence / 10.0
        goal_success = self.agent.completed_goals / max(
            1, self.agent.completed_goals + len(self.agent.goals)
        )
        need_stability = 1.0 / (1.0 + np.std(levels))

        fitness = (
            0.3 * need_satisfaction
            + 0.2 * energy_ratio
            + 0.2 * intelligence
            + 0.15 * goal_success
            + 0.15 * need_stability
        )

        return float(np.clip(fitness, 0.0, 1.0))

    def _config_similarity(self, config1: Dict, config2: Dict) -> float:
        if not config2:
            return 0.5
        keys = set(config1.keys()) & set(config2.keys())
        if not keys:
            return 0.5
        v1 = np.array([config1[k] for k in keys])
        v2 = np.array([config2[k] for k in keys])
        denom = np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8
        return float(np.dot(v1, v2) / denom)

    def _config_diversity(self, config: Dict, population: List[Dict]) -> float:
        if len(population) < 2:
            return 0.0
        dists = []
        for other in population:
            if other is config:
                continue
            keys = set(config.keys()) & set(other.keys())
            if keys:
                v1 = np.array([config[k] for k in keys])
                v2 = np.array([other[k] for k in keys])
                dists.append(np.linalg.norm(v1 - v2))
        return float(np.mean(dists)) if dists else 0.0

    def _population_diversity(self) -> float:
        if len(self.population) < 2:
            return 0.0
        dists = []
        for i, c1 in enumerate(self.population):
            for c2 in self.population[i + 1 :]:
                keys = set(c1.keys()) & set(c2.keys())
                if keys:
                    v1 = np.array([c1[k] for k in keys])
                    v2 = np.array([c2[k] for k in keys])
                    dists.append(np.linalg.norm(v1 - v2))
        return float(np.mean(dists)) if dists else 0.0

    def _mutate_config(self, config: Dict, scale: float = 1.0) -> Dict:
        child = config.copy()
        for name, hp in self.hyperparams.items():
            if name in child and random.random() < self.mutation_rate:
                if hp.max_val / hp.min_val > 10:
                    log_val = np.log(child[name])
                    log_val += np.random.randn() * hp.learning_rate * scale
                    child[name] = np.clip(np.exp(log_val), hp.min_val, hp.max_val)
                else:
                    child[name] = np.clip(
                        child[name] + np.random.randn() * hp.learning_rate * scale,
                        hp.min_val,
                        hp.max_val,
                    )
        return child

    def get_status(self) -> Dict:
        return {
            "hyperparameters": {
                name: hp.get_status() for name, hp in self.hyperparams.items()
            },
            "population_size": len(self.population),
            "best_fitness": self.best_fitness,
            "current_fitness": self._compute_fitness(),
            "cycle_counter": self.cycle_counter,
            "eval_window": self.eval_window,
            "fitness_history": list(self.fitness_history)[-10:],
            "population_diversity": self._population_diversity(),
            "resource_status": dict(self.last_resource_status),
            "cycle_interval_scale": self.hyperparams["cycle_interval_scale"].value,
            "resource_low_pressure_cycles": self.resource_low_pressure_cycles,
            "resource_adaptation_history": list(self.resource_adaptation_history)[-10:],
        }

    def force_exploration(self):
        for hp in self.hyperparams.values():
            hp.learning_rate *= 2.0
        self.mutation_rate = min(0.5, self.mutation_rate * 2.0)
        logger.log("[META_LEARNING] Forced exploration mode activated")

    def force_exploitation(self):
        for hp in self.hyperparams.values():
            hp.learning_rate *= 0.5
        self.mutation_rate = max(0.01, self.mutation_rate * 0.5)
        logger.log("[META_LEARNING] Forced exploitation mode activated")


def create_meta_learner(agent) -> MetaLearner:
    return MetaLearner(agent)
