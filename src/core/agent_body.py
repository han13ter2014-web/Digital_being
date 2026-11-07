"""Body economics, recovery and sleep consolidation from ``agent.py``.

The facade re-exports constants and ``step_body`` so existing imports and the
late-binding call sites in ``src.core.agent`` keep their previous contract.
"""

from typing import Dict

from config.simulation_config import LR_CONFIG
from src.core.buffered_logger import get_logger


# Действия, которые восстанавливают ресурс, а не расходуют его.
# Отдых не может стоить энергии: иначе он недоступен ровно тогда, когда
# нужен, — при истощении. Замер до правки: 243 отказа «too_tired» на 400
# попыток, и отдых среди них.
RECOVERY_ACTIONS: frozenset = frozenset({"rest", "deep_rest"})

# Действия, которые нельзя запретить по нехватке энергии. Иначе существо
# не сможет ни восстановиться, ни починиться, ни сохраниться — и выйдет
# из строя навсегда. Совпадает с «essential» в ActionBudget, плюс rest.
ESSENTIAL_ACTIONS: frozenset = RECOVERY_ACTIONS | {"repair", "checkpoint_now"}

# Сколько ресурса тело тратит на действие (0..1). Раньше интероцепция
# вообще не знала о работе: ``step()`` вызывался только из отдыха и
# восстановления чекпоинта, поэтому усталость не росла от действий.
# Замер: после 20 рабочих циклов fatigue = 0.0, множитель стоимости 1.0.
BODY_LOAD: Dict[str, float] = {
    # тяжёлая мыслительная работа
    "explore": 0.9,
    "synthesis": 0.9,
    "decomposition": 0.85,
    "hypothesis": 0.8,
    "reflection": 0.7,
    "web_search": 0.6,
    "draw": 0.5,
    # сочинение мелодии — как рисунок: творческая, но не тяжёлая работа
    "compose_music": 0.5,
    # чтение новостей — лёгкое: глаза бегут, тело почти не работает
    "read_news": 0.4,
    # «Интернет-1»: прогулка по открытому вебу — такая же лёгкая
    "browse_web": 0.4,
    # общение и решения
    "know_answer": 0.5,
    "ask_user": 0.5,
    "communicate": 0.4,
    "set_own_goal": 0.4,
    "default": 0.3,
    # обслуживание тела
    "repair": 0.2,
    "checkpoint_now": 0.1,
    "wait": 0.0,
}

# Глубина отдыха для действий восстановления.
BODY_REST_DEPTH: Dict[str, float] = {"rest": 0.5, "deep_rest": 1.0}

# Действия, которые уставший мозг делает хуже. Не запрет, а снижение
# тяги: при высокой усталости они проигрывают отдыху и лёгким действиям,
# и агент чередует работу с восстановлением.
HEAVY_ACTIONS: frozenset = frozenset(
    name for name, load in BODY_LOAD.items() if load >= 0.6
)

# Нагрузка отказа: тело живёт этот такт, но не работает.
BODY_DENIED_LOAD: float = 0.05


def step_body(obj, action_type: str, performed: bool = True) -> None:
    """Прожить телом один такт: потратить ресурс или восстановить его.

    Модульная функция, как и ``record_denied_outcome``: ``act()``
    вызывается и в лёгких объектах без тела (тесты бюджета, заглушки), и
    отсутствие интероцепции не должно ронять действие.

    Один такт тела — одно действие. В трей-режиме за цикл действие может
    произойти дважды (спонтанное в ``autonomous_tick`` и ответ на стимул),
    и это два разных усилия, а не одно.
    """
    interoception = getattr(obj, "interoception", None)
    if interoception is None:
        return
    rest_depth = BODY_REST_DEPTH.get(action_type, 0.0)
    if rest_depth > 0:
        load = 0.0
    elif performed:
        load = BODY_LOAD.get(action_type, 0.3)
    else:
        load = BODY_DENIED_LOAD
    try:
        interoception.step(dt=1.0, cognitive_load=load, rest_depth=rest_depth)
    except Exception as exc:  # тело не должно ронять действие
        get_logger().log(f"[BODY] step error for {action_type}: {exc}")
        return
    if rest_depth > 0:
        get_logger().log(
            f"[INTEROCEPTION] Отдых ({action_type}): "
            f"fatigue={interoception.state.fatigue:.2f}, "
            f"atp={interoception.state.atp:.1f}"
        )
    elif load >= 0.6:
        get_logger().log(
            f"[INTEROCEPTION] {action_type}: fatigue="
            f"{interoception.state.fatigue:.2f}, "
            f"atp={interoception.state.atp:.1f}"
        )


def _get_adaptive_cost_impl(self, action_type: str) -> int:
    """Получает адаптивную стоимость действия.

        При ``ADAPTIVE_COSTS_ENABLED=True`` берётся текущая (адаптированная)
        стоимость из ``self._action_costs`` (обновляется в
        ``_adapt_costs_after_action``). При выключенной адаптации —
        фиксированная базовая стоимость, чтобы поведение было детерминированным.

        Раньше обе ветки возвращали одно и то же значение — мёртвая
        логика адаптации (флаг ADAPTIVE_COSTS_ENABLED игнорировался).

        Восстановительные действия бесплатны всегда: это не «скидка», а
        условие существования — платный отдых при нулевой энергии
        превращается в отказ от отдыха.
        """
    if action_type in RECOVERY_ACTIONS:
        return 0
    if not LR_CONFIG.ADAPTIVE_COSTS_ENABLED:
        # Фиксированная «честная» стоимость (без обратной связи).
        return self._action_costs.get(action_type, 2)
    # Адаптивная стоимость — может уменьшаться/увеличиваться по
    # результатам действий. По умолчанию — 2.
    return self._action_costs.get(action_type, 2)


def _recover_energy_impl(self, deep: bool = False) -> float:
    """Возвращает энергию за отдых. Возвращает, сколько добавлено.

        Отдых — единственный способ выйти из истощения: пассивная
        регенерация EnergyPolicy ниже 20% даёт 0.1–1.2 за цикл, а действие
        стоит 2–4. Без этого истощённый агент навсегда оставался в
        состоянии «слишком устал» и не мог даже отдохнуть.
        """
    amount = float(
        getattr(
            LR_CONFIG,
            "DEEP_REST_ENERGY_RECOVERY" if deep else "REST_ENERGY_RECOVERY",
            30.0 if deep else 12.0,
        )
    )
    max_energy = float(getattr(LR_CONFIG, "ENERGY_MAX", 200.0))
    before = float(self.energy)
    self.energy = min(max_energy, before + amount)
    return max(0.0, float(self.energy) - before)


def _body_needs_rest_impl(self) -> bool:
    """Нужен ли телу отдых прямо сейчас (усталость или мало энергии)."""
    fatigue = 0.0
    interoception = getattr(self, "interoception", None)
    if interoception is not None:
        try:
            fatigue = float(interoception.state.fatigue)
        except Exception:
            fatigue = 0.0
    threshold = float(getattr(LR_CONFIG, "REST_FATIGUE_THRESHOLD", 0.6))
    if fatigue >= threshold:
        return True

    max_energy = float(getattr(LR_CONFIG, "ENERGY_MAX", 200.0))
    ratio = float(self.energy) / max_energy if max_energy > 0 else 1.0
    return ratio <= float(getattr(LR_CONFIG, "LOW_ENERGY_RATIO", 0.25))


def _body_recovered_impl(self) -> bool:
    """Достаточно ли восстановлено тело, чтобы вернуться к работе."""
    interoception = getattr(self, "interoception", None)
    if interoception is not None:
        try:
            fatigue = float(interoception.state.fatigue)
            atp_ratio = float(interoception.state.atp) / max(
                1e-6, float(interoception.state.atp_max)
            )
        except Exception:
            fatigue, atp_ratio = 0.0, 1.0
        if fatigue > float(
            getattr(LR_CONFIG, "REST_RECOVERY_FATIGUE", 0.3)
        ):
            return False
        if atp_ratio < float(
            getattr(LR_CONFIG, "REST_RECOVERY_ATP_RATIO", 0.75)
        ):
            return False

    max_energy = float(getattr(LR_CONFIG, "ENERGY_MAX", 200.0))
    ratio = float(self.energy) / max_energy if max_energy > 0 else 1.0
    return ratio >= float(
        getattr(LR_CONFIG, "REST_RECOVERY_ENERGY_RATIO", 0.5)
    )


def _update_rest_mode_impl(self) -> bool:
    """Гистерезис отдыха: решает, продолжает ли тело отдыхать.

        Вход в отдых — по усталости или низкой энергии, выход — только
        когда восстановлено и то, и другое. Без гистерезиса агент
        возвращался к работе на пороге 0.6 с пустым АТФ и тут же снова
        уставал: замер показывал 53 «работа→отдых» за 200 циклов и АТФ,
        застрявший около нуля.
        """
    resting = bool(getattr(self, "_rest_mode", False))
    if self._body_needs_rest():
        resting = True
    elif resting and self._body_recovered():
        resting = False
    self._rest_mode = resting
    return resting


def _is_resting_impl(self) -> bool:
    return bool(getattr(self, "_rest_mode", False))


def _action_cost_now_impl(self, action_type: str) -> float:
    """Сколько энергии действие стоит прямо сейчас (с поправкой на усталость)."""
    base = self._get_adaptive_cost(action_type)
    if action_type in ESSENTIAL_ACTIONS:
        return 0.0 if action_type in RECOVERY_ACTIONS else float(base)
    interoception = getattr(self, "interoception", None)
    if interoception is not None:
        try:
            return float(interoception.get_action_cost(base))
        except Exception:
            return float(base)
    return float(base)


def _is_action_affordable_impl(self, action_type: str) -> bool:
    """Хватает ли энергии на действие (отдых доступен всегда)."""
    if action_type in RECOVERY_ACTIONS:
        return True
    return float(self.energy) >= self._action_cost_now(action_type)


def _accumulate_sleep_impl(self, units: float) -> Dict:
    """Накопить «единицы сна» и, если хватит, осмыслить накопленное.

        Один проход консолидации — это работа, а не отсчёт: связи,
        разбросанные по формулировкам, укрепляются, опыт превращается в
        определения. Поэтому сон измеряется не тиками, а накопленным
        материалом: ``deep_rest`` даёт 1.0, ``rest`` — 0.5.

        Returns:
            Отчёт последнего прохода или пустой словарь, если порог не
            набран.
        """
    if not bool(getattr(LR_CONFIG, "CONSOLIDATION_ENABLED", True)):
        return {}
    mental_models = getattr(self, "mental_models", None)
    if mental_models is None or not hasattr(mental_models, "consolidate"):
        return {}

    self._sleep_units = float(getattr(self, "_sleep_units", 0.0)) + float(units)
    threshold = float(
        getattr(LR_CONFIG, "CONSOLIDATION_SLEEP_UNITS", 3.0) or 3.0
    )
    report: Dict = {}
    while self._sleep_units >= threshold:
        self._sleep_units -= threshold
        try:
            report = mental_models.consolidate(
                link_delta=float(
                    getattr(LR_CONFIG, "CONSOLIDATION_LINK_DELTA", 0.05)
                ),
                max_links=int(
                    getattr(LR_CONFIG, "CONSOLIDATION_MAX_LINKS", 400)
                ),
                max_definitions=int(
                    getattr(LR_CONFIG, "CONSOLIDATION_MAX_DEFINITIONS", 25)
                ),
                confidence_bonus=float(
                    getattr(
                        LR_CONFIG, "CONSOLIDATION_CONFIDENCE_BONUS", 0.02
                    )
                ),
                scan_batch=int(
                    getattr(LR_CONFIG, "CONSOLIDATION_SCAN_BATCH", 400)
                ),
            )
        except Exception as exc:
            get_logger().log(f"[CONSOLIDATION] ошибка: {exc}")
            return {}
        self._consolidation_count = int(
            getattr(self, "_consolidation_count", 0)
        ) + 1
        self._last_consolidation = dict(report)
        get_logger().flush_immediate(
            f"[CONSOLIDATION] связей +{report.get('links', 0)}, "
            f"формулировок +{report.get('definitions', 0)}, "
            f"уточнений {report.get('refined', 0)}, "
            f"уверенность ×{report.get('confidence', 0)}"
        )
    return report


def _adapt_costs_after_action_impl(self, success: bool, action_type: str):
    """Адаптирует энергетические затраты после действия."""
    if not LR_CONFIG.ADAPTIVE_COSTS_ENABLED:
        return
    if action_type in RECOVERY_ACTIONS:
        return  # отдых остаётся бесплатным

    current_cost = self._action_costs.get(action_type, 2)
    rate = LR_CONFIG.COST_ADAPTATION_RATE

    if success:
        # Если действие успешно — увеличиваем его "цену" (агент готов платить больше)
        new_cost = min(10, int(current_cost * (1 + rate)))
    else:
        # Если неуспешно — уменьшаем цену
        new_cost = max(1, int(current_cost * (1 - rate)))

    self._action_costs[action_type] = new_cost
