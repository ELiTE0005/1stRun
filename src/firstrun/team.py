"""Who works on what: expertise per part of the code, from the public git history of the audited repo.

Weights count files changed, never lines, so a blobless clone stays blobless. Emails stay inside this module:
they merge one person's identities and find GitHub logins, and never reach a board, a span or a log.
Everything here fails closed. A failed GitHub lookup leaves logins out, and a failed team map leaves the board as it was.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import httpx

WINDOW_DAYS = 365
HALF_LIFE_DAYS = 90  # a planning quarter
MAX_FILES = 300  # a commit that touches more is a vendoring, a rename sweep or a format run
MASS_CAP = 4  # 1 + log2(files) capped: a 250-file refactor weighs four one-file commits, not 250
DEPTH = 6
DESCEND, SPLIT, MIN_SHARE = 0.85, 0.22, 0.03
AREAS_MAX = 10
AREAS_DUAL = {"code": 7, "docs": 3}
LIST_MAX, PEOPLE_MAX, AREAS_CAP, ITEMS_CAP = 12, 16, 12, 30
TEAM_BYTES = 9_800
ACTIVE_DAYS = QUIET_DAYS = 180
LOOKUP_MAX, LOOKUP_BATCH, LOOKUP_CALLS = 100, 50, 4
GRAPHQL = "https://api.github.com/graphql"

TEAM_SKIP = re.compile(
    r"(^|/)\.[^/]+/|(^|/)(node_modules|vendor|third_party|dist|build|out|target)/|"
    r"\.lock$|-lock\.json$|(^|[/-])lock\.ya?ml$|go\.sum$|\.snap$|"
    r"\.min\.(js|css)$|\.pb\.go$|_pb2\.py$|"
    r"(^|/)(changelog|changes|history)(\.[a-z]+)?$", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LOGIN = re.compile(r"^[A-Za-z0-9-]{1,39}$")
_NOREPLY_ID = re.compile(r"^(\d+)\+([^@]+)@users\.noreply\.github\.com$", re.I)
_NOREPLY = re.compile(r"^([^@+]+)@users\.noreply\.github\.com$", re.I)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
BOT_NAMES = {"github-actions", "dependabot", "renovate", "copilot", "copilot-swe-agent", "pre-commit-ci", "greenkeeper",
             "codecov", "mergify", "semantic-release-bot", "allcontributors", "claude", "devin-ai-integration",
             "cursoragent", "codex", "web-flow"}
_BOT_ROLE = re.compile(r"(^|[-_])(assistant|automation)$", re.I)
GENERIC_NAMES = {"root", "admin", "ubuntu", "user", "unknown", "github", "dev"}
GENERIC_DIRS = {"src", "lib", "app", "core", "internal", "pkg", "main", "source", "packages", "crates", "docs", "content"}


# ----------------------------------------------------------------------------- identities

def noreply(email: str) -> tuple[int | None, str | None]:
    """(GitHub user id, login) from a GitHub noreply address. (None, None) for any other email."""
    e = (email or "").strip()
    m = _NOREPLY_ID.match(e)
    if m:
        return int(m.group(1)), m.group(2)
    m = _NOREPLY.match(e)
    return (None, m.group(1)) if m else (None, None)


def _ends_bot(word: str) -> bool:
    """'snyk-bot', 'FishtownBuildBot', 'x[bot]'. Not 'Talbot' or 'abbot': the suffix needs a separator or a capital B."""
    w = word.strip()
    return w.lower() == "bot" or w.lower().endswith("[bot]") \
        or bool(re.search(r"[-_.]bot$", w, re.I)) or bool(re.search(r"[a-z0-9]Bot$", w))


def is_bot(name: str, email: str = "", login: str | None = None, extra: frozenset | set = frozenset()) -> bool:
    name, email, login = (name or "").strip(), (email or "").strip().lower(), (login or "").strip()
    nr_login = noreply(email)[1] or ""
    # A spaced name ("Sam Talbot") is a person's name, so only a one-word name is read like a login.
    words = [w for w in (login, nr_login, email.split("@", 1)[0], "" if " " in name else name) if w]
    if name.lower().endswith("[bot]") or any(_ends_bot(w) for w in words):
        return True
    low = {name.lower(), login.lower(), nr_login.lower()} - {""}
    if low & BOT_NAMES or low & {x.lower() for x in extra}:
        return True
    if email in ("noreply@github.com", "actions@github.com") or (email.endswith("@anthropic.com") and name.lower() == "claude"):
        return True
    return any(_BOT_ROLE.search(w) for w in (login, nr_login, "" if " " in name else name) if w)


def norm_name(name: str) -> str:
    """NFKD, accents stripped, casefolded, punctuation removed, whitespace collapsed."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).casefold()
    s = re.sub(r"[^\w\s]|_", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def optout_hash(value: str) -> str:
    """The entry for docs/audits/team-optout.json: sha256 of the lowercase login or the normalized name."""
    return "sha256:" + hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.logins: dict[str, set[str]] = {}

    def add(self, k: str, login: str | None) -> None:
        if k not in self.parent:
            self.parent[k] = k
            self.logins[k] = set()
        if login:
            self.logins[self.find(k)].add(login.lower())

    def find(self, k: str) -> str:
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k

    def union(self, a: str, b: str, strict: bool) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        la, lb = self.logins[ra], self.logins[rb]
        if strict and la and lb and la != lb:  # two different known GitHub accounts are two people
            return
        self.parent[rb] = ra
        self.logins[ra] |= lb


# ----------------------------------------------------------------------------- GitHub lookup

_MEMO: dict[tuple[str, str], tuple[str, int] | None] = {}


def _token() -> str:
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t.strip()
    try:
        p = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:  # noqa: BLE001 - no gh, no token
        return ""


def _lookup(slug: str, wanted: dict[str, str], token: str) -> dict[str, tuple[str, int]]:
    owner, name = slug.split("/", 1)
    out: dict[str, tuple[str, int]] = {}
    todo = []
    for key, sha in list(wanted.items())[:LOOKUP_MAX]:
        if not _HEX40.match(sha):
            continue
        if (slug, sha) in _MEMO:
            if _MEMO[(slug, sha)]:
                out[key] = _MEMO[(slug, sha)]
        else:
            todo.append((key, sha))
    remaining = 1000
    for n, i in enumerate(range(0, len(todo), LOOKUP_BATCH)):
        if n >= LOOKUP_CALLS or remaining < 50:
            break
        batch = todo[i:i + LOOKUP_BATCH]
        fields = " ".join(f'c{j}: object(oid: "{sha}") {{ ... on Commit {{ author {{ user {{ login databaseId }} }} }} }}'
                          for j, (_, sha) in enumerate(batch))
        query = f"query {{ repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ {fields} }} }}"
        r = httpx.post(GRAPHQL, json={"query": query}, headers={"Authorization": f"bearer {token}"}, timeout=15)
        r.raise_for_status()
        remaining = int(r.headers.get("X-RateLimit-Remaining") or 1000)
        repo = ((r.json() or {}).get("data") or {}).get("repository")
        if repo is None:
            raise RuntimeError("GitHub returned no repository")
        for j, (key, sha) in enumerate(batch):
            user = ((repo.get(f"c{j}") or {}).get("author") or {}).get("user") or {}
            login, uid = user.get("login"), user.get("databaseId")
            val = (login, uid) if isinstance(login, str) and LOGIN.match(login) and type(uid) is int else None
            _MEMO[(slug, sha)] = val
            if val:
                out[key] = val
    return out


def github_logins(slug: str, wanted: dict[str, str], token: str | None = None) -> dict[str, tuple[str, int]]:
    """{identity key: (login, user id)} for the newest commit of each identity, through the GraphQL API.
    At most 4 calls of 50. Returns {} on any failure, with no token, or when the rate limit runs low."""
    try:
        if not slug or "/" not in slug or not wanted:
            return {}
        token = token or _token()
        return _lookup(slug, wanted, token) if token else {}
    except Exception:  # noqa: BLE001 - the lookup is optional, and a failure must not half-apply
        return {}


# ----------------------------------------------------------------------------- opt-outs

def load_optout(path: Path | None) -> dict:
    """{"hidden": set of sha256 entries, "bots": set of lowercase names}. Empty when the file is missing or broken."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
        return {"hidden": {str(x) for x in doc.get("hidden") or []},
                "bots": {str(x).lower() for x in doc.get("bots") or []}}
    except Exception:  # noqa: BLE001
        return {"hidden": set(), "bots": set()}


def repo_optout(repo: Path, rev: str, paths: list[str] | set[str]) -> bool:
    """True when the audited repo says `team: false` in .github/firstrun.yml or .firstrun.yml at the audited commit."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    for name in (".github/firstrun.yml", ".firstrun.yml"):
        if name not in paths:
            continue
        try:
            # No `-c` here: a config override on the command line breaks the lazy blob fetch.
            p = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{name}"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=30, env=env)
        except Exception:  # noqa: BLE001
            continue
        if p.returncode == 0 and re.search(r"^\s*team:\s*false\b", p.stdout, re.M | re.I):
            return True
    return False


# ----------------------------------------------------------------------------- weights and areas

def _dirs(path: str) -> list[str]:
    """Ancestor folders of a file, shallowest first, with a trailing slash, at most DEPTH deep."""
    parts = path.split("/")[:-1][:DEPTH]
    return ["/".join(parts[:i]) + "/" for i in range(1, len(parts) + 1)]


def _parent(d: str) -> str:
    return d[:-1].rsplit("/", 1)[0] + "/" if "/" in d[:-1] else ""


def _frontier(file_w: dict[str, float], paths: list[str], max_areas: int) -> tuple[list[tuple[str, bool]], dict]:
    """Split the folder tree where the work splits. Returns ([(folder, is_other)], mapped folder per file)."""
    existing = {d for p in paths for d in _dirs(p)}
    mapped: dict[str, str] = {}
    for f in file_w:
        ds = _dirs(f)
        d = ds[-1] if ds else ""
        while d and d not in existing:
            d = _parent(d)
        mapped[f] = d
    W: dict[str, float] = defaultdict(float)
    kids: dict[str, set[str]] = defaultdict(set)
    for f, w in file_w.items():
        d = mapped[f]
        W[""] += w
        chain = _dirs(d + "x") if d else []
        for i, a in enumerate(chain):
            W[a] += w
            kids[chain[i - 1] if i else ""].add(a)
    T = W[""]
    if T <= 0:
        return [], mapped

    def descend(n: str) -> str:
        while True:
            big = [c for c in kids[n] if W[c] >= DESCEND * W[n]]
            if not big:
                return n
            n = big[0]

    def big_kids(n: str) -> list[str]:
        return sorted((c for c in kids[n] if W[c] >= MIN_SHARE * T), key=lambda c: (-W[c], c))

    def splits(n: str) -> bool:
        # Two big subfolders, or one big subfolder beside a big remainder (files in n itself, or a deleted folder).
        big = big_kids(n)
        return len(big) >= 2 or (len(big) == 1 and W[n] - W[big[0]] >= MIN_SHARE * T)

    nodes = [(descend(c), False) for c in big_kids("")]
    weight = {n: W[n[0]] for n in nodes}
    while len(nodes) < max_areas:
        cands = [n for n in nodes if not n[1] and weight[n] >= SPLIT * T and splits(n[0])]
        if not cands:
            break
        n = max(cands, key=lambda x: (weight[x], x[0]))
        nodes.remove(n)
        big = big_kids(n[0])
        for c in big:
            node = (descend(c), False)
            nodes.append(node)
            weight[node] = W[node[0]]
        rem = W[n[0]] - sum(W[c] for c in big)
        if rem >= MIN_SHARE * T:
            nodes.append((n[0], True))
            weight[(n[0], True)] = rem
    nodes.sort(key=lambda x: (-weight[x], x[0]))
    return nodes[:max_areas], mapped


def _label(path: str, other: bool) -> str:
    parts = [p for p in path.split("/") if p]
    base = parts[-1] if parts else path
    if base.lower() in GENERIC_DIRS and len(parts) > 1:
        base = f"{parts[-2]}/{base}"
    return base + (" (other)" if other else "")


def _decay(as_of: datetime, when: datetime, half_life: float = HALF_LIFE_DAYS) -> float:
    return 2 ** (-max(0, (as_of - when).days) / half_life)


def _mass(n: int) -> float:
    return min(1 + math.log2(n), MASS_CAP) if n else 0.0


def _ini(name: str, login: str | None) -> str:
    toks = re.findall(r"[^\W\d_]+", name or "")
    if toks:
        return "".join(t[0] for t in toks[:2]).upper()
    return (login or "?")[:2].upper()


# ----------------------------------------------------------------------------- the context nextup reads

class TeamCtx:
    """What nextup needs to suggest owners. Internal only: it holds person keys, never serialized."""

    def __init__(self, as_of: datetime) -> None:
        self.as_of = as_of
        self.window_days = WINDOW_DAYS
        self.idle = 0
        self.people: dict[str, dict] = {}  # key -> name, login, gh, last, hidden, weight, commits
        self.pid_of_sha: dict[str, str] = {}
        self.files_of_sha: dict[str, list[str]] = {}
        self.w: dict[str, dict[tuple[str, str], float]] = defaultdict(lambda: defaultdict(float))
        self.dw: dict[str, dict[tuple[str, str], float]] = defaultdict(lambda: defaultdict(float))
        # Weight of the files that sit directly in a folder, without its subfolders: the package itself.
        self.dd: dict[str, dict[tuple[str, str], float]] = defaultdict(lambda: defaultdict(float))
        self.recent_by_dir: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        self.dir_commits: Counter = Counter()
        self.file_last: dict[tuple[str, str], tuple[str, str]] = {}
        self.file_commits: Counter = Counter()  # (repo, file) and (key, repo, file) -> window commits
        self.areas: list[dict] = []  # id, repo, path, other
        self.docs_repo = "code"
        self.release_tagger: str | None = None
        self.release_shas: list[str] = []
        self.team: dict = {}
        self._render = None

    def active(self, key: str) -> bool:
        p = self.people.get(key)
        return bool(p) and not p["hidden"] and p["last"] is not None and (self.as_of - p["last"]).days <= ACTIVE_DAYS

    def name(self, key: str) -> str:
        return self.people[key]["name"]

    def last_toucher(self, repo: str, path: str) -> tuple[str, str] | None:
        """(name, YYYY-MM-DD) of the last human in the window who touched the file or its nearest folder."""
        hit = self.file_last.get((repo, path))
        if hit and not self.people[hit[0]]["hidden"]:
            return self.name(hit[0]), hit[1]
        for d in reversed(_dirs(path)):
            for key, day in self.recent_by_dir.get((repo, d), []):
                if not self.people[key]["hidden"]:
                    return self.name(key), day
        return None

    def area_of(self, repo: str, path: str) -> str | None:
        """The area id whose folder is the longest prefix of the path."""
        best, size = None, -1
        for a in self.areas:
            if a["repo"] == repo and path.startswith(a["path"]) and len(a["path"]) > size:
                best, size = a["id"], len(a["path"])
        return best

    def finish(self, keys: list[str]) -> dict[str, str]:
        """List the suggested owners on the map too (up to 16 people), renumber, and return key -> public id."""
        return self._render(keys) if self._render else {}


# ----------------------------------------------------------------------------- build

def build_team(sources: list[dict], as_of: datetime, hidden: set | frozenset = frozenset(),
               extra_bots: set | frozenset = frozenset(), token: str | None = None, github: bool = True,
               release: dict | None = None, window_days: int = WINDOW_DAYS,
               half_life: float = HALF_LIFE_DAYS) -> tuple[dict, TeamCtx]:
    """sources: [{"repo": "code" or "docs", "commits": read_history(), "paths": ls-tree at the audited commit,
    "slug": "owner/name" or ""}]. release: {"tagger": name, "shas": [...]} of the newest release.
    Returns (the board's team block, the context nextup reads)."""
    start = as_of - timedelta(days=window_days)
    ctx = TeamCtx(as_of)
    ctx.window_days = window_days
    ctx.docs_repo = "docs" if any(s["repo"] == "docs" for s in sources) else "code"
    for s in sources:
        for c in s["commits"]:
            ctx.files_of_sha.setdefault(c["sha"][:9], c["files"])

    # B2: which commits count. A history cut by HISTORY_MAX that ends inside the window under-counts it.
    from firstrun.audit import HISTORY_MAX

    capped = any(len(s["commits"]) >= HISTORY_MAX and s["commits"][-1]["date"] > start for s in sources)
    rows, bots = [], 0
    for s in sources:
        for c in s["commits"]:
            when = c.get("adate") or c["date"]
            if c.get("parents", 1) > 1 or when < start:
                continue
            if is_bot(c["author"], c.get("email", ""), extra=extra_bots):
                bots += 1
                continue
            # A commit over MAX_FILES, or one that only touches lock files and the like, weighs nothing. It still
            # says who wrote it, so a document item can name its author.
            files = [f for f in c["files"] if not TEAM_SKIP.search(f)] if len(c["files"]) <= MAX_FILES else []
            rows.append({"repo": s["repo"], "slug": s.get("slug", ""), "c": c, "when": when, "files": files,
                         "key": (c.get("email") or "").strip().lower() or "name:" + norm_name(c["author"])})

    # B4: identities. One key per email; GitHub fills in logins the noreply address does not carry.
    ids: dict[str, dict] = {}
    for r in rows:
        i = ids.setdefault(r["key"], {"names": Counter(), "login": None, "gh": None, "weight": 0.0, "newest": {}})
        i["names"][r["c"]["author"]] += 1
        i["weight"] += _decay(as_of, r["when"], half_life) * _mass(len(r["files"]))
        if r["slug"] and r["slug"] not in i["newest"]:
            i["newest"][r["slug"]] = r["c"]["sha"]  # rows run newest first
        if not i["login"]:
            gh, login = noreply(r["c"].get("email", ""))
            if login and LOGIN.match(login):
                i["login"], i["gh"] = login, gh
    found_any = False
    if github:
        for slug in {r["slug"] for r in rows if r["slug"]}:
            need = sorted((k for k, i in ids.items() if not i["login"] and slug in i["newest"]),
                          key=lambda k: -ids[k]["weight"])[:LOOKUP_MAX]
            try:
                got = github_logins(slug, {k: ids[k]["newest"][slug] for k in need}, token)
            except Exception:  # noqa: BLE001 - belt and braces: the lookup already fails closed
                got = {}
            for k, (login, uid) in got.items():
                if not ids[k]["login"]:
                    ids[k]["login"], ids[k]["gh"] = login, uid
                    found_any = True
    # A login can unmask a bot whose git name looked human.
    late_bots = {k for k, i in ids.items() if i["login"] and is_bot("", "", i["login"], extra_bots)}
    if late_bots:
        bots += sum(1 for r in rows if r["key"] in late_bots)
        rows = [r for r in rows if r["key"] not in late_bots]
        for k in late_bots:
            ids.pop(k)

    uf = _Union()
    for k, i in ids.items():
        uf.add(k, i["login"])
    by_login: dict[str, str] = {}
    for k, i in ids.items():
        if i["login"]:
            first = by_login.setdefault(i["login"].lower(), k)
            uf.union(first, k, strict=False)
    by_name: dict[str, str] = {}
    for k, i in ids.items():
        for n in i["names"]:
            nn = norm_name(n)
            if not nn or nn in GENERIC_NAMES or "@" in n:
                continue
            first = by_name.setdefault(nn, k)
            uf.union(first, k, strict=True)

    members: dict[str, list[str]] = defaultdict(list)
    for k in ids:
        members[uf.find(k)].append(k)
    for n, (root, ks) in enumerate(sorted(members.items(), key=lambda kv: -sum(ids[k]["weight"] for k in kv[1])), 1):
        names = Counter()
        login = gh = None
        for k in ks:
            names.update(ids[k]["names"])
            login = login or ids[k]["login"]
            gh = gh if gh is not None else ids[k]["gh"]
        good = [x for x, _ in names.most_common() if "@" not in x and x.strip()]
        name = good[0] if good else (login or f"Contributor {n}")
        marks = {optout_hash(login)} if login else set()
        marks |= {optout_hash(norm_name(x)) for x in names}
        ctx.people[root] = {"name": name[:80], "login": login, "gh": gh, "last": None, "weight": 0.0, "commits": 0,
                            "hidden": bool(marks & set(hidden)), "ini": _ini(name, login)}
    key_of = {k: uf.find(k) for k in ids}

    # B5: weights. Each kept file gets an equal share of the commit's decayed, log-capped mass.
    file_w: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))  # repo -> file -> weight
    for r in rows:
        pk = key_of[r["key"]]
        ctx.pid_of_sha[r["c"]["sha"][:9]] = pk
        if not r["files"]:
            continue
        p = ctx.people[pk]
        day = r["when"].date().isoformat()
        each = _decay(as_of, r["when"], half_life) * _mass(len(r["files"])) / len(r["files"])
        p["weight"] += each * len(r["files"])
        p["commits"] += 1
        p["last"] = r["when"] if p["last"] is None or r["when"] > p["last"] else p["last"]
        seen_dirs = set()
        for f in r["files"]:
            ctx.w[pk][(r["repo"], f)] += each
            file_w[r["repo"]][f] += each
            ctx.file_last.setdefault((r["repo"], f), (pk, day))
            ctx.file_commits[(r["repo"], f)] += 1
            ctx.file_commits[(pk, r["repo"], f)] += 1
            ds = _dirs(f)
            for d in ds:
                ctx.dw[pk][(r["repo"], d)] += each
                seen_dirs.add(d)
            if ds:
                ctx.dd[pk][(r["repo"], ds[-1])] += each
        for d in seen_dirs:
            ctx.dir_commits[(r["repo"], d)] += 1
            if len(ctx.recent_by_dir[(r["repo"], d)]) < 20:
                ctx.recent_by_dir[(r["repo"], d)].append((pk, day))

    # B6: areas, per repo when the docs live in their own repo.
    areas: list[dict] = []
    file_area: dict[tuple[str, str], int] = {}
    for s in sources:
        fw = file_w.get(s["repo"], {})
        cap = AREAS_DUAL.get(s["repo"], AREAS_MAX) if len(sources) > 1 else AREAS_MAX
        nodes, mapped = _frontier(fw, s.get("paths") or [], cap)
        start_i = len(areas)
        for path, other in nodes:
            areas.append({"repo": s["repo"], "path": path, "other": other, "label": _label(path, other)})
        for f in fw:
            d = mapped[f]
            best, size = None, -1
            for i in range(start_i, len(areas)):
                a = areas[i]
                if d and d.startswith(a["path"]) and len(a["path"]) > size:
                    best, size = i, len(a["path"])
            if best is not None:
                file_area[(s["repo"], f)] = best
    # Two areas with one name read as one: give both their parent folder.
    for lab, n in Counter(a["label"] for a in areas).items():
        if n > 1:
            for a in areas:
                if a["label"] == lab:
                    parts = [p for p in a["path"].split("/") if p]
                    a["label"] = "/".join(parts[-2:]) + (" (other)" if a["other"] else "") if len(parts) > 1 else lab
    for lab, n in Counter(a["label"] for a in areas).items():
        if n > 1:
            for a in areas:
                if a["label"] == lab and a["repo"] == "docs":
                    a["label"] = f"{lab} (docs repo)"

    # B7: metrics.
    T = {repo: sum(fw.values()) for repo, fw in file_w.items()}
    T_all = sum(T.values()) or 1.0
    aw = [0.0] * len(areas)
    pa: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(areas))
    rest_w = 0.0
    for pk, files in ctx.w.items():
        for key, w in files.items():
            i = file_area.get(key)
            if i is None:
                rest_w += w
            else:
                aw[i] += w
                pa[pk][i] += w
    a_commits, a_last = [set() for _ in areas], [None] * len(areas)
    rest_commits = set()
    for n, r in enumerate(rows):
        for f in r["files"]:
            i = file_area.get((r["repo"], f))
            if i is None:
                rest_commits.add(n)
            else:
                a_commits[i].add(n)
                a_last[i] = r["when"] if a_last[i] is None or r["when"] > a_last[i] else a_last[i]

    ranked = sorted((k for k in ctx.people if ctx.people[k]["commits"]), key=lambda k: (-ctx.people[k]["weight"], k))
    for k in ranked:
        ctx.people[k]["last"] = ctx.people[k]["last"] or as_of
    ctx.areas = [{"id": f"a{i + 1}", "repo": a["repo"], "path": a["path"], "other": a["other"]} for i, a in enumerate(areas)]
    for i, a in enumerate(areas):
        a["id"] = f"a{i + 1}"

    def render(extra: list[str]) -> dict[str, str]:
        listed = [k for k in ranked if not ctx.people[k]["hidden"]
                  and (ctx.people[k]["weight"] / T_all >= 0.015 or ctx.people[k]["commits"] >= 3)][:LIST_MAX]
        for k in extra:
            if len(listed) >= PEOPLE_MAX:
                break
            if k in ctx.people and k not in listed and not ctx.people[k]["hidden"] and ctx.people[k]["commits"]:
                listed.append(k)
        listed.sort(key=lambda k: (-ctx.people[k]["weight"], k))
        pub = {k: f"p{n + 1}" for n, k in enumerate(listed)}
        others = [k for k in ranked if k not in pub]
        people = []
        for k in listed:
            p = ctx.people[k]
            row = pa.get(k) or [0.0] * len(areas)
            top = max(range(len(areas)), key=lambda i: row[i]) if areas and max(row) > 0 else None
            people.append({"id": pub[k], "name": p["name"], "login": p["login"], "gh": p["gh"], "ini": p["ini"],
                           "commits": p["commits"], "share": round(p["weight"] / T_all, 3),
                           "last": p["last"].date().isoformat(), "top": areas[top]["id"] if top is not None else None,
                           "top_share": round(row[top] / p["weight"], 2) if top is not None and p["weight"] else 0})
        out_areas = []
        for i, a in enumerate(areas):
            W = aw[i] or 1e-12
            shares = sorted(((pa[k][i] / W, k) for k in ranked if pa.get(k) and pa[k][i] > 0), key=lambda x: (-x[0], x[1]))
            owners = [(s, pub[k]) for s, k in shares if k in pub]
            o_share = sum(s for s, k in shares if k not in pub)
            if o_share > 0:
                owners.append((o_share, "others"))
            owners = [{"p": p, "s": round(s, 2)} for s, p in sorted(owners, key=lambda x: -x[0]) if s >= 0.05][:3]
            cum, bus = 0.0, 0
            for s, _ in shares:
                cum += s
                bus += 1
                if cum >= 0.5 - 1e-9:
                    break
            sig = [s for s, _ in shares if s >= 0.05]
            last = a_last[i]
            out_areas.append({"id": a["id"], "label": a["label"], "path": a["path"], "repo": a["repo"],
                              "share": round(aw[i] / (T.get(a["repo"]) or 1.0), 3), "commits": len(a_commits[i]),
                              "last": last.date().isoformat() if last else None, "owners": owners, "bus": bus,
                              "single": bool(shares) and (shares[0][0] >= 0.75 or len(sig) == 1),
                              "quiet": bool(last) and (as_of - last).days > QUIET_DAYS})
        cells: list[list] = []
        for n, k in enumerate(listed):
            for i in range(len(areas)):
                v = round((pa.get(k) or [0.0] * len(areas))[i] / T_all * 100, 2)
                if v >= 0.01:
                    cells.append([n, i, v])
        for i in range(len(areas)):
            v = round(sum(pa[k][i] for k in others if pa.get(k)) / T_all * 100, 2)
            if v >= 0.01:
                cells.append([-1, i, v])
        o_commits = sum(ctx.people[k]["commits"] for k in others)
        ctx.team.clear()
        ctx.team.update({
            "v": 1, "as_of": as_of.date().isoformat(), "window_days": window_days, "half_life_days": round(half_life),
            "source": "git+github" if found_any else "git", "commits": sum(1 for r in rows if r["files"]),
            "bots_skipped": bots,
            "total_people": len(ranked), "capped": capped,
            "people": people,
            "others": {"people": len(others), "commits": o_commits,
                       "share": round(sum(ctx.people[k]["weight"] for k in others) / T_all, 3)} if others else None,
            "areas": out_areas,
            "rest": {"share": round(rest_w / T_all, 3), "commits": len(rest_commits)},
            "cells": cells,
        })
        if ctx.idle:
            ctx.team["idle_days"] = ctx.idle
        # The board budget is 10 KB for the map. The thinnest ribbons go first, the people and areas never do.
        cells.sort(key=lambda c: -c[2])
        while cells and len(json.dumps(ctx.team, separators=(",", ":"), ensure_ascii=False)) > TEAM_BYTES:
            cells.pop()
        cells.sort(key=lambda c: (c[0] < 0, c[0], c[1]))
        return pub

    ctx._render = render
    render([])
    if release:
        ctx.release_shas = [s[:9] for s in release.get("shas") or []]
        tagger = norm_name(release.get("tagger") or "")
        if tagger and not is_bot(release.get("tagger") or "", extra=extra_bots):
            for k in ranked:
                if any(norm_name(n) == tagger for k2 in members.get(k, []) for n in ids[k2]["names"]):
                    ctx.release_tagger = k
                    break
    return ctx.team, ctx


# ----------------------------------------------------------------------------- the audit hook

def slug_of(repo: Path) -> str:
    """owner/name of a GitHub clone, or '' for anything else."""
    try:
        p = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=10)
        m = re.match(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", p.stdout.strip())
        return f"{m.group(1)}/{m.group(2)}" if m else ""
    except Exception:  # noqa: BLE001
        return ""


def ls_paths(repo: Path, rev: str) -> list[str]:
    p = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(repo), "ls-tree", "-r", "--name-only", rev],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    return p.stdout.splitlines() if p.returncode == 0 else []


def collect(code: dict, as_of: datetime, docs: dict | None = None, release: dict | None = None, enabled: bool = True,
            github: bool = True, optout: dict | None = None) -> tuple[dict, TeamCtx | None]:
    """The team block for an audit, with every opt-out applied. code and docs: {"repo": Path, "rev": str, "commits": [...]}.
    Returns ({"v": 1, "disabled": why}, None) when an opt-out applies."""
    if not enabled:
        return {"v": 1, "disabled": "flag"}, None
    if os.environ.get("FIRSTRUN_TEAM", "").strip() == "0":
        return {"v": 1, "disabled": "env"}, None
    # A repo with no commit in the window would map nobody. Anchor on its last commit, so the map shows who built it.
    newest = [s["commits"][0]["date"] for s in (code, docs) if s and s["commits"]]
    idle = (as_of - max(newest)).days if newest else 0
    window = WINDOW_DAYS
    if idle > WINDOW_DAYS:
        as_of = max(newest)
        oldest = min(s["commits"][-1]["date"] for s in (code, docs) if s and s["commits"])
        window = max(WINDOW_DAYS, (as_of - oldest).days + 1)  # no activity in a year: map the whole life of the repo
    else:
        idle = 0
    sources = []
    for label, src in (("code", code), ("docs", docs)):
        if not src:
            continue
        paths = ls_paths(src["repo"], src["rev"])
        if repo_optout(src["repo"], src["rev"], set(paths)):
            return {"v": 1, "disabled": "repo"}, None
        sources.append({"repo": label, "commits": src["commits"], "paths": paths, "slug": slug_of(src["repo"])})
    if optout is None:
        from firstrun.audit import find_audit_site

        site = find_audit_site()
        optout = load_optout(site / "team-optout.json" if site else None)
    team, ctx = build_team(sources, as_of, hidden=optout.get("hidden") or set(), extra_bots=optout.get("bots") or set(),
                           github=github, release=release, window_days=window,
                           half_life=max(HALF_LIFE_DAYS, window / 2) if idle else HALF_LIFE_DAYS)
    ctx.idle = idle
    if idle:
        team["idle_days"] = idle
    return team, ctx


def counts(team: dict | None, nxt: dict | None = None) -> dict:
    """What a trace span may hold about the team map: numbers only, never a name."""
    t = team or {}
    out = {"disabled": t.get("disabled", ""), "people": len(t.get("people") or []), "total_people": t.get("total_people", 0),
           "areas": len(t.get("areas") or []), "commits": t.get("commits", 0), "bots_skipped": t.get("bots_skipped", 0),
           "source": t.get("source", ""), "single_owner_areas": sum(1 for a in t.get("areas") or [] if a.get("single"))}
    if nxt is not None:
        items = nxt.get("items") or []
        out.update(next_items=len(items), with_owner=sum(1 for i in items if i.get("owner")))
    return out


# ----------------------------------------------------------------------------- publishing rules

_TEAM_KEYS = {"v", "as_of", "window_days", "half_life_days", "source", "commits", "bots_skipped", "total_people", "capped",
              "people", "others", "areas", "rest", "cells", "disabled", "idle_days"}
_PERSON_KEYS = {"id", "name", "login", "gh", "ini", "commits", "share", "last", "top", "top_share"}
_AREA_KEYS = {"id", "label", "path", "repo", "share", "commits", "last", "owners", "bus", "single", "quiet"}
_ITEM_KEYS = {"rank", "kind", "title", "path", "area", "rationale", "why_now", "score", "parts", "effort", "effort_why",
              "judge", "action", "count", "evidence", "owner", "runner_up", "balanced", "fallback"}


def _scrub(x):
    """Every string with an email in it loses the email."""
    if isinstance(x, str):
        return EMAIL.sub("", x).strip() if EMAIL.search(x) else x
    if isinstance(x, list):
        return [_scrub(v) for v in x]
    if isinstance(x, dict):
        return {k: _scrub(v) for k, v in x.items()}
    return x


def _num(x, default=0):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else default


def _clean_team(t: dict) -> dict | None:
    if t.get("disabled"):
        return {"v": 1, "disabled": t["disabled"] if t["disabled"] in ("flag", "env", "repo") else "flag"}
    t = {k: v for k, v in _scrub(t).items() if k in _TEAM_KEYS}
    people = []
    for p in (t.get("people") if isinstance(t.get("people"), list) else [])[:PEOPLE_MAX]:
        if not isinstance(p, dict) or not re.fullmatch(r"p\d{1,3}", str(p.get("id", ""))):
            continue
        p = {k: v for k, v in p.items() if k in _PERSON_KEYS}
        p["name"] = str(p.get("name") or "Contributor")[:80] or "Contributor"
        p["login"] = p["login"] if isinstance(p.get("login"), str) and LOGIN.match(p["login"]) else None
        p["gh"] = p["gh"] if type(p.get("gh")) is int and p["gh"] > 0 else None
        p["ini"] = str(p.get("ini") or "")[:3]
        people.append(p)
    areas = []
    for a in (t.get("areas") if isinstance(t.get("areas"), list) else [])[:AREAS_CAP]:
        if not isinstance(a, dict) or not re.fullmatch(r"a\d{1,3}", str(a.get("id", ""))):
            continue
        a = {k: v for k, v in a.items() if k in _AREA_KEYS}
        ids = {p["id"] for p in people} | {"others"}
        a["owners"] = [o for o in (a.get("owners") or []) if isinstance(o, dict) and o.get("p") in ids][:3]
        areas.append(a)
    cells = []
    for c in t.get("cells") if isinstance(t.get("cells"), list) else []:
        if (isinstance(c, list) and len(c) == 3 and type(c[0]) is int and type(c[1]) is int
                and -1 <= c[0] < len(people) and 0 <= c[1] < len(areas)):
            cells.append([c[0], c[1], _num(c[2])])
    t.update(people=people, areas=areas, cells=cells)
    return t


def sanitize(doc: dict) -> dict:
    """Run on every board before it is published or accepted: no email anywhere in team or next, logins that GitHub
    allows, integer user ids, bounded lists, and owners who are on the map. Changes nothing on an old board."""
    if "team" in doc:
        t = doc["team"]
        t = _clean_team(t) if isinstance(t, dict) else None
        if t is None:
            doc.pop("team")
        else:
            doc["team"] = t
    if "next" in doc:
        n = doc["next"]
        if not isinstance(n, dict):
            doc.pop("next")
        else:
            n = _scrub(n)
            ids = {p["id"] for p in (doc.get("team") or {}).get("people") or []}
            items = []
            for it in (n.get("items") if isinstance(n.get("items"), list) else [])[:ITEMS_CAP]:
                if not isinstance(it, dict):
                    continue
                it = {k: v for k, v in it.items() if k in _ITEM_KEYS}
                for k in ("owner", "runner_up"):
                    o = it.get(k)
                    it[k] = {"p": o["p"], "why": str(o.get("why") or "")} if isinstance(o, dict) and o.get("p") in ids else None
                it["evidence"] = [e for e in (it.get("evidence") or [])
                                  if isinstance(e, dict) and re.fullmatch(r"[0-9a-f]{7,40}", str(e.get("sha", "")))][:5]
                items.append(it)
            n["items"] = items
            doc["next"] = n
    return doc


def strip_people(doc: dict) -> dict:
    """A copy without the team map and without suggested owners, for an audit that leaves the machine."""
    out = dict(doc)
    out.pop("team", None)
    if isinstance(out.get("next"), dict):
        out["next"] = dict(out["next"], items=[dict(it, owner=None, runner_up=None, fallback=None, balanced=False)
                                                for it in out["next"].get("items") or []])
    return out
