"""Transcript segmentation module for the AutoVisionCut pipeline.

Splits a timestamped transcript into clean utterance segments
on sentence boundaries and configurable silence/pause gaps.
"""

import json
import os
import re
import time

from autovideo.config import Config
from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)

DEFAULT_PAUSE_THRESHOLD = 0.7
SEGMENTS_FILENAME = "segments.json"

_SENTENCE_END = re.compile(r"[.!?…]+[\"')%]?\s*$")


def _is_sentence_boundary(text: str) -> bool:
    return bool(_SENTENCE_END.search(text.strip()))


def _detect_silences(
    segments: list[dict], pause_threshold: float = DEFAULT_PAUSE_THRESHOLD
) -> list[dict]:
    silences: list[dict] = []
    for i in range(len(segments) - 1):
        gap = segments[i + 1]["start"] - segments[i]["end"]
        if gap > pause_threshold:
            silences.append({
                "id": f"silence_{i}",
                "start": segments[i]["end"],
                "end": segments[i + 1]["start"],
                "duration": round(gap, 3),
                "gap_between": (i, i + 1),
            })
    return silences


def segment_transcript(
    transcript_path: str,
    output_dir: str,
    pause_threshold: float = DEFAULT_PAUSE_THRESHOLD,
) -> str:
    logger.info(
        "Segmenting transcript from %s (pause_threshold=%.1fs)",
        transcript_path, pause_threshold,
    )
    start_time = time.monotonic()

    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    raw_segments = sorted(
        transcript.get("segments", []), key=lambda s: s.get("start", 0.0)
    )
    if not raw_segments:
        logger.warning("Transcript has no segments; writing empty segments.json")
        segments_output: dict = {"segments": [], "silences": [], "stats": {}}
        return _write_segments(segments_output, output_dir, start_time)

    merged: list[dict] = []
    current: dict | None = None

    for seg in raw_segments:
        text = seg.get("text", "").strip()
        if not text:
            continue

        if current is None:
            current = dict(seg)
            continue

        gap = seg["start"] - current["end"]
        ends_sentence = _is_sentence_boundary(current.get("text", ""))

        if ends_sentence and gap >= pause_threshold:
            merged.append(current)
            current = dict(seg)
        elif gap < pause_threshold:
            current["end"] = seg["end"]
            current["text"] = (current.get("text", "") + " " + text).strip()
            current["confidence"] = max(
                current.get("confidence", 0.0), seg.get("confidence", 0.0)
            )
        else:
            merged.append(current)
            current = dict(seg)

    if current is not None:
        merged.append(current)

    for i, seg in enumerate(merged):
        seg["id"] = i
        seg["duration"] = round(seg["end"] - seg["start"], 3)

    silences = _detect_silences(merged, pause_threshold)
    for s in silences:
        s["tag"] = "dead_air"

    total_duration = merged[-1]["end"] if merged else 0.0
    speech_duration = sum(s["duration"] for s in merged)
    silence_duration = sum(s["duration"] for s in silences)

    stats = {
        "total_segments": len(merged),
        "total_silences": len(silences),
        "total_duration": round(total_duration, 3),
        "speech_duration": round(speech_duration, 3),
        "silence_duration": round(silence_duration, 3),
        "pause_threshold": pause_threshold,
    }

    segments_output = {"segments": merged, "silences": silences, "stats": stats}
    return _write_segments(segments_output, output_dir, start_time)


def _write_segments(
    segments_output: dict, output_dir: str, start_time: float
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, SEGMENTS_FILENAME)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(segments_output, f, indent=2, ensure_ascii=False)

    elapsed = time.monotonic() - start_time
    seg_count = len(segments_output.get("segments", []))
    sil_count = len(segments_output.get("silences", []))
    logger.info(
        "Segmentation complete: %d segments, %d silences → %s (elapsed=%.1fs)",
        seg_count, sil_count, output_path, elapsed,
    )
    return output_path


def run(
    config: Config,
    transcript_path: str,
    output_dir: str,
) -> str:
    return segment_transcript(
        transcript_path=transcript_path,
        output_dir=output_dir,
        pause_threshold=config.pause_threshold,
    )
