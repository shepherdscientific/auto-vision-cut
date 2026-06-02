"""AutoVisionCut — Local Vision-to-Script-to-Cut pipeline orchestration."""

import os
import sys

from autovideo.analyze import run as analyze_run
from autovideo.assemble import run as assemble_run
from autovideo.config import Config
from autovideo.extract import run as extract_run
from autovideo.generate import run as generate_run
from autovideo.logging_setup import get_module_logger, setup_logging
from autovideo.resume import get_pipeline_stage_status
from autovideo.validate import run as validate_run

logger = get_module_logger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi"}


def _run_pipeline(
    video_path: str,
    config: Config,
    output_dir: str,
    video_label: str,
) -> int:
    vlm_model = config.resolve_vlm_path()
    llm_model = config.resolve_llm_path()
    temp_dir = os.path.join(output_dir, "temp")
    frame_interval = config.frame_interval
    context_text = config.read_context_docs()

    status = get_pipeline_stage_status(output_dir)
    vision_log_path = os.path.join(output_dir, "vision_log.json")
    cut_list_path = os.path.join(output_dir, "cut_list.json")
    output_video_path = os.path.join(output_dir, "output_master.mp4")
    frames_dir = os.path.join(temp_dir, "frames")

    logger.info(
        "Config: frame_interval=%d vlm=%s llm=%s output=%s",
        frame_interval,
        vlm_model,
        llm_model,
        output_dir,
    )

    if not status.get("analyze_done"):
        logger.info("[%s] === Stage 1: Frame Extraction ===", video_label)
        try:
            frames = extract_run(
                video_path=video_path,
                frame_interval=frame_interval,
                output_dir=temp_dir,
            )
        except Exception as exc:
            logger.error("[%s] Frame extraction failed: %s", video_label, exc)
            return 1

        if not frames:
            logger.error(
                "[%s] No frames extracted — pipeline cannot proceed", video_label
            )
            return 1

        logger.info("[%s] === Stage 2: Vision Analysis ===", video_label)
        try:
            analyze_run(
                frames=frames_dir,
                model_path=vlm_model,
                output_dir=output_dir,
            )
        except FileNotFoundError as exc:
            logger.error(
                "[%s] VLM model not found: %s. "
                "Install it with: mlx_vlm.download --model %s",
                video_label,
                exc,
                vlm_model,
            )
            return 1
        except Exception as exc:
            logger.error("[%s] Vision analysis failed: %s", video_label, exc)
            return 1
    else:
        logger.info(
            "[%s] Vision log exists, skipping extract + analyze (%s)",
            video_label,
            vision_log_path,
        )

    if not status.get("generate_done") or not os.path.isfile(vision_log_path):
        logger.info("[%s] === Stage 3: Cut-List Generation ===", video_label)
        try:
            generate_run(
                vision_log_path=vision_log_path,
                model_path=llm_model,
                output_dir=output_dir,
                frame_interval=frame_interval,
                use_llm=False,
                context_text=context_text if context_text else None,
            )
        except FileNotFoundError as exc:
            logger.error(
                "[%s] LLM model not found: %s. "
                "Install it with: mlx_lm.download --model %s",
                video_label,
                exc,
                llm_model,
            )
            return 1
        except Exception as exc:
            logger.error("[%s] Cut-list generation failed: %s", video_label, exc)
            return 1
    else:
        logger.info(
            "[%s] Cut list exists, skipping generate (%s)",
            video_label,
            cut_list_path,
        )

    if not status.get("assemble_done"):
        logger.info("[%s] === Stage 4: Video Assembly ===", video_label)
        try:
            assemble_run(
                video_path=video_path,
                cut_list_path=cut_list_path,
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

    logger.info("[%s] === Stage 5: Validation ===", video_label)
    try:
        validate_run(
            output_path=output_video_path,
            cut_list_path=cut_list_path,
        )
    except Exception as exc:
        logger.error("[%s] Validation failed: %s", video_label, exc)
        return 1

    logger.info("[%s] Pipeline completed successfully", video_label)
    logger.info("[%s]   Output video: %s", video_label, output_video_path)
    logger.info("[%s]   Vision log:   %s", video_label, vision_log_path)
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
    logger.info("VLM model: %s", config.resolve_vlm_path())
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

        rc = _run_pipeline(
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
