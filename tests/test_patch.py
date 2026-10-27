from onestrun.models import FailureClass, Patch, Runbook, RunState, RunStatus, Step, StepResult
from onestrun.patch import make_diff, make_pr_body, write_outputs

DOCS = "# Quickstart\n\n```bash\n$ pip install foo\npython old.py\n```\n\nDone.\n"

DOCS_PATCH = Patch(step_id=2, old_command="python old.py", new_command="python new.py", reason="script renamed")
ENV_PATCH = Patch(
    step_id=1,
    old_command="pip install foo",
    new_command="apt-get install -y curl && pip install foo",
    reason="curl missing in slim image",
    failure_class=FailureClass.ENVIRONMENT,
)


def make_state(status=RunStatus.VERIFIED, patches=None) -> RunState:
    return RunState(
        run_id="r1",
        source_url="https://example.com/quickstart",
        status=status,
        patches=patches if patches is not None else [DOCS_PATCH],
        results=[
            StepResult(step_id=1, command="pip install foo", exit_code=0, passed=True),
            StepResult(step_id=2, command="python old.py", exit_code=1, stderr="x\nFileNotFoundError: old.py", passed=False),
        ],
        time_to_first_success_s=42.0,
    )


def test_diff_replaces_right_line_only():
    diff = make_diff(DOCS, [DOCS_PATCH], "quickstart.md")
    assert "--- a/quickstart.md" in diff and "+++ b/quickstart.md" in diff
    assert "-python old.py" in diff and "+python new.py" in diff
    assert "-$ pip install foo" not in diff


def test_diff_prompt_fallback_keeps_prompt():
    patch = Patch(step_id=1, old_command="pip install foo", new_command="pip install bar", reason="renamed")
    diff = make_diff(DOCS, [patch])
    assert "-$ pip install foo" in diff and "+$ pip install bar" in diff
    patch = Patch(step_id=1, old_command="$ pip install foo", new_command="pip install bar", reason="renamed")
    assert "+pip install bar" in make_diff(DOCS.replace("$ pip", "pip"), [patch])


def test_diff_leaves_environment_patch_out():
    diff = make_diff(DOCS, [DOCS_PATCH, ENV_PATCH])
    assert "+apt-get" not in diff
    assert "# Environment fixes" in diff and "curl missing" in diff
    assert make_diff(DOCS, [ENV_PATCH]) == ""


def test_diff_notes_missing_step():
    patch = Patch(step_id=9, old_command="never appears", new_command="x", reason="r")
    diff = make_diff(DOCS, [patch])
    assert "step 9 could not be located" in diff


def test_pr_body_verified():
    body = make_pr_body(make_state(), [DOCS_PATCH], trace_url="https://t/1")
    assert "Verified: a fresh python:3.11-slim container ran all 2 steps" in body
    assert "no model calls during verification" in body
    assert "python old.py" in body and "FileNotFoundError: old.py" in body
    assert "https://t/1" in body
    assert "42 seconds" in body
    assert body.strip().endswith("Found by 1stRun, an agent that runs quickstarts in a clean container.")


def test_pr_body_never_claims_verified_when_unverified():
    body = make_pr_body(make_state(RunStatus.UNVERIFIED), [DOCS_PATCH])
    assert "Verified:" not in body
    assert "Not verified" in body


def test_write_outputs(tmp_path):
    rb = Runbook(source_url="https://example.com/quickstart", docs_markdown=DOCS, steps=[Step(id=1, intent="a", command="pip install foo")])
    written = write_outputs(tmp_path, make_state(), rb)
    assert {p.name for p in written} == {"patch.diff", "pr_body.md"}
    assert "+python new.py" in (tmp_path / "patch.diff").read_text(encoding="utf-8")


def test_write_outputs_nothing_when_unverified_or_no_docs_patch(tmp_path):
    rb = Runbook(source_url="https://example.com/q", docs_markdown=DOCS, steps=[Step(id=1, intent="a", command="x")])
    assert write_outputs(tmp_path, make_state(RunStatus.UNVERIFIED), rb) == []
    assert write_outputs(tmp_path, make_state(patches=[ENV_PATCH]), rb) == []
    assert list(tmp_path.iterdir()) == []


def test_pr_body_proof_links_are_public_only():
    ev = [
        {"kind": "comment", "label": "Maintainer comment", "url": "https://github.com/a/b/issues/1#c1", "public": True},
        {"kind": "comment", "label": "Private note", "url": "https://example.test/n/6", "public": False},
        {"kind": "trace", "label": "Langfuse trace", "url": "", "public": False},
        {"kind": "pr", "label": "this PR", "url": "https://github.com/a/b/pull/1", "public": True},
    ]
    body = make_pr_body(make_state(), [DOCS_PATCH], replay_url="https://1run.netlify.app/run.html#r=abc", evidence=ev)
    assert "[Replay this run step by step](https://1run.netlify.app/run.html#r=abc)" in body
    assert "[Maintainer comment](https://github.com/a/b/issues/1#c1)" in body
    assert "Private note" not in body and "Langfuse trace" not in body and "pull/1" not in body
    assert body.index("Replay this run") > body.index("## Proof")


def test_pr_body_without_proof_links_is_unchanged_in_shape():
    body = make_pr_body(make_state(), [DOCS_PATCH])
    assert "Replay this run" not in body
