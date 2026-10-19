# neatlogs Evidence

Every FirstRun run is one `firstrun.run` WORKFLOW trace in neatlogs. Its spans are `read_docs` and `step.<id>` (TOOL), `planner` and `recover.<id>` (AGENT), `classify_failure` (TOOL), and `budget` and `verify` (GUARDRAIL). Bisect adds `firstrun.bisect` with a `probe.<version>` span per release. Prerequisite Proof adds a `prereqs.prove` GUARDRAIL.

## Before and After Traces Measure the Fix From Neatlogs

| Target | v1 trace | v2 trace |
|---|---|---|
| neatlogs Python SDK | `fccdbad9a9c6177b90112911fe485bd6` | `495d510fd6da5546dbc6ab6e52bcee68` |
| Entire install | `10c44df9626c19f5ac801f1c6d84610e` | `5520c5cff5e0ea61f130eced082b20c4` |
| Chroma getting started | `66ec093b00333fa221fade5d2fc5f55f` | `f63d2b842c2257ae8c340f6ce44e3848` |
| OpenAI v0 README (fixture) | `b98b419e286acf436083febdb5217cf9` | `78e538e63a65c5d00d0281effa119567` |

Per-trace spans, tool calls, cost and duration are in [before_after_traces.json](before_after_traces.json). The tag summaries are in [neatlogs_runs.json](neatlogs_runs.json).

## One Failed-and-Recovered Trace, Exported

[trace-recovered-entire-v2.md](trace-recovered-entire-v2.md) is trace `5520c5cff5e0ea61f130eced082b20c4`. Step 1 failed with `curl: command not found`, recovery installed curl in the container, step 2 failed until `~/.local/bin` was on `PATH`, and a fresh container then ran all 4 steps with no model calls. The trace status reads ERROR because a failed step span rolls up to the trace, while the run itself ended `verified`.

## Two Detections, One Investigate, One Fix Over MCP

1. Detection "docs step broke": a regex on TOOL span output, `command not found|No module named|unrecognized arguments|No matching distribution`.
2. Detection "planner invented a step": a regex on the `planner` span output. It flagged the planner spans of the Chroma, Entire and OpenAI v1 runs.
3. Investigate (Deep, workflow `firstrun`) traced the invented steps to the planner prompt: [neatlogs-investigation.md](neatlogs-investigation.md).
4. A Claude Code session read the detection and its trend over the neatlogs MCP server and applied the fix in commit `3ca6f11`.

## Three Alerts and One AI Evaluator Watch Every Run

Created over the neatlogs CLI on 2026-10-10. Each alert passed a dry-run test with email as the channel.

| Rule | Fires when | ID |
|---|---|---|
| firstrun p95 run cost above Scale cap | p95 `cost` is above $0.035 over 1 day, the $0.028 Scale cap plus 25% | `56b3b8be` |
| firstrun docs breakage or failed verification spike | 25 or more "docs step broke" hits, or 2 or more "Verification Error Monitor" hits, in 60 minutes | `74e5d64c` |
| firstrun budget guardrail tripped | each "Budget Limit Exceeded Alert" hit | `acd01964` |

The AI evaluator "report names the real failed step" (`a6aa683e`) is an agent judge with neatlogs MCP access, a $0.10 budget and 12 tool calls. It checks that the reported failed step matches the first failed TOOL span, that the failure class fits the container output, and that every patch has a passing verify run. Ad-hoc runs return `NOT_FOUND_OR_OPERATION_DISABLED`, so it scores through a scheduled evaluation.

## Evaluations, Sessions and a Second Evaluator Cover Runs and Audits

Set up over the neatlogs CLI on 2026-10-10, after the hackathon lifted plan limits.

**Sessions.** Every trace about one docs site shares the session `docs:<site>` and names the site as its end user, with the command (run, bisect, prereqs, audit) in the end-user metadata. One session shows a site's runs, bisects and audits together, and an evaluation can filter by site.

**A second evaluator.** "audit cards are backed by evidence" (`d1f7c5bb`) is an agent judge with neatlogs MCP access, a $0.10 budget and 12 tool calls. It reads a `firstrun.audit` trace and checks that the root summary matches the span outputs, that each card cites a commit or PR, and that each stale page cites commits on its topic. The audit root span now carries its cards and stale pages in `output.value` for this judge.

**Four evaluations.**

| Evaluation | Traces | Schedule | ID |
|---|---|---|---|
| FirstRun run review: backlog | every `firstrun.run` from 2026-10-10 | one pass | `0363e302` |
| FirstRun run review: every 6 hours | new `firstrun.run` traces | batch every 6 h | `57b7ff3f` |
| FirstRun audit review: backlog | every `firstrun.audit` from 2026-10-10 | one pass | `e16dd7cd` |
| FirstRun audit review: daily | new `firstrun.audit` traces | daily batch | `3122a1d3` |

The Public API cannot assign an AI evaluator to a form question, so each form and its evaluator are set in the dashboard before launch.

**Both evaluators scored real traces on 2026-10-11.** Atharva ran each one from the dashboard's Try it step. The direct run API returned `NOT_FOUND_OR_OPERATION_DISABLED`, so the dashboard was the only path.

| Evaluator | Trace | Tool calls | Result |
|---|---|---|---|
| report names the real failed step | `5520c5cff5e0ea61f130eced082b20c4`, the recovered Entire run | 6 | Named step 1 as the first failed step. Classed `curl: command not found` as `environment`, and the agent's own class matched. Fix proven. |
| audit cards are backed by evidence | `4e936e06f7af5cdadee5e0db7e5d22dc`, the audit of neatlogs/neatlogs | 5 | Score 5 of 5. Counts consistent, every evidence card cites a commit, 0 implausible stale pages. |

Screenshots: [run judge](nl-eval-run-result.png) and [audit judge](nl-eval-audit-result.png).

## Two Launched Evals Scored 67 Traces and Found Where the Agent Overclaims

Atharva launched both evals from the dashboard on 2026-10-11, with the AI judge as the only reviewer. Both finished at 100%. The scores come from `neatlogs evals responses`.

**FirstRun run review** (`15b7ef6b`) judged 52 real runs, tagged `radar`, `real`, `real2`, `v1` and `v2`.

| Question | Result |
|---|---|
| Reported first failed step is the real one | 46 of 52 |
| Run's failure class matches the container output | 38 of 52 |
| Every patch backed by a passing verify rerun | 34 of 52 |
| Overall score, 1 to 5 | mean 3.69. 23 runs scored 5, 17 scored 1 or 2 |

The judge's own failure classes were environment 28, none 12, docs bug 9 and needs secret 3.

The 17 low scores show 3 patterns:

1. Runs that stopped before a clean rerun get no proof. Five Dagster runs stopped after `create-dagster: command not found` and `no such option: --group`. Flask and Litestar server steps timed out with exit 124, before the server-step fix landed.
2. A missing API key counted as a docs bug. Two runs that failed with `No API key provided` reported `docs_bug`, and the judge said `needs_secret`.
3. One run stopped at `read_docs` with `Insufficient credits`, so it had no steps to judge.

**FirstRun audit review** (`14dfda88`) judged the 15 newest audits.

| Question | Result |
|---|---|
| Root summary matches the page and feature outputs | 14 of 15 |
| Every evidence card cites a commit or PR | 15 of 15 |
| Stale pages whose commits do not fit the topic | 0 in all 15 |
| Overall score, 1 to 5 | mean 4.87. 14 audits scored 5 |

**The detection behind the runs.** "docs step broke" flagged 78 tool spans, all on Oct 10 and 11, from a baseline of 0. [Screenshot](nl-detection-docs-step-broke.png).

**neatlogs Copilot says the detection's name overclaims.** Atharva asked Detection Copilot to group the 78 spans by root cause. It found 3 groups:

1. `command not found` for `curl`, `git`, `sudo`, `gpg`, `flask`, `create-dagster` and `entire`.
2. `ModuleNotFoundError` for `httpx`, `sqlalchemy` and `typer`.
3. Missing credentials, such as expired Claude auth or a secret outside the allowlist.

Its verdict: most flagged spans are gaps in FirstRun's own `python:3.11-slim` container, not docs bugs. That fits the design, because recovery treats a first-attempt `environment` failure as something to fix and retry. A flagged span is therefore a step that broke once, and only the report says whether the docs were wrong. The next step is to rename the detection, or to exclude spans that a later attempt passed.

**A radar batch for the evaluations to judge.** `scripts/radar.py` ranked 70 Exa results with Jev, and FirstRun ran the top 18 official quickstarts in 3 parallel lanes, tagged `radar`, under the Team cost cap. Two runs exposed a FirstRun bug: a dev server step (`flask --app hello run`, `litestar run`) never exits, so it timed out. The fix passes a server step once its output says it listens. The `radar-v2` rerun took Flask from 0 of 4 steps to verified 4 of 4.

## The Integration Check Passed the Organizer's Gates

The organizers' setup prompt ran against this repo. Gates 1, 2, 3 and 5 pass and gate 4 is partial: [docs/neatlogs-integration.md](../docs/neatlogs-integration.md).
