"""Write docs/examples/<target-slug>.txt (just the share code) for each finished run id given."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from firstrun import config, share  # noqa: E402
from firstrun.models import RunStatus  # noqa: E402
from firstrun import state as state_io  # noqa: E402


def main(run_ids: list[str]) -> int:
    out_dir = ROOT / "docs" / "examples"
    out_dir.mkdir(parents=True, exist_ok=True)
    for rid in run_ids:
        run_dir = Path(config.RUNS_DIR) / rid
        state = state_io.load_state(rid) if (run_dir / "state.json").exists() else None
        if state is None or state.status in (RunStatus.RUNNING, RunStatus.VERIFYING):
            print(f"- skipped {rid} (missing or still in progress)", file=sys.stderr)
            continue
        payload = share.build_payload(run_dir)
        slug = re.sub(r"[^a-z0-9]+", "-", payload["target"].lower()).strip("-") or "run"
        code = share.encode(payload)
        (out_dir / f"{slug}.txt").write_text(code, encoding="utf-8")
        print(f"- [{payload['target']} ({payload['status']})]({share.share_link(code)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
