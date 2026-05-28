"""Automated assembly module for the AutoVisionCut pipeline."""

import json
import shutil
import time
from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    VideoFileClip,
    concatenate_videoclips,
)

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)


def _load_cut_list(path: str) -> list[dict[str, int]]:
    with open(path, "r") as f:
        data = json.load(f)
    keep = data.get("keep", [])
    if not isinstance(keep, list):
        raise ValueError(f"cut_list.json 'keep' must be a list, got {type(keep).__name__}")
    return keep


def run(
    video_path: str,
    cut_list_path: str,
    output_path: str,
    temp_dir: str = "output/temp",
    cleanup: bool = True,
    voiceover_path: str | None = None,
) -> None:
    logger.info("Video assembly started (video=%s, cuts=%s)", video_path, cut_list_path)
    start_time = time.monotonic()

    keep_ranges = _load_cut_list(cut_list_path)
    logger.info("Loaded %d keep ranges from cut list", len(keep_ranges))

    if not keep_ranges:
        logger.warning("No keep ranges found in cut list, skipping assembly")
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
        logger.info("Slicing segment %d: %.1fs → %.1fs", i + 1, start, end)
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
                "Failed to apply voiceover overlay: %s — rendering without voiceover", exc
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

    elapsed = time.monotonic() - start_time
    logger.info("Video assembly completed (elapsed=%.1fs)", elapsed)
