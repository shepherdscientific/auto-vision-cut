# AutoVisionCut

An automated, local Vision-to-Script-to-Cut pipeline designed to transform hours of raw, disjointed OBS hardware prototyping footage into clean, narrative-driven videos.

Optimized for Apple Silicon (M4 Pro unified memory architecture), AutoVisionCut runs entirely locally—keeping your hardware IP private and avoiding massive cloud bandwidth overhead.

---

## How It Works

AutoVisionCut bypasses traditional timeline editing by treating video assembly as a code execution problem driven by local multimodal intelligence.

```
[Raw OBS Video] ──> (FFmpeg Frame Extraction) ──> [Image Sequences]
                                                         │
[Project Docs]  ──> (Local VLM via MLX Analysis)  <─────┘
      │                  │
      v                  v
[Qwen3 Coder] ──> [Chronological Event Log (JSON)]
      │
      v
[Script + Keep Timestamps (JSON)] ──> (MoviePy Engine) ──> [Final Rendered Video]
```

1. **Extraction:** `ffmpeg` slices raw OBS recordings down to periodic reference frames (every 2–5 seconds).
2. **Perception:** A local Vision-Language Model (VLM) analyzes the frames to build a dense, timestamped narrative ledger of actions (e.g., soldering, part placement, dead time).
3. **Reasoning:** Your local LLM filters out dead air, synthesizes the log against your project reference documentation, and generates a structured voiceover script alongside a definitive cut list.
4. **Execution:** `MoviePy` consumes the cut list, slices the original high-resolution OBS file, and joins the active clips into a coherent assembly.

---

## Hardware & Environment Requirements

- **Host Machine:** Apple Silicon M4 Pro (or equivalent) with Unified Memory (64GB recommended to run VLM and LLM context side-by-side).
- **Dependencies:**
  - Python 3.10+
  - `ffmpeg` (installed via Homebrew and exposed to system PATH)
  - `mlx` / `mlx-vlm` for accelerated local inference
  - `MoviePy` for video compilation

---

## Installation

```bash
# Clone the repository
git clone https://github.com/shepherdscientific/auto-vision-cut.git
cd auto-vision-cut

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install core dependencies
pip install -r requirements.txt

# Ensure ffmpeg is accessible
brew install ffmpeg

# Download the local models into ~/.cache/mlx-models/
mlx_vlm.download --model qwen2.5-vl-7b
mlx_lm.download --model qwen3.8b
```

The VLM model (`qwen2.5-vl-7b`) analyzes screenshots frame-by-frame. The LLM model (`qwen3.8b`) generates cut-lists and voiceover scripts. Models live under `~/.cache/mlx-models/` and are auto-resolved at runtime.

---

## Configuration & Usage

### CLI Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--video` | path(s) | *required* | Video file, directory of videos, or multiple files via glob |
| `--context` | path(s) | none | Markdown files with project specs for context-aware editing |
| `--output-dir` | path | `output` | Directory for pipeline output |
| `--output-mode` | `single\|separate` | `separate` | One merged output or per-video output dirs |
| `--frame-interval` | int | `3` | Seconds between extracted frames (2–5) |
| `--config` | path | none | YAML/JSON config file (alternative to flags) |

### Basic Usage

```bash
# Process a single video
python main.py --video ./assets/raw_footage.mp4

# Process all videos in a directory with project context
python main.py --video ~/Desktop/VideoChannel/wallettest/ --context ~/Desktop/VideoChannel/wallettest/README.md

# Process specific files via shell glob
python main.py --video ~/Desktop/VideoChannel/wallettest/*.mp4 --context ./specs.md

# Custom frame interval and output directory
python main.py --video ./assets/ --frame-interval 4 --output-dir ./edited

# Merge all input videos into a single output
python main.py --video ./raw/ --output-mode single
```

### YAML Configuration

Instead of CLI flags, use a config file:

```yaml
# config.yaml
frame_interval: 4
vlm_model_path: qwen2.5-vl-7b
llm_model_path: qwen3.8b
context_paths:
  - ./assets/project_spec.md
output_mode: separate
```

```bash
python main.py --video ./assets/ --config config.yaml
```

---

## Pipeline Output

After a successful run, each video produces output under `output/<video_name>/` (separate mode) or `output/` (single mode):

| File | Description |
|---|---|
| `vision_log.json` | VLM's chronological event ledger (timestamp, active flag, description per frame) |
| `cut_list.json` | Kept timestamp ranges (`{start, end}`) and generated voiceover script |
| `output_master.mp4` | Final rendered and trimmed video |
| `pipeline.log` | Structured log of the entire pipeline run |

---

## Pipeline Stages

The pipeline runs five stages in sequence. Each stage can be resumed independently if its output artifact already exists.

1. **Extract** (`extract.py`) — Pulls frames at the configured interval using ffmpeg. Returns empty list on failure instead of aborting.
2. **Analyze** (`analyze.py`) — Feeds frames to a local VLM. Generates `vision_log.json` with per-frame activity judgments. Retries inference up to 3 times with exponential backoff.
3. **Generate** (`generate.py`) — Produces `cut_list.json` from the vision log. Filters inactive frames, merges adjacent active segments, drafts voiceover script. Falls back to deterministic mode when LLM is unavailable.
4. **Assemble** (`assemble.py`) — Slices and concatenates the original video using the cut list with MoviePy. Cleans up temp files on success.
5. **Validate** (`validate.py`) — Verifies output exists, has non-zero duration, and segment count matches the cut list.

---

## Error Recovery

- **Retry logic:** VLM and LLM inference calls retry up to 3 times with exponential backoff (1s → 2s → 4s).
- **ffmpeg failures:** Logged and skipped; the pipeline returns an empty frame list rather than aborting.
- **Resume support:** If `vision_log.json`, `cut_list.json`, or `output_master.mp4` already exist in the output directory, the corresponding stages are skipped on re-run.

---

## Development

```bash
# Type check
mypy .

# Lint
ruff check .

# Run tests (unit only, no VLM/LLM required)
pytest -m "not slow and not integration"

# Run full test suite (includes integration tests with synthetic video)
pytest
```

Project follows the Mr. Wiggum (Ralph) autonomous loop structure. See `prd.json` for the full story backlog and `scripts/ralph/AGENTS.md` for development patterns.
