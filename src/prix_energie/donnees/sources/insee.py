"""INSEE – séries mensuelles : IPC (déflateur euros constants) et Brent (prix spot).

Idbanks (note méthodologique INSEE « Prix du pétrole et des matières premières importées », 2023) :
  010002077  Pétrole brut Brent – prix spot – USD/baril
  010002078  Pétrole brut Brent – prix spot – EUR/baril
  001759970  IPC – base 2015 – ensemble des ménages – France (1990 → déc. 2025)
Depuis janvier 2026 l'IPC est publié en base 2025 ; la série base 2015 est raccordée à la
nouvelle base par le rapport des indices sur le mois de recouvrement (déc. 2025) quand les
deux sont disponibles.

Accès : téléchargement CSV depuis le site INSEE (zip « valeurs_mensuelles.csv »). En secours
pour l'IPC : miroir data.gouv.fr (IPC base 2015 rétropolé avant 1990, coefficient documenté par
le producteur du miroir). Le fichier peut aussi être fourni à la main (--ipc-csv).
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date

import pandas as pd

from prix_energie.donnees.fetch import DownloadError, fetch
from prix_energie.journal import Journal

# L'INSEE a déplacé la BDM vers bdm.insee.fr, avec des noms de paramètres différents
# (« donnees_colonne » et « sans_revisions » prennent un tiret bas). L'ancien chemin
# www.insee.fr/fr/statistiques/serie/telecharger/csv/<idbank> répond HTTP 500 depuis.
# Le nouveau est essayé d'abord, l'ancien reste en secours au cas où la bascule serait
# partielle. `anneeFin` vaut l'année courante : une borne lointaine était refusée.
INSEE_CSV_URLS = (
    "https://bdm.insee.fr/series/{idbank}/csv?lang=fr&ordre=antechronologique"
    "&transposition=donnees_colonne&periodeDebut=1&anneeDebut=1970"
    "&periodeFin=12&anneeFin={annee}&revision=sans_revisions",
    "https://www.insee.fr/fr/statistiques/serie/telecharger/csv/{idbank}"
    "?ordre=chronologique&transposition=donneescolonne&periodeDebut=1&anneeDebut=1970"
    "&periodeFin=12&anneeFin={annee}&revision=sansrevisions",
)
# Page de la série, pour citer la source dans le journal sans exposer les paramètres.
INSEE_SERIE_URL = "https://bdm.insee.fr/series/{idbank}"
IDBANK_BRENT_USD = "010002077"
IDBANK_BRENT_EUR = "010002078"
IDBANK_IPC_2015 = "001759970"
# Successeur de la série ci-dessus, arrêtée en déc. 2025 lors du rebasement décennal.
# Mêmes critères (ensemble des ménages, France, Coicop « 00 - Ensemble »), base 2025 ;
# rétropolée jusqu'en 1996, donc suffisante à elle seule pour toute la période couverte
# par les carburants. Sert de raccord automatique au-delà de déc. 2025.
IDBANK_IPC_2025 = "011814630"
IPC_DATAGOUV_PAGE = "https://www.data.gouv.fr/fr/datasets/62de9a202f1e7ddee9c7d19d/"


def _parse_insee_csv(raw: bytes) -> pd.DataFrame:
    """Retourne date (1er du mois), valeur. Accepte zip ou csv, ';' ou ','."""
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".csv") and "valeurs" in n.lower()),
                        next(n for n in z.namelist() if n.lower().endswith(".csv")))
            raw = z.read(name)
    txt = raw.decode("utf-8-sig", "ignore")
    sep = ";" if txt.count(";") >= txt.count(",") else ","
    df = pd.read_csv(io.StringIO(txt), sep=sep, dtype=str)
    # colonne période : 'Période' / 'periode' / 'TIME_PERIOD' ; valeur : première colonne numérique
    pcol = next((c for c in df.columns if re.search(r"p[ée]riode|time|date", c, re.I)), df.columns[0])
    vcol = None
    for c in df.columns:
        if c == pcol:
            continue
        v = pd.to_numeric(df[c].astype(str).str.replace(",", ".", regex=False), errors="coerce")
        if v.notna().sum() >= 12:
            vcol = c
            break
    if vcol is None:
        raise ValueError(f"aucune colonne numérique dans {list(df.columns)}")
    per = df[pcol].astype(str).str.strip()
    # formats : 2024-03, 2024-03-01, 2024M03
    per = per.str.replace(r"^(\d{4})M(\d{2})$", r"\1-\2", regex=True)
    date = pd.to_datetime(per, errors="coerce", format="mixed")
    out = pd.DataFrame({"date": date.dt.to_period("M").dt.to_timestamp(),
                        "valeur": pd.to_numeric(df[vcol].astype(str).str.replace(",", ".", regex=False), errors="coerce")})
    return out.dropna().sort_values("date").reset_index(drop=True)


def load_insee_series(idbank: str, journal: Journal, offline: bool = False) -> pd.DataFrame | None:
    """Série BDM par idbank, en essayant successivement les points d'accès connus."""
    annee = date.today().year
    erreurs = []
    for url in INSEE_CSV_URLS:
        try:
            return _parse_insee_csv(fetch(url.format(idbank=idbank, annee=annee), offline=offline))
        except (DownloadError, ValueError, zipfile.BadZipFile, StopIteration) as e:
            erreurs.append(f"{url.split('/')[2]} : {e}")
    journal.note("ERREUR", f"INSEE {idbank}",
                 "Téléchargement/lecture impossible. " + " | ".join(erreurs))
    return None


def load_brent_insee(journal: Journal, offline: bool = False) -> pd.DataFrame | None:
    usd = load_insee_series(IDBANK_BRENT_USD, journal, offline)
    if usd is None or len(usd) < 24:
        return None
    df = usd.rename(columns={"valeur": "brent_usd_bbl"})
    eur = load_insee_series(IDBANK_BRENT_EUR, journal, offline)
    if eur is not None:
        df = df.merge(eur.rename(columns={"valeur": "brent_eur_bbl"}), on="date", how="left")
    journal.source("Brent – prix spot, moyennes mensuelles ($/b et €/b)", "INSEE (BDM, idbank 010002077 / 010002078)",
                   INSEE_SERIE_URL.format(idbank=IDBANK_BRENT_USD),
                   f"Couverture {df.date.min():%Y-%m} → {df.date.max():%Y-%m}. Brent spot coté à Londres.")
    return df


def load_ipc(journal: Journal, offline: bool = False, ipc_csv: str | None = None,
             idbank_2025: str | None = None, ipc_csv_2025: str | None = None) -> pd.DataFrame | None:
    """IPC mensuel, ensemble des ménages, France, exprimé en base 2015 = 100 sur toute la période."""
    ipc = None
    src = ""
    if ipc_csv:
        try:
            ipc = _parse_insee_csv(open(ipc_csv, "rb").read())
            src = f"fichier fourni ({ipc_csv})"
        except Exception as e:  # noqa: BLE001
            journal.note("ERREUR", "IPC", f"Fichier --ipc-csv illisible : {e}")
    if ipc is None:
        ipc = load_insee_series(IDBANK_IPC_2015, journal, offline)
        src = "INSEE idbank 001759970"
    if ipc is None:
        # miroir data.gouv (csv : periode,date,ipc)
        try:
            html = fetch(IPC_DATAGOUV_PAGE, offline=offline).decode("utf-8", "ignore")
            m = re.search(r'(https://www\.data\.gouv\.fr/api/1/datasets/r/[0-9a-f-]{36})', html)
            if m:
                ipc = _parse_insee_csv(fetch(m.group(1), offline=offline))
                src = "miroir data.gouv.fr de l'IPC INSEE base 2015 (rétropolé avant 1990 par le producteur du miroir)"
        except (DownloadError, ValueError) as e:
            journal.note("ERREUR", "IPC", f"Miroir data.gouv inaccessible : {e}")
    if ipc is None:
        journal.note("INDISPONIBLE", "IPC", "Aucun déflateur chargé : pas de colonnes en euros constants.")
        return None
    ipc = ipc.rename(columns={"valeur": "ipc_base2015"})
    # On conserve la série telle que publiée, avant raccord : la comparer à la série
    # raccordée montre ce que le changement de base a fait, au lieu de l'affirmer.
    ipc["ipc_avant_raccord"] = ipc["ipc_base2015"]
    # Raccord base 2025 (à partir de janv. 2026). La série base 2015 est arrêtée en
    # déc. 2025 : sans ce raccord, aucun euro constant au-delà. La nouvelle base se
    # fournit par idbank (téléchargement) ou par fichier, l'API restant capricieuse.
    idbank_2025 = idbank_2025 or IDBANK_IPC_2025
    if idbank_2025 or ipc_csv_2025:
        new = None
        if ipc_csv_2025:
            try:
                new = _parse_insee_csv(open(ipc_csv_2025, "rb").read())
            except Exception as e:  # noqa: BLE001
                journal.note("ERREUR", "IPC", f"Fichier --ipc-csv-2025 illisible : {e}")
        if new is None and idbank_2025:
            new = load_insee_series(idbank_2025, journal, offline)
        if new is not None:
            common = ipc.merge(new, on="date")
            if len(common):
                k = float((common.ipc_base2015 / common.valeur).iloc[-1])
                # Le raccord d'abord : il se calcule sur la fin de la série *courte*.
                # Fusionner la base 2025 avant reviendrait à allonger cette série, et
                # l'extension ne trouverait plus aucun mois à ajouter.
                ext = new[new.date > ipc.date.max()].assign(ipc_base2015=lambda d: d.valeur * k)[["date", "ipc_base2015"]]
                ipc = pd.concat([ipc, ext], ignore_index=True)
                ipc["bascule_base"] = common.date.max()
                # La base 2025 est ensuite conservée telle que publiée, à son propre
                # niveau : tracée à côté de la série raccordée, elle montre l'écart
                # que le coefficient corrige.
                ipc = ipc.merge(new.rename(columns={"valeur": "ipc_base2025_publie"}),
                                on="date", how="left").sort_values("date")
                journal.note("RUPTURE", "IPC", f"Raccord base 2025 → base 2015 par coefficient {k:.6f} "
                             f"(mois de recouvrement {common.date.max():%Y-%m}).")
            else:
                journal.note("ERREUR", "IPC", "Aucun mois de recouvrement entre base 2015 et base 2025 : pas de raccord.")
    journal.source("IPC – ensemble des ménages – France (déflateur)", "INSEE", src,
                   f"Base 2015 = 100 ; couverture {ipc.date.min():%Y-%m} → {ipc.date.max():%Y-%m}.")
    journal.note("METHODE", "Euros constants", "Valeur constante = valeur courante × IPC(mois de référence) / IPC(mois). "
                 "Le mois de référence se choisit avec --ipc-ref ; par défaut le dernier mois d'IPC disponible.")
    return ipc.reset_index(drop=True)
