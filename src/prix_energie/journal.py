"""Compte rendu de l'exécution : le logger, et le journal publié dans le dossier.

Journal n'est pas un logger : il accumule des enregistrements structurés qui
deviennent les tableaux des sources et des notes du dossier publié. Le logger,
lui, ne sert qu'à la console. Les deux rendent compte, d'où leur voisinage.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

log = logging.getLogger("prix_energie")


@dataclass
class Journal:
    """Collecte tout ce que le classeur doit signaler : sources, ruptures, indisponibilités."""
    sources: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)

    def source(self, serie: str, producteur: str, url: str, detail: str = "") -> None:
        self.sources.append({"Série": serie, "Producteur": producteur, "URL": url, "Détail": detail})

    def note(self, kind: str, serie: str, message: str) -> None:
        """kind ∈ {RUPTURE, DEFINITION, PROVISOIRE, INDISPONIBLE, METHODE, ERREUR}.

        Les notes strictement identiques sont fusionnées : plusieurs séries partagent
        les mêmes contrôles (déflateur, contrats), et les répéter noierait le journal.
        """
        entry = {"Type": kind, "Série": serie, "Message": message}
        if entry in self.notes:
            return
        self.notes.append(entry)
        (log.warning if kind in ("ERREUR", "INDISPONIBLE") else log.info)("[%s] %s – %s", kind, serie, message)

    def to_frames(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        return pd.DataFrame(self.sources), pd.DataFrame(self.notes)
