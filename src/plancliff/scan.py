import json
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum

import psycopg
from psycopg import sql

from plancliff.candidates import candidates
from plancliff.parameters import parameter_columns
from plancliff.settings import Settings
from plancliff.fix import Fix, check_fixes
from plancliff.verify import Verification, reset, verify

DEFAULT_INTEGER = 100
STATEMENT = "plancliff_probe"
INTEGER_TYPES = {"smallint", "integer", "bigint"}


class Verdict(StrEnum):
    CLIFF = "cliff"
    LATENT = "latent"
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True)
class Finding:
    name: str
    sql: str
    verdict: Verdict
    ratio: float = 0.0
    scenario: str = ""
    generic_ms: float = 0.0
    custom_ms: float = 0.0
    values: tuple[str, ...] = ()
    error: str = ""
    verification: Verification | None = None
    verification_error: str = ""
    fixes: tuple[Fix, ...] = ()
    note: str = ""
    seconds: float = field(default=0.0, compare=False)


class MissingValue(Exception):
    pass


def _execution_ms(conn: psycopg.Connection, mode: str, values: list, runs: int) -> float:
    conn.execute("select set_config('plan_cache_mode', %s, true)", (mode,))
    explain = sql.SQL("explain (analyze, timing off, format json) execute {}({})").format(
        sql.Identifier(STATEMENT), sql.SQL(", ").join(map(sql.Literal, values))
    )
    timings = []
    for _ in range(1 + runs):
        plan = conn.execute(explain).fetchone()[0]
        plan = json.loads(plan) if isinstance(plan, str) else plan
        timings.append(float(plan[0]["Execution Time"]))
    return min(timings[1:])


def _values_per_scenario(conn: psycopg.Connection, query: str) -> dict[str, list]:
    tried = {number: candidates(conn, column) for number, column in parameter_columns(query).items()}
    types = conn.execute("select parameter_types::text[] from pg_prepared_statements where name = %s", (STATEMENT,)).fetchone()[0]
    frequent, rare = [], []
    for number, type_name in enumerate(types, start=1):
        if number in tried:
            frequent.append(tried[number].frequent)
            rare.append(tried[number].rare)
        elif type_name in INTEGER_TYPES:
            frequent.append(DEFAULT_INTEGER)
            rare.append(DEFAULT_INTEGER)
        else:
            raise MissingValue(f"${number} ({type_name}) matches no column: a value must be supplied")
    return {"frequent": frequent, "rare": rare}


def _measure(conn: psycopg.Connection, name: str, query: str, settings: Settings) -> Finding:
    conn.execute("select set_config('statement_timeout', %s, true)", (f"{int(settings.timeout_s * 1000)}ms",))
    conn.execute("deallocate all")
    conn.execute(sql.SQL("prepare {} as {}").format(sql.Identifier(STATEMENT), sql.SQL(query)))
    worst = Finding(name=name, sql=query, verdict=Verdict.OK)
    for scenario, values in _values_per_scenario(conn, query).items():
        generic = _execution_ms(conn, "force_generic_plan", values, settings.runs)
        custom = _execution_ms(conn, "force_custom_plan", values, settings.runs)
        ratio = generic / max(custom, 0.001)
        if ratio > worst.ratio:
            worst = Finding(
                name=name, sql=query, verdict=Verdict.OK, ratio=ratio, scenario=scenario,
                generic_ms=generic, custom_ms=custom, values=tuple(str(v) for v in values),
            )
    return replace(worst, verdict=Verdict.CLIFF if settings.is_slowdown(worst.generic_ms, worst.custom_ms) else Verdict.OK)


def _first_line(error: Exception) -> str:
    return (str(error).strip().splitlines() or [type(error).__name__])[0]


def _verify(conn: psycopg.Connection, finding: Finding, settings: Settings) -> Finding:
    try:
        verification = verify(conn, finding.sql, finding.values, settings)
    except Exception as error:
        return replace(finding, verification_error=_first_line(error))
    finally:
        reset(conn)
    if not verification.confirmed:
        return replace(finding, verification=verification, verdict=Verdict.LATENT)
    fixes = check_fixes(conn, finding.sql, finding.values, verification, settings)
    return replace(finding, verification=verification, verdict=Verdict.CLIFF, fixes=fixes)


def scan_query(conn: psycopg.Connection, name: str, query: str, settings: Settings = Settings()) -> Finding:
    """scan_query measures, verifies each cliff and proves its fixes, in transactions it always rolls back; failures become ERROR findings."""
    if conn.autocommit:
        raise ValueError("scan_query needs a connection with autocommit off, or measured writes would be committed")
    started = time.perf_counter()
    try:
        finding = _measure(conn, name, query, settings)
    except Exception as error:
        finding = Finding(name=name, sql=query, verdict=Verdict.ERROR, error=_first_line(error))
    finally:
        reset(conn)
    if finding.verdict is Verdict.CLIFF and settings.verify:
        finding = _verify(conn, finding, settings)
    return replace(finding, seconds=time.perf_counter() - started)
