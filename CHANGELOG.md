# Changelog

## 0.1.1 — 2026-11-26

- `--driver psycopg|pgx|asyncpg|jdbc` writes the unprepared fix in the application's driver: `pgx.QueryExecModeExec`, `setPrepareThreshold(0)`, `statement_cache_size=0`, or `prepare=False`. The JSON report records the driver.
- An `INSERT` gets a value absent from each unique column (integer, text, `bytea`, `uuid`) instead of the most common one, so it no longer fails on an existing key. On Temporal's 94 queries, untestable queries drop from 11 to 7.
- Every measured or replayed execution is undone by a savepoint, so repeated inserts do not collide and repeated deletes see the same rows.
- Fixed: a connection on which psycopg had prepared statements of its own lost plancliff's probe on the first savepoint rollback; scans now turn psycopg's automatic preparation off and restore it afterwards.

## 0.1.0 — 2026-11-26

First release.

- `plancliff scan` measures generic against custom plans for each query, with the most and the least common value of each parameter's column from `pg_stats`, inside transactions that are rolled back.
- Each cliff is verified by 20 calls in `auto` mode, as a driver would make them: `cliff` when Postgres switches to the generic plan and slows down, `latent` when it keeps the custom plan.
- Each confirmed cliff gets two targeted fixes, `SET LOCAL plan_cache_mode = force_custom_plan` and an unprepared query, each proven by 20 more calls.
- Queries come from a file or from `pg_stat_statements`, of the scanned database or of another one through `--stats-from` and a read-only connection; constants hidden as `$n` are also tried as constants.
- Refuses to scan a database other sessions are connected to, unless `--allow-busy`.
- Text report, coloured in a terminal, or `--format json`; exit code 1 on a confirmed cliff.
- Tested on PostgreSQL 14 to 18 and Python 3.11 to 3.13.
