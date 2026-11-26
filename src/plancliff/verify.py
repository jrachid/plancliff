import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import psycopg
from psycopg import pq, sql

from plancliff.settings import Settings

STATEMENT = "plancliff_verify"
BEFORE = slice(1, 5)
AFTER = slice(6, None)


@dataclass(frozen=True)
class Replay:
    timings: tuple[float, ...]
    generic_plans: int | None
    custom_plans: int | None
    switched_at: int | None

    @property
    def before_ms(self) -> float:
        return statistics.median(self.timings[BEFORE])

    @property
    def after_ms(self) -> float:
        return statistics.median(self.timings[AFTER])


@dataclass(frozen=True)
class Verification:
    calls: int
    generic_plans: int
    custom_plans: int
    switched_at: int | None
    before_ms: float
    after_ms: float
    confirmed: bool


def reset(conn: psycopg.Connection) -> None:
    """reset rolls back the current transaction and drops every prepared statement of the session."""
    conn.rollback()
    conn.execute("deallocate all")
    conn.rollback()


def _plan_counts(conn: psycopg.Connection) -> tuple[int, int]:
    return conn.execute("select generic_plans, custom_plans from pg_prepared_statements where name = %s", (STATEMENT,)).fetchone()


def _timed(calls: int, run: Callable[[], None], after_each: Callable[[], bool] = lambda: False) -> tuple[list[float], int | None]:
    timings, first_hit = [], None
    for number in range(1, calls + 1):
        started = time.perf_counter()
        run()
        timings.append((time.perf_counter() - started) * 1000)
        if first_hit is None and after_each():
            first_hit = number
    return timings, first_hit


def _start(conn: psycopg.Connection, settings: Settings) -> None:
    if settings.verify_calls < AFTER.start + 1:
        raise ValueError(f"verify_calls must be at least {AFTER.start + 1}")
    conn.execute("select set_config('statement_timeout', %s, true)", (f"{int(settings.timeout_s * 1000)}ms",))


def replay_prepared(conn: psycopg.Connection, query: str, values: Sequence[str], mode: str, settings: Settings) -> Replay:
    """replay_prepared prepares the query afresh and calls it verify_calls times under plan_cache_mode `mode`, in the caller's transaction."""
    _start(conn, settings)
    conn.execute("select set_config('plan_cache_mode', %s, true)", (mode,))
    conn.execute("deallocate all")
    conn.execute(sql.SQL("prepare {} as {}").format(sql.Identifier(STATEMENT), sql.SQL(query)))
    call = sql.SQL("execute {}({})").format(sql.Identifier(STATEMENT), sql.SQL(", ").join(map(sql.Literal, values)))
    timings, switched_at = _timed(settings.verify_calls, lambda: conn.execute(call), lambda: _plan_counts(conn)[0] > 0)
    generic, custom = _plan_counts(conn)
    return Replay(tuple(timings), generic, custom, switched_at)


def replay_unprepared(conn: psycopg.Connection, query: str, values: Sequence[str], settings: Settings) -> Replay:
    """replay_unprepared sends the query verify_calls times as an unnamed statement, the path of psycopg's prepare=False."""
    _start(conn, settings)
    params = [value.encode() for value in values]

    def run() -> None:
        result = conn.pgconn.exec_params(query.encode(), params)
        if result.status not in (pq.ExecStatus.TUPLES_OK, pq.ExecStatus.COMMAND_OK):
            raise psycopg.DatabaseError(str(result.get_error_message()).removeprefix("ERROR:").strip())

    timings, _ = _timed(settings.verify_calls, run)
    return Replay(tuple(timings), None, None, None)


def verify(conn: psycopg.Connection, query: str, values: Sequence[str], settings: Settings) -> Verification:
    """verify replays the query in auto mode, as a driver would, and confirms the cliff when Postgres switches and slows down."""
    replay = replay_prepared(conn, query, values, "auto", settings)
    return Verification(
        calls=settings.verify_calls, generic_plans=replay.generic_plans, custom_plans=replay.custom_plans,
        switched_at=replay.switched_at, before_ms=replay.before_ms, after_ms=replay.after_ms,
        confirmed=replay.generic_plans > 0 and settings.is_slowdown(replay.after_ms, replay.before_ms),
    )
