"""Pipeline resume support for the AutoVisionCut pipeline.

Checks for existing intermediate artifacts so the pipeline can
resume from the last successful stage rather than restarting from scratch.
"""

import os
from pathlib import Path
from typing import Optional

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)


def check_artifact(path: str) -> bool:
    return os.path.isfile(path) and os.path.getsize(path) > 0


def get_pipeline_stage_status(
    output_dir: str = "output",
    video_path: Optional[str] = None,
) -> dict[str, bool]:
    vision_log_path = os.path.join(output_dir, "vision_log.json")
    cut_list_path = os.path.join(output_dir, "cut_list.json")
    output_video_path = os.path.join(output_dir, "output_master.mp4")

    status: dict[str, bool] = {
        "analyze_done": check_artifact(vision_log_path),
        "generate_done": check_artifact(cut_list_path),
        "assemble_done": check_artifact(output_video_path),
    }

    if video_path:
        status["extract_done"] = (
            Path(output_dir).exists()
            and bool(list(Path(output_dir).glob("frames/*.jpg")))
        )

    logger.info(
        "Pipeline stage status: analyze=%s generate=%s assemble=%s",
        status["analyze_done"],
        status["generate_done"],
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
    elif status.get("generate_done"):
        logger.info("Resuming from assembly stage")
    elif status.get("analyze_done"):
        logger.info("Resuming from generate stage")
    else:
        logger.info("Starting pipeline from extract stage")

    return status
