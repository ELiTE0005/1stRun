"""Every main page of the site carries the same footer, byte for byte."""

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
PAGES = ["index.html", "doc-test/index.html", "doc-audit/index.html", "plan/index.html", "judges/index.html"]
FOOTER = re.compile(r'<footer class="sf">.*?</footer>', re.S)


def _footers():
    return {p: FOOTER.findall((DOCS / p).read_text(encoding="utf-8")) for p in PAGES}


def test_each_page_has_one_shared_footer():
    found = _footers()
    for page, blocks in found.items():
        assert len(blocks) == 1, f"{page} has {len(blocks)} shared footers"
        assert "/assets/site-footer.css" in (DOCS / page).read_text(encoding="utf-8")
    assert len({b[0] for b in found.values()}) == 1, "the footer markup differs between pages"


def test_footer_local_links_exist():
    block = _footers()["index.html"][0]
    for href in re.findall(r'(?:href|src)="(/[^"]*)"', block):
        target = DOCS / href.lstrip("/")
        if href.endswith("/"):
            target = target / "index.html"
        assert target.is_file(), f"footer link {href} has no file in docs/"
