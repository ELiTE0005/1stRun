# FirstRun Business Plan

FirstRun runs a dev tool's quickstart in a clean container every night, finds the first step that breaks, proves the fix with a second clean run, and drafts the docs PR. The buyer is a DevRel or docs team at a dev-tool company.

The business plan sets the agent's spending limit. `firstrun econ` reads every neatlogs trace, cfo.ai turns the costs into a per-tier cap, and `firstrun run --tier` stops any run that spends past it.

cfo.ai model, public and read-only: [https://cfo.ai/s/_u5lbrHIl9KX_JQE](https://cfo.ai/s/_u5lbrHIl9KX_JQE)

## Three Tiers Price by Quickstarts Covered

| Tier | Price per month | Quickstarts | Runs per month |
|---|---|---|---|
| Free | $0 | 1, weekly | 4 |
| Team | $49 | 10, nightly | 300 |
| Scale | $299 | 100, nightly, with PRs, Docs Bisect and Prerequisite Proof | 3,000 |

## The Average Run Costs $0.0178, but One in Twenty Costs Three Times That

neatlogs holds 88 `firstrun.run` traces from 2026-10-10 and 2026-10-11. `firstrun econ` reads them and writes [`drivers.csv`](drivers.csv), the file cfo.ai imports. Each quantile row names the trace it came from, so a judge can open the trace behind any cost in the model.

| Driver | Cost per run | neatlogs trace |
|---|---|---|
| Mean | $0.01782 | all 88 |
| p50 | $0.01355 | `2120da35fc8a46c311f4da61c07cff0c` |
| p90 | $0.04424 | `ec246a27f83c9e11d682eb09a1818f58` |
| p95 | $0.05286 | `495d510fd6da5546dbc6ab6e52bcee68` |
| Max | $0.10135 | `a462576e751e91543b5623185331d603` |
| Compute | $0.0020 | assumption: AWS t3.medium at $0.0416 an hour for the measured 175.7 s mean |

The costs are Sonnet 5.5 list price, and Anthropic did not bill them. The 88 traces include development runs, so the spread is wider than a production month would show.

The expensive runs are the useful ones. A run that hits a broken step pays for recovery and for the second clean run. Of 19 real-world runs, 10 ended `verified` with 32 proven patches, and the 19 runs cost $0.97 in total. That is $0.0975 per verified quickstart (source: `runs/*/state.json`).

## The Old $0.50 Cap Let a Scale Customer Cost Five Times the Price

Before this plan, every run had the same cap of $0.50 in `src/firstrun/models.py`. That cap was 30 times the mean run cost, and nothing in the business set it.

| Tier | Revenue per run | Margin at mean cost | Margin at p95 cost | Margin if every run hits $0.50 |
|---|---|---|---|---|
| Team | $0.1633 | 88.6% | 67.7% | -207.3% |
| Scale | $0.0997 | 81.3% | 47.1% | -403.6% |

The mean says both tiers are healthy. The p95 says Scale falls below a 70% margin in a month with many broken quickstarts. The old cap says one bad month can cost a Scale customer's fee five times over.

## The Margin Floor Sets the Cap, and the Agent Enforces It

The founder picks one number, a 70% gross margin floor. The cap for each tier is the model spend one run may use and still keep that floor:

```text
cap per run = price / runs per month x (1 - margin floor) - compute per run
```

If every run in a month hits the cap, the tier still earns 70%. A Free run has no revenue, so its cap is the measured median run.

| Tier | Cap per run | Measured runs over the cap |
|---|---|---|
| Free | $0.0108 | 48.4% |
| Team | $0.0471 | 7.8% |
| Scale | $0.0280 | 25.0% |

`firstrun run <url> --tier scale` loads the cap from [`unit_economics.json`](unit_economics.json). The executor and the recovery agent both check it, and each check is a `budget` GUARDRAIL span in neatlogs. A run that passes the cap stops with `cost budget spent`, and the report names the step where it stopped.

On the typer quickstart, `--tier scale` verified 7/7 steps at $0.0201. `--tier free` stopped at step 4 with `cost budget spent: $0.0115 of $0.0108`.

The cap checks FirstRun's own cost count, which runs 39% above neatlogs on 43 matched runs ($1.5253 against $1.0989). So the cap stops a run early, never late.

## Scale Needs a Fix, and the Data Names Two

A 25% stop rate means Scale customers would see one run in four end early. The price or the allowance has to move. Both fixes come from the same formula.

| Option | Price | Runs per month | Cap per run | Measured runs over the cap |
|---|---|---|---|---|
| Today | $299 | 3,000 | $0.0280 | 25.0% |
| Raise the price | $529 | 3,000 | $0.0510 | 4.7% |
| Halve the allowance | $299 | 1,500 (50 quickstarts) | $0.0579 | 3.1% |

Team at $49 already stops only 7.8% of runs. A $53 price would cover the p95 run at the floor.

## The Planner Fix From the Traces Cut Cost per Run by 24%

neatlogs Detections and an Investigate run found the planner inventing steps. The fix shipped in commit 3ca6f11. The same 4 targets, before and after, as neatlogs measured them:

| Agent | Model cost per run | Quickstarts finished | Failed steps recovered |
|---|---|---|---|
| v1 | $0.0262 | 2 of 4 | 0 |
| v2 | $0.0200 | 3 of 4 | 3 |

## cfo.ai Shows the Old Cap Runs Out of Cash in Month 14

Ari built the model in cfo.ai over MCP, in workspace "Atharva CFOAI", page "FirstRun model". Every formula reads its number from a "FirstRun drivers" table, and its "Driver source" column names the neatlogs trace behind each measured cost. The figures below were read back from cfo.ai, not computed by hand. Cost per run is $0.01862, the 64-trace mean plus compute. Gross margin includes Stripe fees.

| Scenario | Scale gross margin | Team gross margin | Month 18 MRR | Month 18 cash |
|---|---|---|---|---|
| Base | 77.1% | 84.3% | $2,069 | $16,685 |
| Growth | 77.1% | 84.3% | $5,427 | $44,674 |
| Tail month: every run at p95 cost | 41.9% | 62.9% | $2,069 | $12,503 |
| Old cap: every Scale run at $0.50 | -406.7% | 84.3% | $2,069 | -$12,212 |
| Scale at $529 | 85.8% | 84.3% | $2,875 | $21,146 |
| Scale at 1,500 runs | 87.0% | 84.3% | $2,069 | $17,280 |

Under the old cap, cash first goes negative in December 2027, month 14. Every other Scenario has positive net cash flow, so cfo.ai shows no runway limit. Raising Scale to $529 earns the most cash. Halving the Scale allowance keeps the $299 price and still clears the 70% floor.

## Both Scenarios Pay Back Fixed Costs in Month 2

This hand-built table came before the cfo.ai model and uses the v1 cost of $0.02771 per run. The cfo.ai table above uses the 64-trace cost, so its month 18 cash is higher.

Both scenarios start with $5,000 cash on 2026-11-01. Fixed costs are $25 a month. Monthly churn is 10% on Free, 5% on Team and 3% on Scale. Stripe takes 2.9% plus $0.30 per paid invoice.

- **Base:** 10 new Free users a month. 1 new Team customer a month in months 2 to 6, then 2 a month. 1 new Scale customer in months 9, 12, 15 and 18.
- **Growth:** 30 new Free users a month. 3 new Team customers a month. 1 new Scale customer a month from month 4.

| Scenario | Month | Free | Team | Scale | MRR | Costs | Cumulative cash |
|---|---|---|---|---|---|---|---|
| Base | 1 | 10.0 | 0.0 | 0.0 | $0 | $26 | $4,974 |
| Base | 6 | 46.9 | 4.5 | 0.0 | $222 | $76 | $5,377 |
| Base | 12 | 71.8 | 13.9 | 1.9 | $1,254 | $349 | $8,578 |
| Base | 18 | 85.0 | 20.8 | 3.5 | $2,069 | $566 | $15,747 |
| Growth | 1 | 30.0 | 3.0 | 0.0 | $147 | $58 | $5,089 |
| Growth | 6 | 140.6 | 15.9 | 2.9 | $1,649 | $468 | $8,268 |
| Growth | 12 | 215.3 | 27.6 | 8.0 | $3,741 | $1,062 | $20,757 |
| Growth | 18 | 255.0 | 36.2 | 12.2 | $5,428 | $1,542 | $41,180 |

Customer counts are expected values, so they carry decimals. No salary is paid. With zero paying customers, $5,000 lasts about 190 months. One Team customer covers the $25 fixed costs. No customer has paid yet, so every customer count above is an assumption.

## Rebuild the Model From the Traces

1. Run `firstrun econ`. It reads neatlogs and rewrites `drivers.csv` and `unit_economics.json`.
2. Attach `drivers.csv` and `inputs.json` to Ari in cfo.ai, and paste the prompt below.
3. Run `firstrun run <url> --tier <name>`. The agent now spends inside the cap the plan set.

```text
FirstRun is an AI agent that runs a dev tool's quickstart docs in a clean container every night and drafts a docs pull request when a step breaks. Customers are DevRel and docs teams at developer tool companies.

Use the attached drivers.csv for every cost. Rows with measured=yes come from neatlogs traces, and the source column names the trace. Keep that source on each Variable. Rows with measured=no are assumptions, so label them as assumptions.

Plans: Free at $0 (4 runs a month), Team at $49 (300 runs a month), Scale at $299 (3,000 runs a month). Cost per run is cost_per_run_mean plus compute_per_run. Add Stripe at 2.9% plus $0.30 per paid invoice, $25 fixed costs a month and no founder salary. Start with $5,000 cash on 2026-11-01 and model 18 months. Use the customer additions and churn rates in inputs.json for a Base and a Growth Scenario.

Then make four more Scenarios from Base and compare them with Base on gross margin per plan, ending cash and runway:
1. "Tail month": cost per run is cost_per_run_p95 for every run.
2. "Old cap": cost per run is $0.50 for every Scale run, the cap before this plan.
3. "Scale at $529": Scale price $529, runs unchanged.
4. "Scale at 1,500 runs": Scale price $299, Scale runs 1,500.

Show customers per plan, MRR, gross margin per plan, operating costs, ending cash and cash runway.
```
