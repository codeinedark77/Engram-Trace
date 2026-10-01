# Chronicle

A standalone, tamper-evident decision-trace recorder for autonomous agent systems.

Every agent action gets recorded as a `TraceRecord` — who decided what, why, and
what happened — and each record is chained by hash to the one before it. Edit,
delete, or reorder a row directly in the database and `verify_integrity()` will
catch it and tell you exactly where the chain broke. It's a black-box flight
recorder for your agents, not an authorization system — it doesn't decide
anything, it just makes sure nothing that already happened can be quietly
rewritten.

Chronicle has no dependency on any other package in the empire. Anything —
Safety Guardian, agent-harness, a single agent, a completely unrelated
project — can `pip install -e .` and start calling `Recorder.record()`.

## Quickstart

```python
from chronicle import Recorder, DecisionOutcome

recorder = Recorder(db_path="empire.db")

trace = recorder.record(
    agent_id="planner-01",
    decision="propose deploying agent-harness to production",
    outcome=DecisionOutcome.PROPOSED,
    correlation_id="rollout-2026-08-10",
    reasoning="all 123 tests green, canary window looks clean",
)

recorder.record(
    agent_id="safety-guardian",
    decision="approve deployment",
    outcome=DecisionOutcome.APPROVED,
    correlation_id="rollout-2026-08-10",
    parent_trace_id=trace.trace_id,
)

report = recorder.verify_integrity()
assert report.is_valid
```

For a propose → resolve arc like the one above, `recorder.decision()` is the
more ergonomic version of the same two calls — and it records `FAILED`
automatically if the block raises, so a crashing agent still leaves a trace:

```python
with recorder.decision(agent_id="safety-guardian", decision="authorize deploy",
                        correlation_id="rollout-2026-08-10") as d:
    if is_within_scope(action):
        d.resolve(DecisionOutcome.APPROVED, reasoning="within declared scope")
    else:
        d.resolve(DecisionOutcome.DENIED, reasoning="scope violation")
```

## Why hash-chained

Each `TraceRecord.record_hash` is `sha256(prev_hash + canonical_json(record))`.
Writes take an immediate SQLite write lock before reading the previous hash, so
concurrent writers can't race on it — same fix pattern as the TOCTOU close in
Companion's approve/deny path, applied here to the read-prev-hash step.

`verify_integrity()` walks every record in sequence order and recomputes each
hash from its stored contents. A tampered `decision` field, a deleted row, or
a reordered one all break the chain from that point forward, and the report
tells you the exact `seq` where it broke.

One honest subtlety: if the store's earliest record really is `seq=1`,
`verify_integrity()` independently confirms the chain back to true genesis
(`anchored_at_genesis=True`). If earlier history has been archived and pruned
(see below), the earliest *remaining* record's own `prev_hash` is trusted as
the starting point instead — the result can still be `is_valid=True` (what's
left really is self-consistent) but `anchored_at_genesis=False`, since
nothing in the live store alone can prove that starting hash is genuine. A
pruned-but-honest store is not the same thing as a tampered one, and the
report says so explicitly instead of just reporting BROKEN either way.

## Running as a service

```bash
uvicorn chronicle.api:app --port 8420
```

By default this runs with **no authentication** — fine for local dev, not
fine for anything reachable by other agents. See Authentication below.

| Endpoint | Purpose | Auth |
|---|---|---|
| `POST /traces` | record a decision | required if configured |
| `GET /traces?agent_id=&correlation_id=&outcome=` | query traces | required if configured |
| `GET /traces/{correlation_id}/chain` | full chain for one task | required if configured |
| `GET /traces/{correlation_id}/replay` | chain as readable markdown | required if configured |
| `GET /integrity` | run a full integrity check | required if configured |
| `GET /health` | liveness check | never required |

## Authentication

A tamper-evident log that anyone can write to isn't very tamper-evident.
Every route except `/health` is gated behind a bearer token, but only once
you've configured one — no token configured means no auth enforced, so
local single-user testing still works with zero setup.

```bash
TOKEN=$(chronicle token)          # generate a random token
chronicle --db empire.db serve --token "$TOKEN"
# or export CHRONICLE_API_TOKEN and omit --token entirely
```

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8420/traces
```

`create_app()` resolves the token as: an explicit `api_token` argument, then
the `CHRONICLE_API_TOKEN` env var, then `None` (no auth) if neither is set.
Passing `api_token=None` explicitly forces auth off even if the env var is
set — mainly useful for tests. Token comparison uses
`secrets.compare_digest` to avoid a timing side-channel. `chronicle serve`
prints a visible warning to stderr if it starts with no token configured,
so running unauthenticated is never a silent default in production.

This only protects the network-exposed API. The CLI and any direct
`Recorder(db_path=...)` usage talk straight to the SQLite file and are
governed by filesystem permissions instead — same trust boundary as any
database: network access is authenticated, local shell access is a
different, orthogonal concern.

## Command line

Installing the package registers a `chronicle` command:

```bash
# record a decision from a shell script or a non-Python agent
chronicle --db empire.db log deploy-agent "deployed v1.0" executed \
    --correlation-id rollout-2026-08-10 --reasoning "canary passed"

# check the chain hasn't been tampered with
chronicle --db empire.db verify
chronicle --db empire.db verify --json   # for feeding a dashboard/script

# replay a task's full decision chain as markdown
chronicle --db empire.db replay rollout-2026-08-10

# run the API service (equivalent to the uvicorn command above)
chronicle --db empire.db serve --port 8420 --token "$TOKEN"

# generate a random token for serve/CHRONICLE_API_TOKEN
chronicle token
```

`verify` exits `0` when the chain is valid and `1` when it's broken, so it
drops straight into a CI step or a cron job without extra glue.

## Archiving old history

A hash chain that runs forever eventually means a database that grows
forever. `archive_and_prune()` handles this safely: it exports the requested
range to a JSONL file, re-reads and independently verifies that file, and
only *then* deletes those records from the live store. It refuses to delete
anything it hasn't successfully verified from disk first.

```python
deleted = recorder.archive_and_prune("2026-q3.jsonl", up_to_seq=48200)

# months later, prove the archive and the live store still form one
# unbroken chain, even though the early part now only exists in the file
report = recorder.verify_continuity("2026-q3.jsonl")
assert report.is_valid and report.anchored_at_genesis
```

From the command line:

```bash
chronicle --db empire.db archive 2026-q3.jsonl --up-to-seq 48200
chronicle --db empire.db verify --archive 2026-q3.jsonl
```

`examples/archiving.py` runs this end to end and prints the difference
between "the live remainder is self-consistent" and "the full history is
provably intact" — the two things a broken chain and a pruned-but-honest
chain both look like from the live store's side alone.

## Where this plugs into the empire

- **agent-harness** — call `recorder.record()` (or wrap the transition in
  `recorder.decision()`) at each lifecycle state change (proposed →
  approved/denied → executed/failed). The `correlation_id` should be the
  task/session id already flowing through the lifecycle state machine;
  `parent_trace_id` chains sub-decisions to the decision that spawned them.
- **Safety Guardian v2** — `recorder.decision()` maps directly onto
  Guardian's authorize flow: open the span when a request comes in,
  `resolve()` with APPROVED or DENIED and Guardian's own explanation as
  `reasoning`. This is what turns "Guardian denied it" into something you
  can replay six weeks later and actually reconstruct.
- **Meta-dashboard** — poll `GET /integrity` on an interval and surface it as
  a canary signal: a broken chain is a stronger red flag than almost anything
  else the dashboard tracks, since it means the audit trail itself was
  touched. `GET /traces` with a `since` filter feeds a live decision stream.
  If Chronicle is running with a token configured, the dashboard needs it in
  its own config to keep polling.
- **Non-Python pieces** (Sieve, shell hooks, CI steps) — `chronicle log`
  gives anything that can shell out a way to write into the same chain, no
  Python binding required.
- **Empire Manifest** (if built) — Manifest defines what an agent is allowed
  to do; Chronicle records what it actually did. An action that Chronicle
  shows executing outside an agent's declared Manifest scope is itself worth
  alerting on.

This session couldn't wire directly into agent-harness or Safety Guardian's
actual code (not present here) — the integration points above are the
concrete next step, not yet done.

## Tests

71 tests, 97% statement coverage. The uncovered spots are a couple of
duplicate 404 branches already proven by identical passing tests, `prune`'s
rollback path (hard to trigger deterministically, same class as similar
paths elsewhere), a blank-line skip when parsing an archive file, and the
`serve` command body — it blocks running a real server, so it's verified by
actually launching it (with and without a token) and curling every response
code by hand rather than by a pytest unit test. Covers the storage layer,
hash-chain linkage, tamper/deletion detection, replay rendering, the
FastAPI surface and its bearer-token auth (missing/wrong/correct token,
env-var fallback, explicit override, `/health` always open), the CLI, the
`decision()` context manager including its failure path, archiving and
pruning including a refusal test that forces a failed verification, the
anchored-vs-tampered distinction after pruning, and concurrent-writer
correctness under 8 threads hammering the same store simultaneously.

The `anchored_at_genesis` field exists because of a real bug this session
caught by actually running `examples/archiving.py`, not just the unit
suite: the first version of `verify_integrity()` reported a legitimately
archived-and-pruned store as `BROKEN`, identical to real tampering, because
it always checked against true genesis regardless of whether earlier
history had been honestly removed. None of the unit tests at the time
called plain `verify_integrity()` on a pruned store, so it slipped past
"all green" — the fix and its regression tests are in `test_integrity.py`
and `test_cli.py`.

```bash
pip install -e ".[dev]"
pytest --cov=chronicle
```

CI (`.github/workflows/test.yml`) runs the same suite on Python 3.10, 3.11,
and 3.12 on every push/PR. Verified locally that the YAML parses and the
job structure is correct — not yet run on an actual GitHub runner.
