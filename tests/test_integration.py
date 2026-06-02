"""Integration and smoke tests for the full AutoVisionCut pipeline."""

import json
from pathlib import Path

import pytest

from autovideo.assemble import run as assemble_run
from autovideo.extract import run as extract_run
from autovideo.generate import run as generate_run
from autovideo.validate import run as validate_run


@pytest.mark.integration
@pytest.mark.slow
def test_full_pipeline_smoke(synthetic_video: Path, tmp_path: Path) -> None:
    """Run the full pipeline on a synthetic video and verify output."""
    output_dir = tmp_path / "output"
    temp_dir = tmp_path / "temp"

    frames = extract_run(
        video_path=str(synthetic_video),
        frame_interval=3,
        output_dir=str(temp_dir),
    )
    assert len(frames) >= 3

    vision_events = [
        {
            "timestamp": int(f.stem),
            "frame": f.name,
            "active": True,
            "description": "User is actively prototyping a feature",
        }
        for f in frames
    ]
    vision_log_path = output_dir / "vision_log.json"
    vision_log_path.parent.mkdir(parents=True, exist_ok=True)
    vision_log_path.write_text(json.dumps(vision_events, indent=2))

    cut_list = generate_run(
        vision_log_path=str(vision_log_path),
        model_path="qwen3",
        output_dir=str(output_dir),
        use_llm=False,
    )
    assert "keep" in cut_list

    output_video = output_dir / "output_master.mp4"
    assemble_run(
        video_path=str(synthetic_video),
        cut_list_path=str(output_dir / "cut_list.json"),
        output_path=str(output_video),
        temp_dir=str(temp_dir),
        cleanup=False,
    )
    assert output_video.exists()
    file_size = output_video.stat().st_size
    assert file_size > 0

    validation_result = validate_run(
        output_path=str(output_video),
        cut_list_path=str(output_dir / "cut_list.json"),
    )
    assert validation_result["keep_range_count"] == len(cut_list["keep"])
    assert validation_result["video_info"]["duration"] > 0


@pytest.mark.integration
@pytest.mark.slow
def test_full_pipeline_deterministic_with_inactive_frames(
    synthetic_video: Path, tmp_path: Path
) -> None:
    """Pipeline handles frames marked as inactive and still produces output."""
    output_dir = tmp_path / "output"
    temp_dir = tmp_path / "temp"

    frames = extract_run(
        video_path=str(synthetic_video),
        frame_interval=3,
        output_dir=str(temp_dir),
    )

    half = len(frames) // 2
    vision_events = []
    for i, f in enumerate(frames):
        vision_events.append({
            "timestamp": int(f.stem),
            "frame": f.name,
            "active": i < half,
            "description": "Active work" if i < half else "Idle, staring at screen",
        })

    vision_log_path = output_dir / "vision_log.json"
    vision_log_path.parent.mkdir(parents=True, exist_ok=True)
    vision_log_path.write_text(json.dumps(vision_events, indent=2))

    cut_list = generate_run(
        vision_log_path=str(vision_log_path),
        model_path="qwen3",
        output_dir=str(output_dir),
        use_llm=False,
    )
    assert "keep" in cut_list

    output_video = output_dir / "output_master.mp4"
    assemble_run(
        video_path=str(synthetic_video),
        cut_list_path=str(output_dir / "cut_list.json"),
        output_path=str(output_video),
        temp_dir=str(temp_dir),
        cleanup=False,
    )
    assert output_video.exists()
    assert output_video.stat().st_size > 0


@pytest.mark.integration
@pytest.mark.slow
def test_pipeline_asserts_cut_list_matches_segments(
    synthetic_video: Path, tmp_path: Path
) -> None:
    """Cut list keep ranges count matches the assembled segment count."""
    output_dir = tmp_path / "output"
    temp_dir = tmp_path / "temp"

    frames = extract_run(
        video_path=str(synthetic_video),
        frame_interval=3,
        output_dir=str(temp_dir),
    )

    vision_events = [
        {"timestamp": int(f.stem), "frame": f.name, "active": True, "description": "Working"}
        for f in frames
    ]
    vision_log_path = output_dir / "vision_log.json"
    vision_log_path.parent.mkdir(parents=True, exist_ok=True)
    vision_log_path.write_text(json.dumps(vision_events, indent=2))

    cut_list = generate_run(
        vision_log_path=str(vision_log_path),
        model_path="qwen3",
        output_dir=str(output_dir),
        use_llm=False,
    )
    assert "keep" in cut_list

    output_video = output_dir / "output_master.mp4"
    assemble_run(
        video_path=str(synthetic_video),
        cut_list_path=str(output_dir / "cut_list.json"),
        output_path=str(output_video),
        temp_dir=str(temp_dir),
        cleanup=False,
    )

    validation_result = validate_run(
        output_path=str(output_video),
        cut_list_path=str(output_dir / "cut_list.json"),
    )
    assert validation_result["keep_range_count"] == len(cut_list["keep"])
    assert validation_result["keep_range_count"] > 0


@pytest.mark.integration
def test_pipeline_rejects_nonexistent_video(tmp_path: Path) -> None:
    """Extraction raises an error when the video does not exist."""
    with pytest.raises(Exception):
        extract_run(
            video_path="/nonexistent/test.mp4",
            frame_interval=3,
            output_dir=str(tmp_path),
        )


@pytest.mark.integration
def test_extract_to_generate_to_assemble_timestamps_consistent(
    synthetic_video: Path, tmp_path: Path
) -> None:
    """Frame timestamps from extract are consistent in generate and assemble flow."""
    output_dir = tmp_path / "output"
    temp_dir = tmp_path / "temp"

    frames = extract_run(
        video_path=str(synthetic_video),
        frame_interval=3,
        output_dir=str(temp_dir),
    )
    timestamps = [int(f.stem) for f in frames]

    vision_events = [
        {"timestamp": ts, "frame": f"{ts:06d}.jpg", "active": True, "description": "Test"}
        for ts in timestamps
    ]
    vision_log_path = output_dir / "vision_log.json"
    vision_log_path.parent.mkdir(parents=True, exist_ok=True)
    vision_log_path.write_text(json.dumps(vision_events, indent=2))

    cut_list = generate_run(
        vision_log_path=str(vision_log_path),
        model_path="qwen3",
        output_dir=str(output_dir),
        use_llm=False,
    )

    assert len(cut_list["keep"]) > 0
    first_keep = cut_list["keep"][0]
    assert first_keep["start"] <= first_keep["end"]
    assert first_keep["start"] >= 0
    assert first_keep["end"] <= timestamps[-1] + 3 + 5


@pytest.mark.integration
def test_synthetic_video_fixture_is_valid(synthetic_video: Path) -> None:
    """Verify the synthetic video fixture was generated correctly."""
    assert synthetic_video.exists()
    assert synthetic_video.stat().st_size > 0
    assert synthetic_video.suffix == ".mp4"


@pytest.mark.integration
@pytest.mark.slow
def test_main_pipeline_orchestration(synthetic_video: Path, tmp_path: Path) -> None:
    """main.py orchestrates the full pipeline and produces output_master.mp4."""
    import subprocess
    import sys

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "--video", str(synthetic_video),
            "--output-dir", str(output_dir),
            "--frame-interval", "3",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )

    if result.returncode != 0:
        if "mlx" in result.stderr.lower() or "vlm" in result.stderr.lower():
            pytest.skip("VLM model not available for full pipeline test")
        assert False, f"main.py failed (exit={result.returncode}):\n{result.stderr}"

    output_video = output_dir / "output_master.mp4"
    assert output_video.exists()
    assert output_video.stat().st_size > 0


def test_main_rejects_missing_video() -> None:
    """main.py exits with code 1 when --video is missing."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "main.py"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode == 1
    assert "required" in result.stderr


def test_main_rejects_nonexistent_video() -> None:
    """main.py exits with code 1 when the video file doesn't exist."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "main.py", "--video", "/nonexistent/test.mp4"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode == 1
    assert "not found" in result.stderr
