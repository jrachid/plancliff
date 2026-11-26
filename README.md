# plancliff

Find the PostgreSQL queries that become hundreds of times slower once Postgres switches a prepared statement to its generic plan, and prove the fix before production finds them for you.

```
$ plancliff scan postgresql://localhost/openfga_copy --stats-from postgresql://localhost/openfga_prod
1 queries from pg_stat_statements of openfga_prod, costliest first
 CLIFF      945.8×  generic     48.24 ms, custom     0.05 ms  SELECT store, object_type, object_id, relation, _user, user_…  [12 calls, queryid -1250848085573255456]
         triggered by the frequent values: store1, document, obj1188, viewer, group:hot1#member, userset, … (31 values)
         confirmed: Postgres switched to the generic plan at prepared call 6 (15/20 generic); calls 2-5 0.47 ms, calls 7-20 40.78 ms
         fix ✓ SET LOCAL plan_cache_mode = force_custom_plan;  -- in the same transaction, just before this query
               proven: calls 7-20 0.53 ms, 0/20 generic
         fix ✓ never prepare this query; with psycopg 3: cursor.execute(query, params, prepare=False)
               proven: calls 7-20 0.62 ms
```

## The problem

Drivers prepare the queries you run often: psycopg 3 from the 6th call, asyncpg always, the PostgreSQL JDBC driver after a few executions. After 5 executions of a prepared statement, Postgres may switch to a **generic plan**, built once without looking at the parameter values. It decides by comparing *estimated* costs, and on a skewed column the estimate can be badly wrong: the query that took a millisecond now takes hundreds, from the 11th call of your application onwards, and nothing in the code changed.

Two public examples, both reproduced on their real schema in [`labo/`](labo/README.md):

- [OpenFGA #3444](https://github.com/openfga/openfga/issues/3444): the write pre-check, `SELECT … FOR UPDATE`, reported going from 13 ms to 43 s. Reproduced through psycopg 3 with default settings: 0.6 to 1 ms for calls 1 to 10, 242 ms at call 11.
- [Temporal #12791](https://github.com/temporalio/temporal/issues/12791): the task cleanup `DELETE`. Reproduced the same way: 0.8 to 1.3 ms for calls 1 to 10, then 2.1 to 2.3 s per call.

The usual cure, `plan_cache_mode = force_custom_plan` for the whole database, makes every query plan on every call: about +75% on a 4-table join in the lab. The point is to know *which* queries need it.

## What plancliff does

1. **Measure.** For each parameter, it finds the column the parameter is compared with and tries the most and the least common value from `pg_stats`. It runs the query with the generic plan forced, then with the custom plan forced, best of 3 after a warm-up. At least 10× and 5 ms slower is a cliff.
2. **Verify.** It prepares each cliff again and calls it 20 times in the default `auto` mode, as your driver would. The cliff is **confirmed** when Postgres actually switches to the generic plan and calls 7-20 are at least 10× slower than calls 2-5.
3. **Prove the fix.** It replays each confirmed cliff 20 more times with each targeted fix, and reports a fix as proven only when the drop is gone.

Everything runs inside transactions that are rolled back, writes included.

## Install

```bash
pip install plancliff      # or: uv tool install plancliff, or run it once with: uvx plancliff
```

Python 3.11 or later. PostgreSQL 14 or later; tested on 14, 15, 16, 17 and 18.

## Usage

```bash
# recommended: the queries production actually runs, read from its pg_stat_statements, measured on a copy
plancliff scan postgresql://user@host/app_copy --stats-from postgresql://readonly@prod/app

# a database that has its own statistics, such as a staging database under real traffic
plancliff scan postgresql://user@host/app

# or a file: one query per block, blocks separated by a blank line, $1, $2… placeholders, an optional "-- name" line
plancliff scan postgresql://user@host/app_copy queries.sql
```

Scan a copy with realistic data: a cliff only shows on data as skewed as production's. `--stats-from` connects with `default_transaction_read_only` and only reads `pg_stat_statements`; a restored copy has no statistics of its own.

| Verdict | Meaning | Fails the run |
| --- | --- | --- |
| `cliff` | confirmed: Postgres switches to the generic plan and the query slows down; also when the verification could not run | yes |
| `latent` | the forced generic plan is slow, but Postgres keeps the custom plan today; new statistics could change that | no |
| `ok` | the generic plan is not much slower | no |
| `error` | the query could not be tested: empty table, duplicate key, a text parameter that matches no column | no |

Exit code: 1 when at least one `cliff` is found, 0 otherwise, 2 on a usage error. A CI job can run it against a staging copy and fail on a new cliff.

## Fixing a cliff

Both fixes plancliff proves touch one query only; every other query keeps the plan cache.

```python
# any driver: force the custom plan for this transaction only
with conn.transaction():
    conn.execute("SET LOCAL plan_cache_mode = force_custom_plan")
    rows = conn.execute("select id from jobs where status = %s order by created_at limit 10", ("pending",)).fetchall()

# psycopg 3: never prepare this one query
cur.execute("select id from jobs where status = %s order by created_at limit 10", ("pending",), prepare=False)
```

Not preparing a query is written differently in each driver; `--driver` makes the report use yours. plancliff proves this fix by sending the query as an unnamed statement, which is what all of them do:

| `--driver` | Never prepare this query | Scope |
| --- | --- | --- |
| `psycopg` (default) | `cursor.execute(query, params, prepare=False)` | one query |
| `pgx` | `conn.Query(ctx, sql, pgx.QueryExecModeExec, args...)` | one query |
| `jdbc` | `((PGStatement) statement).setPrepareThreshold(0)` | one statement |
| `asyncpg` | no per-query switch: a connection opened with `statement_cache_size=0` | the whole connection |

Both fixes make Postgres plan this query on each call. For one query the cost is lost in the noise: on Temporal's v2 task cleanup, 2.53 ms per call before the switch, 2.49 ms with `SET LOCAL`, against 68 ms without a fix.

## Reading pg_stat_statements

plancliff keeps the application's parameterised queries (`select`, `insert`, `update`, `delete`, `with`, `merge`), costliest first (`--top`, 100 by default), and skips utility statements and queries on system objects (`pg_*`, `information_schema`). The extension must be loaded (`shared_preload_libraries`) and installed (`CREATE EXTENSION pg_stat_statements`).

pg_stat_statements replaces constants with `$n`: a `limit 10` written in the code is stored as `limit $2`, and a parameterised limit hides the cliff from the generic plan. So an integer parameter that matches no column is also tried as a constant, and the worse verdict is kept, with a note. When your code really passes that value as a parameter, this can report a cliff that only exists in the constant form.

Without the `pg_read_all_stats` role, the statements of other roles are stored as `<insufficient privilege>`: plancliff counts them and says so (`GRANT pg_read_all_stats TO <role>;`), rather than silently scanning fewer queries; when it can read none at all, it exits with 2 instead of reporting an empty, green scan.

## Safety

- Every measure, verification and fix replay runs in a transaction that is rolled back; a connection in autocommit mode is refused.
- Each execution has a statement timeout, 30 s by default (`--timeout`).
- plancliff refuses to scan a database other sessions are connected to: measuring a write or a `FOR UPDATE` read locks rows while it runs, even rolled back, and a live application would wait. `--allow-busy` overrides this for a shared staging database you accept to slow down. plancliff's own connections are named `plancliff` and do not count.
- `--stats-from` only reads, through a read-only connection.

## Options

| Option | Effect |
| --- | --- |
| `--stats-from DSN` | read `pg_stat_statements` from this database instead of the scanned one |
| `--top N` | number of `pg_stat_statements` queries to scan, costliest first (100) |
| `--format json` | one JSON document on stdout: source, settings, every query with its measure, verification and fixes, a summary |
| `--no-verify` | skip the 20 calls; every measured cliff then counts as a `cliff`, without a proven fix |
| `--threshold`, `--min-gap-ms` | the cliff rule, 10× and 5 ms by default |
| `--timeout` | statement timeout per execution, in seconds (30) |
| `--allow-busy` | scan even when other sessions are connected |
| `--driver psycopg\|pgx\|asyncpg\|jdbc` | the application's driver, so the unprepared fix is written in its terms |
| `-v` | also list the queries that are fine |
| `--color auto\|always\|never` | coloured in a terminal, plain when piped; `NO_COLOR=1` and `FORCE_COLOR=1` are honoured |
| `--version` | print the version |

## Limits

- **Two scenarios per column**, its most and its least common value, taken independently: a trap that needs a specific combination of values can be missed.
- **Realistic data only.** On synthetic data with 101 task queues instead of 2,000, Temporal's ticket query does not fall: plancliff reports the data it is given.
- **Untestable queries** come out as `error`: empty tables, text or binary parameters that match no column, queries completed at runtime. On Temporal's 94 queries, 7 are untestable. An `INSERT` gets a value absent from each unique column, so it does not hit an existing key.
- **The verification replays one value 20 times.** An application varies its values, which can make Postgres switch earlier, later, or never.
- **Planning time is not measured**, so a custom plan that is slow because it replans on each call (the reverse problem) is not reported.
- **Postgres 18 folds a list of constants** into `IN ($1 /*, ... */)` in `pg_stat_statements`; plancliff replays it with a single value.
- **psycopg 3 drops its prepared statements on every `ROLLBACK`**: an application that rolls back often is not exposed, until it starts committing more.
- The replays plancliff runs are themselves counted by `pg_stat_statements` on the scanned database.

## Where the numbers come from

Every figure in this README comes from a script in [`labo/`](labo/README.md) that can be run again: the two public victims reproduced on their real schema with skewed data, the 94 queries of Temporal 1.31.1 extracted from its Go code, and the cost of the global setting. The test suite runs against PostgreSQL 14 to 18 and Python 3.11 to 3.13 on every push.

## Licence

MIT, see [`LICENSE`](LICENSE).
