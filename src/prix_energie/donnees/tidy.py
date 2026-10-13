"""Écriture des séries normalisées en CSV.

Un fichier par série, format d'échange strict : UTF-8, séparateur « , », point
décimal, dates ISO (AAAA-MM-JJ). C'est ce qui se relit sans surprise depuis
pandas, R ou un tableur, et ce qui se compare d'une exécution à l'autre.

Un double-clic sous Windows ouvrira ces fichiers dans Excel avec une virgule
décimale mal interprétée : c'est un défaut d'import d'Excel, pas du fichier.
Passer par « Données > À partir d'un fichier texte » et choisir l'anglais, ou
utiliser `dialect="excel-fr"` pour obtenir « ; » et la virgule décimale.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from prix_energie.bundle import Bundle
from prix_energie.journal import log
from prix_energie.donnees.guard import Ecart, comparer, lire_existant, pertes

# Séries du bundle -> nom de fichier. Les absentes sont simplement ignorées.
SERIES = {
    "gazole": "carburants_gazole_mensuel",
    "sansplomb": "carburants_sansplomb_mensuel",
    "sp_e5": "carburants_sp95_e5_mensuel",
    "sp_e10_dgec": "carburants_sp95_e10_mensuel",
    "wob_weekly": "carburants_wob_hebdo",
    "brent": "brent_mensuel",
    "marge": "marge_raffinage_mensuel",
    "td_annuel": "transport_distribution_annuel",
    "cotations": "cotations_rotterdam_mensuel",
    "elec_semestriel": "electricite_semestriel",
    "elec_composantes": "electricite_composantes_annuel",
    "elec_ancienne": "electricite_ancienne_1985_2007",
    "elec_bandes": "electricite_bandes_consommation",
    "trv": "electricite_trv",
    "elec_mensuel": "electricite_mensuel_prolonge",
    "cout_km": "cout_100km_mensuel",
    "ipc": "ipc_mensuel",
    "dgec_base": "carburants_base_dgec",
    "stations": "carburants_prix_par_station",
}


def write_csvs(bundle: Bundle, outdir: Path, dialect: str = "standard",
               sur_perte: str = "refuser") -> tuple[list[Path], list[Ecart]]:
    """Écrit chaque série disponible du bundle, après comparaison avec l'existant.

    `sur_perte` décide du sort d'un fichier dont la nouvelle version perdrait des
    données : « refuser » garde l'ancien et dépose le nouveau en `.nouveau.csv`,
    « ecraser » écrit quand même, « ignorer » écrit sans comparer.
    Retourne les fichiers écrits et les écarts constatés.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    sep, decimal = (";", ",") if dialect == "excel-fr" else (",", ".")
    written: list[Path] = []
    ecarts: list[Ecart] = []

    for attr, stem in SERIES.items():
        df = getattr(bundle, attr, None)
        if df is None or not len(df):
            continue
        path = outdir / f"{stem}.csv"

        bloque = False
        if sur_perte != "ignorer":
            ancien = lire_existant(path, sep)
            if ancien is not None:
                diff = comparer(ancien, df, path.name)
                ecarts += diff
                for e in diff:
                    (log.warning if e.nature == "PERTE" else log.info)("%s", e)
                if pertes(diff) and sur_perte == "refuser":
                    bloque = True

        cible = path.with_suffix(".nouveau.csv") if bloque else path
        df.to_csv(cible, index=False, sep=sep, decimal=decimal,
                  encoding="utf-8", date_format="%Y-%m-%d")
        if bloque:
            log.error("CSV : %s NON écrasé (perte de données). Nouvelle version dans %s",
                      path.name, cible.name)
        else:
            written.append(cible)
            log.info("CSV : %s (%d lignes, %d colonnes)", path.name, len(df), df.shape[1])

    # Le journal fait partie du livrable : sans lui, on ne sait pas ce qui manque.
    sources, notes = bundle.journal.to_frames()
    for df, stem in ((sources, "_sources"), (notes, "_notes")):
        if len(df):
            path = outdir / f"{stem}.csv"
            df.to_csv(path, index=False, sep=sep, decimal=decimal, encoding="utf-8")
            written.append(path)

    return written, ecarts


# Colonnes de date à reparser à la relecture, par ordre de préférence.
DATE_COLS = ("mois", "date", "periode")


def read_csvs(outdir: Path, bundle: Bundle) -> Bundle:
    """Recharge dans `bundle` les séries présentes dans `outdir`.

    Permet de retravailler les figures sans refaire ni le téléchargement ni le
    parsing : c'est la séparation parse / report, côté relecture.
    """
    for attr, stem in SERIES.items():
        path = outdir / f"{stem}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, encoding="utf-8")
        for col in DATE_COLS:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        setattr(bundle, attr, df)
        log.info("CSV relu : %s (%d lignes)", path.name, len(df))
    return bundle
