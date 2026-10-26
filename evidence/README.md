# Evidence

Every claim in the README has a file here or a public link. Nothing in this folder holds a key.

| Claim | Proof |
|---|---|
| Each run is one neatlogs trace, and v2 beat v1 on the same 4 targets | [neatlogs.md](neatlogs.md), [before_after_traces.json](before_after_traces.json), [neatlogs_runs.json](neatlogs_runs.json) |
| A failed step was recovered and verified in a fresh container | [trace-recovered-entire-v2.md](trace-recovered-entire-v2.md) |
| neatlogs found the agent's own bug, and the fix came over MCP | [neatlogs-investigation.md](neatlogs-investigation.md), commit `3ca6f11` |
| 91 of 132 non-merge commits carry their Entire session, and Trails reviewed every layer | [entire.md](entire.md) |
| The build agents used the Entire graph | [graph.ndjson](graph.ndjson), [entire.json](entire.json) |
| The Entire judge ranks the repo with no excluded work | [jury-selftest.txt](jury-selftest.txt) |
| FirstRun found real docs bugs and opened upstream PRs | [dbt #10149](https://github.com/dbt-labs/docs.getdbt.com/pull/10149), [dbt #10150](https://github.com/dbt-labs/docs.getdbt.com/pull/10150), [entireio/cli #2724](https://github.com/entireio/cli/pull/2724), [accuknox/help #671](https://github.com/accuknox/help/pull/671) |
| The jafgen release that broke the dbt guide | [comment on dbt #10149](https://github.com/dbt-labs/docs.getdbt.com/pull/10149#issuecomment-6096827074) |
| Cost per run comes from neatlogs, one trace per row | [../business/drivers.csv](../business/drivers.csv), [../business/BUSINESS_PLAN.md](../business/BUSINESS_PLAN.md) |
| cfo.ai modeled 18 months from the traces, and the old cap runs out of cash in month 14 | [public cfo.ai model](https://cfo.ai/s/_u5lbrHIl9KX_JQE), [../docs/data/cfo-model.json](../docs/data/cfo-model.json) |
| Every run and audit ends with a priced, capped, checkable receipt | [../docs/receipts/](../docs/receipts/), [sample bill](../docs/receipts/FR-20261010-091740-help-accuknox-com.html), `firstrun receipt --check` |
| Audit costs are measured, and the 7 older audits show an estimate from a re-run | [../scripts/audit_cost_estimates.py](../scripts/audit_cost_estimates.py), `cost` in each [board](../docs/audits/) |
| Doc-audit ranks the top 10 tasks and maps contributors to the code they know | [../src/firstrun/nextup.py](../src/firstrun/nextup.py), [../src/firstrun/team.py](../src/firstrun/team.py), [../scripts/audit_team_backfill.py](../scripts/audit_team_backfill.py), [the Doc-audit page](https://firstrun.atharvashah.com/doc-audit/) |
| A coding agent can run both tools from one URL, with JSON output and a preflight | [../docs/agent.md](../docs/agent.md), [../docs/llms.txt](../docs/llms.txt), [../AGENTS.md](../AGENTS.md), [../skills/firstrun/SKILL.md](../skills/firstrun/SKILL.md), [../tests/test_agent_cli.py](../tests/test_agent_cli.py), `firstrun doctor --json` |
| Every rubric claim in one place for judges | [the For Judges page](https://firstrun.atharvashah.com/judges/), [../docs/judges/index.html](../docs/judges/index.html) |
| The plan sets the agent's cost cap, and a live run stopped at it | PR [#15](https://github.com/HighnessAtharva/firstrun/pull/15), neatlogs trace `7060f5bd8dbb8cdc6c1dec3830ba7bab` |
| neatlogs alerts and an AI evaluator watch the runs | [neatlogs.md](neatlogs.md) |
| The session that built and ran FirstRun is public | [Entire session](https://entire.io/gh/HighnessAtharva/firstrun/session/ae05fb29-0c85-4558-9980-42419f08ca9c) |
| Every upstream PR carries a public replay of its run | the proof comments on [#10149](https://github.com/dbt-labs/docs.getdbt.com/pull/10149#issuecomment-6097945132), [#10150](https://github.com/dbt-labs/docs.getdbt.com/pull/10150#issuecomment-6097945350), [#2724](https://github.com/entireio/cli/pull/2724#issuecomment-6097945657), [#671](https://github.com/accuknox/help/pull/671#issuecomment-6097945911) |

These files are a record of the hackathon build. The script that generated them is gone.
