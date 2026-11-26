"""Usage : python auto.py ; rejoue en mode auto et lit les compteurs de plans de pg_prepared_statements."""
import time

import psycopg

from reproduire import DSN, REQUETE, parametres

with psycopg.connect(DSN) as c:
    for appel in range(1, 31):
        t = time.perf_counter()
        c.execute(REQUETE, parametres(appel)).fetchall()
        c.commit()
        d = (time.perf_counter() - t) * 1e3
        if appel in (5, 6, 10, 11, 12, 20, 30) or d > 20:
            print(f"appel {appel:2} : {d:8.1f} ms")
    for nom, gen, spe in c.execute("select name, generic_plans, custom_plans from pg_prepared_statements"):
        print("instruction préparée", nom, "| plans génériques :", gen, "| plans spécifiques :", spe)
