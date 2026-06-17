#!/bin/bash
# Ralph Wiggum - Autonomous AI agent loop
# Usage: ./ralph.sh [--tool amp|claude|opencode|gemini|codex] [max_iterations]
#
# Agent persona support:
#   Add "agents" to prd.json at the PRD level (default for all stories) and/or
#   at the story level (overrides the default for that iteration).
#   Agent files are loaded from an agency-agents/ directory — checked first as
#   a sibling of this script's directory, then as a subdirectory within it.
#   Agent names must match filenames in agency-agents/ (without the .md extension).
#   Example: "agents": ["engineering-software-architect"]
#            → loads agency-agents/engineering/engineering-software-architect.md
#
# Local↔remote failover:
#   Each iteration, ralph estimates token cost from the iteration's prompt
#   inputs (agent prefix + tool-specific base file + prd.json + progress.txt)
#   plus RALPH_AGENT_READ_BUDGET. If the estimate exceeds RALPH_LOCAL_CONTEXT_PCT%
#   of RALPH_LOCAL_CONTEXT_MAX, it sources RALPH_REMOTE_ENV. If the local
#   llama-server isn't reachable, same thing. Otherwise it sources RALPH_LOCAL_ENV.
#   See .env.example for the full set of knobs.

set -e

TOOL="amp"        # Default tool
MAX_ITERATIONS=10
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRD_FILE="$SCRIPT_DIR/prd.json"
PROGRESS_FILE="$SCRIPT_DIR/progress.txt"
ARCHIVE_DIR="$SCRIPT_DIR/archive"
LAST_BRANCH_FILE="$SCRIPT_DIR/.last-branch"
COST_LOG="$SCRIPT_DIR/.ralph-cost.log"

# ---------------------------------------------------------------------------
# Local↔remote failover configuration (all overridable via env / .env)
# ---------------------------------------------------------------------------
RALPH_LOCAL_ENV="${RALPH_LOCAL_ENV:-$HOME/.local/bin/ralph-local-llama.env}"
RALPH_REMOTE_ENV="${RALPH_REMOTE_ENV:-$HOME/.local/bin/ralph-opencode-anthropic.env}"
RALPH_LOCAL_CONTEXT_MAX="${RALPH_LOCAL_CONTEXT_MAX:-131072}"
RALPH_LOCAL_CONTEXT_PCT="${RALPH_LOCAL_CONTEXT_PCT:-80}"
RALPH_AGENT_READ_BUDGET="${RALPH_AGENT_READ_BUDGET:-30000}"
RALPH_LOCAL_LLAMA_URL="${RALPH_LOCAL_LLAMA_URL:-http://localhost:8080/health}"
# Max seconds for a single agent call. Guards against a stalled model API
# (idle-but-open HTTPS connection) hanging the whole loop forever. 0 = unbounded.
RALPH_AGENT_TIMEOUT="${RALPH_AGENT_TIMEOUT:-900}"
# Connectivity gate (run before each agent call). The loop talks to a remote
# model API, so a network cut would otherwise burn the full agent timeout every
# iteration. Probe URL + poll interval (seconds). NET_GATE_DIR is a per-user
# marker dir shared across concurrent loops so the ⏸/▶ Slack notices dedupe.
RALPH_NET_CHECK_URL="${RALPH_NET_CHECK_URL:-https://api.deepseek.com}"
RALPH_NET_POLL="${RALPH_NET_POLL:-15}"
NET_GATE_DIR="${RALPH_NET_GATE_DIR:-/tmp/ralph-net-gate-$(id -u 2>/dev/null)}"
mkdir -p "$NET_GATE_DIR" 2>/dev/null || true
LOCAL_THRESHOLD=$(( RALPH_LOCAL_CONTEXT_MAX * RALPH_LOCAL_CONTEXT_PCT / 100 ))

# Resolve a `timeout` binary to bound each agent call so a stalled model API
# ends the iteration (the existing `|| true` swallows timeout's exit 124)
# instead of hanging the loop. macOS ships neither `timeout` nor `gtimeout` by
# default — if absent (and not disabled via RALPH_AGENT_TIMEOUT=0) the agent
# runs UNBOUNDED and we warn once. -k 30 hard-kills if SIGTERM is ignored.
AGENT_TIMEOUT_CMD=""
if [ "${RALPH_AGENT_TIMEOUT}" != "0" ]; then
  if command -v timeout >/dev/null 2>&1; then
    AGENT_TIMEOUT_CMD="timeout -k 30 ${RALPH_AGENT_TIMEOUT}"
  elif command -v gtimeout >/dev/null 2>&1; then
    AGENT_TIMEOUT_CMD="gtimeout -k 30 ${RALPH_AGENT_TIMEOUT}"
  else
    echo "  ⚠️  RALPH_AGENT_TIMEOUT=${RALPH_AGENT_TIMEOUT}s set but no 'timeout'/'gtimeout' on PATH — agent runs UNBOUNDED (brew install coreutils). Set RALPH_AGENT_TIMEOUT=0 to silence." >&2
  fi
fi

# ---------------------------------------------------------------------------
# Locate agency-agents directory
# Priority: sibling directory first, then subdirectory of SCRIPT_DIR
# ---------------------------------------------------------------------------
AGENT_DIR=""
for _candidate in "$SCRIPT_DIR/../agency-agents" "$SCRIPT_DIR/agency-agents"; do
  if [ -d "$_candidate" ]; then
    AGENT_DIR="$(cd "$_candidate" && pwd)"
    break
  fi
done

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case $1 in
    --tool)
      TOOL="$2"
      shift 2
      ;;
    --tool=*)
      TOOL="${1#*=}"
      shift
      ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        MAX_ITERATIONS="$1"
      fi
      shift
      ;;
  esac
done

# Validate tool
VALID_TOOLS="amp claude opencode gemini codex"
if ! echo "$VALID_TOOLS" | grep -qw "$TOOL"; then
  echo "Error: Invalid tool '$TOOL'. Must be one of: $VALID_TOOLS"
  exit 1
fi

# ---------------------------------------------------------------------------
# Archive previous run if branch changed
# ---------------------------------------------------------------------------
if [ -f "$PRD_FILE" ] && [ -f "$LAST_BRANCH_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  LAST_BRANCH=$(cat "$LAST_BRANCH_FILE" 2>/dev/null || echo "")

  if [ -n "$CURRENT_BRANCH" ] && [ -n "$LAST_BRANCH" ] && [ "$CURRENT_BRANCH" != "$LAST_BRANCH" ]; then
    DATE=$(date +%Y-%m-%d)
    FOLDER_NAME=$(echo "$LAST_BRANCH" | sed 's|^ralph/||')
    ARCHIVE_FOLDER="$ARCHIVE_DIR/$DATE-$FOLDER_NAME"
    echo "Archiving previous run: $LAST_BRANCH"
    mkdir -p "$ARCHIVE_FOLDER"
    [ -f "$PRD_FILE" ] && cp "$PRD_FILE" "$ARCHIVE_FOLDER/"
    [ -f "$PROGRESS_FILE" ] && cp "$PROGRESS_FILE" "$ARCHIVE_FOLDER/"
    [ -f "$COST_LOG" ] && cp "$COST_LOG" "$ARCHIVE_FOLDER/"
    echo "   Archived to: $ARCHIVE_FOLDER"

    echo "# Ralph Progress Log" > "$PROGRESS_FILE"
    echo "Started: $(date)" >> "$PROGRESS_FILE"
    echo "---" >> "$PROGRESS_FILE"
    : > "$COST_LOG"
  fi
fi

# Track current branch
if [ -f "$PRD_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  [ -n "$CURRENT_BRANCH" ] && echo "$CURRENT_BRANCH" > "$LAST_BRANCH_FILE"
fi

# Initialize progress file
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Ralph Progress Log" > "$PROGRESS_FILE"
  echo "Started: $(date)" >> "$PROGRESS_FILE"
  echo "---" >> "$PROGRESS_FILE"
fi

echo "🚀 Starting Ralph — Tool: $TOOL — Max iterations: $MAX_ITERATIONS"
if [ -n "$AGENT_DIR" ]; then
  echo "   Agent directory: $AGENT_DIR"
else
  echo "   No agency-agents/ directory found — persona injection disabled"
fi

# ---------------------------------------------------------------------------
# Review-gate preflight (visibility): surface whether the aider/Kimi review can
# actually run, so a misconfigured gate is obvious at startup instead of being
# silently skipped every iteration.
# ---------------------------------------------------------------------------
if [ "${SKIP_AIDER_REVIEW:-0}" = "1" ]; then
  echo "   Review gate: DISABLED (SKIP_AIDER_REVIEW=1)"
elif [ ! -f "$SCRIPT_DIR/aider-review.sh" ]; then
  echo "   Review gate: ⚠️  aider-review.sh not found next to ralph.sh — reviews will NOT run"
elif ! command -v aider >/dev/null 2>&1; then
  echo "   Review gate: ⚠️  'aider' CLI not on PATH — reviews will SKIP (e.g. pipx install aider-chat)"
else
  echo "   Review gate: aider present, model=${AIDER_REVIEW_MODEL:-<local fallback — set AIDER_REVIEW_MODEL>}"
fi

# ---------------------------------------------------------------------------
# Helper: check prd.json for incomplete stories
# ---------------------------------------------------------------------------
prd_all_complete() {
  if [ ! -f "$PRD_FILE" ]; then return 1; fi
  local incomplete
  incomplete=$(jq '[.userStories[] | select(.passes != true)] | length' "$PRD_FILE" 2>/dev/null) || return 1
  [ "$incomplete" = "0" ]
}

# ---------------------------------------------------------------------------
# Failover helpers — keep these dumb and side-effect-free except apply_/log_.
# ---------------------------------------------------------------------------

# Map a tool name to its base prompt file (the one each case branch uses).
base_prompt_for_tool() {
  case "$1" in
    amp)      echo "$SCRIPT_DIR/prompt.md" ;;
    claude)   echo "$SCRIPT_DIR/CLAUDE.md" ;;
    opencode) echo "$SCRIPT_DIR/OPENCODE.md" ;;
    gemini)   echo "$SCRIPT_DIR/GEMINI.md" ;;
    codex)    echo "$SCRIPT_DIR/AIDER_CODEX.md" ;;
    *)        echo "$SCRIPT_DIR/prompt.md" ;;
  esac
}

# Estimate token count for the upcoming iteration. Sums bytes of the agent
# prefix file + tool-specific base prompt + prd.json + progress.txt, then
# divides by 3 (conservative chars-per-token for code-heavy English) and
# adds RALPH_AGENT_READ_BUDGET for files the agent will read on top.
# $1 — agent prefix file path (may not exist or be empty)
estimate_input_tokens() {
  local agent_prefix_file="$1"
  local base_prompt
  base_prompt=$(base_prompt_for_tool "$TOOL")
  local total_chars=0 f
  for f in "$agent_prefix_file" "$base_prompt" "$PRD_FILE" "$PROGRESS_FILE"; do
    [ -f "$f" ] && total_chars=$(( total_chars + $(wc -c < "$f") ))
  done
  echo $(( total_chars / 3 + RALPH_AGENT_READ_BUDGET ))
}

# Probe local llama-server. 3s timeout — long enough for slow boot, short
# enough not to stall an iteration when the server is gone.
llama_reachable() {
  curl -sf --max-time 3 "$RALPH_LOCAL_LLAMA_URL" >/dev/null 2>&1
}

# Decide route for this iteration. Echoes "local" or "remote".
# Order: explicit override > context-fits check > reachability check.
pick_endpoint() {
  local est=$1
  if [ "${RALPH_FORCE_REMOTE:-0}" = "1" ];     then echo "remote"; return; fi
  if [ "${RALPH_DISABLE_FAILOVER:-0}" = "1" ]; then echo "local";  return; fi
  if [ "$est" -gt "$LOCAL_THRESHOLD" ];        then echo "remote"; return; fi
  if ! llama_reachable;                        then echo "remote"; return; fi
  echo "local"
}

# Source the env file matching the chosen endpoint. Set -a/+a so vars
# defined inside the file are exported even if the file omits `export`.
apply_endpoint_env() {
  local endpoint=$1 env_file
  if [ "$endpoint" = "remote" ]; then env_file="$RALPH_REMOTE_ENV"
  else                               env_file="$RALPH_LOCAL_ENV"
  fi
  if [ -f "$env_file" ]; then
    # shellcheck disable=SC1090
    set -a; source "$env_file"; set +a
  else
    echo "  ⚠️  Warning: $endpoint env file not found: $env_file" >&2
  fi
}

# Append a tab-separated line to .ralph-cost.log including the model and an
# estimated input cost. est_cost_usd = est_tokens × RALPH_COST_PER_MTOK_INPUT
# (USD per 1M input tokens; default 0.27 ≈ DeepSeek; set per provider —
# e.g. 0.74 for Kimi K2.6). Output tokens aren't known until after the run, so
# the tool's own reported (actual) cost is captured separately post-run.
log_iteration() {
  local iter=$1 endpoint=$2 est=$3 model=$4
  local rate="${RALPH_COST_PER_MTOK_INPUT:-0.27}"
  local est_cost
  est_cost=$(awk "BEGIN{printf \"%.4f\", ($est/1000000.0)*$rate}")
  printf "%s\tphase=run\titer=%d\ttool=%s\tmodel=%s\tendpoint=%s\test_tokens=%d\test_cost_usd=%s\n" \
    "$(date +%Y-%m-%dT%H:%M:%S%z)" "$iter" "$TOOL" "$model" "$endpoint" "$est" "$est_cost" >> "$COST_LOG"
}

# ---------------------------------------------------------------------------
# Per-iteration Slack notification. Non-blocking and best-effort:
#   * Reads SLACK_WEBHOOK_URL from the environment (or whatever the endpoint /
#     review env files exported via `set -a; source`). NEVER hardcoded.
#   * If SLACK_WEBHOOK_URL is unset/empty, or curl is missing, returns silently.
#   * curl is bounded (-m 10) and errors are swallowed (|| true) so a Slack
#     hiccup can never break or stall the loop.
# $1 — iteration number   $2 — story id   $3 — review result   $4 — summary line
# ---------------------------------------------------------------------------
slack_notify() {
  local iter="$1" story="$2" result="$3" summary="$4"
  [ -z "${SLACK_WEBHOOK_URL:-}" ] && return 0
  command -v curl >/dev/null 2>&1 || return 0

  local emoji
  case "$result" in
    pass) emoji="✅" ;;
    fail) emoji="❌" ;;
    *)    emoji="➖" ;;
  esac

  # Collapse newlines/tabs to spaces, then escape backslash + double-quote so
  # the value embeds safely inside the JSON string below.
  local safe_summary
  safe_summary=$(printf '%s' "$summary" | tr '\n\t' '  ' | sed 's/\\/\\\\/g; s/"/\\"/g')
  local text="${emoji} Ralph iter ${iter} — ${story} — review: ${result} — ${safe_summary}"

  curl -sf -m 10 -X POST -H 'Content-Type: application/json' \
    --data "{\"text\":\"${text}\"}" "$SLACK_WEBHOOK_URL" >/dev/null 2>&1 || true
}

# Post a raw text line to Slack (best-effort, non-blocking) — shares the guard
# and curl flags with slack_notify. Used for the connectivity ⏸/▶ notices.
slack_send_text() {
  local text="$1"
  [ -z "${SLACK_WEBHOOK_URL:-}" ] && return 0
  command -v curl >/dev/null 2>&1 || return 0
  local safe
  safe=$(printf '%s' "$text" | tr '\n\t' '  ' | sed 's/\\/\\\\/g; s/"/\\"/g')
  curl -sf -m 10 -X POST -H 'Content-Type: application/json' \
    --data "{\"text\":\"${safe}\"}" "$SLACK_WEBHOOK_URL" >/dev/null 2>&1 || true
}

# Cheap reachability probe to the model provider. Exit 0 = the host answered
# (ANY HTTP response, even 4xx — we only care that the network/TLS path is up,
# NOT that we're authenticated, so deliberately NO -f). Non-zero = DNS/connect/
# timeout = treat as down.
network_reachable() {
  curl -s -o /dev/null --max-time 5 "$RALPH_NET_CHECK_URL" >/dev/null 2>&1
}

# Connectivity GATE — call before each agent run. Reachable → return at once.
# Down → pause and re-check every RALPH_NET_POLL seconds until it returns, then
# resume. Waits out an outage of ANY length (no artificial cap). A drop that
# happens DURING an agent call is still caught by the RALPH_AGENT_TIMEOUT
# backstop; this gate then waits before the next attempt.
#
# Multi-loop safe: the probe is read-only (no shared lock — each loop gates
# independently). The ⏸/▶ Slack notices are deduped across concurrent loops via
# atomic mkdir/rmdir on a shared marker ($NET_GATE_DIR/outage) so N loops emit
# ONE ⏸ and ONE ▶ per outage window. The dedupe NEVER blocks a loop: mkdir/rmdir
# are instant and their failure just means another loop already posted.
wait_for_network() {
  if network_reachable; then
    # Fast path. Clear a stale marker (e.g. the loop that posted ⏸ exited
    # before recovery) and post the resume once, so the next outage isn't muted.
    if rmdir "$NET_GATE_DIR/outage" 2>/dev/null; then
      slack_send_text "▶ back online — resuming ralph ($(hostname -s 2>/dev/null) $(date '+%H:%M:%S'))"
    fi
    return 0
  fi

  # Down: first loop to claim the marker posts the pause notice.
  if mkdir "$NET_GATE_DIR/outage" 2>/dev/null; then
    slack_send_text "⏸ network down — pausing ralph ($(hostname -s 2>/dev/null) $(date '+%H:%M:%S'))"
  fi
  echo "  ⏸  Network unreachable (${RALPH_NET_CHECK_URL}) — pausing; re-checking every ${RALPH_NET_POLL}s..." >&2

  until network_reachable; do
    sleep "$RALPH_NET_POLL"
  done

  echo "  ▶  Network back — resuming." >&2
  # First loop to clear the marker posts the resume notice.
  if rmdir "$NET_GATE_DIR/outage" 2>/dev/null; then
    slack_send_text "▶ back online — resuming ralph ($(hostname -s 2>/dev/null) $(date '+%H:%M:%S'))"
  fi
}

# ---------------------------------------------------------------------------
# Helper: write agent persona prefix for the next incomplete story to a file.
#
# Resolution order: story.agents → prd.agents → empty (no persona, no change)
#
# $1 — output file path to write combined agent content into
# Logs loaded/missing agents to stderr so they surface in the terminal.
# Returns 0 if at least one agent was loaded, 1 if none.
# ---------------------------------------------------------------------------
write_agent_prefix() {
  local out_file="$1"
  : > "$out_file"   # truncate / create

  if [ ! -f "$PRD_FILE" ] || [ -z "$AGENT_DIR" ]; then
    return 1
  fi

  # Resolve agents: story-level overrides PRD-level
  local agents
  agents=$(jq -r '
    ([ .userStories[] | select(.passes != true) ][0].agents // .agents // []) | .[]
  ' "$PRD_FILE" 2>/dev/null) || agents=""

  if [ -z "$agents" ]; then
    return 1
  fi

  local loaded=0
  while IFS= read -r agent_name; do
    [ -z "$agent_name" ] && continue
    local agent_file
    agent_file=$(find "$AGENT_DIR" -name "${agent_name}.md" 2>/dev/null | head -1)
    if [ -f "$agent_file" ]; then
      cat "$agent_file" >> "$out_file"
      printf '\n\n---\n\n' >> "$out_file"
      echo "  🎭 Agent loaded: $agent_name" >&2
      loaded=$((loaded + 1))
    else
      echo "  ⚠️  Warning: agent '${agent_name}' not found in $AGENT_DIR" >&2
    fi
  done <<< "$agents"

  [ "$loaded" -gt 0 ] && return 0 || return 1
}

# ---------------------------------------------------------------------------
# Optional completion hook — runs $RALPH_ON_COMPLETE once when the loop finishes
# (any exit after it starts: all-complete, <promise>COMPLETE</promise>, or max
# iterations). Opt-in; unset = no-op. The hook runs in a subshell and its exit
# code never masks the loop's result. Examples:
#   RALPH_ON_COMPLETE='git push'
#   RALPH_ON_COMPLETE='pullscript.sh . -p'
# ---------------------------------------------------------------------------
_on_complete() {
  local code=$?
  trap - EXIT                       # don't re-enter
  if [ -n "${RALPH_ON_COMPLETE:-}" ]; then
    echo ""
    echo "🔔 RALPH_ON_COMPLETE (loop exit=$code): $RALPH_ON_COMPLETE"
    ( eval "$RALPH_ON_COMPLETE" ) || echo "⚠️  RALPH_ON_COMPLETE returned non-zero (ignored)"
  fi
  exit "$code"
}
trap _on_complete EXIT

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
for i in $(seq 1 $MAX_ITERATIONS); do
  echo ""
  echo "==============================================================="
  echo "  Ralph Iteration $i of $MAX_ITERATIONS ($TOOL)"
  echo "==============================================================="

  # Early exit: all stories already marked complete before this iteration
  if prd_all_complete; then
    echo ""
    echo "✅ All PRD stories already complete — skipping iteration $i"
    exit 0
  fi

  # Capture the story this iteration will work BEFORE the agent runs (after it
  # runs the story may flip to passes:true and "first incomplete" would shift).
  # Used only for the per-iteration Slack notification below.
  STORY_ID=$(jq -r '[ .userStories[] | select(.passes != true) ][0].id // "unknown"' "$PRD_FILE" 2>/dev/null || echo "unknown")

  # -------------------------------------------------------------------------
  # Resolve agent personas for this iteration's story
  # -------------------------------------------------------------------------
  AGENT_PREFIX_FILE=$(mktemp)
  write_agent_prefix "$AGENT_PREFIX_FILE" || true   # failure = no agents, that's fine

  # -------------------------------------------------------------------------
  # Decide local↔remote, source the matching env, log it.
  # MUST happen before the agent runs — agents read endpoint env on startup.
  # -------------------------------------------------------------------------
  EST=$(estimate_input_tokens "$AGENT_PREFIX_FILE")
  ENDPOINT=$(pick_endpoint "$EST")
  apply_endpoint_env "$ENDPOINT"
  # Prefer an explicit env override; otherwise read the model from opencode.json
  # (the config the loop actually uses) so the cost log shows the real model,
  # not just the tool name.
  MODEL="${OPENCODE_MODEL:-${AIDER_MODEL:-}}"
  if [ -z "$MODEL" ]; then
    for _oc in opencode.json "$SCRIPT_DIR/../../opencode.json"; do
      if [ -f "$_oc" ] && command -v jq >/dev/null 2>&1; then
        MODEL="$(jq -r '.model // empty' "$_oc" 2>/dev/null)"; [ -n "$MODEL" ] && break
      fi
    done
  fi
  MODEL="${MODEL:-$TOOL}"
  log_iteration "$i" "$ENDPOINT" "$EST" "$MODEL"
  echo "  📡 Endpoint: $ENDPOINT  model=$MODEL  (est=$EST tok, threshold=$LOCAL_THRESHOLD)"

  # -------------------------------------------------------------------------
  # Build the combined prompt (agent prefix + base instruction file)
  # -------------------------------------------------------------------------
  TMPPROMPT=$(mktemp)
  TMPOUT=$(mktemp)

  # -------------------------------------------------------------------------
  # Determine whether we can stream output live via /dev/tty.
  # /dev/tty is the controlling terminal — works on Linux and macOS.
  # Falls back to captured-then-printed output (e.g. CI with no tty).
  # This fixes the "STDOUT stuck on iteration 1" problem: previously, all
  # output was buffered silently inside $(...) until the command finished.
  # -------------------------------------------------------------------------
  STREAM_LIVE=false
  [ -w /dev/tty ] && STREAM_LIVE=true

  # -------------------------------------------------------------------------
  # Connectivity gate: pause HERE (at an iteration boundary, not mid-call) if
  # the model API is unreachable, and resume the instant it returns. A drop
  # that happens during the agent call is caught by RALPH_AGENT_TIMEOUT, and
  # the next iteration gates here again.
  # -------------------------------------------------------------------------
  wait_for_network

  # -------------------------------------------------------------------------
  # Run the AI tool
  # -------------------------------------------------------------------------
  case "$TOOL" in

    "amp")
      cat "$AGENT_PREFIX_FILE" "$SCRIPT_DIR/prompt.md" > "$TMPPROMPT"
      if $STREAM_LIVE; then
        cat "$TMPPROMPT" | $AGENT_TIMEOUT_CMD amp --dangerously-allow-all 2>&1 | tee /dev/tty > "$TMPOUT" || true
      else
        cat "$TMPPROMPT" | $AGENT_TIMEOUT_CMD amp --dangerously-allow-all > "$TMPOUT" 2>&1 || true
      fi
      ;;

    "claude")
      # NOTE: Claude Code requires the prompt as a string argument, NOT via
      # stdin. Newer versions misparse stdin as structured tool input (ZodError).
      cat "$AGENT_PREFIX_FILE" "$SCRIPT_DIR/CLAUDE.md" > "$TMPPROMPT"
      if $STREAM_LIVE; then
        $AGENT_TIMEOUT_CMD claude --dangerously-skip-permissions --print "$(cat "$TMPPROMPT")" 2>&1 | tee /dev/tty > "$TMPOUT" || true
      else
        $AGENT_TIMEOUT_CMD claude --dangerously-skip-permissions --print "$(cat "$TMPPROMPT")" > "$TMPOUT" 2>&1 || true
      fi
      ;;

    "opencode")
      cat "$AGENT_PREFIX_FILE" "$SCRIPT_DIR/OPENCODE.md" > "$TMPPROMPT"
      if $STREAM_LIVE; then
        $AGENT_TIMEOUT_CMD opencode run "$(cat "$TMPPROMPT")" 2>&1 | tee /dev/tty > "$TMPOUT" || true
      else
        $AGENT_TIMEOUT_CMD opencode run "$(cat "$TMPPROMPT")" > "$TMPOUT" 2>&1 || true
      fi
      ;;

    "gemini")
      cat "$AGENT_PREFIX_FILE" "$SCRIPT_DIR/GEMINI.md" > "$TMPPROMPT"
      if $STREAM_LIVE; then
        $AGENT_TIMEOUT_CMD gemini -p "$(cat "$TMPPROMPT")" 2>&1 | tee /dev/tty > "$TMPOUT" || true
      else
        $AGENT_TIMEOUT_CMD gemini -p "$(cat "$TMPPROMPT")" > "$TMPOUT" 2>&1 || true
      fi
      ;;

    "codex")
      # aider reads instructions from a file; prepend agent content inline
      cat "$AGENT_PREFIX_FILE" "$SCRIPT_DIR/AIDER_CODEX.md" > "$TMPPROMPT"
      if $STREAM_LIVE; then
        $AGENT_TIMEOUT_CMD aider --model gpt-4o --message-file "$TMPPROMPT" --yes --no-auto-commit 2>&1 | tee /dev/tty > "$TMPOUT" || true
      else
        $AGENT_TIMEOUT_CMD aider --model gpt-4o --message-file "$TMPPROMPT" --yes --no-auto-commit > "$TMPOUT" 2>&1 || true
      fi
      ;;

  esac

  # Best-effort: record the tool's own reported cost for this iteration. Output
  # formats vary by tool (aider prints "Cost: $X"; others differ) — logged as NA
  # when not parseable. Combine with est_cost_usd for a fuller spend picture.
  ACTUAL_COST=$(grep -oiE 'cost[^0-9$]*\$?[0-9]+\.[0-9]+' "$TMPOUT" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | tail -1)
  printf "%s\tphase=run\titer=%d\ttool=%s\tmodel=%s\tactual_cost_usd=%s\n" \
    "$(date +%Y-%m-%dT%H:%M:%S%z)" "$i" "$TOOL" "${MODEL:-$TOOL}" "${ACTUAL_COST:-NA}" >> "$COST_LOG"

  # Capture output for completion detection
  OUTPUT=$(cat "$TMPOUT")

  # Clean up temp files
  rm -f "$AGENT_PREFIX_FILE" "$TMPPROMPT" "$TMPOUT"

  # If not streamed live, print now
  if ! $STREAM_LIVE; then
    printf '%s\n' "$OUTPUT"
  fi

  # -------------------------------------------------------------------------
  # Post-iteration verification: ensure the agent committed its work
  # -------------------------------------------------------------------------
  if ! git -C "$SCRIPT_DIR" diff --quiet --exit-code 2>/dev/null || \
     ! git -C "$SCRIPT_DIR" diff --cached --quiet --exit-code 2>/dev/null; then
    UNCOMMITTED=$(git -C "$SCRIPT_DIR" status --porcelain | wc -l | tr -d ' ')
    echo ""
    echo "  ⚠️  Warning: $UNCOMMITTED uncommitted file(s) detected after iteration $i."
    echo "     The agent may have modified files but did not commit. Auto-committing..."
    git -C "$SCRIPT_DIR" add -A
    git -C "$SCRIPT_DIR" commit -m "chore(ralph): auto-commit uncommitted changes from iteration $i" || true
  fi

  # -------------------------------------------------------------------------
  # Post-iteration code-review gate (loop-driven, not left to the agent).
  # The loop runs the reviewer itself so the gate ALWAYS fires — cheaper coding
  # models routinely skip it, so relying on the agent means it never runs.
  # Reviews this iteration's commit/diff. Configure the reviewer via
  # AIDER_REVIEW_MODEL + its key, e.g.
  #   openrouter/moonshotai/kimi-k2.6   +   OPENROUTER_API_KEY
  #
  #   SKIP_AIDER_REVIEW=1     disable the gate entirely
  #   RALPH_REVIEW_ENV=path   env file to source for the review model/keys
  #   RALPH_REQUIRE_REVIEW=1  stop the loop when the review returns RESULT: FAIL
  # -------------------------------------------------------------------------
  REVIEW_RESULT="skipped"
  if [ "${SKIP_AIDER_REVIEW:-0}" != "1" ] && [ -f "$SCRIPT_DIR/aider-review.sh" ]; then
    if [ -n "${RALPH_REVIEW_ENV:-}" ] && [ -f "$RALPH_REVIEW_ENV" ]; then
      # shellcheck disable=SC1090
      { set -a; source "$RALPH_REVIEW_ENV"; set +a; }
    fi
    REPO_ROOT=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_DIR")
    echo ""
    echo "  🔍 Post-iteration review (model=${AIDER_REVIEW_MODEL:-<local fallback>})"
    if ( cd "$REPO_ROOT" && bash "$SCRIPT_DIR/aider-review.sh" ); then
      REVIEW_RESULT="pass"
      echo "  ✅ Review gate clear for iteration $i."
    else
      REVIEW_RESULT="fail"
      echo "  ❌ Review gate reported issues on iteration $i (RESULT: FAIL)."
    fi
  fi

  # -------------------------------------------------------------------------
  # Per-iteration Slack notification (non-blocking). Posts the story id, the
  # review-gate result, and a one-line change summary (this iteration's latest
  # commit subject). Done BEFORE the RALPH_REQUIRE_REVIEW hard stop below so a
  # failing iteration still notifies before the loop exits.
  # -------------------------------------------------------------------------
  ITER_SUMMARY=$(git -C "$SCRIPT_DIR" log -1 --format='%s' 2>/dev/null || echo "no commit")
  slack_notify "$i" "${STORY_ID:-unknown}" "$REVIEW_RESULT" "$ITER_SUMMARY"

  # Hard stop on a failing review, if requested (Slack already posted above).
  if [ "$REVIEW_RESULT" = "fail" ]; then
    if [ "${RALPH_REQUIRE_REVIEW:-0}" = "1" ]; then
      echo "  ⛔ RALPH_REQUIRE_REVIEW=1 — stopping so you can address the findings."
      exit 1
    fi
    echo "     Continuing (set RALPH_REQUIRE_REVIEW=1 to make this a hard stop)."
  fi

  # -------------------------------------------------------------------------
  # Completion detection
  # -------------------------------------------------------------------------

  # Primary: model emits <promise>COMPLETE</promise>
  if printf '%s\n' "$OUTPUT" | grep -q "<promise>COMPLETE</promise>"; then
    echo ""
    echo "✅ Ralph completed all tasks at iteration $i of $MAX_ITERATIONS"
    exit 0
  fi

  # Fallback: inspect prd.json directly.
  # Handles cases where the model finishes but doesn't emit the signal
  # (e.g. truncated output, JSON-wrapped response, or crash after writing).
  if prd_all_complete; then
    echo ""
    echo "✅ All PRD stories complete (verified via prd.json) at iteration $i"
    exit 0
  fi

  echo "Iteration $i complete. Continuing..."
  sleep 2
done

echo ""
echo "Ralph reached max iterations ($MAX_ITERATIONS) without completing all tasks."
echo "Check $PROGRESS_FILE for status. Remaining stories:"
jq '[.userStories[] | select(.passes != true) | {id, title}]' "$PRD_FILE" 2>/dev/null || true
exit 1
