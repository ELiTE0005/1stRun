# FirstRun Compared With the Alternatives

| Feature | FirstRun | Claude Code | GitHub Actions | GitHub Agents | Custom workflow |
|---|---|---|---|---|---|
| Runs the quickstart as a new developer | Every step runs in a fresh Docker container | Runs on your machine. An optional OS sandbox limits files and network | A fresh runner per job, but you script every step | Works in its own Actions-powered VM, on your repo, not a new-user setup | Only as clean as the environment you build |
| Plans steps from a docs URL | The planner writes one step per command | When you prompt it with the page | You write each step | Starts from an issue or task, not a docs page | You write the parser |
| Improvises when a step fails | Classifies the failure, patches, retries up to 3 times per step | Iterates inside one session | The job fails and stops | Iterates in one session and pushes commits to its draft PR | Only what you code |
| Proves the fix | A second clean container must pass the whole quickstart | Only if you ask for it | Only if you script a second run | Your repo's own tests and CI, not a clean-user rerun | Only if you code it |
| Telemetry per run | neatlogs spans for planner, executor and verifier. Measured cost of $0.02 per run | OpenTelemetry metrics and events, such as cost and tokens. Set up through environment variables | Logs and run history. No agent traces | A session log you can read or stream. No cost trace you own | You build it |
| Opens the docs PR | After you approve once | When you ask | Only if you script it | Opens a draft PR and asks you for review | Only if you code it |
| Ease of use | Paste a docs URL, then paste the prompt into your coding agent | One prompt, but you define the test and the clean setup | A YAML file per quickstart | Assign an issue to Copilot | Highest effort |
| Proof in public repos | 4 upstream PRs, all open (see the record above) | Not specific to docs | Not specific to docs | Not specific to docs | Depends on your build |

FirstRun reads a docs quickstart and runs every step in a clean container, the way a new developer would. It stops at the first failure and classifies it. It tries a fix up to 3 times, then proves the fix with a second clean run. It asks once before it opens a PR.

FirstRun opened 4 upstream docs PRs, and all are open today. The dbt DuckDB quickstart had a broken `jafgen` command (#10149) and no stated Python version (#10150). The Entire CLI installer put `entire` on a path that a clean shell lacks (entireio/cli#2724). The AccuKnox `knoxctl` page named 0.9.0 as the latest release while its installer fetched 0.9.58, and its APT steps assume `curl`, `gnupg` and `sudo` (accuknox/help#671). MkDocs and Dagster passed with no docs change, so a run also shows when docs hold up.

Every run is a neatlogs trace, so a bad run has a readable cause. A docs bug surfaces in a run instead of in a reader who leaves without filing an issue. The four PRs now wait for maintainer review.

Sources for the GitHub Agents and Claude Code columns: GitHub docs on the Copilot coding agent and the Claude Code monitoring and sandboxing docs.
