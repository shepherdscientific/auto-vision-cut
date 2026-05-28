"""Tests for the frame extraction module."""

from pathlib import Path
from unittest import mock

import pytest

from autovideo.extract import run


@pytest.mark.slow
def test_extract_frames_from_synthetic_video(temp_dir: Path, synthetic_video: Path) -> None:
    extracted = run(
        video_path=str(synthetic_video),
        frame_interval=3,
        output_dir=str(temp_dir),
    )
    assert len(extracted) > 0
    assert all(p.suffix == ".jpg" for p in extracted)
    for p in extracted:
        assert p.exists()


def test_extract_timestamps_aligned(temp_dir: Path, synthetic_video: Path) -> None:
    extracted = run(
        video_path=str(synthetic_video),
        frame_interval=2,
        output_dir=str(temp_dir),
    )
    expected_timestamps = [i * 2 for i in range(len(extracted))]
    actual = [int(p.stem) for p in extracted]
    assert actual == expected_timestamps
    assert all(ts % 2 == 0 for ts in actual)


def test_extract_creates_output_directory(temp_dir: Path, synthetic_video: Path) -> None:
    frames_subdir = temp_dir / "frames"
    run(
        video_path=str(synthetic_video),
        frame_interval=3,
        output_dir=str(temp_dir),
    )
    assert frames_subdir.is_dir()


def test_extract_different_intervals(temp_dir: Path, synthetic_video: Path) -> None:
    interval_2 = run(
        video_path=str(synthetic_video),
        frame_interval=2,
        output_dir=str(temp_dir / "interval2"),
    )
    interval_5 = run(
        video_path=str(synthetic_video),
        frame_interval=5,
        output_dir=str(temp_dir / "interval5"),
    )
    assert len(interval_2) >= len(interval_5)


def test_extract_uses_correct_ffmpeg_params(temp_dir: Path, synthetic_video: Path) -> None:
    probe_result = {
        "streams": [
            {"codec_type": "video", "duration": "10.0"},
        ],
        "format": {"duration": "10.0"},
    }
    with mock.patch("autovideo.extract.ffmpeg.probe", return_value=probe_result), \
         mock.patch("autovideo.extract.ffmpeg.input") as mock_input:
        mock_chain = mock.MagicMock()
        mock_input.return_value = mock_chain

        run(
            video_path=str(synthetic_video),
            frame_interval=3,
            output_dir=str(temp_dir),
        )

        mock_input.assert_called_once()


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path
