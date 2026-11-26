from dataclasses import dataclass

import psycopg
from psycopg import sql

from plancliff.parameters import Column


class EmptyTable(Exception):
    pass


@dataclass(frozen=True)
class Candidates:
    frequent: object
    rare: object


def candidates(conn: psycopg.Connection, column: Column) -> Candidates:
    """candidates returns the most and least common values of a column from pg_stats, or one sampled value; raises EmptyTable."""
    row = conn.execute(
        "select most_common_vals::text::text[], most_common_freqs from pg_stats"
        " where tablename = %s and attname = %s and (%s::text is null or schemaname = %s)"
        " order by schemaname = current_schema() desc limit 1",
        (column.table, column.name, column.schema, column.schema),
    ).fetchone()
    if row and row[0]:
        by_frequency = sorted(zip(row[1], row[0]))
        return Candidates(frequent=by_frequency[-1][1], rare=by_frequency[0][1])
    table = sql.Identifier(column.schema, column.table) if column.schema else sql.Identifier(column.table)
    pick = sql.SQL("select {}::text from {} {} limit 1")
    sample = conn.execute(pick.format(sql.Identifier(column.name), table, sql.SQL("tablesample system (1)"))).fetchone()
    sample = sample or conn.execute(pick.format(sql.Identifier(column.name), table, sql.SQL(""))).fetchone()
    if sample is None:
        raise EmptyTable(f"table {column.table} is empty: no value to try for {column.name}")
    return Candidates(frequent=sample[0], rare=sample[0])
