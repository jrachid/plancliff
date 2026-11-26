# plancliff

Find the PostgreSQL queries that become hundreds of times slower once Postgres switches to a generic plan.

Point plancliff at a copy of your database: it tells you which queries will get at least 10× slower once Postgres switches a prepared statement to its generic plan, and the value that triggers the drop.

## Usage

```bash
# the queries your application actually runs, read from pg_stat_statements of production, measured on a copy
plancliff scan postgresql://user@host/db_copy --stats-from postgresql://readonly@prod/db

# the same, when the scanned database has its own pg_stat_statements (a staging database under real traffic)
plancliff scan postgresql://user@host/db

# or a file: one query per block, blocks separated by a blank line, with $1, $2… placeholders
plancliff scan postgresql://user@host/db_copy queries.sql
```

Every query runs inside a transaction that is rolled back, writes included. `--stats-from` connects with `default_transaction_read_only` and only reads `pg_stat_statements`: a restored copy has no statistics of its own.

plancliff refuses to scan a database other sessions are connected to: measuring a write or a `FOR UPDATE` read locks rows while it runs, even rolled back, and would make a live application wait. `--allow-busy` overrides this for a shared staging database you accept to slow down. plancliff's own connections are named `plancliff` and do not count.

```
 CLIFF      650.8×  generic     89.80 ms, custom     0.14 ms  queue
         triggered by the rare values: pending
         confirmed: Postgres switched to the generic plan at prepared call 6 (15/20 generic); calls 2-5 0.32 ms, calls 7-20 94.97 ms
         fix ✓ SET LOCAL plan_cache_mode = force_custom_plan;  -- in the same transaction, just before this query
               proven: calls 7-20 0.37 ms, 0/20 generic
         fix ✓ never prepare this query; with psycopg 3: cursor.execute(query, params, prepare=False)
               proven: calls 7-20 0.31 ms

3 queries in 2.0 s: 1 cliff, 0 latent, 2 ok, 0 error
Prefer the targeted fixes above to the broad one: ALTER ROLE <app role> SET plan_cache_mode = force_custom_plan  -- every query of the role pays planning, +78% on a 4-table join
```

## Reading pg_stat_statements

plancliff keeps the application's parameterised queries (`select`, `insert`, `update`, `delete`, `with`, `merge`), costliest first (`--top`, 100 by default), and skips utility statements and queries on system objects (`pg_*`, `information_schema`). The extension must be loaded (`shared_preload_libraries`) and installed (`CREATE EXTENSION pg_stat_statements`).

pg_stat_statements replaces constants with `$n`: a `limit 10` written in the code is stored as `limit $2`, and a parameterised limit hides the cliff from the generic plan. So an integer parameter that matches no column is also tried as a constant, and the worse verdict is kept, with a note. When your code really passes that value as a parameter, this can report a cliff that only exists in the constant form.

Without the `pg_read_all_stats` role, the statements of other roles are stored as `<insufficient privilege>`: plancliff counts them and says so (`GRANT pg_read_all_stats TO <role>;`), rather than silently scanning fewer queries; when it can read none at all, it exits with 2 instead of reporting an empty, green scan.

The replays plancliff runs are themselves counted by pg_stat_statements on the scanned database.

## How it decides

1. **Measure.** For each parameter, plancliff finds the column it is compared with and tries the most and the least common value from `pg_stats`. It runs the query with the generic plan forced, then with the custom plan forced, and keeps the best of 3 runs after a warm-up. A gap of at least 10× and 5 ms is a cliff.
2. **Verify.** Each cliff is prepared again and called 20 times in the default `auto` mode, as your driver would. It is **confirmed** when Postgres actually switches to the generic plan and calls 7-20 are at least 10× slower than calls 2-5.
3. **Prove the fix.** Each confirmed cliff is replayed 20 more times with each targeted fix: `SET LOCAL plan_cache_mode = force_custom_plan` in the transaction, and sending the query unprepared (psycopg 3: `prepare=False`). A fix is reported as proven when calls 7-20 no longer fall off the cliff. Setting `plan_cache_mode` for a whole role also works, but makes every query of that role plan on each call.

| Verdict | Meaning | Fails the run |
| --- | --- | --- |
| `cliff` | confirmed: Postgres switches to the generic plan and the query slows down (or the verification itself could not run) | yes |
| `latent` | the generic plan is slow, but Postgres keeps the custom plan today; new statistics could change that | no |
| `ok` | the generic plan is not much slower | no |
| `error` | the query could not be tested: empty table, duplicate key, a parameter without a column | no |

Exit code: 1 when at least one `cliff` is found, 0 otherwise, 2 on a usage error.

## Options

| Option | Effect |
| --- | --- |
| `--format json` | one JSON document on stdout: settings, every query with its measure and verification, a summary |
| `--no-verify` | skip the 20 calls; every measured cliff then counts as a `cliff` |
| `--threshold`, `--min-gap-ms` | the cliff rule, 10× and 5 ms by default |
| `--timeout` | statement timeout per execution, 30 s by default |
| `-v` | also list the queries that are fine |
| `--color auto\|always\|never` | coloured in a terminal, plain when piped; `NO_COLOR=1` and `FORCE_COLOR=1` are honoured |

## Status

Work in progress towards 0.1. The experiments behind every figure are in [`labo/`](labo/README.md).

## Licence

MIT, see [`LICENSE`](LICENSE).
