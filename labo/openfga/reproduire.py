"""Usage : python reproduire.py ; rejoue la pré-vérification d'écriture d'OpenFGA (#3444) 12 fois sur une connexion psycopg."""
import sys
import time

import psycopg

DSN = "postgresql://postgres:p@localhost:55432/openfga"
N_TUPLES = 6
REQUETE = (
    "SELECT store, object_type, object_id, relation, _user, user_type, condition_name, condition_context, ulid, inserted_at "
    "FROM tuple WHERE store = %s AND (object_type, object_id, relation, _user, user_type) IN ("
    + ", ".join(["(%s, %s, %s, %s, %s)"] * N_TUPLES)
    + ") FOR UPDATE"
)


def parametres(appel):
    p = ["store1"]
    for k in range(N_TUPLES):
        g = 700000 + appel * 10 + k
        p += ["document", f"obj{g}", "viewer", f"group:hot{k % 4}#member", "userset"]
    return p


if __name__ == "__main__":
    reglages = {"prepare_threshold": None} if "--sans-preparation" in sys.argv else {}
    with psycopg.connect(DSN, **reglages) as c:
        for appel in range(1, 13):
            t = time.perf_counter()
            c.execute(REQUETE, parametres(appel)).fetchall()
            c.commit()
            print(f"appel {appel:2} : {(time.perf_counter() - t) * 1e3:9.1f} ms")
