"""Pipeline resume support for the AutoVisionCut pipeline.

Checks for existing intermediate artifacts so the pipeline can
resume from the last successful stage rather than restarting from scratch.
"""

import os
from typing import Optional

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)


def check_artifact(path: str) -> bool:
    return os.path.isfile(path) and os.path.getsize(path) > 0


def get_pipeline_stage_status(
    output_dir: str = "output",
    video_path: Optional[str] = None,
) -> dict[str, bool]:
    transcript_path = os.path.join(output_dir, "transcript.json")
    segments_path = os.path.join(output_dir, "segments.json")
    cut_list_path = os.path.join(output_dir, "cut_list.json")
    approved_cut_list_path = os.path.join(output_dir, "cut_list.approved.json")
    output_video_path = os.path.join(output_dir, "output_master.mp4")

    vision_log_path = os.path.join(output_dir, "vision_log.json")

    status: dict[str, bool] = {
        "transcribe_done": check_artifact(transcript_path),
        "segment_done": check_artifact(segments_path),
        "vision_done": check_artifact(vision_log_path),
        "generate_done": check_artifact(cut_list_path),
        "review_done": check_artifact(approved_cut_list_path),
        "assemble_done": check_artifact(output_video_path),
    }

    logger.info(
        "Pipeline stage status: transcribe=%s segment=%s vision=%s "
        "generate=%s review=%s assemble=%s",
        status["transcribe_done"],
        status["segment_done"],
        status["vision_done"],
        status["generate_done"],
        status["review_done"],
        status["assemble_done"],
    )

    return status


def resume_from_stage(
    output_dir: str = "output",
    video_path: Optional[str] = None,
) -> dict[str, bool]:
    status = get_pipeline_stage_status(output_dir, video_path)

    if status.get("assemble_done"):
        logger.info("Final output already exists, all stages complete")
    elif status.get("review_done"):
        logger.info("Resuming from assembly stage")
    elif status.get("generate_done"):
        logger.info("Resuming from review gate stage")
    elif status.get("segment_done"):
        logger.info("Resuming from classification stage")
    elif status.get("transcribe_done"):
        logger.info("Resuming from segmentation stage")
    else:
        logger.info("Starting pipeline from transcription stage")

    return status
