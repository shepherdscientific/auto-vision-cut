"""Tests for the retake/false-start deduplication module."""

import json
from pathlib import Path

from autovideo.dedup import (
    _is_false_start,
    _normalize,
    _select_best_take,
    _similarity,
    detect_retake_clusters,
    run,
)


def test_normalize_strips_punctuation_and_lower() -> None:
    assert _normalize("Hello, World!") == "hello world"


def test_similarity_identical() -> None:
    assert _similarity("hello world", "hello world") == 1.0


def test_similarity_completely_different() -> None:
    assert _similarity("abc xyz", "123 456") < 0.3


def test_similarity_near_duplicate() -> None:
    assert _similarity(
        "Hello world this is a test",
        "hello world this is a test",
    ) > 0.9


def test_is_false_start_patterns() -> None:
    assert _is_false_start("Let me start over here") is True
    assert _is_false_start("Wait, let me rephrase that") is True
    assert _is_false_start("Actually, let me redo this") is True
    assert _is_false_start("Scratch that") is True
    assert _is_false_start("No, that wasn't right") is True
    assert _is_false_start("This is normal content") is False


def test_detect_retake_clusters_empty() -> None:
    assert detect_retake_clusters([]) == []


def test_detect_retake_clusters_single_segment() -> None:
    segments = [{"text": "hello world"}]
    assert detect_retake_clusters(segments) == []


def test_detect_retake_clusters_finds_duplicates() -> None:
    segments = [
        {"text": "Welcome to the tutorial today"},
        {"text": "Welcome to the tutorial today"},
        {"text": "Welcome to the tutorial today"},
        {"text": "Now we will begin"},
    ]
    clusters = detect_retake_clusters(segments, similarity_threshold=0.75)
    assert len(clusters) == 1
    assert clusters[0] == [0, 1, 2]


def test_detect_retake_clusters_no_false_positives() -> None:
    segments = [
        {"text": "Hello world"},
        {"text": "Goodbye world"},
        {"text": "Farewell earth"},
    ]
    clusters = detect_retake_clusters(segments, similarity_threshold=0.75)
    assert clusters == []


def test_select_best_take_prefers_last_sentence_boundary() -> None:
    segments = [
        {"text": "Welcome to", "start": 0.0, "end": 2.0},
        {"text": "Welcome to the tutorial today.", "start": 2.5, "end": 5.0},
    ]
    best = _select_best_take([0, 1], segments)
    assert best == 1


def test_select_best_take_prefers_longer() -> None:
    segments = [
        {"text": "Hi", "start": 0.0, "end": 1.0},
        {"text": "Hello everyone and welcome back to the channel", "start": 1.5, "end": 4.0},
    ]
    best = _select_best_take([0, 1], segments)
    assert best == 1


def test_run_flags_false_starts(tmp_path: Path) -> None:
    segments = [
        {"id": 0, "start": 0.0, "end": 2.0, "text": "Let me start over", "confidence": 0.9},
        {"id": 1, "start": 2.5, "end": 5.0, "text": "Hello world today", "confidence": 0.9},
    ]
    seg_path = tmp_path / "segments.json"
    seg_path.write_text(json.dumps({"segments": segments}))

    run(str(seg_path), output_dir=str(tmp_path))

    with open(seg_path, "r") as f:
        data = json.load(f)

    assert data["segments"][0].get("false_start") is True
    assert data["segments"][0].get("dedup_reason") == "false_start_detected"
    assert data["segments"][1].get("false_start") is None


def test_run_flags_retake_clusters(tmp_path: Path) -> None:
    segments = [
        {"id": 0, "start": 0.0, "end": 2.0,
         "text": "Welcome to the tutorial", "confidence": 0.9},
        {"id": 1, "start": 2.5, "end": 5.0,
         "text": "Welcome to the tutorial today", "confidence": 0.9},
        {"id": 2, "start": 5.5, "end": 8.0,
         "text": "Now we begin", "confidence": 0.9},
    ]
    seg_path = tmp_path / "segments.json"
    seg_path.write_text(json.dumps({"segments": segments}))

    run(str(seg_path), output_dir=str(tmp_path))

    with open(seg_path, "r") as f:
        data = json.load(f)

    # cluster 0,1 — best take should be 1 (longer + sentence boundary)
    assert data["segments"][0].get("retake_cluster_id") == 0
    assert data["segments"][0].get("is_best_take") is False
    assert data["segments"][0].get("dedup_reason") == "retake_inferior_take (cluster 0)"

    assert data["segments"][1].get("retake_cluster_id") == 0
    assert data["segments"][1].get("is_best_take") is True

    assert data["segments"][2].get("retake_cluster_id") is None


def test_run_no_changes_when_nothing_to_dedup(tmp_path: Path) -> None:
    segments = [
        {"id": 0, "start": 0.0, "end": 2.0, "text": "Hello world", "confidence": 0.9},
        {"id": 1, "start": 2.5, "end": 5.0, "text": "Completely different text", "confidence": 0.9},
    ]
    seg_path = tmp_path / "segments.json"
    seg_path.write_text(json.dumps({"segments": segments}))

    run(str(seg_path), output_dir=str(tmp_path))

    with open(seg_path, "r") as f:
        data = json.load(f)

    assert data["segments"][0].get("false_start") is None
    assert data["segments"][0].get("is_best_take") is None
    assert data["segments"][1].get("false_start") is None
    assert data["segments"][1].get("is_best_take") is None
