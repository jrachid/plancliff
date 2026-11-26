import json
import re

import pytest

from plancliff import Settings, Verdict, scan_query
from plancliff.cli import EXIT_CLIFF, EXIT_OK, main
from plancliff.verify import verify

QUEUE = "select id from jobs where status = $1 order by created_at limit 10"
JOIN = "select count(*) from events e join deliveries d on d.event_id = e.id where e.kind = $1"


def test_a_queue_cliff_is_confirmed_because_postgres_switches_at_the_sixth_prepared_call(conn):
    finding = scan_query(conn, "queue", QUEUE)
    assert finding.verdict is Verdict.CLIFF, finding
    v = finding.verification
    assert v.confirmed and v.switched_at == 6
    assert v.generic_plans == 15 and v.custom_plans == 5
    assert v.after_ms >= 10 * v.before_ms


def test_a_join_whose_generic_plan_postgres_never_picks_is_latent_not_a_cliff(conn):
    finding = scan_query(conn, "join", JOIN)
    assert finding.verdict is Verdict.LATENT, finding
    assert finding.ratio >= 10
    assert finding.verification.generic_plans == 0 and finding.verification.custom_plans == 20
    assert finding.verification.switched_at is None


def test_without_verification_the_same_join_counts_as_a_cliff(conn):
    finding = scan_query(conn, "join", JOIN, Settings(verify=False))
    assert finding.verdict is Verdict.CLIFF and finding.verification is None


def test_twenty_verified_deletes_leave_the_table_untouched(conn):
    before = conn.execute("select count(*) from jobs").fetchone()[0]
    conn.rollback()
    finding = scan_query(conn, "dequeue", f"delete from jobs where id in ({QUEUE})")
    assert finding.verdict is Verdict.CLIFF and finding.verification.confirmed, finding
    assert conn.execute("select count(*) from jobs").fetchone()[0] == before


def test_verification_needs_enough_calls_to_see_the_switch(conn):
    with pytest.raises(ValueError):
        verify(conn, QUEUE, ("pending",), Settings(verify_calls=6))


def test_a_latent_query_alone_does_not_fail_the_run(dsn, tmp_path, capsys):
    queries = tmp_path / "queries.sql"
    queries.write_text(f"-- join\n{JOIN}\n")
    assert main(["scan", dsn, str(queries)]) == EXIT_OK
    output = capsys.readouterr().out
    assert "LATENT" in output and "kept the custom plan for 20/20 calls" in output
    assert main(["scan", dsn, str(queries), "--no-verify"]) == EXIT_CLIFF


def test_the_text_report_says_when_postgres_switched(dsn, tmp_path, capsys):
    queries = tmp_path / "queries.sql"
    queries.write_text(f"-- queue\n{QUEUE}\n")
    assert main(["scan", dsn, str(queries)]) == EXIT_CLIFF
    assert "confirmed: Postgres switched to the generic plan at prepared call 6 (15/20 generic)" in capsys.readouterr().out


def test_the_json_report_carries_every_query_its_verification_and_no_colour(dsn, tmp_path, capsys):
    queries = tmp_path / "queries.sql"
    queries.write_text(f"-- queue\n{QUEUE}\n\n-- join\n{JOIN}\n\n-- by key\nselect id from jobs where id = $1\n\n-- empty\nselect id from empty_table where label = $1\n")
    assert main(["scan", dsn, str(queries), "--format", "json", "--color", "always"]) == EXIT_CLIFF
    raw = capsys.readouterr().out
    assert not re.search(r"\033\[", raw)
    document = json.loads(raw)
    assert document["format"] == 1
    assert [q["verdict"] for q in document["queries"]] == ["cliff", "latent", "ok", "error"]
    assert document["queries"][0]["verification"]["switched_at"] == 6
    assert document["queries"][2]["verification"] is None
    assert document["summary"] | {"seconds": 0} == {"queries": 4, "cliff": 1, "latent": 1, "ok": 1, "error": 1, "seconds": 0}
