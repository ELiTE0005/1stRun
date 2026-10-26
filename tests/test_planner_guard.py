"""Planner guards (drop invented steps) and the plan cache. Fixes the neatlogs finding "planner invented a step"."""

import json

import pytest

from firstrun import planner

DOCS = """# Quickstart

```bash
pip install chromadb
export OPENAI_API_KEY='sk-...'
```

```python
print("hi")
```
"""


def _step(i, command, files=None, **kw):
    return {"id": i, "intent": f"step {i}", "command": command, "files": files or [],
            "expected": {"exit_code": 0}, "source_line": command, **kw}


def _plan(steps, docs=DOCS):
    return planner.plan_from_markdown(docs, "u", llm=lambda p: json.dumps({"title": "t", "steps": steps}))


def _commands(rb):
    return [s.command for s in rb.steps]


@pytest.mark.parametrize("bad", ["true", ":", "command -v entire", "test -f first_trace.py", "which python", "ls"])
def test_invented_steps_are_dropped(bad):
    rb = _plan([_step(1, bad), _step(2, "pip install chromadb")])
    assert _commands(rb) == ["pip install chromadb"]
    assert [s.id for s in rb.steps] == [1]


def test_fake_secret_export_is_rewritten_when_docs_show_it():
    rb = _plan([_step(1, "export OPENAI_API_KEY='sk-...'")])
    assert _commands(rb) == ['export OPENAI_API_KEY="${OPENAI_API_KEY}"']


def test_fake_secret_export_is_dropped_when_docs_do_not_show_it():
    rb = _plan([_step(1, "export OPENAI_API_KEY='sk-...'"), _step(2, "pip install chromadb")],
               docs="```bash\npip install chromadb\n```")
    assert _commands(rb) == ["pip install chromadb"]


def test_real_docs_command_is_kept():
    rb = _plan([_step(1, "pip   install\n chromadb")])
    assert _commands(rb) == ["pip   install\n chromadb"]


def test_command_missing_from_docs_is_dropped():
    assert _plan([_step(1, "pip install chromadb"), _step(2, "curl https://evil.example")]).steps[-1].command == "pip install chromadb"


def test_run_file_the_step_creates_is_kept():
    files = [{"path": "quickstart.py", "content": 'print("hi")'}]
    rb = _plan([_step(1, "python quickstart.py", files)])
    assert _commands(rb) == ["python quickstart.py"] and rb.steps[0].files[0].path == "quickstart.py"


def test_run_file_the_step_does_not_create_is_dropped():
    assert _plan([_step(1, "python other.py"), _step(2, "pip install chromadb")]).steps[0].command == "pip install chromadb"


def test_files_of_a_dropped_noop_move_to_the_next_step():
    files = [{"path": "quickstart.py", "content": "x"}]
    rb = _plan([_step(1, "true", files), _step(2, "python quickstart.py")])
    assert _commands(rb) == ["python quickstart.py"]
    assert rb.steps[0].files[0].path == "quickstart.py"


def test_skipped_steps_are_not_guarded():
    rb = _plan([_step(1, "pip install chromadb"),
                _step(2, "open https://example.com", skipped_out_of_scope=True, skip_reason="needs a browser")])
    assert len(rb.steps) == 2


def test_guard_logs_and_counts_drops(monkeypatch):
    logs = []
    monkeypatch.setattr(planner.tracing, "log", lambda msg, **kw: logs.append((msg, kw)))
    _plan([_step(1, "true"), _step(2, "command -v entire"), _step(3, "pip install chromadb")])
    assert [kw["why"] for m, kw in logs if "dropped" in m] == ["no-op command", "invented check"]


def test_cache_gives_the_same_runbook_twice(tmp_runs_dir, monkeypatch):
    monkeypatch.delenv("FIRSTRUN_REPLAN", raising=False)
    replies = [json.dumps({"title": "t", "steps": [_step(1, "pip install chromadb")]}),
               json.dumps({"title": "t", "steps": [_step(1, "pip install chromadb"), _step(2, "export OPENAI_API_KEY='sk-...'")]})]
    calls = []
    monkeypatch.setattr(planner, "ask_claude", lambda prompt, system: (calls.append(1) or replies[len(calls) - 1], {}))
    first = planner.plan_from_markdown(DOCS, "u")
    second = planner.plan_from_markdown(DOCS, "u")
    assert len(calls) == 1
    assert first.steps == second.steps and second.docs_markdown == DOCS
    assert list((tmp_runs_dir / ".plan_cache").glob("*.json"))


def test_replan_env_var_bypasses_the_cache(tmp_runs_dir, monkeypatch):
    monkeypatch.setenv("FIRSTRUN_REPLAN", "1")
    calls = []
    reply = json.dumps({"title": "t", "steps": [_step(1, "pip install chromadb")]})
    monkeypatch.setattr(planner, "ask_claude", lambda prompt, system: (calls.append(1) or reply, {}))
    planner.plan_from_markdown(DOCS, "u")
    planner.plan_from_markdown(DOCS, "u")
    assert len(calls) == 2
