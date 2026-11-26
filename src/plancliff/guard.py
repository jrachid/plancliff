from dataclasses import dataclass

import psycopg

APPLICATION_NAME = "plancliff"
OTHER_SESSIONS = """
select coalesce(usename, '?'), coalesce(nullif(application_name, ''), '?')
  from pg_stat_activity
 where datname = current_database()
   and pid <> pg_backend_pid()
   and usesysid is not null
   and (backend_type is null or backend_type = 'client backend')
   and application_name is distinct from %s
"""


@dataclass(frozen=True)
class Session:
    user: str
    application: str


def other_sessions(conn: psycopg.Connection) -> list[Session]:
    """other_sessions lists who else is connected to this database, as far as the role can see; plancliff's own sessions are left out."""
    try:
        return [Session(*row) for row in conn.execute(OTHER_SESSIONS, (APPLICATION_NAME,)).fetchall()]
    finally:
        conn.rollback()


def busy_message(sessions: list[Session]) -> str:
    seen = ", ".join(sorted({f"{s.user} ({s.application})" for s in sessions}))
    return (
        f"{len(sessions)} other session(s) connected to this database: {seen}. "
        "Measuring writes and FOR UPDATE reads locks rows while they run, even rolled back. "
        "Scan a copy instead, reading this database's queries without writing to it: plancliff scan <copy> --stats-from <this database>. "
        "Or pass --allow-busy if slowing this database down is acceptable."
    )
