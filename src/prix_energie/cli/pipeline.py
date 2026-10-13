"""Construction des données et des figures.

Invocation : python -m prix_energie build [--offline] [-v]

Produit des CSV normalisés (un fichier par série) et des figures PNG.
Trois étapes, enchaînées par défaut, sélectionnables avec --only :

  fetch   téléchargement vers le cache disque   (.cache_prix_energie/)
  data    parsing + contrôles -> CSV            (--only data)
  figures CSV -> PNG                            (--only figures, sans réseau ni parsing)

Le classeur Excel n'est plus produit par défaut : sa logique de calcul vivait dans
des formules, donc hors de portée des tests. Utiliser --xlsx pour le régénérer.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from prix_energie.chemins import DONNEES, SITE
from prix_energie.cli import pages
from prix_energie.cli.pages import SiteIncomplet


def _dessiner(bundle, site: Path) -> int:
    """Figures, images du fil, contrôle du catalogue, puis pages.

    Toute étape qui écrit des figures passe par ici : les pages reprennent des valeurs
    des CSV, et un site dont il manque une figure ne doit pas être publié. Une erreur
    arrête donc la construction au lieu d'être seulement journalisée.
    """
    from prix_energie.viz import catalogue
    from prix_energie.viz.carrousel import construire as write_carrousel
    from prix_energie.viz.feed import generer as write_feed
    from prix_energie.viz.figures import write_figures

    figures = write_figures(bundle, site / "figures")
    print(f"{len(figures)} figure(s) dans {site / 'figures'}")
    # Second jeu, format timeline : mêmes données, trois séries au plus,
    # titre et conclusion dans l'image. Il ne remplace pas le premier.
    feed_png = write_feed(bundle, site / "feed")
    write_carrousel(site / "feed", site / "feed" / "carrousel_linkedin.pdf")
    print(f"{len(feed_png)} image(s) de fil dans {site / 'feed'}")

    fautes = ([f"figures {e}" for e in catalogue.ecarts(catalogue.FIGURES, figures)]
              + [f"fil {e}" for e in catalogue.ecarts(catalogue.FEED, feed_png)])
    if fautes:
        raise SiteIncomplet("le site ne correspond pas au catalogue (viz/catalogue.py) :\n  "
                             + "\n  ".join(fautes))
    pages.main()
    return len(figures)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    # Deux dossiers de nature differente : les CSV sont une donnee qu'on garde,
    # les figures et les pages un derive que la forge reconstruit.
    p.add_argument("--data", type=Path, default=DONNEES,
                   help="dossier des series normalisees (defaut : data/)")
    p.add_argument("--site", type=Path, default=SITE,
                   help="dossier du site produit (defaut : site/)")
    p.add_argument("--only", choices=("all", "fetch", "data", "figures"), default="all",
                   help="n'exécuter qu'une étape (défaut : tout)")
    p.add_argument("--sur-perte", choices=("refuser", "ecraser", "ignorer"), default="refuser",
                   help="si la nouvelle version d'un CSV perd des données : refuser de l'écraser "
                        "(défaut, dépose un .nouveau.csv), l'écraser quand même, ou ne pas comparer")
    p.add_argument("--csv-dialect", choices=("standard", "excel-fr"), default="standard",
                   help="'standard' : virgule + point décimal (échange) ; 'excel-fr' : ';' + virgule décimale")
    p.add_argument("--xlsx", type=Path, default=None, help="régénérer aussi l'ancien classeur Excel à ce chemin")
    p.add_argument("--start", default="1985-01", help="premier mois (AAAA-MM) ; carburants dès 2005 (WOB) ou 1985 avec --dgec-base")
    p.add_argument("--dgec-base", default=None, help="export manuel (xlsx/csv) de la base DGEC des prix 1985→, pour remonter avant 2005")
    p.add_argument("--ipc-ref", default=None, help="mois de référence des euros constants (AAAA-MM) ; défaut : dernier mois IPC")
    p.add_argument("--ipc-csv", default=None, help="fichier IPC INSEE fourni à la main (csv ou zip)")
    p.add_argument("--ipc-idbank-2025", default=None, help="idbank INSEE de l'IPC base 2025 pour raccorder après déc. 2025")
    p.add_argument("--ipc-csv-2025", default=None, help="fichier IPC base 2025 fourni à la main (raccord après déc. 2025)")
    p.add_argument("--e10-chain", default="2020-01", help="mois de chaînage SP95-E5 → SP95-E10 (AAAA-MM)")
    # Trois semaines : la DGEC ne laisse en ligne que la note la plus récente, les URL
    # des précédentes renvoient 404. On capture donc celle de la semaine, avec deux
    # semaines de rattrapage si la chaîne n'a pas tourné. Le cache disque fait l'archive :
    # la couverture des cotations s'étend d'un mois par mois écoulé.
    p.add_argument("--npg-weeks", type=int, default=3, help="nb de notes hebdo DGEC (PDF) à lire pour les cotations Rotterdam")
    p.add_argument("--trv-kwh", type=float, default=3500.0)
    p.add_argument("--trv-kva", type=int, default=6)
    p.add_argument("--offline", action="store_true", help="n'utiliser que le cache .cache_prix_energie/")
    p.add_argument("--note", action="append", default=[], help="note libre à reporter dans le journal")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(levelname)s %(message)s")

    from prix_energie.modele.assemblage import Bundle, build          # import après réglage TLS
    from prix_energie.donnees.fetch import TLS_MODE
    from prix_energie.journal import Journal
    from prix_energie.config import Choices
    from prix_energie.donnees.contracts import ContractError
    from prix_energie.donnees.tidy import read_csvs, write_csvs
    log = logging.getLogger("prix_energie")
    log.info("TLS : %s", TLS_MODE)

    choices = Choices(start=a.start, sp_e10_chain=a.e10_chain, npg_weeks=a.npg_weeks,
                      trv_ref_kwh=a.trv_kwh, trv_power_kva=a.trv_kva, notes=a.note,
                      ipc_ref=a.ipc_ref, ipc_csv=a.ipc_csv, ipc_idbank_2025=a.ipc_idbank_2025,
                      ipc_csv_2025=a.ipc_csv_2025, dgec_base=a.dgec_base)

    # --- figures seules : on repart des CSV, sans réseau ni parsing
    if a.only == "figures":
        bundle = read_csvs(a.data, Bundle(choices=choices, journal=Journal()))
        try:
            _dessiner(bundle, a.site)
        except SiteIncomplet as e:
            log.error("%s", e)
            return 4
        return 0

    try:
        bundle = build(choices, offline=a.offline)
    except ContractError as e:
        # Un contrat violé veut dire « les chiffres seraient faux », pas « il manque
        # une option » : on s'arrête au lieu de livrer un résultat d'apparence normale.
        log.error("Contrat de source non respecté : %s", e)
        return 2

    if a.only == "fetch":
        print("Téléchargements à jour dans le cache.")
        return 0

    written, ecarts = write_csvs(bundle, a.data, dialect=a.csv_dialect, sur_perte=a.sur_perte)
    bloquants = [e for e in ecarts if e.nature == "PERTE"]
    n_figures = 0
    if a.only == "all":
        try:
            n_figures = _dessiner(bundle, a.site)
        except SiteIncomplet as e:
            log.error("%s", e)
            return 4

    if a.xlsx:
        from prix_energie.donnees.excel import write_workbook
        out = write_workbook(bundle, a.xlsx)
        print(f"Classeur écrit : {out}")

    _, notes = bundle.journal.to_frames()
    n_err = int((notes["Type"] == "ERREUR").sum()) if len(notes) else 0
    n_ind = int((notes["Type"] == "INDISPONIBLE").sum()) if len(notes) else 0
    if bloquants:
        print(f"\n{len(bloquants)} perte(s) de données détectée(s) : fichiers NON écrasés :")
        for e in bloquants:
            print(f"  {e}")
        print("Comparer avec les .nouveau.csv, puis relancer avec --sur-perte ecraser si c'est voulu.")

    print(f"{len(written)} CSV et {n_figures} figure(s) dans {a.data} et {a.site}  "
          f"({n_err} erreur(s) de source, {n_ind} composante(s) indisponible(s) – voir _notes.csv)")
    # 3 = les données en place ont été préservées, il y a un arbitrage à faire.
    # 4 = le site serait incomplet : catalogue ou marqueur de page non satisfait.
    return 3 if bloquants else (1 if n_err else 0)
