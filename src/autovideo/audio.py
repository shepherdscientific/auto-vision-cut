"""Audio extraction and processing module for the AutoVisionCut pipeline."""

import time
from pathlib import Path

import ffmpeg

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)


def extract_audio(video_path: str, output_path: str) -> str:
    logger.info("Extracting audio from %s", video_path)

    start_time = time.monotonic()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    (
        ffmpeg
        .input(video_path)
        .output(str(output_path), acodec="aac", vn=None)
        .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
    )

    elapsed = time.monotonic() - start_time
    logger.info("Audio extracted to %s (elapsed=%.1fs)", output_path, elapsed)
    return output_path


def mix_voiceover(
    video_audio_path: str,
    voiceover_path: str,
    output_path: str,
    voiceover_volume: float = 0.7,
) -> str:
    logger.info(
        "Mixing voiceover %s with audio %s (volume=%.1f)",
        voiceover_path,
        video_audio_path,
        voiceover_volume,
    )

    start_time = time.monotonic()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    video_input = ffmpeg.input(video_audio_path)
    voice_input = ffmpeg.input(voiceover_path)

    mixed = ffmpeg.filter(
        [video_input, voice_input],
        "amix",
        inputs=2,
        duration="first",
        weights=f"1 {voiceover_volume}",
    )

    out = ffmpeg.output(mixed, str(output_path))
    out.run(overwrite_output=True, capture_stdout=True, capture_stderr=True)

    elapsed = time.monotonic() - start_time
    logger.info("Mixed audio saved to %s (elapsed=%.1fs)", output_path, elapsed)
    return output_path
