# AutoVisionCut

An automated, local Vision-to-Script-to-Cut pipeline designed to transform hours of raw, disjointed OBS hardware prototyping footage into clean, narrative-driven videos.

Optimized for Apple Silicon (M4 Pro unified memory architecture), AutoVisionCut runs entirely locally—keeping your hardware IP private and avoiding massive cloud bandwidth overhead.

---

## How It Works

AutoVisionCut bypasses traditional timeline editing by treating video assembly as a code execution problem driven by local multimodal intelligence.

```
[Raw OBS Video] ──> (FFmpeg Frame Extraction) ──> [Image Sequences]
                                                         │
[Project Docs]  ──> (Local VLM via MLX Analysis)  <──────┘
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

* **Host Machine:** Apple Silicon M4 Pro (or equivalent) with Unified Memory (64GB recommended to run VLM and LLM context side-by-side).
* **Dependencies:**
* Python 3.10+
* `ffmpeg` (installed via Homebrew and exposed to system PATH)
* `mlx` / `mlx-vlm` for accelerated local inference
* `MoviePy` for video compilation



---

## Installation

```bash
# Clone the repository
git clone https://github.com/shepherdscientific/auto-vision-cut.git
cd auto-vision-cut

# Install core dependencies
pip install -r requirements.txt

# Ensure ffmpeg is accessible
brew install ffmpeg

```

---

## Configuration & Usage

The system operations are governed by a standard configuration or a target `prd.json` file compatible with the **Mr. Wiggum (Ralph)** autonomous loop structure.

### 1. Drop Your Assets

Place your raw OBS files (e.g., `.mp4`, `.mkv`) and any project reference markdown files in the source directory:

```
/assets
  ├── raw_footage.mp4
  └── firmware_spec.md

```

### 2. Execute the Pipeline

Run the master orchestration script to start frame extraction, VLM evaluation, script generation, and slicing:

```bash
python main.py --video ./assets/raw_footage.mp4 --context ./assets/firmware_spec.md

```

### 3. Review the Artifacts

The system spits out a localized directory containing:

* **`event_log.json`**: The VLM's chronological ledger of what happened.
* **`narration_script.md`**: A generated voiceover script mapped perfectly to your timeline.
* **`cut_list.json`**: The precise timestamp bounds kept for the final render.
* **`output_master.mp4`**: Your condensed, edited video.

---
