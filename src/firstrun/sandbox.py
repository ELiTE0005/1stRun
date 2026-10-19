"""Track T2. One fresh Docker container per run, through `wsl -d Ubuntu-22.04 docker`."""

from __future__ import annotations

import os
import re
import secrets
import shlex
import subprocess
import sys
import time

from firstrun import config
from firstrun.models import FileSpec, StepResult

OUTPUT_CAP = 20 * 1024  # keep the last 20 KB of each stream
WORKDIR = "/work"

# Runs inside the container. Reads the step script from stdin, then runs it in its own
# bash with stdin closed, so a command that reads stdin cannot eat the script.
_RUNNER = """#!/bin/bash
cat > /tmp/.fr_step.sh
exec bash /tmp/.fr_step.sh < /dev/null
"""

# Restore env and cwd, run the command, save env and cwd, keep the exit code.
_PREFIX = """if [ -f /tmp/.fr_env ]; then . /tmp/.fr_env; fi
# A developer's terminal is a tty, so Python prints each line as it goes. Match that, or a dev server's
# "Serving on" line sits in a buffer until the process dies.
export PYTHONUNBUFFERED=1
cd "$(cat /tmp/.fr_cwd 2>/dev/null || echo /work)" 2>/dev/null || cd /work
# Trade-off: exit 141 (SIGPIPE) maps to 0, as in `yes | tool`, where the producer dies after the
# consumer finishes. A real command that exits 141 by itself is also hidden. PIPESTATUS is not reliable here.
trap '__fr_rc=$?; if [ "$__fr_rc" -eq 141 ]; then __fr_rc=0; fi; pwd > /tmp/.fr_cwd; export -p > /tmp/.fr_env; exit $__fr_rc' EXIT
# The shell keeps its folder between steps and retries, so `cd proj` from inside proj is a no-op,
# wherever the cd sits in the command. Any other cd behaves as usual.
cd() { if [ "$#" -eq 1 ] && [ ! -d "$1" ] && [ "$(basename "$PWD")" = "${1%/}" ]; then return 0; fi; builtin cd "$@"; }
# Any failing line or pipe part fails the step, as a developer typing the lines would see it.
set -eo pipefail
"""

_LEADING_CD = re.compile(r"^\s*cd\s+([A-Za-z0-9_][A-Za-z0-9_.\-]*)/?\s*&&\s*")


def guard_leading_cd(command: str) -> str:
    """Steps share one shell, so a `cd dir &&` the docs show may find the shell already inside dir.

    Rewrite only the leading `cd <relative dir> &&`, and only for execution. The reported command is unchanged.
    """
    m = _LEADING_CD.match(command)
    if not m:
        return command
    d = m.group(1)
    return f'{{ [ "$(basename "$PWD")" = "{d}" ] || cd {d}; }} && ' + command[m.end():]


# Kill every process except PID 1 (sleep infinity) and this shell.
_KILL_ALL = (
    "for d in /proc/[0-9]*; do p=${d#/proc/}; "
    '[ "$p" -gt 1 ] && [ "$p" != "$$" ] && kill -9 "$p" 2>/dev/null; done; true'
)


class DockerUnavailable(RuntimeError):
    """Docker (through WSL) cannot be reached, so the run stops before step 1."""


_DOCKER_DOWN = re.compile(
    r"cannot connect to the docker daemon|is the docker daemon running|error during connect|"
    r"docker: command not found|docker: not found|no such file or directory|wsl.*not|"
    r"the system cannot find|failed to connect|connection refused",
    re.I,
)


def _tail(data: bytes, cap: int = OUTPUT_CAP) -> str:
    """Keep the last `cap` bytes. A cut stream starts with a marker that says how much was dropped."""
    if len(data) > cap:
        dropped = len(data) - cap
        marker = b"[output truncated: first " + str(dropped).encode() + b" bytes dropped]" + bytes([10])
        data = marker + data[-(cap - len(marker)):]  # the whole text, marker included, stays within cap
    return data.decode("utf-8", errors="replace")


# --- stale containers --------------------------------------------------------

_NAME_WITH_PID = re.compile(r"^firstrun-.+-(\d+)-[0-9a-f]{6}$")
_OLD_AGE = re.compile(r"hour|day|week|month|year", re.I)


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_stale(name: str, running_for: str = "") -> bool:
    """A firstrun- container is stale when its owner process is gone, or it is over an hour old."""
    m = _NAME_WITH_PID.match(name)
    if m:
        return not _pid_alive(int(m.group(1)))
    return bool(_OLD_AGE.search(running_for))


def remove_stale() -> list[str]:
    """Remove firstrun- containers a crashed run left behind. Never touches a live run's container."""
    listing = subprocess.run(
        [*config.DOCKER_CMD, "ps", "-a", "--filter", "name=firstrun-", "--format", "{{.Names}}:{{.RunningFor}}"],
        capture_output=True, timeout=60,
    )
    if listing.returncode != 0:
        return []
    removed: list[str] = []
    for line in listing.stdout.decode("utf-8", errors="replace").splitlines():
        name, _, age = line.strip().partition(":")  # wsl passes the format through bash, so no pipe
        if name.startswith("firstrun-") and is_stale(name, age):
            subprocess.run([*config.DOCKER_CMD, "rm", "-f", name], capture_output=True, timeout=60)
            removed.append(name)
    return removed


def _allowlist_env() -> dict[str, str]:
    """KEY=VALUE lines from config.SECRETS_ALLOWLIST. Missing file means no secrets."""
    from firstrun import config

    out: dict[str, str] = {}
    try:
        text = config.SECRETS_ALLOWLIST.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    return out


class Container:
    """A running container. Use as a context manager: the container is removed on exit."""

    def __init__(
        self,
        image: str = "python:3.11-slim",
        name: str | None = None,
        env: dict[str, str] | None = None,
        run: str | None = None,
    ):
        self.image = image
        # Default env: the test keys from the secrets allowlist, nothing else from the host.
        self.env = dict(env) if env is not None else _allowlist_env()
        label = run or "run"
        self.name = name or f"firstrun-{label}-{os.getpid()}-{secrets.token_hex(3)}"
        self.started = False

    # --- docker plumbing --------------------------------------------------

    def _docker(self, args: list[str], input_bytes: bytes | None = None, timeout: float | None = 120):
        try:
            return subprocess.run(
                [*config.DOCKER_CMD, *args],
                input=input_bytes, capture_output=True, timeout=timeout,
            )
        except OSError as exc:  # the wsl or docker program is missing
            raise DockerUnavailable(f"docker unavailable: {exc}") from exc

    def _sh(self, script: str, timeout: float | None = 60) -> subprocess.CompletedProcess:
        """Run a small bash script in the container through stdin."""
        return self._docker(["exec", "-i", self.name, "bash", "-s"], script.encode("utf-8"), timeout)

    def __enter__(self) -> "Container":
        probe = self._docker(["image", "inspect", self.image])
        if probe.returncode != 0:
            if _DOCKER_DOWN.search(_tail(probe.stderr, 2000)) and "no such image" not in _tail(probe.stderr, 2000).lower():
                raise DockerUnavailable(f"docker unavailable: {_tail(probe.stderr, 300).strip()}")
            pulled = self._docker(["pull", self.image], timeout=900)
            if pulled.returncode != 0:
                raise RuntimeError(f"docker pull {self.image} failed: {_tail(pulled.stderr, 500)}")
        try:
            remove_stale()  # containers a crashed run left behind
        except Exception:
            pass
        run = self._docker(["run", "-d", "--name", self.name, "--network", "bridge", self.image, "sleep", "infinity"])
        if run.returncode != 0:
            raise RuntimeError(f"docker run failed: {_tail(run.stderr, 500)}")
        self.started = True
        try:
            # Env goes in through stdin, so secrets never show up on a command line.
            env_lines = "".join(f"export {k}={shlex.quote(v)}\n" for k, v in self.env.items())
            setup = (
                f"mkdir -p {WORKDIR}\n"
                f"cat > /usr/local/bin/fr_run <<'FR_RUNNER_EOF'\n{_RUNNER}FR_RUNNER_EOF\n"
                "chmod +x /usr/local/bin/fr_run\n"
                f"cat > /tmp/.fr_env <<'FR_ENV_EOF'\n{env_lines}FR_ENV_EOF\n"
                f"echo {WORKDIR} > /tmp/.fr_cwd\n"
            )
            done = self._sh(setup)
            if done.returncode != 0:
                raise RuntimeError(f"container setup failed: {_tail(done.stderr, 500)}")
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc) -> None:
        if not self.started:
            return
        self.started = False
        try:
            self._docker(["rm", "-f", self.name], timeout=60)
        except Exception:
            pass

    # --- public API -------------------------------------------------------

    def write_files(self, files: list[FileSpec]) -> None:
        for f in files:
            mark = f"FR_EOF_{secrets.token_hex(4)}"
            path = shlex.quote(f.path)
            content = f.content if f.content.endswith("\n") or not f.content else f.content + "\n"
            script = (
                f"{_PREFIX}"
                f'mkdir -p "$(dirname {path})"\n'
                f"cat > {path} <<'{mark}'\n{content}{mark}\n"
            )
            done = self._sh(script)
            if done.returncode != 0:
                raise RuntimeError(f"write_files {f.path} failed: {_tail(done.stderr, 500)}")

    def exec(self, command: str, timeout_s: int = 300, ready=None) -> StepResult:
        """Run one shell command in the container workdir. Never raises on a non-zero exit.

        ready: a compiled regex. When the output matches it (a dev server saying it listens), the command is
        stopped 2 s later and reported as timed out, so the caller can tell "came up" from "hung"."""
        # The rewrite is execution-only: callers keep the original command for reports.
        script = _PREFIX + guard_leading_cd(command) + "\n"
        start = time.monotonic()
        proc = subprocess.Popen(
            [*config.DOCKER_CMD, "exec", "-i", self.name, "fr_run"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        timed_out = False
        if ready is not None:
            out, err, code, timed_out = self._exec_until_ready(proc, script, timeout_s, ready)
        else:
            out, err, code, timed_out = self._exec_plain(proc, script, timeout_s)
        from firstrun.redact import redact

        return StepResult(
            step_id=0,
            command=command,
            exit_code=code,
            stdout=redact(_tail(out or b"")),
            stderr=redact(_tail(err or b"")),
            duration_s=round(time.monotonic() - start, 3),
            timed_out=timed_out,
        )

    def _stop(self, proc) -> None:
        proc.kill()
        try:
            self._sh(_KILL_ALL, timeout=30)
        except Exception:
            pass

    def _exec_until_ready(self, proc, script: str, timeout_s: int, ready):
        import threading

        bufs = {"out": bytearray(), "err": bytearray()}

        def pump(stream, key):
            for chunk in iter(lambda: stream.read1(4096), b""):
                bufs[key].extend(chunk)

        threads = [threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True),
                   threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True)]
        for t in threads:
            t.start()
        try:
            proc.stdin.write(script.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        deadline, seen_at = time.monotonic() + timeout_s, None
        while proc.poll() is None and time.monotonic() < deadline:
            if seen_at is None and ready.search((bufs["out"] + b"\n" + bufs["err"]).decode("utf-8", "replace")):
                seen_at = time.monotonic()
            if seen_at is not None and time.monotonic() - seen_at >= 2:  # a server that crashes on boot dies first
                break
            time.sleep(0.25)
        timed_out = proc.poll() is None
        if timed_out:
            self._stop(proc)
        for t in threads:
            t.join(timeout=5)
        code = 124 if timed_out else proc.returncode
        return bytes(bufs["out"]), bytes(bufs["err"]), code, timed_out

    def _exec_plain(self, proc, script: str, timeout_s: int):
        timed_out = False
        try:
            out, err = proc.communicate(script.encode("utf-8"), timeout=timeout_s)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            self._stop(proc)
            out, err = proc.communicate()
            code = 124
        return out, err, code, timed_out
