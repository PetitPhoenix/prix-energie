"""Les dossiers du projet, nommés une fois.

Deux natures à ne pas confondre. `data/` contient les séries normalisées : elles sont
versionnées, parce qu'un producteur révise ses chiffres et retire ses archives, et
qu'un CSV daté dans un commit est la seule trace de ce qui était publié ce jour-là.
`site/` contient ce qui s'en déduit, pages et figures : régénérable à l'identique,
donc reconstruit par la forge plutôt que stocké.

Le chemin de la racine se trouve par un marqueur et non par un nombre de niveaux :
compter les parents cassait à chaque déplacement de module.
"""
from __future__ import annotations

from pathlib import Path


def racine() -> Path:
    """La racine du dépôt, reconnue à son pyproject.toml."""
    for d in Path(__file__).resolve().parents:
        if (d / "pyproject.toml").exists():
            return d
    raise RuntimeError("racine du dépôt introuvable : pas de pyproject.toml")


RACINE = racine()

DONNEES = RACINE / "data"
SITE = RACINE / "site"
FIGURES = SITE / "figures"
FEED = SITE / "feed"
CONTENU = RACINE / "contenu"
