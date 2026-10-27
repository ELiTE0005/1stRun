"""Track T6. Renders runs/ into one static, self-contained HTML report page.

extras keys (all optional, a missing one renders as "missing"):
  trace_urls: {run_id: url}      Langfuse trace link per run
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from urllib.parse import urlparse

from onestrun.models import Runbook, RunState, StepStatus

_MISSING = '<span class="missing">missing</span>'


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _template() -> str:
    return resources.files("onestrun").joinpath("templates/report.html").read_text(encoding="utf-8")


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
    detail = ["<h3>Steps</h3>", _step_rows(state, runbook)]
    err = _error_tail(state)
    if err:
        detail.append("<h3>Error</h3>")
        detail.append(f"<pre>{_e(err)}</pre>")
    detail.append(_patches(state))
    if state.stop_reason:
        detail.append(f"<h3>Stop reason</h3><pre>{_e(state.stop_reason)}</pre>")
    detail.append(f"<h3>Trace</h3><p>{_link(trace, 'Open trace') if trace else _MISSING}</p>")
    if report_md:
        detail.append(f"<h3>report.md</h3><pre>{_e(report_md.strip())}</pre>")
    return (
        '<details class="run"><summary>'
        f'<div><div class="target">{_e(title)}</div><div class="rid">{_e(state.run_id)}</div></div>'
        f'<span class="pill {_e(status)}">{_e(status)}</span>'
        f'<div class="meta">{meta}</div>{ff_line}</summary>'
        f'<div class="detail">{"".join(detail)}</div></details>'
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
        .replace("__BUILT__", built)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    return out_path
