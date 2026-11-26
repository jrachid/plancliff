"""Usage : python reproduire.py [--sans-preparation] ; rejoue le nettoyage de tâches de Temporal (#12791) 14 fois sur une connexion."""
import sys
import time

import psycopg

DSN = "postgresql://postgres:p@localhost:55432/temporal"
REQUETE = (
    "DELETE FROM tasks WHERE range_hash = %(h)s AND task_queue_id = %(q)s AND task_id IN (SELECT task_id FROM "
    "tasks WHERE range_hash = %(h)s AND task_queue_id = %(q)s AND task_id < %(t)s ORDER BY task_queue_id, task_id LIMIT %(n)s)"
)

if __name__ == "__main__":
    reglages = {"prepare_threshold": None} if "--sans-preparation" in sys.argv else {}
    with psycopg.connect(DSN, **reglages) as c:
        for appel in range(1, 15):
            t = time.perf_counter()
            supprimees = c.execute(REQUETE, {"h": 0, "q": b"\x00\xff", "t": 1_000_000, "n": 100}).rowcount
            c.commit()
            print(f"appel {appel:2} : {(time.perf_counter() - t) * 1e3:9.1f} ms, {supprimees} tâches supprimées")
        for gen, spe in c.execute("select generic_plans, custom_plans from pg_prepared_statements"):
            print("plans génériques :", gen, "| plans spécifiques :", spe)
