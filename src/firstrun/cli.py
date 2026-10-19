"""Track T2. `firstrun run <url>`, `--targets`, `--resume`, and `firstrun report`."""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
from pathlib import Path

import click

from firstrun import config
from firstrun.models import RunState, RunStatus


def _recover_fn(budget=None):
    """Layer 2 recovery: classify, ask once, search, patch."""
    from functools import partial

    from firstrun.recovery import recover

    return partial(recover, budget=budget) if budget else recover


def _verify():
    """Model-free re-run of the patched runbook in a brand-new container."""
    from firstrun.verify import verify

    from firstrun import state as state_io

    return lambda runbook, state: verify(runbook, state.patches, pins=state_io.load_pins(state.run_id))

def _elapsed_s(state: RunState) -> float:
    """Wall time of a run from its ISO timestamps. 0 when either is missing."""
    from datetime import datetime

    try:
        return (datetime.fromisoformat(state.finished_at) - datetime.fromisoformat(state.started_at)).total_seconds()
    except (TypeError, ValueError):
        return 0.0


def _first_error_line(state: RunState) -> str:
    for r in reversed(state.results):
        if not r.passed:
            for text in (r.stderr, r.stdout):
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                if lines:
                    return re.sub(r"^/tmp/\.fr_step\.sh: line \d+: ", "", lines[-1])[:120]
            return "timed out" if r.timed_out else f"exit {r.exit_code}"
    return state.stop_reason


def _summary(state: RunState, commands: dict[int, str]) -> list[str]:
    from firstrun.report import reported_failed_step

    total = len(commands)
    passed = sum(1 for s in state.step_status.values() if s.value == "passed")
    fid = reported_failed_step(state)
    if state.status == RunStatus.FAILED and fid is not None:
        return [f"✗ step {fid}/{total}  {commands.get(fid, '')}  ->  {_first_error_line(state)}"]
    if state.status == RunStatus.FAILED and state.stop_reason:
        return [f"✗ {state.stop_reason}"]
    secs = state.time_to_first_success_s or 0
    mark = "✓" if state.status != RunStatus.FAILED else "✗"
    return [f"{mark} {state.status.value} {passed}/{total} steps, {secs:.0f} s, ${state.usage.cost_usd:.2f}"]


# A run that stops for one of these reasons never started a container. The exit code is 2, not 1.
EARLY_STOPS = ("no runnable steps", "out of scope", "docs unreachable", "planner failed", "model auth failed",
               "docker unavailable")


def exit_code(state: RunState) -> int:
    if state.status != RunStatus.FAILED:
        return 0
    return 2 if state.stop_reason.startswith(EARLY_STOPS) else 1


DOCKER_FIX = "Docker is not running in WSL. Start it: wsl -d Ubuntu-22.04 sudo service docker start"
AUTH_FIX = "Claude auth is missing or expired. Add CLAUDE_CODE_OAUTH_TOKEN to your .env (run: claude setup-token)"


def friendly(reason: str) -> str:
    """One sentence plus the fix for a setup failure. Any other reason passes through."""
    low = reason.lower()
    if low.startswith("docker unavailable"):
        return DOCKER_FIX
    if low.startswith("model auth failed"):
        return AUTH_FIX
    return reason


def _setup_exit(message: str, code: str = ""):
    click.echo(f"✗ {message}")
    _json_error(code or error_code(message) or "setup_failed", message)
    sys.exit(2)


# --- --json for agents ---------------------------------------------------------
# With --json a command prints ONE JSON object on stdout. Every human line goes to stderr.
# The keys are documented in docs/agent.md. Add keys freely, never rename or drop one.

# (reason prefix or fragment, machine code). The first match wins.
ERROR_CODES = (
    ("docker unavailable", "docker_unavailable"), ("docker is not running", "docker_unavailable"),
    ("model auth failed", "auth_missing"), ("claude auth is missing", "auth_missing"),
    ("docs unreachable", "docs_unreachable"), ("no runnable steps", "no_runnable_steps"),
    ("out of scope", "out_of_scope"), ("planner failed", "planner_failed"),
    ("budget spent", "budget_spent"), ("needs_human", "needs_human"), ("secret", "needs_secret"),
    ("timed out", "step_timeout"), ("clone failed", "clone_failed"), ("unknown run id", "unknown_run_id"),
    ("no audit found", "not_found"), ("no runs found", "not_found"), ("no verified run", "not_found"),
)

_JSON: dict | None = None  # the object a --json command is building, or None


def error_code(reason: str) -> str:
    low = (reason or "").lower()
    return next((code for frag, code in ERROR_CODES if frag in low), "")


def _json_error(code: str, message: str, fix: str = "") -> None:
    if _JSON is not None and not _JSON.get("error"):
        _JSON["error"] = {"code": code, "message": message, "fix": fix}


@contextlib.contextmanager
def _json_out(command: str, enabled: bool):
    """Yield the dict to fill. Human output goes to stderr. The dict is printed on exit, also on an error exit."""
    global _JSON
    if not enabled:
        yield {}
        return
    _JSON = {"ok": True, "command": command, "exit_code": 0, "error": None}
    real, code = sys.stdout, 0
    try:
        with contextlib.redirect_stdout(sys.stderr):
            yield _JSON
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        raise
    except click.ClickException as exc:
        code = exc.exit_code
        _json_error(error_code(exc.format_message()) or "error", exc.format_message())
        raise
    except BaseException as exc:
        code = 1
        _json_error("internal", f"{exc.__class__.__name__}: {exc}"[:300])
        raise
    finally:
        out, _JSON = _JSON, None
        out["exit_code"] = code
        if code and not out["error"]:  # a failed run carries its own error. Lift the first one to the top.
            out["error"] = next((r["error"] for r in out.get("runs", []) if r.get("error")), None)
        out["ok"] = code == 0 and not out["error"]
        real.write(json.dumps(out, ensure_ascii=False, default=str) + "\n")
        real.flush()


def run_json(run_id: str, cached: bool = False) -> dict:
    """The --json record of one run folder, read back from disk."""
    from firstrun import state as state_io
    from firstrun.report import reported_failed_step

    d = state_io.run_dir(run_id).resolve()
    st = state_io.load_state(run_id)
    try:
        steps = [s for s in state_io.load_runbook(run_id).steps if not s.skipped_out_of_scope]
    except (OSError, ValueError):
        steps = []
    files = {name: str(d / name) if (d / name).exists() else None
             for name in ("state.json", "runbook.json", "report.md", "patch.diff", "pr_body.md", "receipt.json")}
    share_url = None
    try:
        from firstrun import share

        share_url = share.link_for_run(d)[0]
    except Exception:  # noqa: BLE001 - the share link is optional
        pass
    rec = {
        "run_id": st.run_id, "source_url": st.source_url, "target": state_io.target_name(st.source_url),
        "status": st.status.value, "stop_reason": st.stop_reason, "cached": cached,
        "steps_total": len(steps), "steps_passed": sum(1 for s in st.step_status.values() if s.value == "passed"),
        "first_failed_step": st.first_failed_step, "reported_failed_step": reported_failed_step(st),
        "patches": len(st.patches), "verified": st.status == RunStatus.VERIFIED,
        "time_to_first_success_s": st.time_to_first_success_s, "elapsed_s": _elapsed_s(st),
        "cost_usd": round(st.usage.cost_usd, 6), "run_dir": str(d), "files": files, "share_url": share_url,
        "error": None,
    }
    if st.status == RunStatus.FAILED:
        why = st.stop_reason or _first_error_line(st)
        code = error_code(why) or ("step_failed" if reported_failed_step(st) is not None else "failed")
        rec["error"] = {"code": code, "message": why, "fix": friendly(why) if friendly(why) != why else ""}
    return rec


def _quiet_logs() -> None:
    """neatlogs logs at INFO. Show that only when FIRSTRUN_DEBUG=1."""
    import logging

    if os.environ.get("FIRSTRUN_DEBUG") == "1":
        return
    for name in ("neatlogs", "opentelemetry"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _early_stop(url: str, run_id: str, reason: str) -> RunState:
    """Write state.json and report.md for a run that could not start. No container is touched."""
    from datetime import datetime, timezone

    from firstrun import report, state as state_io
    from firstrun.models import Runbook

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state = RunState(run_id=run_id, source_url=url, status=RunStatus.FAILED, stop_reason=reason,
                     started_at=now, finished_at=now)
    runbook = Runbook(source_url=url, steps=[])
    state_io.save_runbook(run_id, runbook)
    state_io.save_state(state)
    report.write_report(state, runbook)
    click.echo(f"✗ {friendly(reason)}")
    click.echo(f"report: {state_io.run_dir(run_id) / 'report.md'}")
    return state


def _echo_share(run_dir) -> None:
    try:
        from firstrun import share

        click.echo(f"share: {share.link_for_run(run_dir)[0]}")
    except Exception:  # noqa: BLE001 - a share failure never breaks a run
        pass
    try:
        from firstrun import publish

        out = publish.publish_run(run_dir)
        if out:
            click.echo(f"site log: {out} (commit docs/runs to show it on the site)")
    except Exception:  # noqa: BLE001 - a publish failure never breaks a run
        pass


def _run_one(url: str, tags: list[str], resume: str | None, verify: bool, recover: bool = True,
             budget=None) -> RunState:
    import neatlogs

    from firstrun import executor, patch, planner, state as state_io
    from firstrun.report import reported_failed_step
    from firstrun.tracing import init_tracing, mark_error, set_io

    init_tracing(tags)
    _quiet_logs()
    run_id = resume or state_io.new_run_id(url)
    source = state_io.load_runbook(resume).source_url if resume else url
    attrs = {
        "target": state_io.target_name(source),
        "run_id": run_id,
        "variant": tags[0] if tags else "dev",
        "tags": list(tags),
    }
    planner.LAST_USAGE.clear()
    click.echo(f"target: {attrs['target']}")
    # One trace per run: reading the docs, planning, every step and verification.
    from firstrun.tracing import session_attrs

    with neatlogs.trace("firstrun.run", kind="WORKFLOW", **attrs,
                        **session_attrs(attrs["target"], "run", variant=attrs["variant"])) as root:
        set_io(root, input={"url": source, "run_id": run_id, "resume": bool(resume), "tags": list(tags)})
        try:
            runbook = state_io.load_runbook(resume) if resume else planner.plan(url)
        except planner.PlanError as exc:
            neatlogs.log("run stopped before step 1: {why}", level="error", why=exc.reason)
            set_io(root, output={"status": "failed", "stop_reason": exc.reason})
            mark_error(root, exc.reason)
            return _early_stop(url, run_id, exc.reason)
        final = executor.run(
            runbook, run_id=run_id, resume=bool(resume), tags=tags,
            recover=_recover_fn(budget) if recover else None,
            verify=_verify() if verify else None,
            budget=budget,
            trace=False,
        )
        set_io(root, output={
            "status": final.status.value, "stop_reason": final.stop_reason,
            "steps": len(runbook.steps), "patches": len(final.patches),
            "first_failed_step": final.first_failed_step,
            "reported_failed_step": reported_failed_step(final),
            "time_to_first_success_s": final.time_to_first_success_s,
        })
        if final.status not in (RunStatus.PASSED, RunStatus.VERIFIED):
            mark_error(root, f"{final.status.value}: {final.stop_reason}"[:300])
    if planner.LAST_USAGE:
        final.usage.input_tokens += int(planner.LAST_USAGE.get("input_tokens", 0))
        final.usage.output_tokens += int(planner.LAST_USAGE.get("output_tokens", 0))
        final.usage.cost_usd += float(planner.LAST_USAGE.get("cost_usd", 0.0))
    state_io.save_state(final)
    run_dir = state_io.run_dir(final.run_id)
    from firstrun import report

    report.write_report(final, runbook)
    written = patch.write_outputs(run_dir, final, runbook)
    commands = {s.id: s.command for s in runbook.steps}
    lines = _summary(final, commands)
    for line in lines:
        click.echo("✗ " + friendly(line[2:]) if line.startswith("✗ ") else line)
    if not lines[0].startswith("✓") and final.status == RunStatus.FAILED:
        click.echo(f"ran {_elapsed_s(final):.0f} s, ${final.usage.cost_usd:.2f} list price")
    click.echo(f"report: {run_dir / 'report.md'}")
    for path in written:
        click.echo(f"wrote {path}")
    _echo_share(run_dir)
    return final

class _UrlGroup(click.Group):
    """`firstrun <url>` and `firstrun ./path` mean `firstrun run <url>`."""

    def parse_args(self, ctx, args):
        if args and args[0] not in self.commands and args[0] not in ("--help", "-h"):
            args = ["run", *args]
        return super().parse_args(ctx, args)


@click.group(cls=_UrlGroup)
def cli() -> None:
    """FirstRun: run a quickstart in a fresh container and find the step that breaks."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


@cli.command("run")
@click.argument("url", required=False)
@click.option("--targets", type=click.Path(exists=True, dir_okay=False), help="File with one URL per line.")
@click.option("--resume", "resume_id", help="Resume the run with this id.")
@click.option("--tag", "tags", multiple=True, help="Trace tag. The first one is the variant.")
@click.option("--offline", is_flag=True, help="Plan without a model.")
@click.option("--no-verify", is_flag=True, help="Skip the verification re-run.")
@click.option("--no-recover", is_flag=True, help="Layer 1 only: stop at the first failed step.")
@click.option("--fresh", is_flag=True, help="Ignore a cached result and run again.")
@click.option("--tier", help="Cap spend per run at this plan tier's cap from business/unit_economics.json.")
@click.option("--json", "as_json", is_flag=True, help="Print one JSON object on stdout. Logs go to stderr.")
def run_cmd(url, targets, resume_id, tags, offline, no_verify, no_recover, fresh, tier, as_json) -> None:
    with _json_out("run", as_json) as out:
        out["runs"] = []
        _run_cmd(url, targets, resume_id, tags, offline, no_verify, no_recover, fresh, tier, out["runs"])


def _record(records: list, run_id: str, cached: bool = False) -> None:
    """Add a run's --json record. Only in --json mode, and a failure to read it back never breaks the run."""
    if _JSON is None:
        return
    try:
        records.append(run_json(run_id, cached))
    except Exception as exc:  # noqa: BLE001
        records.append({"run_id": run_id, "error": {"code": "unreadable", "message": str(exc)[:200], "fix": ""}})


def _run_cmd(url, targets, resume_id, tags, offline, no_verify, no_recover, fresh, tier, records: list) -> None:
    if offline:
        os.environ["FIRSTRUN_OFFLINE"] = "1"
    if not (url or targets or resume_id):
        raise click.UsageError("give a URL, --targets FILE or --resume RUN_ID")
    budget = None
    if tier:
        from firstrun import econ

        try:
            budget = econ.budget_for_tier(tier)
        except econ.EconError as exc:
            raise click.ClickException(str(exc))
        click.echo(f"tier: {tier}, cost cap ${budget.cost_usd_per_run:.4f} per run")
    urls: list[str] = []
    if url:
        urls.append(url)
    if targets:
        for line in Path(targets).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    from firstrun import state as state_io
    from firstrun.tracing import close_tracing

    config.load_env()
    if not fresh and not resume_id:
        from firstrun import cache

        todo = []
        for u in urls:
            hit = cache.find_recent(u)
            if hit:
                click.echo(cache.describe(hit))
                click.echo(f"report: {state_io.run_dir(hit) / 'report.md'}")
                _echo_share(state_io.run_dir(hit))
                _record(records, hit, cached=True)
            else:
                todo.append(u)
        urls = todo
        if not urls:
            sys.exit(0)
    if not offline and not resume_id and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        _setup_exit(AUTH_FIX)
    if resume_id and not (state_io.run_dir(resume_id) / "state.json").exists():
        raise click.ClickException(f"unknown run id: {resume_id}. Nothing to resume, no run was started.")
    worst = 0
    try:
        if resume_id:
            final = _run_one("", list(tags), resume_id, not no_verify, not no_recover, budget)
            _record(records, final.run_id)
            worst = exit_code(final)
        for u in urls:
            final = _run_one(u, list(tags), None, not no_verify, not no_recover, budget)
            _record(records, final.run_id)
            worst = max(worst, exit_code(final))
    except Exception as exc:  # noqa: BLE001 - setup failures get one sentence, not a traceback
        from firstrun import llm, planner
        from firstrun.sandbox import DockerUnavailable

        if isinstance(exc, DockerUnavailable):
            _setup_exit(DOCKER_FIX)
        if isinstance(exc, llm.ModelAuthError):
            _setup_exit(AUTH_FIX)
        if isinstance(exc, planner.PlanError):
            _setup_exit(friendly(exc.reason))
        raise
    finally:
        close_tracing()
    sys.exit(worst)


@cli.command("report")
@click.option("--html", "html", is_flag=True, help="Also write an HTML report.")
def report_cmd(html) -> None:
    from firstrun import report

    click.echo(report.summary_table(config.RUNS_DIR))
    if html:
        try:
            from firstrun import report_html
        except ImportError:
            raise click.ClickException("firstrun.report_html is not built yet")
        out = Path("report") / "index.html"
        out.parent.mkdir(exist_ok=True)
        extras = report_html.load_evidence(Path("evidence"), config.RUNS_DIR)
        report_html.write_html(config.RUNS_DIR, out, extras)
        click.echo(f"html: {out}")


@cli.command("receipt")
@click.argument("run_id", required=False)
@click.option("--tier", help="The plan tier that bills this run. It is marked on the receipt.")
@click.option("--html", "html", is_flag=True, help="Also write receipt.html.")
@click.option("--check", "check_path", type=click.Path(exists=True, dir_okay=False),
              help="Verify a receipt.json and the run files beside it. Writes nothing.")
@click.option("--all-published", "all_published", is_flag=True,
              help="Write a receipt into docs/receipts for every run and audit the site lists.")
@click.option("--hash-only", is_flag=True, help="With --check: check the receipt hash only, for a receipt fetched from the site.")
@click.option("--json", "as_json", is_flag=True, help="Print one JSON object on stdout. Logs go to stderr.")
def receipt_cmd(run_id, tier, html, check_path, all_published, hash_only, as_json) -> None:
    """Write receipt.json and receipt.md for a run or a doc audit: work, price, caps or limits, proof and file hashes."""
    with _json_out("receipt", as_json) as out:
        _receipt_cmd(run_id, tier, html, check_path, all_published, out, hash_only)


def _receipt_fields(r: dict, files: list) -> dict:
    """The --json record of one written receipt."""
    audit = r.get("kind") == "audit"
    price = r["price"]["usd"] if audit else round(r["price"]["model_cost_usd"] + r["price"].get("compute_per_run_usd", 0), 6)
    return {"receipt_id": r["receipt_id"], "kind": "audit" if audit else "run", "hash": r["hash"],
            "price_usd": price, "price_basis": r["price"].get("basis", ""),
            "verified": None if audit else bool(r["proof"]["verified"]),
            "cards": r["proof"].get("cards") if audit else None,
            "cards_citing_evidence": r["proof"].get("cards_citing_evidence") if audit else None,
            "files": [str(Path(f).resolve()) for f in files]}


def _receipt_cmd(run_id, tier, html, check_path, all_published, out: dict, hash_only: bool = False) -> None:
    from firstrun import econ, receipt, state as state_io

    if all_published:
        from firstrun import publish

        site = publish.find_site_dir()
        if site is None:
            raise click.ClickException("docs/runs not found. Run this inside the firstrun checkout or set FIRSTRUN_SITE_DIR.")
        done = receipt.publish_all(site.parent, Path(config.RUNS_DIR))
        click.echo(f"wrote {done['runs']} run receipts and {done['audits']} audit receipts to {site.parent / 'receipts'}"
                   + (f", redrew {done['redrawn']} more" if done["redrawn"] else ""))
        for item in done["skipped"]:
            click.echo(f"skipped {item}: no run folder or no unit economics")
        out.update(mode="all_published", **{k: done[k] for k in ("runs", "audits", "redrawn", "skipped")})
        return
    if check_path:
        problems = receipt.check(Path(check_path))
        if hash_only:  # a receipt fetched from the site has no run files beside it
            problems = [p for p in problems if "hash does not match" in p]
        for p in problems:
            click.echo(f"FAIL: {p}")
        hash_ok = not any("hash does not match" in p for p in problems)
        out.update(mode="check", path=str(check_path), valid=not problems, hash_ok=hash_ok, hash_only=hash_only,
                   problems=problems)
        if problems:
            _json_error("receipt_invalid", "; ".join(problems), "" if not hash_ok else
                        "The receipt itself is unchanged, but its run files are missing or differ. For a receipt from "
                        "the site, add --hash-only. Otherwise check it inside the run folder.")
            sys.exit(1)
        click.echo("ok: the receipt hash matches" if hash_only else "ok: the receipt and its evidence files are untouched")
        return
    if not run_id:
        dirs = sorted(d.name for d in Path(config.RUNS_DIR).glob("*") if (d / "state.json").exists())
        if not dirs:
            raise click.ClickException("no runs found")
        run_id = dirs[-1]
    run_dir = state_io.run_dir(run_id)
    if (run_dir / "audit.json").exists():
        a = json.loads((run_dir / "audit.json").read_text(encoding="utf-8"))
        r = receipt.build_audit(a, run_dir)
        written = receipt.write(run_dir, r, with_html=html)
        for f in written:
            click.echo(f"wrote {f}")
        out.update(mode="write", **_receipt_fields(r, written))
        cost = r["price"]["usd"]
        click.echo(f"{r['receipt_id']}: {'cost not recorded' if cost is None else f'${cost:.6f} Jev cost'}, "
                   f"{r['proof']['cards_citing_evidence']} of {r['proof']['cards']} cards cited, hash {r['hash'][:19]}")
        return
    if not (run_dir / "state.json").exists():
        raise click.ClickException(f"unknown run id: {run_id}")
    econ_path = econ.BUSINESS / "unit_economics.json"
    if not econ_path.exists():
        raise click.ClickException(f"{econ_path} not found. Run firstrun econ first.")
    data = json.loads(econ_path.read_text(encoding="utf-8"))
    if tier and tier.lower() not in {k.lower() for k in data["tiers"]}:
        raise click.ClickException(f"unknown tier {tier!r}. Known: {', '.join(data['tiers'])}")
    state = state_io.load_state(run_id)
    try:
        steps = sum(1 for s in state_io.load_runbook(run_id).steps if not s.skipped_out_of_scope)
    except (OSError, ValueError):
        steps = None
    plan = Path("docs") / "data" / "plan.json"
    cfo_url = ""
    if plan.exists():
        cfo_url = (json.loads(plan.read_text(encoding="utf-8")).get("cfo") or {}).get("model", "")
    r = receipt.build(state, run_dir, data, bills=tier, cfo_url=cfo_url, steps_total=steps)
    written = receipt.write(run_dir, r, with_html=html)
    for f in written:
        click.echo(f"wrote {f}")
    out.update(mode="write", **_receipt_fields(r, written))
    click.echo(f"{r['receipt_id']}: ${r['price']['model_cost_usd']:.4f} model cost, "
               f"{'verified' if r['proof']['verified'] else 'not verified'}, hash {r['hash'][:19]}")


@cli.command("share")
@click.argument("run_id", required=False)
def share_cmd(run_id) -> None:
    """Print a share link for a run (default: the newest run)."""
    from firstrun import share, state as state_io

    if not run_id:
        dirs = sorted(d.name for d in Path(config.RUNS_DIR).glob("*") if (d / "state.json").exists())
        if not dirs:
            raise click.ClickException("no runs found")
        run_id = dirs[-1]
    run_dir = state_io.run_dir(run_id)
    if not (run_dir / "state.json").exists():
        raise click.ClickException(f"unknown run id: {run_id}")
    link, code = share.link_for_run(run_dir)
    click.echo(link)
    click.echo(f"code: {code}")
    click.echo(f"code length: {len(code)}")


@cli.command("audit")
@click.argument("target")
@click.option("--days", "stale_days", default=180, show_default=True, help="A page older than this is stale or quiet.")
@click.option("--no-jev", is_flag=True, help="Sort commits by their subject line only. No model call.")
@click.option("--no-publish", is_flag=True, help="Do not write docs/audits for the site.")
@click.option("--docs-repo", help="A second repo that holds the docs, when they do not live next to the code.")
@click.option("--no-team", is_flag=True, help="Leave out the team map and the suggested owners. FIRSTRUN_TEAM=0 does the same.")
@click.option("--json", "as_json", is_flag=True, help="Print one JSON object on stdout. Logs go to stderr.")
def audit_cmd(target, stale_days, no_jev, no_publish, docs_repo, no_team, as_json) -> None:
    """Audit a repo's docs: stale pages, features with no docs, and proposal cards. TARGET is owner/repo, a GitHub URL, a git folder, or a docs site with a sitemap."""
    with _json_out("audit", as_json) as out:
        _audit_cmd(target, stale_days, no_jev, no_publish, docs_repo, no_team, out)


def audit_json(result: dict, out_dir: Path, top: int = 10) -> dict:
    """The --json record of one audit: counts, cost, the top tasks with their suggested owner, and the files."""
    people = {p["id"]: p for p in ((result.get("team") or {}).get("people") or [])}

    def owner(o):
        p = people.get((o or {}).get("p", ""))
        return {"name": p["name"], "login": p.get("login") or "", "why": o.get("why", "")} if p else None

    tasks = [{"rank": x.get("rank"), "kind": x.get("kind"), "title": x.get("title"), "path": x.get("path") or "",
              "score": x.get("score"), "effort": x.get("effort"), "action": x.get("action", ""),
              "rationale": x.get("rationale", ""), "owner": owner(x.get("owner"))}
             for x in ((result.get("next") or {}).get("items") or [])[:top]]
    return {"audit_id": result["id"], "repo": result.get("repo"), "url": result.get("url"),
            "docs_repo": result.get("docs_repo") or "", "mode": result.get("mode", "repo"),
            "summary": result["summary"], "jev": bool(result.get("jev")), "cost": result.get("cost"),
            "team": bool(people), "top_tasks": tasks, "run_dir": str(out_dir),
            "files": {"audit_json": str(out_dir / "audit.json"), "audit_md": str(out_dir / "audit.md")},
            "published": None}


def _audit_cmd(target, stale_days, no_jev, no_publish, docs_repo, no_team, out: dict) -> None:
    from firstrun import audit as audit_mod, tracing

    tracing.init_tracing(tags=["audit"])
    try:
        if re.match(r"^(https?://)?[\w.-]+\.[a-z]{2,}(/|$)", target) and "github.com" not in target:
            result = audit_mod.audit_sitemap(target, stale_days)
        else:
            click.echo(f"auditing {target}: cloning history, no checkout")
            result = audit_mod.audit(target, stale_days, use_jev=not no_jev, docs_repo=docs_repo, team=not no_team)
    except (RuntimeError, ValueError) as e:
        tracing.close_tracing()
        raise click.ClickException(str(e)) from e
    out_dir = Path(config.RUNS_DIR) / result["id"]
    md = audit_mod.save(result, out_dir)
    if _JSON is not None:
        out.update(audit_json(result, out_dir.resolve()))
    s = result["summary"]
    click.echo(f"{s['pages']} pages: {s['stale']} stale, {s['quiet']} quiet, {s['aging']} aging, {s['fresh']} fresh"
               + (f", {s['unchecked']} unchecked" if s.get("unchecked") else "") + f". Oldest {s['oldest_days']} days.")
    click.echo(f"{s['features']} recent features, {s['uncovered']} with no docs. {s['cards']} proposal cards.")
    click.echo(f"report: {md}")
    click.echo(f"issue: firstrun audit-issue {result['id']}")
    if not no_publish:
        site = audit_mod.find_audit_site()
        if site:
            published = audit_mod.publish(result, site, out_dir)
            out["published"] = str(published)
            click.echo(f"site log: {published} (commit docs/audits and docs/receipts to show it on the site)")
    tracing.close_tracing()


@cli.command("audit-issue")
@click.argument("audit_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Print repo, title, body and commands as JSON.")
def audit_issue_cmd(audit_id, as_json) -> None:
    """Write issue.md for the docs team from an audit and print the gh command. Opens nothing."""
    from firstrun import audit as audit_mod

    dirs = sorted(d for d in Path(config.RUNS_DIR).glob("audit-*") if (d / "audit.json").exists())
    if audit_id:
        dirs = [d for d in dirs if d.name == audit_id]
    if not dirs:
        raise click.ClickException("no audit found. Run firstrun audit owner/repo first.")
    d = dirs[-1]
    data = audit_mod.issue(json.loads((d / "audit.json").read_text(encoding="utf-8")))
    (d / "issue.md").write_text(data["body"], encoding="utf-8")
    data["body_file"] = str(d / "issue.md")
    if as_json:
        click.echo(json.dumps(data, indent=1))
        return
    click.echo(f"title: {data['title']}")
    click.echo(f"body: {d / 'issue.md'}")
    for c in data["commands"]:
        click.echo(f"run from {d}: {c}")


@cli.command("audit-submit")
@click.argument("audit_id", required=False)
@click.option("--yes", is_flag=True, help="Upload without asking first.")
@click.option("--open", "open_browser", is_flag=True, help="Open the prefilled issue in the browser.")
@click.option("--with-team", is_flag=True, help="Keep the team map and the suggested owners. Left out by default.")
def audit_submit_cmd(audit_id, yes, open_browser, with_team) -> None:
    """Offer a local audit for the public doc-audit log: a secret gist plus a prefilled issue. A maintainer publishes it."""
    import shutil
    import subprocess

    from firstrun import intake, team

    dirs = sorted(d for d in Path(config.RUNS_DIR).glob("audit-*") if (d / "audit.json").exists())
    if audit_id:
        dirs = [d for d in dirs if d.name == audit_id]
    if not dirs:
        raise click.ClickException("no audit found. Run firstrun audit owner/repo first.")
    path = dirs[-1] / "audit.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    try:
        intake.validate(dict(doc))
    except ValueError as e:
        raise click.ClickException(f"{path} is not a complete audit: {e}") from e
    repo = doc["repo"]
    if not with_team:
        # A private repo's contributors stay off the public log unless the owner asks for the map.
        path = dirs[-1] / "audit-submit.json"
        path.write_text(json.dumps(team.strip_people(doc), indent=1, ensure_ascii=False), encoding="utf-8")
    click.echo(f"{path} holds the docs paths, page titles and commit subjects of {repo}.")
    click.echo("The team map and the suggested owners are " + ("included." if with_team else
                                                               "left out. Add --with-team to include them."))
    click.echo("It goes into a secret gist. A maintainer reads it before it reaches the public log.")
    if not yes and not click.confirm("Upload it?", default=False):
        raise click.Abort()
    if not shutil.which("gh"):
        raise click.ClickException("the GitHub CLI (gh) is not installed. Paste audit.json into a secret gist at "
                                   f"https://gist.github.com, then open {intake.submission_url(repo, '<gist link>')}")
    p = subprocess.run(["gh", "gist", "create", str(path), "--desc", f"FirstRun doc-audit of {repo}"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    gist = next((ln.strip() for ln in p.stdout.splitlines() if intake.gist_id(ln.strip())), "")
    if p.returncode != 0 or not gist:
        raise click.ClickException(f"gh gist create failed: {(p.stderr or p.stdout).strip()[:300]}")
    url = intake.submission_url(repo, gist)
    click.echo(f"gist: {gist}")
    click.echo(f"issue: {url}")
    click.echo("Submit the issue. The board appears at " + intake.SITE + f"?id={doc['id']} once it is published.")
    if open_browser:
        click.launch(url)


@cli.command("publish")
@click.argument("run_id", required=False)
@click.option("--all", "everything", is_flag=True, help="Publish every run folder, not only the newest.")
def publish_cmd(run_id, everything) -> None:
    """Write a run to docs/runs so the public site lists it. Run it inside the firstrun checkout."""
    from firstrun import publish, state as state_io

    site = publish.find_site_dir()
    if site is None:
        raise click.ClickException("docs/runs not found. Run this inside the firstrun checkout or set FIRSTRUN_SITE_DIR.")
    if everything:
        click.echo(f"published {publish.publish_all(config.RUNS_DIR, site)} runs to {site}")
        return
    if not run_id:
        dirs = sorted(d.name for d in Path(config.RUNS_DIR).glob("*") if (d / "state.json").exists())
        if not dirs:
            raise click.ClickException("no runs found")
        run_id = dirs[-1]
    run_dir = state_io.run_dir(run_id)
    if not (run_dir / "state.json").exists():
        raise click.ClickException(f"unknown run id: {run_id}")
    click.echo(f"published: {publish.publish_run(run_dir, site)}")


@cli.command("bisect")
@click.argument("run_id", required=False)
@click.option("--package", required=True, help="PyPI package whose releases to search.")
@click.option("--step", "step_id", type=int, help="Step to test (default: the run's failed step).")
@click.option("--max-probes", default=8, show_default=True, type=int, help="Container probes to spend.")
def bisect_cmd(run_id, package, step_id, max_probes) -> None:
    """Find the release of PACKAGE that broke a step. Replays stored commands, no model call."""
    from firstrun import bisect, state as state_io
    from firstrun.sandbox import DockerUnavailable
    from firstrun.tracing import close_tracing, init_tracing

    if not run_id:
        dirs = sorted(d.name for d in Path(config.RUNS_DIR).glob("*") if (d / "state.json").exists())
        if not dirs:
            raise click.ClickException("no runs found")
        run_id = dirs[-1]
    if not (state_io.run_dir(run_id) / "state.json").exists():
        raise click.ClickException(f"unknown run id: {run_id}")
    init_tracing(["bisect"])
    _quiet_logs()

    def show(entry: dict) -> None:
        mark = "✓" if entry["passed"] else "✗"
        line = f"{mark} {entry['version']:<10}{entry['date']}"
        if not entry["passed"] and entry["error"]:
            line += f"  {entry['error']}"
        click.echo(line)

    try:
        doc = bisect.run(run_id, package, step_id, max_probes, on_probe=show)
    except DockerUnavailable:
        _setup_exit(DOCKER_FIX)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    finally:
        close_tracing()
    if doc["first_bad"]:
        click.echo(f"First bad: {package} {doc['first_bad']} ({doc['first_bad_date']}). "
                   f"Last good: {doc['last_good']}. {doc['probes']} probes, $0 model cost.")
    else:
        click.echo(f"{doc['verdict']}. {doc['probes']} probes, $0 model cost.")
    click.echo(f"saved: {bisect.bisect_path(run_id)}")


@cli.command("pr")
@click.argument("run_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Print repo, path, branch, diff, pr_body and commands as JSON.")
def pr_cmd(run_id, as_json) -> None:
    """Print the steps for your own agent to open a docs PR (default: newest verified run). Opens nothing."""
    from firstrun import pr, state as state_io

    if not run_id:
        found = []
        for d in sorted(Path(config.RUNS_DIR).glob("*")):
            sj = d / "state.json"
            if (d / "patch.diff").exists() and sj.exists() and '"status": "verified"' in sj.read_text(encoding="utf-8"):
                found.append(d.name)
        if not found:
            click.echo("✗ no verified run with a patch.diff found")
            sys.exit(1)
        run_id = found[-1]
    try:
        text = pr.as_json(state_io.run_dir(run_id)) if as_json else pr.plan(state_io.run_dir(run_id))
    except pr.NotReady as exc:
        click.echo(f"✗ {exc}")
        sys.exit(1)
    click.echo(text, nl=as_json)


# --- prereqs (Prerequisite Proof) ---------------------------------------------

@cli.command("prereqs")
@click.argument("run_id", required=False)
@click.option("--no-prove", is_flag=True, help="Derive and print the block only. Start no container.")
@click.option("--rounds", default=2, show_default=True, help="Proof rounds. A failure that names a missing tool adds it.")
@click.option("--json", "as_json", is_flag=True, help="Print one JSON object on stdout. Logs go to stderr.")
def prereqs_cmd(run_id, no_prove, rounds, as_json) -> None:
    """Print the Prerequisites a run revealed and prove them in a fresh container (default: newest verified run)."""
    with _json_out("prereqs", as_json) as out:
        _prereqs_cmd(run_id, no_prove, rounds, out)


def _prereqs_cmd(run_id, no_prove, rounds, out: dict) -> None:
    import neatlogs

    from firstrun import prereqs, state as state_io
    from firstrun.tracing import close_tracing, init_tracing

    if not run_id:
        found = [d.name for d in sorted(Path(config.RUNS_DIR).glob("*"))
                 if (d / "state.json").exists() and '"status": "verified"' in (d / "state.json").read_text(encoding="utf-8")]
        if not found:
            raise click.ClickException("no verified run found")
        run_id = found[-1]
    if not (state_io.run_dir(run_id) / "state.json").exists():
        raise click.ClickException(f"unknown run id: {run_id}")
    config.load_env()
    init_tracing(["prereqs"])
    _quiet_logs()
    try:
        runbook = state_io.load_runbook(run_id)
        from firstrun.tracing import session_attrs

        with neatlogs.trace("firstrun.prereqs", kind="WORKFLOW", run_id=run_id, tags=["prereqs"],
                            **session_attrs(state_io.target_name(runbook.source_url), "prereqs")):
            if no_prove:
                result = prereqs.derive(state_io.load_state(run_id), runbook)
            else:
                result = prereqs.prove(run_id, rounds=rounds)
        derived = {k: v for k, v in result.items() if k != "proof"}
        click.echo(prereqs.to_markdown(derived, runbook.title))
        out.update(run_id=run_id, prereqs=derived, proof=result.get("proof"), files={})
        if no_prove:
            return
        click.echo(prereqs.proof_line(result))
        click.echo(f"wrote {state_io.run_dir(run_id) / 'prereqs.md'}")
        out["files"] = {n: str(state_io.run_dir(run_id) / n) for n in ("prereqs.json", "prereqs.md")}
    except Exception as exc:  # noqa: BLE001
        from firstrun.sandbox import DockerUnavailable

        if isinstance(exc, DockerUnavailable):
            _setup_exit(DOCKER_FIX)
        raise
    finally:
        close_tracing()


@cli.command("doctor")
@click.option("--for", "tool", type=click.Choice(["all", "test", "audit"]), default="all", show_default=True,
              help="Which tool must be ready for exit code 0: Doc-test, Doc-audit or both.")
@click.option("--json", "as_json", is_flag=True, help="Print one JSON object on stdout.")
def doctor_cmd(tool, as_json) -> None:
    """Check that this machine can run FirstRun: Python, git, Docker, keys and network. Prints no key value."""
    from firstrun import doctor

    with _json_out("doctor", as_json) as out:
        result = doctor.run()
        out.update(result)
        marks = {"pass": "✓", "warn": "!", "fail": "✗"}
        for c in result["checks"]:
            click.echo(f"{marks[c['status']]} {c['name']}: {c['detail']}")
            if c["fix"]:
                click.echo(f"    fix: {c['fix']}")
        can = result["can_run"]
        click.echo(f"env file: {result['env_file']['path']} ({'found' if result['env_file']['exists'] else 'not found'})")
        click.echo(f"Doc-test can run: {'yes' if can['doc_test'] else 'no'}. "
                   f"Doc-audit can run: {'yes' if can['doc_audit'] else 'no'}. "
                   "A hosted audit and the public data need no setup.")
        if not doctor.ready(result, tool):
            failed = [c["name"] for c in result["checks"]
                      if c["status"] == "fail" and (tool == "all" or tool in c["required_for"])]
            _json_error("not_ready", "these checks failed: " + ", ".join(failed),
                        "Apply the fix line under each failed check, then run firstrun doctor again.")
            sys.exit(1)


@cli.command("econ")
@click.option("--traces", "traces_file", type=click.Path(exists=True, dir_okay=False),
              help="A saved `neatlogs traces list --json` payload. Default: read neatlogs now.")
@click.option("--since", default="2026-10-10T00:00:00Z", show_default=True, help="Earliest trace to read.")
@click.option("--margin-floor", default=0.70, show_default=True, type=float, help="Gross margin each tier must keep.")
def econ_cmd(traces_file, since, margin_floor) -> None:
    """Measure cost per run from neatlogs, write drivers.csv for cfo.ai and the per-tier cost caps."""
    from firstrun import econ

    if not 0 <= margin_floor < 1:
        raise click.BadParameter("must be at least 0 and below 1", param_hint="--margin-floor")
    config.load_env()
    inputs = json.loads((econ.BUSINESS / "inputs.json").read_text(encoding="utf-8"))
    try:
        raw = Path(traces_file).read_text(encoding="utf-8") if traces_file else econ.fetch_traces(since)
        result = econ.build(raw, inputs, margin_floor)
    except econ.EconError as exc:
        raise click.ClickException(str(exc))
    d = result["drivers"]
    click.echo(f"{d['traces']} runs: mean ${d['cost_mean']:.4f}, p95 ${d['cost_p95']['usd']:.4f}, "
               f"max ${d['cost_max']['usd']:.4f} per run")
    for name, t in result["tiers"].items():
        line = f"{name}: cap ${t['cap_usd_per_run']:.4f} per run, {t['measured_runs_over_cap_pct']}% of runs over it"
        if "margin_at_p95_pct" in t:
            line += f", margin {t['margin_at_mean_pct']}% at mean, {t['margin_at_p95_pct']}% at p95"
        click.echo(line)
    for path in econ.write(result):
        click.echo(f"wrote {path}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
