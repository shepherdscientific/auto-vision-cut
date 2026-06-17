"""Pipeline orchestrator for the AutoVisionCut pipeline.

Runs the full pipeline: transcribe → segment → dedup → extract → analyze
→ classify → review → assemble.
"""

import logging
import os
import sys
import time
from typing import cast

from autovideo.analyze import run as analyze_run
from autovideo.assemble import run as assemble_run
from autovideo.classify import run as classify_run
from autovideo.config import Config
from autovideo.dedup import run_from_config as dedup_run
from autovideo.extract import run as extract_run
from autovideo.induce import induce_criteria_from_config
from autovideo.logging_setup import get_module_logger, setup_logging
from autovideo.resume import resume_from_stage
from autovideo.review import run as review_run
from autovideo.segment import run as segment_run
from autovideo.transcribe import run as transcribe_run

logger = get_module_logger(__name__)


def run_pipeline(config: Config) -> None:
    if config.video_path is None:
        logger.error("No video path specified")
        sys.exit(1)
    video_path: str = config.video_path
    output_dir = config.output_dir
    os.makedirs(output_dir, exist_ok=True)

    status = resume_from_stage(output_dir=output_dir, video_path=video_path)

    if status.get("assemble_done"):
        logger.info("Pipeline already complete — exiting")
        return

    transcript_path = os.path.join(output_dir, "transcript.json")
    segments_path = os.path.join(output_dir, "segments.json")
    cut_list_path = os.path.join(output_dir, "cut_list.json")
    approved_cut_list_path = os.path.join(output_dir, "cut_list.approved.json")
    output_video_path = os.path.join(output_dir, "output_master.mp4")

    if not status.get("transcribe_done"):
        transcript_path = transcribe_run(config, video_path, output_dir)
    else:
        logger.info("Transcription already done — skipping")

    if config.induce_from_path:
        induce_criteria_from_config(config, transcript_path)

    if not status.get("segment_done"):
        segments_path = segment_run(config, transcript_path, output_dir)
    else:
        logger.info("Segmentation already done — skipping")

    if not status.get("dedup_done"):
        dedup_run(config, segments_path, output_dir)
    else:
        logger.info("Dedup already done — skipping")

    if not status.get("vision_done"):
        frames = extract_run(video_path, config.frame_interval, output_dir)
        if frames:
            vlm_model = config.resolve_vlm_path()
            analyze_run(frames, vlm_model, output_dir=output_dir)
    else:
        logger.info("Vision analysis already done — skipping")

    if not status.get("generate_done"):
        classify_run(config, segments_path, output_dir)
    else:
        logger.info("Classification already done — skipping")

    if not status.get("review_done"):
        approved = review_run(cut_list_path, segments_path, output_dir, config.approval_required)
        if approved is None:
            logger.info("Review gate blocking — pipeline halting")
            return
    else:
        logger.info("Review already done — skipping")

    if not status.get("assemble_done"):
        assemble_run(
            video_path=video_path,
            cut_list_path=approved_cut_list_path,
            output_path=output_video_path,
            temp_dir=os.path.join(output_dir, "temp"),
        )
    else:
        logger.info("Assembly already done — skipping")

    logger.info("Pipeline complete — output: %s", output_video_path)


def main() -> None:
    config = Config.from_args()
    setup_logging(level=logging.INFO)
    start = time.monotonic()
    try:
        run_pipeline(config)
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
    elapsed = time.monotonic() - start
    logger.info("Total elapsed time: %.1fs", elapsed)


if __name__ == "__main__":
    main()
