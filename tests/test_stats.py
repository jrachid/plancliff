import json
import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from plancliff import Verdict
from plancliff.cli import EXIT_CLIFF, EXIT_USAGE, main
from plancliff.stats import StatsUnavailable, read_stat_queries

STATS_ADMIN_DSN = os.environ.get("PLANCLIFF_TEST_STATS_DSN", "postgresql://postgres:p@localhost:55433/postgres")
PRODUCTION, COPY = "plancliff_stats_prod", "plancliff_stats_copy"
QUEUE_IN_APP = "select id from jobs where status = %s order by created_at limit 10"


def _build(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("create table jobs (id bigserial primary key, status text not null, created_at timestamptz not null, payload text)")
        conn.execute(
            "insert into jobs (status, created_at) select case when g > 299700 then 'pending' else 'done' end,"
            " timestamptz '2026-01-01' + g * interval '1 second' from generate_series(1, 300000) g"
        )
        conn.execute("create index on jobs (status)")
        conn.execute("create index on jobs (created_at)")
        conn.execute("analyze")


@pytest.fixture(scope="module")
def stats_dsns():
    try:
        admin = psycopg.connect(STATS_ADMIN_DSN, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as error:
        pytest.skip(f"no Postgres with pg_stat_statements for these tests (set PLANCLIFF_TEST_STATS_DSN): {error}")
    with admin:
        if "pg_stat_statements" not in admin.execute("show shared_preload_libraries").fetchone()[0]:
            pytest.skip("pg_stat_statements is not in shared_preload_libraries of PLANCLIFF_TEST_STATS_DSN")
        for name in (PRODUCTION, COPY):
            admin.execute(f"drop database if exists {name} with (force)")
            admin.execute(f"create database {name}")
            admin.execute(f"alter database {name} set max_parallel_workers_per_gather = 0")
    production, copy = (make_conninfo(STATS_ADMIN_DSN, dbname=name) for name in (PRODUCTION, COPY))
    for dsn in (production, copy):
        _build(dsn)
    with psycopg.connect(production, autocommit=True) as conn:
        conn.execute("create extension pg_stat_statements")
        conn.execute("select pg_stat_statements_reset(0, (select oid from pg_database where datname = current_database()), 0)")
    with psycopg.connect(production) as app:
        for i in range(12):
            app.execute(QUEUE_IN_APP, ("pending",)).fetchall()
            app.execute("select id, status from jobs where id = %s", (i + 1,)).fetchall()
            app.execute("select count(*) from jobs").fetchall()
            app.commit()
    yield production, copy
    with psycopg.connect(STATS_ADMIN_DSN, autocommit=True) as admin:
        for name in (PRODUCTION, COPY):
            admin.execute(f"drop database if exists {name} with (force)")


def test_reading_keeps_the_application_queries_costliest_first(stats_dsns):
    with psycopg.connect(stats_dsns[0]) as conn:
        queries = read_stat_queries(conn, 100)
    texts = [q.sql for q in queries]
    assert texts[0] == "select id from jobs where status = $1 order by created_at limit $2"
    assert "select id, status from jobs where id = $1" in texts
    assert not any(t.lower().startswith(("begin", "commit")) or "$" not in t or "pg_" in t for t in texts)
    assert all(q.calls >= 1 for q in queries)
    with psycopg.connect(stats_dsns[0]) as conn:
        assert len(read_stat_queries(conn, 1)) == 1


def test_a_missing_extension_says_how_to_install_it(stats_dsns):
    with psycopg.connect(stats_dsns[1]) as conn, pytest.raises(StatsUnavailable, match="CREATE EXTENSION pg_stat_statements"):
        read_stat_queries(conn, 100)


def test_a_limit_constant_hidden_as_a_parameter_is_still_caught(stats_dsns, capsys):
    assert main(["scan", stats_dsns[0], "--top", "1", "--format", "json"]) == EXIT_CLIFF
    document = json.loads(capsys.readouterr().out)
    query = document["queries"][0]
    assert query["verdict"] == Verdict.CLIFF.value
    assert query["sql"] == "select id from jobs where status = $1 order by created_at limit 100"
    assert "$2 also tried as the constant 100" in query["note"]
    assert query["verification"]["confirmed"] and all(fix["works"] for fix in query["fixes"])
    assert document["source"] == {"kind": "pg_stat_statements", "database": PRODUCTION, "top": 1}


def test_stats_read_on_production_are_measured_on_the_copy(stats_dsns, capsys):
    production, copy = stats_dsns
    assert main(["scan", copy, "--stats-from", production, "--top", "2"]) == EXIT_CLIFF
    output = capsys.readouterr().out
    assert f"2 queries from pg_stat_statements of {PRODUCTION}" in output
    assert "CLIFF" in output and "note:" in output


def test_the_production_connection_is_read_only(stats_dsns):
    with psycopg.connect(stats_dsns[0], options="-c default_transaction_read_only=on") as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("update jobs set payload = 'x' where id = 1")


def test_a_database_without_the_extension_is_a_usage_error(stats_dsns, capsys):
    assert main(["scan", stats_dsns[1]]) == EXIT_USAGE
    assert "CREATE EXTENSION pg_stat_statements" in capsys.readouterr().err


def test_a_file_and_stats_from_together_are_a_usage_error(stats_dsns, tmp_path):
    queries = tmp_path / "queries.sql"
    queries.write_text("select 1\n")
    assert main(["scan", stats_dsns[1], str(queries), "--stats-from", stats_dsns[0]]) == EXIT_USAGE


def test_the_constant_form_renumbers_the_parameters_that_stay(stats_dsns):
    from plancliff.stats import constant_form

    with psycopg.connect(stats_dsns[1]) as conn:
        text, note = constant_form(conn, "select id from jobs where status = $2 order by created_at limit $1")
        assert text == "select id from jobs where status = $1 order by created_at limit 100"
        assert note.startswith("$1 also tried as the constant 100")
        assert constant_form(conn, "select id from jobs where id = $1") is None
