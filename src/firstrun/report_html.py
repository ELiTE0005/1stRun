"""Track T6. Renders runs/ into one static, self-contained HTML report page.

extras keys (all optional, a missing one renders as "missing"):
  trace_urls: {run_id: url}      neatlogs trace link per run
  entire_checkpoint_url: str     latest Entire checkpoint link
  entire_checkpoints: int        checkpoint count
  graph_stats: int | str         `entire graph stats` number
  neatlogs_summary: str          one line, such as "14 vs 6 tool calls"
  cfo_plan_url: str              cfo.ai plan link
  cfo_cost_per_run: float | str  cost per run from the plan
  trace_ids: {run_id: trace id}  shown when no trace URL is known
  neatlogs_groups: {tag: {...}}  per-tag stats from evidence/neatlogs_runs.json
  evidence_files: {key: file}    source file shown in each number's tooltip
`load_evidence` builds these from evidence/*.json.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from urllib.parse import urlparse

from firstrun.models import Runbook, RunState, StepStatus

_MISSING = '<span class="missing">missing</span>'


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _template() -> str:
    return resources.files("firstrun").joinpath("templates/report.html").read_text(encoding="utf-8")


def _safe_url(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return url.strip()
    return None


def _link(url: object, label: str) -> str:
    safe = _safe_url(url)
    if safe is None:
        return _MISSING
    return f'<a href="{_e(safe)}" rel="noopener">{_e(label)}</a>'


def _secs(value: float | None) -> str:
    return _MISSING if value is None else f"{value:.1f} s"


def _target(url: str) -> str:
    p = urlparse(url)
    if p.netloc:
        return (p.netloc + p.path).rstrip("/")
    return url


def _counts(state: RunState, runbook: Runbook | None) -> tuple[int, int]:
    if runbook is not None:
        total = len(runbook.steps)
    else:
        total = len(set(state.step_status) | {r.step_id for r in state.results})
    if state.step_status:
        passed = sum(1 for s in state.step_status.values() if s == StepStatus.PASSED)
    else:
        passed = len({r.step_id for r in state.results if r.passed})
    return passed, total


def _load(runs_dir: Path):
    """Return (loaded, unreadable). loaded holds (state, runbook or None, report_md or None)."""
    loaded, bad = [], []
    if not runs_dir.is_dir():
        return loaded, bad
    for d in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        sj = d / "state.json"
        if not sj.is_file():
            continue
        try:
            state = RunState.model_validate_json(sj.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - one bad file must not kill the page
            bad.append(d.name)
            continue
        runbook = None
        rj = d / "runbook.json"
        if rj.is_file():
            try:
                runbook = Runbook.model_validate_json(rj.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                runbook = None
        md = d / "report.md"
        report_md = md.read_text(encoding="utf-8") if md.is_file() else None
        loaded.append((state, runbook, report_md))
    loaded.sort(key=lambda t: (t[0].started_at or "~", t[0].run_id))
    return loaded, bad


def _first_failed_command(state: RunState, runbook: Runbook | None) -> str | None:
    sid = state.first_failed_step
    if sid is None:
        return None
    if runbook is not None:
        for s in runbook.steps:
            if s.id == sid:
                return s.command
    for r in state.results:
        if r.step_id == sid:
            return r.command
    return None


def _step_rows(state: RunState, runbook: Runbook | None) -> str:
    last = {}
    for r in state.results:
        last[r.step_id] = r
    cmds = {s.id: s.command for s in runbook.steps} if runbook else {}
    ids = sorted(set(cmds) | set(last) | set(state.step_status))
    rows = []
    for i in ids:
        r = last.get(i)
        cmd = cmds.get(i) or (r.command if r else None)
        status = state.step_status.get(i)
        status_txt = status.value if status else ("passed" if r and r.passed else "missing")
        broke = i == state.first_failed_step
        if r is None:
            exit_html = _MISSING
            dur = _MISSING
        else:
            cls = "exit0" if r.exit_code == 0 else "exitn"
            exit_html = f'<span class="{cls}">{_e(r.exit_code)}</span>'
            dur = f"{r.duration_s:.1f} s"
        rows.append(
            f'<tr class="{"broke" if broke else ""}"><td class="num">{i}</td>'
            f'<td class="cmd">{_e(cmd) if cmd else _MISSING}</td>'
            f'<td class="num">{exit_html}</td><td class="num">{dur}</td>'
            f"<td>{_e(status_txt)}</td></tr>"
        )
    if not rows:
        return f'<p class="empty">No steps recorded: {_MISSING}</p>'
    return (
        '<div class="tscroll"><table><thead><tr><th>#</th><th>Command</th><th>Exit</th>'
        "<th>Time</th><th>Status</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _error_tail(state: RunState) -> str | None:
    sid = state.first_failed_step
    for r in reversed(state.results):
        if r.step_id == sid and not r.passed:
            text = (r.stderr or r.stdout or "").strip()
            return text[-1200:] if text else None
    return None


def _patches(state: RunState) -> str:
    if not state.patches:
        return ""
    out = []
    for p in state.patches:
        src = f"<p>Source: {_e(p.source)}</p>" if p.source else ""
        out.append(
            f'<div class="patch"><p>Step {_e(p.step_id)}: {_e(p.reason)}</p>'
            f'<p class="old">Before: <code>{_e(p.old_command)}</code></p>'
            f'<p class="new">After: <code>{_e(p.new_command)}</code></p>{src}</div>'
        )
    return "<h3>Patch</h3>" + "".join(out)


def _src(value: object, source: str | None, text: str | None = None) -> str:
    """Wrap a number in a tooltip that names the file it came from (plan/22 rule 1)."""
    shown = _e(value) if text is None else text
    return f'<span title="source: {_e(source)}">{shown}</span>' if source else shown


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def load_evidence(evidence_dir: Path, runs_dir: Path) -> dict:
    """Read evidence/*.json into report extras. A missing file leaves its keys out."""
    evidence_dir = Path(evidence_dir)
    extras: dict = {}
    files: dict = {}
    nl = evidence_dir / "neatlogs_runs.json"
    if nl.is_file():
        try:
            groups = json.loads(nl.read_text(encoding="utf-8")).get("groups") or {}
        except ValueError:
            groups = {}
        if groups:
            extras["neatlogs_groups"] = groups
            files["neatlogs"] = "evidence/neatlogs_runs.json"
            v1, v2 = groups.get("v1"), groups.get("v2")
            if v1 and v2:
                extras["neatlogs_summary"] = (
                    f"{v1['avg_tool_calls']:g} vs {v2['avg_tool_calls']:g} tool calls")
            # Traces carry no run_id, so match by start time: within 60 s of state.started_at.
            traces = [(_parse(t.get("startedAt")), t.get("traceId")) for g in groups.values()
                      for t in g.get("traces", [])]
            ids: dict = {}
            loaded, _bad = _load(Path(runs_dir))
            for state, _rb, _md in loaded:
                started = _parse(state.started_at)
                if not started:
                    continue
                best = min(((abs((ts - started).total_seconds()), tid) for ts, tid in traces if ts and tid),
                           default=None)
                if best and best[0] <= 60:
                    ids[state.run_id] = best[1]
            if ids:
                extras["trace_ids"] = ids
    en = evidence_dir / "entire.json"
    if en.is_file():
        try:
            data = json.loads(en.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
        if data.get("checkpoints") is not None:
            extras["entire_checkpoints"] = data["checkpoints"]
        if data.get("graph_tokens_saved") is not None:
            extras["graph_stats"] = f"~{data['graph_tokens_saved']:,} tokens saved"
        files["entire"] = "evidence/entire.json"
    extras["evidence_files"] = files
    return extras


def _group_table(groups: dict, source: str) -> str:
    order = [t for t in ("v1", "v2") if t in groups] + sorted(t for t in groups if t not in ("v1", "v2"))
    rows = []
    for tag in order:
        g = groups[tag]
        cells = [
            _e(tag), _src(g["count"], source), _src(f"{g['avg_spans']:.1f}", source),
            _src(f"{g['avg_tool_calls']:.1f}", source), _src(f"${g['avg_cost_usd']:.4f}", source),
            _src(f"{g['avg_duration_s']:.0f} s", source), _src(g["errors"], source),
        ]
        rows.append("<tr>" + "".join(f'<td class="num">{c}</td>' if i else f"<td>{c}</td>"
                                     for i, c in enumerate(cells)) + "</tr>")
    return (
        '<div class="tscroll"><table><thead><tr><th>Tag</th><th>Runs</th><th>Spans</th><th>Tools</th>'
        "<th>Cost</th><th>Time</th><th>Errors</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _run_block(state: RunState, runbook: Runbook | None, report_md: str | None, extras: dict) -> str:
    passed, total = _counts(state, runbook)
    status = state.status.value
    title = (runbook.title if runbook and runbook.title else "") or _target(state.source_url)
    ff = _first_failed_command(state, runbook)
    if state.first_failed_step is not None:
        code = f"<code>{_e(ff)}</code>" if ff else _MISSING
        ff_line = f'<div class="fail-line">First failed step {_e(state.first_failed_step)}: {code}</div>'
    else:
        ff_line = ""
    meta = (
        f"<span><b>{passed}/{total}</b> steps passed</span>"
        f"<span>First success: <b>{_secs(state.time_to_first_success_s)}</b></span>"
        f"<span>Cost: <b>${state.usage.cost_usd:.4f}</b> list price, not billed</span>"
    )
    trace = (extras.get("trace_urls") or {}).get(state.run_id)
    trace_id = (extras.get("trace_ids") or {}).get(state.run_id)
    detail = ["<h3>Steps</h3>", _step_rows(state, runbook)]
    err = _error_tail(state)
    if err:
        detail.append("<h3>Error</h3>")
        detail.append(f"<pre>{_e(err)}</pre>")
    detail.append(_patches(state))
    if state.stop_reason:
        detail.append(f"<h3>Stop reason</h3><pre>{_e(state.stop_reason)}</pre>")
    detail.append(f"<h3>neatlogs trace</h3><p>{_link(trace, 'Open trace') if trace else (_src(trace_id, 'evidence/neatlogs_runs.json', f'<code>{_e(trace_id)}</code>') if trace_id else _MISSING)}</p>")
    if report_md:
        detail.append(f"<h3>report.md</h3><pre>{_e(report_md.strip())}</pre>")
    return (
        '<details class="run"><summary>'
        f'<div><div class="target">{_e(title)}</div><div class="rid">{_e(state.run_id)}</div></div>'
        f'<span class="pill {_e(status)}">{_e(status)}</span>'
        f'<div class="meta">{meta}</div>{ff_line}</summary>'
        f'<div class="detail">{"".join(detail)}</div></details>'
    )


def _kv(rows: list[tuple[str, str]]) -> str:
    return '<dl class="kv">' + "".join(f"<div><dt>{_e(k)}</dt><dd>{v}</dd></div>" for k, v in rows) + "</dl>"


def _val(value: object) -> str:
    return _MISSING if value in (None, "") else _e(value)


def _panels(runs: list[RunState], extras: dict) -> str:
    traces = extras.get("trace_urls") or {}
    ids = extras.get("trace_ids") or {}
    files = extras.get("evidence_files") or {}
    neat_src, entire_src = files.get("neatlogs"), files.get("entire")
    linked = sum(1 for r in runs if _safe_url(traces.get(r.run_id)) or r.run_id in ids)
    neat_rows = [
        ("Trace links", _src(f"{linked} of {len(runs)}", neat_src) if (traces or ids) else _MISSING),
        ("v1 vs v2", _src(extras.get("neatlogs_summary"), neat_src) if extras.get("neatlogs_summary") else _MISSING),
    ]
    entire_rows = [
        ("Checkpoints", _src(extras.get("entire_checkpoints"), entire_src) if extras.get("entire_checkpoints") is not None else _MISSING),
        ("Graph stats", _src(extras.get("graph_stats"), entire_src) if extras.get("graph_stats") not in (None, "") else _MISSING),
        ("Latest checkpoint", _link(extras.get("entire_checkpoint_url"), "Open")),
    ]
    cfo_cost = extras.get("cfo_cost_per_run")
    if isinstance(cfo_cost, (int, float)):
        cfo_cost = f"${cfo_cost:.4f}"
    cfo_rows = [
        ("Cost per run", _val(cfo_cost)),
        ("Plan", _link(extras.get("cfo_plan_url"), "Open plan")),
    ]
    cards = [
        ("neatlogs", "neatlogs", "Traces every step of every run.", neat_rows,
         _group_table(extras["neatlogs_groups"], neat_src or "evidence/neatlogs_runs.json")
         if extras.get("neatlogs_groups") else ""),
        ("entire", "Entire", "Checkpoints the work and graphs the code.", entire_rows, ""),
        ("cfoai", "cfo.ai", "Prices a run and plans the business.", cfo_rows, ""),
    ]
    return "".join(
        f'<article class="card"><div class="logo {cls}" role="img" aria-label="{_e(name)} logo"></div>'
        f'<h3>{_e(name)}</h3><p class="role">{_e(role)}</p>{_kv(rows)}{extra}</article>'
        for cls, name, role, rows, extra in cards
    )


def _summary(runs: list[RunState], bad: list[str]) -> str:
    n = len(runs) + len(bad)
    if n == 0:
        return '<span class="missing">No runs found.</span>'
    verified = sum(1 for r in runs if r.status.value == "verified")
    broke = sum(1 for r in runs if r.status.value in ("failed", "unverified"))
    word = "quickstart" if n == 1 else "quickstarts"
    return f'<b>{n}</b> {word} ran. <b class="ok">{verified}</b> verified. <b class="bad">{broke}</b> broke.'


def write_html(runs_dir: Path, out_path: Path, extras: dict | None = None) -> Path:
    extras = extras or {}
    runs_dir, out_path = Path(runs_dir), Path(out_path)
    loaded, bad = _load(runs_dir)
    blocks = [_run_block(s, rb, md, extras) for s, rb, md in loaded]
    for name in bad:
        blocks.append(
            f'<details class="run"><summary><div><div class="target">{_e(name)}</div>'
            f'<div class="rid">state.json unreadable</div></div><span class="pill">missing</span>'
            "</summary></details>"
        )
    if not blocks:
        blocks.append(f'<p class="empty">No runs found in {_e(runs_dir)}: {_MISSING}</p>')
    states = [s for s, _, _ in loaded]
    built = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    page = (
        _template()
        .replace("__SUMMARY__", _summary(states, bad))
        .replace("__RUNS__", "\n".join(blocks))
        .replace("__PANELS__", _panels(states, extras))
        .replace("__BUILT__", built)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    return out_path
