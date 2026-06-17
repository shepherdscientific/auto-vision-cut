"""Retake and false-start deduplication for transcript segments.

Detects near-duplicate adjacent segments (retakes) and false starts,
marking inferior takes so the classifier can cut them.
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)

DEFAULT_SIMILARITY_THRESHOLD = 0.75

_FALSE_START_PATTERNS = [
    re.compile(r"\blet\s+me\s+(start\s+over|try\s+that\s+again|rephrase)\b", re.I),
    re.compile(r"\bwait\b\s*[.,]?\s*(let\s+me\s+)?(start\s+over|redo\s+that|try\s+again)", re.I),
    re.compile(r"\bactually\b\s*[.,]?\s*(let\s+me\s+)?(rephrase|reword|redo)", re.I),
    re.compile(r"\bscratch\s+that\b", re.I),
    re.compile(r"\bno\b\s*[.,]?\s*(that\s+(isn'?t|wasn'?t)\s+right|wait)", re.I),
]


def _normalize(text: str) -> str:
    """Lowercase and strip punctuation for comparison."""
    return re.sub(r"[^\w\s]", "", text.lower())


def _similarity(a: str, b: str) -> float:
    a_norm = _normalize(a)
    b_norm = _normalize(b)
    if not a_norm or not b_norm:
        return 0.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def _is_false_start(text: str) -> bool:
    return any(p.search(text) for p in _FALSE_START_PATTERNS)


def detect_retake_clusters(
    segments: list[dict[str, Any]], similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
) -> list[list[int]]:
    """Return list of index clusters where adjacent segments are near-duplicates."""
    clusters: list[list[int]] = []
    current_cluster: list[int] = []

    for i, seg in enumerate(segments):
        if i == 0:
            current_cluster = [i]
            continue

        prev_text = segments[i - 1].get("text", "")
        curr_text = seg.get("text", "")

        if _similarity(prev_text, curr_text) >= similarity_threshold:
            current_cluster.append(i)
        else:
            if len(current_cluster) > 1:
                clusters.append(current_cluster)
            current_cluster = [i]

    if len(current_cluster) > 1:
        clusters.append(current_cluster)

    return clusters


def _select_best_take(cluster_indices: list[int], segments: list[dict[str, Any]]) -> int:
    """Select the best take from a retake cluster.

    Prefers the last take that ends with a sentence boundary and has decent length.
    """
    best_idx = cluster_indices[-1]  # default: last take
    best_score = -1.0

    for idx in cluster_indices:
        seg = segments[idx]
        text = seg.get("text", "")
        duration = seg.get("duration", seg.get("end", 0) - seg.get("start", 0))

        # Score: longer is better, sentence boundary ending is bonus
        score = duration
        if re.search(r"[.!?…]+$", text.strip()):
            score += 2.0

        if score > best_score:
            best_score = score
            best_idx = idx

    return best_idx


def run(
    segments_path: str,
    output_dir: str = "output",
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> str:
    logger.info(
        "Dedup started (segments=%s, threshold=%.2f)",
        segments_path,
        similarity_threshold,
    )

    with open(segments_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])
    if not segments:
        logger.warning("No segments to deduplicate")
        return segments_path

    # Detect false starts
    false_start_count = 0
    for seg in segments:
        text = seg.get("text", "")
        if _is_false_start(text):
            seg["false_start"] = True
            seg["dedup_reason"] = "false_start_detected"
            false_start_count += 1

    if false_start_count:
        logger.info("Flagged %d false-start segment(s)", false_start_count)

    # Detect retake clusters
    clusters = detect_retake_clusters(segments, similarity_threshold)
    if clusters:
        logger.info("Found %d retake cluster(s)", len(clusters))

    for cluster in clusters:
        best_idx = _select_best_take(cluster, segments)
        for idx in cluster:
            seg = segments[idx]
            seg["retake_cluster_id"] = cluster[0]
            if idx == best_idx:
                seg["is_best_take"] = True
            else:
                seg["is_best_take"] = False
                seg["dedup_reason"] = f"retake_inferior_take (cluster {cluster[0]})"

    output_path = Path(output_dir) / "segments.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    total_flagged = sum(
        1
        for s in segments
        if s.get("is_best_take") is False or s.get("false_start")
    )
    logger.info("Dedup complete: flagged %d segment(s) for cutting", total_flagged)

    return str(output_path)
