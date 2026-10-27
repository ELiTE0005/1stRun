# 1stRun Agent Quickstart

Canonical URL: https://1strun.rajbir.tech/agent.md. Follow the steps in order. Ask the human only where a step says so.

1stRun checks documentation by running it. Doc-test runs a docs quickstart in a clean Docker container, fixes the first step that breaks and proves the fix in a second clean container. Doc-audit reads a GitHub repo's whole git history, code and docs. It ranks stale docs pages and the work to do next, and maps who works on which part of the code. A repo with no docs folder still gets a team map. Every run and every audit can end with a receipt that prices the work and carries a hash you can check.

## 1. Pick the Tool From the Task

| The human gives you | Use | Command |
|---|---|---|
| A docs or quickstart URL | Doc-test | `1stRun run <url> --json` |
| A GitHub repo and a question about its docs, or about who works on which part of its code | Doc-audit | `1stRun audit <owner/repo> --no-publish --json` |
| A public GitHub repo, and no install is allowed | Hosted Doc-audit | Recipe D |
| A question about a run or an audit already on the site | Public data | Recipe E |
| A request for cost or proof of a run or an audit | Receipt | `1stRun receipt <id> --json` |

## 2. Run the Preflight Before You Install

Run these 3 checks. Each one prints a version. A missing tool prints "not found" or "not recognized".

```bash
python3 --version
git --version
docker info --format '{{.ServerVersion}}'
```

On Windows, run these in PowerShell instead. 1stRun calls Docker inside WSL when `docker` is not on PATH.

```powershell
py -3.11 --version
git --version
wsl -d Ubuntu-22.04 docker info --format '{{.ServerVersion}}'
```

- Python must be 3.11 or newer. If it is missing, ask the human to install Python 3.11.
- git must be on PATH. The install and `1stRun audit` both need it. If it is missing, ask the human to install git.
- Docker is needed for Doc-test only. If Docker fails, ask the human to start it, for example with `wsl -d Ubuntu-22.04 sudo service docker start`. Doc-audit works without Docker.
1stRun reads keys from `.env` in the folder you run it from. Set `ONESTRUN_ENV_FILE` to use another file. A key that is already in the environment wins over `.env`. `1stRun doctor` names the file it read in `env_file.path`. For a run with no keys at all, point `ONESTRUN_ENV_FILE` at an empty file.

| Variable | Needed for | Required | Without it |
|---|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Doc-test | Yes, for Doc-test | `1stRun run` stops with exit 2, `auth_missing`. The human creates it with `claude setup-token`. |
| `ONESTRUN_JUDGE` | The judge model in Doc-audit | No | With `CLAUDE_CODE_OAUTH_TOKEN` set, Claude judges, on your subscription. Without it, a local Ollama with `qwen2.5:7b` judges, if it runs. `off`, `claude` or `ollama` forces a choice. With no judge, Doc-audit sorts commits by subject line. |
| `ONESTRUN_JUDGE_CLAUDE_MODEL` | Claude model for the judge | No | The model 1stRun uses elsewhere. |
| `ONESTRUN_JUDGE_BASE_URL`, `ONESTRUN_JUDGE_MODEL`, `ONESTRUN_JUDGE_API_KEY` | An OpenAI-compatible judge endpoint, such as a free cloud tier | No | Setting the URL picks that endpoint over Claude. |
| `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` | Traces in Langfuse | No | A warning on stderr. The run works. |
| `LANGFUSE_BASE_URL` | Langfuse region or self-hosted URL | No | 1stRun uses `https://cloud.langfuse.com`. |
| `GITHUB_TOKEN` or `GH_TOKEN` | Team map logins | No | `gh auth token` is tried. Without any, some people show up twice. |
| `ONESTRUN_DOCKER` | Doc-test | No | 1stRun uses `docker`, or WSL on Windows. |
| `ONESTRUN_ENV_FILE` | Key file path | No | 1stRun reads `./.env`. |
| `ONESTRUN_RUNS_DIR` | Output folder | No | Run folders go to `./runs`. |
| `ONESTRUN_TEAM=0` | Team map opt-out | No | The audit includes the team map. |

Never write a key value yourself. Ask the human to add the line to `.env`, then run the preflight again.

These paths need no key: `1stRun audit <owner/repo> --no-judge`, the hosted audit (Recipe D), the public data (Recipe E) and `1stRun receipt --check`.

## 3. Install 1stRun in a Virtual Environment

The install takes about 3 minutes, because it pulls the Claude Agent SDK and Langfuse.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install git+https://github.com/ELiTE0005/1stRun
1stRun --help
1stRun doctor --json
```

On Windows, run these in PowerShell 7:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install git+https://github.com/ELiTE0005/1stRun
1stRun --help
1stRun doctor --json
```

If `1stRun doctor` is an unknown command, the install is old. Add `--upgrade --force-reinstall` to the pip line.

`1stRun doctor --json` checks Python, git, Docker, each key and the network. It prints whether a key is set, never its value. It exits 0 when Doc-test and Doc-audit can both run. Gate an audit-only task with `--for audit` and a Doc-test task with `--for test`. Read `can_run` and apply the `fix` of each check with `"status": "fail"`. A `net_*` check that fails once can be a slow network, so run `1stRun doctor` again before you report it.
## 4. Run the Recipe That Matches the Task

Every `--json` command prints one JSON object on stdout. Progress lines go to stderr. Parse stdout only, and read the exit code from its `exit_code` key. Windows PowerShell 5.1 writes UTF-16 with `>`, so use PowerShell 7 or `| Out-File -Encoding utf8` there. Paths in the JSON are absolute. Run and audit ids start with the UTC start time.

**A. Test a docs URL.** Give the tool call a timeout of 30 minutes, because each step may run for up to 5 minutes.

```bash
1stRun run https://docs.example.com/quickstart --json > result.json
```

A URL tested in the last 24 hours returns the saved result with `"cached": true`. Add `--fresh` to run it again. Read `runs[0].status`, then `runs[0].files["report.md"]`. A stopped run resumes with `1stRun run --resume <run_id> --json`.

**B. Audit a repo.** `--no-publish` keeps the audit on your disk. The fastapi/typer audit took 97 seconds on 2026-10-11. A large docs set takes much longer: dbt-core with its docs repo ran for more than 30 minutes on Windows. Run a large audit as a background job, or use the hosted audit in Recipe D.

```bash
1stRun audit fastapi/typer --no-publish --json > audit-result.json
```

```bash
1stRun audit dbt-labs/dbt-core --docs-repo dbt-labs/docs.getdbt.com --no-publish --json > audit-result.json
```

- `--docs-repo` reads the docs from a second repo.
- `--no-judge` makes no model call. Use it for a fast run with no judge. Then `judge` is false and `stale` comes from text matching alone, so it can count too many pages.
- With a judge model, a candidate page that the judge did not read shows as `unchecked`. `cost.judge_usd` is Claude's list price, not billed, or 0 for a local model.
- `--no-team` leaves out people.

Read `top_tasks` for the ranked work list. It holds up to 10 tasks and can hold fewer. When the human asks for more tasks than exist, report the real count and say that the audit ranked no more. Each task has `rank`, `title`, `score` from 0 to 100, `effort` of S, M or L, `action` and `owner`. `owner` is null when no person stands out. Present an owner to the human as a suggestion, because anyone can take any task.

To draft a GitHub issue for the docs team, run `1stRun audit-issue <audit_id> --json`. It writes `issue.md` to `body_file` and returns the `gh` command in `commands`. It opens nothing. The command targets the audited repo, so section 8 applies.

**C. Turn a verified run into a docs PR.** Run `1stRun pr <run_id> --json`. It prints the repo, the diff, the PR body and the `gh` commands. It opens nothing. Follow the safety rules in section 8 before you run any of those commands.

**D. Ask for a hosted audit without an install.** This works for a public GitHub repo only. Give the human this link with OWNER/REPO filled in, and ask the human to click Submit new issue:

```text
https://github.com/ELiTE0005/1stRun/issues/new?template=audit-request.yml&title=Audit+request%3A+OWNER%2FREPO&repo=OWNER%2FREPO
```

A GitHub Action audits the repo in about 2 minutes and comments the board link on the issue. The board opens at `https://1strun.rajbir.tech/doc-audit/?id=<audit_id>` about 1 minute after the comment. Find the id in `audits/index.json` by `repo`, as in Recipe E. A form that ticks "Leave out the team map" gets a board with no people.

**E. Read the public data.** These files are plain JSON, so any HTTP client reads them. Use `https://1strun.rajbir.tech/` as the base URL.

| Path | Holds |
|---|---|
| `audits/index.json` | `audits[]`: one row per audit with `id`, `repo`, `ts`, `pages`, `stale`, `quiet`, `uncovered`, `cards`, `receipt`, `receipt_usd` |
| `audits/<audit_id>.json` | One full board: `summary`, `pages[]`, `cards[]`, `next.items[]` (the ranked tasks), `team.people[]`, `drafts`, `cost` |
| `runs/index.json` | `runs[]`: one row per Doc-test run with `id`, `url`, `status`, `passed`, `total`, `fixes`, `seconds`, `cost`, `fixture`, `receipt`. A `fixture: true` row tests a known-broken sample page, not a real product, so leave it out of counts about real docs. |
| `runs/<run_id>.txt` | The run as a share code: base64url of gzip of JSON, fields in `share-format.md` |
| `receipts/<receipt_id>.json` | `work`, `price`, `caps` (runs) or `limits` (audits), `proof`, `hash` |

Rows can carry more keys than the table lists. In `next.items[]`, `owner.p` is the `id` of a person in `team.people[]`. Decode a run share code with this command:

```bash
curl -s https://1strun.rajbir.tech/runs/20261010-174858-docs-litestar-dev.txt | python3 -c "import sys,gzip,base64,json;c=sys.stdin.read().strip();print(json.dumps(json.loads(gzip.decompress(base64.urlsafe_b64decode(c+'='*(-len(c)%4)))),indent=1))"
```

**F. Make and check a receipt.** An audit receipt needs nothing more. A run receipt needs the price table in `business/unit_economics.json` beside your working folder. Set `ONESTRUN_BUSINESS_DIR` to use another folder.

```bash
mkdir -p business && curl -sSfo business/unit_economics.json https://raw.githubusercontent.com/ELiTE0005/1stRun/main/business/unit_economics.json
1stRun receipt <run_id or audit_id> --json
1stRun receipt --check runs/<id>/receipt.json --json
```

`--check` exits 0 when the receipt hash and every evidence file match. A receipt from `receipts/` on the site has no run or audit files beside it. Save it in an empty folder and add `--hash-only`, which checks the receipt hash alone:

```bash
mkdir -p site-receipt && curl -sSfo site-receipt/receipt.json https://1strun.rajbir.tech/receipts/FR-audit-20261010-163257-fastapi-typer.json
1stRun receipt --check site-receipt/receipt.json --hash-only --json
```

## 5. Read the Result From the Status and the Files

| Run status | Meaning |
|---|---|
| `passed` | Every step passed as written. Nothing was patched. |
| `verified` | A step broke, 1stRun patched it, and a second clean container passed every step with no model calls. |
| `unverified` | 1stRun patched a step, but the second clean container did not pass. Treat the patch as unproven. |
| `failed` | A step gave up, a budget ran out, or the run stopped before step 1. Read `error.code`. |
| `running` or `verifying` | The run has not finished, or it stopped without a final write. Resume it or ignore it. |

| File in the run folder | Holds |
|---|---|
| `report.md` | The human summary: steps, the failed step, the class, the fix and the proof. Read it first. |
| `state.json` | Machine state after every step: `status`, `step_status`, `results`, `patches`, `usage`. |
| `runbook.json` | The planned steps and the docs text the planner read. |
| `patch.diff` and `pr_body.md` | Only for a `verified` docs fix. The diff of the docs page and a PR body. |
| `audit.json` and `audit.md` | Doc-audit output in `runs/<audit_id>/`. Page statuses are `stale`, `unchecked`, `quiet`, `aging` and `fresh`. |
| `receipt.json` and `receipt.md` | Written by `1stRun receipt`. |

## 6. Parse the JSON by Its Stable Keys

Every `--json` object has `ok`, `command`, `exit_code` and `error`. `error` is null or `{"code", "message", "fix"}`. New keys may appear. Existing keys keep their names.

- **`run`** adds `runs[]`. Each run has `run_id`, `source_url`, `target`, `status`, `stop_reason`, `cached`, `steps_total`, `steps_passed`, `first_failed_step`, `reported_failed_step`, `patches`, `verified`, `time_to_first_success_s`, `elapsed_s`, `cost_usd`, `run_dir`, `share_url`, `error` and `files`. `files` maps `state.json`, `runbook.json`, `report.md`, `patch.diff`, `pr_body.md` and `receipt.json` to a path or null.
- **`audit`** adds `audit_id`, `repo`, `url`, `docs_repo`, `mode`, `summary`, `judge`, `cost`, `team`, `top_tasks[]`, `run_dir`, `files` and `published`. `summary` counts `pages`, `fresh`, `aging`, `stale`, `quiet` and `unchecked`, plus `ancient` (pages 730 days old or older, also counted under their status), `median_age_days`, `oldest_days`, `features`, `uncovered` and `cards`. A task has `rank`, `kind`, `title`, `path`, `score`, `effort`, `action`, `rationale` and `owner` (`{"name", "login", "why"}` or null).
- **`receipt`** adds `mode`. With `"mode": "write"` it adds `receipt_id`, `kind`, `hash`, `price_usd`, `price_basis`, `verified`, `cards`, `cards_citing_evidence` and `files`. With `"mode": "check"` it adds `path`, `valid`, `hash_ok`, `hash_only` and `problems[]`.
- **`prereqs`** adds `run_id`, `prereqs`, `proof` and `files`.
- **`doctor`** adds `env_file`, `docker_cmd`, `can_run` and `checks[]`. A check has `name`, `status` (`pass`, `warn` or `fail`), `required_for`, `detail` and `fix`.

## 7. Map Each Exit Code and Error Code to a Fix

| Command | Exit 0 | Exit 1 | Exit 2 |
|---|---|---|---|
| `run` | `passed`, `verified` or `unverified`, or a cached result | A step failed | Setup failed or the run stopped before step 1. Also a bad option. |
| `audit`, `receipt`, `prereqs`, `audit-issue`, `pr` | Done | An error. Read `error.code`. | A bad option |
| `receipt --check` | Receipt and files match | A mismatch or a missing file | A bad option |
| `doctor` | The chosen tools can run | A required check failed | A bad option |

| `error.code` | Cause | Fix |
|---|---|---|
| `auth_missing` | `CLAUDE_CODE_OAUTH_TOKEN` is not set or expired. | Ask the human to run `claude setup-token` and add the token to `.env`. |
| `docker_unavailable` | Docker is not running or not installed. | Ask the human to start Docker, or set `ONESTRUN_DOCKER`. |
| `docs_unreachable` | The URL answered 401, 403, 404, 410 or 5xx, or the network failed. Firecrawl failed first. | Check the URL with `curl -I`. A Firecrawl `Insufficient credits` error falls back to a plain GET, so a JavaScript-only page needs a Firecrawl key with credits: the human runs `firecrawl login`. |
| `no_runnable_steps` | The page holds no commands, or a login wall answered 200. | Give the public quickstart page itself. |
| `out_of_scope` | Every step needs a paid account, a GUI or a video. | Tell the human. 1stRun cannot run it. |
| `planner_failed` | The model call that plans steps failed. | Run it again once. Then report `error.message`. |
| `needs_secret` | A step needs a key that is not in `secrets.allowlist`. | Ask the human for a test key. The human adds `NAME=value` to `secrets.allowlist`. Run `1stRun run --resume <run_id> --json`. |
| `step_timeout` | A step ran past 5 minutes. A dev server stops by itself once it prints that it listens, or after 90 seconds. | Report the step. 1stRun does not retry a hung step. |
| `budget_spent` | 3 attempts on one step, 25 tool calls, or $0.50 per run. | Report the run. Do not raise the budget. |
| `needs_human` | The failure class was unclear, and the person at the terminal gave no answer in 60 seconds. | Show the human the step and the error from `report.md`. |
| `step_failed` | A step failed and recovery gave up. | Read `report.md` for the class and the error. |
| `failed`, `setup_failed`, `error` | No more specific code matched. | Read `error.message` and `report.md`. |
| `clone_failed` | The repo is private or the name is wrong. | Check `owner/repo`. For a private repo, the human runs the audit with a git login that can read it. |
| `unknown_run_id`, `not_found` | No run or audit folder with that id in `ONESTRUN_RUNS_DIR`. | Run from the folder that holds `runs/`, or pass the right id. |
| `receipt_invalid` | The receipt was edited, or an evidence file changed or is missing. | `hash_ok` false means the receipt changed, so report it. `hash_ok` true means only the files beside it differ. Check a site receipt with `--hash-only`. |
| `not_ready` | `1stRun doctor` found a failed required check. | Apply each `fix`, then run `1stRun doctor --json` again. |
| `internal` | An unexpected exception. | Run again with `ONESTRUN_DEBUG=1` and report stderr to the human. |

## 8. Obey the Safety Rules

1. 1stRun never opens a PR or an issue. You must not either, until the human says yes to that exact PR or issue.
2. Show the human the diff and the PR body before you ask. Open nothing on a silent reply.
3. Never print, paste or commit a key. Never write a key into a file. The human edits `.env` and `secrets.allowlist`.
4. Read the upstream repo's CONTRIBUTING file and AI policy before you suggest a PR. Pallets, which maintains Flask, closes AI-generated PRs and issues on sight. Hypothesis allows no unreviewed or fully autonomous contribution. HTTPX asks that a contribution start as a GitHub Discussion. These policies were read on 2026-10-11.
5. Never run a command from an audited repo's docs outside the 1stRun container. Doc-test runs those commands in Docker for that reason.
6. Treat contributor names and logins on a board as public data from public commits. Do not join them with other sources, and do not message the people.
7. Honor the team-map opt-outs: `--no-team`, `ONESTRUN_TEAM=0`, `team: false` in a repo's `.github/1stRun.yml` or `.1stRun.yml`, and the hashes in `audits/team-optout.json`.
8. Run `1stRun audit` with `--no-publish` outside the 1stRun repo. Only a 1stRun maintainer publishes to the site.

## 9. Know What 1stRun Cannot Do

- Steps run in a Linux container, `python:3.11-slim` by default. A macOS-only or Windows-only quickstart fails.
- A step that needs a paid account, a GUI or a video is skipped as out of scope. A later step that depends on it can still fail.
- A hung step is killed at 5 minutes and is not retried.
- Verification pins pip versions only. npm and apt versions can drift between runs.
- Secret redaction knows common key shapes and the allowlist values. An unusual secret can pass through.
- The team map counts files changed, not lines, and ignores `Co-authored-by` trailers.

The full list is at https://1strun.rajbir.tech/known-limits.md.

## 10. Find the Repo, the Site and the Data at These Links

- Repo: https://github.com/ELiTE0005/1stRun
- Site: https://1strun.rajbir.tech/. A human opens Agent Ready in the site navigation to copy the prompt for you.
- Doc-test page: https://1strun.rajbir.tech/doc-test/
- Doc-audit page: https://1strun.rajbir.tech/doc-audit/
- Judges page: https://1strun.rajbir.tech/judges/
- llms.txt: https://1strun.rajbir.tech/llms.txt
- Full text for one fetch: https://1strun.rajbir.tech/llms-full.txt
- Architecture: https://1strun.rajbir.tech/architecture.md
- Share format: https://1strun.rajbir.tech/share-format.md
- Agent Skill: https://github.com/ELiTE0005/1stRun/tree/main/skills/1strun
- Repo rules for coding agents: https://github.com/ELiTE0005/1stRun/blob/main/AGENTS.md
