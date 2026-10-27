# Share Format v1

`1stRun share` turns one run folder into a share code. The web viewer at `run.html` turns the code back into the run. No server stores anything: the code travels in the URL fragment, after `#`, which browsers never send to a server.

## Encoding Is JSON, Then Gzip, Then Base64url

1. Build the JSON object below with `separators=(",", ":")`.
2. Compress it with gzip (Python `gzip.compress`, level 9).
3. Encode it as base64url without `=` padding.
4. The link is `https://1run.netlify.app/run.html#r=<code>`.

The browser decodes with `atob` after mapping `-`→`+` and `_`→`/`, then `DecompressionStream("gzip")`.

## The JSON Object

```json
{
  "v": 1,
  "run_id": "20261010-085917-docs-getdbt-com",
  "target": "docs.getdbt.com",
  "title": "Quickstart for dbt Core using DuckDB",
  "source_url": "https://docs.getdbt.com/guides/duckdb",
  "status": "verified",
  "fixture": false,
  "tags": ["real"],
  "started_at": "2026-10-10T08:59:17+00:00",
  "finished_at": "2026-10-10T09:09:30+00:00",
  "time_to_first_success_s": 613.0,
  "tool_calls": 6,
  "cost_usd": 0.06,
  "image": "python:3.11-slim",
  "steps": [
    {
      "id": 10,
      "intent": "Generate more data",
      "command": "jafgen --years 6",
      "status": "passed",
      "attempts": 2,
      "exit_code": 0,
      "duration_s": 4.1,
      "skipped": false,
      "skip_reason": "",
      "error_tail": "Usage: jafgen [OPTIONS] [YEARS]\nError: No such option: --years"
    }
  ],
  "classifications": {
    "10": {"source": "judge", "probabilities": {"docs_bug": 0.91, "environment": 0.05, "product_bug": 0.03, "needs_secret": 0.01}}
  },
  "patches": [
    {"step_id": 10, "old_command": "jafgen --years 6", "new_command": "jafgen 6",
     "failure_class": "docs_bug", "reason": "years is a positional argument.", "source": "usage line"}
  ],
  "gave_up": [],
  "verify": {"status": "verified", "steps_passed": 9, "steps_total": 9},
  "diff": "--- a/duckdb-qs.md\n+++ b/duckdb-qs.md\n...",
  "pr_body": "Fix a broken command in the quickstart...",
  "trace_id": "optional trace id or empty"
}
```

## Limits Keep a Code Short

- `error_tail` holds at most the last 600 characters of the last failed attempt of that step, after secret redaction. stdout comes first and stderr last, so a long install log cannot push the error out.
- `diff` holds at most 4,000 characters and `pr_body` at most 3,000.
- `status` per step is one of `passed`, `failed`, `gave_up`, `skipped`, `pending`, `needs_human`.
- A run status is one of `passed`, `failed`, `verified`, `unverified`.
- Unknown fields are ignored by the viewer, so later versions can add fields.

## Three Fields Feed the Docs Execution Graph

The viewer draws a graph from the docs page to the fresh-container proof. Codes without these fields still render, with less detail.

- `steps[].quote` is the docs sentence the planner copied the command from, at most 240 characters.
- `steps[].tries` lists the last 5 attempts of the step in order, each as `{"command", "exit_code", "passed"}`. A step that failed and then passed shows as "Failed as written" with its rerun.
- `evidence` lists links from `evidence.json` in the run folder. Each item is `{"kind", "label", "url", "public", "step_id"}`. `kind` is one of `trace`, `pr`, `comment`. The encoder drops any URL that does not start with `https://`. `public: false` makes the viewer label the link as needing a login. A `step_id` ties a PR or comment to the step it fixes.

```json
[
  {"kind": "pr", "label": "dbt-labs/docs.getdbt.com#10149", "url": "https://github.com/dbt-labs/docs.getdbt.com/pull/10149", "step_id": 10}
]
```

