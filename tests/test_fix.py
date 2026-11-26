import json

from plancliff import Settings, Verdict, scan_query
from plancliff.cli import EXIT_CLIFF, main
from plancliff.fix import Method

QUEUE = "select id from jobs where status = $1 order by created_at limit 10"
JOIN = "select count(*) from events e join deliveries d on d.event_id = e.id where e.kind = $1"
DEQUEUE = "delete from jobs where id in (select id from jobs where status = $1 order by created_at limit 10) returning id, $1::text"


def test_a_confirmed_cliff_gets_both_targeted_fixes_and_both_are_proven(conn):
    finding = scan_query(conn, "queue", QUEUE)
    assert finding.verdict is Verdict.CLIFF
    fixes = {fix.method: fix for fix in finding.fixes}
    assert set(fixes) == {Method.SET_LOCAL, Method.UNPREPARED}
    assert all(fix.works and not fix.error for fix in fixes.values()), fixes
    assert fixes[Method.SET_LOCAL].generic_plans == 0
    assert fixes[Method.UNPREPARED].generic_plans is None
    assert fixes[Method.SET_LOCAL].after_ms * 10 < finding.verification.after_ms


def test_a_parameter_used_twice_is_fixed_through_the_unprepared_path_too(conn):
    finding = scan_query(conn, "dequeue", DEQUEUE)
    assert finding.verdict is Verdict.CLIFF, finding
    assert all(fix.works for fix in finding.fixes), finding.fixes


def test_forty_more_fixed_deletes_still_leave_the_table_untouched(conn):
    before = conn.execute("select count(*) from jobs").fetchone()[0]
    conn.rollback()
    finding = scan_query(conn, "dequeue", DEQUEUE)
    assert len(finding.fixes) == 2 and all(fix.calls == 20 for fix in finding.fixes)
    assert conn.execute("select count(*) from jobs").fetchone()[0] == before


def test_latent_and_unverified_cliffs_get_no_fix(conn):
    assert scan_query(conn, "join", JOIN).fixes == ()
    unverified = scan_query(conn, "queue", QUEUE, Settings(verify=False))
    assert unverified.verdict is Verdict.CLIFF and unverified.fixes == ()


def test_the_text_report_shows_each_proven_fix_and_the_broad_one_once(dsn, tmp_path, capsys):
    queries = tmp_path / "queries.sql"
    queries.write_text(f"-- queue\n{QUEUE}\n\n-- dequeue\n{DEQUEUE}\n")
    assert main(["scan", dsn, str(queries)]) == EXIT_CLIFF
    output = capsys.readouterr().out
    assert output.count("fix ✓ SET LOCAL plan_cache_mode = force_custom_plan;") == 2
    assert output.count("prepare=False") == 2
    assert output.count("ALTER ROLE") == 1


def test_the_json_report_carries_the_fixes(dsn, tmp_path, capsys):
    queries = tmp_path / "queries.sql"
    queries.write_text(f"-- queue\n{QUEUE}\n")
    main(["scan", dsn, str(queries), "--format", "json"])
    fixes = json.loads(capsys.readouterr().out)["queries"][0]["fixes"]
    assert [fix["method"] for fix in fixes] == ["set_local", "unprepared"]
    assert all(fix["works"] for fix in fixes)
