import json
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum

import psycopg
from psycopg import sql

from plancliff.candidates import candidates
from plancliff.parameters import parameter_columns

RATIO_THRESHOLD = 10.0
MIN_GAP_MS = 5.0
RUNS = 3
DEFAULT_INTEGER = 100
STATEMENT = "plancliff_probe"
INTEGER_TYPES = {"smallint", "integer", "bigint"}


class Verdict(StrEnum):
    CLIFF = "cliff"
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True)
class Settings:
    ratio_threshold: float = RATIO_THRESHOLD
    min_gap_ms: float = MIN_GAP_MS
    runs: int = RUNS
    timeout_s: float = 30.0


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
    is_cliff = worst.ratio >= settings.ratio_threshold and worst.generic_ms - worst.custom_ms >= settings.min_gap_ms
    return replace(worst, verdict=Verdict.CLIFF if is_cliff else Verdict.OK)


def scan_query(conn: psycopg.Connection, name: str, query: str, settings: Settings = Settings()) -> Finding:
    """scan_query compares generic and custom plans inside a transaction it always rolls back; failures become an ERROR finding."""
    if conn.autocommit:
        raise ValueError("scan_query needs a connection with autocommit off, or measured writes would be committed")
    started = time.perf_counter()
    try:
        finding = _measure(conn, name, query, settings)
    except Exception as error:
        finding = Finding(name=name, sql=query, verdict=Verdict.ERROR, error=str(error).splitlines()[0])
    finally:
        conn.rollback()
        conn.execute("deallocate all")
        conn.rollback()
    return replace(finding, seconds=time.perf_counter() - started)
