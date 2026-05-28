"""Unified configuration module for the AutoVisionCut pipeline."""

import argparse
import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Config:
    frame_interval: int = 3
    vlm_model_path: str = "qwen-vl"
    llm_model_path: str = "qwen3"
    input_dir: str = "assets"
    output_dir: str = "output"
    temp_dir: str = "output/temp"
    video_path: str | None = None
    config_path: str | None = None

    _defaults: dict[str, Any] = field(default_factory=dict, repr=False, init=False)

    def __post_init__(self) -> None:
        self._defaults = {
            "frame_interval": 3,
            "vlm_model_path": "qwen-vl",
            "llm_model_path": "qwen3",
            "input_dir": "assets",
            "output_dir": "output",
            "temp_dir": "output/temp",
            "video_path": None,
            "config_path": None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        field_names = {f.name for f in fields(cls) if f.init}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_json(cls, path: str) -> "Config":
        with open(path, "r") as f:
            data = json.load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_file(cls, path: str) -> "Config":
        p = Path(path)
        if p.suffix in (".yaml", ".yml"):
            return cls.from_yaml(path)
        elif p.suffix == ".json":
            return cls.from_json(path)
        else:
            raise ValueError(f"Unsupported config format: {p.suffix}. Use .yaml, .yml, or .json")

    @classmethod
    def from_args(cls, argv: list[str] | None = None) -> "Config":
        parser = argparse.ArgumentParser(
            description="AutoVisionCut — Local Vision-to-Script-to-Cut pipeline"
        )
        parser.add_argument(
            "--video",
            type=str,
            default=None,
            help="Path to the input OBS video file",
        )
        parser.add_argument(
            "--config",
            type=str,
            default=None,
            help="Path to YAML/JSON configuration file",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Directory for pipeline output files",
        )
        parser.add_argument(
            "--frame-interval",
            type=int,
            default=None,
            help="Seconds between extracted frames (2-5 recommended)",
        )
        args = parser.parse_args(argv)

        config = cls()
        if args.config:
            config = cls.from_file(args.config)
            config.config_path = args.config

        overrides: dict[str, Any] = {}
        if args.video is not None:
            overrides["video_path"] = args.video
        if args.output_dir is not None:
            config.output_dir = args.output_dir
        if args.frame_interval is not None:
            config.frame_interval = args.frame_interval

        if overrides:
            config = cls.from_dict({**config.__dict__, **overrides})

        return config

    def resolve_path(self, relative: str) -> Path:
        return Path(relative).resolve()
