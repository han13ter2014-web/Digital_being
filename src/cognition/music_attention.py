"""Ограниченное внимание к собственным мелодиям без эмоций и наград."""


def _provenance(work):
    if not isinstance(work, dict):
        return None
    identifier = work.get("id")
    revision = work.get("revision")
    sha256 = work.get("sha256")
    if (
        not isinstance(identifier, str)
        or type(revision) is not int
        or revision < 1
        or not isinstance(sha256, str)
    ):
        return None
    return identifier, revision, sha256


def listening_candidate(agent):
    """Предложить одну реальную редакцию; не создавать цель или аффект.

    Непрослушанная работа получает умеренный приоритет. Знакомая работа не
    исчезает: её сила растёт с паузой, личной значимостью и ассоциациями,
    но остаётся ограниченной. Проверка WAV выполняется только при исполнении.
    """
    catalog = getattr(agent, "_music_catalog", None)
    memory = getattr(agent, "music_memory", None)
    if not isinstance(catalog, dict) or not catalog or memory is None:
        return None

    cycle = getattr(agent, "cycle_count", 0)
    if type(cycle) is not int or cycle < 0:
        return None
    marker = getattr(agent, "_unheard_music_revision", None)
    if not isinstance(marker, dict):
        marker = {}
    choices = []
    for key in sorted(catalog):
        work = catalog[key]
        provenance = _provenance(work)
        if provenance is None or key != provenance[0]:
            continue
        identifier, revision, sha256 = provenance
        try:
            heard = memory.has_listened(identifier, revision, sha256)
            remembered = memory.get_work(identifier)
        except (TypeError, ValueError):
            continue
        unheard = not heard
        marked = (
            marker.get("work_id") == identifier
            and marker.get("revision") == revision
            and marker.get("sha256") == sha256
        )
        if unheard:
            strength = 0.42 + (0.04 if marked else 0.0)
        else:
            last_cycle = remembered["last_listened_cycle"]
            elapsed = max(0, cycle - last_cycle)
            significance = float(remembered["personal_significance"])
            associations = len(remembered["associations"])
            strength = (
                0.06
                + min(0.22, elapsed * 0.02)
                + significance * 0.12
                + min(4, associations) * 0.01
            )
        choices.append(
            (
                min(0.5, strength),
                identifier,
                {
                    "source": "music_attention",
                    "action": "listen_music",
                    "strength": min(0.5, strength),
                    "params": {
                        "work_id": identifier,
                        "revision": revision,
                        "sha256": sha256,
                        "topic": str(work.get("theme") or ""),
                        "unheard": unheard,
                    },
                },
            )
        )
    if not choices:
        return None
    # При равной силе идентификатор даёт стабильный выбор без random.
    return max(choices, key=lambda item: (item[0], item[1]))[2]
