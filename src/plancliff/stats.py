from dataclasses import dataclass, replace

import psycopg
from pglast import parse_sql
from pglast.visitors import Visitor
from psycopg import sql

from plancliff.candidates import INTEGER_TYPES
from plancliff.parameters import parameter_columns
from plancliff.scan import DEFAULT_INTEGER, Finding, Verdict, scan_query
from plancliff.settings import Settings
from plancliff.verify import reset

TYPES_STATEMENT = "plancliff_types"
NAME_WIDTH = 60
SEVERITY = {Verdict.CLIFF: 3, Verdict.LATENT: 2, Verdict.OK: 1, Verdict.ERROR: 0}
READ = """
select queryid, calls, total_exec_time, query
  from pg_stat_statements
 where dbid = (select oid from pg_database where datname = current_database())
   and toplevel
   and query ~* '^\\s*(select|insert|update|delete|with|merge)\\M'
   and query ~ '\\$[0-9]'
   and query !~* '(\\mpg_|\\minformation_schema\\M)'
 order by total_exec_time desc
 limit %s
"""


HIDDEN = """
select count(*)
  from pg_stat_statements
 where dbid = (select oid from pg_database where datname = current_database())
   and query = '<insufficient privilege>'
"""


class StatsUnavailable(Exception):
    pass


@dataclass(frozen=True)
class StatQuery:
    queryid: int
    calls: int
    total_ms: float
    sql: str

    @property
    def name(self) -> str:
        text = " ".join(self.sql.split())
        return f"{text[:NAME_WIDTH] + '…' if len(text) > NAME_WIDTH else text}  [{self.calls} calls, queryid {self.queryid}]"


@dataclass(frozen=True)
class StatsRead:
    queries: list[StatQuery]
    hidden: int


def read_stat_queries(conn: psycopg.Connection, top: int) -> StatsRead:
    """read_stat_queries returns the application's queries, costliest first, and how many the role may not read; raises StatsUnavailable."""
    if not conn.execute("select 1 from pg_extension where extname = 'pg_stat_statements'").fetchone():
        raise StatsUnavailable("pg_stat_statements is not installed in this database: run CREATE EXTENSION pg_stat_statements;")
    try:
        rows = conn.execute(READ, (top,)).fetchall()
        hidden = conn.execute(HIDDEN).fetchone()[0]
    except psycopg.Error as error:
        raise StatsUnavailable(f"pg_stat_statements cannot be read: {str(error).strip().splitlines()[0]}") from error
    finally:
        conn.rollback()
    return StatsRead([StatQuery(*row) for row in rows], hidden)


class _Params(Visitor):
    def __init__(self) -> None:
        self.found: list[tuple[int, int]] = []

    def visit_ParamRef(self, ancestors, node):
        self.found.append((node.location, node.number))


def _parameter_types(conn: psycopg.Connection, query: str) -> list[str]:
    try:
        conn.execute(sql.SQL("prepare {} as {}").format(sql.Identifier(TYPES_STATEMENT), sql.SQL(query)))
        return conn.execute("select parameter_types::text[] from pg_prepared_statements where name = %s", (TYPES_STATEMENT,)).fetchone()[0]
    finally:
        reset(conn)


def constant_form(conn: psycopg.Connection, query: str) -> tuple[str, str] | None:
    """constant_form turns integer parameters without a column back into constants, renumbering the others; None when there are none."""
    bound = parameter_columns(query)
    types = _parameter_types(conn, query)
    inlined = [n for n, type_name in enumerate(types, start=1) if n not in bound and type_name in INTEGER_TYPES]
    if not inlined:
        return None
    kept = [n for n in range(1, len(types) + 1) if n not in inlined]
    renumber = {old: new for new, old in enumerate(kept, start=1)}
    finder = _Params()
    finder(parse_sql(query))
    text = query
    for location, number in sorted(set(finder.found), reverse=True):
        token = f"${number}"
        replacement = str(DEFAULT_INTEGER) if number in inlined else f"${renumber[number]}"
        text = text[:location] + replacement + text[location + len(token):]
    names = ", ".join(f"${n}" for n in inlined)
    return text, f"{names} also tried as the constant {DEFAULT_INTEGER}: pg_stat_statements does not tell constants from parameters"


def hidden_message(hidden: int) -> str:
    return (
        f"{hidden} statements of other roles are hidden from this role, so it cannot tell which are application queries: "
        "GRANT pg_read_all_stats TO <this role>; lets it read them"
    )


def scan_stat_query(conn: psycopg.Connection, stat: StatQuery, settings: Settings) -> Finding:
    """scan_stat_query scans the stored text and, when it hides constants, their constant form too, and keeps the worse verdict."""
    finding = scan_query(conn, stat.name, stat.sql, settings)
    try:
        variant = constant_form(conn, stat.sql)
    except Exception:
        return finding
    if variant is None:
        return finding
    text, note = variant
    other = scan_query(conn, stat.name, text, settings)
    if SEVERITY[other.verdict] > SEVERITY[finding.verdict]:
        return replace(other, note=note, seconds=finding.seconds + other.seconds)
    return replace(finding, seconds=finding.seconds + other.seconds)
