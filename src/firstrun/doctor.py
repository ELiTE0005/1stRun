"""`firstrun doctor`. Checks that a machine can run Doc-test and Doc-audit, and says how to fix each gap.

It reads whether a key is set, never its value. Every check is a function, so tests replace the slow ones.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from firstrun import config

# Endpoints FirstRun calls. Any HTTP answer counts as reachable: the check is the network, not the key.
ENDPOINTS = {
    "github": "https://github.com",
    "firecrawl": "https://api.firecrawl.dev",
    "typesafe": "https://api.typesafe.ai",
}

# The tools each check gates. "test" is Doc-test, "audit" is Doc-audit.
REQUIRED = {
    "python": ("test", "audit"),
    "git": ("test", "audit"),
    "docker": ("test",),
    "CLAUDE_CODE_OAUTH_TOKEN": ("test",),
    "net_github": ("audit",),
}


def _check(name: str, ok: bool, detail: str, fix: str = "", optional: bool = False) -> dict:
    status = "pass" if ok else ("warn" if optional else "fail")
    return {"name": name, "status": status, "required_for": list(REQUIRED.get(name, ())),
            "detail": detail, "fix": "" if ok else fix}


def check_python() -> dict:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    return _check("python", ok, f"Python {v.major}.{v.minor}.{v.micro} at {sys.executable}",
                  "Install Python 3.11 or newer, then make a venv with it: python3.11 -m venv .venv")


def check_git() -> dict:
    exe = shutil.which("git")
    return _check("git", bool(exe), exe or "git is not on PATH",
                  "Install git (https://git-scm.com/downloads). pip install from GitHub and firstrun audit both need it.")


def probe_docker(timeout: float = 30) -> tuple[bool, str]:
    """(ok, detail) from `docker info` through FIRSTRUN_DOCKER or the default command."""
    cmd = [*config.DOCKER_CMD, "info", "--format", "{{.ServerVersion}}"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{' '.join(config.DOCKER_CMD)}: {exc.__class__.__name__}"
    if p.returncode != 0:
        tail = (p.stderr or p.stdout).strip().splitlines()
        return False, f"{' '.join(config.DOCKER_CMD)} info failed: {tail[-1][:160] if tail else 'exit ' + str(p.returncode)}"
    return True, f"{' '.join(config.DOCKER_CMD)}, server {p.stdout.strip()}"


def check_docker(probe=probe_docker) -> dict:
    ok, detail = probe()
    fix = ("Start Docker inside WSL: wsl -d Ubuntu-22.04 sudo service docker start. "
           "Or set FIRSTRUN_DOCKER to a working docker command.") if sys.platform == "win32" else (
           "Install Docker and start the daemon, or set FIRSTRUN_DOCKER to a working docker command.")
    return _check("docker", ok, detail, fix)


KEY_INFO = {
    "CLAUDE_CODE_OAUTH_TOKEN": (False, "Doc-test plans and repairs steps with Claude.",
                                "Ask the human to run `claude setup-token` and put CLAUDE_CODE_OAUTH_TOKEN in .env."),
    "TYPESAFE_API_KEY": (True, "Optional. Jev classifies failures and reads stale pages. Without it, Doc-test asks Claude "
                               "and Doc-audit sorts commits by subject line.",
                         "Optional. Ask the human for a TypeSafe key and put TYPESAFE_API_KEY in .env."),
    "LANGFUSE_PUBLIC_KEY": (True, "Optional. Exports one Langfuse trace per run. Needs LANGFUSE_SECRET_KEY too.",
                            "Optional. Put LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env to export traces."),
    "LANGFUSE_SECRET_KEY": (True, "Optional. Exports one Langfuse trace per run. Needs LANGFUSE_PUBLIC_KEY too.",
                            "Optional. Put LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env to export traces."),
    "GITHUB_TOKEN": (True, "Optional. GITHUB_TOKEN, GH_TOKEN or a gh login lets the team map join commit authors "
                           "to GitHub logins.",
                     "Optional. Set GITHUB_TOKEN or GH_TOKEN, or run `gh auth login`."),
}


def check_key(name: str) -> dict:
    optional, why, fix = KEY_INFO[name]
    if name == "GITHUB_TOKEN":
        from firstrun.team import _token  # GITHUB_TOKEN, GH_TOKEN or `gh auth token`. The value stays here.

        present = bool(_token())
    else:
        present = bool(os.environ.get(name))
    return _check(name, present, ("set. " if present else "not set. ") + why, fix, optional=optional)


def check_tool(name: str, why: str, fix: str) -> dict:
    exe = shutil.which(name) or (shutil.which(name + ".cmd") if sys.platform == "win32" else None)
    return _check(name, bool(exe), (exe + ". " if exe else "not on PATH. ") + why, fix, optional=True)


def probe_url(url: str, timeout: float = 10, tries: int = 2) -> tuple[bool, str]:
    """Any HTTP answer within `tries` attempts. One slow answer is common, so a single timeout is not a failure."""
    import httpx

    err = ""
    for _ in range(tries):
        try:
            r = httpx.get(url, timeout=timeout, follow_redirects=False)
        except httpx.HTTPError as exc:
            err = exc.__class__.__name__
            continue
        return True, f"{url}: HTTP {r.status_code}"
    return False, f"{url}: {err} after {tries} tries"


def check_net(label: str, url: str, probe=probe_url) -> dict:
    ok, detail = probe(url)
    optional = label != "github"
    return _check(f"net_{label}", ok, detail, f"{url} did not answer over HTTPS. Run firstrun doctor again. "
                  "If it fails twice, check the network or the proxy.",
                  optional=optional)


def run(docker_probe=None, url_probe=None) -> dict:
    """Every check, plus which tools can run. Loads .env first, the same way a run does."""
    docker_probe, url_probe = docker_probe or probe_docker, url_probe or probe_url
    config.load_env()
    env_file = config.ENV_FILE
    checks = [
        check_python(),
        check_git(),
        check_docker(docker_probe),
        *(check_key(k) for k in KEY_INFO),
        check_tool("firecrawl", "Optional. Doc-test reads docs pages with it and falls back to a plain HTTP GET.",
                   "Optional. npm install -g firecrawl-cli, then firecrawl login."),
        check_tool("gh", "Optional. Needed for audit-submit and for the commands that firstrun pr prints.",
                   "Optional. Install the GitHub CLI from https://cli.github.com and run gh auth login."),
        *(check_net(k, u, url_probe) for k, u in ENDPOINTS.items()),
    ]
    failed = {c["name"] for c in checks if c["status"] == "fail"}
    can = {tool: not any(tool in REQUIRED.get(n, ()) for n in failed) for tool in ("test", "audit")}
    return {
        "env_file": {"path": str(env_file), "exists": env_file.exists()},
        "docker_cmd": " ".join(config.DOCKER_CMD),
        "can_run": {"doc_test": can["test"], "doc_audit": can["audit"], "hosted_audit": True, "read_public_data": True},
        "checks": checks,
    }


def ready(result: dict, tool: str) -> bool:
    can = result["can_run"]
    if tool == "test":
        return can["doc_test"]
    if tool == "audit":
        return can["doc_audit"]
    return can["doc_test"] and can["doc_audit"]
