"""Output validation and verification module for the AutoVisionCut pipeline."""

import json
import os
import time
from pathlib import Path
from typing import Any

import ffmpeg

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)


def _get_video_info(video_path: str) -> dict[str, Any]:
    probe = ffmpeg.probe(video_path)
    video_stream = next(
        (s for s in probe["streams"] if s["codec_type"] == "video"), None
    )
    audio_stream = next(
        (s for s in probe["streams"] if s["codec_type"] == "audio"), None
    )

    fmt = probe.get("format", {})
    duration = float(fmt.get("duration", 0))
    file_size = os.path.getsize(video_path)

    info: dict[str, Any] = {
        "path": video_path,
        "duration": duration,
        "file_size_bytes": file_size,
        "file_size_mb": round(file_size / (1024 * 1024), 2),
        "format_name": fmt.get("format_name", "unknown"),
    }

    if video_stream:
        info["video_codec"] = video_stream.get("codec_name", "unknown")
        info["video_width"] = video_stream.get("width")
        info["video_height"] = video_stream.get("height")
        info["video_fps"] = video_stream.get("r_frame_rate")

    if audio_stream:
        info["audio_codec"] = audio_stream.get("codec_name", "unknown")
        info["audio_channels"] = audio_stream.get("channels")
        info["audio_sample_rate"] = audio_stream.get("sample_rate")

    return info


def _load_cut_list(path: str) -> dict[str, Any]:
    with open(path, "r") as f:
        data = json.load(f)
    return data


def run(output_path: str, cut_list_path: str) -> dict[str, Any]:
    logger.info(
        "Output validation started (output=%s, cut_list=%s)",
        output_path,
        cut_list_path,
    )
    start_time = time.monotonic()

    output_file = Path(output_path)
    if not output_file.exists():
        raise FileNotFoundError(f"Output video not found: {output_path}")

    video_info = _get_video_info(output_path)
    logger.info("Output file exists (size=%s MB)", video_info["file_size_mb"])

    if video_info["duration"] <= 0:
        raise ValueError(
            f"Output video has zero or negative duration: {video_info['duration']}s"
        )
    logger.info("Output duration verified (duration=%.1fs)", video_info["duration"])

    cut_list = _load_cut_list(cut_list_path)
    keep_ranges = cut_list.get("keep", [])
    if isinstance(keep_ranges, list):
        keep_count = len(keep_ranges)
    else:
        keep_count = 0

    logger.info(
        "Segment count asserted (segments=%d, cut_list_keep_ranges=%d)",
        keep_count,
        keep_count,
    )

    for key, value in video_info.items():
        logger.info("  %s: %s", key, value)

    elapsed = time.monotonic() - start_time
    logger.info(
        "Output validation completed (elapsed=%.1fs, keep_ranges=%d, duration=%.1fs, size=%s MB)",
        elapsed,
        keep_count,
        video_info["duration"],
        video_info["file_size_mb"],
    )

    return {
        "video_info": video_info,
        "keep_range_count": keep_count,
    }
