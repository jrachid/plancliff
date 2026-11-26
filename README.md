# plancliff

Find the PostgreSQL queries that become hundreds of times slower once Postgres switches to a generic plan.

Point plancliff at a copy of your database: it tells you which queries will get at least 10× slower once Postgres switches a prepared statement to its generic plan, and the value that triggers the drop.

## Usage

```bash
plancliff scan postgresql://user@host/db_copy queries.sql
```

`queries.sql` holds one query per block, blocks separated by a blank line, with `$1`, `$2`… placeholders; an optional `-- name` line names a block. Every query runs inside a transaction that is rolled back, writes included.

```
 CLIFF     679.6×  generic     99.89 ms, custom     0.15 ms  queue
        triggered by the rare values: pending

3 queries in 0.5 s: 1 cliff, 2 ok, 0 error
```

The report is coloured in a terminal and plain when piped or redirected; `NO_COLOR=1`, `FORCE_COLOR=1` and `--color always|never` override that.

Exit code: 0 when no cliff is found, 1 when at least one is, 2 on a usage error.

## Status

Work in progress towards 0.1. The experiments behind every figure are in [`labo/`](labo/README.md).

## Licence

MIT, see [`LICENSE`](LICENSE).
