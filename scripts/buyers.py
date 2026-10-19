"""Turn the run log into a ranked buyer list. Company-level data only: no people, no emails.

1. Every docs site FirstRun ran on (docs/runs/index.json) or audited (docs/audits/index.json) maps to a company domain.
2. treg enriches each domain once ($0.0018 a hit, capped at $0.01 a call).
3. Jev scores each company in one call: is it a FirstRun buyer, and did the run show a problem its users hit?
4. Code ranks and writes business/buyers.csv and business/buyers.md.

    python scripts/buyers.py            # uses the cached enrichment in business/.buyers_cache.json
    python scripts/buyers.py --refresh  # calls treg again
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from firstrun import config  # noqa: E402

CACHE = ROOT / "business" / ".buyers_cache.json"
SKIP = {"github.com", "raw.githubusercontent.com", "web.archive.org", "httpbin.org", "framesurge.sh", "docs.rs"}
# Docs hosts whose company domain differs from the host, and audited repos by owner.
DOMAIN = {"docs.getdbt.com": "getdbt.com", "help.altimate.ai": "altimate.ai", "help.accuknox.com": "accuknox.com",
          "typer.tiangolo.com": "fastapi.tiangolo.com", "fastapi.tiangolo.com": "fastapi.tiangolo.com",
          "flask.palletsprojects.com": "palletsprojects.com", "flask-sqlalchemy.palletsprojects.com": "palletsprojects.com",
          "docs.astral.sh": "astral.sh", "docs.pola.rs": "pola.rs", "python-httpx.org": "encode.io",
          "AltimateAI/altimate-code": "altimate.ai", "entireio/cli": "entire.io", "dbt-labs/dbt-core": "getdbt.com",
          "fastapi/typer": "fastapi.tiangolo.com"}
ICP = ("FirstRun sells to the DevRel or docs team of a company that ships a developer product with public quickstart "
       "docs, at $49 to $299 a month. A volunteer open-source project with no company behind it rarely pays.")


def domain_of(host: str) -> str | None:
    if host in DOMAIN:
        return DOMAIN[host]
    if host in SKIP or "/" in host:
        return None
    return re.sub(r"^(docs|help|www|learn|developers)\.", "", host)


def findings() -> dict[str, list[dict]]:
    """domain -> what FirstRun found there, newest first."""
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads((ROOT / "docs/runs/index.json").read_text(encoding="utf-8"))["runs"]:
        d = None if r["fixture"] else domain_of(r["target"])
        if d:
            out[d].append({"kind": "run", "status": r["status"], "summary": r["summary"], "fixes": r["fixes"],
                           "link": f"https://1run.netlify.app/run.html#ex={r['id']}"})
    for a in json.loads((ROOT / "docs/audits/index.json").read_text(encoding="utf-8"))["audits"]:
        d = domain_of(a["repo"])
        if d:
            out[d].append({"kind": "audit", "status": f"{a['stale']} stale, {a['uncovered']} features with no docs",
                           "summary": f"{a['pages']} pages audited", "fixes": 0,
                           "link": f"https://1run.netlify.app/audit.html?id={a['id']}"})
    return out


def enrich(domains: list[str], refresh: bool) -> dict[str, dict]:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() and not refresh else {}
    for d in domains:
        if d in cache:
            continue
        p = subprocess.run(["treg", "call", "treg.companies.enrich", "--data", json.dumps({"domain": d}),
                            "--header", "X-Treg-Route-Max-Cost: 0.01"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        try:
            body = json.loads(p.stdout[p.stdout.index("{"):])
            raw = ((body.get("raw") or {}).get("data") or {}).get("companies") or [{}]
            cache[d] = {**(body.get("output") or {}), "keywords": (raw[0].get("keywords") or "")[:400],
                        "funding": raw[0].get("totalFunding")}
        except (ValueError, KeyError):
            cache[d] = {"name": d, "error": (p.stderr or p.stdout)[:200]}
        CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return cache


def judge(rows: list[dict]) -> None:
    config.load_env()
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise SystemExit("TYPESAFE_API_KEY is not set")
    state = {"ideal_customer": ICP,
             "companies": {str(i): {"name": r["name"], "domain": r["domain"], "industry": r.get("industry"),
                                    "employees": r.get("employees"), "keywords": r.get("keywords", "")[:300],
                                    "firstrun_found": [f"{f['kind']}: {f['status']}. {f['summary']}" for f in r["found"][:3]]}
                           for i, r in enumerate(rows)}}
    q = {}
    for i in range(len(rows)):
        q[f"fit{i}"] = {"type": "score", "criteria": ["not a buyer", "weak fit", "good fit", "ideal fit"],
                        "instructions": f"Company {i}: how well does it match the ideal customer?"}
        q[f"pain{i}"] = {"type": "noul", "instructions": f"Company {i}: do FirstRun's findings show a docs problem "
                                                         f"that this company's users would actually hit?"}
    r = httpx.post("https://api.typesafe.ai/v1/systemone", json={"model": "jev-latest", "state": state, "questions": q},
                   headers={"Authorization": f"Bearer {key}"}, timeout=120)
    r.raise_for_status()
    a = r.json()["answers"]
    for i, row in enumerate(rows):
        row["fit"] = int(a[f"fit{i}"]["score"])
        row["pain"] = round(float(a[f"pain{i}"]["noul"]), 2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    found = findings()
    info = enrich(sorted(found), args.refresh)
    rows = [{"domain": d, "name": info.get(d, {}).get("name") or d, **{k: info.get(d, {}).get(k) for k in
             ("industry", "employees", "location", "keywords", "funding")}, "found": found[d]} for d in sorted(found)]
    judge(rows)
    labels = ["not a buyer", "weak fit", "good fit", "ideal fit"]
    rows.sort(key=lambda r: (-r["fit"], -r["pain"], r["name"].lower()))
    with (ROOT / "business/buyers.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["company", "domain", "industry", "employees", "fit", "pain", "firstrun_found", "proof"])
        for r in rows:
            top = r["found"][0]
            w.writerow([r["name"], r["domain"], r.get("industry") or "", r.get("employees") or "", labels[r["fit"]],
                        r["pain"], f"{top['kind']}: {top['status']}. {top['summary']}"[:200], top["link"]])
    good = [r for r in rows if r["fit"] >= 2]
    L = ["# Buyers FirstRun Already Has Proof For", "",
         f"FirstRun ran on or audited the docs of {len(rows)} companies. Jev rates {len(good)} of them a good or ideal "
         "fit for a $49 to $299 plan. Each row links the replay or audit that proves the finding.", "",
         "Company data comes from treg at $0.0018 a lookup. It holds no people and no emails.", "",
         "| Company | Employees | Fit | Pain | What FirstRun found | Proof |", "|---|---|---|---|---|---|"]
    for r in rows:
        top = r["found"][0]
        L.append(f"| {r['name']} | {r.get('employees') or '?'} | {labels[r['fit']]} | {r['pain']:.2f} | "
                 f"{top['kind']}: {top['status']} | [open]({top['link']}) |")
    (ROOT / "business/buyers.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    for r in rows:
        print(f"{labels[r['fit']]:<12} pain={r['pain']:.2f} {r['name']:<28} {r.get('employees') or '?':>6}  {r['found'][0]['status']}")


if __name__ == "__main__":
    main()
