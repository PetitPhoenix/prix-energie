"""Les images du fil assemblées en un PDF, pour un post LinkedIn de type document.

Un post à plusieurs images les dispose en mosaïque : cinq graphiques y deviennent
cinq vignettes, et aucune n'est lisible. Un post document affiche une page à la fois,
en pleine largeur, et le lecteur fait défiler. C'est le seul format de la plateforme
qui rende un graphique lisible sur mobile sans qu'on zoome.

L'ordre suit celui du fil : chaque page correspond à un message, et la dernière
renvoie au dossier.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from prix_energie.journal import log

# L'ordre est celui du raisonnement, pas celui des fichiers.
PAGES = ["prix_reel", "part_taxes", "aval", "cascade", "cout_100km"]


def construire(feed_dir: Path, sortie: Path) -> Path | None:
    """Assemble les PNG du fil en un PDF, une image par page."""
    images = []
    for nom in PAGES:
        f = feed_dir / f"{nom}.png"
        if not f.exists():
            log.warning("Carrousel : %s absent, page ignorée", f.name)
            continue
        # Le PDF ne porte pas d'alpha : on aplatit sur blanc plutôt que de laisser
        # le convertisseur choisir, ce qu'il fait en noir une fois sur deux.
        im = Image.open(f).convert("RGBA")
        fond = Image.new("RGB", im.size, (255, 255, 255))
        fond.paste(im, mask=im.split()[3])
        images.append(fond)
    if not images:
        return None
    sortie.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(sortie, "PDF", resolution=160.0, save_all=True,
                   append_images=images[1:])
    log.info("Carrousel : %s (%d pages)", sortie.name, len(images))
    return sortie
