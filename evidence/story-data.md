# Story Data: How neatlogs and Entire Changed FirstRun

Read back on 2026-10-11 between 10:20 and 11:30 IST with `neatlogs-cli` 0.2.0 (OAuth user, project `e6bcef18-b18b-4745-90b1-3691c29c2493`), `entire` and `git`. Nothing in neatlogs or Entire was created, changed or deleted to make this file.

Every number carries a label. **Measured** means it was read from a neatlogs or Entire API, a span payload, `docs/runs/index.json` or git on 2026-10-11. **Inferred** means it joins two measured facts by time or by reasoning. **Claimed** means an earlier file in this repo states it and no API returns it.

Times are UTC unless marked IST. IST is UTC + 5:30.

## 1. Neatlogs Holds 205 Traces and $1.76 of Model Cost

**Trace count (measured, `traces list --from 2026-10-01`).** 205 traces in the project. The first is 2026-10-08 17:48, the last is 2026-10-10 19:29. No trace arrived after that, so nothing ran on 2026-10-11 before this read.

| Workflow | Trace name | Traces | Trace status ERROR | Cost in traces |
|---|---|---|---|---|
| firstrun | firstrun.run | 67 | 50 | $1.5682 |
| firstrun | firstrun.audit | 34 | 0 | $0 (no model call) |
| firstrun | firstrun (bisect and early roots) | 6 | 1 | $0.0414 |
| firstrun | firstrun.prereqs | 3 | 3 | $0 |
| firstrun | firstrun.bisect | 2 | 2 | $0 |
| firstrun | claude_agent.query (orphan roots) | 2 | 0 | $0.1244 |
| firstrun | probe.a, probe.b, probe.c, firstrun.hello | 4 | 0 | $0 |
| neatlogs-app | junk test traces from pytest | 82 | 33 | $0.0214 |
| neatlogs.doctor.v2 | doctor.probe.root | 4 | 0 | $0 |
| support-bot | handle_request (not FirstRun) | 1 | 1 | $0 |

- Total cost in all traces: **$1.7553** (measured). `analytics cost --workflow firstrun` gives $1.7340 over 118 traces.
- Per day: 2 traces on 2026-10-08 (support-bot and 1 other), 203 on 2026-10-10 (measured).
- `analytics kpis --workflow firstrun`, 2026-10-08 to 2026-10-12: 119 traces, error rate 0.471, detection hit rate 0.454, average duration 172.8 s (measured).
- The 82 `neatlogs-app` traces came from a pytest fixture leak, fixed before 08:14 UTC on 2026-10-10. `traces delete` returns `NOT_FOUND_OR_OPERATION_DISABLED` with `operationGate: tier-c-compute`, so they stay (claimed in the friction log, gate not re-tested).

**Trace status is not the run result.** A failed `step.<id>` span rolls ERROR up to the trace even when the root span says `verified` (see `docs/neatlogs-integration.md`, "Open limits"). Use the root span output or `docs/runs/index.json` for outcomes, never the trace status.

**firstrun.run by tag (measured, cost and duration from the trace).**

| Tag | Runs | First to last (UTC) | Mean cost | p95 cost | Mean duration |
|---|---|---|---|---|---|
| dev | 7 | 07:35 to 08:44 | $0.0031 | $0.0169 | 78 s |
| v1 | 4 | 07:40 to 07:47 | $0.0262 | $0.0397 | 128 s |
| check | 4 | 08:10 to 08:18 | $0.0065 | $0.0211 | 108 s |
| v2 | 8 | 08:59 to 09:44 | $0.0333 | $0.1014 | 204 s |
| real | 12 | 08:59 to 10:42 | $0.0285 | $0.0508 | 446 s |
| selftest | 1 | 11:26 | $0.0258 | | 244 s |
| real2 | 7 | 11:33 to 11:57 | $0.0404 | $0.0596 | 261 s |
| tiercap | 3 | 12:27 to 12:40 | $0.0032 | $0.0045 | 118 s |
| none | 1 | 14:37 | $0.0327 | | 138 s |
| radar | 18 | 17:21 to 17:46 | $0.0186 | $0.0512 | 200 s |
| radar-v2 | 2 | 17:38 to 17:48 | $0.0600 | $0.0653 | 410 s |

All 67 runs: mean $0.0234, p95 $0.0547, max $0.1014 (trace `a462576e751e91543b5623185331d603`, v2 OpenAI fixture). 17 runs cost more than $0.035.

Trace cost undercounts. LLM spans carry fresh input tokens only, so the run log (`docs/runs/index.json`) and `state.json` show higher figures. Example: dlthub trace `1b47ffa6` holds $0.0512, its run log row says $0.10.

**Tool spans (measured, `analytics tools`).** `step.1` ran 130 times with 46 errors, `step.2` 105 times with 36 errors, `step.3` 80 times with 21 errors. `classify_failure` ran 71 times with 0 errors. `read_docs` ran 60 times with 2 errors.

**Run outcomes from the root span (measured, `traces payload <trace> <root span> --fields output`, 66 of 67 runs read).** 28 failed, 22 verified, 9 passed, and 8 roots carry no status (the 4 v1 runs and 4 early dev and check runs predate the root output). By tag: v2 3 failed, 3 passed, 2 verified. real 6 failed, 6 verified. real2 3 failed, 4 verified. radar 8 failed, 6 verified, 4 passed. radar-v2 1 passed, 1 verified. tiercap 2 failed, 1 verified.

**False fails with exit code 0 (measured).** 11 `step.<id>` spans in 7 runs have status ERROR, `exit_code` 0 and `passed` false. The step ran, and only the expected-output or file check failed. They are dlthub `1b47ffa6` step 2 (2 spans), uv `57b8ba9f` step 3, uv `14e57f34` step 4, Dagster `b3b5dd14`, `08379c21` (2 spans) and `35f401fc`, and MkDocs `a73e1c42` (3 spans, fixed by `2de852f`). In dlthub step 2 the pipeline printed "Load package ... is LOADED and contains no failed jobs", but the planner expected the text "Pipeline quick_start completed". The docs fix `pip install "dlt[duckdb]"` worked on attempt 1, and recovery then spent 2 more attempts on pip warnings.

**Timeouts (measured).** 5 step spans timed out: `perseus serve -w` (`04800d65`), `litestar run` (`0ef82814`), `flask --app hello run` (`ffda8db9`), an apt and git clone step (`dd687707`) and a `uv run --with 'fastapi[standard]'` step (`b759dc53`). Only flask and litestar were rerun after `4e57b29`.

**Reported step differs from first failed step (measured).** 2 roots report a later step than the first failure: `04800d65` (first 1, reported 3) and `1b47ffa6` (first 1, reported 2).

**Sessions (measured).** Since commit `c1a26f0` (2026-10-10 17:52 UTC), each run carries the session `docs:<site>`. All 20 radar and radar-v2 runs and every audit trace from 19:29 carry one, for example `docs:flask.palletsprojects.com` and `docs:fastapi/typer`.

## 2. One Investigate Closed a Detection, and 3 Alert Fires Stay Open

### Detections

14 detections exist. 8 were made for FirstRun on 2026-10-10. The other 6 are project defaults from 2026-07-06. Hit counts come from `detections hits`, mapped to traces by `traceId`.

| ID | Name | Type and rule | Created (UTC) | Hits | Traces |
|---|---|---|---|---|---|
| `6c99b4f4` | docs step broke | regex on TOOL output: `command not found\|No module named\|unrecognized arguments\|No matching distribution` | 08:31 | 78 | 35 |
| `b08cc3e2` | planner invented a step | regex on `planner` span output: `"command":\s*"(true\|:)"\|sk-\.\.\.\|command -v \|test -f ` | 08:32 | 8 | 8 |
| `5b6b1a38` | Budget Limit Exceeded Alert | suggested regex on trace: `budget spent\|budget exceeded\|...` | 11:24 | 26 | 16 |
| `1ef61112` | Missing API Key Detector | suggested regex | 11:24 | 8 | 5 |
| `c13f8f86` | Documentation Unreachable Alert | condition `error_type = firstrun.planner.DocsUnreachable` | 11:25 | 2 | 2 |
| `07a3b36d` | Verification Error Monitor | condition `span_name = verify AND status = ERROR` | 11:25 | 4 | 4 (all junk `neatlogs-app`) |
| `8e8809e5` | Prerequisite Validation Error Monitor | suggested condition | 11:25 | 2 | 2 (`firstrun.prereqs`) |
| `00ca334d` | OpenAI Authentication Error Monitor | condition | 07:35 | 3 | 1 (support-bot) |
| `43df543a` | Execution Failed (default) | any span ERROR | 2026-07-06 | 238 by trend | 51 by analytics |

**"planner invented a step" hits, with what each one matched (measured from the `planner` span payload).**

| Trace | Tag, start (UTC) | Target | What the regex matched | A real invented step? |
|---|---|---|---|---|
| `66ec093b00333fa221fade5d2fc5f55f` | v1, 07:42 | Chroma | step 2 `"command":"true"` | Yes |
| `b98b419e286acf436083febdb5217cf9` | v1, 07:47 | OpenAI v0 fixture | step 5 `export OPENAI_API_KEY='sk-...'` | Yes |
| `10c44df9626c19f5ac801f1c6d84610e` | v1, 07:42 | Entire install | steps 3 and 4 `command -v entire`, `command -v git-remote-entire` | No. The Entire docs page in the same span says both lines |
| `a994d8bf646fa843d271835932ab9209` | v2, 09:01 | Entire install | the same 2 docs lines, now with `source_line` set | No |
| `5520c5cff5e0ea61f130eced082b20c4` | v2, 09:34 | Entire install | the same 2 docs lines, with `source_line` | No |
| `a462576e751e91543b5623185331d603` | v2, 09:11 | OpenAI v0 fixture | `sk-...` inside the docs markdown that the span echoes. No step holds it | No |
| `78e538e63a65c5d00d0281effa119567` | v2, 09:44 | OpenAI v0 fixture | same as above | No |
| `eeff46ddf8080f7d9ff304fec4b6b50d` | selftest, 11:26 | FirstRun README | the README sentence that describes this bug | No |

Two consequences for the story:

1. The planner fix `3ca6f11` (08:58 UTC) is measured. Real invented steps went from **2 of 4 v1 runs** to **0 of 52 runs** after the fix. All 5 later hits are false positives.
2. The README line "It added `command -v entire` ... which the docs never say" (`README.md` line 488) and the question in `evidence/neatlogs-investigation.md` are wrong for `command -v entire`. The fetched Entire docs contain it. `test -f first_trace.py` was not found in any flagged span, so that part is unverified.

**"docs step broke" by batch (measured).** 78 hits on 35 traces: 1 junk, 2 check, 4 dev, 4 real batch 1 plus 8 more real, 2 v2, 6 real2 plus 1 bisect root, 3 tiercap, 5 radar. In the radar batch it hit `9c95e901` (sqlalchemy), `ffda8db9` (flask), `1b47ffa6` (dlthub), `8274692e` (django, 2 hits) and `9a118077` (peewee). The hourly trend peaks at 20 hits at 12:00 UTC (the tiercap typer runs).

### Alert Rules and Fires

3 rules, all created over the CLI on 2026-10-10 at 13:30 UTC, all enabled, email channel on (measured).

| Rule ID | Name | Type | Condition |
|---|---|---|---|
| `56b3b8be-532b-4fb8-9607-0dbd0725ef77` | firstrun p95 run cost above Scale cap | metric_threshold | p95 `cost` > 0.035 over 1440 min, cooldown 720 min |
| `74e5d64c-21a9-4ad9-badc-d18517bf4cf6` | firstrun docs breakage or failed verification spike | compound, OR | "docs step broke" >= 25 or "Verification Error Monitor" >= 2 in 60 min, cooldown 120 min |
| `acd01964-3557-49ca-a315-f0d0e4566b59` | firstrun budget guardrail tripped | per_event on `5b6b1a38` | each hit, cooldown 30 min |

3 fires (measured, `alerts history`). Each was delivered to `in_app` only, though the rules have email on.

| Fire ID | When (UTC) | Rule | Investigation target | What it shows |
|---|---|---|---|---|
| `82c90725-f45f-4151-a98d-c1688121827b` | 2026-10-10 13:31 | p95 cost | trace_search, 2026-10-09 13:31 to 2026-10-10 13:31 | 46 runs in the window, p95 $0.0529, max $0.1014 (computed from traces) |
| `a1548265-70b5-462f-a464-acb634362165` | 2026-10-10 17:40 | budget guardrail | trace `1b47ffa63caaa65954c3ea7a02bbf512` | dlthub radar run gave up: "attempt budget spent: step 2 used 3 attempts" |
| `3c0a782c-d774-43c4-9abf-95d6803bde6f` | 2026-10-11 01:31 | p95 cost | trace_search, 2026-10-10 01:31 to 2026-10-11 01:31 | 67 runs, p95 $0.0547, max $0.1014 (computed) |

The compound rule `74e5d64c` never fired. Its peak was 20 "docs step broke" hits in one hour, below 25.

No code change followed any fire. All three are open leads (see section 6).

### Incidents

The CLI has no command to list or read incidents. `incidents publish` exists but needs a service-account token (`ServiceAccountBearerAuth` only, `source: incident_loop`), and this CLI runs as an OAuth user. **No incident data could be read.** The repo, the vault plan and the build log mention no incident ID.

### Investigations

One Investigate run is on record (claimed, no ID). Atharva ran it in the dashboard on 2026-10-10 at about 14:25 IST (08:55 UTC), Deep mode, workflow `firstrun`, last 14 days. It followed the "planner invented a step" detection.

- **Question:** why the planner adds steps not in the docs, skips key-gated steps, and gives 4 steps then 3 for the same page.
- **Root cause it named:** the system prompt of the `claude_agent.query` call in `planner.py`. No confidence score was saved.
- **Proposed fix:** a stricter prompt with 4 rules. Copy only commands the docs write, drop `true` placeholders, drop fake secrets, and keep key-gated steps (full text in `evidence/neatlogs-investigation.md`).
- **The change:** a headless Claude Code session with the neatlogs MCP server (Entire session `ed6583d8`, prompt "You are fixing the FirstRun planner with a fix tha...", started 14:25 IST) wrote commit `3ca6f11` at 14:28 IST, "Planner fix from neatlogs Investigate: copy commands only, guard against invented steps". It changed `src/firstrun/planner.py` (+160 lines), added `tests/test_planner_guard.py` (112 lines) and a plan cache. Entire checkpoint `01M4JGJ6NTE7YNB9Z0YW5FYVHN`.
- **The effect:** see the detection table above. Real invented steps fell from 2 of 4 runs to 0 of 52 (measured).

The CLI has no Investigate command, and none of the 288 Public API operations in `schema list` names one. The investigation ID, transcript and canvas live only in the dashboard.

## 3. Two Evaluators and Four Evaluations Exist, and None Has Run

**2 evaluators (measured, `evaluators get`).** Both were created over the CLI on 2026-10-10. Both are `agent_judge`, with a $0.10 budget, 12 tool calls and reasoning on. Each has one tool grant, `neatlogs_mcp`, which reads `"configured": false`. Check in the dashboard that the judge can read traces before launch. `evaluators runs` returns 0 runs for both.

| ID | Name | Judges | Output fields |
|---|---|---|---|
| `a6aa683e-61c8-407a-bdad-e260a7e7e0d1` | report names the real failed step | one `firstrun.run` trace | `names_real_failed_step` (boolean), `failure_class` (categorical: docs_bug, environment, product_bug, needs_secret, none, unclassified), `failure_class_correct` (boolean), `fix_proven` (boolean), `score` (numeric 1 to 5), `reason` (text) |
| `d1f7c5bb-4ba5-4154-b48e-729b2df5cdea` | audit cards are backed by evidence | one `firstrun.audit` trace | `counts_consistent` (boolean), `cards_have_evidence` (boolean), `implausible_stale_pages` (numeric), `score` (numeric 1 to 5), `reason` (text) |

**4 evaluations, all `draft` (measured, `evals list`, `evals get`).** `evals form get` returns `NOT_FOUND` for all 4, so no questions exist yet. `evals stats`: 0 active, 0 completed, 0 submitted responses, average score null.

| ID | Name | Trace filter | Schedule |
|---|---|---|---|
| `0363e302-a5b9-44ce-ae44-5bb158c2189f` | FirstRun run review: backlog | workflow `firstrun`, span `firstrun.run`, 2026-10-10 to 2026-10-11 | manual, existing traces |
| `57b7ff3f-75f9-4348-9ce6-5b5d8a973173` | FirstRun run review: every 6 hours | workflow `firstrun`, span `firstrun.run` | batch 6 h, future traces, schedule status draft |
| `e16dd7cd-cbac-456b-8960-24323c0ad04b` | FirstRun audit review: backlog | workflow `firstrun`, span `firstrun.audit`, 2026-10-10 to 2026-10-12 | manual, existing traces |
| `3122a1d3-36b5-4d5b-8428-a8f6ae02af31` | FirstRun audit review: daily | workflow `firstrun`, span `firstrun.audit` | batch 1 d, future traces, schedule status draft |

No scores exist.

## 4. Entire Recorded 74 Checkpoints and 8 Runner Findings

**Sessions and checkpoints (measured).**

- `entire recap --week`: 12 sessions, 74 checkpoints, 12.6M tokens, 2 active days, Claude Code 68 checkpoints and "Unknown" 6.
- `entire activity`: 74 checkpoints, 170.4k tokens per checkpoint, 1.4 sessions per checkpoint, peak session 0.8 h.
- `entire session list` on this machine: 11 sessions. The largest is `ae05fb29` (52 turns, 173.4M tokens), the public build session.
- `git ls-remote origin 'refs/entire/checkpoints/*'`: 68 refs. 75 of the 86 non-merge commits on `main` carry an `Entire-Checkpoint:` trailer. Merge commits carry none by design.

**Trails (measured, `trail list --status any`).** 32 trails: 26 merged, 3 closed (retro review trails 3, 4, 5), 3 open (1 and 2 branchless from the first hour, 32 in building on `site/audit-intake-test-bar`).

**Runner findings (measured, `trail finding --status any`).** 8 findings on 6 trails. 5 are resolved, 3 are open.

| Trail | Finding ID | Severity, confidence | Finding | Resolution |
|---|---|---|---|---|
| 3 | `01M4JMBPW6HQ3GXP4CEVC3JQJP` | high, 0.80 | `recovery.py:228`: a `needs_secret` step retried the same command until the budget ran out | Fixed in `e2aacb7` (2026-10-10 15:37 IST): stops with a clear reason |
| 3 | `01M4JMBPWRN19E5A1AV778MY42` | medium, 0.65 | `config.py:21`: Docker defaulted to the author's WSL | Fixed in `e2aacb7`: docker from PATH, WSL only on Windows |
| 7 | `01M4JNAG8GAFEJZYBB6P0HQS63` | high, 1.00 | `sandbox.py:239`: the cd guard from `d22eb69` was never called | Fixed in `f87db02` (15:56 IST), with a test on the exec path |
| 31 | `01M4MKKJQJQXZV883N40F8D9KC` | low, 0.55 | `docs/index.html:863`: build-log road measured before the reveal ended | Fixed in `91e6637` |
| 17 | `01M4JYBE4JJDVBDTABS5SJHN66` | medium, 0.40 | `econ.py:39`: raw neatlogs CLI stderr goes into the error message and could print a key | **Open** |
| 25 | `01M4KF1SA70682E8NQ4QPTSQR8` | low, 0.70 | `docs/index.html:453`: runs deduplicated by title can hide real runs | **Open** |
| 30 | `01M4KN8QQBRS8JEWD5J1PHZY01` | medium, 0.75 | `docs/doc-test/index.html:1267`: a run with `gave_up` and no patch loses its Fix section | **Open** |

The fifth resolved finding is counted as stale on trail 7.

**Recap and activity highlights (measured).** Skills used: claude-api, neathack, impeccable. Tool mix: other 61%, file operations 16%, shell 11%. Earlier evidence (`evidence/entire.md`, claimed): graph stats of 10 calls and about 56,254 tokens saved, 7 Brain facts, a jury self-test score of 3.93 of 5.

## 5. Nine Signals Led to a Commit, and Six Have a Measured Effect

Only rows with evidence. Run outcomes come from `docs/runs/index.json` unless a trace is named.

| Signal (tool and ID) | Finding | Change (commit) | Measured effect |
|---|---|---|---|
| neatlogs detection `b08cc3e2` on v1 traces `66ec093b`, `b98b419e`, `10c44df9`, then Investigate (Deep, no ID) | The planner prompt let the model write `true` placeholders and fake `sk-...` exports | `3ca6f11` Planner fix from neatlogs Investigate, applied over neatlogs MCP by Entire session `ed6583d8` | Real invented steps: 2 of 4 v1 runs, then 0 of 52 runs (measured from span payloads). Chroma: 3/3 in 272 s (v1 `66ec093b`), then 2/2 in 201 s (`f63d2b84`) |
| neatlogs readback of trace `452add41` (organizer check 3b) | Step, recover, budget and verify spans had no input or output, and pytest leaked about 50 traces a run | `d55c576` neatlogs integration check: spans carry input, output, status | Later traces carry payloads (this file reads them). A pytest run after the fix made 0 traces (claimed in `docs/neatlogs-integration.md`) |
| v2 traces read back (`a994d8bf`, `a462576e`, 2026-10-10 09:01 to 09:11) | A piped install passed falsely, pip noise hid the error, an apt fix counted as a docs bug | `7de398d` Fix three agent bugs found in the v2 runs | Entire install: v1 failed 0/4 (`10c44df9`), v2 verified 4/4 (`5520c5cf`, run cost $0.0229). Attribution is shared with `3ca6f11` and recovery (inferred) |
| real-batch traces: MkDocs `a73e1c42` (budget detection `5b6b1a38`, 2 hits), dbt step 3 | A 5-line step passed on its last line, and a file check ran after a `cd` | `2de852f` Fail a step on any failing line, check files from where the step started | MkDocs: failed 1/9 at 09:28 (`a73e1c42`), then verified 9/10 at 10:10 (`cef9cc00`) |
| neatlogs traces as cost data: 64 runs, mean $0.0167, p95 $0.0508 | The fixed $0.50 cap allowed a -403.6% Scale margin | `f0a83e1` Business plan sets the agent's cost cap per tier | `--tier free` run `7060f5bd` stopped at "cost budget spent: $0.0115 of $0.0108", and detection `5b6b1a38` caught it. `--tier scale` run `9a29db32` verified 7/7 at $0.0201 |
| run log and "docs step broke" hit on `ffda8db9` (flask), with litestar `0ef82814` | A dev server step never exits, so the run timed out | `4e57b29` Pass a dev server step once it says it listens | Flask: 0/4 in 336 s (`ffda8db9`), then verified 4/4 (`34248334`). Litestar: 1/3, then 3/3 (`997d95dd`). Cost rose from $0.0030 to $0.0653 and from $0.0188 to $0.0547 |
| Entire Trail 3 runner findings | `needs_secret` retry loop, WSL-only Docker | `e2aacb7` | Both findings resolved with the sha. No trace measures the effect |
| Entire Trail 7 runner finding (confidence 1.00) | The cd guard was dead code | `f87db02` | Resolved. The Dagster reruns stayed failed (1/10 at 10:30, 4/10 at 10:42). `4b9de7a` then found the Dagster docs correct |
| neatlogs evaluator setup (`a6aa683e`, `d1f7c5bb`) | Evals could not filter by site, and the audit root had no output to judge | `c1a26f0` One session per docs site, audit traces a judge can read | All 20 radar runs and later audit traces carry `docs:<site>` sessions (measured) |

## 6. Twelve Gaps Limit the Story

1. **No Investigate ID or transcript.** Only the pasted text exists. No confidence score was kept.
2. **No incident data.** The CLI cannot list incidents, and no file names one.
3. **No eval scores.** All 4 evaluations are drafts with no form. Both evaluators show 0 runs, and their `neatlogs_mcp` grant reads `configured: false`.
4. **No action on the 3 alert fires.** The cost alert fired twice with p95 $0.0529 and $0.0547, above the $0.035 line. The budget alert fired on dlthub. No investigation or commit followed.
5. **One alert channel is silent.** Fires went to `in_app` only, though each rule has email on.
6. **Trace status hides results.** 50 of 67 runs show ERROR at trace level, but the root spans say only 28 failed. A dashboard error-rate chart overstates failure.
7. **Trace cost undercounts.** Cache tokens are missing from LLM spans. The run log is higher (dlthub $0.0512 in the trace, $0.10 in the log).
8. **The "planner invented a step" detection is noisy now.** All 5 hits after the fix are false positives, because the regex reads the docs text that the planner span echoes.
9. **A README claim is wrong.** Line 488 says the docs never say `command -v entire`. The Entire docs do.
10. **The before and after has thin samples.** Each before and after pair is 1 run per target, and several fixes landed within minutes of each other, so attribution is shared.
11. **There is no trace after 2026-10-10 19:29 UTC**, so no fix after `4e57b29` has a measured after-run in neatlogs.
12. **3 Entire findings are open** (trails 17, 25, 30). The approvals gate was never met, because Entire does not count the author's own approval.
