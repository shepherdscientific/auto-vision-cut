# Mr. Wiggum

![Ralph](ralph.webp)

Mr. Wiggum is a fork of [Ralph](https://github.com/snarktank/ralph) — an autonomous AI agent loop that runs AI coding tools repeatedly until all PRD items are complete. Each iteration is a fresh instance with clean context. Memory persists via git history, `progress.txt`, and `prd.json`.

**What this fork adds on top of Ralph:**

- **Multi-tool support** — run the loop with Amp, Claude Code, OpenCode, Gemini CLI, or Codex. Each tool has its own optimised prompt file.
- **Agent persona injection** — assign specialist personas (e.g. `engineering-backend-architect`, `testing-reality-checker`) to individual stories or the whole PRD. Personas are prepended to the base prompt, shaping the agent's approach per task.
- **Live STDOUT streaming** — output is streamed to the terminal in real time via `/dev/tty` when available.
- **Aider code review gate** — after each implementation, [aider](https://aider.chat) reviews the diff before committing. Critical issues must be fixed; the loop never commits code that fails review.
- **Provider-agnostic review** — the aider review step works against a local LLM server, Gemini, DeepSeek, or any OpenAI-compatible API. Switch providers with a single env var, independently of whichever tool is running the main loop.
- **PATCH-not-REWRITE guards** — all prompt files explicitly instruct the agent to make surgical edits rather than rewriting entire files, preventing silent regressions and wasted tokens.
- **`SKIP_AIDER_REVIEW` env var** — opt out of the review step per-run without editing any files.
- **Graceful server detection** — if the local LLM server is unreachable, the review step skips automatically instead of blocking the loop.

Based on [Geoffrey Huntley's Ralph pattern](https://ghuntley.com/ralph/).

---

## Prerequisites

- One or more of the following AI coding tools installed and authenticated:
  - [Amp CLI](https://ampcode.com) (`amp`)
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude`) — `npm install -g @anthropic-ai/claude-code`
  - [OpenCode](https://opencode.ai) (`opencode`) — **recommended path for Gemini, DeepSeek, Kimi, and any OpenRouter model** (native tool calling; the standalone Gemini CLI has tool calling gaps that break the loop)
  - [Gemini CLI](https://github.com/google-gemini/gemini-cli) (`gemini`) — limited tool calling support; prefer `--tool opencode` with a Gemini model instead
  - OpenAI Codex (`codex`)
- [aider](https://aider.chat) installed (`pip install aider-chat`) — required for the review gate
- `jq` installed (`brew install jq` on macOS)
- A git repository for your project

---

## Setup

### Option 1: Copy to your project

```bash
mkdir -p scripts/ralph
cp /path/to/mr-wiggum/ralph.sh scripts/ralph/
cp /path/to/mr-wiggum/aider-review.sh scripts/ralph/
cp /path/to/mr-wiggum/AGENTS.md scripts/ralph/

# Copy the prompt file(s) for your tool(s) of choice:
cp /path/to/mr-wiggum/CLAUDE.md scripts/ralph/     # Claude Code
cp /path/to/mr-wiggum/prompt.md scripts/ralph/      # Amp
cp /path/to/mr-wiggum/OPENCODE.md scripts/ralph/    # OpenCode
cp /path/to/mr-wiggum/GEMINI.md scripts/ralph/      # Gemini CLI

# Optionally copy agent personas:
cp -r /path/to/mr-wiggum/agency-agents scripts/ralph/

chmod +x scripts/ralph/ralph.sh scripts/ralph/aider-review.sh
```

### Option 2: Install skills globally

```bash
# For Amp
cp -r skills/prd ~/.config/amp/skills/
cp -r skills/ralph ~/.config/amp/skills/

# For Claude Code
cp -r skills/prd ~/.claude/skills/
cp -r skills/ralph ~/.claude/skills/
```

---

## Usage

```bash
# Default tool (amp), 10 iterations
./scripts/ralph/ralph.sh 10

# Specify a tool
./scripts/ralph/ralph.sh --tool claude 10
./scripts/ralph/ralph.sh --tool opencode 10
./scripts/ralph/ralph.sh --tool gemini 10

# Skip the aider review gate
SKIP_AIDER_REVIEW=1 ./scripts/ralph/ralph.sh --tool claude 10
```

### OpenCode: auto-accepting permissions

OpenCode prompts for tool permissions interactively by default, which blocks the unattended loop. Add a `permission` block to your project's `opencode.json` to pre-approve all tool use:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "google/gemini-2.5-pro",
  "permission": {
    "read": "allow",
    "write": "allow",
    "bash": "allow",
    "external_directory": "allow"
  }
}
```

`external_directory` is required separately — OpenCode treats paths outside the project root (e.g. `/tmp/prd.json` written during the loop) as a distinct permission class from `read`/`write`. Without it you’ll still get interactive prompts for those paths even with the other three set.

Claude Code uses `--dangerously-skip-permissions` for the same effect; Amp uses `--dangerously-allow-all`. The `permission` config is the OpenCode equivalent.

### Using Gemini models via OpenCode

The `--tool gemini` backend uses the Gemini CLI, which has limited tool calling support and will fail on tasks requiring file edits or bash execution. For Gemini models, use OpenCode instead — it connects to the Gemini API natively via `@ai-sdk/google` with full tool support:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "google/gemini-2.5-pro",
  "permission": { "read": "allow", "write": "allow", "bash": "allow", "external_directory": "allow" },
  "provider": {
    "google": {
      "npm": "@ai-sdk/google",
      "name": "Google",
      "options": { "apiKey": "{env:GEMINI_API_KEY}" },
      "models": {
        "gemini-2.5-pro": { "name": "Gemini 2.5 Pro", "limit": { "context": 1000000, "output": 65536 } }
      }
    }
  }
}
```

Then run with `--tool opencode` as usual — no changes to `ralph.sh` needed.

### Using OpenRouter with Claude Code (Anthropic models only)

[OpenRouter](https://openrouter.ai) lets you access many models through a single API key. Claude Code is the simplest integration — three env vars, no config changes:

```bash
export ANTHROPIC_BASE_URL=https://openrouter.ai/api
export ANTHROPIC_AUTH_TOKEN=sk-or-...   # your OpenRouter key
export ANTHROPIC_API_KEY=               # must be explicitly empty

./scripts/ralph/ralph.sh --tool claude 10
```

> **Important:** The Claude Code CLI is hardcoded to Anthropic's provider protocol. Even when routing through OpenRouter, it can only call **Anthropic-hosted models** (Claude Sonnet, Haiku, Opus). You cannot use it to call Kimi, Qwen, Mistral, or other non-Anthropic models — use OpenCode for those instead (see below).

You can route different task types to different Anthropic models via env vars:

```bash
export ANTHROPIC_DEFAULT_SONNET_MODEL=anthropic/claude-sonnet-4-6   # main loop
export ANTHROPIC_DEFAULT_HAIKU_MODEL=anthropic/claude-haiku-4-5     # fast sub-tasks
export CLAUDE_CODE_SUBAGENT_MODEL=anthropic/claude-haiku-4-5        # sub-agents
```

**BYOK (Bring Your Own Key):** You cannot use your existing Anthropic API key directly as an OpenRouter key — they are separate accounts. However, OpenRouter supports linking your Anthropic key under *Settings → Integrations* so that Anthropic model requests route through your own Anthropic account instead of OpenRouter’s shared pool. This avoids spending OpenRouter credits on Anthropic models if you already have an Anthropic subscription.

**Free tier warning:** The OpenRouter free plan gives only **5 requests/day** without purchased credits — not viable for the ralph loop. Add $5 in credits to get 50 req/day. For serious use with Claude, BYOK with your existing Anthropic key is the most cost-effective path.

### Using OpenRouter with OpenCode (any model)

For non-Anthropic models on OpenRouter — Kimi K2.5, Qwen, Mistral, DeepSeek, or any other — use `--tool opencode` with an OpenRouter provider block in `opencode.json`. OpenCode has no provider lock-in and handles tool calling correctly for all of them.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "openrouter/moonshotai/kimi-k2.5",
  "permission": { "read": "allow", "write": "allow", "bash": "allow", "external_directory": "allow" },
  "provider": {
    "openrouter": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "OpenRouter",
      "options": {
        "baseURL": "https://openrouter.ai/api/v1",
        "apiKey": "{env:OPENROUTER_API_KEY}"
      },
      "models": {
        "moonshotai/kimi-k2.5": {
          "name": "Kimi K2.5",
          "limit": { "context": 131072, "output": 16384 }
        }
      }
    }
  }
}
```

Swap the `model` and the key in `models` to use any other OpenRouter model — the rest of the config stays identical. Then:

```bash
export OPENROUTER_API_KEY=sk-or-...
./scripts/ralph/ralph.sh --tool opencode 10
```

---

## Agent Personas

Agent personas allow each story (or the whole PRD) to run with a specialist mindset. Personas are loaded from `agency-agents/` and prepended to the base prompt before each iteration.

### Assigning personas in `prd.json`

```json
{
  "agents": ["engineering-software-architect"],
  "userStories": [
    {
      "id": "US-001",
      "agents": ["engineering-frontend-developer"],
      "title": "Build the dashboard UI"
    },
    {
      "id": "US-002",
      "title": "Add API endpoint"
    }
  ]
}
```

Resolution order: `story.agents` → `prd.agents` → no persona (zero regression — stories without agents run exactly as before).

Multiple agents can be listed — their content is concatenated in order.

### Available personas

27 personas across four categories (see [`agency-agents/README.md`](agency-agents/README.md) for full descriptions):

**Engineering (16):** `engineering-software-architect`, `engineering-backend-architect`, `engineering-frontend-developer`, `engineering-senior-developer`, `engineering-ai-engineer`, `engineering-ai-data-remediation-engineer`, `engineering-data-engineer`, `engineering-database-optimizer`, `engineering-devops-automator`, `engineering-security-engineer`, `engineering-mobile-app-builder`, `engineering-code-reviewer`, `engineering-rapid-prototyper`, `engineering-autonomous-optimization-architect`, `engineering-sre`, `engineering-technical-writer`

**Testing (8):** `testing-accessibility-auditor`, `testing-api-tester`, `testing-evidence-collector`, `testing-performance-benchmarker`, `testing-reality-checker`, `testing-test-results-analyzer`, `testing-tool-evaluator`, `testing-workflow-optimizer`

**Product (1):** `product-manager`

**Design (2):** `design-ui-designer`, `design-ux-architect`

---

## Aider Review Gate

After each story implementation, `aider-review.sh` reviews the diff before committing. The review backend is fully independent of the main loop tool — you can run ralph on a local model and review with Gemini, or vice versa.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `SKIP_AIDER_REVIEW` | `0` | Set to `1` to skip entirely |
| `AIDER_REVIEW_MODEL` | *(unset → local)* | Model for review: `gemini/gemini-2.5-pro`, `deepseek/deepseek-chat`, `openai/qwen3-coder-next`, etc. |
| `AIDER_REVIEW_API_BASE` | `$LLM_API_BASE` | Override API base URL for OpenAI-compatible providers |
| `AIDER_REVIEW_API_KEY` | `$LLM_API_KEY` | Override API key |
| `LLM_API_BASE` | `http://localhost:8080/v1` | Local server base URL (used when `AIDER_REVIEW_MODEL` is unset) |
| `LLM_API_KEY` | `dummy` | Local server key (`dummy` works for most local servers) |

### Provider auto-detection

- **`gemini/*`** — uses `GEMINI_API_KEY`, no base URL needed (native litellm support)
- **`deepseek/*` or any other prefix** — uses `AIDER_REVIEW_API_BASE` + `AIDER_REVIEW_API_KEY` (falls through to `OPENAI_BASE_URL` / `OPENAI_API_KEY` if set)
- **Unset** — falls back to local server with health check; skips gracefully if unreachable

### Examples

```bash
# Local LLM review (default — requires server at localhost:8080)
./ralph.sh --tool claude 10

# Gemini review, any main tool
export GEMINI_API_KEY=AIza...
export AIDER_REVIEW_MODEL=gemini/gemini-2.5-pro
./ralph.sh --tool opencode 10

# DeepSeek review
export AIDER_REVIEW_MODEL=deepseek/deepseek-chat
export AIDER_REVIEW_API_BASE=https://api.deepseek.com/v1
export AIDER_REVIEW_API_KEY=sk-...
./ralph.sh --tool claude 10

# Ralph on local model, Gemini review (split setup)
export GEMINI_API_KEY=AIza...
export AIDER_REVIEW_MODEL=gemini/gemini-2.5-pro
./ralph.sh --tool opencode 10   # opencode uses local config; review uses Gemini

# Skip review entirely
SKIP_AIDER_REVIEW=1 ./ralph.sh --tool claude 10
```

---

## Key Files

| File | Purpose |
|------|---------|
| `ralph.sh` | The bash loop that spawns fresh AI instances |
| `CLAUDE.md` | Prompt template for Claude Code |
| `OPENCODE.md` | Prompt template for OpenCode |
| `GEMINI.md` | Prompt template for Gemini CLI |
| `prompt.md` | Prompt template for Amp |
| `AIDER_CODEX.md` | Prompt template for Aider/Codex review loop |
| `aider-review.sh` | Provider-agnostic code review gate |
| `AGENTS.md` | Seed pattern library — copy to your project and customise |
| `prd.json.example` | Example PRD format (includes `agents` fields) |
| `agency-agents/` | 27 specialist agent persona files |

---

## References

- [Original Ralph by Geoffrey Huntley](https://ghuntley.com/ralph/)
- [snarktank/ralph](https://github.com/snarktank/ralph) — upstream repo
- [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) — source of the persona files
- [aider](https://aider.chat)
- [Amp documentation](https://ampcode.com/manual)
- [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code)
- [OpenCode](https://opencode.ai)
- [OpenRouter](https://openrouter.ai)
