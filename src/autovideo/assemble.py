"""Automated assembly module for the AutoVisionCut pipeline.

Delegates to src/autovideo/render.py (ffmpeg concat, frame-accurate)
with MoviePy fallback.
"""

import time

from autovideo.logging_setup import get_module_logger
from autovideo.render import run as render_run

logger = get_module_logger(__name__)


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

    render_run(
        video_path=video_path,
        cut_list_path=cut_list_path,
        output_path=output_path,
        temp_dir=temp_dir,
        cleanup=cleanup,
        voiceover_path=voiceover_path,
    )

    elapsed = time.monotonic() - start_time
    logger.info("Video assembly completed (elapsed=%.1fs)", elapsed)
