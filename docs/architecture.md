# Architecture

FirstRun turns a docs page into a runbook, runs it in Docker, and repairs the first step that breaks. A second run with no model calls proves the repair.

## A Run Moves Through Six Statuses

| Status | Meaning |
|---|---|
| `running` | Steps are executing. |
| `passed` | Every step passed and verification has not run. |
| `failed` | A step gave up or a budget tripped. |
| `verifying` | The model-free re-run is in progress. |
| `verified` | The re-run passed with the patches applied. |
| `unverified` | The re-run did not pass. |

A clean pass with no patch ends as `passed`, because nothing needs verifying.

Each step has its own status: `pending`, `running`, `passed`, `failed`, `recovering`, `gave_up`, `skipped` and `needs_human`. FirstRun writes `state.json` after every step, so `--resume RUN_ID` continues a stopped run.

## Four Failure Classes Decide What Recovery Does

`classify_failure` returns a probability for each class.

| Class | Cause | Recovery |
|---|---|---|
| `docs_bug` | The docs are wrong. A package was renamed, a flag was removed or a version moved. | Search for the current form and patch the step. |
| `environment` | The container lacks something the docs assume, such as `curl`. | Retry once on a network drop. Otherwise install the missing package and run the step again. |
| `product_bug` | The product itself is broken. | Give up and report the error. A docs patch cannot fix it. |
| `needs_secret` | The step needs a key FirstRun does not have. | Inject the value from the secrets allowlist. Give up if the name is not on it. |

Jev (TypeSafe System One) returns the probabilities. If Jev fails, Claude classifies instead. When the top class is below 0.7, FirstRun asks one question at the terminal and stores the answer in `precedents.json`. The same failure never asks twice. With no terminal, FirstRun uses the top class. A person who stays silent for 60 seconds gets `needs_human`.

## Hard Budgets Stop a Runaway Run

The `budget` span checks these limits before every recovery.

| Budget | Limit |
|---|---|
| Attempts per step | 3 |
| Tool calls per run | 25 |
| Cost per run | $0.50 |
| Time per step | 5 min |

A tripped budget ends the run as `failed` and marks the span as an error.

## Verification Cannot Call a Model

`verify` starts a new container and replays the stored commands with the patches applied. It runs inside `block_model_calls()`, so a Claude or Jev call raises `ModelCallBlocked`. The agent cannot talk its way to a pass. Pip versions are pinned from the first run, so a new release does not change the result.

## Every Box in the Flow Is a Span

| Span | Kind | Holds |
|---|---|---|
| `firstrun.run` | WORKFLOW | Input: url, run id, tags. Output: final status, stop reason, step and patch counts. |
| `read_docs` | TOOL | Input: the URL. Output: the markdown. |
| `planner` | AGENT | The runbook. Child spans: `claude_agent.query` and its LLM calls. |
| `step.N` | TOOL | Input: the command. Output: exit code and the last 2,000 characters of stdout and stderr. ERROR when the step fails. |
| `classify_failure` | TOOL | Input: the error text. Output: probabilities and the source (`jev`, `claude` or a precedent). |
| `recover.N` | AGENT | The search, the patch and the retry. |
| `budget` | GUARDRAIL | Input: attempts and cost. Output: passed and the reason. |
| `verify` | GUARDRAIL | Child `step.N` spans and the per-step results. |

Jev is not an SDK-wrapped provider, so it appears as the `classify_failure` TOOL span with `source: jev`.

## Outputs Land in One Run Folder

`runs/<run-id>/` holds `state.json`, `runbook.json`, `report.md`, and for a repaired run `patch.diff` and `pr_body.md`. Secrets are redacted before anything is written. `firstrun report --html` reads every run folder and writes `report/index.html`.
