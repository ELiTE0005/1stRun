# 1stRun

Docs that work. Literally.

1stRun runs a quickstart in a clean container, finds the first step that breaks, and proves the fix with a second clean run.

**The problem:** quickstarts break when a package is renamed, a flag is removed or a version moves. Nobody on the team gets an alert. The first person who finds the break is a new user, and most new users leave.

## What It Does

- **Doc-test** reads a docs page, turns it into a list of shell steps, and runs them in a fresh Docker container. When a step fails, it classifies the failure, repairs the docs step, and replays the repaired steps in a second clean container with model calls blocked. The agent cannot talk its way to a pass.
- **Doc-audit** reads a repo's git history and lists the docs pages that went stale and the shipped features that have no docs. It ranks the results into a short list of tasks.
- **Receipts** close every run and audit: what it cost at list price, the tier cap it sits under, and the proof that it passed.

Every run is one trace in Langfuse when keys are set.

## What It Uses

| Piece | Used for | Needed? |
|---|---|---|
| Claude, through the Claude Agent SDK and a `CLAUDE_CODE_OAUTH_TOKEN` | Planning, repair, failure classification, and the Doc-audit judge | Yes, for Doc-test |
| Docker | One clean container per Doc-test run | Yes, for Doc-test |
| git | Cloning history for Doc-audit | Yes |
| [Langfuse](https://langfuse.com) | One trace per run | No. With no keys, tracing is off. |
| [Ollama](https://ollama.com) with `qwen2.5:7b` | Backup failure classifier. The judge when no Claude token is set. | No |
| Firecrawl CLI | A better docs-to-markdown reader | No. 1stRun falls back to plain HTTP. |
| `GITHUB_TOKEN` or `gh` | Matches commit authors to GitHub logins in the team map | No |

1stRun does not use Neatlogs, TypeSafe, Entire or cfo.ai.

## Run Your First Check in 5 Minutes

You need:

- Python 3.11 or newer.
- Git.
- Docker, running. On Windows, 1stRun uses `docker` from your `PATH`, or Docker inside WSL with `wsl -d Ubuntu-22.04 docker`. Set `ONESTRUN_DOCKER` to use another command.
- A Claude subscription token in `CLAUDE_CODE_OAUTH_TOKEN`. Create one with `claude setup-token`.

Install from a clone of this repo:

```bash
pip install -e .
```

1stRun reads keys from `.env` in the folder you run it from. Copy the names you need from the table below. To use another file, set `ONESTRUN_ENV_FILE`.

Check your setup. `1stRun doctor` prints one line for each tool and key, and never prints a key value:

```bash
1stRun doctor
```

Run it on a quickstart URL:

```bash
1stRun run https://www.mkdocs.org/getting-started/
```

In testing, this page ended `verified 9/10` steps in about a minute for about $0.03 at list price. One step is skipped because it starts a dev server that needs a browser.

A URL tested in the last 24 hours returns the cached result. Add `--fresh` to run it again.

Read the result in `runs/<run-id>/report.md`. Build the HTML report with `1stRun report --html`.

## Settings

| Variable | Does |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude access. Required for Doc-test. |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | Turn on tracing. The base URL defaults to `https://cloud.langfuse.com`. Use `https://us.cloud.langfuse.com` for the US region. |
| `ONESTRUN_JUDGE` | `off`, `claude` or `ollama`. Unset: Claude if a token is set, else a local Ollama. |
| `ONESTRUN_JUDGE_BASE_URL`, `ONESTRUN_JUDGE_MODEL`, `ONESTRUN_JUDGE_API_KEY` | Use any OpenAI-compatible endpoint as the judge. |
| `ONESTRUN_JUDGE_CLAUDE_MODEL` | Use a different Claude model for the judge. |
| `ONESTRUN_NO_EXPORT=1` | Keep tracing off even when keys are set. |
| `ONESTRUN_DOCKER`, `ONESTRUN_ENV_FILE`, `ONESTRUN_RUNS_DIR` | Docker command, key file, and output folder. |

[docs/agent.md](docs/agent.md) lists every command, `--json` key and exit code.

## Doc-audit

```bash
1stRun audit owner/repo
```

The audit clones the history without a checkout, so it works offline after that. With a judge, Claude reads each stale candidate page and each new feature next to the closest docs page and keeps only the real gaps. Without one, 1stRun sorts commits by their subject line and text matching alone can over-count stale pages. Add `--no-judge` to skip the judge, and `--no-publish` to keep the result out of `docs/audits`.

## Tests

The offline suite needs no network, Docker or keys:

```bash
pip install -e ".[dev]"
PYTHONPATH=src python -m pytest -q
```

Some git tests need `commit.gpgsign` off in your git config. See [AGENTS.md](AGENTS.md) for the repo rules and [CLAUDE.md](CLAUDE.md) for how the code fits together. [docs/architecture.md](docs/architecture.md) has the statuses, budgets and spans.
