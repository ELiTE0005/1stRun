import json
import os

import pytest

from firstrun import planner

MD = """# Quickstart

Install it:

```bash
# install
$ pip install neatlogs
$ python -c "import neatlogs" && \\
    echo ok
```

Output looks like:

```text
ok
```

```json
{"a": 1}
```

```sh
export KEY=abc
```
"""

GOOD = {
    "title": "Quickstart",
    "image": "python:3.11-slim",
    "steps": [
        {"id": 1, "intent": "install", "command": "pip install neatlogs",
         "files": [], "expected": {"exit_code": 0}, "source_line": "$ pip install neatlogs"},
        {"id": 2, "intent": "write", "command": "python app.py",
         "files": [{"path": "app.py", "content": "print(1)"}],
         "expected": {"exit_code": 0, "output_contains": "1"}, "source_line": "python app.py"},
    ],
}


def test_heuristic_plan():
    rb = planner.heuristic_plan(MD, "u")
    cmds = [s.command for s in rb.steps]
    assert cmds == ["pip install neatlogs", 'python -c "import neatlogs" && echo ok', "export KEY=abc"]
    assert [s.id for s in rb.steps] == [1, 2, 3]
    assert rb.title == "Quickstart"


def test_plan_from_markdown_plain_and_fenced():
    rb = planner.plan_from_markdown(MD, "u", llm=lambda p: json.dumps(GOOD))
    assert len(rb.steps) == 2 and rb.docs_markdown == MD and rb.source_url == "u"
    rb = planner.plan_from_markdown(MD, "u", llm=lambda p: "Here:\n```json\n" + json.dumps(GOOD) + "\n```")
    assert rb.steps[1].files[0].path == "app.py"


def test_plan_retries_once_on_invalid():
    calls = []

    def llm(p):
        calls.append(p)
        return "not json" if len(calls) == 1 else json.dumps(GOOD)

    rb = planner.plan_from_markdown(MD, "u", llm=llm)
    assert len(calls) == 2 and "invalid" in calls[1] and len(rb.steps) == 2


def test_plan_fails_after_second_invalid():
    with pytest.raises(ValueError):
        planner.plan_from_markdown(MD, "u", llm=lambda p: '{"steps": [{"id": 0}]}')


def test_read_docs_file_url(tmp_path):
    f = tmp_path / "d.md"
    f.write_text(MD, encoding="utf-8")
    assert planner.read_docs(f.as_uri()) == MD
    assert planner.read_docs(str(f)) == MD


def test_plan_offline_and_fallback(tmp_path, monkeypatch):
    f = tmp_path / "d.md"
    f.write_text(MD, encoding="utf-8")
    monkeypatch.setenv("FIRSTRUN_OFFLINE", "1")
    assert len(planner.plan(f.as_uri()).steps) == 3
    monkeypatch.delenv("FIRSTRUN_OFFLINE")
    with pytest.raises(planner.PlanError, match="planner failed"):  # no silent heuristic after a model failure
        planner.plan(f.as_uri(), llm=lambda p: "garbage")


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("FIRSTRUN_LIVE") != "1", reason="set FIRSTRUN_LIVE=1")
def test_live_neatlogs_plan():
    from firstrun.tracing import close_tracing, init_tracing

    init_tracing(tags=["dev"], disable_export=False)
    rb = planner.plan("https://docs.neatlogs.com/sdk/python")
    close_tracing()
    print("steps:", len(rb.steps), [s.command for s in rb.steps])
    assert rb.steps and all(s.command for s in rb.steps)
