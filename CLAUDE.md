# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

FirstRun is a Python 3.11 CLI (`firstrun`) that checks documentation by running it. **Doc-test** turns a quickstart page into a runbook, runs it in a clean Docker container, repairs the first step that breaks, then proves the repair with a second model-free run. **Doc-audit** reads a repo's history and lists stale docs pages and undocumented features. Every run and audit ends with a receipt (cost, plan-tier cap, proof). `docs/` is also the static Netlify site (no build step).

`AGENTS.md` is the fuller contributor guide and `docs/agent.md` is the guide for using FirstRun on *other* projects. This file does not repeat them in full.

## Commands

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
PYTHONPATH=src python -m pytest -q                          # offline suite: no network, Docker or key
PYTHONPATH=src python -m pytest tests/test_verify.py -q     # one file
PYTHONPATH=src python -m pytest tests/test_verify.py::test_name -q   # one test
FIRSTRUN_LIVE=1 python -m pytest -q                         # also run tests marked `live` (need Docker/model/network)
python scripts/build_llms_full.py                           # regenerate docs/llms-full.txt
```

On Windows PowerShell: `$env:PYTHONPATH="src"; py -3.11 -m pytest -q`. CI runs `python -m pytest -q -p no:cacheprovider` with `FIRSTRUN_NO_EXPORT=1 FIRSTRUN_ENV_FILE=/dev/null`. There is no linter configured.

Running the tool itself (needs Docker, plus keys in `.env`: `CLAUDE_CODE_OAUTH_TOKEN`, optionally `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL`, `TYPESAFE_API_KEY`, `FIRECRAWL_API_KEY_1`):

```bash
firstrun doctor                              # checks Docker, keys, auth
firstrun run <docs-url> [--offline] [--no-verify] [--no-recover] [--resume RUN_ID] [--tier T] [--json]
firstrun audit owner/repo [--no-publish]
```

Inside this checkout, `run` and `audit` publish to `docs/runs` and `docs/audits` (the public site log); pass `--no-publish` for audits you do not mean to publish.

## Architecture

All code is in `src/firstrun/`; `cli.py` is the single Click entry point (`firstrun.cli:main`) and holds every command and exit code.

**Doc-test pipeline** (see `docs/architecture.md` for the span/budget tables):
`docs_source` / `planner` (page → `Runbook` of steps, via Claude Agent SDK) → `executor` + `sandbox` (steps run in one fresh Docker container per run, sharing one bash session that persists env and cwd between steps) → on failure `classify` (Jev from TypeSafe returns class probabilities, Claude is the fallback; classes `docs_bug` / `environment` / `product_bug` / `needs_secret`) → `recovery` (search, patch, retry) with `budget` limits (3 attempts/step, 25 tool calls, $0.50, 5 min/step) → `patch` → `verify` (new container, replays stored commands with patches, **inside `block_model_calls()`** so no model call can occur) → `report` / `receipt` / `pr` / `share` / `publish`. State is written to `runs/<run-id>/state.json` after every step, which is what `--resume` reads. `precedents.json` remembers human answers to low-confidence classifications.

**Doc-audit**: `audit.py` (git-history analysis), `team.py` (team map), `bisect.py`, `nextup.py`, `prereqs.py`, `intake.py` (audit-request issue workflow, driven by `scripts/audit_intake.py` and `.github/workflows/`).

**Cross-cutting**:
- `config.py` is the only place that names the model, env vars, paths or Docker command (on Windows without `docker`, it falls back to `wsl -d Ubuntu-22.04 docker`). It also holds author-machine paths (`D:\Atharva\...`) that are skipped when absent.
- `tracing.py` is the only module that imports Langfuse. Everything else calls its facade (`trace`, `span`, `log`, `annotate`, `set_io`, `mark_error`), and each run is one Langfuse trace. With no keys or `FIRSTRUN_NO_EXPORT=1` every call is a no-op. `init_tracing` also patches `claude_agent_sdk.query` with the OpenInference instrumentor, so `llm.py` needs no wrapping. The Agent SDK must use the subscription OAuth token, never an API key.
- `redact.py` strips secrets before anything is written to disk.
- `econ.py` / `receipt.py` price runs against `business/unit_economics.json` (the cfo.ai model).

## Conventions That Bite

- A command with `--json` prints exactly one JSON object on stdout and all human text on stderr. Add keys freely; never rename or drop one (`docs/agent.md` documents them).
- A new error needs a machine code in `ERROR_CODES` in `cli.py` (first fragment match wins, so order matters) **and** a row in the error table of `docs/agent.md`.
- After editing `docs/agent.md`, the README quickstart, `docs/architecture.md`, `docs/known-limits.md` or `docs/share-format.md`, run `python scripts/build_llms_full.py`; a test fails while `docs/llms-full.txt` is stale.
- `tests/conftest.py` disables trace export, blanks the Langfuse/Firecrawl keys and points `FIRSTRUN_SITE_DIR` at a missing folder so tests never publish. Keep new tests inside its fixtures (`load_doc`, `load_runbook`, etc.; fixtures live in `tests/fixtures/`).
- Docs are written in ASD-STE100 Simplified Technical English: short, active, one idea per sentence. `PRODUCT.md` defines the site's brand and design rules.
- Never print or commit keys (`.env` is git-ignored). FirstRun never opens PRs or issues itself; ask before running any `gh` command that `firstrun pr` / `firstrun audit-issue` prints. Never run a command from an audited repo's docs outside the FirstRun container. Keep the team-map opt-outs working (`--no-team`, `FIRSTRUN_TEAM=0`, `team: false` in `.firstrun.yml`, `docs/audits/team-optout.json`).
- `.claude/launch.json` contains static-server configs with the author's `D:/Atharva/...` paths; `python -m http.server <port> --directory docs` serves the site locally.

<!-- entire-agent:begin -->
Read .entire/agent-guide.md for this repository's workflow, source inspection, and verification guidance.
@.entire/agent-guide.md
<!-- entire-agent:end -->
