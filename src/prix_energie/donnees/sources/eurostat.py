"""Eurostat – prix de l'électricité pour les ménages (France, bande DC 2 500–4 999 kWh).

* nrg_pc_204   : semestriel, 2007S1 →, trois niveaux : X_TAX (hors toutes taxes),
                 X_VAT (hors TVA et autres taxes récupérables), I_TAX (toutes taxes comprises).
* nrg_pc_204_c : annuel, 2017 →, composantes : NRG_SUP (énergie et fourniture), NETC (réseau),
                 TAX_* (taxes/contributions), VAT.
* nrg_pc_204_h : ancienne méthodologie 1985 → 2007 (consommateurs-types Da…De, prix au 1er
                 janvier / 1er juillet). Rupture méthodologique en 2007.
Les codes de dimension sont lus dans la réponse JSON-stat (pas de code en dur au-delà des
filtres), et les indicateurs de statut (p = provisoire, e = estimé, b = rupture) sont conservés.
"""
from __future__ import annotations

import json
from itertools import product

import pandas as pd

from prix_energie.donnees.fetch import DownloadError, fetch
from prix_energie.journal import Journal
from prix_energie.config import EUROSTAT_API, EUROSTAT_DATASETS


def _jsonstat_to_frame(js: dict) -> pd.DataFrame:
    ids = js["id"]
    sizes = js["size"]
    dims = js["dimension"]
    # index -> code pour chaque dimension, et libellés
    codes = {}
    labels = {}
    for d in ids:
        idx = dims[d]["category"]["index"]
        inv = {v: k for k, v in idx.items()} if isinstance(idx, dict) else dict(enumerate(idx))
        codes[d] = [inv[i] for i in range(len(inv))]
        labels[d] = dims[d]["category"].get("label", {})
    values = js["value"]
    status = js.get("status", {}) or {}
    rows = []
    # JSON-stat : valeur à l'index linéaire (row-major sur `size`)
    for combo in product(*[range(n) for n in sizes]):
        lin = 0
        for k, c in enumerate(combo):
            lin = lin * sizes[k] + c
        v = values.get(str(lin)) if isinstance(values, dict) else (values[lin] if lin < len(values) else None)
        if v is None:
            continue
        row = {d: codes[d][c] for d, c in zip(ids, combo)}
        row.update({f"{d}_label": labels[d].get(codes[d][c], codes[d][c]) for d, c in zip(ids, combo)})
        row["value"] = v
        row["status"] = status.get(str(lin), "") if isinstance(status, dict) else ""
        rows.append(row)
    return pd.DataFrame(rows)


def _get(dataset: str, filters: dict, offline: bool) -> pd.DataFrame:
    qs = "&".join(f"{k}={v}" for k, v in filters.items())
    url = f"{EUROSTAT_API.format(dataset=dataset)}?format=JSON&lang=FR&{qs}"
    raw = fetch(url, offline=offline)
    return _jsonstat_to_frame(json.loads(raw.decode("utf-8")))


def _period(s: str) -> pd.Timestamp:
    """'2007-S1' → 2007-01-01 ; '2007-S2' → 2007-07-01 ; '2017' → 2017-01-01."""
    if "-S" in s:
        y, sem = s.split("-S")
        return pd.Timestamp(int(y), 1 if sem == "1" else 7, 1)
    return pd.Timestamp(int(s[:4]), 1, 1)


def load_eurostat(journal: Journal, offline: bool = False) -> dict:
    out = {"semestriel": None, "composantes": None, "ancienne": None, "bandes": None}

    # ---- nrg_pc_204 semestriel
    try:
        df = _get("nrg_pc_204", EUROSTAT_DATASETS["nrg_pc_204"], offline)
        piv = df.pivot_table(index="time", columns="tax", values="value", aggfunc="first")
        st = df.groupby("time")["status"].agg(lambda s: "".join(sorted(set("".join(s)))))
        piv = piv.rename(columns={"X_TAX": "hors_taxes", "X_VAT": "hors_tva", "I_TAX": "ttc"})
        piv["statut"] = st
        piv.index = [_period(t) for t in piv.index]
        piv.index.name = "periode"
        piv = piv.sort_index().reset_index()
        # composantes additives (€/kWh → c€/kWh)
        for c in ("hors_taxes", "hors_tva", "ttc"):
            piv[c] = piv[c] * 100
        out["semestriel"] = piv
        journal.source("Électricité ménages – prix semestriels 3 niveaux de taxes (2007→)", "Eurostat nrg_pc_204",
                       "https://ec.europa.eu/eurostat/databrowser/view/nrg_pc_204/default/table",
                       "France, bande DC (2 500–4 999 kWh), €/kWh → c€/kWh. Moyenne pondérée de tous les contrats "
                       "(TRV et offres de marché), pas le seul TRV.")
        journal.note("DEFINITION", "Eurostat nrg_pc_204", "'Hors taxes' = énergie + fourniture + réseau. "
                     "'Hors TVA' − 'hors taxes' = taxes et contributions hors TVA (TCFE/accise, CSPE avant 2016, CTA…). "
                     "'TTC' − 'hors TVA' = TVA. Décomposition fourniture/réseau indisponible dans ce jeu.")
    except (DownloadError, KeyError, ValueError) as e:
        journal.note("ERREUR", "Eurostat nrg_pc_204", f"{e}")

    # ---- nrg_pc_204_c composantes annuelles
    try:
        df = _get("nrg_pc_204_c", EUROSTAT_DATASETS["nrg_pc_204_c"], offline)
        piv = df.pivot_table(index="time", columns="nrg_prc", values="value", aggfunc="first") * 100
        lab = df.drop_duplicates("nrg_prc").set_index("nrg_prc")["nrg_prc_label"].to_dict()
        st = df.groupby("time")["status"].agg(lambda s: "".join(sorted(set("".join(s)))))
        piv["statut"] = st
        piv.index = [_period(t) for t in piv.index]
        piv.index.name = "periode"
        out["composantes"] = piv.sort_index().reset_index()
        out["composantes_labels"] = lab
        journal.source("Électricité ménages – composantes annuelles du prix (2017→)", "Eurostat nrg_pc_204_c",
                       "https://ec.europa.eu/eurostat/databrowser/view/nrg_pc_204_c/default/table",
                       "NRG_SUP = énergie et fourniture ; NETC = réseau ; TAX_* = taxes et contributions ; VAT = TVA. c€/kWh.")
        journal.note("INDISPONIBLE", "Électricité fourniture/réseau", "Décomposition fourniture / réseau publiée par "
                     "Eurostat seulement depuis 2017 (règlement UE 2016/1952). Avant 2017 : seuls les trois niveaux "
                     "(hors taxes, hors TVA, TTC) sont disponibles.")
    except (DownloadError, KeyError, ValueError) as e:
        journal.note("ERREUR", "Eurostat nrg_pc_204_c", f"{e}")

    # ---- nrg_pc_204 toutes bandes de consommation
    # La bande DC (2 500–4 999 kWh) est la référence habituelle, mais un logement
    # chauffé à l'électricité dépasse largement 5 000 kWh : sans les autres bandes,
    # impossible de savoir si le prix au kWh dépend du volume consommé.
    try:
        filtres = {k: v for k, v in EUROSTAT_DATASETS["nrg_pc_204"].items() if k != "nrg_cons"}
        df = _get("nrg_pc_204", filtres, offline)
        df = df[df["tax"] == "I_TAX"]
        piv = df.pivot_table(index="time", columns="nrg_cons", values="value", aggfunc="first") * 100
        piv.index = [_period(t) for t in piv.index]
        piv.index.name = "periode"
        out["bandes"] = piv.sort_index().reset_index()
        out["bandes_labels"] = df.drop_duplicates("nrg_cons").set_index("nrg_cons")["nrg_cons_label"].to_dict()
        journal.source("Électricité ménages – prix TTC par bande de consommation (2007→)", "Eurostat nrg_pc_204",
                       "https://ec.europa.eu/eurostat/databrowser/view/nrg_pc_204/default/table",
                       "Toutes bandes de consommation annuelle, France, prix TTC en c€/kWh.")
    except (DownloadError, KeyError, ValueError) as e:
        journal.note("ERREUR", "Eurostat bandes de consommation", f"{e}")

    # ---- nrg_pc_204_h ancienne méthodologie (1985–2007)
    try:
        df = _get("nrg_pc_204_h", EUROSTAT_DATASETS["nrg_pc_204_h"], offline)
        # sélection du consommateur-type Dc (3 500 kWh/an) par libellé, sinon le premier
        cons_col = next((c for c in df.columns if c in ("consom", "nrg_cons", "indic_en")), None)
        if cons_col:
            lab = df[f"{cons_col}_label"].astype(str)
            mask = lab.str.contains(r"\bDc\b|3 ?500", case=False, regex=True)
            if mask.any():
                df = df[mask]
        tax_col = next((c for c in df.columns if c in ("tax", "indic_en")), None)
        if tax_col:
            piv = df.pivot_table(index="time", columns=tax_col, values="value", aggfunc="first") * 100
            piv.index = [_period(t) for t in piv.index]
            piv.index.name = "periode"
            piv = piv.sort_index().reset_index()
            piv.attrs["labels"] = df.drop_duplicates(tax_col).set_index(tax_col)[f"{tax_col}_label"].to_dict()
            out["ancienne"] = piv
        journal.source("Électricité ménages – ancienne méthodologie (1985→2007)", "Eurostat nrg_pc_204_h",
                       "https://ec.europa.eu/eurostat/databrowser/view/nrg_pc_204_h/default/table",
                       "Consommateur-type Dc (3 500 kWh/an, 1 300 kWh de nuit), prix au 1er janvier et 1er juillet.")
        journal.note("RUPTURE", "Électricité", "2007 : passage des consommateurs-types (ancienne méthode) aux prix moyens "
                     "par bande de consommation (directive 2008/92/CE puis règlement 2016/1952). Les deux séries ne "
                     "sont pas directement raccordables ; elles sont présentées côte à côte.")
    except (DownloadError, KeyError, ValueError) as e:
        journal.note("ERREUR", "Eurostat nrg_pc_204_h", f"{e}")
    return out
