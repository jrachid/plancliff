import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from plancliff import Verdict, scan_query
from plancliff.cli import EXIT_CLIFF, EXIT_OK, EXIT_USAGE, main
from plancliff.guard import other_sessions
from plancliff.stats import read_stat_queries

from .conftest import ADMIN_DSN, STATS_ADMIN_DSN

BY_KEY = "select id, status from jobs where id = $1"
READER = "plancliff_test_reader"


@pytest.fixture
def queries(tmp_path):
    path = tmp_path / "queries.sql"
    path.write_text(f"{BY_KEY}\n")
    return str(path)


@pytest.fixture
def reader(dsn):
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f"drop role if exists {READER}")
        admin.execute(f"create role {READER} login password 'r'")
    yield make_conninfo(dsn, user=READER, password="r")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f"drop role if exists {READER}")


def test_a_database_another_application_is_connected_to_is_refused(dsn, queries, capsys):
    with psycopg.connect(dsn, application_name="billing-api"):
        assert main(["scan", dsn, queries]) == EXIT_USAGE
    message = capsys.readouterr().err
    assert "1 other session(s)" in message and "billing-api" in message and "--allow-busy" in message and "--stats-from" in message


def test_allow_busy_scans_anyway(dsn, queries):
    with psycopg.connect(dsn, application_name="billing-api"):
        assert main(["scan", dsn, queries, "--allow-busy"]) == EXIT_OK


def test_once_the_application_disconnects_the_scan_runs(dsn, queries):
    with psycopg.connect(dsn, application_name="billing-api"):
        pass
    assert main(["scan", dsn, queries]) == EXIT_OK


def test_other_plancliff_sessions_do_not_count(dsn):
    with psycopg.connect(dsn, application_name="plancliff"), psycopg.connect(dsn) as conn:
        assert other_sessions(conn) == []


def test_an_unprivileged_role_still_sees_an_application_session(dsn, reader):
    with psycopg.connect(dsn, application_name="billing-api"), psycopg.connect(reader) as conn:
        sessions = other_sessions(conn)
    assert [(s.user, s.application) for s in sessions] == [(conninfo_to_dict(dsn)["user"], "billing-api")]


def test_a_cte_dequeue_is_a_confirmed_cliff(conn):
    query = "with q as (select id from jobs where status = $1 order by created_at limit 10) delete from jobs where id in (select id from q) returning $1::text"
    finding = scan_query(conn, "cte", query)
    assert finding.verdict is Verdict.CLIFF, finding
    assert finding.values == ("pending",) and all(fix.works for fix in finding.fixes)


@pytest.fixture
def stats_reader(stats_dsns):
    production = stats_dsns[0]
    with psycopg.connect(STATS_ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f"drop role if exists {READER}")
        admin.execute(f"create role {READER} login password 'r'")
    yield production, make_conninfo(production, user=READER, password="r")
    with psycopg.connect(STATS_ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f"drop owned by {READER}")
        admin.execute(f"drop role if exists {READER}")


def test_queries_hidden_by_missing_rights_are_counted_and_reported(stats_reader, capsys):
    production, reader_dsn = stats_reader
    with psycopg.connect(reader_dsn) as conn:
        read = read_stat_queries(conn, 100)
    assert read.queries == [] and read.hidden >= 3
    assert main(["scan", production, "--stats-from", reader_dsn, "--allow-busy"]) == EXIT_USAGE
    message = capsys.readouterr().err
    assert f"{read.hidden} statements of other roles are hidden" in message and "GRANT pg_read_all_stats" in message


def test_granting_pg_read_all_stats_reveals_them(stats_reader):
    production, reader_dsn = stats_reader
    with psycopg.connect(STATS_ADMIN_DSN, autocommit=True) as admin:
        admin.execute(f"grant pg_read_all_stats to {READER}")
    with psycopg.connect(reader_dsn) as conn:
        read = read_stat_queries(conn, 100)
    assert read.hidden == 0
    assert "select id from jobs where status = $1 order by created_at limit $2" in [q.sql for q in read.queries]
    assert main(["scan", production, "--stats-from", reader_dsn, "--top", "1", "--allow-busy"]) == EXIT_CLIFF
