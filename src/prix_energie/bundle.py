"""Le contrat de données : ce que l'assemblage produit et que tout le reste lit.

Ce module n'appartient à aucune couche. Tant que Bundle vivait dans le calcul,
les écrivains de CSV devaient importer le calcul pour connaître la forme de ce
qu'ils écrivent, ce qui refermait un cycle entre `donnees` et `modele`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from prix_energie.journal import Journal
from prix_energie.config import Choices


@dataclass
class Bundle:
    choices: Choices
    journal: Journal
    gazole: pd.DataFrame | None = None       # mensuel
    sansplomb: pd.DataFrame | None = None    # mensuel chaîné E5→E10
    sp_e5: pd.DataFrame | None = None        # mensuel E5 seul (WOB)
    sp_e10_dgec: pd.DataFrame | None = None  # mensuel E10 seul (DGEC 2020→)
    elec_semestriel: pd.DataFrame | None = None
    elec_composantes: pd.DataFrame | None = None
    elec_composantes_labels: dict = field(default_factory=dict)
    elec_ancienne: pd.DataFrame | None = None
    elec_bandes: pd.DataFrame | None = None
    elec_bandes_labels: dict = field(default_factory=dict)
    trv: pd.DataFrame | None = None
    brent: pd.DataFrame | None = None
    brent_source: str = ""
    marge: pd.DataFrame | None = None
    td_annuel: pd.DataFrame | None = None
    cotations: pd.DataFrame | None = None
    wob_weekly: pd.DataFrame | None = None
    ipc: pd.DataFrame | None = None
    dgec_base: pd.DataFrame | None = None
    cout_km: pd.DataFrame | None = None
    stations: pd.DataFrame | None = None
    elec_mensuel: pd.DataFrame | None = None
