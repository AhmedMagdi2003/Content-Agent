"""Generate English narration from the scene manifest, without uploading any video.

Run from the repository root with:
    uv run python -m scripts.generate_walkthrough_voiceover
"""

from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

from openai import OpenAI

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "data" / "walkthrough-edit-work"
MANIFEST = WORK / "scenes.json"
FFMPEG = (
    ROOT
    / "data"
    / "walkthrough-tools"
    / "imageio_ffmpeg"
    / "binaries"
    / "ffmpeg-win-x86_64-v7.1.exe"
)
INSTRUCTIONS = (
    "Speak in clear, warm, confident English with a neutral international accent. "
    "This is a professional product walkthrough for evaluators. Use a steady, "
    "conversational pace with small pauses at sentence boundaries. Be informative "
    "and natural, not dramatic or sales-like. Speak exactly the supplied words."
)


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def main() -> None:
    settings = Settings()
    api_key = settings.openai_api_key.get_secret_value()
    if not api_key:
        raise SystemExit("No OpenAI API key is configured in the project's environment.")
    if not MANIFEST.is_file():
        raise SystemExit(
            "Scene manifest not found. Run the walkthrough builder once to prepare it."
        )

    scenes = json.loads(MANIFEST.read_text(encoding="utf-8"))
    client = OpenAI(api_key=api_key, timeout=120.0, max_retries=2)
    WORK.mkdir(parents=True, exist_ok=True)
    print(f"Generating {len(scenes)} English narration segments; no video or image is sent.")

    for scene in scenes:
        raw = WORK / f"voice-{scene['Index']:02d}.wav"
        target = WORK / f"voice-{scene['Index']:02d}-fixed.wav"
        response = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="marin",
            input=scene["English"],
            instructions=INSTRUCTIONS,
            response_format="wav",
        )
        raw.write_bytes(response.content)
        subprocess.run(
            [
                str(FFMPEG),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(raw),
                "-c:a",
                "pcm_s16le",
                "-ar",
                "24000",
                "-ac",
                "1",
                str(target),
            ],
            check=True,
        )
        duration = wav_duration(target)
        slot = scene["End"] - scene["Start"]
        print(f"{scene['Index']:02d}: {duration:0.1f}s narration / {slot:0.1f}s scene")


if __name__ == "__main__":
    main()
