"""Script and cut-list generation module for the AutoVisionCut pipeline."""

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)


def run(vision_log_path: str, model_path: str) -> None:
    logger.info("Cut-list generation started (log=%s, model=%s)", vision_log_path, model_path)
    logger.info("Cut-list generation completed")
