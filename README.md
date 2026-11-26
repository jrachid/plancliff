# plancliff

Find the PostgreSQL queries that become hundreds of times slower once Postgres switches to a generic plan.

Point plancliff at a copy of your database: it tells you which queries will get at least 10× slower once Postgres switches a prepared statement to its generic plan, and the value that triggers the drop.

## Usage

```bash
plancliff scan postgresql://user@host/db_copy queries.sql
```

`queries.sql` holds one query per block, blocks separated by a blank line, with `$1`, `$2`… placeholders; an optional `-- name` line names a block. Every query runs inside a transaction that is rolled back, writes included.

```
 CLIFF      650.8×  generic     89.80 ms, custom     0.14 ms  queue
         triggered by the rare values: pending
         confirmed: Postgres switched to the generic plan at prepared call 6 (15/20 generic); calls 2-5 0.35 ms, calls 7-20 99.62 ms

3 queries in 2.1 s: 1 cliff, 0 latent, 2 ok, 0 error
```

## How it decides

1. **Measure.** For each parameter, plancliff finds the column it is compared with and tries the most and the least common value from `pg_stats`. It runs the query with the generic plan forced, then with the custom plan forced, and keeps the best of 3 runs after a warm-up. A gap of at least 10× and 5 ms is a cliff.
2. **Verify.** Each cliff is prepared again and called 20 times in the default `auto` mode, as your driver would. It is **confirmed** when Postgres actually switches to the generic plan and calls 7-20 are at least 10× slower than calls 2-5.

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
