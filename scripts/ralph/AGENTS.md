# AutoVisionCut — Agent Notes (Lean Mode)

**Project:** AutoVisionCut — a local, privacy-preserving pipeline that turns raw
footage into an edited video. Current spine: ffmpeg frame extract → MLX VLM
per-frame analysis → cut-list generation → MoviePy assemble → validate.

**Redesign in flight (this branch — `prd.json` US-100…US-111):** pivot the
cut/keep decisioning from frame-vision to **transcript-first** — local Whisper
transcript → utterance segments → LLM keep/cut classifier driven by an explicit,
editable base cut/keep prompt (optionally auto-generated from a prior run's
transcript) → **human review gate** → ffmpeg render. Vision becomes an optional
secondary signal. See `docs/autovideo-redesign.md` for the full rationale.

**Stack:** Python 3.10+, MLX (mlx-vlm / mlx-lm / mlx-whisper) for local
Apple-Silicon inference, ffmpeg + MoviePy for media. The loop routes coding to
DeepSeek and the review gate to Kimi K2.6 via OpenRouter (see `opencode.json`
and `.env.deepseek-kimi.example`).

## Environment
- Virtualenv: `source .venv/bin/activate` (a `venv/` also exists).
- Typecheck: `mypy .` · Lint: `ruff check .` · Test: `pytest` (markers: `slow`, `integration`).

## Iteration Rules
1. Read `prd.json` (root) and this file.
2. Check `git log -n 10`.
3. Implement ONE story (priority order), with tests.
4. Run the quality gate + `./scripts/ralph/aider-review.sh`.
5. Update `progress.txt` (human audit) and `prd.json` (state) — see the jq rule below.
6. If tests fail and you cannot fix: document the blocker here and EXIT (no commit).

## ⚠️ Updating prd.json Safely
NEVER hand-edit prd.json or use sed/awk (creates duplicate keys). Use jq:
```bash
jq '(.userStories[] | select(.id=="US-XXX") | .passes)=true' prd.json > /tmp/prd.json && mv /tmp/prd.json prd.json
```
Validate with `./scripts/ralph/validate-prd.sh`; repair with `./scripts/ralph/fix-prd-duplicates.sh`.

## Aider Review (Mandatory Gate)
Run `./scripts/ralph/aider-review.sh` AFTER implementation, BEFORE updating prd.json.
Apply all critical fixes. If the reviewer surfaces a reusable pattern, append it below.

## Discovered Patterns (the "brain")
- **Frame-interval-aware segment merging:** in `generate._merge_adjacent_segments`, use `gap_threshold = max(5, frame_interval * 2)` so sampling gaps bridge but genuine inactivity does not.
- **Validate before assembly:** validate the cut list against video metadata (`validate.run()`) before rendering; abort early on a malformed / out-of-range cut list instead of producing a broken output.
- **Parse model JSON defensively:** VLM/LLM outputs often wrap JSON in ```` ```json ```` fences or emit several objects; strip fences and parse robustly. Do NOT default a parse failure to `active: true` / keep-everything — that silently keeps the whole video (the exact bug the transcript-first redesign fixes).
