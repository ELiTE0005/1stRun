import os
from pathlib import Path

import pytest

# Tests never export traces. Set ONESTRUN_EXPORT_TESTS=1 to turn that off on purpose.
if os.environ.get("ONESTRUN_EXPORT_TESTS") != "1":
    os.environ["ONESTRUN_NO_EXPORT"] = "1"
    # Empty values block config.load_env from reading the real keys out of .env.
    os.environ["LANGFUSE_PUBLIC_KEY"] = ""
    os.environ["LANGFUSE_SECRET_KEY"] = ""
    # An empty value also keeps a real Firecrawl key in .env out of every test.
    os.environ.setdefault("FIRECRAWL_API_KEY", "")

# No test reaches a real judge model, even on a machine that runs Ollama. A test that wants one sets its URL.
os.environ.setdefault("ONESTRUN_JUDGE", "off")

# Tests never write the public site log in docs/runs or docs/audits. A missing folder turns publishing off.
os.environ["ONESTRUN_SITE_DIR"] = str(Path(__file__).parent / "_no_site" / "runs")

from onestrun import config  # noqa: E402
from onestrun.models import Runbook  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    """Skip tests marked live unless ONESTRUN_LIVE=1."""
    if os.environ.get("ONESTRUN_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set ONESTRUN_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs network, Docker or a model")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def load_doc():
    def _load(name: str) -> str:
        name = name if name.endswith(".md") else f"{name}.md"
        return (FIXTURES / "docs" / name).read_text(encoding="utf-8")
    return _load


@pytest.fixture
def load_runbook():
    def _load(name: str) -> Runbook:
        name = name if name.endswith(".json") else f"{name}.json"
        text = (FIXTURES / "runbooks" / name).read_text(encoding="utf-8")
        return Runbook.model_validate_json(text)
    return _load


@pytest.fixture
def tmp_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ONESTRUN_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def tmp_precedents(tmp_path, monkeypatch):
    path = tmp_path / "precedents.json"
    monkeypatch.setenv("ONESTRUN_PRECEDENTS", str(path))
    monkeypatch.setattr(config, "PRECEDENTS_FILE", path)
    return path


@pytest.fixture
def fake_llm():
    """Factory: fake_llm(["a", "b"]) returns a callable that yields the replies in order."""
    def _make(responses):
        queue = list(responses)
        calls = []

        def _call(prompt: str) -> str:
            calls.append(prompt)
            if not queue:
                raise AssertionError("fake_llm ran out of canned responses")
            return queue.pop(0)

        _call.calls = calls
        return _call
    return _make


@pytest.fixture(scope="session", autouse=True)
def _tracing_never_exports():
    """Mark tracing started with export off, so no tracing.log or span in a test leaves the machine."""
    if os.environ.get("ONESTRUN_EXPORT_TESTS") == "1":
        yield
        return
    from onestrun import tracing

    tracing._ready = True  # init_tracing must not start a Langfuse client. With no client every call is a no-op.
    yield
