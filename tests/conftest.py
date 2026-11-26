import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

ADMIN_DSN = os.environ.get("PLANCLIFF_TEST_DSN", "postgresql://postgres:p@localhost:55432/postgres")
TEST_DB = "plancliff_test"
REQUIRE_DB = bool(os.environ.get("PLANCLIFF_REQUIRE_DB"))


def _unavailable(reason: str) -> None:
    """_unavailable skips the database tests locally, and fails them in CI where PLANCLIFF_REQUIRE_DB is set."""
    (pytest.fail if REQUIRE_DB else pytest.skip)(reason)
JOBS = 300_000
PENDING = 300
EVENTS = 300_000


@pytest.fixture(scope="session")
def dsn() -> str:
    try:
        admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as error:
        _unavailable(f"no Postgres for the database tests (set PLANCLIFF_TEST_DSN): {error}")
    with admin:
        admin.execute(f"drop database if exists {TEST_DB} with (force)")
        admin.execute(f"create database {TEST_DB}")
        admin.execute(f"alter database {TEST_DB} set max_parallel_workers_per_gather = 0")
    test_dsn = make_conninfo(ADMIN_DSN, dbname=TEST_DB)
    with psycopg.connect(test_dsn, autocommit=True) as conn:
        conn.execute("create table jobs (id bigserial primary key, status text not null, created_at timestamptz not null, payload text)")
        conn.execute(
            "insert into jobs (status, created_at) select case when g > %s then 'pending' else 'done' end,"
            " timestamptz '2026-01-01' + g * interval '1 second' from generate_series(1, %s) g",
            (JOBS - PENDING, JOBS),
        )
        conn.execute("create index on jobs (status)")
        conn.execute("create index on jobs (created_at)")
        conn.execute("create table empty_table (id int primary key, label text)")
        conn.execute("create table events (id bigserial primary key, kind text not null)")
        conn.execute(
            "insert into events (kind) select case when g %% 1000 = 0 then 'alert' when g %% 2 = 0 then 'info' else 'debug' end"
            " from generate_series(1, %s) g order by random()",
            (EVENTS,),
        )
        conn.execute("create table deliveries (id bigserial primary key, event_id bigint not null, target text)")
        conn.execute(
            "insert into deliveries (event_id, target) select 1 + (g::bigint * 7919) %% %s, 'hook' from generate_series(1, %s) g",
            (EVENTS, 2 * EVENTS),
        )
        conn.execute("create index on events (kind)")
        conn.execute("create index on deliveries (event_id)")
        conn.execute("analyze")
    yield test_dsn
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f"drop database if exists {TEST_DB} with (force)")


@pytest.fixture
def conn(dsn):
    with psycopg.connect(dsn) as connection:
        yield connection
        connection.rollback()


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


@pytest.fixture(scope="session")
def stats_dsns():
    try:
        admin = psycopg.connect(STATS_ADMIN_DSN, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as error:
        _unavailable(f"no Postgres with pg_stat_statements for these tests (set PLANCLIFF_TEST_STATS_DSN): {error}")
    with admin:
        if "pg_stat_statements" not in admin.execute("show shared_preload_libraries").fetchone()[0]:
            _unavailable("pg_stat_statements is not in shared_preload_libraries of PLANCLIFF_TEST_STATS_DSN")
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
