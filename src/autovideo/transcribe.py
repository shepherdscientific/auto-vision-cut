"""Audio transcription module for the AutoVisionCut pipeline.

Extracts audio from video and transcribes it locally using mlx-whisper.
Produces a timestamped transcript.json with per-segment and per-word timestamps.
"""

import json
import os
import time
from pathlib import Path

import mlx_whisper

from autovideo.audio import extract_audio
from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)

DEFAULT_WHISPER_MODEL = "mlx-community/whisper-tiny"
TRANSCRIPT_FILENAME = "transcript.json"


def _build_segment(segment: dict, idx: int) -> dict:
    result = {
        "id": idx,
        "start": segment["start"],
        "end": segment["end"],
        "text": segment["text"].strip(),
        "confidence": segment.get("avg_logprob", 0.0),
    }
    words = segment.get("words")
    if words and isinstance(words, list):
        word_list = [
            {"w": w["word"].strip(), "start": w["start"], "end": w["end"]}
            for w in words
            if "start" in w and "end" in w and w.get("word", "").strip()
        ]
        if word_list:
            result["words"] = word_list
    return result


def transcribe(
    video_path: str,
    output_dir: str,
    model_path: str = DEFAULT_WHISPER_MODEL,
    word_timestamps: bool = True,
) -> str:
    logger.info(
        "Transcribing audio from %s (model=%s, word_timestamps=%s)",
        video_path, model_path, word_timestamps,
    )
    start_time = time.monotonic()

    audio_path = os.path.join(output_dir, "temp_audio.aac")
    extract_audio(video_path, audio_path)

    logger.info("Running mlx-whisper on %s with model %s", audio_path, model_path)
    result = mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=model_path,
        word_timestamps=word_timestamps,
        verbose=None,
    )

    segments_raw = result.get("segments", [])
    transcript = {
        "segments": [
            _build_segment(seg, i) for i, seg in enumerate(segments_raw)
        ],
        "language": result.get("language", "unknown"),
        "model": model_path,
    }

    output_path = os.path.join(output_dir, TRANSCRIPT_FILENAME)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    try:
        Path(audio_path).unlink(missing_ok=True)
    except Exception:
        logger.warning("Could not remove temp audio %s", audio_path)

    elapsed = time.monotonic() - start_time
    logger.info(
        "Transcription complete: %d segments, %s (elapsed=%.1fs)",
        len(transcript["segments"]), output_path, elapsed,
    )
    return output_path
