"""Shared helpers for the tests/test_edge_*.py files. Offline fakes, plus a live container factory."""

from __future__ import annotations

import contextlib

from firstrun.models import Runbook, Step, StepResult


class FakeContainer:
    """Scripted container. `script` maps a command to (exit_code, stdout, stderr) or a callable."""

    def __init__(self, script=None, files=()):
        self.script = script or {}
        self.log: list[str] = []
        self.files = set(files)
        self.written: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def write_files(self, files):
        for f in files:
            self.files.add(f.path)
            self.written[f.path] = f.content

    def exec(self, command, timeout_s=300):
        self.log.append(command)
        if command.startswith("test -e "):
            hit = command.split()[-1].strip("'") in self.files
            return StepResult(step_id=0, command=command, exit_code=0 if hit else 1)
        entry = self.script.get(command, (0, "", ""))
        if callable(entry):
            entry = entry(command)
        code, out, err = entry
        return StepResult(step_id=0, command=command, exit_code=code, stdout=out, stderr=err, duration_s=0.01)


def factory_for(container):
    return lambda image=None, **kw: container


def make_runbook(*commands, **kw) -> Runbook:
    steps = [Step(id=i, intent=f"step {i}", command=c) for i, c in enumerate(commands, 1)]
    return Runbook(source_url=kw.pop("source_url", "https://docs.example.com/quickstart"),
                   title="Example", steps=steps, **kw)


class Recorder:
    """Collects span names and log messages that a test cares about."""

    def __init__(self):
        self.spans: list[tuple[str, dict]] = []
        self.logs: list[tuple[str, dict]] = []

    def names(self) -> list[str]:
        return [n for n, _ in self.spans]

    def log_text(self) -> str:
        return " | ".join(f"{m} {kw}" for m, kw in self.logs)


def install_recorder(monkeypatch) -> Recorder:
    from firstrun import tracing

    rec = Recorder()
    real_trace, real_log = tracing.trace, tracing.log

    @contextlib.contextmanager
    def trace(name, *args, **kwargs):
        rec.spans.append((name, kwargs))
        with real_trace(name, *args, **kwargs) as span:
            yield span

    def log(message, *args, **kwargs):
        rec.logs.append((message, kwargs))
        return real_log(message, *args, **kwargs)

    monkeypatch.setattr(tracing, "trace", trace)
    monkeypatch.setattr(tracing, "log", log)
    return rec
