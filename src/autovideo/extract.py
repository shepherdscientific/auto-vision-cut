"""Frame extraction module for the AutoVisionCut pipeline."""

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)


def run(video_path: str, frame_interval: int) -> None:
    logger.info("Frame extraction started (video=%s, interval=%ds)", video_path, frame_interval)
    logger.info("Frame extraction completed")
