"""Usage : python verifier.py <dsn> <resultats.csv> ; rejoue chaque alerte 20 fois en mode automatique et dit si Postgres bascule vraiment."""
import csv
import json
import sys
import time

import psycopg
from psycopg import sql

APPELS = 20

dsn, fichier = sys.argv[1], sys.argv[2]
with psycopg.connect(dsn) as c:
    for r in csv.DictReader(open(fichier)):
        if r["verdict"] != "FALAISE":
            continue
        vals = json.loads(r["valeurs"])
        c.execute("deallocate all")
        c.execute("set plan_cache_mode = auto")
        c.execute(f"prepare verif as {r['requete']}")
        appel = sql.SQL("execute verif({})").format(sql.SQL(", ").join(map(sql.Literal, vals)))
        temps = []
        for _ in range(APPELS):
            t = time.perf_counter()
            c.execute(appel)
            temps.append((time.perf_counter() - t) * 1e3)
        gen, spe = c.execute("select generic_plans, custom_plans from pg_prepared_statements where name = 'verif'").fetchone()
        c.rollback()
        avant, apres = sorted(temps[1:5])[1], sorted(temps[6:])[len(temps[6:]) // 2]
        confirmee = gen > 0 and apres >= 10 * avant
        print(f"{'CONFIRMÉE' if confirmee else 'NON CONFIRMÉE':14} {r['nom']:45} appels 2-5 : {avant:7.2f} ms, appels 7-20 : {apres:8.2f} ms, plans génériques {gen}/{gen + spe}")
