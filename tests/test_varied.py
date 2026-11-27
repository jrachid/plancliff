from plancliff import Verdict, scan_query
from plancliff.report import text_line
from plancliff.style import Style

ROWS = 6
PRE_CHECK = (
    "select * from tuple where store = $1 and (object_type, object_id, relation, _user, user_type) in ("
    + ", ".join(f"(${2 + 5 * k}, ${3 + 5 * k}, ${4 + 5 * k}, ${5 + 5 * k}, ${6 + 5 * k})" for k in range(ROWS))
    + ") for update"
)


def test_a_pre_check_spread_over_several_usersets_is_measured_at_its_worst(conn):
    finding = scan_query(conn, "pre-check", PRE_CHECK)
    assert finding.verdict is Verdict.CLIFF, finding
    assert finding.scenario == "varied _user", finding
    usersets = {value for value in finding.values if value.startswith("group:")}
    assert len(usersets) == 4, finding.values
    assert "_user varied across parameters" in text_line(finding, Style(False))


def test_a_query_with_one_parameter_per_column_is_never_varied(conn):
    finding = scan_query(conn, "queue", "select id from jobs where status = $1 order by created_at limit 10")
    assert finding.scenario in ("frequent", "rare"), finding
