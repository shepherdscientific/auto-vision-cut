"""Script and cut-list generation module for the AutoVisionCut pipeline."""

import json
import sys
import time
from pathlib import Path
from typing import Any

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)

MAX_RETRIES = 3
RETRY_INITIAL_DELAY = 1.0
RETRY_BACKOFF_FACTOR = 2.0

DEFAULT_LLM_PROMPT = (
    "You are a video editor analyzing a screen-recording prototyping session. "
    "Below is a JSON event log with timestamps, activity flags, and descriptions "
    "of what happened on screen.\n\n"
    "TASK:\n"
    "1. Identify narrative arcs — which segments show productive, focused work "
    "worth keeping.\n"
    "2. Output a JSON object with these keys:\n"
    '   - "keep": an array of {"start": <seconds>, "end": <seconds>} ranges to keep.\n'
    '   - "voiceover": a drafted narration script (2-4 paragraphs) describing '
    "the prototyping workflow seen in the video.\n\n"
    "Rules:\n"
    "- Exclude segments marked as inactive (idle, staring, no tool use).\n"
    "- Merge adjacent active segments that are less than 5 seconds apart.\n"
    "- The voiceover should read like a concise tutorial summary, not a transcript.\n\n"
    "EVENT LOG:\n"
)


def _load_vision_log(path: str) -> list[dict[str, Any]]:
    with open(path, "r") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Vision log must be a JSON array, got {type(data).__name__}")
    return data


def _filter_active(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = [e for e in events if e.get("active", True)]
    logger.info("Filtered %d events to %d active", len(events), len(active))
    return active


def _merge_adjacent_segments(
    segments: list[dict[str, int]], gap_threshold: int = 5
) -> list[dict[str, int]]:
    if not segments:
        return []
    merged = [dict(segments[0])]
    for seg in segments[1:]:
        if seg["start"] <= merged[-1]["end"] + gap_threshold:
            merged[-1]["end"] = max(merged[-1]["end"], seg["end"])
        else:
            merged.append(dict(seg))
    return merged


def _events_to_segments(
    events: list[dict[str, Any]], frame_interval: int = 3
) -> list[dict[str, int]]:
    if not events:
        return []
    sorted_events = sorted(events, key=lambda e: e.get("timestamp", 0))
    segments: list[dict[str, int]] = []
    cur_start = 0
    cur_end = 0
    started = False

    for event in sorted_events:
        ts = int(event.get("timestamp", 0))
        if not started:
            cur_start = ts
            cur_end = ts + frame_interval
            started = True
        elif ts <= cur_end + frame_interval:
            cur_end = max(cur_end, ts + frame_interval)
        else:
            segments.append({"start": cur_start, "end": cur_end})
            cur_start = ts
            cur_end = ts + frame_interval

    if started:
        segments.append({"start": cur_start, "end": cur_end})

    return _merge_adjacent_segments(segments)


def _build_voiceover_from_descriptions(events: list[dict[str, Any]]) -> str:
    descriptions = [
        e.get("description", "")
        for e in events
        if e.get("description") and e.get("active", True)
    ]
    if not descriptions:
        return "No active content detected in this prototyping session."

    lines = ["In this prototyping session, the following activities were observed:"]
    for i, desc in enumerate(descriptions[:20], 1):
        lines.append(f"{i}. {desc.strip().rstrip('.')}.")
    return "\n".join(lines)


def _get_llm_module() -> Any:
    return sys.modules.get("mlx_lm")


def _llm_generate_with_retry(
    model: Any,
    tokenizer: Any,
    prompt: str,
    max_tokens: int,
) -> str | None:
    mlx_lm = _get_llm_module()
    if mlx_lm is None:
        return None

    delay = RETRY_INITIAL_DELAY
    last_exception: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return mlx_lm.generate(model, tokenizer, prompt, max_tokens=max_tokens)
        except Exception as exc:
            last_exception = exc
            if attempt < MAX_RETRIES:
                logger.warning(
                    "LLM generate attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1,
                    MAX_RETRIES + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)
                delay *= RETRY_BACKOFF_FACTOR

    logger.warning(
        "LLM generation failed after %d attempts: %s — falling back to deterministic mode",
        MAX_RETRIES + 1,
        last_exception,
    )
    return None


def _build_prompt(
    events: list[dict[str, Any]],
    context_text: str | None = None,
) -> str:
    prompt = DEFAULT_LLM_PROMPT
    if context_text:
        prompt = (
            "You are a video editor analyzing a screen-recording prototyping session. "
            "Below is a JSON event log with timestamps, activity flags, and "
            "descriptions of what happened on screen.\n\n"
            "CONTEXT DOCUMENTS (project specification / reference):\n"
            f"{context_text}\n\n"
            "Use the context documents to better judge which segments are "
            "on-topic productive work vs irrelevant browsing or idle time.\n\n"
            + DEFAULT_LLM_PROMPT.partition("TASK:\n")[2]
        )
    return prompt + json.dumps(events, indent=2)


def _generate_with_llm(
    events: list[dict[str, Any]],
    model_path: str,
    max_tokens: int = 1024,
    context_text: str | None = None,
) -> dict[str, Any]:
    mlx_lm = _get_llm_module()
    if mlx_lm is None:
        try:
            import mlx_lm  # noqa: F811
        except ImportError:
            logger.warning(
                "mlx_lm not available, using deterministic cut-list generation"
            )
            return _generate_deterministic(events)

    try:
        logger.info("Loading LLM model: %s", model_path)
        load_result = mlx_lm.load(model_path)
        model = load_result[0]
        tokenizer = load_result[1]
        logger.info("LLM model loaded")
    except Exception as exc:
        logger.warning(
            "Failed to load LLM model %s: %s — falling back to deterministic mode",
            model_path,
            exc,
        )
        return _generate_deterministic(events)

    prompt = _build_prompt(events, context_text)
    logger.info("Sending prompt to LLM (%d events, %d chars)", len(events), len(prompt))

    raw_output = _llm_generate_with_retry(model, tokenizer, prompt, max_tokens)
    if raw_output is None:
        return _generate_deterministic(events)

    json_start = raw_output.find("{")
    json_end = raw_output.rfind("}")
    if json_start != -1 and json_end != -1:
        try:
            json_str = raw_output[json_start : json_end + 1]
            result = json.loads(json_str)
            logger.info(
                "LLM generated cut-list with %d keep ranges",
                len(result.get("keep", [])),
            )
            return result
        except json.JSONDecodeError:
            logger.warning("LLM output JSON parsing failed, falling back")
            return _generate_deterministic(events)
    else:
        logger.warning("LLM output did not contain valid JSON, falling back")
        return _generate_deterministic(events)


def _generate_deterministic(events: list[dict[str, Any]]) -> dict[str, Any]:
    active = _filter_active(events)
    keep = _events_to_segments(active)
    voiceover = _build_voiceover_from_descriptions(active)
    logger.info("Deterministic cut-list generated (%d keep ranges)", len(keep))
    return {"keep": keep, "voiceover": voiceover}


def run(
    vision_log_path: str,
    model_path: str,
    output_dir: str = "output",
    frame_interval: int = 3,
    use_llm: bool = False,
    context_text: str | None = None,
) -> dict[str, Any]:
    logger.info(
        "Cut-list generation started (log=%s, model=%s, llm=%s, context=%s)",
        vision_log_path,
        model_path,
        use_llm,
        "yes" if context_text else "no",
    )

    start_time = time.monotonic()

    events = _load_vision_log(vision_log_path)
    logger.info("Loaded %d events from vision log", len(events))

    if use_llm:
        result = _generate_with_llm(events, model_path, context_text=context_text)
    else:
        result = _generate_deterministic(events)

    elapsed = time.monotonic() - start_time
    logger.info(
        "Cut-list generation completed (keep_ranges=%d, voiceover_chars=%d, elapsed=%.1fs)",
        len(result.get("keep", [])),
        len(result.get("voiceover", "")),
        elapsed,
    )

    output_file = Path(output_dir) / "cut_list.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    logger.info("Cut list saved to %s", output_file)

    return result
