"""Local vision analysis module for the AutoVisionCut pipeline."""

import gc
import json
import time
from pathlib import Path
from typing import Any, Union

import mlx.core as mx
from mlx_vlm import generate, load

from autovideo.logging_setup import get_module_logger
from autovideo.retry import retry_with_backoff

logger = get_module_logger(__name__)

DEFAULT_VLM_PROMPT = (
    "Output exactly one JSON object with these keys: "
    '\"active\" (boolean), \"description\" (string). '
    "Set \"active\": false if this frame shows idle time "
    '(staring at screen, no visible tool use, browser tab switching '
    'without active work). Set \"active\": true and describe '
    "the physical action and tools being used."
)

MAX_TOKENS = 256
DEFAULT_BATCH_SIZE = 4
MAX_RETRIES = 3
RETRY_INITIAL_DELAY = 1.0
RETRY_BACKOFF_FACTOR = 2.0


@retry_with_backoff(
    max_retries=MAX_RETRIES,
    initial_delay=RETRY_INITIAL_DELAY,
    backoff_factor=RETRY_BACKOFF_FACTOR,
)
def _generate_frame(
    model: Any,
    processor: Any,
    prompt: str,
    frame_path: str,
) -> Any:
    return generate(
        model,
        processor,
        prompt,
        image=frame_path,
        max_tokens=MAX_TOKENS,
    )


def _resolve_frames(frames_input: Union[list[Path], str]) -> list[Path]:
    if isinstance(frames_input, str):
        frames_dir = Path(frames_input)
        if not frames_dir.is_dir():
            raise ValueError(f"Frames directory not found: {frames_input}")
        return sorted(frames_dir.glob("*.jpg"))
    return sorted(frames_input)


def run(
    frames: Union[list[Path], str],
    model_path: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    output_dir: str = "output",
) -> list[dict[str, Any]]:
    logger.info(
        "Vision analysis started (model=%s, batch_size=%d)", model_path, batch_size
    )

    start_time = time.monotonic()
    frame_list = _resolve_frames(frames)
    logger.info("Frames to analyze: %d", len(frame_list))

    if not frame_list:
        logger.warning("No frames found, skipping analysis")
        return []

    logger.info("Loading VLM model: %s", model_path)
    model, processor = load(model_path)
    logger.info("VLM model loaded")

    events: list[dict[str, Any]] = []

    for batch_start in range(0, len(frame_list), batch_size):
        batch = frame_list[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        logger.info("Processing batch %d (%d frames)", batch_num, len(batch))

        for frame_path in batch:
            try:
                timestamp_seconds = int(frame_path.stem)
                prompt = (
                    f"This is a screenshot from a screen recording at "
                    f"{timestamp_seconds} seconds. "
                    + DEFAULT_VLM_PROMPT
                )

                result = _generate_frame(
                    model=model,
                    processor=processor,
                    prompt=prompt,
                    frame_path=str(frame_path),
                )

                raw_text = result.text.strip()

                try:
                    parsed = json.loads(raw_text)
                    if "timestamp" not in parsed:
                        parsed["timestamp"] = timestamp_seconds
                    parsed["frame"] = frame_path.name
                    events.append(parsed)
                except json.JSONDecodeError:
                    logger.warning(
                        "VLM output is not valid JSON (frame=%s), using raw text",
                        frame_path.name,
                    )
                    events.append(
                        {
                            "timestamp": timestamp_seconds,
                            "frame": frame_path.name,
                            "description": raw_text,
                            "active": True,
                        }
                    )
            except Exception as exc:
                logger.error("Error processing frame %s: %s", frame_path.name, exc)
                events.append(
                    {
                        "timestamp": int(frame_path.stem),
                        "frame": frame_path.name,
                        "description": f"ERROR: {exc}",
                        "active": True,
                        "error": str(exc),
                    }
                )

        mx.eval(mx.zeros(1))
        gc.collect()

    events.sort(key=lambda e: e.get("timestamp", 0))

    elapsed = time.monotonic() - start_time
    logger.info(
        "Vision analysis completed (events=%d, elapsed=%.1fs)", len(events), elapsed
    )

    output_file = Path(output_dir) / "vision_log.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(events, f, indent=2)
    logger.info("Vision log saved to %s", output_file)

    return events
