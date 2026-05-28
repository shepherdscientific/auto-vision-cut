"""Shared test fixtures for the AutoVisionCut pipeline."""

import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a 10-second synthetic test video with video and audio tracks."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin is None:
        pytest.skip("ffmpeg binary not found on PATH")

    import subprocess

    output_path = tmp_path_factory.mktemp("fixtures") / "synthetic_test.mp4"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi", "-i", "testsrc=duration=10:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path
