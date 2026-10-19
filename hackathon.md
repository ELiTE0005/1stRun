# neatHack Build Log: FirstRun

## Project

- **Name:** FirstRun
- **Purpose:** FirstRun runs your quickstart in a clean container, finds the first step that breaks, and proves the fix with a second clean run.
- **Problem:** Quickstarts break when a package is renamed, a flag is removed or a version moves. Nobody on the team gets an alert. The first person who finds the break is a new user, and most new users leave.

## Team

- Atharva Shah ([@HighnessAtharva](https://github.com/HighnessAtharva)), solo.

## Stack

| Part | Tool |
|---|---|
| Language | Python 3.11 |
| Agent | Claude Agent SDK, model `claude-sonnet-5-5` at medium effort, auth through `CLAUDE_CODE_OAUTH_TOKEN` |
| Tracing | neatlogs Python SDK 1.4.26, neatlogs CLI 0.2.0 |
| Sandbox | Docker Engine 29.8.2 in WSL Ubuntu 22.04, one fresh container per run |
| Docs reader | Firecrawl CLI 1.25.3 |
| Failure classifier | Jev (TypeSafe System One) |
| Session capture | Entire CLI 0.11.4: Checkpoints, Graph, Brain, Trails |
| Business plan | cfo.ai |

## Planning Happened Before the Event

Planning and tool tests happened before the event in a private repo. No FirstRun code was written before kickoff (Sat 2026-10-10, 12:30 PM IST).

## Build Log

### 2026-10-10 (Saturday)

- **12:30 to 13:10 IST.** Created the public repo, ran `entire enable --agent claude-code --search-skill --agent-help-skill` before commit 1, and pushed the Entire config, 6 Trail runners, and the Graph and Brain agent instructions.
- **13:20 IST.** Preflight passed: 4 keys present (lengths only checked), Docker 29.8.2 in WSL, `gh`, Firecrawl 1.25.3, Entire 0.11.4, the venv on Python 3.11. `entire doctor` reports no problems.
- **13:30 IST.** Scaffold: `pyproject.toml`, `src/firstrun/config.py` (the only file that names a model), `src/firstrun/tracing.py`.
  - `python -m neatlogs doctor --probe` passed 8 of 8 checks, including `TRACE_VISIBLE` and `TRACE_FINALIZED`.
  - The first FirstRun trace, `firstrun.hello`, is trace `fdcab847f3129a251c6ae45f00c76a1c`. It is finalized with 2 spans and tag `hello`, and the neatlogs CLI read it back.

Entire state at the scaffold commit, run by the build agent:

```text
$ entire status
● Enabled · branch main
  Agents · Claude Code
  Checkpoints sync to: origin
1 session

$ entire checkpoint list
  branch       main
  checkpoints  0
No checkpoints found on this branch.
```

The checkpoint count is 0 because the scaffold commit is the first commit made inside an agent session. Later entries record the count after it.

- **12:55 IST. Entire checkpoints hung on Git 2.33.** The post-commit hook waited 206 s on `git update-ref --stdin` and the checkpoint for the scaffold commit was never written. Upgrading Git for Windows to 2.55.0 fixed it: the next hook took 3 s and the checkpoint landed.
- **13:00 to 13:35 IST. Six worker agents built FirstRun in parallel** on main, one track each: fixtures, planner, executor, recovery, verify and output, report page. Each track is one commit with its own checkpoint.
- **13:35 IST. Layer 1 done.** `firstrun run https://docs.neatlogs.com/sdk/python` passed 4 of 4 steps in 70 s and wrote `report.md`. The first live run showed one run split into 3 neatlogs traces, so the CLI now opens one `firstrun.run` trace around reading, planning, every step and verification.

### v1 Runs, Layer 1 Only (Recovery Off), Tag `v1`

| Target | Result | Time | Cost (list price, not billed) |
|---|---|---|---|
| neatlogs Python SDK | passed 3/3 | 84 s | $0.036 |
| Entire CLI install | failed at step 1: `curl: command not found` on python:3.11-slim | n/a | $0.023 |
| Chroma getting started | passed 3/3 | 250 s | $0.029 |
| OpenAI v0 README (FIXTURE, Wayback 2023-08-02) | failed at step 6: `openai: command not found`, the documented CLI is gone from today's SDK | n/a | $0.031 |

neatlogs v1 traces, one `firstrun.run` trace per run, cost as neatlogs measured it:

| Target | Trace ID | Spans | Tool spans | LLM calls | neatlogs cost |
|---|---|---|---|---|---|
| neatlogs | `fccdbad9a9c6177b90112911fe485bd6` | 9 | 4 | 1 | $0.0397 |
| Entire | `10c44df9626c19f5ac801f1c6d84610e` | 7 | 2 | 1 | $0.0170 |
| Chroma | `66ec093b00333fa221fade5d2fc5f55f` | 9 | 4 | 1 | $0.0217 |
| OpenAI v0 FIXTURE | `b98b419e286acf436083febdb5217cf9` | 12 | 7 | 1 | $0.0266 |

Six mistakes the agent itself made in v1. These are the "before" story:

1. **The plan changes between runs.** The same neatlogs page gave 4 steps at 13:35 and 3 steps at 13:40.
2. **The planner invents steps.** It added `command -v entire`, `command -v git-remote-entire` and `test -f first_trace.py`, which are not in the docs.
3. **The planner writes placeholder steps.** Chroma step 2 is `true`, a no-op standing in for "create the file".
4. **A fake secret passes as a step.** The OpenAI step `export OPENAI_API_KEY='sk-...'` exits 0, so it counts as a pass while proving nothing.
5. **The planner skips the step that matters.** It dropped the OpenAI `openai.ChatCompletion.create` example and the neatlogs "run your app" step because they need a key. Those are the steps most likely to break.
6. **Most expected results check only the exit code.** 9 of 16 steps have no output check, so a command that prints an error and exits 0 would pass.

### Saturday Afternoon: neatlogs Found the Agent's Own Bug, and v2 Fixed It

- **14:10 IST.** Atharva created two neatlogs detections: "docs step broke" (TOOL spans) and "planner invented a step" (the planner span). The second flagged the planner spans of 3 v1 runs.
- **14:40 IST.** neatlogs Investigate (Deep, workflow `firstrun`) traced the invented steps to the planner prompt and proposed a stricter one ([evidence/neatlogs-investigation.md](evidence/neatlogs-investigation.md)).
- **14:45 IST.** A headless Claude Code session read the detection and its trend over the neatlogs MCP server and applied the fix with code guards and a plan cache: commit 3ca6f11, checkpoint `01M4JGJ6NTE7YNB9Z0YW5FYVHN`, [Entire commit view](https://entire.io/gh/HighnessAtharva/firstrun/commit/3ca6f118ecb0a8915315eea27b5588dd8a7c6299).
- **15:15 IST. v2 versus v1** on the same 4 targets: quickstarts finished 2 to 3 of 4, failed steps recovered 0 to 3, cost per run $0.0262 to $0.0200 (neatlogs). The v2 and real-world runs exposed 5 agent bugs, all fixed: a pipe that hid a missing `curl`, a multi-line step that hid a failing `pip`, pip noise that hid the real error, container fixes counted as docs bugs, and a file check after `cd`.

### Saturday Evening: Real Docs, Upstream PRs, and Entire Reviewing Every Layer

- **Real quickstarts:** dbt + DuckDB, AccuKnox knoxctl, Dagster, MkDocs and the Entire install all reached `verified` in a fresh container.
- **Upstream PRs, each from a verified run and a duplicate search:** [dbt-labs/docs.getdbt.com#10149](https://github.com/dbt-labs/docs.getdbt.com/pull/10149) (`jafgen --years` removed), [#10150](https://github.com/dbt-labs/docs.getdbt.com/pull/10150) (Python 3.12 floor), [entireio/cli#2724](https://github.com/entireio/cli/pull/2724) (Linux PATH after `install.sh`), [accuknox/help#671](https://github.com/accuknox/help/pull/671) (knoxctl page named 0.9.0 while the installer fetched 0.9.58).
- **No PR where the docs were right:** Dagster's page already covers both gaps FirstRun hit, so FirstRun opened nothing there. MkDocs needed only `curl` in the container.
- **Trails:** branch-backed Trails 3 to 8 cover every commit since kickoff. Entire runners raised 3 real bugs, all fixed and resolved with the commit SHA: a secret retry loop, a Windows-only Docker default, and a `cd` guard that was written but never called.
- **CI:** GitHub Actions runs the offline suite on every push. It caught 3 tests that passed only with a local Claude token.

### Saturday Night: Two New Answers From the Same Engine

- **Docs Bisect** (`firstrun bisect`): on the dbt guide, `jafgen --years 6` passes on jafgen 0.3.1 (2023-01-17) and fails on 0.4.6 (2024-04-07), and PyPI has no release between them. The guide merged on 2025-03-14, 11 months later. 5 probes, $0 in model calls. The evidence is a [comment on #10149](https://github.com/dbt-labs/docs.getdbt.com/pull/10149#issuecomment-6096827074).
- **Prerequisite Proof** (`firstrun prereqs`): proven blocks for AccuKnox (curl, ca-certificates, gnupg, sudo, 5/5 steps), MkDocs (curl, 9/9 steps) and Entire (curl, git, `~/.local/bin` on PATH, 4/4 steps).
- **Website:** [1run.netlify.app](https://1run.netlify.app) takes a docs URL and writes a prompt for the visitor's own coding agent. A tested URL shows its cached run first. Every run prints a share link that replays read, plan, run, fix, prove, plus the bisect timeline and the assumptions card.
- **Jury self-test:** the Entire judge plugin ranked the repo with no excluded work, 3.93 of 5 ([evidence/jury-selftest.txt](evidence/jury-selftest.txt)).

### 2026-10-10, 17:45 to 18:05 IST: The Business Plan Sets the Agent's Budget

- **Done: `firstrun econ`.** The command reads 88 `firstrun.run` traces from neatlogs and writes [business/drivers.csv](business/drivers.csv) and [business/unit_economics.json](business/unit_economics.json). Mean cost per run is $0.0178, p95 is $0.0529 and max is $0.1014. Each quantile row names its trace ID.
- **Finding:** the fixed $0.50 cap in `models.py` was 30 times the mean run. If every run hit it, Scale margin would be -403.6%. At a 70% margin floor, the Scale cap is $0.028, and 25.0% of measured runs cost more than that. [business/BUSINESS_PLAN.md](business/BUSINESS_PLAN.md) gives two fixes from the same formula: Scale at $529, or Scale at 1,500 runs.
- **Done: `firstrun run --tier NAME`.** The executor and the recovery agent check the tier's cap in the `budget` GUARDRAIL span.
- **Live runs on the typer quickstart, tag `tiercap`:**
  - `--tier scale` ($0.0280 cap): verified 7/7 steps in 127 s with 8 patches, at $0.0201 list price. neatlogs trace `9a29db323b3d054bb2c82e82e080340f`.
  - `--tier free` ($0.0108 cap): stopped at step 4 with `cost budget spent`, after 4 patches and $0.0114. neatlogs trace `06e7f3765141c2f417a862beef5f5134`.
- **Tests:** 255 passed and 2 skipped in the offline suite, including 8 new tests in `tests/test_econ.py`.
  - `--tier free` again, after the cap message moved to 4 decimals: stopped at step 4 with `cost budget spent: $0.0115 of $0.0108`. neatlogs trace `7060f5bd8dbb8cdc6c1dec3830ba7bab`.
- **Known gap: two cost counters.** On 43 runs matched by start time, FirstRun's own count totals $1.5253 and neatlogs totals $1.0989, so FirstRun counts 39% higher. The gap holds after the traces finalized, so ingestion lag does not explain it. The cap checks FirstRun's count, so it stops a run early and never late. Unifying the two counters is next.
- **Done later the same evening:** Ari built the cfo.ai model from `drivers.csv` over the `cfoai` MCP server, with 6 Scenarios. It is public at [cfo.ai/s/_u5lbrHIl9KX_JQE](https://cfo.ai/s/_u5lbrHIl9KX_JQE).

### 2026-10-10, 18:30 to 19:30 IST: The Docs Execution Graph

- **Done:** `run.html` draws a graph from the docs page, through every step, to the fresh-container proof. A failed step branches into its container output, its proposed fix, its rerun and its evidence. Clicking a node opens a side panel with the quoted docs sentence, the command, the output, the change, and every attempt before and after.
- **Honest labels:** nodes read Passed, Failed as written, Blocked, Not run, or Not run: out of scope. Red means the docs are wrong. Amber means the container lacked a prerequisite and the docs were fine.
- **Evidence path:** a toggle shows neatlogs trace, Entire checkpoint, Entire session, Trail and PRs in order. The checkpoint and session pages open without a login. The Trail and the neatlogs trace need one, and the page says so. Entire Graph is not used, because it maps code, not docs steps.
- **Example:** the dbt replay links step 3 to [#10150](https://github.com/dbt-labs/docs.getdbt.com/pull/10150) and step 10 to [#10149](https://github.com/dbt-labs/docs.getdbt.com/pull/10149) and its bisect comment.
- **Fixes found while building it:** the share tail kept pip download lines and dropped the real error, so stderr now goes last. `report.md` called the step that ended a run its "First Failed Step" even after recovery fixed an earlier failure. It now names both steps, and the root span carries `reported_failed_step` for the neatlogs eval.
- **Checked:** desktop at 1280 px and phone at 375 px with no sideways scroll, the dbt, Dagster and fixture codes, and no console errors. Offline suite: 260 passed, 2 skipped.

### 2026-10-10, 19:00 IST: neatlogs Alerts, an AI Evaluator, and Public Proof Upstream

- **Alerts, created over the neatlogs CLI with write scopes Atharva approved:** "firstrun p95 run cost above Scale cap" (p95 `cost` above $0.035 over 1 day, `56b3b8be`), "firstrun docs breakage or failed verification spike" (compound rule on 2 detections, `74e5d64c`) and "firstrun budget guardrail tripped" (each Budget Limit Exceeded hit, `acd01964`). All three send email. A dry-run test of each returned `simulated` for email.
- **AI evaluator:** "report names the real failed step", an agent judge with neatlogs MCP access, a $0.10 budget and 12 tool calls (`a6aa683e`). An ad-hoc run returned `NOT_FOUND_OR_OPERATION_DISABLED` with gate `tier-c-compute`, so scoring runs only through a scheduled evaluation.
- **cfo.ai:** Ari built the model over the `cfoai` MCP from `drivers.csv`. Under the old $0.50 Scale cap, cash goes negative in month 14. The figures are in [business/BUSINESS_PLAN.md](business/BUSINESS_PLAN.md).
- **Public proof on the 4 upstream PRs:** each got a comment linking the live replay, opened on the fixed step, and the public Entire session. The comments are on [dbt #10149](https://github.com/dbt-labs/docs.getdbt.com/pull/10149#issuecomment-6097945132), [dbt #10150](https://github.com/dbt-labs/docs.getdbt.com/pull/10150#issuecomment-6097945350), [Entire #2724](https://github.com/entireio/cli/pull/2724#issuecomment-6097945657) and [AccuKnox #671](https://github.com/accuknox/help/pull/671#issuecomment-6097945911).

## Demo

Landing page: https://firstrun.atharvashah.com (Netlify, published from docs/ on main). The older address https://1run.netlify.app serves the same site.

Run replay with the docs execution graph: https://1run.netlify.app/run.html?s=10#ex=dbt opens the dbt run on the step that broke.

Demo video, 2:54, covering the problem, Doc-test, Doc-audit, Agent Ready, neatlogs incidents, Entire and cfo.ai: https://www.youtube.com/watch?v=9xxgu_1bH-E
The 2:59 long cut, with each tool's architecture, implementation and runtime: https://www.youtube.com/watch?v=JJNWWhSV9pc

## Built in Public

Links were checked logged out on 2026-10-11 through the public X embed endpoint and the Zernio post ledger. The Tag column says whether the post text carries #neatHack.

| When (IST) | Post | Tag | Link |
|---|---|---|---|
| Sat 10:45 | "my neatlogs hackathon project has already caught doc issues" | yes | https://twitter.com/i/web/status/2108788557670125946 |
| Sat 11:00 | "built this weekend at #neatHack", a reply to the 10:45 post | yes | https://twitter.com/i/web/status/2108792303611429152 |
| Sat 12:32 | "#neatHack kickoff, 12:30 IST" | yes | https://twitter.com/i/web/status/2108815318541844954 |
| Sat 13:14 | "#neatHack, day one. all three required tools are up" | yes | https://twitter.com/i/web/status/2108826005854937357 |
| Sat 13:26 | "your quickstart is the only part of your product" | yes | https://twitter.com/i/web/status/2108828983194206308 |
| Sat 15:15 | "a quickstart breaks the way an agent breaks" | yes | https://twitter.com/i/web/status/2108856505566921210 |
| Sat 18:15 | "send me your quickstart and FirstRun runs it" | yes | https://twitter.com/i/web/status/2108901819426431407 |
| Sat 18:23 | "4 docs PRs opened on day one of #neatHack" | yes | https://twitter.com/i/web/status/2108903653411021062 |
| Sat 19:11 | "Some containers were harmed in the making of FirstRun" | no | https://twitter.com/i/web/status/2108915865697608147 |
| Sat 19:30 | LinkedIn: "Never let an AI agent fix every failure on its own" | yes | https://www.linkedin.com/feed/update/urn:li:share:7514686677714665473/ |
| Sat 21:15 | "an agent that heals every failure on its own drifts" | yes | https://twitter.com/i/web/status/2108947112809378291 |
| Sun 07:32 | "a maintainer who gets a PR from an agent asks one question" | yes | https://twitter.com/i/web/status/2109102359779365016 |
| Sun 10:32 | "FirstRun had no web UI at kickoff. that was the bet." | no | https://twitter.com/i/web/status/2109147626390097946 |
| Mon 12:00 | "my AI CFO found a bug in my agent", scheduled | | after it posts |
| Mon 13:30 | "4 docs PRs in 48 hours of #neatHack", scheduled | | after it posts |

## Known Limitations and Next Steps

- The Entire Brain watcher does not run on Windows, so Brain runs with `--no-daemon` and is refreshed by hand.

## Submission

Confirmed requirements from https://neatlogs.com/hackathon:

- [x] Uses neatlogs, Entire and cfo.ai, with a clear role for each: [evidence/README.md](evidence/README.md).
- [x] Demo video of 3 minutes or less covering all three tools: [https://www.youtube.com/watch?v=9xxgu_1bH-E](https://www.youtube.com/watch?v=9xxgu_1bH-E), 2:54. The 2:59 long cut stays at [https://www.youtube.com/watch?v=JJNWWhSV9pc](https://www.youtube.com/watch?v=JJNWWhSV9pc).
- [x] Public repo with setup and run instructions, and an MIT [LICENSE](LICENSE).
- [x] Architecture, implementation, runtime, reasoning and result for each tool, in one table: [The Three Tools at a Glance](README.md#the-three-tools-at-a-glance).
- [x] Entire checkpoint link plus its ID: [01M4JGJ6NTE7YNB9Z0YW5FYVHN](https://entire.io/gh/HighnessAtharva/firstrun/commit/3ca6f118ecb0a8915315eea27b5588dd8a7c6299).
- [x] cfo.ai business plan with pricing, costs, revenue and runway: [https://cfo.ai/s/_u5lbrHIl9KX_JQE](https://cfo.ai/s/_u5lbrHIl9KX_JQE) and [business/BUSINESS_PLAN.md](business/BUSINESS_PLAN.md).
- [ ] Quote post on X between 7:00 and 11:55 PM IST on Mon 2026-10-12.
