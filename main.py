"""AutoVisionCut — Local Vision-to-Script-to-Cut pipeline orchestration."""

import os
import sys

from autovideo.assemble import run as assemble_run
from autovideo.classify import run as classify_run
from autovideo.config import Config
from autovideo.dedup import run as dedup_run
from autovideo.induce import induce_run
from autovideo.logging_setup import get_module_logger, setup_logging
from autovideo.resume import get_pipeline_stage_status
from autovideo.review import run as review_run
from autovideo.segment import segment_transcript
from autovideo.transcribe import transcribe
from autovideo.validate import run as validate_run

logger = get_module_logger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi"}


def _run_transcript_pipeline(
    video_path: str,
    config: Config,
    output_dir: str,
    video_label: str,
) -> int:
    status = get_pipeline_stage_status(output_dir)
    transcript_path = os.path.join(output_dir, "transcript.json")
    segments_path = os.path.join(output_dir, "segments.json")
    cut_list_path = os.path.join(output_dir, "cut_list.json")
    approved_cut_list_path = os.path.join(output_dir, "cut_list.approved.json")
    output_video_path = os.path.join(output_dir, "output_master.mp4")

    if not status.get("transcribe_done"):
        logger.info("[%s] === Stage 1: Audio Extraction + Transcription ===", video_label)
        try:
            transcript_path = transcribe(
                video_path=video_path,
                output_dir=output_dir,
            )
        except Exception as exc:
            logger.error("[%s] Transcription failed: %s", video_label, exc)
            return 1
    else:
        logger.info(
            "[%s] Transcript exists, skipping transcription (%s)",
            video_label,
            transcript_path,
        )

    if not status.get("segment_done"):
        logger.info("[%s] === Stage 2: Transcript Segmentation ===", video_label)
        try:
            segment_transcript(
                transcript_path=transcript_path,
                output_dir=output_dir,
            )
        except Exception as exc:
            logger.error("[%s] Segmentation failed: %s", video_label, exc)
            return 1

        logger.info("[%s] === Stage 2b: Retake / False-Start Deduplication ===", video_label)
        try:
            dedup_run(
                segments_path=segments_path,
                output_dir=output_dir,
            )
        except Exception as exc:
            logger.error("[%s] Deduplication failed: %s", video_label, exc)
            return 1
    else:
        logger.info(
            "[%s] Segments exist, skipping segmentation + dedup (%s)",
            video_label,
            segments_path,
        )

    if config.induce_from_path:
        logger.info("[%s] === Stage 2c: Criteria Induction ===", video_label)
        try:
            induced = induce_run(
                config=config,
                transcript_path=transcript_path,
                approved_path=(
                    approved_cut_list_path
                    if os.path.isfile(approved_cut_list_path)
                    else None
                ),
            )
            if induced:
                config.criteria_path = induced
                logger.info(
                    "[%s] Using induced criteria: %s", video_label, induced,
                )
        except Exception as exc:
            logger.warning(
                "[%s] Criteria induction failed, falling back to default: %s",
                video_label, exc,
            )

    if not status.get("generate_done"):
        logger.info("[%s] === Stage 3: LLM Segment Classification ===", video_label)
        try:
            classify_run(
                config=config,
                segments_path=segments_path,
                output_dir=output_dir,
            )
        except Exception as exc:
            logger.error("[%s] Classification failed: %s", video_label, exc)
            return 1
    else:
        logger.info(
            "[%s] Cut list exists, skipping classification (%s)",
            video_label,
            cut_list_path,
        )

    if not status.get("review_done"):
        logger.info("[%s] === Stage 4: Human Review Gate ===", video_label)
        try:
            approved = review_run(
                cut_list_path=cut_list_path,
                segments_path=segments_path,
                output_dir=output_dir,
                approval_required=config.approval_required,
            )
            if approved is not None:
                approved_cut_list_path = approved
            else:
                logger.info(
                    "[%s] Review gate blocked — re-run with approved cut list to continue",
                    video_label,
                )
                return 1
        except Exception as exc:
            logger.error("[%s] Review gate failed: %s", video_label, exc)
            return 1
    else:
        logger.info(
            "[%s] Approved cut list exists, skipping review gate (%s)",
            video_label,
            approved_cut_list_path,
        )

    if not status.get("assemble_done"):
        logger.info("[%s] === Stage 5: Video Assembly ===", video_label)
        temp_dir = os.path.join(output_dir, "temp")
        try:
            assemble_run(
                video_path=video_path,
                cut_list_path=approved_cut_list_path,
                output_path=output_video_path,
                temp_dir=temp_dir,
                cleanup=True,
            )
        except Exception as exc:
            logger.error("[%s] Video assembly failed: %s", video_label, exc)
            return 1
    else:
        logger.info(
            "[%s] Output video exists, skipping assemble (%s)",
            video_label,
            output_video_path,
        )

    logger.info("[%s] === Stage 6: Validation ===", video_label)
    try:
        validate_run(
            output_path=output_video_path,
            cut_list_path=approved_cut_list_path,
        )
    except Exception as exc:
        logger.error("[%s] Validation failed: %s", video_label, exc)
        return 1

    logger.info("[%s] Pipeline completed successfully", video_label)
    logger.info("[%s]   Output video: %s", video_label, output_video_path)
    logger.info("[%s]   Cut list:     %s", video_label, cut_list_path)

    return 0


def main(argv: list[str] | None = None) -> int:
    config = Config.from_args(argv)
    if config.video_path is None:
        print("Error: --video is required", file=sys.stderr)
        return 1

    video_paths = config.resolve_video_paths()
    if not video_paths:
        print(
            f"Error: no video files found at: {config.video_path}", file=sys.stderr
        )
        return 1

    for vp in video_paths:
        if not vp.exists():
            print(f"Error: video not found: {vp}", file=sys.stderr)
            return 1
        if vp.suffix.lower() not in VIDEO_EXTENSIONS:
            print(
                f"Error: unsupported video format: {vp.suffix} ({vp})",
                file=sys.stderr,
            )
            return 1

    base_output = config.output_dir
    os.makedirs(base_output, exist_ok=True)
    log_file = os.path.join(base_output, "pipeline.log")
    setup_logging(log_file=log_file)

    logger.info(
        "AutoVisionCut pipeline starting (videos=%d, mode=%s)",
        len(video_paths),
        config.output_mode,
    )
    logger.info("LLM model: %s", config.resolve_llm_path())

    context_paths = config.resolve_context_paths()
    if context_paths:
        logger.info(
            "Context docs: %s", ", ".join(str(p) for p in context_paths)
        )
    else:
        logger.info("No context docs provided")

    exit_code = 0
    for vp in video_paths:
        video_stem = vp.stem
        if config.output_mode == "separate":
            video_output_dir = os.path.join(base_output, video_stem)
        else:
            video_output_dir = base_output

        os.makedirs(video_output_dir, exist_ok=True)

        logger.info("--- Processing: %s ---", vp.name)
        logger.info("  Source: %s", vp)
        logger.info("  Output: %s", video_output_dir)

        rc = _run_transcript_pipeline(
            video_path=str(vp),
            config=config,
            output_dir=video_output_dir,
            video_label=vp.name,
        )
        if rc != 0:
            logger.error("Pipeline failed for: %s", vp.name)
            exit_code = rc

    if exit_code == 0:
        logger.info("All videos processed successfully")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
