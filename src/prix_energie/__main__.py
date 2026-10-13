"""Répartiteur des sous-commandes : python -m prix_energie <commande> [options].

Une commande par domaine. La construction des séries et l'assemblage des pages sont
séparés parce qu'on réassemble souvent les pages sans retoucher aux données.
"""
from __future__ import annotations

import sys

COMMANDES = {
    "build": ("construire les CSV et les figures", "prix_energie.cli.pipeline"),
    "pages": ("assembler les pages à partir des contenus", "prix_energie.cli.pages"),
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.splitlines()[0])
        print("\nCommandes :")
        for nom, (aide, _) in COMMANDES.items():
            print(f"  {nom:8s} {aide}")
        return 0
    commande = sys.argv[1]
    if commande not in COMMANDES:
        print(f"commande inconnue : {commande}", file=sys.stderr)
        return 2
    # argv est réécrit pour que l'argparse de la sous-commande voie son propre nom.
    sys.argv = [f"prix-energie {commande}"] + sys.argv[2:]
    import importlib
    module = importlib.import_module(COMMANDES[commande][1])
    return module.main() or 0


if __name__ == "__main__":
    raise SystemExit(main())
