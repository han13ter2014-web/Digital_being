"""Creative-work helpers extracted from ``agent.py``.

Local art and music imports remain inside their original call sites. Facade
calls preserve late binding; this module never imports ``src.core.agent``.
"""

import random
from typing import Dict, List

from config.simulation_config import LR_CONFIG
from src.core.buffered_logger import get_logger


def leave_creative_draft_impl(self, reason: str) -> Dict:
    state = getattr(self, "_creative_draft", None)
    if state is None:
        return {"status": "not_found"}
    from src.cognition.creative_catalog import perform_creative

    perform_creative(self, "leave", state["id"], reason)
    return {"status": "left", "draft_id": state["id"]}


def list_creative_drafts_impl(self) -> List[Dict]:
    from src.cognition.creative_catalog import catalog_for

    catalog = catalog_for(self)
    return [catalog[identifier] for identifier in sorted(catalog)]


def _pick_art_theme_impl(self) -> str:
    """Тема картины — из собственной жизни, а не из чужого списка.

        Активная цель, а если её нет — самая слабая известная концепция:
        существо рисует то, что его сейчас занимает.
        """
    goal = getattr(self, "active_goal", None)
    if isinstance(goal, dict):
        title = str(goal.get("title") or "").strip()
        if title:
            return title[:60]
    concepts = getattr(getattr(self, "mental_models", None), "concepts", None)
    if isinstance(concepts, dict) and concepts:
        weakest = min(
            (name for name in concepts if self._is_learnable(name)),
            key=lambda name: float(getattr(concepts[name], "confidence", 0.0) or 0.0),
            default=None,
        )
        if weakest:
            return weakest[:60]
    from src.cognition.local_art import DEFAULT_THEMES

    return random.choice(DEFAULT_THEMES)


def _art_richness_impl(self) -> int:
    """Густота мазков: запас сил тела — видимый в работе факт."""
    max_energy = float(getattr(LR_CONFIG, "ENERGY_MAX", 200) or 200)
    ratio = float(self.energy) / max_energy if max_energy > 0 else 0.0
    return 3 + int(6 * max(0.0, min(1.0, ratio)))


def _act_draw_impl(self) -> Dict:
    """Нарисовать картину: отпечаток текущего внутреннего состояния.

        Палитра — доминирующая эмоция (у уже начатой работы палитра
        хранится с рождения и не переписывается), тема — то, что
        занимает существо, густота — запас сил. Работа на лимите
        редакций оставляется с честной причиной, и начинается новая.
        """
    from src.cognition.local_art import (
        ART_LIMIT, art_available, art_step, art_thumbnail, leave_art,
    )

    work = getattr(self, "_art_work", None)
    try:
        if work is not None and (
            work.get("status") == "left" or work.get("revision", 0) >= ART_LIMIT
        ):
            if work.get("status") != "left":
                work = leave_art(work, "достигнут лимит редакций — работа завершена")
                catalog = getattr(self, "_art_catalog", None)
                if isinstance(catalog, dict):
                    catalog[work["id"]] = dict(work)
                get_logger().log(
                    f"[ART] оставила «{work['theme']}» (лимит редакций)"
                )
            work = None
        if work is None and not art_available(None):
            return {"text": "Ответ: рисовать негде — папка работ заполнена"}

        if work is not None:
            # Работа хранит настроение своего рождения.
            palette = work["palette"]
            theme = work["theme"]
        else:
            palette = "calm"
            emotions = getattr(self, "emotional_state", None)
            dominant = emotions.dominant() if emotions is not None else None
            if dominant:
                palette = dominant["emotion"]
            theme = self._pick_art_theme()

        updated = art_step(
            work, palette=palette, theme=theme, richness=self._art_richness()
        )
        self._art_work = updated
        catalog = getattr(self, "_art_catalog", None)
        if not isinstance(catalog, dict):
            catalog = self._art_catalog = {}
        catalog[updated["id"]] = dict(updated)
        self._record_will(
            "art_works", updated["theme"],
            f"рисунок, редакция {updated['revision']}, палитра {updated['palette']}",
        )
        thumb = art_thumbnail(updated)
        return {
            "target": updated["theme"],
            "text": (
                f"Ответ: нарисовала «{updated['theme']}», редакция "
                f"{updated['revision']} ({updated['palette']})\n{thumb}"
            ),
        }
    except Exception as exc:
        get_logger().log(f"[ART] не удалось нарисовать: {exc}")
        return {"text": "Ответ: хотела нарисовать, но не получилось"}


def list_art_works_impl(self) -> List[Dict]:
    """Каталог собственных рисунков (для снимка жизни)."""
    catalog = getattr(self, "_art_catalog", None)
    if not isinstance(catalog, dict):
        return []
    return [dict(catalog[key]) for key in sorted(catalog)]


def _act_compose_music_impl(self) -> Dict:
    """Сочинить мелодию: отпечаток текущего состояния в звуке.

        Настроение — доминирующая эмоция (у уже начатой работы оно
        хранится с рождения и не переписывается), тема — то, что занимает
        существо. Работа на лимите редакций оставляется с честной
        причиной, и начинается новая.
        """
    from src.cognition.local_music import (
        MOODS, MUSIC_LIMIT, leave_music, music_available, music_notation,
        music_step,
    )

    work = getattr(self, "_music_work", None)
    try:
        if work is not None and (
            work.get("status") == "left" or work.get("revision", 0) >= MUSIC_LIMIT
        ):
            if work.get("status") != "left":
                work = leave_music(work, "достигнут лимит редакций — работа завершена")
                catalog = getattr(self, "_music_catalog", None)
                if isinstance(catalog, dict):
                    catalog[work["id"]] = dict(work)
                get_logger().log(
                    f"[MUSIC] оставила «{work['theme']}» (лимит редакций)"
                )
            work = None
        if work is None and not music_available(None):
            return {"text": "Ответ: сочинять негде — папка мелодий заполнена"}

        if work is not None:
            # Работа хранит настроение своего рождения.
            mood = work["mood"]
            theme = work["theme"]
        else:
            mood = "calm"
            emotions = getattr(self, "emotional_state", None)
            dominant = emotions.dominant() if emotions is not None else None
            if dominant:
                mood = dominant["emotion"]
            if mood not in MOODS:
                # Эмоций больше, чем ладов: незнакомое настроение
                # звучит как покой, а не как отказ творить.
                mood = "calm"
            theme = self._pick_art_theme()

        updated = music_step(work, mood=mood, theme=theme)
        self._music_work = updated
        catalog = getattr(self, "_music_catalog", None)
        if not isinstance(catalog, dict):
            catalog = self._music_catalog = {}
        catalog[updated["id"]] = dict(updated)
        self._record_will(
            "music_works", updated["theme"],
            f"мелодия, редакция {updated['revision']}, настроение {updated['mood']}",
        )
        notation = music_notation(updated)
        return {
            "target": updated["theme"],
            "text": (
                f"Ответ: сочинила мелодию «{updated['theme']}», редакция "
                f"{updated['revision']} ({updated['mood']})\n{notation}"
            ),
        }
    except Exception as exc:
        get_logger().log(f"[MUSIC] не удалось сочинить: {exc}")
        return {"text": "Ответ: хотела сочинить мелодию, но не получилось"}


def list_music_works_impl(self) -> List[Dict]:
    """Каталог собственных мелодий (для снимка жизни)."""
    catalog = getattr(self, "_music_catalog", None)
    if not isinstance(catalog, dict):
        return []
    return [dict(catalog[key]) for key in sorted(catalog)]


def _reward_creative_success_impl(self):
    """Поощряет креативный успех."""
    self._creative_wins += 1
    if self._creative_wins >= 5:  # Каждые 5 успешных креативных действий
        self.energy += LR_CONFIG.CREATIVITY_BONUS_ENERGY * 2
        get_logger().flush_immediate(f"🎨 Креативность окупилась! +{LR_CONFIG.CREATIVITY_BONUS_ENERGY * 2} энергии")
        self._creative_wins = 0


def _record_creative_failure_impl(self):
    """Записывает неудачу креативного действия."""
    self._creative_losses += 1
    if self._creative_losses >= 3:
        # Если слишком много неудач — снижаем ε (меньше случайности)
        LR_CONFIG.EPSILON_GREEDY = max(0.05, LR_CONFIG.EPSILON_GREEDY - 0.02)
        get_logger().log(f"Снижаю ε-greedy до {LR_CONFIG.EPSILON_GREEDY:.0%} (слишком много неудач)")
        self._creative_losses = 0
