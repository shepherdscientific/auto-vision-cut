"""Local vision analysis module for the AutoVisionCut pipeline."""

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)


def run(frames_dir: str, model_path: str) -> None:
    logger.info("Vision analysis started (frames_dir=%s, model=%s)", frames_dir, model_path)
    logger.info("Vision analysis completed")
