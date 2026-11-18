"""Воспроизводимо создать или проверить synthetic PCM fixtures для 9C-3.

Это транспортные сигналы, не записи людей и не материал для оценки качества STT.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SAMPLE_RATE = 16_000
FRAME_COUNT = 1_600


def _wav(frequency: float, amplitude: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        frames = b"".join(
            struct.pack(
                "<h",
                round(
                    amplitude
                    * 32767
                    * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE)
                ),
            )
            for index in range(FRAME_COUNT)
        )
        output.writeframes(frames)
    return buffer.getvalue()


def _scenario(scenario_id: str, audio: str, text: str, confidence: float, raw: bytes):
    return {
        "scenario_id": scenario_id,
        "audio": audio,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "real_speech": False,
        "fake_stt": {"text": text, "confidence": confidence},
    }


def render() -> dict[str, bytes]:
    ru_audio = _wav(440.0, 0.2)
    en_audio = _wav(660.0, 0.3)
    manifest = {
        "schema_version": 1,
        "catalog_revision": "9c3-r1",
        "fixture_kind": "synthetic_pcm_transport_only",
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "sample_width_bytes": 2,
        "frames": FRAME_COUNT,
        "scenarios": [
            _scenario("ru_transport", "ru_tone.wav", "Проверка голосового ввода", 0.75, ru_audio),
            _scenario("en_transport", "en_tone.wav", "Voice input check", 0.5, en_audio),
        ],
    }
    return {
        "ru_tone.wav": ru_audio,
        "en_tone.wav": en_audio,
        "manifest.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="проверить байты без перезаписи fixtures"
    )
    args = parser.parse_args()
    for name, expected in render().items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_bytes() != expected:
                raise SystemExit(f"Fixture differs from canonical content: {name}")
        else:
            path.write_bytes(expected)
    print("Voice fixtures OK" if args.check else "Voice fixtures generated")


if __name__ == "__main__":
    main()
