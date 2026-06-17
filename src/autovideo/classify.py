"""LLM segment classifier for the AutoVisionCut pipeline.

Feeds timestamped transcript segments through an LLM under the cut/keep
criteria prompt and produces a labelled cut_list.json with per-segment
decisions, reasons, and confidence scores.
"""
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from autovideo.config import Config
from autovideo.logging_setup import get_module_logger
from autovideo.model_router import RouterError, get_provider


class ClassifyError(Exception):
    """Raised on unrecoverable classifier failures (LLM fault, parse failure)."""

logger = get_module_logger(__name__)

CUT_LIST_FILENAME = "cut_list.json"
CLASSIFY_DELAY = 1.0
CLASSIFY_BACKOFF = 2.0
CLASSIFY_MAX_RETRIES = 3
MAX_TOKENS = 4096

_FENCE_PATTERN = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def _load_segments(segments_path: str) -> list[dict[str, Any]]:
    with open(segments_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    segments = data.get("segments", [])
    if not isinstance(segments, list):
        raise ValueError(
            f"Expected 'segments' key to contain a list, got {type(segments).__name__}"
        )
    return segments


def _strip_fences(raw: str) -> str:
    match = _FENCE_PATTERN.search(raw)
    return match.group(1).strip() if match else raw.strip()


def _parse_json_output(raw: str) -> dict[str, Any]:
    cleaned = _strip_fences(raw)
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        raise ClassifyError("No JSON object found in LLM output")
    try:
        return json.loads(cleaned[first_brace : last_brace + 1])
    except json.JSONDecodeError as exc:
        raise ClassifyError(f"Failed to parse LLM JSON output: {exc}") from exc


def _load_vision_log(output_dir: str) -> list[dict[str, Any]]:
    vision_path = os.path.join(output_dir, "vision_log.json")
    if not os.path.isfile(vision_path):
        return []
    try:
        with open(vision_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _merge_vision_into_segments(
    segments: list[dict[str, Any]],
    vision_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not vision_events:
        return segments

    merged: list[dict[str, Any]] = []
    for seg in segments:
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", 0.0)
        coverage = [e for e in vision_events if seg_start <= e.get("timestamp", 0) <= seg_end]
        active_count = sum(1 for e in coverage if e.get("active") is True)
        inactive_count = sum(1 for e in coverage if e.get("active") is False)
        descriptions = [e.get("description", "") for e in coverage if e.get("active") is not None]

        has_vision = (active_count + inactive_count) > 0
        if has_vision:
            seg["vision_active"] = active_count >= inactive_count
        else:
            seg["vision_active"] = None
        seg["vision_descriptions"] = descriptions
        merged.append(seg)

    return merged


def _build_classify_prompt(
    segments: list[dict[str, Any]],
    criteria_text: str,
    context_text: str | None = None,
) -> str:
    parts: list[str] = []

    parts.append(criteria_text.strip())

    if context_text:
        parts.append("\n\n## Supplementary Context\n\n" + context_text.strip())

    parts.append(
        "\n\n## Transcript Segments to Classify\n\n"
        "Classify each segment below. Respond with a single JSON object "
        "following the output contract above.\n\n"
    )

    segments_json = json.dumps(segments, indent=2, ensure_ascii=False)
    parts.append(segments_json)

    return "\n\n".join(parts)


DEFAULT_CHUNK_SIZE = 6000


def _chunk_segments(
    segments: list[dict[str, Any]], max_chars: int = DEFAULT_CHUNK_SIZE
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0

    for seg in segments:
        seg_chars = len(json.dumps(seg, ensure_ascii=False))
        if current_chars + seg_chars > max_chars and current:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(seg)
        current_chars += seg_chars

    if current:
        chunks.append(current)

    return chunks


def _classify_chunk(
    provider: Any,
    model: Any,
    tokenizer: Any,
    chunk: list[dict[str, Any]],
    criteria_text: str,
    context_text: str | None = None,
    max_tokens: int = MAX_TOKENS,
) -> list[dict[str, Any]]:
    prompt = _build_classify_prompt(chunk, criteria_text, context_text)
    try:
        raw = provider.generate(model, tokenizer, prompt, max_tokens=max_tokens)
    except RouterError as e:
        raise ClassifyError(str(e)) from e
    parsed = _parse_json_output(raw)

    decisions = parsed.get("decisions")
    if not isinstance(decisions, list):
        raise ClassifyError("LLM output missing 'decisions' array")

    return decisions


def _validate_decisions(
    decisions: list[dict[str, Any]],
    expected_ids: set[int],
) -> list[dict[str, Any]]:
    seen_ids: set[int] = set()
    validated: list[dict[str, Any]] = []

    for d in decisions:
        seg_id = d.get("id")
        if not isinstance(seg_id, int):
            continue
        if seg_id not in expected_ids:
            continue
        if seg_id in seen_ids:
            continue
        seen_ids.add(seg_id)
        validated.append({
            "id": seg_id,
            "decision": "keep" if d.get("decision") != "cut" else "cut",
            "reason": str(d.get("reason", "")),
            "confidence": float(d.get("confidence", 0.5)),
            "tag": str(d.get("tag", "")),
        })

    for sid in sorted(expected_ids - seen_ids):
        validated.append({
            "id": sid,
            "decision": "keep",
            "reason": "default_keep_unmatched",
            "confidence": 0.3,
            "tag": "unknown",
        })
        logger.info("Segment %d not in LLM output — defaulted to keep", sid)

    validated.sort(key=lambda d: d["id"])
    return validated


def _apply_dedup_overrides(
    decisions: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Force-cut segments flagged by the dedup pre-pass as retakes or false starts."""
    seg_map = {s["id"]: s for s in segments}
    modified: list[dict[str, Any]] = []
    for d in decisions:
        seg_id = d["id"]
        seg = seg_map.get(seg_id, {})
        if seg.get("false_start"):
            modified.append({
                **d,
                "decision": "cut",
                "reason": "false_start_detected",
                "tag": "false_start",
            })
        elif seg.get("is_best_take") is False:
            modified.append({
                **d,
                "decision": "cut",
                "reason": f"retake_inferior_take (cluster {seg.get('retake_cluster_id')})",
                "tag": "retake",
            })
        else:
            modified.append(d)
    return modified


def rollback_classify(
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    decisions = [
        {
            "id": s["id"],
            "decision": "keep",
            "reason": "fallback_classifier_unavailable",
            "confidence": 0.3,
            "tag": "unknown",
        }
        for s in segments
    ]
    keeps = [{"start": s["start"], "end": s["end"]} for s in segments]
    total_duration = sum(s.get("duration", s["end"] - s["start"]) for s in segments)
    return _build_output(decisions, keeps, total_duration)


def _build_output(
    decisions: list[dict[str, Any]],
    keeps: list[dict[str, float]],
    total_duration: float,
) -> dict[str, Any]:
    kept_count = sum(1 for d in decisions if d["decision"] == "keep")
    cut_count = sum(1 for d in decisions if d["decision"] == "cut")
    kept_duration = sum(k["end"] - k["start"] for k in keeps)
    time_saved = round(max(0.0, total_duration - kept_duration), 3)

    return {
        "decisions": decisions,
        "keep": keeps,
        "stats": {
            "total_segments": len(decisions),
            "total_kept": kept_count,
            "total_cut": cut_count,
            "time_saved_seconds": time_saved,
        },
    }


def _write_cut_list(result: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info("Cut list saved to %s", output_path)


def classify(
    segments_path: str,
    criteria_text: str,
    model_path: str,
    output_dir: str = "output",
    context_text: str | None = None,
    *,
    max_tokens: int = MAX_TOKENS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    provider_name: str = "mlx_lm",
    base_url: str | None = None,
) -> dict[str, Any]:
    logger.info("Classifier started (segments=%s, model=%s)", segments_path, model_path)
    start_time = time.monotonic()

    segments = _load_segments(segments_path)
    if not segments:
        logger.warning("No segments to classify — writing empty cut list")
        result = rollback_classify([])
        _write_cut_list(result, Path(output_dir) / CUT_LIST_FILENAME)
        return result

    sorted_segments = sorted(segments, key=lambda s: s.get("start", 0.0))
    expected_ids = {s["id"] for s in sorted_segments}

    vision_events = _load_vision_log(output_dir)
    if vision_events:
        n_events = len(vision_events)
        n_segs = len(sorted_segments)
        logger.info("Merging %d vision events into %d segments", n_events, n_segs)
        sorted_segments = _merge_vision_into_segments(sorted_segments, vision_events)

    provider = get_provider(provider_name, base_url=base_url)
    model_load = provider.load(model_path)
    if model_load is None:
        raise ClassifyError(f"Failed to load classifier model: {model_path}")

    model, tokenizer = model_load
    chunks = _chunk_segments(sorted_segments, max_chars=chunk_size)
    logger.info("Split %d segments into %d chunk(s)", len(sorted_segments), len(chunks))

    all_decisions: list[dict[str, Any]] = []
    for i, chunk in enumerate(chunks):
        logger.info("Classifying chunk %d/%d (%d segments)", i + 1, len(chunks), len(chunk))
        chunk_decisions = _classify_chunk(
            provider, model, tokenizer, chunk, criteria_text, context_text, max_tokens=max_tokens,
        )
        all_decisions.extend(chunk_decisions)

    validated = _validate_decisions(all_decisions, expected_ids)
    validated = _apply_dedup_overrides(validated, sorted_segments)

    keeps = [
        {"start": s["start"], "end": s["end"]}
        for s in sorted_segments
        if any(d["id"] == s["id"] and d["decision"] == "keep" for d in validated)
    ]

    if len(sorted_segments) >= 2:
        total_duration = sorted_segments[-1]["end"] - sorted_segments[0]["start"]
    else:
        seg0 = sorted_segments[0]
        total_duration = seg0.get("duration", seg0["end"] - seg0["start"])

    result = _build_output(validated, keeps, total_duration)
    _write_cut_list(result, Path(output_dir) / CUT_LIST_FILENAME)

    elapsed = time.monotonic() - start_time
    s = result["stats"]
    logger.info(
        "Classifier complete: %d kept / %d cut (time_saved=%.1fs, elapsed=%.1fs)",
        s["total_kept"], s["total_cut"], s["time_saved_seconds"], elapsed,
    )

    return result


def run(
    config: Config,
    segments_path: str,
    output_dir: str | None = None,
) -> dict[str, Any]:
    out = output_dir or config.output_dir
    criteria_text = config.read_criteria()
    model_path = config.resolve_classify_model()
    context_text = config.read_context_docs() or None
    return classify(
        segments_path=segments_path,
        criteria_text=criteria_text,
        model_path=model_path,
        output_dir=out,
        context_text=context_text,
        max_tokens=config.classify_max_tokens,
        chunk_size=config.classify_chunk_size,
        provider_name=config.llm_provider,
        base_url=config.llm_base_url,
    )
