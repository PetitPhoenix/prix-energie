"""Prix des carburants relevés station par station (data.economie.gouv.fr).

Seule source du dossier qui donne une dispersion *géographique* : toutes les autres
sont des moyennes nationales, et ne peuvent donc rien dire de l'écart entre deux
pompes. Sur un même jour, cet écart dépasse 90 centimes par litre, soit plusieurs fois
ce que le prix national parcourt en un an.

Le flux est dit « instantané », mais chaque station y figure avec la date de son propre
dernier relevé. Deux tiers datent du jour même, neuf sur dix de moins d'une semaine, et
la queue remonte à plus d'un an : une station qui ne déclare plus garde son ancien prix
au catalogue. On écarte donc les relevés trop vieux, sans quoi le prix le plus bas de
France serait celui d'une pompe qui n'a rien publié depuis treize mois.

Le fichier complet pèse une quinzaine de mégaoctets ; on n'en demande que les colonnes
de prix et de date, ce qui le ramène à un demi-mégaoctet.
"""
from __future__ import annotations

import io

import pandas as pd

from prix_energie.donnees.fetch import DownloadError, fetch
from prix_energie.journal import Journal

# Colonnes demandées à l'API : un prix et sa date de mise à jour par carburant.
CARBURANTS = {"e10": "sansplomb", "gazole": "gazole", "sp98": "sp98", "e85": "e85"}
_SELECT = ",".join(f"{c}_prix,{c}_maj" for c in CARBURANTS)
STATIONS_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "prix-des-carburants-en-france-flux-instantane-v2/exports/csv"
    f"?select={_SELECT}&delimiter=%3B"
)
STATIONS_PAGE = ("https://www.data.gouv.fr/fr/datasets/"
                 "prix-des-carburants-en-france-flux-instantane-v2-amelioree/")

# Un prix hors de ces bornes signale un relevé aberrant ou une erreur d'unité, pas une
# station chère : l'E85 descend sous 0,80 €/l, aucun carburant routier n'atteint 5 €.
BORNES = (0.30, 5.00)
# Au-delà, le prix affiché n'est plus celui pratiqué : neuf stations sur dix se mettent
# à jour dans la semaine, donc ce seuil conserve l'essentiel du réseau.
FRAICHEUR_JOURS = 7
# Écart maximal à la médiane du carburant. Les bornes absolues laissent passer des
# saisies fantaisistes : un gazole à 1,25 €/l quand la médiane est à 2,40 : sans pour
# autant pouvoir être resserrées, puisqu'elles doivent couvrir l'E85 à 0,80 €/l. Un
# écart relatif s'adapte à chaque carburant. À 30 %, la station la moins chère de
# France reste dans le lot : les écarts réels entre enseignes dépassent rarement 10 %.
ECART_MEDIANE_MAX = 0.30


def load_prix_stations(journal: Journal, offline: bool = False,
                       fraicheur_jours: int = FRAICHEUR_JOURS) -> pd.DataFrame | None:
    """Prix par station, une ligne par station, une colonne par carburant."""
    try:
        raw = fetch(STATIONS_URL, offline=offline)
    except DownloadError as e:
        journal.note("INDISPONIBLE", "Prix par station",
                     f"Flux data.economie.gouv.fr inaccessible : {e}")
        return None
    try:
        df = pd.read_csv(io.StringIO(raw.decode("utf-8", "ignore")), sep=";")
    except Exception as e:  # noqa: BLE001
        journal.note("ERREUR", "Prix par station", f"CSV illisible : {e}")
        return None

    presents = [c for c in CARBURANTS if f"{c}_prix" in df.columns]
    if not presents:
        journal.note("ERREUR", "Prix par station",
                     f"Aucune colonne de prix reconnue parmi {list(df.columns)[:8]}.")
        return None

    # Référence de fraîcheur : le relevé le plus récent du fichier, et non la date du
    # jour. Le flux peut avoir quelques heures, et en mode hors-ligne il peut dater.
    dates = [pd.to_datetime(df[f"{c}_maj"], errors="coerce", utc=True)
             for c in presents if f"{c}_maj" in df.columns]
    reference = max((d.max() for d in dates if d.notna().any()), default=None)

    out = pd.DataFrame(index=df.index)
    resume, ecartes = [], []
    for c in presents:
        cible = CARBURANTS[c]
        v = pd.to_numeric(df[f"{c}_prix"], errors="coerce")
        hors = v.notna() & ~v.between(*BORNES)
        v = v.where(~hors)
        n_vieux = 0
        if reference is not None and f"{c}_maj" in df.columns:
            age = (reference - pd.to_datetime(df[f"{c}_maj"], errors="coerce", utc=True)).dt.days
            perime = v.notna() & (age.isna() | (age > fraicheur_jours))
            n_vieux = int(perime.sum())
            v = v.where(~perime)
        # Aberrants, une fois les périmés retirés : la médiane doit être calculée sur
        # des prix en vigueur, sinon le repère lui-même serait tiré par les fantômes.
        n_aberrants = 0
        if v.notna().sum() >= 100:
            med = float(v.median())
            loin = v.notna() & ((v - med).abs() / med > ECART_MEDIANE_MAX)
            n_aberrants = int(loin.sum())
            v = v.where(~loin)
        out[cible] = v
        resume.append(f"{cible} {int(v.notna().sum())}")
        if int(hors.sum()) or n_vieux or n_aberrants:
            ecartes.append(f"{cible} : {int(hors.sum())} hors bornes, {n_vieux} périmés, "
                           f"{n_aberrants} aberrants")

    if ecartes:
        journal.note("METHODE", "Prix par station",
                     f"Relevés écartés : {' ; '.join(ecartes)}. Seuil de fraîcheur "
                     f"{fraicheur_jours} jours ; écart maximal à la médiane "
                     f"{ECART_MEDIANE_MAX:.0%}.")
    horodatage = f"{reference:%Y-%m-%d}" if reference is not None else "date inconnue"
    journal.source("Prix des carburants par station (flux instantané)",
                   "Ministère de l'Économie – data.economie.gouv.fr", STATIONS_PAGE,
                   f"{len(out)} stations, relevés du {horodatage} et des "
                   f"{fraicheur_jours} jours précédents ; retenus : "
                   + ", ".join(resume) + ".")
    journal.note("DEFINITION", "Prix par station",
                 "Dispersion géographique sur une fenêtre de quelques jours, et non "
                 "évolution dans le temps : ces prix ne se comparent pas aux moyennes "
                 "nationales mensuelles du dossier, ils en montrent l'étalement.")
    # Colonnes plutôt qu'attributs : le bundle transite par des CSV entre l'étape
    # « data » et l'étape « figures », et pandas ne conserve pas .attrs à l'écriture.
    # Les figures liraient sinon des métadonnées vides dès qu'on régénère seul le
    # dessin, et la fenêtre des relevés disparaîtrait des légendes.
    if reference is not None:
        out["maj_reference"] = reference.strftime("%Y-%m-%d")
    out["fraicheur_jours"] = fraicheur_jours
    out.attrs["reference"] = reference
    out.attrs["fraicheur_jours"] = fraicheur_jours
    return out
