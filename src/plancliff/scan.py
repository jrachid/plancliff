import json
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum

import psycopg
from psycopg import sql

from plancliff.candidates import INTEGER_TYPES, candidates, fresh_value, unique_columns
from plancliff.fix import Fix, check_fixes
from plancliff.parameters import Column, is_insert, parameter_columns
from plancliff.settings import Settings
from plancliff.verify import SAVEPOINT, Verification, reset, verify

DEFAULT_INTEGER = 100
DEFAULT_SETTINGS = Settings()
STATEMENT = "plancliff_probe"
VARIED = "varied "


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
        conn.execute(f"savepoint {SAVEPOINT}")
        plan = conn.execute(explain).fetchone()[0]
        conn.execute(f"rollback to savepoint {SAVEPOINT}")
        plan = json.loads(plan) if isinstance(plan, str) else plan
        timings.append(float(plan[0]["Execution Time"]))
    return min(timings[1:])


def _values_per_scenario(conn: psycopg.Connection, query: str) -> dict[str, list]:
    columns = parameter_columns(query)
    tried = {number: candidates(conn, column) for number, column in columns.items()}
    types = conn.execute("select parameter_types::text[] from pg_prepared_statements where name = %s", (STATEMENT,)).fetchone()[0]
    keys = {number: column for number, column in columns.items() if column.name in unique_columns(conn, column)} if is_insert(query) else {}
    frequent, rare = [], []
    for number, type_name in enumerate(types, start=1):
        fresh = fresh_value(conn, keys[number], type_name) if number in keys else None
        if fresh is not None:
            frequent.append(fresh)
            rare.append(fresh)
        elif number in tried:
            frequent.append(tried[number].frequent)
            rare.append(tried[number].rare)
        elif type_name in INTEGER_TYPES:
            frequent.append(DEFAULT_INTEGER)
            rare.append(DEFAULT_INTEGER)
        else:
            raise MissingValue(f"${number} ({type_name}) matches no column: a value must be supplied")
    scenarios = {"frequent": frequent, "rare": rare}
    for column, numbers in _repeated_columns(columns, keys).items():
        common = tried[numbers[0]].common
        if len(common) >= 2:
            varied = list(frequent)
            for position, number in enumerate(numbers):
                varied[number - 1] = common[position % len(common)]
            scenarios[f"{VARIED}{column.name}"] = varied
    return scenarios


def _repeated_columns(columns: dict[int, Column], keys: dict[int, Column]) -> dict[Column, list[int]]:
    numbers_by_column: dict[Column, list[int]] = {}
    for number in sorted(columns):
        if number not in keys:
            numbers_by_column.setdefault(columns[number], []).append(number)
    return {column: numbers for column, numbers in numbers_by_column.items() if len(numbers) >= 2}


def _measure(conn: psycopg.Connection, name: str, query: str, settings: Settings) -> Finding:
    conn.execute("select set_config('statement_timeout', %s, true)", (f"{int(settings.timeout_s * 1000)}ms",))
    conn.execute("deallocate all")
    conn.execute(sql.SQL("prepare {} as {}").format(sql.Identifier(STATEMENT), sql.SQL(query)))
    worst, worst_rank = Finding(name=name, sql=query, verdict=Verdict.OK), None
    for scenario, values in _values_per_scenario(conn, query).items():
        generic = _execution_ms(conn, "force_generic_plan", values, settings.runs)
        custom = _execution_ms(conn, "force_custom_plan", values, settings.runs)
        ratio = generic / max(custom, 0.001)
        rank = (settings.is_slowdown(generic, custom), generic - custom)
        if worst_rank is None or rank > worst_rank:
            worst_rank = rank
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


def scan_query(conn: psycopg.Connection, name: str, query: str, settings: Settings = DEFAULT_SETTINGS) -> Finding:
    """scan_query measures, verifies each cliff and proves its fixes, in transactions it always rolls back; failures become ERROR findings."""
    if conn.autocommit:
        raise ValueError("scan_query needs a connection with autocommit off, or measured writes would be committed")
    started = time.perf_counter()
    # psycopg answers any ROLLBACK, savepoints included, with DEALLOCATE ALL once it has prepared a statement itself.
    threshold, conn.prepare_threshold = conn.prepare_threshold, None
    try:
        try:
            finding = _measure(conn, name, query, settings)
        except Exception as error:
            finding = Finding(name=name, sql=query, verdict=Verdict.ERROR, error=_first_line(error))
        finally:
            reset(conn)
        if finding.verdict is Verdict.CLIFF and settings.verify:
            finding = _verify(conn, finding, settings)
    finally:
        conn.prepare_threshold = threshold
    return replace(finding, seconds=time.perf_counter() - started)
