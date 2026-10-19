# Neatlogs integration

Result: **PARTIAL**. Every in-scope capability has a capture path, and the main path was read back from persisted traces. `--resume` and `--targets` have no run of their own. See "Open limits".

Date: 2026-10-10. SDK: `neatlogs` 1.4.26 (latest stable, Doctor v2). CLI: `neatlogs-cli@0.2.0`, profile `work`. Project UUID: `e6bcef18-b18b-4745-90b1-3691c29c2493`. Readback actor: OAuth user, scope `project:read`.

## Coverage Table

All capabilities start at one entry point: `firstrun run <url>` (`src/firstrun/cli.py`, `_run_one`). One `firstrun.run` WORKFLOW trace wraps everything. Providers: Claude Agent SDK (wrapped by `neatlogs.wrap`), Jev (TypeSafe), Firecrawl and Docker, all captured as spans inside that trace.

| Capability | Trigger | Expected trace boundary | Verification command | Evidence trace ID | Status |
|---|---|---|---|---|---|
| Whole run, success with recovery | `firstrun run <url>` | WORKFLOW `firstrun.run`, status OK when VERIFIED | `firstrun run tests/fixtures/docs/curl_missing_FIXTURE.md --tag check` | `76f9f07ce0f45d9f1740444ac554b8a5` | PASS |
| Whole run, success, long path | same | same, 26 spans | `firstrun run tests/fixtures/docs/broken_quickstart_FIXTURE.md --tag check` | `1791e8263c8c06fc3ad5dcc56e26a18a` | PASS |
| Whole run, safe error | same, docs unreachable | WORKFLOW ERROR with `error` payload | `firstrun run https://httpbin.org/status/404 --tag check` | `de25873fe939cef49ff9121974130c2d` | PASS |
| `read_docs` | planner start | TOOL child of root, input url, output markdown | same as row 1 | `76f9f07ce0f45d9f1740444ac554b8a5` | PASS (error case: `de25873f...`) |
| `planner` + Claude query | after read_docs | AGENT, child AGENT `claude_agent.query`, child LLM span with messages, model, tokens | same as row 1 | `76f9f07ce0f45d9f1740444ac554b8a5` | PASS |
| `step.<id>` | each runbook step, replay, verify | TOOL, input command, output exit code and stdout/stderr tail, ERROR status when the step fails | same as row 2 | `1791e8263c8c06fc3ad5dcc56e26a18a` (step.3 ERROR, then OK after patch) | PASS |
| `classify_failure` | failed step | TOOL under `recover.<id>`, input error text, output probabilities and source | same as row 2 | `1791e8263c8c06fc3ad5dcc56e26a18a` | PASS |
| `recover.<id>` | failed step | AGENT, nested budget, classify, Claude fix search with WebFetch TOOL and LLM spans | same as row 2 | `1791e8263c8c06fc3ad5dcc56e26a18a` | PASS |
| `budget` | each recovery | GUARDRAIL, input attempts and cost, output passed and reason | same as row 1 | `76f9f07ce0f45d9f1740444ac554b8a5` | PASS (a tripped budget is not run) |
| `verify` | after a patched pass | GUARDRAIL, child step spans, output per-step results | same as row 1 | `76f9f07ce0f45d9f1740444ac554b8a5` | PASS |
| `--resume RUN_ID` | CLI flag | same root, replay steps with logs | none | none | UNVERIFIED |
| `--targets FILE` | CLI flag | one trace per URL, same path as row 1 in a loop | none | none | UNVERIFIED (shared code) |
| Concurrency, streaming, distributed | n/a | n/a | n/a | n/a | Not used by the app |

Exclusions: `firstrun report` (no AI call), `--offline` planner (no model call, test path), `tracing.hello` (smoke test, workflow `firstrun.hello`).

Typed LLM spans exist for Claude calls only. A Jev call (TypeSafe) is not an SDK-wrapped provider, so it shows as the `classify_failure` TOOL with `source: jev` in its output.

## Gates

| Gate | Result | Evidence |
|---|---|---|
| 1. Coverage map and guidance | PASS | Table above. Guidance loaded: docs index, Python SDK, Claude Agent SDK integration, SDK Doctor. |
| 2. Ingest and readback | PASS | Ingest key `NEATLOGS_API_KEY` loads through `firstrun.config.load_env()`. CLI `whoami` returned the OAuth user and project UUID above, and `traces list` returned traces. |
| 3. Trace contract | PASS | Local Doctor: `python -m neatlogs doctor --local --json` returned `pass`, SDK 1.4.26. Probe: `doctor --probe --json` returned `pass` on 8 checks, trace `6cbfa9d87418626960fc1d2e21a90f94`. |
| 4. Evidence loop | PARTIAL | 3 real runs read back with trace details, span list and payloads: parents, payloads, status and finalization checked. `--resume` and `--targets` not run. |
| 5. Proof and repeatable loop | PASS | This file. |

Offline suite: `.venv\Scripts\python -m pytest -q -p no:cacheprovider` gives 148 passed, 23 skipped, 1 xfailed.

## What Changed

Gaps found by reading the first check run (`452add41933c88edf12207f9ab89254f`) back:

- The `read_docs` span was stored as `firecrawl`, because `tool_name="firecrawl"` overrides the span name. Fixed in `src/firstrun/planner.py` by dropping `tool_name`. The span name now matches the spec.
- `step.<id>` spans had no input or output, and a failed step had status OK. Fixed in `src/firstrun/executor.py` (`run_step`): input is the command and file paths, output is exit code and the last 2000 characters of stdout and stderr, status is ERROR on a failed step.
- The root span output held the planner's runbook instead of the run result. Fixed in `src/firstrun/cli.py`: input is url, run id and tags, output is final status, stop reason, step and patch counts. Root status is ERROR unless the run is PASSED or VERIFIED, and for an early stop.
- `recover.<id>`, `budget` and `verify` had no payloads. Fixed in `src/firstrun/recovery.py`, `src/firstrun/budget.py` and `src/firstrun/verify.py`. A give-up, a tripped budget and an unverified run set ERROR.
- Added helpers `set_io` and `mark_error` in `src/firstrun/tracing.py`. Both swallow their own errors, so telemetry never breaks a run. `close_tracing` now catches flush errors.
- `tests/conftest.py` leaked about 50 empty `neatlogs-app` traces into the project on each pytest run. `neatlogs.wrap` boots its own exporter when `NEATLOGS_API_KEY` is set, and `config.load_env` read the key from `.env`. The fixture now sets the key to an empty string, which `load_env` does not overwrite. A pytest run after the fix created 0 traces.

No span name or kind changed.

## Repeat the Evidence Loop

Environment variable names: `NEATLOGS_API_KEY` (project ingest key, in `D:\Atharva\NOTES\.env`, loaded at run time). Never set `NEATLOGS_TOKEN` and `NEATLOGS_API_KEY` together for the CLI.

1. Run with a fresh tag, and note the UTC time before it:
   `$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\firstrun.exe run tests/fixtures/docs/curl_missing_FIXTURE.md --tag check`
2. Read back with the key removed from the CLI child environment:
   `env -u NEATLOGS_API_KEY -u NEATLOGS_TOKEN npx --yes -p node@22 -p neatlogs-cli@0.2.0 -- neatlogs --profile work --json traces list --limit 5 --from <UTC time>`
   In PowerShell, run the same command from a child process that clears both variables first.
3. Then: `traces spans list <trace-id> --limit 50` and `traces payload <trace-id> <span-id> --fields input,output,error`. The `--fields` flag is required.
4. Match the trace by its `check` tag and start time. Wait for `finalizationStatus` to be `finalized`.
5. Local Doctor: `.venv\Scripts\python -m neatlogs doctor --local --json`. Probe: `doctor --probe --json` with the key in the environment.

## Open Limits

- The trace-level status is ERROR when any child span is ERROR, even when the root is OK. A recovered run (for example `76f9f07c...`) therefore lists as ERROR at trace level. The failing step span is the useful signal, so this is kept.
- LLM span prompt tokens count fresh input only, and cache tokens are not in them. The SDK's per-turn LLM span shows a duration of 0 ms. Cost per run stays accurate in `state.json`, not in the trace totals.
- The 404 case reported `Insufficient credits` from Firecrawl slot 1. The app fell back to a plain GET and the trace is correct, but the Firecrawl key needs `keys.py activate` before the next live run.
- The earlier empty `neatlogs-app` traces (about 50, from 2026-10-10 08:14 UTC and before) still sit in the project. Deleting them is permanent, so it needs Atharva's go-ahead (`traces delete <id>`).
- Browser dashboard checks were not done. No login was attempted.
