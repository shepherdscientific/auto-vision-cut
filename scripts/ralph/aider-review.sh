#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Aider Review — provider-agnostic
#
# Environment variables (all optional):
#
#   SKIP_AIDER_REVIEW=1          Skip this step entirely (no warning)
#
#   AIDER_REVIEW_MODEL           Model for review, e.g.:
#                                  openai/qwen3-coder-next   (local, default)
#                                  gemini/gemini-2.5-pro
#                                  deepseek/deepseek-chat
#
#   AIDER_REVIEW_API_BASE        Override API base URL (OpenAI-compatible providers)
#                                  Defaults to LLM_API_BASE for local/deepseek
#   AIDER_REVIEW_API_KEY         Override API key
#                                  Defaults to LLM_API_KEY or provider env vars
#
# Provider auto-detection (when AIDER_REVIEW_MODEL is set):
#   gemini/*   → uses GEMINI_API_KEY (no base URL needed)
#   *          → uses AIDER_REVIEW_API_BASE + AIDER_REVIEW_API_KEY
#
# ---------------------------------------------------------------------------

# --- Load review env (model + keys) if not already in the environment --------
# Lets the gate work even when invoked by a tool that sanitizes the environment,
# or by a user who forgot to `source` their env file. Honors RALPH_REVIEW_ENV
# first, then conventional repo-root locations. Anything already exported wins.
if [ -z "${AIDER_REVIEW_MODEL:-}" ]; then
  _ar_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  _ar_root="$(git -C "$_ar_dir" rev-parse --show-toplevel 2>/dev/null || echo "$_ar_dir")"
  for _ar_env in "${RALPH_REVIEW_ENV:-}" "$_ar_root/.env.deepseek-kimi" "$_ar_dir/.env.deepseek-kimi" "$_ar_root/.ralph-review.env"; do
    if [ -n "$_ar_env" ] && [ -f "$_ar_env" ]; then
      echo "🔑 aider-review: loading review env from $_ar_env"
      # shellcheck disable=SC1090
      set -a; . "$_ar_env"; set +a
      break
    fi
  done
fi

# Skip entirely if requested
if [ "${SKIP_AIDER_REVIEW:-0}" = "1" ]; then
  echo "⏭️  SKIP_AIDER_REVIEW=1 — skipping aider review step"
  exit 0
fi

# Verify aider is installed
if ! command -v aider &> /dev/null; then
  echo -e "\033[33m⚠️  aider-review: 'aider' CLI not found on PATH — REVIEW SKIPPED (this is NOT a pass).\033[0m"
  echo "   Install it so the review gate can run, e.g.:  pipx install aider-chat"
  exit 0
fi

# --- Resolve model -------------------------------------------------------
REVIEW_MODEL="${AIDER_REVIEW_MODEL:-}"

if [ -z "$REVIEW_MODEL" ]; then
  # No explicit review model — fall back to local server (legacy behaviour)
  REVIEW_MODEL="openai/qwen3-coder-next"
  USE_LOCAL=1
else
  USE_LOCAL=0
fi

# --- Detect provider from model prefix -----------------------------------
PROVIDER="${REVIEW_MODEL%%/*}"   # e.g. "gemini", "deepseek", "openai"

# --- Build aider args based on provider ----------------------------------
AIDER_EXTRA_ARGS=()

if [ "${USE_LOCAL:-0}" = "1" ]; then
  # ── Local server (original behaviour) ──────────────────────────────────
  API_BASE="${AIDER_REVIEW_API_BASE:-${LLM_API_BASE:-http://localhost:8080/v1}}"
  API_KEY="${AIDER_REVIEW_API_KEY:-${LLM_API_KEY:-dummy}}"

  if ! curl -sf --max-time 5 "$API_BASE/models" > /dev/null; then
    echo -e "\033[33m⚠️  aider-review: AIDER_REVIEW_MODEL not set and local LLM server not responding at $API_BASE — REVIEW SKIPPED (this is NOT a pass)\033[0m"
    echo "   For Kimi via OpenRouter:  export AIDER_REVIEW_MODEL=openrouter/moonshotai/kimi-k2.6  (and OPENROUTER_API_KEY)"
    echo "   Or point RALPH_REVIEW_ENV at an env file that exports them; SKIP_AIDER_REVIEW=1 to silence this gate"
    exit 0
  fi

  AIDER_EXTRA_ARGS+=(--openai-api-base "$API_BASE" --openai-api-key "$API_KEY")

elif [ "$PROVIDER" = "gemini" ]; then
  # ── Gemini (native litellm support, no base URL needed) ─────────────────
  KEY="${AIDER_REVIEW_API_KEY:-${GEMINI_API_KEY:-}}"
  if [ -z "$KEY" ]; then
    echo "⚠️  AIDER_REVIEW_MODEL=gemini/* but GEMINI_API_KEY is not set — skipping review."
    exit 0
  fi
  # aider/litellm picks up GEMINI_API_KEY automatically; passing explicitly for clarity
  export GEMINI_API_KEY="$KEY"

elif [ "$PROVIDER" = "openrouter" ]; then
  # ── OpenRouter (native litellm support — reads OPENROUTER_API_KEY, no base) ─
  KEY="${AIDER_REVIEW_API_KEY:-${OPENROUTER_API_KEY:-}}"
  if [ -z "$KEY" ]; then
    echo "⚠️  AIDER_REVIEW_MODEL=openrouter/* but OPENROUTER_API_KEY is not set — skipping review."
    exit 0
  fi
  export OPENROUTER_API_KEY="$KEY"

else
  # ── OpenAI-compatible (DeepSeek, any other API) ──────────────────────────
  API_BASE="${AIDER_REVIEW_API_BASE:-${OPENAI_BASE_URL:-${LLM_API_BASE:-}}}"
  API_KEY="${AIDER_REVIEW_API_KEY:-${OPENAI_API_KEY:-${LLM_API_KEY:-dummy}}}"

  if [ -z "$API_BASE" ]; then
    echo "⚠️  AIDER_REVIEW_MODEL=$REVIEW_MODEL requires AIDER_REVIEW_API_BASE (or OPENAI_BASE_URL) — skipping review."
    exit 0
  fi

  AIDER_EXTRA_ARGS+=(--openai-api-base "$API_BASE" --openai-api-key "$API_KEY")
fi

# -------------------------------------------------------------------------
# Capture the changes to review. Aider with --message alone does NOT see the
# working-tree diff (it only sees files explicitly added to the chat), so the
# model would otherwise reply "please provide the git diff". Embed it directly.
REVIEW_DIFF="$(git diff HEAD 2>/dev/null)"
UNTRACKED="$(git ls-files --others --exclude-standard 2>/dev/null)"
if [ -n "$UNTRACKED" ]; then
  while IFS= read -r _f; do
    [ -f "$_f" ] && REVIEW_DIFF="$REVIEW_DIFF
=== NEW FILE: $_f ===
$(cat "$_f" 2>/dev/null)"
  done <<< "$UNTRACKED"
fi
# Fall back to the latest commit when nothing is pending (review after commit).
if [ -z "$(printf '%s' "$REVIEW_DIFF" | tr -d '[:space:]')" ]; then
  REVIEW_DIFF="(no uncommitted changes; reviewing the latest commit)
$(git show --stat --patch HEAD 2>/dev/null)"
fi
# Cap size so a large diff doesn't blow the context window.
REVIEW_DIFF="$(printf '%s' "$REVIEW_DIFF" | head -c 150000)"

echo "🔍 Running Aider review  model=$REVIEW_MODEL  ($(printf '%s' "$REVIEW_DIFF" | wc -l) diff lines)"

REVIEW_OUTPUT=$(mktemp)
trap "rm -f $REVIEW_OUTPUT" EXIT

set +e
aider \
  --model "$REVIEW_MODEL" \
  ${AIDER_EXTRA_ARGS[@]+"${AIDER_EXTRA_ARGS[@]}"} \
  --yes \
  --no-auto-commit \
  --message "You are a senior code reviewer. Review ONLY the diff below — do NOT ask for more files or additional context; everything you need is included.
1. If there are critical logic errors, security issues, or PRD mismatches, print a line 'RESULT: FAIL' and list them.
2. If the code is sound, print a line 'RESULT: PASS'.
3. Always suggest one new pattern for AGENTS.md.
You MUST print exactly one of 'RESULT: PASS' or 'RESULT: FAIL'.

--- DIFF UNDER REVIEW ---
$REVIEW_DIFF" 2>&1 | tee "$REVIEW_OUTPUT"
AIDER_EXIT=${PIPESTATUS[0]}
set -e

# Record the review's own cost as a separate phase so review spend can be
# tallied apart from the coding run. Aider prints a "Cost: $X.XX ..." line;
# logged as NA when not parseable. Same .ralph-cost.log next to this script.
REVIEW_COST_LOG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.ralph-cost.log"
REVIEW_COST=$(grep -oiE 'cost[^0-9$]*\$?[0-9]+\.[0-9]+' "$REVIEW_OUTPUT" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | tail -1)
printf "%s\tphase=review\ttool=aider\tmodel=%s\tactual_cost_usd=%s\n" \
  "$(date +%Y-%m-%dT%H:%M:%S%z)" "$REVIEW_MODEL" "${REVIEW_COST:-NA}" >> "$REVIEW_COST_LOG" 2>/dev/null || true

if grep -q "RESULT: FAIL" "$REVIEW_OUTPUT"; then
  echo "❌ Aider review failed — fix critical issues before committing."
  exit 1
fi

# A genuine review MUST emit "RESULT: PASS". If neither PASS nor FAIL appears the
# model/provider call errored (e.g. litellm could not route the model) — never
# report a false "passed".
if ! grep -q "RESULT: PASS" "$REVIEW_OUTPUT"; then
  echo -e "\033[33m⚠️  Aider review did NOT run — no RESULT produced (aider exit=$AIDER_EXIT). This is NOT a pass.\033[0m"
  echo "   Likely an AIDER_REVIEW_MODEL/provider or API-key issue (e.g. use openrouter/google/gemini-2.5-pro)."
  echo "   Set SKIP_AIDER_REVIEW=1 to intentionally skip the gate."
  exit 0
fi

echo "✅ Aider review passed."
exit 0
