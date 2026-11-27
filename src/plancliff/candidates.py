import secrets
import uuid
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
    common: tuple = ()


def candidates(conn: psycopg.Connection, column: Column) -> Candidates:
    """candidates returns a column's common values from pg_stats, most common first, or one sampled value; raises EmptyTable."""
    row = conn.execute(
        "select most_common_vals::text::text[], most_common_freqs from pg_stats"
        " where tablename = %s and attname = %s and (%s::text is null or schemaname = %s)"
        " order by schemaname = current_schema() desc limit 1",
        (column.table, column.name, column.schema, column.schema),
    ).fetchone()
    if row and row[0]:
        common = tuple(value for _, value in sorted(zip(row[1], row[0]), key=lambda pair: -pair[0]))
        return Candidates(frequent=common[0], rare=common[-1], common=common)
    table = _relation(column)
    pick = sql.SQL("select {}::text from {} {} limit 1")
    sample = conn.execute(pick.format(sql.Identifier(column.name), table, sql.SQL("tablesample system (1)"))).fetchone()
    sample = sample or conn.execute(pick.format(sql.Identifier(column.name), table, sql.SQL(""))).fetchone()
    if sample is None:
        raise EmptyTable(f"table {column.table} is empty: no value to try for {column.name}")
    return Candidates(frequent=sample[0], rare=sample[0])


def _relation(column: Column) -> sql.Identifier:
    return sql.Identifier(column.schema, column.table) if column.schema else sql.Identifier(column.table)


UNIQUE_COLUMNS = """
select distinct a.attname
  from pg_index i
  join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
 where i.indrelid = to_regclass(%s) and i.indisunique
"""
TEXT_TYPES = {"text", "character varying", "character", "citext"}
INTEGER_TYPES = {"smallint", "integer", "bigint"}


def unique_columns(conn: psycopg.Connection, column: Column) -> set[str]:
    name = f"{column.schema}.{column.table}" if column.schema else column.table
    return {row[0] for row in conn.execute(UNIQUE_COLUMNS, (name,)).fetchall()}


def fresh_value(conn: psycopg.Connection, column: Column, type_name: str) -> object | None:
    """fresh_value returns a value absent from the column, so an INSERT does not hit an existing key; None for unsupported types."""
    if type_name in INTEGER_TYPES:
        query = sql.SQL("select coalesce(max({}), 0) + 1 from {}").format(sql.Identifier(column.name), _relation(column))
        return conn.execute(query).fetchone()[0]
    if type_name in TEXT_TYPES:
        return f"plancliff-{secrets.token_hex(6)}"
    if type_name == "bytea":
        return f"\\x{secrets.token_hex(8)}"
    if type_name == "uuid":
        return str(uuid.uuid4())
    return None
