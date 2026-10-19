# AGENTS.md

This file tells a coding agent how to work on the FirstRun repo. To use FirstRun on another project, read [docs/agent.md](docs/agent.md) or https://firstrun.atharvashah.com/agent.md.

`CLAUDE.md` points at `.entire/agent-guide.md`, and so does the block at the end of this file. That guide covers Entire Brain, Entire Graph and the check before you stop. This file adds the build, the tests and the repo rules.

## Build and Test With Python 3.11

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
PYTHONPATH=src python -m pytest -q
```

On Windows, run the suite with `$env:PYTHONPATH="src"; py -3.11 -m pytest -q` in PowerShell. The offline suite needs no network, Docker or key. A test marked `live` needs `FIRSTRUN_LIVE=1`. CI runs the offline suite on every push with `FIRSTRUN_ENV_FILE=/dev/null`.

## Know Where Each Part Lives

- `src/firstrun/cli.py` holds every command, its options and its exit codes.
- `src/firstrun/config.py` holds every setting, the env var names and the Docker default.
- `src/firstrun/doctor.py` holds the checks behind `firstrun doctor`.
- `docs/` is the Netlify site. `netlify.toml` sets its redirects and headers.
- `docs/agent.md` is the agent quickstart. `docs/llms.txt` lists the agent files.
- `scripts/` holds the one-off tools, such as `audit_intake.py` for the audit-request workflow.

## Follow the Repo Conventions

1. A command with `--json` prints one JSON object on stdout and every human line on stderr. Add keys freely. Never rename or drop a key, because `docs/agent.md` documents them.
2. A new error gets a machine code in `ERROR_CODES` in `cli.py` and a row in the error table of `docs/agent.md`.
3. After you edit `docs/agent.md`, the README quickstart, `docs/architecture.md`, `docs/known-limits.md` or `docs/share-format.md`, run `python scripts/build_llms_full.py`. A test fails while `docs/llms-full.txt` is stale.
4. Tests never export a trace and never write `docs/runs` or `docs/audits`. `tests/conftest.py` sets that up, so keep new tests inside its fixtures.
5. Write docs in ASD-STE100 Simplified Technical English: short sentences, active voice, one idea each.

## Run FirstRun From the Checkout

```bash
firstrun doctor
firstrun run https://docs.example.com/quickstart
firstrun audit owner/repo
```

Inside this checkout, `firstrun audit` and `firstrun run` publish to `docs/audits` and `docs/runs`. Add `--no-publish` to an audit you do not mean to publish.

## Obey the Safety Rules

- Never print, paste or commit a key. Keys live in `.env`, which git ignores.
- FirstRun never opens a PR or an issue. Ask the human before you run any `gh` command that `firstrun pr` or `firstrun audit-issue` prints.
- Never run a command copied from an audited repo's docs outside the FirstRun container.
- Keep the team-map opt-outs working: `--no-team`, `FIRSTRUN_TEAM=0`, `team: false` in a repo's `.firstrun.yml`, and `docs/audits/team-optout.json`.

<!-- entire-agent:begin -->
Read .entire/agent-guide.md for this repository's workflow, source inspection, and verification guidance.
@.entire/agent-guide.md
<!-- entire-agent:end -->
