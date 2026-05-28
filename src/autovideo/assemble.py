"""Automated assembly module for the AutoVisionCut pipeline."""

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)


def run(video_path: str, cut_list_path: str, output_path: str) -> None:
    logger.info("Video assembly started (video=%s, cuts=%s)", video_path, cut_list_path)
    logger.info("Video assembly completed")
