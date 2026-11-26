import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg
from psycopg import sql

from plancliff.settings import Settings

STATEMENT = "plancliff_verify"
BEFORE = slice(1, 5)
AFTER = slice(6, None)


@dataclass(frozen=True)
class Verification:
    calls: int
    generic_plans: int
    custom_plans: int
    switched_at: int | None
    before_ms: float
    after_ms: float
    confirmed: bool


def _generic_plans(conn: psycopg.Connection) -> tuple[int, int]:
    return conn.execute("select generic_plans, custom_plans from pg_prepared_statements where name = %s", (STATEMENT,)).fetchone()


def verify(conn: psycopg.Connection, query: str, values: Sequence[str], settings: Settings) -> Verification:
    """verify replays the query verify_calls times in auto mode, as a driver would, inside the caller's transaction."""
    if settings.verify_calls < AFTER.start + 1:
        raise ValueError(f"verify_calls must be at least {AFTER.start + 1}")
    conn.execute("select set_config('statement_timeout', %s, true)", (f"{int(settings.timeout_s * 1000)}ms",))
    conn.execute("select set_config('plan_cache_mode', 'auto', true)")
    conn.execute("deallocate all")
    conn.execute(sql.SQL("prepare {} as {}").format(sql.Identifier(STATEMENT), sql.SQL(query)))
    call = sql.SQL("execute {}({})").format(sql.Identifier(STATEMENT), sql.SQL(", ").join(map(sql.Literal, values)))
    timings, switched_at = [], None
    for number in range(1, settings.verify_calls + 1):
        started = time.perf_counter()
        conn.execute(call)
        timings.append((time.perf_counter() - started) * 1000)
        if switched_at is None and _generic_plans(conn)[0] > 0:
            switched_at = number
    generic, custom = _generic_plans(conn)
    before, after = statistics.median(timings[BEFORE]), statistics.median(timings[AFTER])
    return Verification(
        calls=settings.verify_calls, generic_plans=generic, custom_plans=custom, switched_at=switched_at,
        before_ms=before, after_ms=after, confirmed=generic > 0 and settings.is_slowdown(after, before),
    )
