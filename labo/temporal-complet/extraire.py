"""Usage : python extraire.py ; extrait les requêtes SQL des fichiers Go de Temporal et écrit requetes.sql (une par bloc)."""
import pathlib
import re

CHAINE = re.compile(r"(\w+)\s*=\s*((?:`[^`]*`\s*\+?\s*)+)", re.S)
MORCEAU = re.compile(r"`([^`]*)`")
GABARIT_CARTES = re.compile(r"%(\[\d\])?v")
TABLES_CARTES = {
    "activity_info_maps": "schedule_id",
    "timer_info_maps": "timer_id",
    "child_execution_info_maps": "initiated_id",
    "request_cancel_info_maps": "initiated_id",
    "signal_info_maps": "initiated_id",
    "chasm_node_maps": "chasm_path",
}


def instancier(nom, sql):
    if not GABARIT_CARTES.search(sql):
        return [(nom, sql)]
    if "%[2]v" in sql or "%[3]v" in sql or "%[5]v" in sql:
        return []
    return [(f"{nom}[{t}]", sql.replace("%[1]v", t).replace("%[4]v", cle).replace("%v", t))
            for t, cle in TABLES_CARTES.items()]


requetes, ecartees = [], {"insertion à paramètres nommés": 0, "gabarit non résolu": 0, "sans paramètre $n": 0, "IN avec ?": 0}
for f in sorted(pathlib.Path("go").glob("*.go")):
    for nom, brut in CHAINE.findall(f.read_text()):
        sql = "".join(MORCEAU.findall(brut))
        if not re.search(r"\b(SELECT|DELETE|UPDATE|INSERT)\b", sql, re.I):
            continue
        if re.search(r":\w+", sql) and not re.search(r"\$\d", sql):
            ecartees["insertion à paramètres nommés"] += 1
            continue
        if "?" in sql:
            ecartees["IN avec ?"] += 1
            continue
        instances = instancier(nom, sql)
        if not instances:
            ecartees["gabarit non résolu"] += 1
            continue
        for n, s in instances:
            if "%" in s:
                ecartees["gabarit non résolu"] += 1
            elif not re.search(r"\$\d", s):
                ecartees["sans paramètre $n"] += 1
            else:
                requetes.append((f"{f.stem}.{n}", " ".join(s.split())))

with open("requetes.sql", "w") as out:
    for nom, sql in requetes:
        out.write(f"-- {nom}\n{sql}\n\n")
print(len(requetes), "requêtes gardées ;", ecartees)
