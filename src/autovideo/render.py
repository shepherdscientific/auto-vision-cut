"""Frame-accurate render module for the AutoVisionCut pipeline.

Primary path: ffmpeg concat demuxer (frame-accurate, re-encoded for clean joins).
Fallback path: MoviePy concatenation (slower, less accurate).
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import ffmpeg
from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    VideoFileClip,
    concatenate_videoclips,
)

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)


def _moviepy_assemble(
    video_path: str,
    keep_ranges: list[dict],
    output_path: str,
    temp_dir: str = "output/temp",
    cleanup: bool = True,
    voiceover_path: str | None = None,
) -> None:
    if not keep_ranges:
        logger.warning("No keep ranges found, skipping MoviePy assembly")
        return

    logger.info("Loading video: %s", video_path)
    clip = VideoFileClip(video_path)
    duration = clip.duration
    logger.info("Video loaded (duration=%.1fs)", duration)

    subclips = []
    for i, rng in enumerate(keep_ranges):
        start = max(0.0, float(rng["start"]))
        end = min(duration, float(rng["end"]))
        if end <= start:
            logger.warning("Skipping invalid range #%d: start=%d end=%d", i, int(start), int(end))
            continue
        logger.info("Slicing segment %d: %.1fs -> %.1fs", i + 1, start, end)
        subclip = clip.subclipped(start, end)
        subclips.append(subclip)

    if not subclips:
        logger.warning("No valid subclips produced, skipping assembly")
        clip.close()
        return

    logger.info("Concatenating %d subclips", len(subclips))
    final = concatenate_videoclips(subclips)

    if voiceover_path:
        logger.info("Processing voiceover overlay: %s", voiceover_path)
        try:
            vo_audio = AudioFileClip(voiceover_path)
            if vo_audio.duration > final.duration:
                vo_audio = vo_audio.subclipped(0, final.duration)
            vo_audio = vo_audio.with_volume_scaled(0.7)

            if final.audio is not None:
                mixed = CompositeAudioClip([final.audio, vo_audio])
                final = final.with_audio(mixed)
            else:
                final = final.with_audio(vo_audio)
            logger.info("Voiceover overlay applied successfully")
        except Exception as exc:
            logger.warning(
                "Failed to apply voiceover overlay: %s - rendering without voiceover", exc
            )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Rendering output to %s", output_path)
    final.write_videofile(str(output_path), codec="libx264", audio_codec="aac", logger=None)
    logger.info("Render complete")

    final.close()
    clip.close()
    for subclip in subclips:
        subclip.close()

    if cleanup:
        temp_path = Path(temp_dir)
        if temp_path.exists():
            logger.info("Cleaning up temp directory: %s", temp_dir)
            shutil.rmtree(temp_path)


def _build_concat_file(
    video_path: str,
    keep_ranges: list[dict],
    duration: float,
    concat_path: str,
) -> int:
    with open(concat_path, "w") as f:
        segment_count = 0
        for rng in keep_ranges:
            start = max(0.0, float(rng["start"]))
            end = min(duration, float(rng["end"]))
            if end <= start:
                logger.warning("Skipping invalid range: start=%s end=%s", start, end)
                continue
            f.write(f"file '{video_path}'\n")
            f.write(f"inpoint {start}\n")
            f.write(f"outpoint {end}\n")
            segment_count += 1
        return segment_count


def _run_ffmpeg_concat(concat_path: str, output_path: str) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_path,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg concat failed (exit={result.returncode}):\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def run(
    video_path: str,
    cut_list_path: str,
    output_path: str,
    temp_dir: str = "output/temp",
    cleanup: bool = True,
    voiceover_path: str | None = None,
) -> None:
    logger.info("Render started (video=%s, cuts=%s)", video_path, cut_list_path)
    start_time = time.monotonic()

    with open(cut_list_path, "r") as f:
        data = json.load(f)
    keep_ranges = data.get("keep", [])
    if not isinstance(keep_ranges, list):
        raise ValueError(f"cut_list 'keep' must be a list, got {type(keep_ranges).__name__}")
    logger.info("Loaded %d keep ranges from cut list", len(keep_ranges))

    if not keep_ranges:
        logger.warning("No keep ranges found, skipping render")
        return

    if voiceover_path:
        logger.info("Voiceover path provided - falling back to MoviePy path")
        _moviepy_assemble(
            video_path=video_path,
            keep_ranges=keep_ranges,
            output_path=output_path,
            temp_dir=temp_dir,
            cleanup=cleanup,
            voiceover_path=voiceover_path,
        )
        return

    probe = ffmpeg.probe(video_path)
    duration = float(probe["format"]["duration"])

    concat_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, dir=tempfile.gettempdir()
        ) as concat_file:
            concat_path = concat_file.name
            segment_count = _build_concat_file(
                video_path=video_path,
                keep_ranges=keep_ranges,
                duration=duration,
                concat_path=concat_path,
            )

        if segment_count == 0:
            logger.warning("No valid segments to render")
            return

        _run_ffmpeg_concat(concat_path=concat_path, output_path=output_path)
        logger.info("ffmpeg concat render complete (%d segments)", segment_count)
    except Exception as exc:
        logger.warning("ffmpeg concat failed (%s) - falling back to MoviePy path", exc)
        _moviepy_assemble(
            video_path=video_path,
            keep_ranges=keep_ranges,
            output_path=output_path,
            temp_dir=temp_dir,
            cleanup=cleanup,
            voiceover_path=voiceover_path,
        )
    finally:
        if concat_path is not None and os.path.isfile(concat_path):
            os.unlink(concat_path)

    elapsed = time.monotonic() - start_time
    logger.info("Render completed (elapsed=%.1fs)", elapsed)
