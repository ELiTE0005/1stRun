"""Docs Bisect. Find the release of a package that broke one runbook step.

Every probe replays stored commands in a fresh container with PIP_CONSTRAINT pinning one
release. No model call happens here. A test enforces that this file imports no model module.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from onestrun import tracing

from onestrun import config, state as state_io
from onestrun.models import FileSpec, Runbook, Step
from onestrun.tracing import mark_error, set_io

CONSTRAINTS_PATH = "/tmp/constraints.txt"
PYPI_URL = "https://pypi.org/pypi/{package}/json"


# --- releases ----------------------------------------------------------------

def _fetch_json(url: str) -> dict:
    """GET a JSON document. Falls back to curl when Python's CA store cannot verify the host."""
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - an expired CA root or a proxy: try curl once
        proc = subprocess.run(["curl", "-sSfL", url], capture_output=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"cannot fetch {url}: {proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
        return json.loads(proc.stdout.decode("utf-8"))


def _allows_python(requires_python: str | None, python: str) -> bool:
    if not requires_python:
        return True
    from packaging.specifiers import InvalidSpecifier, SpecifierSet

    try:
        spec = SpecifierSet(requires_python)
    except InvalidSpecifier:
        return True
    # "3.11" means the newest 3.11 patch release, which the slim image ships.
    return spec.contains(f"{python}.99", prereleases=True)


def releases(package: str, python: str = "3.11",
             fetch: Callable[[str], dict] | None = None) -> list[tuple[str, str]]:
    """(version, upload_date) for each final release, oldest to newest, that allows `python`."""
    from packaging.version import InvalidVersion, Version

    data = (fetch or _fetch_json)(PYPI_URL.format(package=package))
    found: list[tuple[Version, str, str]] = []
    for ver, files in (data.get("releases") or {}).items():
        try:
            parsed = Version(ver)
        except InvalidVersion:
            continue
        if parsed.is_prerelease or parsed.is_devrelease or not files:
            continue
        live = [f for f in files if not f.get("yanked")]
        if not live:
            continue
        if not any(_allows_python(f.get("requires_python"), python) for f in live):
            continue
        stamps = sorted(f.get("upload_time_iso_8601") or f.get("upload_time") or "" for f in live)
        found.append((parsed, ver, stamps[0][:10]))
    found.sort(key=lambda t: t[0])
    return [(ver, date) for _, ver, date in found]


# --- slicing -----------------------------------------------------------------

def _name_pattern(package: str) -> re.Pattern[str]:
    parts = re.split(r"[-_.]+", package.lower())
    return re.compile(r"(?<![A-Za-z0-9])" + r"[-_.]?".join(map(re.escape, parts)) + r"(?![A-Za-z0-9])", re.I)


def slice_steps(runbook: Runbook, failing_step_id: int, package: str,
                patches: list | None = None) -> list[Step]:
    """The minimal steps for one probe, in runbook order, ending with the failing step.

    Other steps use their patched command (environment fixes stay). The failing step keeps its original command.
    """
    from onestrun.verify import apply_patches

    patched = apply_patches(runbook, patches or [])
    originals = {s.id: s for s in runbook.steps}
    if failing_step_id not in originals:
        raise ValueError(f"no step {failing_step_id} in the runbook")
    failing = originals[failing_step_id]
    pattern = _name_pattern(package)
    out: list[Step] = []
    for step in patched.steps:
        if step.id > failing_step_id or step.skipped_out_of_scope:
            continue
        if step.id == failing_step_id:
            out.append(failing.model_copy(deep=True))
            continue
        mentions = bool(pattern.search(step.command))
        makes_file = any(f.path.rsplit("/", 1)[-1] in failing.command for f in step.files)
        if mentions or makes_file:
            out.append(step)
    return out


# --- one probe ---------------------------------------------------------------

def _default_factory(image: str, name: str, env: dict[str, str]):
    from onestrun.sandbox import Container, _allowlist_env

    return Container(image=image, name=name, env={**_allowlist_env(), **env})


def _default_run_step(container, step):
    from onestrun.executor import run_step

    return run_step(container, step)


_BOX = "╭╮╯╰│─┌┐└┘├┤┬┴┼ "


def _error_line(result) -> str:
    """The most telling line of a failed step: the last one that names an error, else the last line.

    Rich prints errors inside a box, so the box characters are stripped first.
    """
    for text in (result.stderr, result.stdout):
        lines = [ln.strip(_BOX).strip() for ln in text.splitlines()]
        lines = [re.sub(r"^/tmp/\.fr_step\.sh: line \d+: ", "", ln) for ln in lines if ln.strip(_BOX).strip()]
        if lines:
            named = [ln for ln in lines if re.search(r"error|no such|not found|invalid|unrecognized|failed", ln, re.I)]
            return (named or lines)[-1][:120]
    return "timed out" if result.timed_out else f"exit {result.exit_code}"


def probe(steps: list[Step], image: str, package: str, version: str,
          container_factory: Callable[..., Any] | None = None,
          run_step: Callable[[Any, Step], Any] | None = None) -> tuple[bool, str]:
    """TOOL span `probe.<version>`. Run `steps` in a fresh container with `package` pinned to `version`.

    The last step is the one under test. Returns (passed, short error line). Never calls a model.
    `container_factory(image, name, env)` returns a context manager.
    """
    factory = container_factory or _default_factory
    runner = run_step or _default_run_step
    name = f"1stRun-bisect-{package}-{version}"
    env = {"PIP_CONSTRAINT": CONSTRAINTS_PATH}
    passed, error = False, ""
    with tracing.trace(f"probe.{version}", kind="TOOL") as span, config.block_model_calls():
        span.set_attribute("package", package)
        span.set_attribute("version", version)
        try:
            with factory(image, name, env) as container:
                container.write_files([FileSpec(path=CONSTRAINTS_PATH, content=f"{package}=={version}\n")])
                passed = True
                for step in steps:
                    result = runner(container, step)
                    if not result.passed:
                        passed = False
                        error = _error_line(result)
                        if step is not steps[-1]:
                            error = f"step {step.id}: {error}"
                        break
        except config.ModelCallBlocked as exc:
            passed, error = False, f"model call blocked: {exc}"
        except Exception as exc:  # noqa: BLE001 - a broken container is a failed probe, not a crash
            if exc.__class__.__name__ == "DockerUnavailable":
                raise
            passed, error = False, f"probe error: {exc}"[:120]
        span.set_attribute("passed", passed)
        set_io(span, input={"package": package, "version": version, "steps": [s.id for s in steps]},
               output={"passed": passed, "error": error})
        if not passed:
            mark_error(span, error)
    return passed, error


# --- the search --------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bisect_path(run_id: str):
    return state_io.run_dir(run_id) / "bisect.json"


def _save(run_id: str, doc: dict) -> None:
    state_io._write(bisect_path(run_id), json.dumps(doc, indent=2, ensure_ascii=False))


def run(run_id: str, package: str, step_id: int | None = None, max_probes: int = 8,
        container_factory: Callable[..., Any] | None = None,
        run_step: Callable[[Any, Step], Any] | None = None,
        release_list: list[tuple[str, str]] | None = None,
        on_probe: Callable[[dict], None] | None = None) -> dict:
    """WORKFLOW span `onestrun.bisect`. Binary-search the releases of `package` for the first bad one."""
    from onestrun.report import reported_failed_step

    state = state_io.load_state(run_id)
    runbook = state_io.load_runbook(run_id)
    if step_id is None:
        step_id = reported_failed_step(state)
    if step_id is None:
        raise ValueError("this run has no failed step. Pass --step N")
    steps = slice_steps(runbook, step_id, package, state.patches)
    command = next(s.command for s in runbook.steps if s.id == step_id)
    found = re.search(r"python:(\d+\.\d+)", runbook.image)
    python = found.group(1) if found else "3.11"
    doc: dict = {
        "package": package, "step_id": step_id, "command": command, "image": runbook.image,
        "releases_tested": [], "last_good": None, "first_bad": None, "first_bad_date": None,
        "verdict": "", "probes": 0, "started_at": _now(), "finished_at": "",
    }

    from onestrun.tracing import session_attrs

    with tracing.trace("onestrun.bisect", kind="WORKFLOW", run_id=run_id, package=package, step_id=step_id,
                        **session_attrs(state_io.target_name(runbook.source_url), "bisect", package=package)
                        ) as root, config.block_model_calls():
        set_io(root, input={"run_id": run_id, "package": package, "step_id": step_id, "max_probes": max_probes})
        rels = release_list if release_list is not None else releases(package, python)
        doc["releases_available"] = len(rels)

        def test(idx: int) -> bool:
            ver, date = rels[idx]
            ok, err = probe(steps, runbook.image, package, ver, container_factory, run_step)
            entry = {"version": ver, "date": date, "passed": ok, "error": err}
            doc["releases_tested"].append(entry)
            doc["probes"] = len(doc["releases_tested"])
            tracing.log("probe {version}: {result}", version=ver, result="pass" if ok else "fail", error=err)
            _save(run_id, doc)
            if on_probe:
                on_probe(entry)
            return ok

        def finish(verdict: str) -> dict:
            doc["verdict"] = verdict
            doc["finished_at"] = _now()
            _save(run_id, doc)
            set_io(root, output={k: doc[k] for k in ("last_good", "first_bad", "first_bad_date", "verdict", "probes")})
            return doc

        if len(rels) < 2:
            return finish(f"only {len(rels)} release(s) allow Python {python}: nothing to bisect")
        _save(run_id, doc)
        lo, hi = 0, len(rels) - 1
        newest_ok = test(hi)
        oldest_ok = test(lo)
        if not newest_ok and not oldest_ok:
            return finish("fails on every release: not a version regression")
        if newest_ok and oldest_ok:
            return finish("passes on every release: no regression to find")
        if newest_ok:
            return finish("fails on old releases and passes on new ones: fixed upstream, not broken")
        while hi - lo > 1 and doc["probes"] < max_probes:
            mid = (lo + hi) // 2
            if test(mid):
                lo = mid
            else:
                hi = mid
        doc["last_good"] = rels[lo][0]
        if hi - lo == 1:
            doc["first_bad"], doc["first_bad_date"] = rels[hi]
            return finish(f"first bad release: {package} {rels[hi][0]} ({rels[hi][1]})")
        return finish(f"max probes reached: first bad release is after {rels[lo][0]} and no later than {rels[hi][0]}")
