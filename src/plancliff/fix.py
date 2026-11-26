from dataclasses import dataclass
from enum import StrEnum

import psycopg

from plancliff.settings import Settings
from plancliff.verify import Replay, Verification, replay_prepared, replay_unprepared, reset


class Method(StrEnum):
    SET_LOCAL = "set_local"
    UNPREPARED = "unprepared"


HINTS = {
    Method.SET_LOCAL: "SET LOCAL plan_cache_mode = force_custom_plan;  -- in the same transaction, just before this query",
    Method.UNPREPARED: "never prepare this query; with psycopg 3: cursor.execute(query, params, prepare=False)",
}
BROAD_FIX = "ALTER ROLE <app role> SET plan_cache_mode = force_custom_plan  -- every query of the role pays planning, +78% on a 4-table join"


@dataclass(frozen=True)
class Fix:
    method: Method
    hint: str
    calls: int = 0
    after_ms: float = 0.0
    generic_plans: int | None = None
    works: bool = False
    error: str = ""


def _judge(method: Method, replay: Replay, baseline: Verification, settings: Settings) -> Fix:
    works = not settings.is_slowdown(replay.after_ms, baseline.before_ms) and not replay.generic_plans
    return Fix(method, HINTS[method], len(replay.timings), replay.after_ms, replay.generic_plans, works)


def check_fixes(conn: psycopg.Connection, query: str, values: tuple[str, ...], baseline: Verification, settings: Settings) -> tuple[Fix, ...]:
    """check_fixes replays a confirmed cliff with each targeted fix; a fix works when calls 7-20 no longer fall off the cliff."""
    replays = {
        Method.SET_LOCAL: lambda: replay_prepared(conn, query, values, "force_custom_plan", settings),
        Method.UNPREPARED: lambda: replay_unprepared(conn, query, values, settings),
    }
    fixes = []
    for method, replay in replays.items():
        try:
            fixes.append(_judge(method, replay(), baseline, settings))
        except Exception as error:
            fixes.append(Fix(method, HINTS[method], error=(str(error).strip().splitlines() or [type(error).__name__])[0]))
        finally:
            reset(conn)
    return tuple(fixes)
