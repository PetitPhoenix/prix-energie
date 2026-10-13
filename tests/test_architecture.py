"""Les couches ne s'importent que vers le bas.

Le découpage en `donnees`, `modele` et `viz` ne vaut que s'il tient dans le temps. Un
import ajouté sans y penser le défait sans rien casser à l'exécution : le cycle se
voit des mois plus tard, quand on veut déplacer un fichier et que tout suit.

Ce test lit les imports plutôt que de les exécuter : il ne dépend d'aucune donnée et
reste rapide même quand le pipeline ne tourne pas.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "prix_energie"

# Ce que chaque couche a le droit d'importer. La racine (`common`, `config`,
# `bundle`) est accessible à toutes : elle ne contient que des définitions
# partagées, sans calcul ni dessin.
AUTORISE = {
    "donnees": {"racine"},
    "modele": {"donnees", "racine"},
    "viz": {"modele", "donnees", "racine"},
    "cli": {"viz", "modele", "donnees", "racine"},
    "racine": {"racine"},
}


def couche(module: str) -> str:
    """La couche d'un module, d'après la première composante de son chemin."""
    if module.startswith("prix_energie."):
        module = module[len("prix_energie."):]
    tete = module.split(".")[0]
    return tete if tete in AUTORISE else "racine"


def imports_internes() -> list[tuple[str, str, str, str]]:
    """(fichier, couche source, module importé, couche cible) pour le paquet."""
    out = []
    for p in sorted(SRC.rglob("*.py")):
        rel = p.relative_to(SRC).with_suffix("").as_posix().replace("/", ".")
        source = couche(rel)
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ImportFrom) and n.module \
               and n.module.startswith("prix_energie"):
                out.append((rel, source, n.module, couche(n.module)))
    return out


@pytest.mark.parametrize("couche_source", sorted(AUTORISE))
def test_une_couche_n_importe_que_vers_le_bas(couche_source: str) -> None:
    fautes = [f"{fichier} importe {module}"
              for fichier, source, module, cible in imports_internes()
              if source == couche_source
              and cible != couche_source
              and cible not in AUTORISE[couche_source]]
    assert not fautes, (
        f"la couche « {couche_source} » ne peut importer que "
        f"{sorted(AUTORISE[couche_source])} :\n  " + "\n  ".join(fautes))


def test_aucun_cycle_entre_couches() -> None:
    liens: dict[str, set[str]] = {}
    for _, source, _, cible in imports_internes():
        if source != cible:
            liens.setdefault(source, set()).add(cible)
    cycles = sorted({tuple(sorted((a, b)))
                     for a, vers in liens.items()
                     for b in vers if a in liens.get(b, set())})
    assert not cycles, "couches qui s'importent mutuellement : " + str(cycles)


def test_tous_les_imports_du_paquet_sont_absolus() -> None:
    """Un import relatif change de sens quand le fichier se déplace.

    C'est ce qui a rendu pénible le passage en `src/` : `.style` ne désigne pas le
    même module selon le paquet d'où il est écrit.
    """
    relatifs = []
    for p in sorted(SRC.rglob("*.py")):
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ImportFrom) and n.level:
                relatifs.append(f"{p.relative_to(SRC)}:{n.lineno}")
    assert not relatifs, "imports relatifs : " + ", ".join(relatifs)
