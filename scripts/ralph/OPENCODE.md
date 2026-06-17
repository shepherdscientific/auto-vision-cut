# OpenCode Agent Instructions — AutoVisionCut

> **Permissions note:** OpenCode prompts for tool permissions interactively by default.
> The repo's `opencode.json` already sets `"permission": { "read": "allow", "write": "allow", "bash": "allow" }`
> so the loop runs unattended.

You are operating in an autonomous Ralph Loop on **AutoVisionCut**, a local
video auto-editing pipeline (Python 3.10+, MLX, ffmpeg, MoviePy). Move the
project forward by exactly ONE user story per iteration.

## 1. Context Initialization
- Read `prd.json` (repo root) and pick the highest-priority story where `passes: false`.
- Read `scripts/ralph/AGENTS.md` for project patterns and rules.
- Read ONLY the `## Codebase Patterns` section of `progress.txt` (it grows unboundedly).
- Check `git log -n 5` for recent changes.

## 2. Implementation Phase
- Work on ONLY the selected story; keep changes focused and minimal.
- Use `edit`, `write`, and `bash` to implement and test. Patch — do not rewrite whole files.
- Reuse the existing `src/autovideo/` modules (config, logging, retry, resume) and follow their patterns.

## 3. Quality Gate (all must pass before commit)
- Activate the venv: `source .venv/bin/activate` (a `venv/` also exists).
- Typecheck: `mypy .`
- Lint: `ruff check .`
- Test: `pytest -m "not slow and not integration"` for the fast loop; run the full `pytest` when the story touches the pipeline end-to-end.
- **Mandatory review:** run `./scripts/ralph/aider-review.sh`. Apply every fix marked "Critical".

## 4. Commit
```bash
git add -A
git commit -m "feat(US-XXX): brief description"
```

## 5. State Update (use jq — never hand-edit prd.json)
- Mark the story done:
  `jq '(.userStories[] | select(.id=="US-XXX") | .passes)=true' prd.json > /tmp/prd.json && mv /tmp/prd.json prd.json`
- Append a short entry to `progress.txt` (what changed, files, learnings).
- If you found a reusable pattern, append it to `scripts/ralph/AGENTS.md` (never rewrite it).

## 6. Exit
- If ALL stories in `prd.json` have `passes: true`, reply with: <promise>COMPLETE</promise>
- Otherwise state the story is finished and exit (the next iteration continues).
