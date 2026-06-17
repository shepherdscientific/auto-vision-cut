"""Criteria induction module for the AutoVisionCut pipeline.

Derives a personalized cut/keep criteria prompt from a prior transcript
and optional approved cut list, using an LLM 'induction' pass.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from autovideo.config import Config
from autovideo.logging_setup import get_module_logger


class InduceError(Exception):
    """Raised on unrecoverable induction failures."""

logger = get_module_logger(__name__)

INDUCE_DELAY = 1.0
INDUCE_BACKOFF = 2.0
INDUCE_MAX_RETRIES = 3
MAX_TOKENS = 4096

_FENCE_PATTERN = re.compile(
    r"```(?:md|markdown)?\s*\n?(.*?)\n?```", re.DOTALL
)

INDUCTION_SYSTEM_PROMPT = """\
You are an expert video editor analyzing a creator's transcript \
and editorial decisions.
Your task: derive a personalized cut/keep criteria prompt \
that captures the creator's editing style.

Study the transcript segments and (if provided) the approved keep/cut decisions.
Then write a criteria prompt in the same format as the example below.

Output ONLY a single markdown code block containing the criteria file content.
Follow the structure exactly:

```md
# Cut/Keep Criteria — <channel name>

You are a video editor classifying transcript segments of a screen-recording / talking-head video.
For each segment, decide whether it should be **KEPT** in the final edit or **CUT**.

## CUT Rules (remove these)

- <real filler words observed from the transcript, e.g., "um", "uh", "like", "you know">
- <other CUT rules tailored to this creator's actual patterns>
- Dead air: segments consisting only of silence or mouth noises
- False starts: aborted sentences, self-corrections
- Retakes: repeated deliveries of the same idea
- Tangents / off-topic: rambling off the main subject
- Redundancy: repeating the same point already made clearly
- Interruptions: external noise, coughing, someone speaking over the creator

## KEEP Rules (preserve these)

- Substantive explanations: clear, on-topic content that advances the tutorial / narrative
- Best take: the most fluent, complete delivery of a repeated idea
- Hooks: opening statements that set up what the video is about
- CTAs: calls to action
- Punchlines / key insights: memorable takeaways
- Demos / walkthroughs: step-by-step demonstrations
- Concise transitions: brief segues between topics

## JSON Output Contract

You MUST output a single JSON object with EXACTLY this structure:

```json
{
  "decisions": [
    {
      "id": <int>,
      "decision": "keep" | "cut",
      "reason": "<brief rationale matching a rule above>",
      "confidence": <float 0.0-1.0>,
      "tag": "<tag>"
    }
  ],
  "keep": [{"start": <float>, "end": <float>}],
  "stats": {
    "total_kept": <int>,
    "total_cut": <int>,
    "time_saved_seconds": <float>
  }
}
```

## Runtime Tunables (override via config)

- **aggressiveness**: light | medium | heavy
- **filler_sensitivity**: low | medium | high
- **always_keep[]**: list of segment text patterns to always keep
- **always_cut[]**: list of segment text patterns to always cut

## Recommended Tunables

**aggressiveness**: <recommended value>
**filler_sensitivity**: <recommended value>
**always_keep**: <patterns observed to always be kept>
**always_cut**: <patterns observed to always be cut>
"""


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _strip_fences(raw: str) -> str:
    match = _FENCE_PATTERN.search(raw)
    return match.group(1).strip() if match else raw.strip()


def _find_common_fillers(
    transcript_path: str, approved_path: str | None = None
) -> list[str]:
    """Scan transcript for common filler words to personalize the criteria."""
    try:
        data = _load_json(transcript_path)
        segments = data.get("segments", [])
    except Exception:
        return ["um", "uh", "like", "you know"]

    filler_counts: dict[str, int] = {}
    filler_words = [
        "um", "uh", "like", "you know", "sort of", "kind of",
        "actually", "basically", "literally", "so ", "well ",
    ]
    for seg in segments:
        text = (seg.get("text") or "").lower()
        for fw in filler_words:
            if fw in text:
                filler_counts[fw] = filler_counts.get(fw, 0) + text.count(fw)

    if approved_path:
        try:
            approved = _load_json(approved_path)
            cut_ids = {
                d["id"] for d in approved.get("decisions", [])
                if d.get("decision") == "cut"
            }
            cut_filler_counts: dict[str, int] = {}
            for seg in segments:
                if seg.get("id") in cut_ids:
                    text = (seg.get("text") or "").lower()
                    for fw in filler_words:
                        if fw in text:
                            cut_filler_counts[fw] = (
                                cut_filler_counts.get(fw, 0) + text.count(fw)
                            )
            if cut_filler_counts:
                filler_counts = cut_filler_counts
        except Exception:
            pass

    sorted_fillers = sorted(filler_counts.items(), key=lambda x: -x[1])
    return [fw for fw, _ in sorted_fillers[:5]] or ["um", "uh", "like", "you know"]


def _load_overrides(prior_dir: str) -> list[dict[str, str | int | float]] | None:
    """Load user override examples from a prior run's overrides.json."""
    override_path = os.path.join(prior_dir, "overrides.json")
    if not os.path.isfile(override_path):
        return None
    try:
        data = _load_json(override_path)
        if isinstance(data, list) and data:
            logger.info("Loaded %d user override examples from %s", len(data), override_path)
            return data
    except Exception as exc:
        logger.warning("Failed to load overrides from %s: %s", override_path, exc)
    return None


def _build_induction_input(
    transcript_path: str,
    approved_path: str | None = None,
    overrides_path: str | None = None,
) -> str:
    parts: list[str] = []

    try:
        data = _load_json(transcript_path)
        segments = data.get("segments", data)
        if isinstance(segments, dict):
            segments = [segments]
        text_content = "\n".join(
            f"[{s.get('id','?')}] {s.get('start',0):.1f}s-"
            f"{s.get('end',0):.1f}s: {s.get('text','')}"
            for s in segments
        )
        parts.append("## Prior Transcript\n\n" + text_content)
    except Exception as exc:
        raise InduceError(f"Failed to read transcript: {exc}") from exc

    if approved_path:
        try:
            approved = _load_json(approved_path)
            parts.append("\n## Approved Cut/Keep Decisions\n\n")
            for d in approved.get("decisions", []):
                parts.append(
                    f"  Segment {d.get('id')}: {d.get('decision')} "
                    f"(confidence={d.get('confidence')}, reason={d.get('reason')})"
                )
            parts.append(
                f"\nStats: kept={approved.get('stats', {}).get('total_kept')}, "
                f"cut={approved.get('stats', {}).get('total_cut')}, "
                f"time_saved={approved.get('stats', {}).get('time_saved_seconds')}s"
            )
        except Exception as exc:
            logger.warning(
                "Failed to read approved cut list, continuing without: %s", exc
            )

    if overrides_path:
        try:
            overrides = _load_json(overrides_path)
            if isinstance(overrides, list) and overrides:
                parts.append("\n## User Override Examples (learn from these)\n\n")
                parts.append(
                    "The creator manually changed these segments' decisions. "
                    "Treat them as high-signal corrections to the model's judgment:\n\n"
                )
                for o in overrides:
                    oid = o.get("id", "?")
                    otext = o.get("text", "")
                    odec = o.get("decision", "?")
                    oorig = o.get("original_decision", "?")
                    parts.append(
                        f"- Segment {oid}: text=\"{otext}\", "
                        f"original={oorig}, overridden_to={odec}"
                    )
        except Exception as exc:
            logger.warning(
                "Failed to read override examples, continuing without: %s", exc
            )

    return "\n".join(parts)


def _has_mlx_lm() -> bool:
    return "mlx_lm" in sys.modules


def _load_model(model_path: str) -> tuple[Any, Any] | None:
    llm_mod = sys.modules.get("mlx_lm")
    if llm_mod is None:
        try:
            import mlx_lm as _mlx
            llm_mod = _mlx
        except ImportError:
            return None
    if llm_mod is None:
        return None
    try:
        logger.info("Loading induction model: %s", model_path)
        load_result = llm_mod.load(model_path)
        logger.info("Induction model loaded")
        return (load_result[0], load_result[1])
    except Exception as exc:
        logger.warning(
            "Failed to load induction model %s: %s", model_path, exc
        )
        return None


def _call_llm(
    model: Any,
    tokenizer: Any,
    prompt: str,
    max_tokens: int = MAX_TOKENS,
) -> str:
    mlx_lm = sys.modules.get("mlx_lm")
    if mlx_lm is None:
        raise InduceError("mlx_lm not available for LLM call")

    delay = INDUCE_DELAY
    last_exception: Exception | None = None
    for attempt in range(INDUCE_MAX_RETRIES + 1):
        try:
            return mlx_lm.generate(model, tokenizer, prompt, max_tokens=max_tokens)
        except Exception as exc:
            last_exception = exc
            if attempt < INDUCE_MAX_RETRIES:
                logger.warning(
                    "Induction LLM attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1, INDUCE_MAX_RETRIES + 1, exc, delay,
                )
                time.sleep(delay)
                delay *= INDUCE_BACKOFF
    raise InduceError(
        f"LLM generation failed after {INDUCE_MAX_RETRIES + 1} "
        f"attempts: {last_exception}"
    ) from last_exception


def induce_criteria(
    transcript_path: str,
    output_criteria_path: str,
    model_path: str,
    approved_path: str | None = None,
    channel_name: str = "custom",
    overrides_path: str | None = None,
) -> str:
    logger.info(
        "Criteria induction started (transcript=%s, approved=%s, overrides=%s, channel=%s)",
        transcript_path, approved_path or "none", overrides_path or "none", channel_name,
    )
    start_time = time.monotonic()

    filler_words = _find_common_fillers(transcript_path, approved_path)
    induction_input = _build_induction_input(transcript_path, approved_path, overrides_path)
    fillers_text = ", ".join(f'"{fw}"' for fw in filler_words)

    system_with_fillers = INDUCTION_SYSTEM_PROMPT.replace(
        'e.g., "um", "uh", "like", "you know"',
        f"e.g., {fillers_text}",
    )

    prompt = (
        f"{system_with_fillers}\n\n"
        f"Channel name: {channel_name}\n\n"
        f"{induction_input}\n\n"
        "Write the criteria file content now. "
        "Output ONLY a markdown code block containing the complete criteria file."
    )

    model_load = _load_model(model_path)
    if model_load is None:
        raise InduceError(f"Failed to load induction model: {model_path}")

    model, tokenizer = model_load
    raw = _call_llm(model, tokenizer, prompt)
    criteria_content = _strip_fences(raw)

    if not criteria_content:
        raise InduceError("LLM returned empty criteria content")

    output_path = Path(output_criteria_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(criteria_content, encoding="utf-8")

    elapsed = time.monotonic() - start_time
    logger.info(
        "Criteria induced and saved to %s (elapsed=%.1fs)",
        output_criteria_path, elapsed,
    )

    return str(output_path)


def induce_run(
    config: Config,
    transcript_path: str,
    approved_path: str | None = None,
) -> str | None:
    induce_from = config.induce_from_path
    if not induce_from:
        return None

    channel = config.criteria_channel or "default"
    output_criteria_path = os.path.join("criteria", f"{channel}.md")

    if Path(output_criteria_path).is_file() and not config.induce_force:
        logger.info(
            "Criteria file %s already exists — skipping induction "
            "(set induce_force=True to regenerate)", output_criteria_path,
        )
        return output_criteria_path

    if os.path.isdir(induce_from):
        transcript_to_use = os.path.join(induce_from, "transcript.json")
    else:
        transcript_to_use = induce_from

    if approved_path is None and os.path.isdir(induce_from):
        approved_to_use: str | None = os.path.join(
            induce_from, "cut_list.approved.json"
        )
    else:
        approved_to_use = approved_path
    if approved_to_use and not os.path.isfile(approved_to_use):
        approved_to_use = None

    model_path = config.resolve_llm_path()

    overrides_to_use: str | None = None
    if os.path.isdir(induce_from):
        overrides_path = os.path.join(induce_from, "overrides.json")
        if os.path.isfile(overrides_path):
            overrides_to_use = overrides_path

    return induce_criteria(
        transcript_path=transcript_to_use,
        output_criteria_path=output_criteria_path,
        model_path=model_path,
        approved_path=approved_to_use,
        channel_name=channel,
        overrides_path=overrides_to_use,
    )
