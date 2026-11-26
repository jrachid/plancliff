"""Usage : python plancliff.py <dsn> <fichier de requêtes, une par bloc séparé par une ligne vide> ; signale les falaises de plan générique."""
import re
import sys

import psycopg
from psycopg import sql
from pglast import ast, parse_sql
from pglast.enums import A_Expr_Kind
from pglast.visitors import Visitor

SEUIL = 10
PLANCHER_MS = 5
MESURES = 3


class Parametres(Visitor):
    def __init__(self):
        self.tables, self.colonnes = {}, {}

    def visit_RangeVar(self, ancestors, node):
        self.tables[node.alias.aliasname if node.alias else node.relname] = node.relname

    def lier(self, colonne, param):
        if isinstance(colonne, ast.ColumnRef) and isinstance(param, ast.ParamRef):
            self.colonnes[param.number] = [f.sval for f in colonne.fields]

    def visit_InsertStmt(self, ancestors, node):
        colonnes = [ast.ColumnRef(fields=(ast.String(sval=rt.name),)) for rt in node.cols or ()]
        for valeurs in getattr(node.selectStmt, "valuesLists", None) or ():
            for col, val in zip(colonnes, valeurs):
                self.lier(col, val)

    def visit_UpdateStmt(self, ancestors, node):
        for rt in node.targetList or ():
            if rt.name:
                self.lier(ast.ColumnRef(fields=(ast.String(sval=rt.name),)), rt.val)

    def visit_A_Expr(self, ancestors, node):
        g, d = node.lexpr, node.rexpr
        if node.kind == A_Expr_Kind.AEXPR_OP:
            self.lier(g, d)
            self.lier(d, g)
        elif node.kind == A_Expr_Kind.AEXPR_IN:
            for element in d:
                if isinstance(g, ast.RowExpr) and isinstance(element, ast.RowExpr):
                    for col, par in zip(g.args, element.args):
                        self.lier(col, par)
                else:
                    self.lier(g, element)


def colonnes_des_parametres(texte):
    v = Parametres()
    v(parse_sql(texte))
    seule = next(iter(v.tables.values())) if len(v.tables) == 1 else None
    return {n: (v.tables.get(ch[0], seule) if len(ch) == 2 else seule, ch[-1]) for n, ch in v.colonnes.items()}


def valeurs(c, table, colonne):
    ligne = c.execute(
        "select most_common_vals::text::text[], most_common_freqs from pg_stats where tablename = %s and attname = %s",
        (table, colonne),
    ).fetchone()
    if ligne and ligne[0]:
        triees = sorted(zip(ligne[1], ligne[0]))
        return {"fréquentes": triees[-1][1], "rares": triees[0][1]}
    ligne = c.execute(sql.SQL("select {}::text from {} tablesample system (1) limit 1").format(
        sql.Identifier(colonne), sql.Identifier(table))).fetchone() or c.execute(
        sql.SQL("select {}::text from {} limit 1").format(sql.Identifier(colonne), sql.Identifier(table))).fetchone()
    if ligne is None:
        raise ValueError(f"table {table} vide : aucune valeur à essayer")
    echantillon = ligne[0]
    return {"fréquentes": echantillon, "rares": echantillon}


def duree(c, mode, vals):
    c.execute(f"set plan_cache_mode = {mode}")
    requete = sql.SQL("explain (analyze, timing off) execute plancliff({})").format(sql.SQL(", ").join(map(sql.Literal, vals)))
    temps = []
    for _ in range(1 + MESURES):
        plan = c.execute(requete).fetchall()
        temps.append(float(re.search(r"Execution Time: ([\d.]+)", plan[-1][0]).group(1)))
    return min(temps[1:])


def examiner(c, texte):
    params = colonnes_des_parametres(texte)
    candidats = {n: valeurs(c, t, col) for n, (t, col) in params.items()}
    c.execute("deallocate all")
    c.execute(f"prepare plancliff as {texte}")
    types = c.execute("select parameter_types::text[] from pg_prepared_statements where name = 'plancliff'").fetchone()[0]
    for n, type_ in enumerate(types, start=1):
        if n not in candidats:
            if type_ not in ("smallint", "integer", "bigint"):
                raise ValueError(f"${n} ({type_}) ne correspond à aucune colonne : valeur à fournir")
            candidats[n] = {"fréquentes": 100, "rares": 100}
    pire = (0.0, "", 0.0, 0.0, [])
    for scenario in ("fréquentes", "rares"):
        vals = [candidats[n][scenario] for n in sorted(candidats)]
        gen, spe = duree(c, "force_generic_plan", vals), duree(c, "force_custom_plan", vals)
        pire = max(pire, (gen / max(spe, 0.001), scenario, gen, spe, vals), key=lambda p: p[0])
    c.rollback()
    return pire


def blocs(fichier):
    for bloc in open(fichier).read().split("\n\n"):
        lignes = [l for l in bloc.strip().splitlines() if l.strip()]
        if not lignes:
            continue
        nom = lignes[0][3:].strip() if lignes[0].startswith("--") else " ".join(lignes)[:55]
        yield nom, "\n".join(l for l in lignes if not l.startswith("--"))


if __name__ == "__main__":
    import csv
    import json
    import time

    dsn, fichier = sys.argv[1], sys.argv[2]
    debut, compte = time.perf_counter(), {"FALAISE": 0, "ok": 0, "erreur": 0}
    with psycopg.connect(dsn) as c, open(fichier + ".resultats.csv", "w", newline="") as sortie:
        ecrivain = csv.writer(sortie)
        ecrivain.writerow(["nom", "verdict", "rapport", "scenario", "generique_ms", "specifique_ms", "duree_s", "requete", "valeurs"])
        for nom, texte in blocs(fichier):
            t = time.perf_counter()
            try:
                rapport, scenario, gen, spe, vals = examiner(c, texte)
                verdict = "FALAISE" if rapport >= SEUIL and gen - spe >= PLANCHER_MS else "ok"
            except Exception as e:
                c.rollback()
                verdict, rapport, scenario, gen, spe, vals = "erreur", 0.0, str(e).splitlines()[0][:90], 0.0, 0.0, []
            secondes = time.perf_counter() - t
            compte[verdict] += 1
            ecrivain.writerow([nom, verdict, f"{rapport:.1f}", scenario, f"{gen:.2f}", f"{spe:.2f}", f"{secondes:.2f}", texte, json.dumps([str(v) for v in vals])])
            if verdict != "ok":
                print(f"{verdict:8} {rapport:9.1f}×  {gen:9.2f} ms / {spe:7.2f} ms  {secondes:5.1f} s  {nom}  {scenario if verdict == 'erreur' else ''}")
    print(f"\n{sum(compte.values())} requêtes en {time.perf_counter() - debut:.1f} s : {compte}")
