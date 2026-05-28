"""Frame extraction module for the AutoVisionCut pipeline."""

import os
import time
from pathlib import Path

import ffmpeg

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)


def run(
    video_path: str,
    frame_interval: int,
    output_dir: str = "output/temp",
) -> list[Path]:
    logger.info("Frame extraction started (video=%s, interval=%ds)", video_path, frame_interval)

    start_time = time.monotonic()

    video_abs = os.path.abspath(video_path)
    frames_dir = Path(output_dir) / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    probe = ffmpeg.probe(video_abs)
    video_stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
    duration = float(video_stream.get("duration", probe.get("format", {}).get("duration", 0)))

    fps = 1.0 / frame_interval

    (
        ffmpeg
        .input(video_abs)
        .filter("fps", fps=fps)
        .output(str(frames_dir / "raw_%06d.jpg"), start_number=0)
        .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
    )

    raw_files = sorted(frames_dir.glob("raw_*.jpg"))
    extracted: list[Path] = []
    for idx, raw_file in enumerate(raw_files):
        timestamp_seconds = idx * frame_interval
        new_name = frames_dir / f"{timestamp_seconds:06d}.jpg"
        raw_file.rename(new_name)
        extracted.append(new_name)

    elapsed = time.monotonic() - start_time

    logger.info(
        "Frame extraction completed (frames=%d, duration=%.1fs, elapsed=%.1fs)",
        len(extracted),
        duration,
        elapsed,
    )

    return extracted
