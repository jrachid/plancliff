"""Usage : python prototype.py ; compare plan générique et plan spécifique pour chaque requête, valeurs tirées de pg_stats."""
import re

import psycopg
from psycopg import sql
from pglast import ast, parse_sql
from pglast.visitors import Visitor

DSN = "postgresql://postgres:p@localhost:55432/postgres"
SEUIL = 10

REQUETES = [
    "select id from jobs where status = $1 order by created_at limit 10",
    "select id, status from jobs where id = $1",
    """select c.segment, p.categorie, sum(l.qte * o.montant) from client c join commande o on o.client_id = c.id
       join ligne l on l.commande_id = o.id join produit p on p.code = l.produit where c.id = $1 group by 1, 2""",
]


class Parametres(Visitor):
    def __init__(self):
        self.tables, self.colonnes = {}, {}

    def visit_RangeVar(self, ancestors, node):
        self.tables[node.alias.aliasname if node.alias else node.relname] = node.relname

    def visit_A_Expr(self, ancestors, node):
        g, d = node.lexpr, node.rexpr
        if isinstance(d, ast.ColumnRef) and isinstance(g, ast.ParamRef):
            g, d = d, g
        if isinstance(g, ast.ColumnRef) and isinstance(d, ast.ParamRef):
            self.colonnes[d.number] = [f.sval for f in g.fields]


def colonnes_des_parametres(sql):
    v = Parametres()
    v(parse_sql(sql))
    seule = next(iter(v.tables.values())) if len(v.tables) == 1 else None
    return {n: (v.tables.get(ch[0], seule) if len(ch) == 2 else seule, ch[-1]) for n, ch in v.colonnes.items()}


def valeurs_candidates(c, table, colonne):
    ligne = c.execute("select most_common_vals::text::text[], most_common_freqs from pg_stats where tablename = %s and attname = %s",
                      (table, colonne)).fetchone()
    if ligne and ligne[0]:
        vals = sorted(zip(ligne[1], ligne[0]))
        return [vals[0][1], vals[-1][1]]
    return [str(x) for x, in c.execute(f"select {colonne} from {table} tablesample system (1) limit 2")]


def duree(c, mode, valeurs):
    c.execute(f"set plan_cache_mode = {mode}")
    litteraux = sql.SQL(", ").join(map(sql.Literal, valeurs))
    plan = c.execute(sql.SQL("explain (analyze, timing off) execute p({})").format(litteraux)).fetchall()
    return float(re.search(r"Execution Time: ([\d.]+)", plan[-1][0]).group(1))


with psycopg.connect(DSN) as c:
    for texte in REQUETES:
        params = colonnes_des_parametres(texte)
        c.execute(f"prepare p as {texte}")
        pire = (0, None)
        for n, (table, colonne) in sorted(params.items()):
            for v in valeurs_candidates(c, table, colonne):
                rapport = duree(c, "force_generic_plan", [v]) / max(duree(c, "force_custom_plan", [v]), 0.001)
                pire = max(pire, (rapport, f"{table}.{colonne} = {v!r}"))
        c.execute("deallocate p")
        c.rollback()
        verdict = "FALAISE" if pire[0] >= SEUIL else "ok"
        print(f"{verdict:8} plan générique {pire[0]:8.1f}× plus lent  ({pire[1]})  {' '.join(texte.split())[:60]}")
