"""Edge cases K3, K4, K6 (keys and network), D2 (the report page) and D6 (no secret in git)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from onestrun import config, report_html, sandbox, tracing
from onestrun.sandbox import Container

ROOT = Path(__file__).resolve().parent.parent
FIX_RUNS = Path(__file__).parent / "fixtures_report"


# --- K3 ------------------------------------------------------------------------

def test_k3_closing_a_run_flushes_and_never_waits_for_ingestion(monkeypatch):
    calls = []

    class FakeClient:
        def flush(self):
            calls.append("flush")

        def shutdown(self):
            pytest.fail("shutdown blocks on ingestion")

    monkeypatch.setattr(tracing, "_client", FakeClient())
    tracing.close_tracing()
    assert calls == ["flush"]


# --- K4 ------------------------------------------------------------------------

def test_k4_missing_langfuse_key_warns_and_the_run_still_starts(monkeypatch, capsys):
    monkeypatch.setattr(tracing, "_ready", False)
    monkeypatch.setattr(tracing, "_client", None)
    monkeypatch.setattr(tracing, "load_env", lambda: None)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("ONESTRUN_NO_EXPORT", raising=False)
    tracing.init_tracing(["v1"])
    assert "LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is missing" in capsys.readouterr().err
    assert not tracing.enabled()                           # no keys: tracing is off, nothing crashes
    with tracing.trace("still.works", kind="TOOL") as span:
        span.set_attribute("k", 1)


# --- K6 ------------------------------------------------------------------------

def test_k6_an_image_that_is_already_pulled_is_never_pulled_again(monkeypatch):
    seen = []

    def fake_docker(self, args, input_bytes=None, timeout=120):
        seen.append(args[0])
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(Container, "_docker", fake_docker)
    monkeypatch.setattr(sandbox, "remove_stale", lambda: [])
    with Container("python:3.11-slim", name="1stRun-t7-k6"):
        pass
    assert "pull" not in seen and seen[0] == "image"


@pytest.mark.live
@pytest.mark.parametrize("image", ["python:3.11-slim", "ubuntu:24.04"])
def test_k6_live_demo_images_are_already_pulled(image):
    out = subprocess.run([*config.DOCKER_CMD, "image", "inspect", image], capture_output=True, timeout=60)
    assert out.returncode == 0, f"{image} is not pulled: pull it before the demo"


# --- D2 ------------------------------------------------------------------------

def test_d2_report_page_reads_runs_at_build_time_and_prints_the_build_time_at_the_top(tmp_path):
    out = report_html.write_html(FIX_RUNS, tmp_path / "index.html")
    page = out.read_text(encoding="utf-8")
    stamp = re.search(r"Built (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) UTC", page)
    assert stamp, "the page has no build time"
    assert page.index(stamp.group(0)) < page.index("<main>")          # above the content
    assert "<b>3</b> quickstarts ran" in page                         # data comes from runs/, not from the template


# --- D6 ------------------------------------------------------------------------

SECRET_SHAPES = re.compile(
    r"sk-ant-[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|"
    r"xox[abprs]-[A-Za-z0-9\-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}|fc-[0-9a-f]{24,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:LANGFUSE|ANTHROPIC|TYPESAFE|FIRECRAWL|APIFY|ELEVENLABS)_[A-Z_0-9]*=[A-Za-z0-9_\-]{16,}"
)


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def _real_hits(text: str) -> list[str]:
    # The tests plant fake secrets that all carry the word SECRET or EXAMPLE on purpose.
    return [m for m in SECRET_SHAPES.findall(text) if "SECRET" not in m.upper() and "EXAMPLE" not in m.upper()]


def test_d6_gitignore_keeps_private_files_out():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    for entry in (".env", "secrets.allowlist", "precedents.json", "runs/", "plan/"):
        assert entry in ignored, f"{entry} is not in .gitignore"


def test_d6_no_secret_in_tracked_files():
    hits = {}
    for name in _git("ls-files").splitlines():
        path = ROOT / name
        if path.suffix in {".png", ".jpg", ".mp4", ".gif", ".ico"} or not path.is_file():
            continue
        found = _real_hits(path.read_text(encoding="utf-8", errors="ignore"))
        if found:
            hits[name] = len(found)
    assert not hits, f"secret-shaped text in: {hits}"


def test_d6_no_secret_in_git_history():
    # Project history only. --all would also read refs/entire/checkpoints, the Entire session
    # transcripts, where base64 screenshot data can match AKIA[0-9A-Z]{16} by chance.
    history = _git("log", "--branches", "--tags", "--remotes", "-p", "--no-color", "--format=%H")
    assert not _real_hits(history), "a secret-shaped string sits in git history"
