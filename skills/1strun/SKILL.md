---
name: 1strun
description: Test a docs quickstart by running it in a clean Docker container, or audit a GitHub repo's docs for stale pages and missing docs, with the 1stRun CLI. Use when the user asks to test, check or verify a quickstart, a getting-started page, an install guide or a README, asks whether the docs still work, asks which docs pages are stale or out of date, asks for the docs work to do next or who should own it, or asks for a 1stRun receipt, run or audit board.
---

# 1stRun

1stRun checks docs by running them. Doc-test runs a quickstart URL in a clean container, patches the first step that breaks and proves the patch in a second clean container. Doc-audit reads a repo's git history and ranks stale pages and docs tasks. The full guide is https://1strun.rajbir.tech/agent.md. Fetch it when a step below is not enough.

## Pick the Command That Matches the Input

| The user gives you | Run |
|---|---|
| A docs or quickstart URL | `1stRun run <url> --json` |
| A GitHub repo | `1stRun audit <owner/repo> --no-publish --json` |
| A repo whose docs live in a second repo | `1stRun audit <owner/repo> --docs-repo <owner/docs-repo> --no-publish --json` |
| A run id or an audit id | `1stRun receipt <id> --json` |

## Check the Machine, Then Install

```bash
python3 --version
git --version
python3 -m venv .venv
. .venv/bin/activate
pip install git+https://github.com/ELiTE0005/1stRun
1stRun doctor --json
```

- Python must be 3.11 or newer, and git must be on PATH.
- On Windows, use `py -3.11 -m venv .venv` and `.venv\Scripts\Activate.ps1` in PowerShell 7.
- The install takes about 3 minutes.
- Read `can_run.doc_test` and `can_run.doc_audit` from the doctor output. Use `--for audit` for an audit-only task. Run doctor again once if a `net_*` check fails. Apply the `fix` of each check with `"status": "fail"`.
- Doc-test needs Docker and `CLAUDE_CODE_OAUTH_TOKEN`. The human creates the token with `claude setup-token` and adds it to `.env`.
- Doc-audit needs no key. Add `--no-jev` when `TYPESAFE_API_KEY` is not set.
- If `1stRun doctor` is an unknown command, add `--upgrade --force-reinstall` to the pip line.

## Read the Result From One JSON Object

Parse stdout only. It holds one JSON object with `ok`, `command`, `exit_code` and `error`, where `error` is null or `{"code", "message", "fix"}`.

- **Doc-test:** read `runs[0].status`. `passed` means every step worked as written. `verified` means 1stRun patched a step and a second clean container passed. `unverified` means the patch did not pass. `failed` means read `error.code` and `runs[0].files["report.md"]`.
- **Doc-audit:** read `top_tasks[]`. It holds up to 10 tasks and can hold fewer, so report the real count. Each task has `rank`, `title`, `score`, `effort`, `action` and `owner`. An owner is `{"name", "login", "why"}` or null. Present the owner as a suggestion.
- **Exit codes:** 0 means done, 1 means a step failed or the command hit an error, and 2 means setup failed before step 1.

Give the tool call a timeout of 30 minutes for `1stRun run`. A small repo audits in about 2 minutes. A large docs set can run past 30 minutes, so run it as a background job.

## Obey the Safety Rules

1. Ask the human before you open any PR or issue. 1stRun opens nothing.
2. Never print, paste or write a key. The human edits `.env`.
3. Read the target repo's contribution rules and AI policy before you suggest a PR. Flask's maintainers close AI-generated PRs on sight.
4. Never run a command from the audited docs outside the 1stRun container.
5. Treat names on a board as public commit data. Leave people out when the user passes `--no-team` or sets `ONESTRUN_TEAM=0`.
