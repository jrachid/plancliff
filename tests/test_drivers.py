import json

import pytest

from plancliff.cli import EXIT_CLIFF, main
from plancliff.fix import UNPREPARED_HINTS

QUEUE = "select id from jobs where status = $1 order by created_at limit 10"


@pytest.fixture
def queries(tmp_path):
    path = tmp_path / "queries.sql"
    path.write_text(f"-- queue\n{QUEUE}\n")
    return str(path)


@pytest.mark.parametrize(
    ("driver", "expected"),
    [
        ("psycopg", "prepare=False"),
        ("pgx", "pgx.QueryExecModeExec"),
        ("jdbc", "setPrepareThreshold(0)"),
        ("asyncpg", "statement_cache_size=0"),
    ],
)
def test_the_unprepared_fix_is_written_for_the_application_driver(dsn, queries, capsys, driver, expected):
    assert main(["scan", dsn, queries, "--driver", driver]) == EXIT_CLIFF
    output = capsys.readouterr().out
    assert expected in output
    assert output.count("fix ✓") == 2


def test_every_driver_has_its_own_wording():
    assert len(set(UNPREPARED_HINTS.values())) == len(UNPREPARED_HINTS) == 4


def test_the_json_report_records_the_driver(dsn, queries, capsys):
    main(["scan", dsn, queries, "--driver", "pgx", "--format", "json"])
    document = json.loads(capsys.readouterr().out)
    assert document["settings"]["driver"] == "pgx"
    assert "pgx.QueryExecModeExec" in document["queries"][0]["fixes"][1]["hint"]
