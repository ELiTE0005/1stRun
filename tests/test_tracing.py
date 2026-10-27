"""The tracing facade over Langfuse. Spans go to an in-memory exporter, so nothing leaves the machine."""

from __future__ import annotations

import json
import uuid

import pytest

from onestrun import econ, tracing


@pytest.fixture
def exporter(monkeypatch):
    """A real Langfuse client whose spans land in memory."""
    from langfuse import Langfuse
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exp = InMemorySpanExporter()
    # Langfuse keeps one client per public key, so each test gets its own key and its own exporter.
    client = Langfuse(public_key=f"pk-lf-{uuid.uuid4()}", secret_key="sk-lf-test", base_url="http://localhost:1",
                      span_exporter=exp)
    monkeypatch.setattr(tracing, "_client", client)
    monkeypatch.setattr(tracing, "_tags", [])
    yield exp
    client.flush()
    client.shutdown()


def _spans(exp) -> dict:
    return {s.name: s for s in exp.get_finished_spans()}


def _attr(span, key):
    value = span.attributes.get(key)
    try:
        return json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return value


def test_a_trace_nests_and_maps_kinds(exporter):
    with tracing.trace("onestrun.run", kind="WORKFLOW", run_id="r1") as root:
        root.set_attribute("step.exit_code", 3)
        with tracing.trace("step.1", kind="TOOL") as step:
            tracing.set_io(step, input={"command": "pip install x"}, output={"exit_code": 3})
            tracing.mark_error(step, "step 1 failed (exit 3)")
    tracing.close_tracing()
    spans = _spans(exporter)
    assert spans["step.1"].parent.span_id == spans["onestrun.run"].context.span_id
    assert spans["onestrun.run"].attributes["langfuse.observation.type"] == "chain"
    assert spans["step.1"].attributes["langfuse.observation.type"] == "tool"
    root = spans["onestrun.run"]
    assert _attr(root, "langfuse.observation.metadata.run_id") == "r1"
    assert _attr(root, "langfuse.observation.metadata.step.exit_code") == 3
    step = spans["step.1"]
    assert step.attributes["langfuse.observation.level"] == "ERROR"
    assert _attr(step, "langfuse.observation.input") == {"command": "pip install x"}
    assert _attr(step, "langfuse.observation.output") == {"exit_code": 3}


def test_session_user_and_tags_reach_every_span_of_the_trace(exporter, monkeypatch):
    monkeypatch.setattr(tracing, "_tags", ["v2"])
    with tracing.trace("onestrun.run", kind="WORKFLOW", tags=["extra"],
                       **tracing.session_attrs("docs.example.com", "run", variant="v2")):
        with tracing.trace("budget", kind="GUARDRAIL"):
            pass
    tracing.close_tracing()
    for span in exporter.get_finished_spans():
        assert span.attributes["session.id"] == "docs:docs.example.com"
        assert span.attributes["user.id"] == "docs.example.com"
        assert set(span.attributes["langfuse.trace.tags"]) == {"v2", "extra"}


def test_log_is_an_event_on_the_open_span_and_fills_the_template(exporter):
    with tracing.trace("recover.2", kind="AGENT"):
        tracing.log("patch rejected: {why}", level="warning", why="drift", step_id=2)
    tracing.close_tracing()
    spans = _spans(exporter)
    event = spans["patch rejected: drift"]
    assert event.attributes["langfuse.observation.level"] == "WARNING"
    assert event.parent.span_id == spans["recover.2"].context.span_id
    assert _attr(event, "langfuse.observation.metadata.step_id") == 2


def test_annotate_marks_the_span_that_is_open(exporter):
    with tracing.trace("planner", kind="AGENT"):
        tracing.annotate(**{"planner.guard_dropped": 2})
    tracing.close_tracing()
    assert _attr(_spans(exporter)["planner"], "langfuse.observation.metadata.planner.guard_dropped") == 2


def test_the_span_decorator_records_arguments_and_the_result(exporter):
    @tracing.span(kind="TOOL", name="read_docs")
    def read_docs(url: str) -> str:
        return "# docs"

    assert read_docs("https://example.com/q") == "# docs"
    tracing.close_tracing()
    span = _spans(exporter)["read_docs"]
    assert span.attributes["langfuse.observation.type"] == "tool"
    assert "https://example.com/q" in span.attributes["langfuse.observation.input"]
    assert "# docs" in span.attributes["langfuse.observation.output"]


def test_an_exception_passes_through_a_trace(exporter):
    with pytest.raises(ValueError):
        with tracing.trace("verify", kind="GUARDRAIL"):
            raise ValueError("boom")


def test_with_tracing_off_every_call_is_a_no_op(monkeypatch):
    monkeypatch.setattr(tracing, "_client", None)

    @tracing.span(kind="TOOL")
    def f(x):
        return x + 1

    with tracing.trace("a", kind="WORKFLOW", run_id="r") as span:
        span.set_attribute("k", 1)
        tracing.set_io(span, input={"i": 1}, output={"o": 2})
        tracing.mark_error(span, "x")
        tracing.log("hello {n}", n=1)
        tracing.annotate(k=1)
    assert f(1) == 2
    assert not tracing.enabled()
    tracing.close_tracing()
    tracing.shutdown_tracing()


def test_a_broken_client_never_breaks_a_run(monkeypatch):
    class Broken:
        def start_as_current_observation(self, **kw):
            raise RuntimeError("langfuse is down")

        def create_event(self, **kw):
            raise RuntimeError("langfuse is down")

        def update_current_span(self, **kw):
            raise RuntimeError("langfuse is down")

        def flush(self):
            raise RuntimeError("langfuse is down")

    monkeypatch.setattr(tracing, "_client", Broken())
    with tracing.trace("a", kind="TOOL") as span:
        span.set_attribute("k", 1)
        tracing.log("x")
        tracing.annotate(k=1)
    tracing.close_tracing()


# --- econ reads the run folders ---------------------------------------------------

def _state(runs, name, cost, start, end):
    d = runs / name
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({
        "run_id": name, "usage": {"cost_usd": cost}, "started_at": start, "finished_at": end}), encoding="utf-8")


def test_econ_reads_cost_and_duration_from_run_folders(tmp_path):
    _state(tmp_path, "run-a", 0.02, "2026-10-12T10:00:00+00:00", "2026-10-12T10:03:00+00:00")
    _state(tmp_path, "run-old", 9.0, "2026-09-01T10:00:00+00:00", "2026-09-01T10:01:00+00:00")
    _state(tmp_path, "run-unfinished", 1.0, "2026-10-12T11:00:00+00:00", "")
    (tmp_path / "run-broken").mkdir()
    (tmp_path / "run-broken" / "state.json").write_text("{not json", encoding="utf-8")
    traces = econ.run_traces(econ.fetch_traces("2026-10-10T00:00:00Z", runs_dir=tmp_path))
    assert [(t["traceId"], t["totalCostUsd"], t["durationMs"]) for t in traces] == [("run-a", 0.02, 180000.0)]
