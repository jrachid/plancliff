import psycopg
import pytest

from plancliff import Verdict, scan_query


@pytest.fixture(scope="module")
def keyed_tables(dsn):
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("create table accounts (id integer primary key, email text unique not null, note text)")
        conn.execute("insert into accounts select g, 'user' || g || '@example.com', 'n' from generate_series(1, 1000) g")
        conn.execute("create table queue_data (namespace_id bytea, queue_name text, data text, primary key (namespace_id, queue_name))")
        conn.execute("insert into queue_data select int4send(g), 'q' || g, 'd' from generate_series(1, 1000) g")
        conn.execute("analyze accounts, queue_data")
    yield
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("drop table accounts, queue_data")


def test_an_insert_on_taken_keys_gets_fresh_values_instead_of_an_error(conn, keyed_tables):
    finding = scan_query(conn, "insert", "insert into accounts (id, email, note) values ($1, $2, $3)")
    assert finding.verdict is not Verdict.ERROR, finding
    assert int(finding.values[0]) > 1000
    assert finding.values[1].startswith("plancliff-")


def test_a_composite_bytea_and_text_key_gets_fresh_values_too(conn, keyed_tables):
    finding = scan_query(conn, "insert", "insert into queue_data (namespace_id, queue_name, data) values ($1, $2, $3)")
    assert finding.verdict is not Verdict.ERROR, finding


def test_measured_inserts_leave_the_table_as_it_was(conn, keyed_tables):
    before = conn.execute("select count(*), max(id) from accounts").fetchone()
    conn.rollback()
    scan_query(conn, "insert", "insert into accounts (id, email, note) values ($1, $2, $3)")
    assert conn.execute("select count(*), max(id) from accounts").fetchone() == before


def test_a_connection_that_prepares_everything_does_not_lose_the_probe(dsn):
    many_params = "select id from jobs where status = $1 and id > $2 and id < $3 and created_at > $4 order by created_at limit $5"
    with psycopg.connect(dsn, prepare_threshold=0) as connection:
        finding = scan_query(connection, "many", many_params)
        assert finding.verdict is not Verdict.ERROR, finding
        assert connection.prepare_threshold == 0
