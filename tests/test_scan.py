import psycopg
import pytest

from plancliff import Verdict, scan_query
from plancliff.cli import EXIT_CLIFF, EXIT_OK, EXIT_USAGE, main

QUEUE = "select id from jobs where status = $1 order by created_at limit 10"
BY_KEY = "select id, status from jobs where id = $1"


def test_a_queue_read_on_a_rare_status_is_reported_as_a_cliff(conn):
    finding = scan_query(conn, "queue", QUEUE)
    assert finding.verdict is Verdict.CLIFF, finding
    assert finding.ratio >= 10
    assert finding.values == ("pending",)


def test_a_read_by_primary_key_is_not_a_cliff(conn):
    assert scan_query(conn, "by key", BY_KEY).verdict is Verdict.OK


def test_a_measured_delete_leaves_the_table_untouched(conn):
    before = conn.execute("select count(*) from jobs").fetchone()[0]
    conn.rollback()
    finding = scan_query(conn, "delete", "delete from jobs where status = $1 and id < 1000")
    assert finding.verdict is not Verdict.ERROR, finding
    assert conn.execute("select count(*) from jobs").fetchone()[0] == before


def test_an_integer_parameter_without_column_gets_a_default_value(conn):
    finding = scan_query(conn, "limit", "select id from jobs where status = $1 order by created_at limit $2")
    assert finding.verdict is not Verdict.ERROR, finding
    assert finding.values == ("pending", "100")


def test_a_text_parameter_without_column_is_an_error_asking_for_a_value(conn):
    finding = scan_query(conn, "no column", "select $1::text || 'x'")
    assert finding.verdict is Verdict.ERROR
    assert "value must be supplied" in finding.error


def test_an_empty_table_is_an_error_and_the_scan_goes_on(conn):
    assert scan_query(conn, "empty", "select id from empty_table where label = $1").verdict is Verdict.ERROR
    assert scan_query(conn, "by key", BY_KEY).verdict is Verdict.OK


def test_a_query_slower_than_the_timeout_is_an_error_not_a_hang(conn):
    finding = scan_query(conn, "slow", "select pg_sleep(2) from jobs where id = $1", settings=_settings(timeout_s=0.2))
    assert finding.verdict is Verdict.ERROR
    assert "timeout" in finding.error


def test_an_autocommit_connection_is_refused_so_writes_cannot_be_committed(dsn):
    with psycopg.connect(dsn, autocommit=True) as autocommit, pytest.raises(ValueError):
        scan_query(autocommit, "delete", "delete from jobs where id = $1")


def test_the_command_exits_with_1_when_a_cliff_is_found(dsn, tmp_path, capsys):
    queries = tmp_path / "queries.sql"
    queries.write_text(f"-- queue\n{QUEUE}\n\n-- by key\n{BY_KEY}\n")
    assert main(["scan", dsn, str(queries)]) == EXIT_CLIFF
    output = capsys.readouterr().out
    assert "CLIFF" in output and "queue" in output and "pending" in output
    assert "2 queries" in output and "1 cliff, 0 latent, 1 ok, 0 error" in output


def test_the_command_exits_with_0_when_every_query_is_fine(dsn, tmp_path):
    queries = tmp_path / "queries.sql"
    queries.write_text(f"{BY_KEY}\n")
    assert main(["scan", dsn, str(queries)]) == EXIT_OK


def test_a_missing_file_or_an_unreachable_database_is_a_usage_error(dsn, tmp_path):
    assert main(["scan", dsn, str(tmp_path / "absent.sql")]) == EXIT_USAGE
    queries = tmp_path / "queries.sql"
    queries.write_text(f"{BY_KEY}\n")
    assert main(["scan", "postgresql://nobody@localhost:1/none?connect_timeout=1", str(queries)]) == EXIT_USAGE


def _settings(**overrides):
    from plancliff.settings import Settings

    return Settings(**overrides)


def test_piping_the_report_into_head_ends_quietly(dsn, tmp_path):
    import subprocess
    import sys

    queries = tmp_path / "queries.sql"
    queries.write_text("\n\n".join([QUEUE, BY_KEY] * 4) + "\n")
    script = f"{sys.executable} -m plancliff.cli scan '{dsn}' {queries} -v | head -1"
    result = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=120, check=False)
    assert result.stdout.count("\n") == 1
    assert "Traceback" not in result.stderr and "BrokenPipeError" not in result.stderr, result.stderr
