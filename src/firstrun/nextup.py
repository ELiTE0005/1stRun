"""What to ship next: one ranked list built from the audit's cards, pages and features, with a suggested owner each.

Every number in a title, a rationale or a reason comes from a field of the board or from the git history, and the
score follows WEIGHTS and nothing else, so a maintainer can recompute any rank by hand. The same code serves a new
audit and the backfill of an old board.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import date, datetime
from pathlib import PurePosixPath

WEIGHTS = {"impact": 0.30, "urgency": 0.25, "evidence": 0.20, "judged": 0.15, "ease": 0.10}
EASE = {"S": 1.0, "M": 0.6, "L": 0.3}
TOP = 10
CAPS = {"refresh": 5, "document": 5, "announce": 2, "release": 1, "quickstart": 1}
ITEMS_MAX = 30
NEXT_BYTES = 24_500
EXTRA_REFRESH = 10
# (evidence authorship, code folders, docs folder) per kind. Release notes go to whoever tagged the release.
AFF = {"document": (0.50, 0.35, 0.15), "refresh": (0.25, 0.30, 0.45), "announce": (0.80, 0.20, 0.0),
       "quickstart": (0.0, 0.0, 1.0), "release": (1.0, 0.0, 0.0)}
OWNER_MIN, RUNNER_MIN, POOL = 0.25, 0.15, 0.6
FLOOR = 1.0  # below one fresh one-file commit of weight, nobody knows a code folder
# A docs target is often one file (README.md at the root), and one edit 3 months ago weighs 0.5.
FLOOR_DOCS = 0.5
_ENTRY = re.compile(r"readme|index|quickstart|getting[-_]started|install|introduction|overview", re.I)
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


# ----------------------------------------------------------------------------- small helpers

def _day(s: str | None) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _days(as_of: date, s: str | None) -> int | None:
    d = _day(s)
    return max(0, (as_of - d).days) if d else None


def _fmt(s: str | None, year: bool = True) -> str:
    d = _day(s)
    if not d:
        return str(s or "")
    return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}" if year else f"{_MONTHS[d.month - 1]} {d.day}"


def _ago(n: int) -> str:
    if n <= 0:
        return "today"
    if n == 1:
        return "1 day ago"
    if n < 14:
        return f"{n} days ago"
    if n < 60:
        return f"{n // 7} weeks ago"
    if n < 730:
        return f"{n // 30} months ago"
    return f"{n // 365} years ago"


def _n(k: int, word: str) -> str:
    return f"{k} {word}" + ("" if k == 1 else "s")


def _half(days: int | None, half_life: float) -> float:
    return 2 ** (-days / half_life) if days is not None else 0.0


def _clean(subject: str) -> str:
    from firstrun.audit import _clean as clean

    return clean(subject)


def _contributor(path: str) -> bool:
    from firstrun.audit import is_contributor_doc

    return is_contributor_doc(path)


def _ev(e: dict) -> dict:
    subject = e.get("subject") or ""
    pr = e.get("pr") or (re.search(r"\(#(\d+)\)\s*$", subject) or [None, None])[1]
    return {"sha": str(e.get("sha") or "")[:9], "date": e.get("date") or "", "subject": subject[:100], "pr": pr}


def _parent(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent in (".", "") else parent + "/"


def _entry(path: str) -> bool:
    p = re.sub(r"^https?://[^/]+/?", "", path).strip("/")
    return bool(_ENTRY.search(PurePosixPath(p).name)) or len([x for x in p.split("/") if x]) <= 2


# ----------------------------------------------------------------------------- candidates

def _refresh(p: dict, card: dict | None, as_of: date, sitemap: bool) -> dict:
    k = int(p.get("relevant_since") or 0)
    age = int(p.get("age_days") or 0)
    ev = [_ev(e) for e in p.get("evidence") or []]
    newest = ev[0]["date"] if ev else None
    d_new = _days(as_of, newest)
    status, judge = p.get("status"), p.get("judge") or "text"
    parts = {"impact": 0.45 + 0.25 * _entry(p["path"]) + 0.30 * min(1, k / 20),
             "urgency": 0.5 * min(1, age / 730) + 0.5 * _half(d_new, 90),
             "evidence": min(1, k / 5),
             "judged": 1.0 if judge == "jev" and status == "stale" else 0.6 if status == "stale" else 0.35}
    effort = "S" if k <= 3 else "M" if k <= 10 else "L"
    why = ("3 or fewer commits changed its topic, so the update is small." if effort == "S" else
           "4 to 10 commits changed its topic, so the update is medium." if effort == "M" else
           "More than 10 commits changed its topic, so expect a rewrite.")
    if p.get("ancient") and effort != "L":
        effort = "M" if effort == "S" else "L"
        why += " The page is over 2 years old, which adds one size."
    if sitemap:
        rationale = (f"Last updated {_fmt(p.get('last_touched'))}, {age} days ago, "
                     "and the sitemap gives no product history.")
        why_now = f"The page was last updated {age} days ago"
    else:
        last = (f"Last edited {_fmt(p['last_touched'])}." if p.get("last_touched")
                else "Last edited before the history window.")
        tail = ("and Jev expects the page is now wrong." if judge == "jev" and status == "stale"
                else "and Jev did not read it.")
        rationale = (f"{last} Since then {_n(k, 'commit')} changed code on its topic, newest {ev[0]['sha']} on "
                     f"{_fmt(newest)}, {tail}" if ev else f"{last} It is {age} days old.")
        why_now = (f"Code moved {d_new} days ago under a page last edited {age} days ago" if ev
                   else f"The page was last edited {age} days ago")
    action = (card or {}).get("action") or (
        ("Jev read the page and the commits and expects at least one to make it wrong or incomplete. "
         if judge == "jev" and status == "stale" else "")
        + "Re-read the page against the current code and update or delete what changed.")
    return {"kind": "refresh", "title": f"Update {(p.get('title') or '').strip() or p['path']}", "path": p["path"],
            "rationale": rationale, "why_now": why_now, "parts": parts, "effort": effort, "effort_why": why,
            "judge": "jev" if judge == "jev" else "text", "action": action, "count": k, "evidence": ev[:5],
            "_shas": [e["sha"] for e in ev], "_files": [], "_docs": p["path"], "_newest": newest or "",
            "_primary": ("docs", p["path"])}


def _feature_of(e: dict, by_sha: dict, card: dict) -> dict:
    """The board feature behind an evidence row, or one rebuilt from the card when the board kept only 40."""
    f = by_sha.get(e.get("sha"))
    if f:
        return f
    m = re.search(r"Add a section to (.+?), the closest page", card.get("action") or "")
    return {"sha": e.get("sha"), "date": e.get("date"), "subject": e.get("subject") or "", "pr": e.get("pr"),
            "strong": [], "files": [], "area": "", "area_src": "", "covered": False, "term": "",
            "judge": "jev" if "Jev read" in (card.get("why") or "") else "text",
            "closest_page": m.group(1) if m else ""}


def _cluster(card: dict, feats: list[dict], by_sha: dict, pages: list[dict], as_of: date, mom: dict) -> dict:
    ev_feats = [_feature_of(e, by_sha, card) for e in card.get("evidence") or []]
    m = re.search(r"`([^`]+)`", card.get("title") or "")
    area = next((f["area"] for f in ev_feats if f.get("area")), m.group(1) if m else "")
    joined = [f for f in feats if f.get("area") == area and not f.get("covered")] or ev_feats
    joined = sorted(joined, key=lambda f: f.get("date") or "", reverse=True)
    n = int(card.get("count") or len(joined))
    newest = joined[0]
    since = re.search(r"since (\d{4}-\d{2}-\d{2})", card.get("why") or "")
    first = since.group(1) if since else min(f.get("date") or "" for f in joined)
    judged = any(f.get("judge") == "jev" for f in joined)
    strong = any(f.get("area_src") == "scope" or f.get("strong") for f in joined)
    own = re.search(r"Add them to (.+?), the `", card.get("action") or "")
    own_path = own.group(1) if own else ""
    if own_path and _contributor(own_path):  # an old board may cite a development doc as the page
        own_path = ""
    if not own_path and (card.get("title") or "").startswith("Document the new"):
        own_path = next(iter(sorted((p["path"] for p in pages if area and area.lower() in p["path"].lower()
                                     and not _contributor(p["path"])), key=len)), "")
    d = _days(as_of, newest.get("date"))
    parts = {"impact": 0.55 + 0.25 * min(1, n / 10) + 0.20 * min(1, (mom.get(area) or {}).get("commits", 0) / 30),
             "urgency": _half(d, 45), "evidence": min(1, n / 5) * (1.0 if strong else 0.85),
             "judged": 1.0 if judged else 0.6}
    if own_path:
        effort = "M" if n <= 6 else "L"
        why = ("Up to 6 changes go into a page that exists." if effort == "M"
               else "More than 6 changes go into a page that exists.")
        title = f"Add the new {area} changes to {PurePosixPath(own_path).name}"
        tail = "Jev found none of them explained in the docs." if judged else "no docs page names them."
    else:
        effort = "L" if n >= 8 else "M"
        why = "A new page for fewer than 8 changes." if effort == "M" else "A new page for 8 or more changes."
        title = f"Write a page for {area}"
        tail = "Jev found no docs page that explains them." if judged else "no docs page names them."
    rationale = (f"{n} user-facing {area} changes shipped since {_fmt(first)}, newest {newest['sha']} on "
                 f"{_fmt(newest.get('date'), year=False)}, and {tail}")
    files = [x for f in joined for x in f.get("files") or []]
    return {"kind": "document", "title": title, "path": own_path, "rationale": rationale,
            "why_now": f"Shipped {_ago(d)}" if d is not None else "", "parts": parts, "effort": effort, "effort_why": why,
            "judge": "jev" if judged else "text", "action": card.get("action") or "", "count": n,
            "evidence": [_ev(f) for f in joined[:5]], "_shas": [f["sha"] for f in joined], "_files": files,
            "_docs": own_path or next((f.get("closest_page") for f in joined if f.get("closest_page")), ""),
            "_newest": newest.get("date") or "", "_primary": ("code", files[0]) if files else None, "_area": area}


def _single(card: dict, by_sha: dict, as_of: date) -> dict | None:
    ev = card.get("evidence") or []
    if not ev:
        return None
    f = _feature_of(ev[0], by_sha, card)
    d = _days(as_of, f.get("date"))
    strong, pr, jev = bool(f.get("strong")), f.get("pr"), f.get("judge") == "jev"
    closest = f.get("closest_page") or ""
    parts = {"impact": 0.55 + 0.10 * strong, "urgency": _half(d, 45),
             "evidence": 0.6 + 0.2 * strong + 0.2 * bool(pr), "judged": 1.0 if jev else 0.6}
    clean = _clean(f["subject"])
    tail = (f"Jev read {closest} and found it does not explain it." if jev and closest
            else "Jev found no docs page that explains it." if jev
            else f"no docs page names `{f.get('term') or clean}`.")
    rationale = f'{f["sha"]} shipped "{clean}" on {_fmt(f.get("date"))}' + (f" in #{pr}" if pr else "") + f", and {tail}"
    effort = "S" if closest else "M"
    return {"kind": "document", "title": f"Document: {clean}", "path": "", "rationale": rationale,
            "why_now": f"Shipped {_ago(d)}" if d is not None else "", "parts": parts, "effort": effort,
            "effort_why": (f"One change, and {closest} is the page to add it to." if closest
                           else "One change with no close page, so it needs a short new page."),
            "judge": "jev" if jev else "text", "action": card.get("action") or "", "count": 1, "evidence": [_ev(f)],
            "_shas": [f["sha"]], "_files": f.get("files") or [], "_docs": closest, "_newest": f.get("date") or "",
            "_primary": ("code", f["files"][0]) if f.get("files") else None}


def _announce(card: dict, by_sha: dict, as_of: date) -> dict | None:
    ev = card.get("evidence") or []
    if not ev:
        return None
    f = _feature_of(ev[0], by_sha, card)
    d = _days(as_of, f.get("date"))
    pr = f.get("pr")
    clean = _clean(f["subject"])
    parts = {"impact": 0.25, "urgency": _half(d, 21), "evidence": 0.5 + 0.2 * bool(pr), "judged": 0.4}
    rationale = (f'{f["sha"]} shipped "{clean}" on {_fmt(f.get("date"))}' + (f" in #{pr}" if pr else "")
                 + (f", {_n(d, 'day')} before this audit." if d is not None else "."))
    return {"kind": "announce", "title": f"Announce: {clean}", "path": "", "rationale": rationale,
            "why_now": f"Shipped {_ago(d)}" if d is not None else "", "parts": parts, "effort": "S",
            "effort_why": "One change to announce.", "judge": "jev" if f.get("judge") == "jev" else "text",
            "action": card.get("action") or "", "count": 1, "evidence": [_ev(f)], "_shas": [f["sha"]],
            "_files": f.get("files") or [], "_docs": "", "_newest": f.get("date") or "",
            "_primary": ("code", f["files"][0]) if f.get("files") else None, "_key": clean.lower()}


def _release(card: dict, rel: dict, as_of: date, changelog_recent: bool) -> dict | None:
    n = int(rel.get("commits") or 0)
    if not n or rel.get("in_changelog"):  # the changelog already names this release
        return None
    name, prev = rel.get("name") or "", rel.get("previous") or ""
    d = _days(as_of, rel.get("date"))
    parts = {"impact": 0.5 + 0.15 * (not changelog_recent), "urgency": _half(d, 30), "evidence": min(1, n / 10),
             "judged": 0.6}
    tail = ("a changelog file changed in the last 60 days." if changelog_recent
            else "no changelog file changed in the last 60 days.")
    if name == "Unreleased":
        title = "Publish release notes for the last 30 days"
        rationale = f"{_n(n, 'commit')} landed in the 30 days before {_fmt(rel.get('date'))} with no release tag, and {tail}"
        why_now = "No release tag covers the last 30 days"
    else:
        title = f"Publish the {name} release notes"
        span = f"between {prev} and {name}" if prev else f"up to {name}"
        rationale = f"{_n(n, 'commit')} landed {span} ({_fmt(rel.get('date'))}), and {tail}"
        why_now = f"{name} shipped {_ago(d)}" if d is not None else ""
    return {"kind": "release", "title": title, "path": "", "rationale": rationale, "why_now": why_now, "parts": parts,
            "effort": "S", "effort_why": "The draft notes are ready to edit.", "judge": "text",
            "action": card.get("action") or "", "count": n, "evidence": [], "_shas": [], "_files": [], "_docs": "",
            "_newest": rel.get("date") or "", "_primary": None, "_tag": name}


def _quickstart(card: dict, pages: list[dict]) -> dict:
    readme = sorted((p for p in pages if re.search(r"(^|/)(readme|quickstart|getting[-_]started)[^/]*$", p["path"], re.I)),
                    key=lambda p: (not p["path"].lower().startswith("readme"), len(p["path"])))
    page = readme[0] if readme else None
    moved = bool(page) and page.get("status") in ("stale", "unchecked", "aging")
    parts = {"impact": 0.4 + 0.3 * moved, "urgency": 0.3, "evidence": 0.3, "judged": 0.5}
    if page and page.get("last_touched"):
        rationale = (f"{page['path']} was last edited on {_fmt(page['last_touched'])}, "
                     "and only a run in a clean container proves its steps still work.")
    else:
        rationale = "An audit reads text, and only a run in a clean container proves the quickstart steps still work."
    return {"kind": "quickstart", "title": "Prove the quickstart still runs", "path": "", "rationale": rationale,
            "why_now": "A text audit cannot prove a run", "parts": parts, "effort": "S",
            "effort_why": "One run of firstrun in a clean container.", "judge": "text",
            "action": card.get("action") or "", "count": 0, "evidence": [], "_shas": [], "_files": [],
            "_docs": page["path"] if page else "README.md", "_newest": "",
            "_primary": None}


def candidates(board: dict, as_of: date, mom: dict, changelog_recent: bool) -> list[dict]:
    feats = board.get("features") or []
    by_sha = {f["sha"]: f for f in feats}
    pages = board.get("pages") or []
    by_path = {p["path"]: p for p in pages}
    sitemap = board.get("mode") == "sitemap"
    items, refreshed = [], set()
    for c in board.get("cards") or []:
        kind = c.get("kind")
        it = None
        if kind == "refresh":
            path = (c.get("title") or "")[len("Refresh "):]
            if path in by_path:
                it = _refresh(by_path[path], c, as_of, sitemap)
                refreshed.add(path)
        elif kind == "document":
            it = _cluster(c, feats, by_sha, pages, as_of, mom) if "count" in c and c.get("evidence") else _single(c, by_sha, as_of)
        elif kind == "feature":
            it = _announce(c, by_sha, as_of)
        elif kind == "automate" and not sitemap:
            it = _release(c, board.get("release") or {}, as_of, changelog_recent)
        elif kind == "quickstart":
            it = _quickstart(c, pages)
        if it:
            items.append(it)
    extra = sorted((p for p in pages if p.get("status") in ("stale", "unchecked") and p["path"] not in refreshed),
                   key=lambda p: (-(p.get("relevant_since") or 0), p["path"]))[:EXTRA_REFRESH]
    items += [_refresh(p, None, as_of, sitemap) for p in extra]
    # One announcement per change, and none for a change a document item already covers.
    documented = {s for it in items if it["kind"] == "document" for s in it["_shas"]}
    seen, out = set(), []
    for it in items:
        if it["kind"] == "announce":
            if it["_key"] in seen or it["_shas"][0] in documented:
                continue
            seen.add(it["_key"])
        out.append(it)
    return out


def score(parts: dict, effort: str) -> int:
    p = {**parts, "ease": EASE[effort]}
    return round(100 * sum(WEIGHTS[k] * p[k] for k in WEIGHTS))


def rank(items: list[dict]) -> list[dict]:
    """Score desc, newest evidence, title. Kind caps hold inside the top 10, and overflow continues at 11."""
    for it in items:
        it["parts"] = {k: round(min(1.0, max(0.0, v)), 2) for k, v in it["parts"].items()}
        it["score"] = score(it["parts"], it["effort"])
        it["parts"]["ease"] = EASE[it["effort"]]
    items = sorted(items, key=lambda it: it["title"])
    items = sorted(items, key=lambda it: it["_newest"] or "", reverse=True)
    items = sorted(items, key=lambda it: -it["score"])
    seen, unique = set(), []  # one item per title: the best-scored copy stays
    for it in items:
        norm = re.sub(r"[^a-z0-9]+", " ", it["title"].lower()).strip()
        if norm not in seen:
            seen.add(norm)
            unique.append(it)
    items = unique
    top, rest, used = [], [], Counter()
    for it in items:
        if len(top) < TOP and used[it["kind"]] < CAPS.get(it["kind"], TOP):
            used[it["kind"]] += 1
            top.append(it)
        else:
            rest.append(it)
    # Too few kinds to fill 10 under the caps: the best of the overflow fills the gap, and the 10 stay in score order.
    while len(top) < TOP and rest:
        top.append(rest.pop(0))
    order = {id(it): i for i, it in enumerate(items)}
    top.sort(key=lambda it: order[id(it)])
    out = (top + rest)[:ITEMS_MAX]
    for i, it in enumerate(out, 1):
        it["rank"] = i
    return out


# ----------------------------------------------------------------------------- owners

def affinity(it: dict, ctx) -> dict[str, dict]:
    """{person key: {"aff", "A", "C", "D", "k", "best_dir"}} for everyone with any claim on the item."""
    from firstrun.audit import _is_product
    from firstrun.team import _dirs

    a, b, g = AFF[it["kind"]]
    shas = [s[:9] for s in it["_shas"]]
    out: dict[str, dict] = {}
    if it["kind"] == "release":
        if ctx.release_tagger:
            return {ctx.release_tagger: {"aff": 1.0, "A": 1.0, "C": 0, "D": 0, "tagger": True}}
        # Release ranges are mostly bot commits (release notes, bumps). Only commits people made can make an owner.
        shas = [s for s in ctx.release_shas if s in ctx.pid_of_sha]
    authors = Counter(ctx.pid_of_sha[s] for s in shas if s in ctx.pid_of_sha)
    files_in: Counter = Counter()
    for f in [f for s in shas for f in ctx.files_of_sha.get(s, []) if _is_product(f)] + list(it["_files"]):
        ds = _dirs(f)
        if ds:
            files_in[ds[-1]] += 1
    code_dirs = set(files_in)
    docs = it["_docs"]
    drepo, dparent = ctx.docs_repo, _parent(docs) if docs else ""
    people = [k for k in ctx.people if not ctx.people[k]["hidden"]]
    # A code folder counts the files that sit directly in it (the package), not its subtree. Each folder is
    # judged on its own, best person = 1, and the folders count by how many of the item's files sit in them.
    # Summing raw weights instead hands the item to whoever owns the busiest folder that holds one of its files.
    C: dict[str, float] = {}
    if b and files_in:
        total = sum(files_in.values())
        for d, n in files_in.items():
            top = max((ctx.dd[k].get(("code", d), 0.0) for k in people), default=0.0)
            if top >= FLOOR:
                for k in people:
                    C[k] = C.get(k, 0.0) + n / total * ctx.dd[k].get(("code", d), 0.0) / top
    D = ({k: (ctx.dw[k].get((drepo, dparent), 0.0) if dparent else 0.0) + ctx.w[k].get((drepo, docs), 0.0)
          for k in people} if g and docs else {})
    cmax = max(C.values(), default=0.0)
    dmax = max(D.values(), default=0.0)
    for k in people:
        A = authors.get(k, 0) / len(shas) if shas else 0.0
        c = C.get(k, 0.0) / cmax if cmax >= FLOOR else 0.0
        d = D.get(k, 0.0) / dmax if dmax >= FLOOR_DOCS else 0.0
        aff = a * A + b * c + g * d
        if aff > 0:
            best = max(sorted(code_dirs), key=lambda x: ctx.dd[k].get(("code", x), 0.0)) if code_dirs else ""
            out[k] = {"aff": aff, "A": a * A, "C": b * c, "D": g * d, "k": authors.get(k, 0), "n": len(shas),
                      "code_dir": best}
    return out


def assign(affs: list[dict[str, float]], eligible, top_n: int = TOP, weight=None) -> list[tuple]:
    """Owner per item in rank order: (pick, top expert, runner-up, balanced). Inside the top 10 nobody gets more than
    max(2, ceil(10 / n) + 1) picks while someone else with at least 60% of the top affinity is free.
    A tie goes to the person with more weight in the whole repo."""
    def ranked(aff):
        return sorted(((v, k) for k, v in aff.items() if eligible(k)),
                      key=lambda x: (-round(x[0], 9), -(weight(x[1]) if weight else 0), x[1]))

    names = {k for aff in affs[:top_n] for v, k in ranked(aff) if v >= OWNER_MIN}
    cap = math.inf if len(names) <= 1 else max(2, math.ceil(top_n / len(names)) + 1)
    used, out = Counter(), []
    for i, aff in enumerate(affs):
        r = ranked(aff)
        if not r or r[0][0] < OWNER_MIN:
            out.append((None, None, None, False))
            continue
        top = r[0][1]
        pick = top
        if i < top_n:
            pool = [k for v, k in r if v >= max(OWNER_MIN, POOL * r[0][0])]
            pick = next((k for k in pool if used[k] < cap), top)
            used[pick] += 1
        runner = next((k for v, k in r if k != pick and v >= RUNNER_MIN), None)
        out.append((pick, top, runner, pick != top))
    return out


def _reason(it: dict, k: str, info: dict, ctx) -> str:
    from firstrun.team import _dirs

    name = ctx.name(k)
    if info.get("tagger"):
        return f"{name} tagged {it.get('_tag')}"
    comp = max(("A", "C", "D"), key=lambda x: (info.get(x, 0), x == "D"))
    if it["kind"] == "release" and info.get("k"):
        return f"{name} wrote {info['k']} of the {info['n']} commits people made in {it.get('_tag')}"
    if comp == "A" and info.get("k"):
        return _wrote(it, name, info)
    repo, start = (ctx.docs_repo, _parent(it["_docs"])) if comp == "D" else ("code", info.get("code_dir") or "")
    chain = list(reversed(_dirs(start + "x"))) if start else []
    # The strongest true statement: the folder, at least 5 commits deep, where this person made the largest share
    # of the last 20 commits. On a tie the deeper folder wins, because it is closer to the page.
    best = None
    for d in chain:
        m = min(20, ctx.dir_commits.get((repo, d), 0))
        if m < 5:
            continue
        mine = sum(1 for p, _ in ctx.recent_by_dir.get((repo, d), []) if p == k)
        if mine and (best is None or mine / m > best[0] / best[1]):
            best = (mine, m, d)
    if best:
        return f"{name} made {best[0]} of the last {best[1]} commits to {best[2]}"
    if comp == "D" and ctx.file_commits.get((k, repo, it["_docs"])):
        return (f"{name} made {ctx.file_commits[(k, repo, it['_docs'])]} of the "
                f"{ctx.file_commits[(repo, it['_docs'])]} edits to {it['_docs']} in the last 12 months")
    if chain:
        return f"{name} worked on {chain[0]} in the last 12 months"
    if info.get("k"):
        return _wrote(it, name, info)
    return f"{name} worked on these files in the last 12 months"


def _wrote(it: dict, name: str, info: dict) -> str:
    """Authorship of the item's own commits. The board lists at most 40 features, so a cluster can have more
    changes than listed commits, and the sentence says which number it counts."""
    k, n, total = info["k"], info["n"], max(int(it.get("count") or 0), info["n"])
    if n == 1:
        sha = it["_shas"][0][:9]
        pr = next((e.get("pr") for e in it["evidence"] if e.get("sha") == sha), None)
        ref = f"#{pr}" if pr else sha
        return f"{name} shipped it in {ref}" if total == 1 else f"{name} shipped {ref}, one of the {total} changes behind it"
    if total > n:
        return f"{name} wrote {k} of the {n} changes the board lists for it"
    return f"{name} wrote {k} of the {n} changes behind it"


def _owners(items: list[dict], ctx) -> None:
    affs_full = [affinity(it, ctx) for it in items]
    picks = assign([{k: v["aff"] for k, v in a.items()} for a in affs_full], ctx.active,
                   weight=lambda k: ctx.people[k]["weight"])
    keys = [p for pick, _, runner, _ in picks for p in (pick, runner) if p]
    pub = ctx.finish(list(dict.fromkeys(keys)))
    for it, info, (pick, _top, runner, balanced) in zip(items, affs_full, picks):
        if pick and pick not in pub:  # the map is full: an owner who is not on it is not suggested
            pick, runner, balanced = None, None, False
        it["owner"] = {"p": pub[pick], "why": _reason(it, pick, info[pick], ctx)} if pick else None
        it["runner_up"] = ({"p": pub[runner], "why": _reason(it, runner, info[runner], ctx)}
                           if pick and runner and runner in pub else None)
        it["balanced"] = bool(balanced)
        it["fallback"] = None
        if not pick:
            repo, path = it["_primary"] or ((ctx.docs_repo, it["_docs"]) if it["_docs"] else (None, None))
            hit = ctx.last_toucher(repo, path) if path else None
            # A commit too big to weigh still has an author: the newest evidence commit a person made.
            for e in it["evidence"] if not hit else []:
                k = ctx.pid_of_sha.get(e["sha"][:9])
                if k and not ctx.people[k]["hidden"]:
                    hit = (ctx.name(k), e["date"])
                    break
            it["fallback"] = (f"Last touched by {hit[0]} on {_fmt(hit[1])}" if hit
                              else "No one touched these files in the last year" if path else None)


# ----------------------------------------------------------------------------- the block

def build_next(board: dict, ctx, as_of: datetime | date, mom: dict | None = None, changelog_recent: bool = False) -> dict:
    """The board's `next` block. ctx is team.TeamCtx, or None when the team map is off: owners are then null."""
    day = as_of.date() if isinstance(as_of, datetime) else as_of
    items = rank(candidates(board, day, mom or {}, changelog_recent))
    if ctx is not None:
        for it in items:  # "docs" means wherever the docs live: their own repo, or the code repo
            if it["_primary"] and it["_primary"][0] == "docs":
                it["_primary"] = (ctx.docs_repo, it["_primary"][1])
        _owners(items, ctx)
        for it in items:
            # The area that holds most of the item's code files. The first file alone can sit in a side folder.
            votes = Counter(a for a in (ctx.area_of("code", f) for f in it["_files"]) if a)
            p = it.get("_primary")
            first = ctx.area_of(*p) if p else None
            it["area"] = max(sorted(votes), key=lambda a: (votes[a], a == first)) if votes else first
    out = []
    for it in items:
        row = {k: it.get(k) for k in ("rank", "kind", "title", "path", "area", "rationale", "why_now", "score", "parts",
                                      "effort", "effort_why", "judge", "action", "count", "evidence", "owner",
                                      "runner_up", "balanced", "fallback")}
        row["balanced"] = bool(row["balanced"])
        if row["rank"] > TOP:  # past the first 10, the drawer is rarely opened: three commits are enough
            row["evidence"] = row["evidence"][:3]
        out.append(row)
    block = {"v": 1, "top": TOP, "weights": dict(WEIGHTS), "items": out}
    # The board budget is 25 KB for this block. The lowest ranks past the first 10 go first.
    while len(out) > TOP and len(json.dumps(block, separators=(",", ":"), ensure_ascii=False)) > NEXT_BYTES:
        out.pop()
    return block
