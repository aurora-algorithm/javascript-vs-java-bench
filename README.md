# JavaScript vs Java: one login API in Node and in Spring Boot

Code and per-run results behind the "JavaScript vs Java on a login API: Spring Boot 5.6x faster, until one Node setting" Short.

## What is tested
`POST /login` with `{"email","password"}` finds the user in an in-memory map loaded from `data/users.json` (100 test
users, bcrypt hashes at cost 10, made once by `node/make_users.mjs`) and checks the password against the stored hash.
Right password: `200 {"ok":true,"id":7}`; wrong or unknown: `401 {"ok":false}`. `GET /health` answers `ok`. The
load test sends one fixed body, `data/login.json`.

| Cell | Server | Password check |
|---|---|---|
| `node-bcryptjs` | Node + Express 5 (`node/app.mjs`, entry `node/server-bcryptjs.mjs`) | bcryptjs (pure JavaScript), `await compare()` |
| `node-bcrypt` | same, entry `node/server-bcrypt.mjs` | bcrypt (C++ addon), `await compare()`, on libuv's thread pool (4 threads by default) |
| `node-bcrypt-6` | same, with `UV_THREADPOOL_SIZE=6` | bcrypt, one pool thread per server core |
| `spring` | Spring Boot (Spring MVC on Tomcat, `java/`) | Spring Security `BCryptPasswordEncoder.matches()` |
| `spring-1core` | the same jar pinned to one core | same |

Before each cell is measured, the script checks four answers (right password, wrong password, unknown user, another
user) and requires them to match across all cells.

## Setup
- **Machine:** Intel i7-13700F PC, Windows 11 (10.0.26200), Balanced power plan, native (no containers).
- **Versions** (`results/jvj-i7win-20261109/meta.json`): Node 24.13.0, Express 5.2.1, bcryptjs 3.0.3, bcrypt 6.0.0,
  Spring Boot 4.1.2 on Temurin 25.0.5, oha 1.16.0.
- **Pinning:** servers on logical CPUs 0,2,4,6,8,10 (six performance cores, their SMT siblings left idle) from their
  first instruction (`tools/pin.py`; the child process inherits the mask); `spring-1core` on CPU 0. oha on CPUs 12-13,
  the session script on 14-15.
- **Load:** oha, 64 connections, one fixed login body. Per cell: 15 s warm-up at full speed, then 20 s measured.
- **Measured alongside:** the server's working set every 0.5 s, its CPU time before and after (cores busy = CPU
  seconds / wall seconds), and `GET /health` every 0.1 s.
- **Quiet machine:** before every cell the script waits until CPUs 0-15 average under 5% with none over 15%.
- **Runs:** 5 recorded rounds (oha's live screen saved as an asciinema cast, `round*/*.cast`), with the cell order
  rotating every round, then 1 plain round with `--no-tui`. Every oha JSON export and server log is in
  `results/jvj-i7win-20261109/round*/` and `plain/`; one line per cell and round in `runs.jsonl`.

## Results (median of 5 rounds, `results/jvj-i7win-20261109/summary.json`)
| Cell | Logins/s | Cores busy | p50 | p99 | Memory (median RSS) |
|---|---|---|---|---|---|
| Node + bcryptjs | 23.8 | 0.99 | 3,028 ms | 4,528 ms | 61.8 MiB |
| Node + bcrypt | 97.2 | 3.97 | 679 ms | 683 ms | 60.9 MiB |
| Node + bcrypt, 6 pool threads | 143.3 | 5.92 | 456 ms | 474 ms | 62.4 MiB |
| Spring Boot | 133.9 | 5.91 | 487 ms | 999 ms | 195.8 MiB |
| Spring Boot, 1 core | 22.9 | 0.97 | 2,773 ms | 6,609 ms | 272.9 MiB |

`spring-1core` has one core to use; the other cells have six.

The plain round is within 1.3% of the recorded median logins/s for every cell (`plain_vs_recorded` in the same
file). `GET /health` latency, startup time and thread counts are in `summary.json` too.

## Reproduce
On Windows 11 with Node 24, Temurin JDK 25, oha on PATH, Git Bash and Python 3.12 with `psutil` and `pywinpty`:

```bash
tools/build.sh                       # npm ci, Maven 3.9.11 into tools/ (sha512 checked), builds build/login-spring.jar
PY=python tools/full.sh <name> 5     # builds, then 5 recorded rounds + the plain round
python3 tools/summarize.py results/<name>
```

`tools/pilot.sh <name>` runs one short round to check the setup. `node node/make_users.mjs` rebuilds
`data/users.json` (new salts, so new hashes).

## Notes
- `node-bcryptjs` uses bcryptjs, the most downloaded bcrypt package on npm.
- Spring Boot uses Spring Security's stock `new BCryptPasswordEncoder()` and Tomcat's default thread pool
  (`application.properties` sets no thread options).
- Node's `UV_THREADPOOL_SIZE` is 4 by default; only `node-bcrypt-6` sets it.
- The test users and passwords (`user7@example.com` / `password-7`) are made up for this benchmark.
