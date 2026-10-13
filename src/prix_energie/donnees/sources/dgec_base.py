"""Export manuel de la « Base de données des prix des produits pétroliers » (DGEC, 1985 →).

La base en ligne (ecologie.gouv.fr, rubrique Prix des produits pétroliers) donne les prix
hebdomadaires/mensuels HT et TTC depuis 1985 pour sp95, sp95-e10, sp98, gazole… mais n'expose
pas de fichier long téléchargeable : l'utilisateur exporte lui-même (tuto DGEC) et passe le
fichier avec --dgec-base. Lecture heuristique : colonne de dates + colonnes reconnues par
mots-clés produit (gazole / sp95 / e10 / e5) et niveau (ttc / ht, htt).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from prix_energie.common import first_numeric_table
from prix_energie.journal import Journal

PRODUCTS = {
    "gazole": re.compile(r"gazole|gasoil|diesel", re.I),
    "sp95_e10": re.compile(r"e10", re.I),
    "sp95": re.compile(r"sp\s?95|sans.?plomb\s?95|eurosuper|super", re.I),
}


def load_dgec_base(path: str, journal: Journal) -> pd.DataFrame | None:
    """Retourne un DataFrame date + colonnes <produit>_<ht|ttc> en c€/l (hebdo ou mensuel selon l'export)."""
    p = Path(path)
    if not p.exists():
        journal.note("ERREUR", "Base DGEC", f"Fichier introuvable : {path}")
        return None
    frames = []
    if p.suffix.lower() in (".xlsx", ".xls"):
        xls = pd.ExcelFile(p)
        for name in xls.sheet_names:
            tab = first_numeric_table(xls.parse(name, header=None), min_dates=24)
            if tab is not None:
                tab.columns = ["date"] + [f"{name}|{c}" for c in tab.columns[1:]]
                frames.append(tab)
    else:
        txt = p.read_text(encoding="utf-8-sig", errors="ignore")
        sep = ";" if txt.count(";") > txt.count(",") else ","
        raw = pd.read_csv(p, sep=sep, header=None, dtype=str, encoding="utf-8-sig")
        raw = raw.apply(lambda s: s.str.replace(",", ".", regex=False) if s.dtype == object else s)
        tab = first_numeric_table(raw, min_dates=24)
        if tab is not None:
            frames.append(tab)
    if not frames:
        journal.note("ERREUR", "Base DGEC", "Aucune table datée reconnue dans l'export.")
        return None
    df = frames[0]
    for f in frames[1:]:
        df = df.merge(f, on="date", how="outer")
    out = pd.DataFrame({"date": df["date"]})
    for c in df.columns[1:]:
        n = c.lower()
        level = "ttc" if "ttc" in n else ("ht" if re.search(r"\bhtt?\b|hors", n) else None)
        if level is None:
            continue
        prod = next((k for k, pat in PRODUCTS.items() if pat.search(n)), None)
        if prod is None:
            continue
        key = f"{prod}_{level}"
        if key not in out.columns:
            out[key] = df[c]
    if out.shape[1] == 1:
        journal.note("ERREUR", "Base DGEC", f"Colonnes produit/niveau non reconnues : {list(df.columns)[:15]}")
        return None
    # unité : la base DGEC est en €/l → c€/l si médiane < 5
    for c in out.columns[1:]:
        if out[c].median() < 5:
            out[c] = out[c] * 100
    journal.source("Carburants – prix HT et TTC depuis 1985 (export manuel de la base DGEC)", "DGEC", path,
                   f"Colonnes reconnues : {list(out.columns[1:])}. Prix du vendredi, France métropolitaine hors Corse.")
    journal.note("DEFINITION", "Base DGEC", "Avant 2005 la série carburants provient de l'export DGEC (prix du vendredi) ; "
                 "à partir de 2005 du Weekly Oil Bulletin (prix du lundi déclarés par la DGEC). Rupture de source "
                 "signalée dans la colonne « Source prix » ; écart de niveau mesuré sur les mois de recouvrement.")
    return out.sort_values("date").reset_index(drop=True)
