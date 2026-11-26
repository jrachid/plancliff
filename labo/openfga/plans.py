"""Usage : python plans.py ; affiche le plan générique et le plan spécifique de la pré-vérification OpenFGA, avec le temps réel."""
import psycopg
from psycopg import sql

from reproduire import DSN, N_TUPLES, parametres

TEXTE = (
    "SELECT * FROM tuple WHERE store = $1 AND (object_type, object_id, relation, _user, user_type) IN ("
    + ", ".join("(" + ", ".join(f"${2 + 5 * k + i}" for i in range(5)) + ")" for k in range(N_TUPLES))
    + ") FOR UPDATE"
)

with psycopg.connect(DSN) as c:
    print(c.execute("select n_distinct from pg_stats where tablename = 'tuple' and attname = '_user'").fetchone())
    c.execute("prepare p as " + TEXTE)
    valeurs = sql.SQL(", ").join(map(sql.Literal, parametres(1)))
    for mode in ("force_generic_plan", "force_custom_plan"):
        c.execute(f"set plan_cache_mode = {mode}")
        lignes = [l for l, in c.execute(sql.SQL("explain (analyze, buffers off) execute p({})").format(valeurs))]
        utiles = [l for l in lignes if any(m in l for m in ("Scan", "Execution Time", "Rows Removed", "LockRows"))]
        print(f"== {mode}")
        print("\n".join(l[:150] for l in utiles[:6] + utiles[-1:]))
    c.rollback()
