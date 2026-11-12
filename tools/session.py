#!/usr/bin/env python3
"""The measurement session (JavaScript vs Java: one login API), natively on Windows (i7-13700F).

Every cell starts one server, checks its answers, warms it up and then measures POST /login under oha at full speed
(64 connections). Each login checks the password against its stored bcrypt hash (cost 10). Cells:

  node-bcryptjs   Node + Express 5, bcryptjs (pure JavaScript, the most downloaded bcrypt on npm)
  node-bcrypt     Node + Express 5, bcrypt (C++ addon; hashes run on libuv's thread pool, 4 threads by default)
  node-bcrypt-6   the same with UV_THREADPOOL_SIZE=6, one pool thread per server core
  spring          Spring Boot 4 (Spring MVC on Tomcat), Spring Security's BCryptPasswordEncoder
  spring-1core    the same Spring Boot jar pinned to one core (how fast Java's bcrypt is per core)

Servers run on six performance cores (logical 0,2,4,6,8,10: one per physical core, SMT siblings idle), oha on 12-13
and this script (memory sampler, /health prober) on 14-15. The E-cores (16-23) are left alone. During every measured
window this script samples the server's working set every 0.5 s, reads its CPU time before and after (cores busy =
CPU seconds / wall seconds), and sends GET /health every 0.1 s to see how long other requests wait. The warm-up
window is stored per request (oha --db-url) and reduced to finished logins per 0.5 s from the server's first answer:
the JIT warm-up curve. The cell order rotates every round. Rounds 1..N record oha's live screen as an asciinema cast;
one final round runs oha with --no-tui, to check that recording didn't move the numbers.

usage (from the repo root, after tools/build.sh):  python tools/session.py RESULTS_DIR [ROUNDS=5]
env:  BENCH_NO_GATE=1 skips the quiet-machine gate (pilot only); BENCH_SECONDS_SCALE=0.25 shortens windows (pilot
      only)
"""
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
BUILD = ROOT / "build"
USERS = ROOT / "data/users.json"
BODY = ROOT / "data/login.json"
SERVER_CPUS = [0, 2, 4, 6, 8, 10]
ONE_CPU = [0]
OHA_CPUS = [12, 13]
SELF_CPUS = [14, 15]
QUIET_CPUS = list(range(16))
PORT = int(os.environ.get("BENCH_PORT", "18126"))
BASE = f"http://127.0.0.1:{PORT}"
CONNECTIONS = 64
SCALE = float(os.environ.get("BENCH_SECONDS_SCALE", "1"))
WARM_S, MEASURE_S = 15, 20
BIN_S = 0.5
HEALTH_EVERY_S = 0.1
COLS, ROWS = 64, 14  # oha's live screen at a size that stays readable on a phone
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PY = str(Path(sys.executable).with_name("python.exe")) if os.name == "nt" else sys.executable
OHA = os.environ.get("OHA") or shutil.which("oha") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/oha.exe")
NODE = os.environ.get("NODE") or shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
JAVA_HOME = Path(os.environ.get("BENCH_JAVA_HOME") or next(Path("C:/Program Files/Eclipse Adoptium").glob("jdk-25*"), Path(".")))
JAVA = os.environ.get("JAVA") or str(JAVA_HOME / "bin" / ("java.exe" if os.name == "nt" else "java"))

CELLS = {
    "node-bcryptjs": {"side": "node", "argv": [NODE, "server-bcryptjs.mjs"], "cwd": ROOT / "node",
                      "cpus": SERVER_CPUS, "env": {}, "exe": "node"},
    "node-bcrypt": {"side": "node", "argv": [NODE, "server-bcrypt.mjs"], "cwd": ROOT / "node",
                    "cpus": SERVER_CPUS, "env": {}, "exe": "node"},
    "node-bcrypt-6": {"side": "node", "argv": [NODE, "server-bcrypt.mjs"], "cwd": ROOT / "node",
                      "cpus": SERVER_CPUS, "env": {"UV_THREADPOOL_SIZE": str(len(SERVER_CPUS))}, "exe": "node"},
    "spring": {"side": "java", "argv": [JAVA, "-jar", str(BUILD / "login-spring.jar")], "cwd": ROOT / "java",
               "cpus": SERVER_CPUS, "env": {}, "exe": "java"},
    "spring-1core": {"side": "java", "argv": [JAVA, "-jar", str(BUILD / "login-spring.jar")], "cwd": ROOT / "java",
                     "cpus": ONE_CPU, "env": {}, "exe": "java"},
}
# Answers compared across every cell (status + body).
CHECKS = [("user7@example.com", "password-7"), ("user7@example.com", "wrong"), ("nobody@example.com", "x"),
          ("user100@example.com", "password-100")]


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def secs(s: float) -> int:
    # bcryptjs interleaves all 64 hashes on one thread, so its first answers take seconds: never under 10 s.
    return max(10, round(s * SCALE))


def cpu_list(cpus: list[int]) -> str:
    return ",".join(map(str, cpus))


def quiet_gate(max_wait: int = 1800) -> dict:
    """Waits until the bench's 16 P-core threads are idle (mean under 5%, none over 15%, over 5 s) and returns that
    reading. Gives up after max_wait: a busy machine voids the numbers."""
    if os.environ.get("BENCH_NO_GATE") == "1":
        return {"gate": "skipped"}
    waited = 0
    while True:
        per = psutil.cpu_percent(interval=5, percpu=True)
        ours = [per[c] for c in QUIET_CPUS]
        reading = {"cores_mean": round(sum(ours) / len(ours), 1), "cores_max": max(ours), "total": round(sum(per) / len(per), 1)}
        if reading["cores_mean"] < 5 and reading["cores_max"] < 15:
            return reading
        if waited >= max_wait:
            raise RuntimeError(f"machine stayed busy for {max_wait} s: {reading}")
        if waited % 300 == 0:
            log(f"machine busy {reading}, waiting")
        waited += 5


def http(method: str, path: str, body: bytes | None = None, timeout: float = 10) -> tuple[int, bytes]:
    headers = {"content-type": "application/json"} if body is not None else {}
    req = urllib.request.Request(BASE + path, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Server:
    """One server process pinned to its cores from its first instruction (pin.py sets the mask; the child inherits
    it, so the JVM's availableProcessors and Node's availableParallelism see the pinned count)."""

    def __init__(self, name: str, logfile: Path):
        spec = CELLS[name]
        inherited = {k: v for k, v in os.environ.items() if k != "UV_THREADPOOL_SIZE"}
        env = {**inherited, "PORT": str(PORT), "USERS": str(USERS), **spec["env"]}
        self.log = open(logfile, "w")
        self.t0 = time.time()
        self.wrapper = subprocess.Popen([PY, str(TOOLS / "pin.py"), cpu_list(spec["cpus"]), *spec["argv"]], env=env,
                                        cwd=spec["cwd"], stdout=self.log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        self.proc = self._child(spec["exe"])
        self.ready_s = self._wait_ready()

    def _child(self, exe: str) -> psutil.Process:
        """The server itself; with CREATE_NO_WINDOW the wrapper also gets a conhost.exe child, which isn't it."""
        for _ in range(400):
            for kid in psutil.Process(self.wrapper.pid).children(recursive=True):
                try:
                    if Path(kid.exe()).stem.lower() == exe:
                        return kid
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    def _wait_ready(self) -> float:
        deadline = self.t0 + 120
        while time.time() < deadline:
            if self.wrapper.poll() is not None:
                raise RuntimeError(f"server exited with {self.wrapper.returncode}")
            try:
                if http("GET", "/health", timeout=1) == (200, b"ok"):
                    return round(time.time() - self.t0, 3)
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                pass
            time.sleep(0.05)
        raise RuntimeError("server not ready after 120 s")

    def memory_mb(self) -> float:
        return round(self.proc.memory_info().rss / 2**20, 1)

    def cpu_s(self) -> float:
        t = self.proc.cpu_times()
        return t.user + t.system

    def threads(self) -> int:
        return self.proc.num_threads()

    def stop(self) -> None:
        try:
            tree = [self.proc, *psutil.Process(self.wrapper.pid).children(recursive=True), psutil.Process(self.wrapper.pid)]
        except psutil.NoSuchProcess:
            tree = [self.proc]
        for p in tree:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(tree, timeout=30)
        self.wrapper.wait(timeout=30)
        self.log.close()
        for _ in range(100):  # the port must be free, or the next server's /health would answer from this one
            try:
                http("GET", "/health", timeout=0.5)
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                return
            time.sleep(0.1)
        raise RuntimeError("old server still answers after stop")


def answers() -> list[list]:
    out = []
    for email, password in CHECKS:
        status, body = http("POST", "/login", json.dumps({"email": email, "password": password}).encode())
        out.append([email, password, status, body.decode()])
    return out


def oha_argv(seconds: int, export: Path | None, db: Path | None, tui: bool) -> list[str]:
    argv = [OHA, "-z", f"{seconds}s", "-c", str(CONNECTIONS), "-m", "POST", "-T", "application/json",
            "-D", str(BODY), BASE + "/login"]
    if export:
        argv += ["--output-format", "json", "-o", str(export)]
    else:
        argv += ["--output-format", "quiet"]
    if db:
        argv += ["--db-url", str(db)]
    if not tui:
        argv.append("--no-tui")
    return [PY, str(TOOLS / "pin.py"), cpu_list(OHA_CPUS), *argv]


def reduce_db(db: Path, seconds: int, offset_s: float) -> dict:
    """Finished logins per BIN_S from oha's per-request table, with the time axis starting at the server's first
    answer (offset_s = seconds from that answer to oha's start)."""
    con = sqlite3.connect(db)
    try:
        statuses = dict(con.execute("SELECT status, COUNT(*) FROM oha GROUP BY status").fetchall())
        bins = [0] * round(seconds / BIN_S)
        for (b, n) in con.execute(f"SELECT CAST(end / {BIN_S} AS INTEGER), COUNT(*) FROM oha WHERE status = 200 GROUP BY 1"):
            if 0 <= b < len(bins):
                bins[b] = n
    finally:
        con.close()
    return {"statuses": {str(k): v for k, v in statuses.items()}, "bin_s": BIN_S, "offset_s": round(offset_s, 3),
            "per_bin": bins}


def health_prober(stop: threading.Event, out: list) -> None:
    while not stop.is_set():
        t = time.perf_counter()
        try:
            status, _ = http("GET", "/health", timeout=10)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            status = 0
        out.append([round((time.perf_counter() - t) * 1000, 2), status])
        stop.wait(HEALTH_EVERY_S)


def memory_sampler(server: Server, stop: threading.Event, out: list) -> None:
    while not stop.wait(0.5):
        try:
            out.append(server.memory_mb())
        except psutil.NoSuchProcess:
            return


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * q / 100))] if s else 0.0


def run_cell(name: str, rdir: Path, record: bool) -> dict:
    server = Server(name, rdir / f"{name}.server.log")
    try:
        first_answer = time.time()
        checks = answers()
        idle_mb = server.memory_mb()
        db = rdir / f"{name}.warm.db"
        db.unlink(missing_ok=True)
        warm_s = secs(WARM_S)
        oha_start = time.time()
        subprocess.check_call(oha_argv(warm_s, None, db, False), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              creationflags=NO_WINDOW)
        warm = reduce_db(db, warm_s, oha_start - first_answer)
        db.unlink(missing_ok=True)

        busy = quiet_gate_for_cell()
        export = rdir / f"{name}.json"
        seconds = secs(MEASURE_S)
        argv = oha_argv(seconds, export, None, record)
        stop = threading.Event()
        mem: list = []
        health: list = []
        threads = [threading.Thread(target=memory_sampler, args=(server, stop, mem)),
                   threading.Thread(target=health_prober, args=(stop, health))]
        psutil.cpu_percent(percpu=True)
        cpu0, t0 = server.cpu_s(), time.time()
        for t in threads:
            t.start()
        try:
            if record:
                rc = subprocess.call([PY, str(TOOLS / "cast.py"), str(rdir / f"{name}.cast"), str(COLS), str(ROWS), "--",
                                      *argv], creationflags=NO_WINDOW)
            else:
                rc = subprocess.call(argv, stdout=subprocess.DEVNULL, creationflags=NO_WINDOW)
        finally:
            stop.set()
            for t in threads:
                t.join()
        cpu1, t1 = server.cpu_s(), time.time()
        per_cpu = psutil.cpu_percent(percpu=True)
        n_threads = server.threads()
        if rc != 0 or not export.exists():
            raise RuntimeError(f"{name}: oha failed ({rc})")
        report = json.loads(export.read_text(encoding="utf-8"))
        codes = report.get("statusCodeDistribution", {})
        if set(codes) != {"200"}:
            raise RuntimeError(f"{name}: non-200 responses {codes} {report.get('errorDistribution')}")
        lat = report["latencyPercentiles"]
        h_ms = [h[0] for h in health if h[1] == 200]
        return {
            "cell": name, "side": CELLS[name]["side"], "cpus": CELLS[name]["cpus"], "started": t0, "seconds": seconds,
            "ready_s": server.ready_s, "checks": checks, "busy_before": busy,
            "rps": report["summary"]["requestsPerSec"], "requests": sum(codes.values()),
            "p50_ms": lat["p50"] * 1000, "p99_ms": lat["p99"] * 1000, "max_ms": report["summary"]["slowest"] * 1000,
            "errors": report.get("errorDistribution", {}),
            "cores_busy": round((cpu1 - cpu0) / (t1 - t0), 3), "threads": n_threads,
            "mem_idle_mb": idle_mb, "mem_mb_median": pct(mem, 50), "mem_mb_max": max(mem) if mem else 0,
            "health_n": len(health), "health_failed": sum(1 for h in health if h[1] != 200),
            "health_p50_ms": pct(h_ms, 50), "health_p99_ms": pct(h_ms, 99), "health_max_ms": max(h_ms) if h_ms else 0,
            "cpu_percpu_during": per_cpu, "warm": warm,
        }
    finally:
        server.stop()


def quiet_gate_for_cell() -> dict:
    """Between warm-up and the measured window the server is idle; only the cores outside its set must be quiet."""
    if os.environ.get("BENCH_NO_GATE") == "1":
        return {"gate": "skipped"}
    per = psutil.cpu_percent(interval=2, percpu=True)
    return {"cores_mean": round(sum(per[c] for c in QUIET_CPUS) / len(QUIET_CPUS), 1), "cores_max": max(per[c] for c in QUIET_CPUS),
            "total": round(sum(per) / len(per), 1)}


def order_for(round_no: int) -> list[str]:
    names = list(CELLS)
    k = (round_no - 1) % len(names)
    return names[k:] + names[:k]


def versions() -> dict:
    def cmd(*a: str) -> str:
        try:
            r = subprocess.run(a, check=False, capture_output=True, text=True, creationflags=NO_WINDOW)
            return (r.stdout + r.stderr).strip()
        except OSError as e:
            return f"unavailable: {e}"
    lock = json.loads((ROOT / "node/package-lock.json").read_text())
    pkgs = {k.split("node_modules/")[-1]: v["version"] for k, v in lock["packages"].items()
            if k.split("node_modules/")[-1] in ("express", "bcrypt", "bcryptjs")}
    boot = (BUILD / "spring-boot-version.txt").read_text().strip() if (BUILD / "spring-boot-version.txt").exists() else ""
    return {
        "node": cmd(NODE, "--version"), "npm_packages": pkgs, "java": cmd(JAVA, "-version"), "spring_boot": boot,
        "oha": cmd(OHA, "--version"), "os": platform.platform(), "cpu": platform.processor(),
        "power_plan": cmd("powercfg", "/getactivescheme"),
    }


def check_answers(rows: list[dict]) -> None:
    seen = {json.dumps(r["checks"]) for r in rows}
    if len(seen) != 1:
        raise RuntimeError(f"servers answered differently: {seen}")
    expect = [200, 401, 401, 200]
    got = [c[2] for c in rows[0]["checks"]]
    if got != expect:
        raise RuntimeError(f"unexpected statuses {got}")


def main() -> int:
    results = Path(sys.argv[1])
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    if hasattr(psutil.Process, "cpu_affinity"):
        psutil.Process().cpu_affinity(SELF_CPUS)
    results.mkdir(parents=True, exist_ok=False)
    (results / "meta.json").write_text(json.dumps(
        {"versions": versions(), "rounds": rounds, "server_cpus": SERVER_CPUS, "oha_cpus": OHA_CPUS,
         "connections": CONNECTIONS, "warm_s": secs(WARM_S), "measure_s": secs(MEASURE_S), "seconds_scale": SCALE,
         "users_sha256": hashlib.sha256(USERS.read_bytes()).hexdigest(), "body": BODY.read_text(),
         "started": time.ctime()}, indent=2))
    log("waiting for a quiet machine (up to 4 h)")
    quiet_gate(max_wait=4 * 3600)
    rows = []
    for r in range(1, rounds + 2):
        record = r <= rounds
        rdir = results / (f"round{r}" if record else "plain")
        rdir.mkdir()
        log(f"round {r} ({'recorded' if record else 'plain'})")
        for name in order_for(r):
            quiet_gate()
            res = run_cell(name, rdir, record)
            res["round"] = r if record else "plain"
            rows.append(res)
            check_answers(rows)
            log(f"  {name:14s} {res['rps']:8.1f} logins/s  cores {res['cores_busy']:.2f}  p99 {res['p99_ms']:7.1f} ms  "
                f"health p50 {res['health_p50_ms']:6.1f} ms  mem {res['mem_mb_median']:6.1f} MB  ready {res['ready_s']} s")
            with open(results / "runs.jsonl", "a") as f:
                f.write(json.dumps(res) + "\n")
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
