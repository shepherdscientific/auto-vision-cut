"""Tests for the human-in-the-loop review gate."""

import csv
import json
from pathlib import Path

from autovideo.review import (
    export_csv,
    generate_review_md,
    run,
)

SAMPLE_CUT_LIST: dict = {
    "decisions": [
        {"id": 1, "decision": "keep", "reason": "substantive explanation",
         "confidence": 0.9, "tag": "substantive"},
        {"id": 2, "decision": "cut", "reason": "filler words",
         "confidence": 0.85, "tag": "filler"},
        {"id": 3, "decision": "keep", "reason": "hook",
         "confidence": 0.8, "tag": "hook"},
    ],
    "keep": [
        {"start": 0.0, "end": 5.0},
        {"start": 12.0, "end": 18.0},
    ],
    "stats": {
        "total_segments": 3,
        "total_kept": 2,
        "total_cut": 1,
        "time_saved_seconds": 5.0,
    },
}

SAMPLE_SEGMENTS: dict = {
    "segments": [
        {"id": 1, "start": 0.0, "end": 5.0, "text": "Substantive explanation.", "duration": 5.0},
        {"id": 2, "start": 5.0, "end": 7.0, "text": "Like, um, you know.", "duration": 2.0},
        {"id": 3, "start": 12.0, "end": 18.0, "text": "Welcome to the video!", "duration": 6.0},
    ],
    "silences": [
        {"start": 7.0, "end": 12.0, "duration": 5.0},
    ],
    "stats": {"total_segments": 3, "total_duration": 18.0},
}


def test_generate_review_md_includes_stats() -> None:
    md = generate_review_md(SAMPLE_CUT_LIST)
    assert "Total segments:" in md
    assert "Kept:" in md
    assert "Cut:" in md
    assert "5.0s" in md


def test_generate_review_md_includes_table() -> None:
    md = generate_review_md(SAMPLE_CUT_LIST)
    assert "| # | Timestamp" in md
    assert "keep" in md.lower() or "KEEP" in md
    assert "substantive" in md
    assert "filler" in md


def test_export_csv_writes_decisions(tmp_path: Path) -> None:
    csv_path = str(tmp_path / "review.csv")
    export_csv(SAMPLE_CUT_LIST, csv_path)
    assert Path(csv_path).exists()

    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 3
    assert rows[0]["id"] == "1"
    assert rows[0]["decision"] == "keep"


def test_export_csv_empty_decisions(tmp_path: Path) -> None:
    csv_path = str(tmp_path / "empty_review.csv")
    export_csv({"decisions": [], "keep": [], "stats": {}}, csv_path)
    assert not Path(csv_path).exists()


def test_run_generates_artifacts_when_no_approval(tmp_path: Path) -> None:
    output_dir = str(tmp_path)
    segments_path = tmp_path / "segments.json"
    segments_path.write_text(json.dumps(SAMPLE_SEGMENTS))
    cut_list_path = tmp_path / "cut_list.json"
    cut_list_path.write_text(json.dumps(SAMPLE_CUT_LIST))

    result = run(
        cut_list_path=str(cut_list_path),
        segments_path=str(segments_path),
        output_dir=output_dir,
        approval_required=True,
    )

    assert result is None
    assert (tmp_path / "review.md").exists()
    assert (tmp_path / "cut_list_review.csv").exists()


def test_run_generates_artifacts_and_passes_when_no_approval_required(tmp_path: Path) -> None:
    output_dir = str(tmp_path)
    segments_path = tmp_path / "segments.json"
    segments_path.write_text(json.dumps(SAMPLE_SEGMENTS))
    cut_list_path = tmp_path / "cut_list.json"
    cut_list_path.write_text(json.dumps(SAMPLE_CUT_LIST))

    result = run(
        cut_list_path=str(cut_list_path),
        segments_path=str(segments_path),
        output_dir=output_dir,
        approval_required=False,
    )

    assert result is not None
    assert Path(result).exists()
    approved = json.loads(Path(result).read_text())
    assert approved["stats"]["total_kept"] == 2
    assert approved["stats"]["total_cut"] == 1


def test_run_returns_existing_approval_path(tmp_path: Path) -> None:
    output_dir = str(tmp_path)
    approved_path = tmp_path / "cut_list.approved.json"
    approved_path.write_text(json.dumps(SAMPLE_CUT_LIST))

    result = run(
        cut_list_path="/nonexistent/cut_list.json",
        segments_path="/nonexistent/segments.json",
        output_dir=output_dir,
        approval_required=True,
    )

    assert result == str(approved_path)


def test_run_applies_csv_overrides(tmp_path: Path) -> None:
    output_dir = str(tmp_path)
    segments_path = tmp_path / "segments.json"
    segments_path.write_text(json.dumps(SAMPLE_SEGMENTS))
    cut_list_path = tmp_path / "cut_list.json"
    cut_list_path.write_text(json.dumps(SAMPLE_CUT_LIST))

    run(
        cut_list_path=str(cut_list_path),
        segments_path=str(segments_path),
        output_dir=output_dir,
        approval_required=True,
    )

    csv_path = tmp_path / "cut_list_review.csv"
    assert csv_path.exists()

    rows: list[dict[str, str]] = []
    with open(str(csv_path), "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    assert len(rows) == 3

    rows[0]["decision"] = "cut"
    with open(str(csv_path), "w", newline="") as f:
        fieldnames = ["id", "start", "end", "decision", "confidence", "tag", "reason", "text"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    result = run(
        cut_list_path=str(cut_list_path),
        segments_path=str(segments_path),
        output_dir=output_dir,
        approval_required=True,
    )

    assert result is not None
    approved = json.loads(Path(result).read_text())
    assert approved["stats"]["total_cut"] == 2
    assert approved["decisions"][0]["decision"] == "cut"


def test_run_enriches_with_segment_data(tmp_path: Path) -> None:
    output_dir = str(tmp_path)
    segments_path = tmp_path / "segments.json"
    segments_path.write_text(json.dumps(SAMPLE_SEGMENTS))
    cut_list_path = tmp_path / "cut_list.json"
    cut_list_path.write_text(json.dumps(SAMPLE_CUT_LIST))

    run(
        cut_list_path=str(cut_list_path),
        segments_path=str(segments_path),
        output_dir=output_dir,
        approval_required=False,
    )

    csv_path = tmp_path / "cut_list_review.csv"
    assert csv_path.exists()

    with open(str(csv_path), "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 3
    assert rows[0]["text"] == "Substantive explanation."
    assert rows[0]["start"] == "0.0"
    assert rows[0]["end"] == "5.0"


def test_run_empty_decisions(tmp_path: Path) -> None:
    output_dir = str(tmp_path)
    segments_path = tmp_path / "segments.json"
    segments_path.write_text(json.dumps(SAMPLE_SEGMENTS))
    cut_list_path = tmp_path / "cut_list.json"
    cut_list_path.write_text(json.dumps({"decisions": [], "keep": [], "stats": {}}))

    result = run(
        cut_list_path=str(cut_list_path),
        segments_path=str(segments_path),
        output_dir=output_dir,
        approval_required=False,
    )

    assert result is not None
    approved = json.loads(Path(result).read_text())
    assert len(approved["decisions"]) == 0


def test_run_blocks_on_corrupt_segments(tmp_path: Path) -> None:
    output_dir = str(tmp_path)
    segments_path = tmp_path / "segments.json"
    segments_path.write_text("this is not json")
    cut_list_path = tmp_path / "cut_list.json"
    cut_list_path.write_text(json.dumps(SAMPLE_CUT_LIST))

    result = run(
        cut_list_path=str(cut_list_path),
        segments_path=str(segments_path),
        output_dir=output_dir,
        approval_required=True,
    )

    assert result is None
    assert (tmp_path / "review.md").exists()
