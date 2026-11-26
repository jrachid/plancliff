import statistics
import time

import psycopg

DSN = "postgresql://postgres:p@localhost:55432/postgres"
FILE = "select id from jobs where status = $1 order by created_at limit 10"


def cout(plan):
    return plan.split("cost=")[1].split(" ")[0]


with psycopg.connect(DSN, autocommit=True) as c:
    c.execute("prepare file(text) as " + FILE)
    gen = c.execute("explain (generic_plan) " + FILE).fetchall()
    spe = c.execute("explain execute file('pending')").fetchall()
    print("estimation, plan générique :", cout(gen[0][0]), "|", gen[1][0].strip()[:70])
    print("estimation, plan spécifique:", cout(spe[0][0]), "|", spe[1][0].strip()[:70])
    for mode in ("force_generic_plan", "force_custom_plan"):
        c.execute(f"set plan_cache_mode = {mode}")
        lignes = c.execute("explain (analyze, timing off, summary on) execute file('pending')").fetchall()
        print(f"réel, {mode:19}:", lignes[-1][0])
    c.execute("set plan_cache_mode = auto")

    c.execute("""create table if not exists client (id int primary key, pays text, segment text);
                 create table if not exists commande (id int primary key, client_id int references client, montant numeric, cree timestamptz);
                 create table if not exists ligne (id int primary key, commande_id int references commande, produit text, qte int);
                 create table if not exists produit (code text primary key, categorie text)""")
    if not c.execute("select count(*) from client").fetchone()[0]:
        c.execute("insert into client select g, 'FR', 's' || (g % 5) from generate_series(1, 50000) g")
        c.execute("insert into commande select g, 1 + g % 50000, g % 300, now() - (g || ' minutes')::interval from generate_series(1, 300000) g")
        c.execute("insert into ligne select g, 1 + g % 300000, 'p' || (g % 2000), 1 + g % 4 from generate_series(1, 600000) g")
        c.execute("insert into produit select 'p' || g, 'c' || (g % 30) from generate_series(0, 1999) g")
        c.execute("create index on commande (client_id); create index on ligne (commande_id); analyze")

REQUETES = {
    "lecture par clé": ("select id, status from jobs where id = %s", lambda i: (1 + i * 7919 % 1_999_999,)),
    "jointure 4 tables": (
        """select c.segment, p.categorie, sum(l.qte * o.montant) from client c join commande o on o.client_id = c.id
           join ligne l on l.commande_id = o.id join produit p on p.code = l.produit where c.id = %s group by 1, 2""",
        lambda i: (1 + i * 7919 % 49_999,),
    ),
}

for nom, (sql, param) in REQUETES.items():
    for mode in ("auto", "force_custom_plan"):
        mesures = []
        for _ in range(3):
            with psycopg.connect(DSN, autocommit=True, options=f"-c plan_cache_mode={mode}") as c:
                for i in range(50):
                    c.execute(sql, param(i)).fetchall()
                t = time.perf_counter()
                for i in range(2000):
                    c.execute(sql, param(i)).fetchall()
                mesures.append((time.perf_counter() - t) / 2000 * 1e6)
        print(f"{nom:18} {mode:18} {statistics.median(mesures):7.1f} µs par requête")
