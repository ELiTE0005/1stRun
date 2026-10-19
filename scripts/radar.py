"""FirstRun Radar: rank candidate quickstarts before spending a run on them.

Exa finds candidate quickstart pages for free. Jev reads each page excerpt once and answers three typed
questions per page. Code turns the answers into a ranked target list, so no model reads pages one by one.

    python scripts/radar.py candidates.json --top 20 --out targets-radar.txt

candidates.json is a list of {"url", "title", "text"}. scripts/radar.py --from-exa parses saved
`mcporter call exa.web_search_exa` output files instead.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from firstrun import config  # noqa: E402

JEV_URL = "https://api.typesafe.ai/v1/systemone"
BATCH = 25

QUESTIONS = {
    "runnable": ("noul", "Can every step of this quickstart run unattended in a fresh Linux container, "
                         "with no account sign-up, API key, GPU, browser or GUI?"),
    "fragile": ("noul", "Is a new developer likely to hit a broken, outdated or missing step in this quickstart, "
                        "such as a renamed package, a changed flag or an unstated prerequisite?"),
    "reach": ("score", "How many developers are likely to follow this quickstart?"),
    "official": ("noul", "Is this page the official documentation or README of the tool itself, "
                         "not a blog post, course, mirror or third-party tutorial?"),
}
REACH = ["niche", "small community", "popular", "very popular"]


def from_exa(paths: list[str]) -> list[dict]:
    """Parse `Title: / URL: / Text:` blocks out of saved Exa results."""
    out = []
    for p in paths:
        text = Path(p).read_text(encoding="utf-8", errors="replace")
        for block in re.split(r"\n(?=Title: )", text):
            url = re.search(r"^URL: (\S+)", block, re.M)
            if not url:
                continue
            title = re.search(r"^Title: (.*)$", block, re.M)
            body = block.split("Text:", 1)[1] if "Text:" in block else block
            out.append({"url": url.group(1), "title": title.group(1).strip() if title else "", "text": body.strip()})
    return out


def dedupe(cands: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in cands:
        u = c["url"].rstrip("/").removesuffix(".md").removesuffix("/index")
        host = re.sub(r"^https?://", "", u).split("/")[0]
        if u in seen or "pypi.org" in host or u.endswith((".sh", ".ps1", ".cmd")):
            continue
        seen.add(u)
        out.append({**c, "url": u})
    return out


def ask(cands: list[dict]) -> dict[int, dict]:
    config.load_env()
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise SystemExit("TYPESAFE_API_KEY is not set")
    state = {str(i): {"url": c["url"], "title": c["title"], "page_excerpt": c["text"][:1800]} for i, c in enumerate(cands)}
    q = {}
    for i in range(len(cands)):
        for name, (typ, text) in QUESTIONS.items():
            q[f"{name}{i}"] = {"type": typ, "instructions": f"Page {i}: {text}"}
            if typ == "score":
                q[f"{name}{i}"]["criteria"] = REACH
    r = httpx.post(JEV_URL, json={"model": "jev-latest", "state": state, "questions": q},
                   headers={"Authorization": f"Bearer {key}"}, timeout=120)
    r.raise_for_status()
    a = r.json()["answers"]
    out = {}
    for i in range(len(cands)):
        out[i] = {"runnable": float(a[f"runnable{i}"]["noul"]), "fragile": float(a[f"fragile{i}"]["noul"]),
                  "reach": int(a[f"reach{i}"]["score"]), "official": float(a[f"official{i}"]["noul"])}
    return out


def rank(cands: list[dict]) -> list[dict]:
    rows = []
    for start in range(0, len(cands), BATCH):
        part = cands[start:start + BATCH]
        for i, v in ask(part).items():
            rows.append({**part[i], **v})
    # Policy lives here, not in the questions: a run only pays off when it can run, may break, and people read it.
    for r in rows:
        r["priority"] = round(r["runnable"] * (0.5 + r["fragile"]) * (1 + r["reach"]), 3)
    return sorted(rows, key=lambda r: -r["priority"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--from-exa", action="store_true")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--min-runnable", type=float, default=0.5)
    ap.add_argument("--min-official", type=float, default=0.5)
    ap.add_argument("--out", default="targets-radar.txt")
    args = ap.parse_args()
    cands = from_exa(args.inputs) if args.from_exa else json.loads(Path(args.inputs[0]).read_text(encoding="utf-8"))
    rows = rank(dedupe(cands))
    Path("evidence/radar.json").write_text(json.dumps([{k: v for k, v in r.items() if k != "text"} for r in rows], indent=1),
                                  encoding="utf-8")
    keep = [r for r in rows if r["runnable"] >= args.min_runnable and r["official"] >= args.min_official][:args.top]
    lines = ["# FirstRun Radar: Exa candidates ranked by Jev (runnable x fragile x reach). See evidence/radar.json."]
    lines += [r["url"] for r in keep]
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    for r in rows:
        mark = "RUN " if r in keep else "    "
        print(f"{mark}{r['priority']:.2f} off={r['official']:.2f} run={r['runnable']:.2f} fragile={r['fragile']:.2f} reach={REACH[r['reach']]:<15} {r['url'][:80]}")


if __name__ == "__main__":
    main()
