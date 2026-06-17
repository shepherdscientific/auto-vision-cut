# AutoVisionCut — Opinion & Cursory Redesign (for consideration)

*Spec/opinions only — nothing here is built. Centered on the cut/keep decisioning gap you named.*

---

## 1. What's actually built

A clean, well-engineered five-stage Python pipeline driven by the ralph/opencode loop:

```
[raw OBS video] → extract (ffmpeg frames every N s)
               → analyze (local VLM per frame → vision_log.json: active flag + description)
               → generate (filter inactive → merge segments → cut_list.json + voiceover)
               → assemble (MoviePy slice + concat → output_master.mp4)
               → validate (exists / non-zero duration / segment count)
```

The **engineering scaffolding is genuinely solid**: `Config` dataclass with CLI+YAML/JSON, structured logging, retry-with-backoff, resume-by-artifact, 122 passing tests, mypy + ruff clean, an aider review gate, and a `prd.json`/`progress.txt` ralph backlog. As *plumbing*, US-000…US-010 are done and the code is tidy.

The stack you can reuse as-is: ralph loop (`scripts/ralph/ralph.sh`, `prompt.md`) with local↔remote failover, opencode provider blocks for **deepseek v4 / kimi k2.5 / local llama-server**, MLX for on-device inference on the M4 Pro, ffmpeg + MoviePy for render.

---

## 2. The honest opinion — where it wasn't spec'd properly

The decisioning core — the part that decides what to cut — is **hollow, and in practice a no-op.** Three compounding problems:

**(a) It's measuring the wrong thing.** The whole spine reasons over *screenshot pixels*: a VLM looks at a frame and judges "is a tool being used / is this idle." But your goal is editing YouTube videos, where the editorial signal lives in **what is said** — the speech. There is **no transcript anywhere** in the repo (grep confirms zero whisper/speech/ASR code; the only hit for "transcript" is one word inside a prompt string). A vision-first editor is solving a different problem (silent prototyping b-roll) than the one you have (talking videos).

**(b) The editor is a no-op on every real run.** The VLM returns markdown-fenced JSON (` ```json … ``` `), sometimes several blocks concatenated per frame. `analyze.py` does `json.loads(raw_text)`, which fails on the fences, so the `except` branch stuffs the raw markdown into `description` and **defaults `active: True`**. Then `generate.py` keeps everything `active`, and `_events_to_segments` merges it into one continuous block. The result, in all five of your saved runs:

| run | keep ranges |
|---|---|
| 20260528_182604 | `0 → 153` (whole clip) |
| 20260529_194153 | `0 → 132` (whole clip) |
| 20260529_194506 | `0 → 12` (whole clip) |
| 20260529_194552 | `0 → 360` (whole clip) |
| printserver | `0 → 108` (whole clip) |

Every run kept the entire video as a single segment. The "cut list" cut nothing. The `voiceover` field is ~19 KB of concatenated raw VLM markdown.

**(c) There is no editorial criteria actually driving anything, and no human gate.** The one editorial prompt (`DEFAULT_LLM_PROMPT` in `generate.py`) is prototyping-flavored ("productive work vs idle, tool use") — *and it never runs*, because `main.py` hardcodes `use_llm=False`. So there is nowhere to say "cut filler, keep the punchline," nothing that derives those rules from your footage, and no point at which you approve the cuts before rendering.

That is exactly the gap you described: **there's no base cut/keep prompt that actually decides, and nothing that generates the criteria from a transcript.** The 122 tests prove the pipes connect; none of them test whether a single cut decision is *correct* — which is the part that's broken.

---

## 3. Cursory redesign — pivot to transcript-first decisioning

Re-center the spine on the transcript. Keep vision as an *optional secondary* signal, not the driver.

### Clean pipeline shape

```
raw video
  └─ extract audio (ffmpeg)
       └─ TRANSCRIBE (local whisper: mlx-whisper / faster-whisper)
            → transcript.json   (word + segment timestamps)   ← the new "text extraction"
       └─ SEGMENT into utterances (sentence/pause-bounded)
            → segments.json      ({id,start,end,text})
       └─ CLASSIFY  (LLM + cut/keep criteria prompt)           ← the decisioning core
            → cut_list.json      (per-segment keep|cut + reason + confidence)
       └─ REVIEW (human-in-the-loop)                           ← approval gate (new)
            → review.md / editable cut_list / EDL  →  YOU APPROVE
       └─ RENDER (ffmpeg concat from approved keeps)
            → output_master.mp4
       └─ VALIDATE

criteria source:  default base prompt   OR   auto-induced from a prior transcript
optional:         VLM vision pass for low-speech segments, merged as secondary signal
```

Three changes do the real work: **(1)** transcript replaces frames as the primary signal; **(2)** an explicit, editable criteria prompt drives an LLM classifier that labels each utterance; **(3)** a human approval gate sits between the proposed cut list and the render.

### (a) A concrete base cut/keep prompt (the default editorial spec)

Ship this as an editable, version-controlled file (`criteria/default.md`). It is the thing that's missing today:

```text
ROLE
You are a video editor for a YouTube channel. Working from a timestamped
transcript of raw footage, decide segment by segment what to KEEP and what to
CUT. Edit for a tight, watchable final cut while preserving the creator's
voice and all substantive content.

INPUT
A JSON array of segments in chronological order: {id, start, end, text}.
Some lines repeat because the creator did multiple takes.

CUT
- Filler and verbal tics: "um", "uh", "like", "you know", throat-clearing.
- Dead air / long pauses with no speech.
- False starts and self-corrections ("wait, let me start over").
- Retakes: when a line is delivered more than once, cut all but the cleanest,
  most complete take (prefer the LAST clean take unless an earlier one is better).
- Off-topic tangents and rambling that don't advance the point.
- Production interruptions ("hang on", "is this recording?", "let me fix the mic").
- Redundant restatements of a point already made clearly.

KEEP
- Substantive explanations, instructions, the core content.
- The single clean final take of any repeated line.
- Hooks, intros, direct address, calls to action.
- Punchlines, payoffs, intentional emphasis.
- Concise transitions that preserve flow.
- Demos / walkthroughs with meaningful narration.

RULES
- Never cut mid-sentence; operate on whole segments / complete thoughts.
- When unsure, KEEP and lower confidence — the human reviews before render.
- Preserve chronological order; never reorder.
- Be consistent: identical filler gets identical treatment.

TUNABLES (override defaults at runtime)
- aggressiveness: light | medium | heavy        (default medium)
- filler_sensitivity: low | medium | high        (default medium)
- always_keep: [...]      always_cut: [...]

OUTPUT (JSON only)
{ "decisions": [
    { "id": <int>, "decision": "keep" | "cut",
      "reason": "<short why>", "confidence": 0.0-1.0,
      "tag": "filler|dead_air|false_start|retake|tangent|interruption|redundant|content|hook|cta|punchline|transition|demo" }
] }
```

### (b) Auto-generating the criteria from a prior run's transcript

Cold start uses the default above. The better mode **derives the criteria from a previous video**, so the editor matches your style. A second LLM pass — "criteria induction" — reads a prior `transcript.json` (and, if available, the cut list you approved for it) and writes a specialized, *editable* criteria file:

```text
ROLE
You are configuring an automatic editor for one specific creator. From a PRIOR
transcript (and optionally the human-approved cut list for it), infer the
creator's editorial style and emit a REUSABLE, EDITABLE criteria prompt.

DERIVE
- Topic/domain and typical structure (hook → body → CTA/outro).
- The creator's ACTUAL recurring filler words and verbal tics (list them).
- Pacing / how aggressively they tend to cut.
- Content they reliably keep vs. cut (from the approved cut list if present).
- Signature/recurring segments (bits, sign-offs).

OUTPUT
A criteria prompt in the same shape as the base spec, specialized to this
creator: concrete always_keep / always_cut lists, the real filler words,
a recommended aggressiveness, and 2–4 few-shot examples pulled from the prior
transcript (segment text → keep/cut + reason). Written as Markdown so the
human can edit it before it is used.
```

The induced file (`criteria/<channel>.md`) becomes the active prompt for future runs. You edit it once; it's reused and versioned. And because the **human review (below) persists your overrides**, each approved edit becomes labeled data that sharpens the next induction — a taste feedback loop.

### (c) The human-in-the-loop review point

This is the safeguard the current design lacks (it renders straight through). After the classifier, before any render:

1. Emit `review.md` (and an editable `cut_list.json` / standard EDL) — every segment with its timestamp, text, decision, reason, confidence, and a running "time saved" tally.
2. **You approve / flip decisions.** Render consumes *only* the approved cut list; without approval the run stops at review.
3. Your overrides are persisted and fed back to criteria induction (US-108).

### Reuse from your existing stack

Nothing here throws away the scaffolding. Keep the **ralph/opencode loop, `prd.json`, `progress.txt`** — the redesign is just new stories. The **LLM classifier + criteria induction** run on **deepseek v4 / kimi k2.5 via openrouter, or the local llama-server** (the failover already exists in `ralph.sh`). **Transcription** stays local on the M4 Pro (mlx-whisper), matching the "runs entirely locally / IP private" ethos. **Render** moves to ffmpeg concat (faster, frame-accurate) with MoviePy as fallback. The **VLM** survives as an optional secondary signal for low-speech stretches — and that path needs the JSON-fence parsing bug fixed regardless.

---

## 4. Draft prd.json stories (passes:false — for consideration)

Full backlog in `prd.json` (matches your ralph schema; `branchName: ralph/redesign`; every story `passes:false`, notes marked DRAFT). Summary:

| ID | Story | Why |
|---|---|---|
| US-100 | Audio extraction + local transcription → timestamped transcript | the missing "text extraction" |
| US-101 | Segment transcript into utterance units | decisions operate on whole thoughts |
| US-102 | **Base cut/keep criteria prompt (editable default)** | the missing editorial spec |
| US-103 | **LLM segment classifier** (keep/cut + reason + confidence) | the decisioning core; fixes the no-op |
| US-104 | Retake / false-start dedup (keep best take) | core to talking-video editing |
| US-105 | **Human-in-the-loop review gate** (approve before render) | the missing safeguard |
| US-106 | Frame-accurate render from approved cut list (ffmpeg concat) | reuses assemble/validate |
| US-107 | **Auto-generate criteria from a prior transcript** | "generate the prompt itself" |
| US-108 | Learn criteria from approved cut lists (taste loop) | overrides sharpen next run |
| US-109 | Optional vision/B-roll secondary signal | salvages analyze.py; fixes fence bug |
| US-110 | Config + model routing (deepseek/kimi/local) + tunables | wiring |
| US-111 | Cut-decision eval harness (precision/recall vs reference edit) | tests *quality*, not just plumbing |

---

## 5. Bottom line

The pipeline is well-built around an empty center. The fix isn't more engineering — it's **changing the signal and adding judgment**: edit from the transcript, drive it with an explicit base cut/keep prompt (optionally auto-derived from a prior video's transcript), and put a human approval gate before the render. Start with US-100 → US-103 → US-105; that alone turns "keeps the whole video" into a real first cut you can approve.
