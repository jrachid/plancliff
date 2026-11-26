"""Usage : python versions.py <dsn admin> [<dsn admin> …] ; mesure les trois formes du nettoyage de tâches de Temporal (#12791, PR #12793) sur chaque serveur."""
import json
import statistics
import sys
import time

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

BASE = "temporal_versions"
HOT_QUEUE = (0, b"\x00\xff")
LIMIT = 100
UPPER = 1_000_000_000

DATA = """
CREATE TABLE tasks (range_hash BIGINT NOT NULL, task_queue_id BYTEA NOT NULL, task_id BIGINT NOT NULL, data BYTEA NOT NULL, data_encoding VARCHAR(16) NOT NULL, PRIMARY KEY (range_hash, task_queue_id, task_id));
INSERT INTO tasks SELECT q, ('\\x00'::bytea || int4send(q)), t, '\\x00', 'Proto3' FROM generate_series(1, 2000) q, generate_series(1, 20) t;
INSERT INTO tasks SELECT 0, '\\x00ff'::bytea, t, '\\x00', 'Proto3' FROM generate_series(1, 200000) t;
CREATE TABLE tasks_v2 (range_hash BIGINT NOT NULL, task_queue_id BYTEA NOT NULL, pass BIGINT NOT NULL, task_id BIGINT NOT NULL, data BYTEA NOT NULL, data_encoding VARCHAR(16) NOT NULL, PRIMARY KEY (range_hash, task_queue_id, pass, task_id));
INSERT INTO tasks_v2 SELECT q, ('\\x00'::bytea || int4send(q)), 1, t, '\\x00', 'Proto3' FROM generate_series(1, 2000) q, generate_series(1, 20) t;
INSERT INTO tasks_v2 SELECT 0, '\\x00ff'::bytea, 1 + t / 1000, t, '\\x00', 'Proto3' FROM generate_series(1, 200000) t;
ANALYZE tasks;
ANALYZE tasks_v2;
"""

V1_INNER = "SELECT {col} FROM tasks WHERE range_hash = $1 AND task_queue_id = $2 AND task_id < $3 ORDER BY task_queue_id,task_id LIMIT $4"
V2_INNER = "SELECT {col} FROM tasks_v2 WHERE range_hash = $1 AND task_queue_id = $2 AND (pass, task_id) < ($3, $4) ORDER BY task_queue_id,pass,task_id LIMIT $5"
FORMS = {
    ("tasks", "IN (today)"): f"DELETE FROM tasks WHERE range_hash = $1 AND task_queue_id = $2 AND task_id IN ({V1_INNER.format(col='task_id')} )",
    ("tasks", "ANY(ARRAY) (PR)"): f"DELETE FROM tasks WHERE range_hash = $1 AND task_queue_id = $2 AND task_id = ANY(ARRAY({V1_INNER.format(col='task_id')} ))",
    ("tasks", "ctid"): f"DELETE FROM tasks WHERE ctid = ANY(ARRAY({V1_INNER.format(col='ctid')}))",
    ("tasks_v2", "IN (today)"): f"DELETE FROM tasks_v2 WHERE range_hash = $1 AND task_queue_id = $2 AND task_id IN ({V2_INNER.format(col='task_id')} )",
    ("tasks_v2", "ANY(ARRAY) (PR)"): f"DELETE FROM tasks_v2 WHERE range_hash = $1 AND task_queue_id = $2 AND task_id = ANY(ARRAY({V2_INNER.format(col='task_id')} ))",
    ("tasks_v2", "ctid"): f"DELETE FROM tasks_v2 WHERE ctid = ANY(ARRAY({V2_INNER.format(col='ctid')}))",
}
VALUES = {"tasks": [*HOT_QUEUE, UPPER, LIMIT], "tasks_v2": [*HOT_QUEUE, UPPER, UPPER, LIMIT]}


def call(values):
    return sql.SQL("p({})").format(sql.SQL(", ").join(map(sql.Literal, values)))


def forced(conn, query, values, mode):
    conn.execute(sql.SQL("prepare p as {}").format(sql.SQL(query)))
    conn.execute("select set_config('plan_cache_mode', %s, true)", (mode,))
    timings = []
    for _ in range(4):
        plan = conn.execute(sql.SQL("explain (analyze, timing off, format json) execute {}").format(call(values))).fetchone()[0]
        timings.append(plan[0]["Execution Time"])
    conn.rollback()
    conn.execute("deallocate all")
    return min(timings[1:])


def auto(conn, query, values, calls=10):
    conn.execute(sql.SQL("prepare p as {}").format(sql.SQL(query)))
    timings = []
    for _ in range(calls):
        started = time.perf_counter()
        conn.execute(sql.SQL("execute {}").format(call(values)))
        timings.append((time.perf_counter() - started) * 1000)
    if conn.info.server_version >= 140000:
        generic = f"{conn.execute("select generic_plans from pg_prepared_statements where name = 'p'").fetchone()[0]}/{calls}"
    else:
        plan = "\n".join(r[0] for r in conn.execute(sql.SQL("explain execute {}").format(call(values))).fetchall())
        generic = "generic" if "$1" in plan else "custom"
    conn.rollback()
    conn.execute("deallocate all")
    return generic, statistics.median(timings[6:])


def measure(admin_dsn):
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        version = admin.execute("show server_version").fetchone()[0].split()[0]
        admin.execute(f"drop database if exists {BASE} with (force)")
        admin.execute(f"create database {BASE}")
    dsn = make_conninfo(admin_dsn, dbname=BASE)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(DATA)
    rows = []
    with psycopg.connect(dsn, prepare_threshold=None) as conn:
        conn.execute("select set_config('max_parallel_workers_per_gather', '0', false)")
        for (table, form), query in FORMS.items():
            values = VALUES[table]
            generic_ms = forced(conn, query, values, "force_generic_plan")
            custom_ms = forced(conn, query, values, "force_custom_plan")
            switched, auto_ms = auto(conn, query, values)
            rows.append({"version": version, "table": table, "form": form, "generic_ms": generic_ms, "custom_ms": custom_ms, "auto_generic_plans": switched, "auto_ms_calls_7_10": auto_ms})
            print(f"PG {version:6} {table:9} {form:16} generic {generic_ms:9.2f} ms  custom {custom_ms:8.2f} ms  auto plan: {switched:>7}, calls 7-10 {auto_ms:8.2f} ms", flush=True)
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f"drop database if exists {BASE} with (force)")
    return rows


if __name__ == "__main__":
    results = [row for dsn in sys.argv[1:] for row in measure(dsn)]
    with open("versions.resultats.json", "w") as out:
        json.dump(results, out, indent=1)
