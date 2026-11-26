"""Usage : python remplir.py <dsn> [lignes] ; remplit chaque table : 80 % des lignes partagent une valeur chaude sur les colonnes de tête de la clé."""
import sys

import psycopg
from psycopg import sql

DSN = sys.argv[1]
LIGNES = int(sys.argv[2]) if len(sys.argv) > 2 else 60_000


def expression(type_, longueur, role):
    """role : 'chaude' (tête de clé déséquilibrée), 'unique' (fin de clé), 'libre' (hors clé)."""
    n = {"chaude": "(CASE WHEN g % 10 < 8 THEN 0 ELSE 1 + g % 500 END)", "unique": "g", "libre": "(g % 1000)"}[role]
    if type_ in ("bigint", "integer", "smallint"):
        return f"{n}::{type_}"
    if type_ == "bytea":
        return f"int4send({n}::int)"
    if type_ == "character varying":
        return f"left('v' || {n}, {longueur or 64})"
    if type_ == "timestamp without time zone":
        return f"(timestamp '2026-01-01' + {n} * interval '1 second')"
    if type_ == "boolean":
        return f"({n} % 2 = 0)"
    raise ValueError(type_)


with psycopg.connect(DSN, autocommit=True) as c:
    tables = [t for t, in c.execute("select table_name from information_schema.tables where table_schema = 'public' order by 1")]
    for table in tables:
        if c.execute(sql.SQL("select exists (select from {})").format(sql.Identifier(table))).fetchone()[0]:
            continue
        cle = [col for col, in c.execute(
            """select a.attname from pg_index i join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
               where i.indrelid = %s::regclass and i.indisprimary order by array_position(i.indkey, a.attnum)""", (table,))]
        colonnes = c.execute(
            "select column_name, data_type, character_maximum_length from information_schema.columns "
            "where table_schema = 'public' and table_name = %s order by ordinal_position", (table,)).fetchall()
        exprs = []
        for nom, type_, longueur in colonnes:
            role = "unique" if cle and nom == cle[-1] else "chaude" if nom in cle else "libre"
            exprs.append(sql.SQL(expression(type_, longueur, role)))
        try:
            c.execute(sql.SQL("insert into {} ({}) select {} from generate_series(1, {}) g").format(
                sql.Identifier(table), sql.SQL(", ").join(sql.Identifier(n) for n, _, _ in colonnes),
                sql.SQL(", ").join(exprs), sql.Literal(LIGNES)))
            print(f"{table:32} clé {cle}")
        except psycopg.Error as e:
            print(f"{table:32} REFUSÉE : {str(e).splitlines()[0]}")
    c.execute("analyze")
