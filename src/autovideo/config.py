"""Unified configuration module for the AutoVisionCut pipeline."""

import argparse
import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

MLX_MODELS_DIR = os.path.expanduser("~/.cache/mlx-models")


def _resolve_model_path(name: str) -> str:
    resolved = os.path.join(MLX_MODELS_DIR, name)
    if os.path.isdir(resolved):
        return resolved
    return name


@dataclass
class Config:
    frame_interval: int = 3
    vlm_model_path: str = "qwen2.5-vl-7b"
    llm_model_path: str = "qwen3.8b"
    input_dir: str = "assets"
    output_dir: str = "output"
    temp_dir: str = "output/temp"
    video_path: str | None = None
    video_paths: list[str] = field(default_factory=list)
    config_path: str | None = None
    context_paths: list[str] = field(default_factory=list)
    output_mode: str = "separate"

    criteria_path: str = "criteria/default.md"
    aggressiveness: str = "medium"
    filler_sensitivity: str = "medium"
    always_keep: list[str] = field(default_factory=list)
    always_cut: list[str] = field(default_factory=list)
    approval_required: bool = True
    induce_from_path: str | None = None
    criteria_channel: str = "default"
    induce_force: bool = False
    vision_enabled: bool = False

    whisper_model: str = "mlx-community/whisper-tiny"
    pause_threshold: float = 0.7
    similarity_threshold: float = 0.75
    classify_max_tokens: int = 4096
    classify_chunk_size: int = 6000
    induce_max_tokens: int = 4096
    llm_provider: str = "mlx_lm"

    _defaults: dict[str, Any] = field(default_factory=dict, repr=False, init=False)

    def __post_init__(self) -> None:
        self._defaults = {
            "frame_interval": 3,
            "vlm_model_path": "qwen2.5-vl-7b",
            "llm_model_path": "qwen3.8b",
            "input_dir": "assets",
            "output_dir": "output",
            "temp_dir": "output/temp",
            "video_path": None,
            "video_paths": [],
            "config_path": None,
            "context_paths": [],
            "output_mode": "separate",
            "criteria_path": "criteria/default.md",
            "aggressiveness": "medium",
            "filler_sensitivity": "medium",
            "always_keep": [],
            "always_cut": [],
            "approval_required": True,
            "induce_from_path": None,
            "criteria_channel": "default",
            "induce_force": False,
            "vision_enabled": False,
            "whisper_model": "mlx-community/whisper-tiny",
            "pause_threshold": 0.7,
            "similarity_threshold": 0.75,
            "classify_max_tokens": 4096,
            "classify_chunk_size": 6000,
            "induce_max_tokens": 4096,
            "llm_provider": "mlx_lm",
        }

    def resolve_vlm_path(self) -> str:
        return _resolve_model_path(self.vlm_model_path)

    def resolve_llm_path(self) -> str:
        return _resolve_model_path(self.llm_model_path)

    def resolve_whisper_path(self) -> str:
        return _resolve_model_path(self.whisper_model)

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
            raise ValueError(
                f"Unsupported config format: {p.suffix}. "
                "Use .yaml, .yml, or .json for config files. "
                "For markdown context files, use --context instead."
            )

    @classmethod
    def from_args(cls, argv: list[str] | None = None) -> "Config":
        parser = argparse.ArgumentParser(
            description="AutoVisionCut — Local Vision-to-Script-to-Cut pipeline"
        )
        parser.add_argument(
            "--video",
            type=str,
            nargs="+",
            default=None,
            help="Path to input OBS video file(s) or a directory containing .mp4/.mkv files",
        )
        parser.add_argument(
            "--config",
            type=str,
            default=None,
            help="Path to YAML/JSON configuration file",
        )
        parser.add_argument(
            "--context",
            type=str,
            nargs="*",
            default=None,
            help="Path(s) to markdown context files for the LLM/VLM",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Directory for pipeline output files",
        )
        parser.add_argument(
            "--output-mode",
            type=str,
            default=None,
            choices=["single", "separate"],
            help="Output mode: 'single' (one merged output) or 'separate' (per-video)",
        )
        parser.add_argument(
            "--frame-interval",
            type=int,
            default=None,
            help="Seconds between extracted frames (2-5 recommended)",
        )
        parser.add_argument(
            "--no-approval",
            action="store_true",
            default=None,
            help="Skip the human review gate and proceed directly to assembly",
        )
        parser.add_argument(
            "--induce-from",
            type=str,
            default=None,
            help="Prior run output dir (or transcript.json) to auto-generate criteria",
        )
        parser.add_argument(
            "--criteria-channel",
            type=str,
            default=None,
            help="Channel name for induced criteria file (criteria/<channel>.md)",
        )
        parser.add_argument(
            "--induce-force",
            action="store_true",
            default=None,
            help="Regenerate criteria even if the file already exists",
        )
        parser.add_argument(
            "--enable-vision",
            action="store_true",
            default=None,
            help="Enable optional VLM vision analysis as secondary signal for low-speech segments",
        )
        parser.add_argument(
            "--whisper-model",
            type=str,
            default=None,
            help="Whisper model name or path for transcription",
        )
        parser.add_argument(
            "--pause-threshold",
            type=float,
            default=None,
            help="Silence gap threshold in seconds for segment boundary detection",
        )
        parser.add_argument(
            "--similarity-threshold",
            type=float,
            default=None,
            help="Text similarity threshold (0.0-1.0) for retake detection",
        )
        parser.add_argument(
            "--classify-max-tokens",
            type=int,
            default=None,
            help="Max tokens for LLM classifier output",
        )
        parser.add_argument(
            "--classify-chunk-size",
            type=int,
            default=None,
            help="Max characters per chunk when classifying long transcripts",
        )
        parser.add_argument(
            "--induce-max-tokens",
            type=int,
            default=None,
            help="Max tokens for criteria induction LLM output",
        )
        parser.add_argument(
            "--aggressiveness",
            type=str,
            default=None,
            choices=["light", "medium", "heavy"],
            help="Editorial aggressiveness for cut/keep decisions",
        )
        parser.add_argument(
            "--filler-sensitivity",
            type=str,
            default=None,
            choices=["low", "medium", "high"],
            help="Sensitivity for filler word detection",
        )
        parser.add_argument(
            "--always-keep",
            type=str,
            nargs="*",
            default=None,
            help="Text patterns to always keep",
        )
        parser.add_argument(
            "--always-cut",
            type=str,
            nargs="*",
            default=None,
            help="Text patterns to always cut",
        )
        parser.add_argument(
            "--llm-provider",
            type=str,
            default=None,
            help="LLM backend (mlx_lm or openai-compatible)",
        )
        args = parser.parse_args(argv)

        config = cls()
        if args.config:
            config = cls.from_file(args.config)
            config.config_path = args.config

        overrides: dict[str, Any] = {}
        if args.video is not None:
            if len(args.video) == 1:
                overrides["video_path"] = args.video[0]
            else:
                overrides["video_paths"] = list(args.video)
        if args.context is not None:
            overrides["context_paths"] = list(args.context)
        if args.output_dir is not None:
            config.output_dir = args.output_dir
        if args.output_mode is not None:
            config.output_mode = args.output_mode
        if args.frame_interval is not None:
            config.frame_interval = args.frame_interval
        if args.no_approval is True:
            config.approval_required = False
        if args.induce_from is not None:
            config.induce_from_path = args.induce_from
        if args.criteria_channel is not None:
            config.criteria_channel = args.criteria_channel
        if args.induce_force is True:
            config.induce_force = True
        if args.enable_vision is True:
            config.vision_enabled = True
        if args.whisper_model is not None:
            config.whisper_model = args.whisper_model
        if args.pause_threshold is not None:
            config.pause_threshold = args.pause_threshold
        if args.similarity_threshold is not None:
            config.similarity_threshold = args.similarity_threshold
        if args.classify_max_tokens is not None:
            config.classify_max_tokens = args.classify_max_tokens
        if args.classify_chunk_size is not None:
            config.classify_chunk_size = args.classify_chunk_size
        if args.induce_max_tokens is not None:
            config.induce_max_tokens = args.induce_max_tokens
        if args.aggressiveness is not None:
            config.aggressiveness = args.aggressiveness
        if args.filler_sensitivity is not None:
            config.filler_sensitivity = args.filler_sensitivity
        if args.always_keep is not None:
            config.always_keep = list(args.always_keep)
        if args.always_cut is not None:
            config.always_cut = list(args.always_cut)
        if args.llm_provider is not None:
            config.llm_provider = args.llm_provider

        if overrides:
            config = cls.from_dict({**config.__dict__, **overrides})

        return config

    def resolve_path(self, relative: str) -> Path:
        return Path(relative).resolve()

    def is_video_directory(self) -> bool:
        if self.video_path is None:
            return False
        p = os.path.expanduser(self.video_path)
        return os.path.isdir(p)

    def resolve_video_paths(self) -> list[Path]:
        if self.video_paths:
            results: list[Path] = []
            for p in self.video_paths:
                expanded = Path(os.path.expanduser(p)).resolve()
                if expanded.is_file():
                    results.append(expanded)
            return results

        if self.video_path is None:
            return []
        p = os.path.expanduser(self.video_path)
        expanded = Path(p).resolve()
        if expanded.is_dir():
            videos = sorted(
                f for f in expanded.iterdir()
                if f.suffix.lower() in (".mp4", ".mkv", ".mov", ".avi")
            )
            return videos
        elif expanded.is_file():
            return [expanded]
        else:
            return [expanded]

    def resolve_context_paths(self) -> list[Path]:
        result: list[Path] = []
        for p in self.context_paths:
            expanded = Path(os.path.expanduser(p))
            if expanded.is_file():
                result.append(expanded)
        return result

    def read_context_docs(self) -> str:
        parts: list[str] = []
        for p in self.resolve_context_paths():
            try:
                content = p.read_text(encoding="utf-8")
                parts.append(f"=== {p.name} ===\n{content}")
            except Exception:
                pass
        return "\n\n".join(parts)

    def resolve_criteria_path(self) -> Path:
        return Path(self.criteria_path).resolve()

    def read_criteria(self) -> str:
        path = self.resolve_criteria_path()
        if not path.is_file():
            raise FileNotFoundError(f"Criteria file not found: {path}")
        raw = path.read_text(encoding="utf-8")
        raw = raw.replace("{{AGGRESSIVENESS}}", self.aggressiveness)
        raw = raw.replace("{{FILLER_SENSITIVITY}}", self.filler_sensitivity)
        raw = raw.replace("{{ALWAYS_KEEP}}", json.dumps(self.always_keep))
        raw = raw.replace("{{ALWAYS_CUT}}", json.dumps(self.always_cut))
        return raw
