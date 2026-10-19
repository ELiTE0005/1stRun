"""Prerequisite Proof. Turns the hidden environment fixes of a run into a Prerequisites block, then proves it.

derive() reads a finished run. prove() installs only those prerequisites in a fresh container and runs the
ORIGINAL docs commands with no patches and no model calls. This file never imports planner, recovery or llm.
"""

from __future__ import annotations

import json
import os
import re
import secrets as _secrets
from typing import Any, Callable

import neatlogs

from firstrun import config, state as state_io
from firstrun.models import FailureClass, Runbook, RunState, Step, StepResult
from firstrun.tracing import mark_error, set_io

# Command name -> the apt package that provides it.
TOOL_PACKAGES = {
    "sudo": "sudo", "git": "git", "curl": "curl", "wget": "wget", "gpg": "gnupg", "gpg2": "gnupg",
    "make": "make", "gcc": "gcc", "g++": "g++", "unzip": "unzip", "zip": "zip", "jq": "jq",
    "tar": "tar", "xz": "xz-utils", "ssh": "openssh-client", "lsb_release": "lsb-release",
    "pkg-config": "pkg-config", "cmake": "cmake",
}

_STEP_PREFIX = re.compile(r"^/tmp/\.fr_step\.sh: line \d+: ")
_NOT_FOUND = re.compile(r"(?:^|\s)([A-Za-z0-9_.+\-]+): (?:command )?not found", re.M)
_EXEC_NOT_FOUND = re.compile(r'exec: "([A-Za-z0-9_.+\-]+)": executable file not found')
_ERRORISH = re.compile(r"error|not found|cannot|can't|failed|no such|denied|fatal|invalid", re.I)
_INSTALL = re.compile(
    r"(?:\b(?:apt-get|apt)\s+(?:-\S+\s+)*install|\bapk\s+add|\b(?:yum|dnf)\s+(?:-\S+\s+)*install)\s+([^&;|\n]*)")
_PKG = re.compile(r"^[a-z0-9][a-z0-9+.\-_:]*$")
_PATH_EXPORT = re.compile(r"export\s+PATH=(\"[^\"]*\"|'[^']*'|\S+)")
_VERSION = re.compile(r"(\d+)\.(\d+)")
_ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_NOT_KEYS = {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "PYTHON_VERSION", "EXIT_CODE"}


# --- small helpers -----------------------------------------------------------

def _missing_tools(text: str) -> list[str]:
    """Names a failure says it could not find, from `X: command not found` and `exec: "X": executable file not found`."""
    return _NOT_FOUND.findall(text) + _EXEC_NOT_FOUND.findall(text)


def _error_line(result: StepResult | None) -> str:
    if result is None:
        return ""
    for text in (result.stderr, result.stdout):
        lines = [_STEP_PREFIX.sub("", ln.strip().strip("╭╮╰╯│─ ")) for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        if lines:
            pick = next((ln for ln in lines if len(ln) > 8 and _ERRORISH.search(ln)), lines[-1])
            return pick[:160]
    return "timed out" if result.timed_out else f"exit {result.exit_code}"


def _tool_error(name: str, result: StepResult) -> str:
    """The failure line that names a missing tool."""
    for ln in (result.stderr + "\n" + result.stdout).splitlines():
        if (f'"{name}": executable file not found' in ln or f"{name}: command not found" in ln
                or f"{name}: not found" in ln):
            return _STEP_PREFIX.sub("", ln.strip())[:160]
    return f"{name}: command not found"


def _failed(state: RunState, step_id: int) -> list[StepResult]:
    return [r for r in state.results if r.step_id == step_id and not r.passed]


def _install_packages(command: str) -> list[str]:
    """Package names from every apt, apk and yum install in one command. Flags and shell variables drop out."""
    found: list[str] = []
    for m in _INSTALL.finditer(command):
        for tok in m.group(1).split():
            tok = tok.split("=")[0]
            if tok.startswith("-") or not _PKG.match(tok):
                continue
            if tok not in found:
                found.append(tok)
    return found


def _has_install(command: str) -> bool:
    return bool(_INSTALL.search(command))


def _path_entries(command: str) -> list[str]:
    out: list[str] = []
    for m in _PATH_EXPORT.finditer(command):
        value = m.group(1).strip("\"'")
        for part in value.split(":"):
            if part and part not in ("$PATH", "${PATH}") and part not in out:
                out.append(part)
    return out


def _floor_tuple(spec: str) -> tuple[int, int] | None:
    m = re.search(r">=\s*(\d+)\.(\d+)", spec)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _floor_text(t: tuple[int, int]) -> str:
    return f">={t[0]}.{t[1]}"


def _image_python(image: str) -> tuple[int, int] | None:
    m = re.match(r"python:(\d+)\.(\d+)", image)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _pypi_requires_python(name: str, version: str) -> str:
    import urllib.request

    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=8) as resp:  # noqa: S310 - fixed https host
        return (json.load(resp).get("info") or {}).get("requires_python") or ""


def python_floor(text: str, fetch: Callable[[str, str], str] | None = None) -> tuple[tuple[int, int] | None, str]:
    """(floor, error_line) from one failing pip output, or (None, "")."""
    for line in text.splitlines():
        if "requires a different python" in line.lower():
            m = re.search(r"not in '([^']+)'", line)
            floor = _floor_tuple(m.group(1)) if m else None
            if floor:
                return floor, line.strip()[:160]
    m = re.search(r"No matching distribution found for ([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-+!]+)", text)
    if not m:
        return None, ""
    name, version = m.group(1), m.group(2)
    err = f"No matching distribution found for {name}=={version}"
    # pip lists the releases it skipped, for example "3.7 Requires-Python >=3.12".
    listed = re.search(rf"(?<![\w.]){re.escape(version)} Requires-Python (>=[\d.]+)", text)
    if listed:
        return _floor_tuple(listed.group(1)), err
    try:
        spec = (fetch or _pypi_requires_python)(name, version)
    except Exception:  # noqa: BLE001 - no network means no floor, not a crash
        return None, ""
    floor = _floor_tuple(spec or "")
    return (floor, err) if floor else (None, "")


# --- derive ------------------------------------------------------------------

def derive(state: RunState, runbook: Runbook, fetch: Callable[[str, str], str] | None = None) -> dict:
    """The prerequisites a finished run revealed. Secret names only, never values."""
    steps = {s.id: s for s in runbook.steps}
    packages: list[str] = []
    tools: list[str] = []
    path: list[str] = []
    secrets_found: list[str] = []
    evidence: list[dict] = []
    floor: tuple[int, int] | None = None

    def note(item: str, step_id: int, command: str, error: str, fix: str) -> None:
        if not any(e["item"] == item for e in evidence):
            evidence.append({"item": item, "step_id": step_id, "command": command, "error_line": error, "fix": fix})

    # Tools the image lacked, seen in the failures themselves.
    for r in state.results:
        if r.passed:
            continue
        for name in _missing_tools(r.stderr + "\n" + r.stdout):
            if name in TOOL_PACKAGES and name not in tools:
                tools.append(name)
                note(TOOL_PACKAGES[name], r.step_id, r.command, _tool_error(name, r),
                     f"apt-get install -y {TOOL_PACKAGES[name]}")

    # Fixes: what each environment patch added.
    for p in state.patches:
        step = steps.get(p.step_id)
        original = step.command if step else p.old_command
        failures = _failed(state, p.step_id)
        err = _error_line(failures[0]) if failures else ""
        if p.failure_class == FailureClass.ENVIRONMENT or _has_install(p.new_command):
            if not _has_install(p.old_command):
                for pkg in _install_packages(p.new_command):
                    if pkg not in packages:
                        packages.append(pkg)
                    note(pkg, p.step_id, original, err if pkg in TOOL_PACKAGES.values() else "", p.new_command[:160])
        for entry in _path_entries(p.new_command):
            if entry not in path:
                path.append(entry)
                note(f"PATH:{entry}", p.step_id, original, err, f'export PATH="{entry}:$PATH"')

    # Python floor, from any failed output or patch reason.
    for r in state.results:
        if r.passed:
            continue
        found, err = python_floor(r.stderr + "\n" + r.stdout, fetch)
        if found and (floor is None or found > floor):
            floor = found
            note("python", r.step_id, r.command, err, f"use python{found[0]}.{found[1]} or newer")

    # Secrets the run needed.
    needed: set[int] = {g.step_id for g in state.gave_up if g.failure_class == FailureClass.NEEDS_SECRET}
    needed |= {sid for sid, c in state.classifications.items() if c.top == FailureClass.NEEDS_SECRET}
    for g in state.gave_up:
        if g.step_id in needed:
            for name in _ENV_NAME.findall(g.reason):
                if name not in _NOT_KEYS and name not in secrets_found:
                    secrets_found.append(name)
                    step = steps.get(g.step_id)
                    note(name, g.step_id, step.command if step else "", g.reason[:160], f"set {name} in the environment")
    for sid in needed:
        for r in _failed(state, sid):
            for name in _ENV_NAME.findall(r.stderr + "\n" + r.stdout):
                if name not in _NOT_KEYS and name not in secrets_found:
                    secrets_found.append(name)
                    note(name, sid, r.command, _error_line(r), f"set {name} in the environment")

    return {
        "system_packages": packages,
        "python": _floor_text(floor) if floor else None,
        "path": path,
        "secrets": secrets_found,
        "tools": tools,
        "evidence": evidence,
    }


def install_set(d: dict) -> list[str]:
    """Every apt package the proof installs: derived packages plus the packages behind missing tools."""
    out = list(d.get("system_packages", []))
    for tool in d.get("tools", []):
        pkg = TOOL_PACKAGES.get(tool, tool)
        if pkg not in out:
            out.append(pkg)
    return out


# --- markdown ----------------------------------------------------------------

def _short(command: str, limit: int = 60) -> str:
    one = " ".join(command.split())
    return one if len(one) <= limit else one[: limit - 3] + "..."


def _reason(d: dict, item: str, what: str) -> str:
    ev = next((e for e in d.get("evidence", []) if e["item"] == item), None)
    if not ev:
        return what
    err = ev["error_line"].rstrip(".")
    tail = f" It fails with: {err}." if err else ""
    return f"{what} Step {ev['step_id']} (`{_short(ev['command'])}`) needs it.{tail}"


def to_markdown(d: dict, title: str = "") -> str:
    """A short Prerequisites block in plain sentences, one bullet per item."""
    lines = ["## Prerequisites", ""]
    intro = f"Set these up before you follow {title}." if title else "Set these up before you follow the steps."
    bullets: list[str] = []
    if d.get("python"):
        v = d["python"].lstrip(">=")
        bullets.append("- " + _reason(d, "python", f"Python {v} or newer."))
    for pkg in install_set(d):
        bullets.append("- " + _reason(d, pkg, f"`{pkg}`."))
    for entry in d.get("path", []):
        bullets.append("- " + _reason(d, f"PATH:{entry}", f"`{entry}` on your PATH."))
    for name in d.get("secrets", []):
        bullets.append("- " + _reason(d, name, f"The `{name}` environment variable."))
    if not bullets:
        return "## Prerequisites\n\nThis run needed nothing beyond the base image.\n"
    return "\n".join([lines[0], "", intro, "", *bullets]) + "\n"


# --- prove -------------------------------------------------------------------

def _default_factory(image: str, name: str):
    from firstrun.sandbox import Container

    return Container(image=image, name=name)


def _default_run_step(container, step: Step) -> StepResult:
    from firstrun.executor import run_step

    return run_step(container, step)


def _image_for(base_image: str, floor: tuple[int, int] | None) -> str:
    have = _image_python(base_image)
    if floor and have and floor > have:
        return f"python:{floor[0]}.{floor[1]}-slim"
    return base_image


def _setup_script(packages: list[str], path: list[str]) -> list[str]:
    cmds: list[str] = []
    if packages:
        cmds.append("apt-get update -qq && apt-get install -y -qq --no-install-recommends " + " ".join(packages))
    for entry in path:
        cmds.append(f'export PATH="{entry}:$PATH"')
    return cmds


def prove(
    run_id: str,
    rounds: int = 2,
    container_factory: Callable[[str, str], Any] | None = None,
    run_step: Callable[[Any, Step], StepResult] | None = None,
    fetch: Callable[[str, str], str] | None = None,
    write: bool = True,
) -> dict:
    """GUARDRAIL span `prereqs.prove`. Fresh container, only the prerequisites, the docs commands as written."""
    state = state_io.load_state(run_id)
    runbook = state_io.load_runbook(run_id)
    derived = derive(state, runbook, fetch)
    factory = container_factory or _default_factory
    runner = run_step or _default_run_step
    steps = [s for s in runbook.steps if not s.skipped_out_of_scope]
    docs_bug_steps = {p.step_id for p in state.patches if p.failure_class == FailureClass.DOCS_BUG}
    proof: dict = {"proven": False, "rounds": 0, "image": runbook.image, "failed_step": None, "error": "",
                   "steps_passed": 0, "steps_total": len(steps), "added": []}

    with neatlogs.trace("prereqs.prove", kind="GUARDRAIL") as span, config.block_model_calls():
        floor = _floor_tuple(derived["python"]) if derived["python"] else None
        for rnd in range(1, max(1, rounds) + 1):
            proof["rounds"] = rnd
            image = _image_for(runbook.image, floor)
            proof.update(image=image, failed_step=None, error="", steps_passed=0)
            name = f"firstrun-prereq-{os.getpid()}-{_secrets.token_hex(3)}"
            failing: StepResult | None = None
            try:
                with factory(image, name) as container:
                    for cmd in _setup_script(install_set(derived), derived["path"]):
                        done = container.exec(cmd, timeout_s=600)
                        if done.exit_code != 0:
                            proof.update(failed_step=0, error=f"setup failed: {_error_line(done)}")
                            break
                    else:
                        for step in steps:
                            result = runner(container, step)
                            if not result.passed:
                                failing = result
                                proof.update(failed_step=step.id, error=_error_line(result))
                                break
                            proof["steps_passed"] += 1
            except config.ModelCallBlocked as exc:
                proof["error"] = f"model call during proof: {exc}"
                break
            except Exception as exc:  # noqa: BLE001 - a broken container is an unproven block, not a crash
                proof["error"] = f"proof error: {exc}"
                break
            if proof["failed_step"] is None:
                proof["proven"] = True
                break
            if failing is None:
                break  # setup failed: nothing new to learn from a step
            # Round failed. Add only what the new failure itself names, then try again.
            text = failing.stderr + "\n" + failing.stdout
            added = _learn(derived, failing, text, floor, fetch)
            if not added:
                break
            floor = _floor_tuple(derived["python"]) if derived["python"] else None
            proof["added"].extend(added)
        if not proof["proven"] and proof["failed_step"] in docs_bug_steps:
            proof["note"] = f"step {proof['failed_step']} is a docs bug FirstRun patched. A prerequisite cannot fix it."
        reason = ("all %d steps ran as written" % len(steps)) if proof["proven"] else (proof["error"] or "not proven")
        span.set_attribute("neatlogs.guardrail.passed", bool(proof["proven"]))
        span.set_attribute("neatlogs.guardrail.reason", reason)
        set_io(span, input={"run_id": run_id, "rounds": rounds, "prerequisites": install_set(derived)},
               output={"proven": proof["proven"], "rounds": proof["rounds"], "image": proof["image"],
                       "failed_step": proof["failed_step"], "error": proof["error"]})
        if not proof["proven"]:
            mark_error(span, reason)

    result = {**derived, "proof": proof}
    if write:
        out = state_io.run_dir(run_id)
        (out / "prereqs.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        (out / "prereqs.md").write_text(to_markdown(derived, runbook.title), encoding="utf-8")
    return result


def _learn(derived: dict, failing: StepResult, text: str, floor, fetch) -> list[str]:
    """Add what the failure names: a missing known tool, or a Python floor. Returns the new items."""
    added: list[str] = []
    for name in _missing_tools(text):
        pkg = TOOL_PACKAGES.get(name)
        if pkg and pkg not in install_set(derived):
            derived["tools"].append(name)
            derived["evidence"].append({"item": pkg, "step_id": failing.step_id, "command": failing.command,
                                        "error_line": _tool_error(name, failing),
                                        "fix": f"added in proof round: apt-get install -y {pkg}"})
            added.append(pkg)
    found, err = python_floor(text, fetch)
    if found and (floor is None or found > floor):
        derived["python"] = _floor_text(found)
        derived["evidence"].append({"item": "python", "step_id": failing.step_id, "command": failing.command,
                                    "error_line": err, "fix": f"use python{found[0]}.{found[1]} or newer"})
        added.append(f"python{found[0]}.{found[1]}")
    return added


def proof_line(result: dict) -> str:
    p = result["proof"]
    if p["proven"]:
        return (f"Proven: a fresh {p['image']} container with only these prerequisites ran "
                f"{p['steps_passed']}/{p['steps_total']} steps as written.")
    why = p.get("error") or "unknown error"
    where = f"step {p['failed_step']}" if p.get("failed_step") else "setup"
    line = (f"Not proven: {where} failed in a fresh {p['image']} container after {p['rounds']} "
            f"round{'s' if p['rounds'] != 1 else ''}. Error: {why}")
    return line + (f" {p['note']}" if p.get("note") else "")
