"""A receipt for one run: the work, its price, the tier caps, the proof it passed, and file hashes.

`firstrun receipt` reads runs/<id>/state.json and business/unit_economics.json, so the price and the
caps on a receipt are the same numbers cfo.ai models. The receipt hash and the evidence hashes let
`firstrun receipt --check` detect an edited receipt or an edited run folder.
"""

from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path

from firstrun import report
from firstrun.models import Runbook, RunState, RunStatus, StepStatus

EVIDENCE = ("state.json", "runbook.json", "report.md")
UNHASHED = ("hash", "issued_at")


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def body_hash(receipt: dict) -> str:
    body = {k: v for k, v in receipt.items() if k not in UNHASHED}
    return _sha(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _caps(cost: float, tiers: dict, compute: float, bills: str | None) -> list[dict]:
    rows = []
    for name, t in tiers.items():
        cap = float(t["cap_usd_per_run"])
        rev = t.get("revenue_per_run")
        rows.append({
            "tier": name,
            "bills_this_run": bool(bills) and name.lower() == bills.lower(),
            "cap_usd": cap,
            "used_pct": round(100 * cost / cap, 1) if cap > 0 else None,
            "within_cap": cost <= cap,
            "price_per_run_usd": rev,
            "margin_pct": round(100 * (1 - (cost + compute) / rev), 1) if rev else None,
        })
    return rows


def _proof(state: RunState, steps: int, passed: int) -> dict:
    ok = state.status == RunStatus.VERIFIED
    if ok:
        claim = "A second clean container ran the patched steps with no model calls, and every step passed."
    elif state.status == RunStatus.PASSED and not state.patches:
        claim = "Every step passed on the first run. No fix was needed, so no second run was made."
    else:
        claim = f"The run ended {state.status.value}. Nothing here is verified."
    return {"status": state.status.value, "verified": ok, "steps_passed": passed, "steps_total": steps, "claim": claim}


def build(state: RunState, run_dir: Path, econ: dict, bills: str | None = None, cfo_url: str = "",
          steps_total: int | None = None) -> dict:
    cost = round(state.usage.cost_usd, 4)
    compute = float(econ["drivers"]["compute_per_run"])
    passed = sum(1 for s in state.step_status.values() if s == StepStatus.PASSED)
    steps = steps_total if steps_total is not None else len(state.step_status)
    first = state.first_failed_step
    cls = state.classifications.get(first) if first is not None else None
    evidence = {n: _sha((run_dir / n).read_bytes()) for n in EVIDENCE if (run_dir / n).exists()}
    r = {
        "receipt_id": f"FR-{state.run_id}",
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "work": {
            "source_url": state.source_url,
            "run_id": state.run_id,
            "started_at": state.started_at,
            "finished_at": state.finished_at,
            "seconds": round(report._duration(state) or 0, 1),
            "first_failed_step": first,
            "failure_class": cls.top.value if cls else None,
            "classified_by": cls.source if cls else None,
            "patches": [{"step": p.step_id, "was": p.old_command, "now": p.new_command, "reason": p.reason}
                        for p in state.patches],
        },
        "price": {
            "model_cost_usd": cost,
            "input_tokens": state.usage.input_tokens,
            "output_tokens": state.usage.output_tokens,
            "tool_calls": state.usage.tool_calls,
            "compute_per_run_usd": compute,
            "basis": "list price, not billed",
        },
        "caps": _caps(cost, econ["tiers"], compute, bills),
        "proof": _proof(state, steps, passed),
        "audit": {
            "run_id": state.run_id,
            "tags": state.tags,
            "evidence_sha256": evidence,
            "caps_from": f"business/unit_economics.json, generated {econ.get('generated_at', 'unknown')}",
            "margin_floor": econ.get("margin_floor"),
            "cfo_model": cfo_url,
        },
    }
    r["hash"] = body_hash(r)
    return r


def check(receipt_path: Path) -> list[str]:
    """Problems found, empty when the receipt and the evidence files next to it are untouched."""
    r = json.loads(receipt_path.read_text(encoding="utf-8"))
    problems = []
    if r.get("hash") != body_hash(r):
        problems.append("the receipt was edited: its hash does not match its content")
    evidence = r.get("audit", {}).get("evidence_sha256") or {}
    base = receipt_path.parent
    if evidence and not any((base / n).exists() for n in evidence):
        # A published copy in docs/receipts: the evidence stays in the run folder.
        from firstrun import config

        item = r.get("audit", {}).get("run_id") or r.get("audit", {}).get("audit_id") or ""
        if item and (Path(config.RUNS_DIR) / item).is_dir():
            base = Path(config.RUNS_DIR) / item
    for name, want in evidence.items():
        f = base / name
        if not f.exists():
            problems.append(f"{name} is missing")
        elif _sha(f.read_bytes()) != want:
            problems.append(f"{name} changed after the receipt was issued")
    return problems


def _flat(text: str, width: int) -> str:
    """One line: backslash-newlines and newlines folded, long text cut."""
    flat = " ".join(text.replace("\\\n", " ").split())
    return flat if len(flat) <= width else flat[: width - 1].rstrip() + "..."


def _cell(text: str, width: int = 110) -> str:
    """A Markdown table cell: one line, pipes escaped."""
    return _flat(text, width).replace("|", "\\|")


def _usd(v: float | None, places: int = 4) -> str:
    return "n/a" if v is None else f"${v:.{places}f}"


def render_md(r: dict) -> str:
    w, p, pf, a = r["work"], r["price"], r["proof"], r["audit"]
    out = [f"# Receipt {r['receipt_id']}", "",
           f"Issued {r['issued_at']}. Hash `{r['hash']}`.", "",
           "## Work", "",
           f"- Source: {w['source_url']}",
           f"- Run: `{w['run_id']}`, {w['seconds']} s",
           f"- Steps passed: {pf['steps_passed']} of {pf['steps_total']}"]
    if w["first_failed_step"] is not None:
        out.append(f"- First failed step: {w['first_failed_step']}, classed {w['failure_class']} by {w['classified_by']}")
    if w["patches"]:
        out += ["", "| Step | Was | Now | Why |", "|---|---|---|---|"]
        out += [f"| {x['step']} | `{_cell(x['was'])}` | `{_cell(x['now'])}` | {_cell(x['reason'], 160)} |" for x in w["patches"]]
    out += ["", "## Price", "",
            f"Model cost {_usd(p['model_cost_usd'])} ({p['input_tokens']:,} tokens in, {p['output_tokens']:,} out, "
            f"{p['tool_calls']} tool calls), {p['basis']}. Compute adds {_usd(p['compute_per_run_usd'], 5)}.", "",
            "## Cap", "", "| Tier | Cap per run | Used | Within cap | Price per run | Margin on this run |",
            "|---|---|---|---|---|---|"]
    for c in r["caps"]:
        used = "n/a" if c["used_pct"] is None else f"{c['used_pct']}%"
        margin = "n/a" if c["margin_pct"] is None else f"{c['margin_pct']}%"
        name = c["tier"] + (" (bills this run)" if c["bills_this_run"] else "")
        out.append(f"| {name} | {_usd(c['cap_usd'], 5)} | {used} | {'yes' if c['within_cap'] else 'NO'} | "
                   f"{_usd(c['price_per_run_usd'], 5)} | {margin} |")
    out += ["", "## Proof", "", f"**{'Verified' if pf['verified'] else 'Not verified'}.** {pf['claim']}", "",
            "## Audit Trail", "", f"Caps and prices: {a['caps_from']}."]
    if a["cfo_model"]:
        out.append(f"cfo.ai model: {a['cfo_model']}")
    out += ["", "| File | SHA-256 |", "|---|---|"]
    out += [f"| {n} | `{h}` |" for n, h in a["evidence_sha256"].items()]
    out += ["", f"Check it: `firstrun receipt --check runs/{w['run_id']}/receipt.json`", ""]
    return "\n".join(out)


def write(run_dir: Path, receipt: dict, with_html: bool = False) -> list[Path]:
    md, page = (render_audit_md, render_audit_html) if receipt.get("kind") == "audit" else (render_md, render_html)
    out = [run_dir / "receipt.json", run_dir / "receipt.md"]
    out[0].write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out[1].write_text(md(receipt), encoding="utf-8")
    if with_html:
        out.append(run_dir / "receipt.html")
        out[-1].write_text(page(receipt), encoding="utf-8")
    return out


# ----------------------------------------------------------------------------- audit receipts

AUDIT_EVIDENCE = ("audit.json", "audit.md", "issue.md")


def build_audit(a: dict, audit_dir: Path | None) -> dict:
    """A receipt for one doc audit. An old audit carries no cost, and the receipt says so.

    `audit_dir` holds audit.json and audit.md for the evidence hashes. None when no run folder was kept."""
    from firstrun import audit as audit_mod

    s, h = a["summary"], a["history"]
    cost = a.get("cost")
    cards = a.get("cards", [])
    cited = sum(1 for c in cards if c.get("evidence"))
    kinds: dict[str, int] = {}
    for c in cards:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    evidence = ({n: _sha((audit_dir / n).read_bytes()) for n in AUDIT_EVIDENCE if (audit_dir / n).exists()}
                if audit_dir else {})
    r = {
        "kind": "audit",
        "receipt_id": f"FR-{a['id']}",
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "work": {
            "repo": a["repo"], "docs_repo": a.get("docs_repo", ""), "url": a.get("url", ""),
            "audited_at": a["generated_at"], "head": h.get("head", ""),
            "commits_read": h["commits"], "since": h["since"], "history_capped": h["capped"],
            "pages": s["pages"], "fresh": s["fresh"], "aging": s["aging"], "stale": s["stale"], "quiet": s["quiet"],
            "features": s["features"], "uncovered": s["uncovered"], "cards": kinds, "judged_by_jev": bool(a.get("jev")),
        },
        "price": {
            "recorded": cost is not None,
            "estimated": bool((cost or {}).get("estimated")),
            "jev_calls": (cost or {}).get("jev_calls"),
            "jev_input_tokens": (cost or {}).get("jev_input_tokens"),
            "usd": (cost or {}).get("jev_usd"),
            "basis": (cost or {}).get("basis", "This audit ran before cost tracking, so its cost was not recorded."),
        },
        "limits": {
            "dollar_cap_per_audit": None,
            "jev_stale_pages_max": audit_mod.JEV_STALE_MAX,
            "jev_commit_sorts_max": audit_mod.JEV_MAX,
            "jev_batch_size": audit_mod.JEV_BATCH,
            "history_commits_max": audit_mod.HISTORY_MAX,
            "note": "The plan sets no dollar cap per audit. Jev reads are limited by the counts below.",
        },
        "proof": {
            "cards": len(cards), "cards_citing_evidence": cited,
            "all_cited": bool(cards) and cited == len(cards),
            "claim": f"{cited} of {len(cards)} cards cite commits or pages you can open." + (
                f" The audit read the history up to commit {h['head'][:9]}." if h.get("head")
                else " This audit did not record the commit it read."),
        },
        "audit": {"audit_id": a["id"], "evidence_sha256": evidence, "generated_by": "firstrun audit"},
    }
    r["hash"] = body_hash(r)
    return r


def render_audit_md(r: dict) -> str:
    w, p, lim, pf, a = r["work"], r["price"], r["limits"], r["proof"], r["audit"]
    cost = (f"Jev cost {'(estimated) ' if p.get('estimated') else ''}{_usd(p['usd'], 6)} "
            f"({p['jev_calls']} calls, {p['jev_input_tokens']:,} input tokens). {p['basis']}"
            if p["recorded"] else p["basis"])
    out = [f"# Receipt {r['receipt_id']}", "",
           f"Issued {r['issued_at']}. Hash `{r['hash']}`.", "",
           "## Work", "",
           f"- Repo: {w['repo']}" + (f", docs in {w['docs_repo']}" if w["docs_repo"] else ""),
           f"- Read {w['commits_read']:,} commits since {w['since']}" + (", capped" if w["history_capped"] else "")
           + (f", up to `{w['head'][:9]}`" if w["head"] else ""),
           f"- Pages: {w['pages']}, {w['stale']} stale, {w['aging']} aging, {w['quiet']} quiet, {w['fresh']} fresh",
           f"- Features: {w['features']}, {w['uncovered']} with no docs",
           "- Cards: " + (", ".join(f"{n} {k}" for k, n in w["cards"].items()) or "none"),
           "", "## Price", "", cost, "",
           "## Limits", "", lim["note"], "",
           f"- Jev reads at most {lim['jev_stale_pages_max']} stale pages, sorts at most {lim['jev_commit_sorts_max']} commits, "
           f"and sends {lim['jev_batch_size']} per call.",
           f"- The audit reads at most {lim['history_commits_max']:,} commits.", "",
           "## Proof", "", f"**{pf['cards_citing_evidence']} of {pf['cards']} cards cited.** {pf['claim']}", "",
           "## Audit Trail", "", "| File | SHA-256 |", "|---|---|"]
    out += [f"| {n} | `{h}` |" for n, h in a["evidence_sha256"].items()]
    out += ["", f"Check it: `firstrun receipt --check runs/{a['audit_id']}/receipt.json`", ""]
    return "\n".join(out)


# ----------------------------------------------------------------------------- the bill (HTML)

def _g(d, *keys, default=None):
    """d[k1][k2]... or default when any level is missing."""
    for k in keys:
        if not isinstance(d, dict) or d.get(k) is None:
            return default
        d = d[k]
    return d


def money(v: float | None) -> str:
    """Bill amounts: 4 places, 6 when a nonzero amount is under a tenth of a cent."""
    if v is None:
        return "Not recorded"
    v = float(v)
    return f"${v:.6f}" if 0 < abs(v) < 0.001 else f"${v:.4f}"


def total_usd(r: dict) -> float | None:
    """The TOTAL line of a receipt. A run adds model usage and compute. An audit is its Jev cost, or None."""
    if r.get("kind") == "audit":
        usd = _g(r, "price", "usd")
        return None if usd is None or not _g(r, "price", "recorded", default=usd is not None) else float(usd)
    model = _g(r, "price", "model_cost_usd")
    if model is None:
        return None
    return round(round(float(model), 4) + round(float(_g(r, "price", "compute_per_run_usd", default=0)), 4), 4)


def _day(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return str(ts)
    return f"{d:%b} {d.day}, {d.year}"


def _short_url(u: str) -> str:
    return u.split("://", 1)[-1].rstrip("/") if u else ""


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:g}%"


_LOGO = ('<svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="frg" x1="0" y1="0" x2="0" y2="1">'
         '<stop offset="0" stop-color="#46A6FF"/><stop offset="1" stop-color="#0060DF"/></linearGradient></defs>'
         '<rect x="2" y="2" width="60" height="60" rx="15" fill="url(#frg)"/>'
         '<path d="M2 17C2 8.7 8.7 2 17 2h30c8.3 0 15 6.7 15 15v5C46 30 18 30 2 22z" fill="#fff" opacity=".24"/>'
         '<path d="M21 22l13 10-13 10" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
         '<rect x="38" y="39" width="12" height="5.5" rx="2.75" fill="#fff"/></svg>')

_GLYPH = {
    "ok": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    "part": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 4v16"/></svg>',
    "no": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17"/></svg>',
}


def _barcode(h: str) -> str:
    """A decorative barcode drawn from the receipt hash, so no two receipts look alike."""
    hexs = (h or "").split(":")[-1][:40] or "0" * 40
    x, bars = 0, []
    for ch in hexs:
        n = int(ch, 16)
        w = 1 + n % 3
        bars.append(f'<rect x="{x}" width="{w}" height="28"/>')
        x += w + 1 + (n // 8)
    return f'<svg class="bc" viewBox="0 0 {x} 28" preserveAspectRatio="none" aria-hidden="true">{"".join(bars)}</svg>'


_CSS = """
:root{
--desk:oklch(95.4% .006 255);--paper:oklch(99.5% .003 90);
--ink:oklch(22% .012 255);--ink2:oklch(36% .012 255);--mut:oklch(50% .012 255);--faint:oklch(68% .01 255);
--rule:oklch(88.5% .008 255);--rule2:oklch(93.5% .006 255);--sunk:oklch(97.4% .004 255);
--acc:oklch(53% .19 256);--acc-bg:oklch(95.6% .026 256);
--ok:oklch(47% .13 150);--ok-bg:oklch(96.2% .035 150);
--warn:oklch(48% .12 66);--warn-bg:oklch(96.2% .05 85);--warn-bar:oklch(76% .14 72);--warn-bar2:oklch(88% .08 80);
--mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
--sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--ease:cubic-bezier(.25,1,.5,1)}
*{box-sizing:border-box;margin:0;padding:0}
html{background:var(--desk);color:var(--ink);font:15px/1.5 var(--sans);-webkit-text-size-adjust:100%;-webkit-font-smoothing:antialiased}
body{background:var(--desk);padding:24px 16px 64px;min-height:100vh;overflow-x:hidden}
a{color:var(--acc);text-underline-offset:3px;text-decoration-thickness:1px}
:focus-visible{outline:2px solid var(--acc);outline-offset:3px;border-radius:4px}
.num,.amt,code,.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.top{max-width:600px;margin:0 auto 14px;display:flex;justify-content:space-between;align-items:center;gap:8px 16px;flex-wrap:wrap;font-size:14px}
.top a{color:var(--ink2)}
.top button{font:inherit;font-size:14px;color:var(--ink2);background:none;border:0;text-decoration:underline;text-underline-offset:3px;text-decoration-thickness:1px;cursor:pointer}
.sheet{max-width:600px;margin:0 auto;filter:drop-shadow(0 1px 1px oklch(30% .02 255/.07)) drop-shadow(0 16px 30px oklch(30% .03 255/.13))}
.paper{--z:14px;position:relative;background:var(--paper);padding:40px 40px 34px;
-webkit-mask:conic-gradient(from -45deg at bottom,#0000,#000 1deg 89deg,#0000 90deg) bottom/var(--z) 51% repeat-x,conic-gradient(from 135deg at top,#0000,#000 1deg 89deg,#0000 90deg) top/var(--z) 51% repeat-x;
mask:conic-gradient(from -45deg at bottom,#0000,#000 1deg 89deg,#0000 90deg) bottom/var(--z) 51% repeat-x,conic-gradient(from 135deg at top,#0000,#000 1deg 89deg,#0000 90deg) top/var(--z) 51% repeat-x}
.hd{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
.brand{display:flex;align-items:center;gap:9px;font-weight:650;font-size:16px;letter-spacing:-.01em}
.logo{width:30px;height:30px;flex:none}
.doc{text-align:right}
h1{font-size:30px;line-height:1;letter-spacing:-.03em;font-weight:700}
.kind{display:block;margin-top:6px;font-size:13px;color:var(--mut)}
.meta{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 18px;margin-top:28px;font-size:13.5px}
.meta dt{color:var(--mut)}
.meta dd{color:var(--ink);overflow-wrap:anywhere}
.for{margin-top:22px;padding:14px 16px;background:var(--sunk);border-radius:10px}
.for small{display:block;font-size:12px;color:var(--mut);margin-bottom:2px}
.for a,.for b{font-size:16px;font-weight:600;overflow-wrap:anywhere;color:var(--ink)}
.for a{text-decoration-color:var(--faint)}
.for a:hover{text-decoration-color:var(--ink)}
.for span{display:block;font-size:13px;color:var(--mut);margin-top:2px}
section{margin-top:30px}
h2{font-size:11.5px;font-weight:650;letter-spacing:.09em;text-transform:uppercase;color:var(--mut);padding-bottom:8px;border-bottom:1px solid var(--rule)}
.items{width:100%;border-collapse:collapse;font-size:14.5px}
.items th,.items td{text-align:left;padding:12px 0;border-bottom:1px dashed var(--rule);vertical-align:top}
.items thead th{font-size:11.5px;font-weight:650;letter-spacing:.09em;text-transform:uppercase;color:var(--mut);padding:0 0 8px;border-bottom:1px solid var(--rule)}
.items td b{font-weight:600}
.items td span{display:block;font-size:12.5px;color:var(--mut);margin-top:2px}
.items .amt{text-align:right;white-space:nowrap;padding-left:16px}
.items td.amt{font-size:14.5px}
.items .nr{font-family:var(--sans);color:var(--mut);font-size:13px}
.items tfoot th,.items tfoot td{border-bottom:0;border-top:2px solid var(--ink);padding-top:14px}
.items tfoot th{font-size:16px;font-weight:700}
.items tfoot td.amt{font-size:26px;font-weight:650;letter-spacing:-.02em;line-height:1.1}
.items tfoot td.amt.nr{font-size:17px;font-weight:600;color:var(--ink2)}
.basis{margin-top:8px;font-size:12.5px;color:var(--mut)}
.facts{display:flex;flex-wrap:wrap;gap:1px;background:var(--rule2);border:1px solid var(--rule2);border-radius:10px;overflow:hidden;margin-top:14px}
.facts div{flex:1 1 104px;background:var(--paper);padding:10px 12px}
.facts dt{font-size:12px;color:var(--mut)}
.facts dd{font-size:15px;font-weight:600;font-family:var(--mono);font-variant-numeric:tabular-nums}
.line{margin-top:12px;font-size:14px;color:var(--ink2)}
.fixes{list-style:none;margin-top:12px;display:grid;gap:10px}
.fixes li{font-size:14px;color:var(--ink2)}
.fixes b{color:var(--ink);font-weight:600;margin-right:4px}
details{margin-top:4px}
summary{cursor:pointer;color:var(--acc);font-size:13px;text-decoration:underline;text-underline-offset:3px;text-decoration-thickness:1px;width:max-content;max-width:100%}
.cmd{margin-top:6px;display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 10px;font-size:12.5px;background:var(--sunk);border-radius:8px;padding:10px 12px}
.cmd dt{color:var(--mut);font-family:var(--sans)}
.cmd dd{font-family:var(--mono);overflow-wrap:anywhere;white-space:pre-wrap;color:var(--ink)}
.caps{list-style:none;margin-top:14px;display:grid;gap:16px}
.cap-h{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;font-size:14.5px}
.cap-h b{font-weight:650}
.cap-h .cv{margin-left:auto;font-size:13px;color:var(--mut)}
.tag{font-size:11px;font-weight:650;letter-spacing:.05em;text-transform:uppercase;color:var(--acc);background:var(--acc-bg);border-radius:99px;padding:1px 8px}
.meter{position:relative;height:10px;margin-top:7px;border-radius:99px;background:var(--rule2);overflow:hidden}
.meter i{position:absolute;inset:0 auto 0 0;border-radius:99px;background:var(--acc);transform-origin:left center;animation:grow .9s var(--ease) both}
.over .meter i{background:repeating-linear-gradient(-45deg,var(--warn-bar) 0 5px,var(--warn-bar2) 5px 10px)}
.meter.lim i{background:var(--ink2)}
.cap-s{display:flex;justify-content:space-between;gap:4px 14px;flex-wrap:wrap;margin-top:5px;font-size:12.5px;color:var(--mut)}
.cap-s .st{color:var(--ink2);font-weight:500}
.over .cap-s .st{color:var(--warn);font-weight:650}
.over .cap-s .st::before{content:"\\25B2";font-size:9px;margin-right:5px;vertical-align:1px}
.note{margin-top:12px;font-size:12.5px;color:var(--mut)}
.proof{display:flex;align-items:center;gap:22px;margin-top:16px}
.proof p{flex:1;font-size:14.5px;color:var(--ink2)}
.stamp{flex:none;display:inline-flex;align-items:center;gap:8px;padding:9px 16px;border:2.5px solid currentColor;border-radius:10px;box-shadow:inset 0 0 0 2px var(--paper),inset 0 0 0 3.5px currentColor;font-weight:800;font-size:15px;letter-spacing:.12em;text-transform:uppercase;line-height:1.15;transform:rotate(-4deg);animation:stamp .5s var(--ease) .35s both;max-width:240px;text-align:center}
.stamp svg{width:20px;height:20px;flex:none;fill:none;stroke:currentColor;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}
.stamp.ok{color:var(--ok);background:var(--ok-bg)}
.stamp.part{color:var(--warn);background:var(--warn-bg)}
.stamp.no{color:var(--ink2);background:var(--sunk);border-style:dashed}
.perf{position:relative;margin:34px -40px 0;border-top:2px dashed var(--rule)}
.perf::before,.perf::after{content:"";position:absolute;top:-12px;width:22px;height:22px;border-radius:50%;background:var(--desk)}
.perf::before{left:-11px}.perf::after{right:-11px}
.stub{padding-top:24px;display:grid;gap:14px;font-size:12.5px;color:var(--mut)}
.stub .k{display:block;font-size:11.5px;font-weight:650;letter-spacing:.09em;text-transform:uppercase;color:var(--mut);margin-bottom:3px}
.stub code{font-size:12px;color:var(--ink2);overflow-wrap:anywhere;word-break:break-all}
.ev{list-style:none;display:grid;gap:3px}
.ev li{display:grid;grid-template-columns:96px minmax(0,1fr);gap:10px}
.ev li span{color:var(--ink2)}
.check{display:block;background:var(--sunk);border:1px solid var(--rule2);border-radius:8px;padding:9px 12px;color:var(--ink)!important;font-size:12.5px!important}
.bc{display:block;width:100%;height:28px;fill:var(--ink)}
.fine{text-align:center}
.sr-h{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;padding:0}
@keyframes grow{from{transform:scaleX(0)}}
@keyframes stamp{from{opacity:0;transform:rotate(-4deg) scale(1.35)}}
@media (max-width:560px){
body{padding:16px 10px 48px}
.paper{padding:32px 20px 28px}
.perf{margin:30px -20px 0}
h1{font-size:25px}
.brand{font-size:15px}.logo{width:26px;height:26px}
.meta{gap:6px 12px;font-size:13px}
.proof{flex-direction:column;align-items:flex-start;gap:16px}
.items tfoot td.amt{font-size:22px}
.ev li{grid-template-columns:1fr;gap:0}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media print{
@page{margin:10mm}
html,body,.paper{background:transparent}
body{padding:0}
.top,.perf,details{display:none}
.sheet{filter:none;max-width:none}
.paper{-webkit-mask:none;mask:none;padding:0;zoom:.8;column-count:2;column-gap:44px;column-rule:1px dashed var(--rule)}
.hd,.meta,.for,.items,.caps li,.facts,.proof,.stub>div,.stub>svg,h2{break-inside:avoid}
h2{break-after:avoid}
section{margin-top:20px}
.meta{margin-top:16px}.for{margin-top:14px;padding:10px 14px}
.items th,.items td{padding:8px 0}
.fixes{gap:6px}.fixes li{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stub{padding-top:20px;gap:10px}
.stamp{transform:none}
*{animation:none!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""


def _shell(title: str, back: str, inner: str, stub: str) -> str:
    """The shared bill. `back` is the top bar, `inner` the paper above the perforation, `stub` the paper below it."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="color-scheme" content="light"><meta name="robots" content="noindex">
<style>{_CSS}</style></head><body>
<nav class="top" aria-label="Receipt">{back}<button type="button" onclick="window.print()">Print or save as PDF</button></nav>
<main class="sheet"><article class="paper">
{inner}
<div class="perf" role="separator"></div>
<footer class="stub">
{stub}
</footer>
</article></main></body></html>
"""


def _head(r: dict, kind: str, date: str) -> str:
    e = html.escape
    return (f'<header class="hd"><div class="brand">{_LOGO}FirstRun</div>'
            f'<div class="doc"><h1>Receipt</h1><span class="kind">{e(kind)}</span></div></header>'
            f'<dl class="meta"><dt>Receipt no.</dt><dd class="mono">{e(str(r.get("receipt_id", "")))}</dd>'
            + (f'<dt>Date</dt><dd>{e(date)}</dd>' if date else "")
            + (f'<dt>Issued</dt><dd>{e(_day(r.get("issued_at")))}</dd>' if r.get("issued_at") else "")
            + "</dl>")


def _stub(r: dict, run_id: str, extra: str = "") -> str:
    e = html.escape
    ev = _g(r, "audit", "evidence_sha256", default={}) or {}
    files = "".join(f'<li><span>{e(n)}</span><code>{e(h)}</code></li>' for n, h in ev.items())
    files_html = (f'<div><span class="k">Evidence files</span><ul class="ev">{files}</ul></div>' if files
                  else '<div><span class="k">Evidence files</span>No run folder was kept for this item, so the hash covers the receipt only.</div>')
    return (f'<div><span class="k">Receipt hash</span><code>{e(str(r.get("hash", "")))}</code></div>'
            f'{files_html}{extra}'
            f'<div><span class="k">Check it</span><code class="check">firstrun receipt --check docs/receipts/{e(str(r.get("receipt_id", "")))}.json</code></div>'
            f'{_barcode(str(r.get("hash", "")))}'
            f'<p class="fine">Issued by FirstRun. List prices, not billed.</p>')


def _stamp(cls: str, text: str) -> str:
    return f'<div class="stamp {cls}" role="img" aria-label="{html.escape(text)}">{_GLYPH[cls]}<span>{html.escape(text)}</span></div>'


def render_html(r: dict) -> str:
    e = html.escape
    w, p, pf, a = r.get("work") or {}, r.get("price") or {}, r.get("proof") or {}, r.get("audit") or {}
    run_id = str(w.get("run_id") or a.get("run_id") or "")
    src = str(w.get("source_url") or "")
    model, compute = p.get("model_cost_usd"), p.get("compute_per_run_usd")
    tok = []
    if p.get("input_tokens") is not None:
        tok.append(f"{p['input_tokens']:,} tokens in")
    if p.get("output_tokens") is not None:
        tok.append(f"{p['output_tokens']:,} out")
    if p.get("tool_calls"):
        tok.append(f"{p['tool_calls']} tool calls")
    total = total_usd(r)
    rows = (f'<tr><td><b>Model usage</b><span>{e(", ".join(tok)) or "Token counts not recorded"}</span></td>'
            f'<td class="amt{" nr" if model is None else ""}">{money(model)}</td></tr>')
    if compute is not None:
        rows += ('<tr><td><b>Compute</b><span>Clean containers for the run and the proof</span></td>'
                 f'<td class="amt">{money(round(float(compute), 4))}</td></tr>')
    items = (f'<table class="items"><thead><tr><th>Item</th><th class="amt">Amount</th></tr></thead><tbody>{rows}</tbody>'
             f'<tfoot><tr><th>Total</th><td class="amt{" nr" if total is None else ""}">{money(total)}</td></tr></tfoot></table>'
             f'<p class="basis">{e(str(p.get("basis") or "list price, not billed")).capitalize()}.</p>')

    caps = ""
    for c in r.get("caps") or []:
        used = c.get("used_pct")
        ok = bool(c.get("within_cap"))
        fill = 0 if used is None else min(100.0, max(0.0, float(used)))
        tier = e(str(c.get("tier", "")))
        st = f"{_pct(used)} of cap used, " + ("within cap" if ok else "over cap")
        extra = []
        if c.get("price_per_run_usd") is not None:
            extra.append(f"Price {money(c['price_per_run_usd'])} per run")
        if c.get("margin_pct") is not None:
            extra.append(f"margin {c['margin_pct']:g}%")
        caps += (f'<li class="{"ok" if ok else "over"}"><div class="cap-h"><b>{tier}</b>'
                 + ('<span class="tag">Billed tier</span>' if c.get("bills_this_run") else "")
                 + f'<span class="cv num">{money(c.get("cap_usd"))} cap</span></div>'
                 f'<div class="meter" role="img" aria-label="{tier}: {e(st)}"><i style="width:{fill:.1f}%"></i></div>'
                 f'<div class="cap-s"><span class="st">{e(st[0].upper() + st[1:])}</span><span>{e(", ".join(extra))}</span></div></li>')
    cfo = _g(r, "audit", "cfo_model", default="")
    caps_html = (f'<section aria-labelledby="h-caps"><h2 id="h-caps">Tier Caps</h2><ul class="caps">{caps}</ul>'
                 f'<p class="note">Model cost against the most each plan tier allows per run. '
                 + (f'Caps from <a href="{e(cfo)}">the cfo.ai model</a>.' if cfo else "Caps from the FirstRun plan.")
                 + '</p></section>') if caps else ""

    passed, steps = pf.get("steps_passed"), pf.get("steps_total")
    facts = []
    if passed is not None and steps is not None:
        facts.append(("Steps passed", f"{passed} of {steps}"))
    if w.get("seconds") is not None:
        facts.append(("Time", f"{w['seconds']:g} s"))
    patches = w.get("patches") or []
    facts.append(("Fixes", str(len(patches))))
    if w.get("first_failed_step") is not None:
        facts.append(("First break", f"Step {w['first_failed_step']}"))
    facts_html = "".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in facts)
    why = ""
    if w.get("first_failed_step") is not None and w.get("failure_class"):
        cls, by = str(w["failure_class"]).replace("_", " "), str(w.get("classified_by") or "")
        why = (f'<p class="line">Step {e(str(w["first_failed_step"]))} broke first. '
               + (f'{e(by[:1].upper() + by[1:])} classed the cause as {e(cls)}.' if by else f'The cause was classed as {e(cls)}.')
               + '</p>')
    fixes = "".join(
        f'<li><b>Step {e(str(x.get("step", "")))}.</b>{e(_flat(str(x.get("reason") or ""), 200))}'
        f'<details><summary>Show the command change</summary><dl class="cmd"><dt>Was</dt><dd>{e(str(x.get("was") or ""))}</dd>'
        f'<dt>Now</dt><dd>{e(str(x.get("now") or ""))}</dd></dl></details></li>' for x in patches)
    fixes_html = f'<ol class="fixes">{fixes}</ol>' if fixes else ""

    verified = bool(pf.get("verified"))
    status = str(pf.get("status") or "")
    if verified:
        stamp = _stamp("ok", "Verified")
    elif status == "passed":
        stamp = _stamp("ok", "Passed as written")
    else:
        stamp = _stamp("no", "Not verified")

    back = (f'<a href="../doc-test/#ex={e(run_id)}">Open the run</a>' if run_id else '<a href="../doc-test/">Doc-test</a>')
    for_line = (f'<div class="for"><small>For</small><a href="{e(src)}">{e(_short_url(src))}</a></div>' if src
                else '<div class="for"><small>For</small><b>A doc-test run</b></div>')
    inner = (_head(r, "Doc-test run", _day(w.get("finished_at") or w.get("started_at"))) + for_line
             + f'<section aria-labelledby="h-items"><h2 id="h-items" class="sr-h">Charges</h2>{items}</section>'
             + caps_html
             + f'<section aria-labelledby="h-work"><h2 id="h-work">Work</h2><dl class="facts">{facts_html}</dl>{why}{fixes_html}</section>'
             + f'<section aria-labelledby="h-proof"><h2 id="h-proof">Proof</h2><div class="proof"><p>{e(str(pf.get("claim") or "No proof was recorded."))}</p>{stamp}</div></section>')
    caps_from = _g(r, "audit", "caps_from", default="")
    extra = f'<div><span class="k">Caps and prices</span>{e(caps_from)}.</div>' if caps_from else ""
    return _shell(f"Receipt {r.get('receipt_id', '')}", back, inner, _stub(r, run_id, extra))


def render_audit_html(r: dict) -> str:
    e = html.escape
    w, p, lim, pf, a = (r.get("work") or {}, r.get("price") or {}, r.get("limits") or {}, r.get("proof") or {},
                        r.get("audit") or {})
    audit_id = str(a.get("audit_id") or "")
    recorded = bool(p.get("recorded")) and p.get("usd") is not None
    total = total_usd(r)
    if recorded:
        sub = []
        if p.get("jev_calls") is not None:
            sub.append(f"{p['jev_calls']} calls")
        if p.get("jev_input_tokens") is not None:
            sub.append(f"{p['jev_input_tokens']:,} input tokens")
        if p.get("estimated"):
            sub.append("estimated from a re-run")
        jev = f'<tr><td><b>Jev reads</b><span>{e(", ".join(sub))}</span></td><td class="amt">{money(p["usd"])}</td></tr>'
    else:
        jev = ('<tr><td><b>Jev reads</b><span>Calls and tokens were not counted.</span></td>'
               '<td class="amt nr">Not recorded</td></tr>')
    rows = ('<tr><td><b>Clone and history scan</b><span>One blobless clone. No model call.</span></td>'
            f'<td class="amt">{money(0.0)}</td></tr>' + jev)
    items = (f'<table class="items"><thead><tr><th>Item</th><th class="amt">Amount</th></tr></thead><tbody>{rows}</tbody>'
             f'<tfoot><tr><th>Total{" (estimated)" if p.get("estimated") else ""}</th>'
             f'<td class="amt{" nr" if total is None else ""}">{money(total)}</td></tr></tfoot></table>'
             f'<p class="basis">{e(str(p.get("basis") or ""))}</p>')

    read, cap = w.get("commits_read"), lim.get("history_commits_max")
    meter = ""
    if read is not None and cap:
        pct = min(100.0, 100 * float(read) / float(cap))
        meter = (f'<li class="ok"><div class="cap-h"><b>History read</b><span class="cv num">{cap:,} commit limit</span></div>'
                 f'<div class="meter lim" role="img" aria-label="{read:,} of {cap:,} commits read"><i style="width:{max(pct, .6):.1f}%"></i></div>'
                 f'<div class="cap-s"><span class="st num">{read:,} commits</span><span>{"capped at the limit" if w.get("history_capped") else "within the limit"}</span></div></li>')
    bits = []
    if lim.get("jev_stale_pages_max") is not None:
        bits.append(f"Jev reads at most {lim['jev_stale_pages_max']} stale pages")
    if lim.get("jev_commit_sorts_max") is not None:
        bits.append(f"sorts at most {lim['jev_commit_sorts_max']} commits")
    if lim.get("jev_batch_size") is not None:
        bits.append(f"and sends {lim['jev_batch_size']} per call")
    limits_html = (f'<section aria-labelledby="h-lim"><h2 id="h-lim">Limits</h2>'
                   + (f'<ul class="caps">{meter}</ul>' if meter else "")
                   + '<p class="note">' + ("The plan sets no dollar cap per audit." if lim.get("dollar_cap_per_audit") is None
                                           else f"The plan caps an audit at {money(lim['dollar_cap_per_audit'])}.")
                   + (f' {e(", ".join(bits))}.' if bits else "") + '</p></section>')

    facts = [(k, w.get(f)) for k, f in (("Pages", "pages"), ("Stale", "stale"), ("Aging", "aging"), ("Quiet", "quiet"),
                                        ("Fresh", "fresh"), ("Features", "features"), ("No docs", "uncovered"))
             if w.get(f) is not None]
    facts_html = "".join(f"<div><dt>{e(k)}</dt><dd>{v:,}</dd></div>" for k, v in facts)
    hist = ""
    if read is not None:
        hist = (f'<p class="line">Read {read:,} commits' + (f' since {e(_day(w.get("since")))}' if w.get("since") else "")
                + (f', up to <code>{e(str(w["head"])[:9])}</code>' if w.get("head") else "") + ".</p>")
    cards = ", ".join(f"{n} {k}" for k, n in (w.get("cards") or {}).items())
    cards_html = f'<p class="line">Cards: {e(cards)}.</p>' if cards else ""

    n, total_cards = pf.get("cards_citing_evidence"), pf.get("cards")
    if total_cards:
        stamp = _stamp("ok" if pf.get("all_cited") else "part", f"{n} of {total_cards} cards cited")
    else:
        stamp = _stamp("no", "No cards")

    repo, url = str(w.get("repo") or ""), str(w.get("url") or "")
    for_line = ('<div class="for"><small>For</small>'
                + (f'<a href="{e(url)}">{e(repo or _short_url(url))}</a>' if url.startswith("http") else f"<b>{e(repo)}</b>")
                + (f'<span>Docs in {e(str(w["docs_repo"]))}</span>' if w.get("docs_repo") else "") + "</div>")
    back = (f'<a href="../doc-audit/?id={e(audit_id)}">Open the board</a>' if audit_id else '<a href="../doc-audit/">Doc-audit</a>')
    inner = (_head(r, "Doc-audit", _day(w.get("audited_at"))) + for_line
             + f'<section aria-labelledby="h-items"><h2 id="h-items" class="sr-h">Charges</h2>{items}</section>'
             + limits_html
             + f'<section aria-labelledby="h-work"><h2 id="h-work">Work</h2><dl class="facts">{facts_html}</dl>{hist}{cards_html}</section>'
             + f'<section aria-labelledby="h-proof"><h2 id="h-proof">Proof</h2><div class="proof"><p>{e(str(pf.get("claim") or ""))}</p>{stamp}</div></section>')
    return _shell(f"Receipt {r.get('receipt_id', '')}", back, inner, _stub(r, audit_id))


# ----------------------------------------------------------------------------- the site copy

def load_econ(docs: Path) -> tuple[dict | None, str]:
    """The tier caps (business/unit_economics.json beside docs/, else the configured folder) and the cfo.ai link."""
    from firstrun import econ as econ_mod

    data = None
    for p in (docs.parent / "business" / "unit_economics.json", econ_mod.BUSINESS / "unit_economics.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            break
        except (OSError, ValueError):
            continue
    cfo = ""
    try:
        cfo = (json.loads((docs / "data" / "plan.json").read_text(encoding="utf-8")).get("cfo") or {}).get("model", "")
    except (OSError, ValueError, AttributeError):
        pass
    return data, cfo


def for_run(run_dir: Path, econ: dict, bills: str | None = None, cfo_url: str = "") -> dict:
    """build() from a run folder: state.json, and runbook.json for the count of steps in scope."""
    state = RunState.model_validate_json((run_dir / "state.json").read_text(encoding="utf-8"))
    steps = None
    try:
        rb = Runbook.model_validate_json((run_dir / "runbook.json").read_text(encoding="utf-8"))
        steps = sum(1 for s in rb.steps if not s.skipped_out_of_scope)
    except (OSError, ValueError):
        pass
    return build(state, run_dir, econ, bills=bills, cfo_url=cfo_url, steps_total=steps)


def billed_tier(receipts_dir: Path, receipt_id: str) -> str | None:
    """The tier an earlier copy of this receipt marked as billing the run, so a rebuild keeps it."""
    try:
        old = json.loads((receipts_dir / f"{receipt_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return next((c["tier"] for c in old.get("caps") or [] if c.get("bills_this_run")), None)


def index_fields(r: dict) -> dict:
    """What a site index row needs for the View receipt button."""
    fields = {"receipt": r["receipt_id"], "receipt_usd": total_usd(r)}
    if _g(r, "price", "estimated", default=False):
        fields["receipt_est"] = True
    return fields


def publish_site(r: dict, receipts_dir: Path) -> Path:
    """Write <receipt id>.json and .html into docs/receipts. Unchanged content keeps its first issue time."""
    receipts_dir.mkdir(parents=True, exist_ok=True)
    jp = receipts_dir / f"{r['receipt_id']}.json"
    try:
        old = json.loads(jp.read_text(encoding="utf-8"))
        if old.get("hash") == r.get("hash") and old.get("issued_at"):
            r = {**r, "issued_at": old["issued_at"]}
    except (OSError, ValueError):
        pass
    page = render_audit_html if r.get("kind") == "audit" else render_html
    jp.write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (receipts_dir / f"{r['receipt_id']}.html").write_text(page(r), encoding="utf-8")
    return jp


def run_folder(runs_dir: Path, row: dict) -> Path | None:
    """The run folder behind an index row. Some old rows carry a redacted id, such as `...-fla[REDACTED]`
    for flask-palletsprojects-com. Those match the one folder with the same prefix and the same source URL."""
    rid = str(row.get("id") or "")
    d = runs_dir / rid
    if (d / "state.json").exists():
        return d
    if "[REDACTED]" not in rid:
        return None
    prefix = rid.split("[REDACTED]")[0]
    hits = []
    for cand in runs_dir.glob(f"{prefix}*"):
        try:
            src = json.loads((cand / "state.json").read_text(encoding="utf-8")).get("source_url")
        except (OSError, ValueError):
            continue
        if src == row.get("url"):
            hits.append(cand)
    return hits[0] if len(hits) == 1 else None


def publish_all(docs: Path, runs_dir: Path) -> dict:
    """A receipt in docs/receipts for every run and audit the site lists, and the receipt fields on each index row.

    Run folders come from `runs_dir`. Audit boards come from docs/audits. Other receipts already in the folder
    get their HTML redrawn from their JSON."""
    out = docs / "receipts"
    econ, cfo = load_econ(docs)
    done: dict = {"runs": 0, "audits": 0, "redrawn": 0, "skipped": []}
    written: set[str] = set()
    idx = docs / "runs" / "index.json"
    if idx.exists():
        doc = json.loads(idx.read_text(encoding="utf-8"))
        for row in doc.get("runs", []):
            d = run_folder(Path(runs_dir), row)
            if econ is None or d is None:
                done["skipped"].append(row["id"])
                continue
            r = for_run(d, econ, billed_tier(out, f"FR-{d.name}"), cfo)
            publish_site(r, out)
            row.update(index_fields(r))
            written.add(r["receipt_id"])
            done["runs"] += 1
        idx.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    aidx = docs / "audits" / "index.json"
    if aidx.exists():
        doc = json.loads(aidx.read_text(encoding="utf-8"))
        for row in doc.get("audits", []):
            board = docs / "audits" / f"{row['id']}.json"
            if not board.exists():
                done["skipped"].append(row["id"])
                continue
            d = Path(runs_dir) / row["id"]
            r = build_audit(json.loads(board.read_text(encoding="utf-8")), d if d.is_dir() else None)
            publish_site(r, out)
            row.update(index_fields(r))
            written.add(r["receipt_id"])
            done["audits"] += 1
        aidx.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    for jp in sorted(out.glob("*.json")) if out.is_dir() else []:
        if jp.stem in written:
            continue
        try:
            r = json.loads(jp.read_text(encoding="utf-8"))
            page = render_audit_html if r.get("kind") == "audit" else render_html
            jp.with_suffix(".html").write_text(page(r), encoding="utf-8")
            done["redrawn"] += 1
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return done
