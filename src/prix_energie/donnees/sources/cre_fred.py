"""CRE (data.gouv.fr) – historique du TRV électricité Bleu résidentiel, et secours Brent (FRED)."""
from __future__ import annotations

import io
import re

import pandas as pd

from prix_energie.donnees.fetch import DownloadError, fetch
from prix_energie.journal import Journal
from prix_energie.config import CRE_TRV_DATASET_URL, CRE_TRV_RESOURCES, FRED_BRENT_CSV, Choices


def _read_csv_any(raw: bytes) -> pd.DataFrame:
    txt = raw.decode("utf-8-sig", "ignore")
    sep = ";" if txt.count(";") > txt.count(",") else ","
    return pd.read_csv(io.StringIO(txt), sep=sep, decimal="," if sep == ";" else ".", dtype=str)


def _col(df: pd.DataFrame, *pats: str) -> str | None:
    for c in df.columns:
        n = c.lower()
        if all(re.search(p, n) for p in pats):
            return c
    return None


def load_cre_trv(journal: Journal, choices: Choices, offline: bool = False) -> pd.DataFrame | None:
    """TRV Bleu option Base, puissance `choices.trv_power_kva` : part fixe et variable HT/TTC,
    et prix moyen TTC/HT pour la consommation de référence."""
    try:
        df = _read_csv_any(fetch(CRE_TRV_RESOURCES["base"], offline=offline))
    except DownloadError as e:
        journal.note("ERREUR", "TRV CRE", f"{e}")
        return None
    c_deb = _col(df, r"debut|début|date_deb")
    c_fin = _col(df, r"fin")
    c_p = _col(df, r"puiss|p_sous|kva")
    c_fix_ht = _col(df, r"fixe", r"ht") or _col(df, r"abo", r"ht")
    c_var_ht = _col(df, r"var", r"ht") or _col(df, r"kwh", r"ht")
    c_fix_ttc = _col(df, r"fixe", r"ttc") or _col(df, r"abo", r"ttc")
    c_var_ttc = _col(df, r"var", r"ttc") or _col(df, r"kwh", r"ttc")
    missing = [n for n, c in [("début", c_deb), ("puissance", c_p), ("fixe HT", c_fix_ht), ("variable HT", c_var_ht),
                              ("fixe TTC", c_fix_ttc), ("variable TTC", c_var_ttc)] if c is None]
    if missing:
        journal.note("ERREUR", "TRV CRE", f"Colonnes non reconnues {missing} ; colonnes lues : {list(df.columns)}")
        return None
    num = lambda s: pd.to_numeric(s.astype(str).str.replace(",", ".", regex=False).str.replace(" ", ""), errors="coerce")  # noqa: E731
    out = pd.DataFrame({
        "debut": pd.to_datetime(df[c_deb], errors="coerce", dayfirst=True),
        "fin": pd.to_datetime(df[c_fin], errors="coerce", dayfirst=True) if c_fin else pd.NaT,
        "puissance_kva": num(df[c_p]),
        "fixe_ht_eur_an": num(df[c_fix_ht]),
        "var_ht": num(df[c_var_ht]),
        "fixe_ttc_eur_an": num(df[c_fix_ttc]),
        "var_ttc": num(df[c_var_ttc]),
    })
    out = out[out.puissance_kva == choices.trv_power_kva].dropna(subset=["debut"]).sort_values("debut")
    if out.empty:
        journal.note("ERREUR", "TRV CRE", f"Aucune ligne pour {choices.trv_power_kva} kVA.")
        return None
    # unité de la part variable : €/kWh (≈0,1–0,3) ou c€/kWh (≈10–30) → on normalise en c€/kWh
    if out.var_ttc.median() < 2:
        out["var_ht"] *= 100
        out["var_ttc"] *= 100
        var_unit_note = "part variable lue en €/kWh, convertie en c€/kWh"
    else:
        var_unit_note = "part variable lue en c€/kWh"
    # part fixe : €/an ou €/mois → si < 40, on suppose €/mois
    if out.fixe_ttc_eur_an.median() < 40:
        out["fixe_ht_eur_an"] *= 12
        out["fixe_ttc_eur_an"] *= 12
        fix_unit_note = "part fixe lue en €/mois, convertie en €/an"
    else:
        fix_unit_note = "part fixe lue en €/an"
    k = choices.trv_ref_kwh
    out["prix_moyen_ht_ceur_kwh"] = out.var_ht + out.fixe_ht_eur_an * 100 / k
    out["prix_moyen_ttc_ceur_kwh"] = out.var_ttc + out.fixe_ttc_eur_an * 100 / k
    out["taxes_et_tva_ceur_kwh"] = out.prix_moyen_ttc_ceur_kwh - out.prix_moyen_ht_ceur_kwh
    journal.source(f"TRV électricité Bleu résidentiel, option Base {choices.trv_power_kva} kVA (2012→)",
                   "Commission de régulation de l'énergie (CRE) via data.gouv.fr", CRE_TRV_DATASET_URL,
                   f"{var_unit_note} ; {fix_unit_note}. Grilles applicables (dates de début/fin).")
    journal.note("METHODE", "TRV CRE", f"Prix moyen = part variable + part fixe / {k:.0f} kWh (consommation de "
                 "référence, choix méthodologique). HT = hors toutes taxes et contributions (fourniture + réseau + "
                 "CTA non séparables ici) ; TTC − HT = TCFE/accise + CTA + TVA, non séparables avec ce jeu de données.")
    journal.note("INDISPONIBLE", "TRV CRE", "Pas de série CRE en open data avant 2012. La décomposition officielle "
                 "fourniture/réseau/taxes du TRV figure dans les délibérations tarifaires de la CRE (PDF).")
    return out.reset_index(drop=True)


def load_fred_brent(journal: Journal, offline: bool = False) -> pd.DataFrame | None:
    try:
        raw = fetch(FRED_BRENT_CSV, offline=offline)
    except DownloadError as e:
        journal.note("ERREUR", "Brent FRED", f"{e}")
        return None
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = ["date", "brent_usd_bbl"]
    df["date"] = pd.to_datetime(df.date, errors="coerce")
    df["brent_usd_bbl"] = pd.to_numeric(df.brent_usd_bbl, errors="coerce")
    df = df.dropna()
    m = df.assign(mois=df.date.dt.to_period("M").dt.to_timestamp()).groupby("mois").brent_usd_bbl.mean().reset_index()
    m = m.rename(columns={"mois": "date"})
    journal.source("Brent Europe spot – secours (quotidien → moyenne mensuelle, $/b)", "US EIA via FRED (St. Louis Fed)",
                   FRED_BRENT_CSV, "Source non européenne, utilisée seulement faute de fichier DGEC exploitable.")
    journal.note("DEFINITION", "Brent", "Série de secours EIA/FRED : Brent Europe spot FOB, moyenne des jours "
                 "ouvrés ; la DGEC publie la moyenne des clôtures du Brent daté. Écart typique < 1 $/b.")
    return m
