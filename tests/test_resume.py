"""Tests for the pipeline resume module."""

from pathlib import Path

from autovideo.resume import check_artifact, get_pipeline_stage_status, resume_from_stage


def test_check_artifact_exists_and_non_empty(tmp_path: Path) -> None:
    p = tmp_path / "test.json"
    p.write_text('{"key": "value"}')
    assert check_artifact(str(p)) is True


def test_check_artifact_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.json"
    p.write_text("")
    assert check_artifact(str(p)) is False


def test_check_artifact_missing_file() -> None:
    assert check_artifact("/nonexistent/file.json") is False


def test_get_pipeline_stage_status_none_done(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    status = get_pipeline_stage_status(output_dir=str(output_dir))

    assert status["analyze_done"] is False
    assert status["generate_done"] is False
    assert status["assemble_done"] is False


def test_get_pipeline_stage_status_analyze_done(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "vision_log.json").write_text('[{"active": true}]')

    status = get_pipeline_stage_status(output_dir=str(output_dir))

    assert status["analyze_done"] is True
    assert status["generate_done"] is False
    assert status["assemble_done"] is False


def test_get_pipeline_stage_status_generate_done(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "vision_log.json").write_text('[{"active": true}]')
    (output_dir / "cut_list.json").write_text('{"keep": []}')

    status = get_pipeline_stage_status(output_dir=str(output_dir))

    assert status["analyze_done"] is True
    assert status["generate_done"] is True
    assert status["assemble_done"] is False


def test_get_pipeline_stage_status_all_done(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "vision_log.json").write_text('[{"active": true}]')
    (output_dir / "cut_list.json").write_text('{"keep": []}')
    (output_dir / "output_master.mp4").write_text("fake mp4 content")

    status = get_pipeline_stage_status(output_dir=str(output_dir))

    assert status["analyze_done"] is True
    assert status["generate_done"] is True
    assert status["assemble_done"] is True


def test_get_pipeline_stage_status_empty_artifact_not_done(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "vision_log.json").write_text("")

    status = get_pipeline_stage_status(output_dir=str(output_dir))

    assert status["analyze_done"] is False


def test_resume_from_stage_returns_correct_stage(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    status = resume_from_stage(output_dir=str(output_dir))
    assert status["analyze_done"] is False
    assert status["generate_done"] is False


def test_resume_from_stage_detects_generate_done(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "vision_log.json").write_text('[{"active": true}]')
    (output_dir / "cut_list.json").write_text('{"keep": []}')

    status = resume_from_stage(output_dir=str(output_dir))
    assert status["analyze_done"] is True
    assert status["generate_done"] is True
    assert status["assemble_done"] is False


def test_resume_from_stage_all_complete(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "vision_log.json").write_text('[{"active": true}]')
    (output_dir / "cut_list.json").write_text('{"keep": []}')
    (output_dir / "output_master.mp4").write_text("fake mp4 content")

    status = resume_from_stage(output_dir=str(output_dir))
    assert status["assemble_done"] is True
