import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

ADMIN_DSN = os.environ.get("PLANCLIFF_TEST_DSN", "postgresql://postgres:p@localhost:55432/postgres")
TEST_DB = "plancliff_test"
JOBS = 300_000
PENDING = 300


@pytest.fixture(scope="session")
def dsn() -> str:
    try:
        admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as error:
        pytest.skip(f"no Postgres for the database tests (set PLANCLIFF_TEST_DSN): {error}")
    with admin:
        admin.execute(f"drop database if exists {TEST_DB} with (force)")
        admin.execute(f"create database {TEST_DB}")
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
        conn.execute("analyze")
    yield test_dsn
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f"drop database if exists {TEST_DB} with (force)")


@pytest.fixture
def conn(dsn):
    with psycopg.connect(dsn) as connection:
        yield connection
        connection.rollback()
