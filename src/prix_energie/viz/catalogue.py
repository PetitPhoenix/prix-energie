"""Les figures que le site doit contenir.

Une figure ne disparaît pas sans qu'on l'ait décidé : `build` compare ce qu'il vient de
dessiner à cette liste et s'arrête sur tout écart. Le cas s'est produit avant que la liste
existe : les générateurs de deux figures de l'électricité ont été perdus sans que rien ne
le signale, alors que leurs données étaient toujours là. `write_figures` saute aussi une
figure dont la série manque ; sans ce contrôle, la figure disparaîtrait du site en silence.

Ajouter une figure, c'est l'ajouter ici ; en retirer une, c'est la retirer ici, dans le
même commit.
"""
from __future__ import annotations

from pathlib import Path

FIGURES = (
    "accises_comparees",
    "accises_comparees_constants",
    "aval_petrolier",
    "brent",
    "brent_constants",
    "cascade_couts",
    "controle_sources",
    "courant_vs_constant",
    "cout_100km",
    "cout_100km_constants",
    "cout_100km_indice",
    "electricite_bandes_consommation",
    "electricite_barres",
    "electricite_barres_constants",
    "electricite_composantes",
    "electricite_decomposition",
    "electricite_decomposition_constants",
    "electricite_hors_taxes",
    "electricite_hors_taxes_constants",
    "electricite_taxes",
    "electricite_taxes_constants",
    "electricite_taxes_detail",
    "energie_constant",
    "energie_courant",
    "gazole_barres",
    "gazole_barres_constants",
    "gazole_barres_part",
    "gazole_decomposition",
    "gazole_decomposition_constants",
    "gazole_hors_taxes",
    "gazole_hors_taxes_constants",
    "gazole_taxes",
    "gazole_taxes_constants",
    "inflation",
    "part_taxes",
    "postes_dispersion",
    "sansplomb_barres",
    "sansplomb_barres_constants",
    "sansplomb_barres_part",
    "sansplomb_decomposition",
    "sansplomb_decomposition_constants",
    "sansplomb_hors_taxes",
    "sansplomb_hors_taxes_constants",
    "sansplomb_taxes",
    "sansplomb_taxes_constants",
    "serie_longue",
    "solde_compare",
    "solde_compare_constants",
    "zoom_12m_gazole",
    "zoom_12m_sansplomb",
)

FEED = (
    "aval",
    "cascade",
    "cout_100km",
    "part_taxes",
    "prix_reel",
)


def ecarts(attendu: tuple[str, ...], produit: list[Path]) -> list[str]:
    """Ce qui manque et ce qui est en trop, en clair. Vide si tout correspond."""
    obtenu = {p.stem for p in produit}
    manquantes = sorted(set(attendu) - obtenu)
    en_trop = sorted(obtenu - set(attendu))
    out = []
    if manquantes:
        out.append("absentes : " + ", ".join(manquantes))
    if en_trop:
        out.append("hors catalogue : " + ", ".join(en_trop))
    return out
