"""Мелодия как отпечаток внутреннего состояния — артефакт, не декларация чувств.

Мелодия — это настоящий WAV-файл в той же creative-папке, что рисунки и
черновики. Лад и темп рождаются из доминирующей эмоции в момент начала
работы и хранятся в работе: настроение мелодии не меняется задним числом,
новое настроение — новая мелодия. Редакция добавляет фразы к прежним:
seed не содержит номера редакции, поэтому начало воспроизводимо, а каждая
редакция достраивает произведение, а не переписывает.

Дисциплина та же, что у рисунков: лимит редакций, «оставить работу»
только с причиной, чужие правки файла не затираются (проверка sha256),
квота на папку.

Звук — чистый stdlib: ``wave`` + синтез синусами (вторая гармоника для
теплоты), огибающая против щелчков, потолок длительности. Песочница
текстовая, поэтому байты пишет сам орган — но только внутрь creative-корня
и только по имени, которое он же породил (uuid.hex + .wav).
"""

import hashlib
import io
import math
import random
import struct
import wave
from uuid import uuid4

from src.core.activity_workspace import ActivityWorkspace


MUSIC_LIMIT = 6  # редакций (фраз) одной работы
MAX_MUSIC = 16  # мелодий в папке (своя квота, отдельно от рисунков)

SAMPLE_RATE = 22050  # Гц, 16-бит моно
MAX_SECONDS = 24.0  # потолок длительности: 6 тактов по 4 доли на самом
# медленном темпе (72 уд/мин) умещаются ровно
AMPLITUDE = 0.45

# Лады в полутонах от тоники.
_SCALES = {
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "minor_pent": (0, 3, 5, 7, 10),
    "major": (0, 2, 4, 5, 7, 9, 11),
    "major_pent": (0, 2, 4, 7, 9),
}

# Настроение = (лад, midi тоники, ударов в минуту). Эмоция задаёт колорит,
# не содержание. A3 = 57, A4 = 69 (стандартный MIDI-номер).
MOODS = {
    "fear": ("minor_pent", 45, 72),  # низко, медленно, рублено
    "sadness": ("minor", 50, 76),  # минор, неспешно
    "joy": ("major_pent", 57, 120),  # светло, быстро
    "calm": ("major_pent", 52, 92),  # ровно, умеренно
}

DEFAULT_THEMES = ("тишина", "дорога", "свет", "след", "вопрос", "берег")

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def _midi_name(midi: int) -> str:
    return f"{_NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def _midi_freq(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def validate_music(state):
    if not isinstance(state, dict):
        raise ValueError("local_music: нужен словарь")
    identifier = state.get("id")
    if (
        not isinstance(identifier, str)
        or len(identifier) != 32
        or any(ch not in "0123456789abcdef" for ch in identifier)
    ):
        raise ValueError("local_music.id")
    if (
        type(state.get("revision")) is not int
        or not 1 <= state["revision"] <= MUSIC_LIMIT
    ):
        raise ValueError("local_music.revision")
    if state.get("status", "active") not in {"active", "left"}:
        raise ValueError("local_music.status")
    if state.get("status") == "left" and (
        not isinstance(state.get("leave_reason"), str)
        or not state["leave_reason"].strip()
    ):
        raise ValueError("local_music.leave_reason")
    if state.get("mood") not in MOODS:
        raise ValueError("local_music.mood")
    for key in ("theme", "sha256"):
        if not isinstance(state.get(key), str) or not state[key]:
            raise ValueError(f"local_music.{key}")
    if not isinstance(state.get("score"), list):
        raise ValueError("local_music.score")


def leave_music(state, reason):
    validate_music(state)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Нужна причина оставить работу")
    if state.get("status") == "left":
        return dict(state)
    return {**state, "status": "left", "leave_reason": reason.strip()[:1000]}


def music_available(state=None, workspace=None):
    """Можно ли сочинять: активная работа с запасом редакций или место."""
    if state is not None:
        validate_music(state)
        if (
            state.get("status", "active") == "active"
            and state["revision"] < MUSIC_LIMIT
        ):
            return True
    workspace = workspace or ActivityWorkspace()
    return len(workspace.list("*.wav")) < MAX_MUSIC


def _compose_score(theme, mood, phrases):
    """Детерминированная нотная запись: seed = тема|лад, без редакции.

    Каждая следующая редакция достраивает фразы в конец: прежняя мелодия
    повторяется нота в ноту. Мелодия — случайное блуждание по ступеням
    лада с редкими паузами и октавными прыжками.

    Возвращает список тактов: такт = список (midi|None, длительность в
    долях), None — пауза.
    """
    seed = hashlib.sha256(f"{theme}|{mood}".encode("utf-8")).hexdigest()
    rng = random.Random(seed)
    scale_name, tonic, _tempo = MOODS[mood]
    scale = _SCALES[scale_name]

    bars = []
    degree = rng.randrange(len(scale))
    for _phrase in range(phrases):
        bar = []
        beats = 0.0
        while beats < 4.0:  # такт 4/4
            step = rng.choice((-2, -1, -1, 0, 1, 1, 2))
            degree = max(0, min(len(scale) - 1, degree + step))
            midi = tonic + scale[degree]
            if rng.random() < 0.12:
                midi += 12  # октавный прыжок
            duration = rng.choice((0.5, 1.0, 1.0, 2.0))
            if beats + duration > 4.0:
                duration = 4.0 - beats
            if rng.random() < 0.1:
                bar.append((None, duration))  # пауза — тоже музыка
            else:
                bar.append((midi, duration))
            beats += duration
        bars.append(bar)
    return bars


def _synthesize(bars, mood):
    """Свести нотную запись в байты WAV (16-бит моно, sine + 2-я гармоника)."""

    _scale_name, _tonic, tempo = MOODS[mood]
    beat_sec = 60.0 / tempo

    frames = bytearray()
    total_sec = 0.0
    for bar in bars:
        for midi, beats in bar:
            note_sec = beats * beat_sec
            total_sec += note_sec
            if total_sec > MAX_SECONDS:
                break
            count = max(1, int(SAMPLE_RATE * note_sec))
            attack = max(1, int(SAMPLE_RATE * 0.01))
            release = max(1, int(SAMPLE_RATE * 0.04))
            for i in range(count):
                envelope = 1.0
                if i < attack:
                    envelope = i / attack
                elif i > count - release:
                    envelope = max(0.0, (count - i) / release)
                if midi is None:
                    sample = 0.0
                else:
                    freq = _midi_freq(midi)
                    t = i / SAMPLE_RATE
                    sample = (
                        AMPLITUDE
                        * envelope
                        * (
                            math.sin(2.0 * math.pi * freq * t)
                            + 0.2 * math.sin(4.0 * math.pi * freq * t)
                        )
                    )
                value = int(max(-1.0, min(1.0, sample)) * 32767)
                frames += struct.pack("<h", value)
        if total_sec > MAX_SECONDS:
            break

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


def music_notation(state):
    """Текстовая нотная запись для ответа: имена нот по тактам."""
    validate_music(state)
    bars = _compose_score(state["theme"], state["mood"], state["revision"])
    words = []
    for bar in bars:
        words.append(" ".join(_midi_name(m) if m is not None else "—" for m, _d in bar))
    return " | ".join(words)


def music_step(state=None, *, mood="calm", theme=None, workspace=None):
    """Одна редакция мелодии: новая работа или новая фраза поверх.

    Ревизия N — это ровно N фраз: редакция добавляет один такт к прежним,
    начало воспроизводимо нота в ноту.
    """
    workspace = workspace or ActivityWorkspace()
    root = workspace.root
    if state is not None:
        validate_music(state)
    if (
        state is None
        or state["revision"] >= MUSIC_LIMIT
        or state.get("status") == "left"
    ):
        if len(workspace.list("*.wav")) >= MAX_MUSIC:
            raise ValueError("Папка мелодий заполнена; новые файлы не создаются")
        identifier = uuid4().hex
        if mood not in MOODS:
            raise ValueError(f"local_music: неизвестное настроение {mood!r}")
        theme = (theme or "").strip() or random.choice(DEFAULT_THEMES)
        revision = 1
    else:
        identifier, theme, mood = state["id"], state["theme"], state["mood"]
        # Прежняя редакция может остаться в общем корне до перехода (5C):
        # копируем её в каталог жизни, оригинал не трогаем.
        workspace.ensure_from_legacy(f"{identifier}.wav")
        previous = (root / f"{identifier}.wav").read_bytes()
        if hashlib.sha256(previous).hexdigest() != state["sha256"]:
            raise ValueError(
                "Мелодия изменена извне; автоматическая перезапись отменена"
            )
        revision = state["revision"] + 1

    bars = _compose_score(theme, mood, revision)
    content = _synthesize(bars, mood)

    workspace.write_bytes(
        f"{identifier}.wav",
        content,
        overwrite=True,
        kind="creative",
        metadata={"activity": "music", "work_id": identifier, "revision": revision},
    )
    if (root / f"{identifier}.wav").read_bytes() != content:
        raise IOError("Не совпало обратное чтение мелодии")

    return {
        "id": identifier,
        "theme": theme,
        "mood": mood,
        "revision": revision,
        "status": "active",
        "sha256": hashlib.sha256(content).hexdigest(),
        "score": [_midi_name(m) if m is not None else "—" for m, _d in bars[-1]],
    }
