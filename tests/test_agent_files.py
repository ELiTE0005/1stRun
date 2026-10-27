"""The agent files stay in step with the code: llms-full.txt, the error table, the headers and the page links. Offline."""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

from onestrun.cli import ERROR_CODES

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
AGENT = (DOCS / "agent.md").read_text(encoding="utf-8")


def test_llms_full_is_current():
    spec = importlib.util.spec_from_file_location("build_llms_full", ROOT / "scripts" / "build_llms_full.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    current = (DOCS / "llms-full.txt").read_text(encoding="utf-8")
    assert current == mod.build(), "docs/llms-full.txt is stale. Run: python scripts/build_llms_full.py"


def test_agent_md_names_every_error_code_and_stays_short():
    codes = {code for _, code in ERROR_CODES} | {"step_failed", "receipt_invalid", "not_ready", "internal"}
    missing = sorted(c for c in codes if f"`{c}`" not in AGENT)
    assert not missing, f"add these codes to the error table in docs/agent.md: {missing}"
    assert len(AGENT.splitlines()) <= 250


def test_llms_txt_follows_the_convention():
    text = (DOCS / "llms.txt").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0].startswith("# ") and lines[2].startswith("> ")
    assert "https://1strun.rajbir.tech/agent.md" in text.split("## ")[1]  # agent.md is the first link


def test_netlify_serves_agent_files_as_utf8_with_cors():
    rules = {h["for"]: h["values"] for h in tomllib.loads((ROOT / "netlify.toml").read_text(encoding="utf-8"))["headers"]}
    for path, kind in (("/agent.md", "text/markdown"), ("/llms.txt", "text/plain"), ("/llms-full.txt", "text/plain")):
        assert rules[path]["Content-Type"] == f"{kind}; charset=utf-8"
        assert rules[path]["Access-Control-Allow-Origin"] == "*"
        assert "max-age=" in rules[path]["Cache-Control"]
    assert (DOCS / "robots.txt").exists()


def test_pages_point_agents_at_agent_md():
    for page in ("index.html", "doc-test/index.html", "doc-audit/index.html"):
        html = (DOCS / page).read_text(encoding="utf-8")
        assert '<link rel="alternate" type="text/markdown" href="/agent.md"' in html, page
    for page in ("doc-test/index.html", "doc-audit/index.html"):
        html = (DOCS / page).read_text(encoding="utf-8")
        assert "Read https://1strun.rajbir.tech/agent.md and follow it." in html, page
    assert '<a href="/agent.md">For agents</a>' in (DOCS / "index.html").read_text(encoding="utf-8")


def test_skill_frontmatter():
    text = (ROOT / "skills" / "1strun" / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"---\nname: (\S+)\ndescription: (.+?)\n---\n", text, re.S)
    assert m and m.group(1) == "1strun" and len(m.group(2)) <= 1024
