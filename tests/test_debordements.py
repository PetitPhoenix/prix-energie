"""Aucun texte ne sort du cadre des images du fil.

Ces images sont vues seules, en petit, et personne ne les ouvre pour vérifier qu'un
titre n'est pas coupé. Le défaut est arrivé en figeant la police : DejaVu Sans est
plus large que celle qui servait avant, et trois figures ont perdu la fin de leur
titre ou le début d'un libellé sans que rien ne le signale.

Le contrôle mesure le rectangle de chaque texte rendu et le compare au cadre. Il ne
porte que sur le jeu social : les figures du dossier sont enregistrées en `bbox
tight`, qui élargit l'image plutôt que de rogner le texte.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from prix_energie.bundle import Bundle  # noqa: E402
from prix_energie.chemins import DONNEES  # noqa: E402
from prix_energie.config import Choices  # noqa: E402
from prix_energie.donnees.tidy import read_csvs  # noqa: E402
from prix_energie.journal import Journal  # noqa: E402
from prix_energie.viz import feed  # noqa: E402

MARGE = 1.0   # un pixel de tolérance, le rendu n'est pas au demi-pixel près


@pytest.fixture(scope="module")
def bundle() -> Bundle:
    return read_csvs(DONNEES, Bundle(choices=Choices(), journal=Journal()))


def _figures(b: Bundle, out: Path):
    return [
        ("prix_reel", lambda: feed.prix_reel(b.sansplomb, out, "x")),
        ("part_taxes", lambda: feed.part_taxes(
            {"Sans-plomb": b.sansplomb, "Gazole": b.gazole,
             "Électricité": b.elec_mensuel}, out, "x")),
        ("aval", lambda: feed.aval(b.sansplomb, b.gazole, out, "x")),
        ("cascade", lambda: feed.cascade(b.sansplomb, b.stations, out, "x")),
        ("cout_100km", lambda: feed.cout_km(b.cout_km, out, "x")),
    ]


def _textes_hors_cadre(fig) -> list[tuple[int, str]]:
    fig.canvas.draw()
    rendu = fig.canvas.get_renderer()
    larg, haut = fig.get_size_inches() * fig.dpi
    fautes = []

    def examiner(artiste) -> None:
        if not artiste.get_text().strip():
            return
        bb = artiste.get_window_extent(rendu)
        debord = max(-bb.x0, bb.x1 - larg, -bb.y0, bb.y1 - haut)
        if debord > MARGE:
            fautes.append((round(debord), artiste.get_text()[:60].replace("\n", " ")))

    for ax in fig.axes:
        # Matplotlib conserve des graduations hors des limites de l'axe : elles ne
        # sont pas dessinées, les compter donnerait de faux débordements.
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        visibles = [t for t, v in zip(ax.get_xticklabels(), ax.get_xticks())
                    if x0 <= v <= x1]
        visibles += [t for t, v in zip(ax.get_yticklabels(), ax.get_yticks())
                     if y0 <= v <= y1]
        for a in [*ax.texts, ax.title, ax.xaxis.label, ax.yaxis.label, *visibles]:
            examiner(a)
        if ax.get_legend():
            for a in ax.get_legend().get_texts():
                examiner(a)
    for a in fig.texts:
        examiner(a)
    return fautes


@pytest.mark.parametrize("nom", ["prix_reel", "part_taxes", "aval", "cascade",
                                 "cout_100km"])
def test_aucun_texte_ne_sort_du_cadre(nom: str, bundle: Bundle, tmp_path: Path) -> None:
    construire = dict(_figures(bundle, tmp_path))[nom]
    gardees: list = []
    vrai_ecrire = feed._ecrire

    def capturer(fig, outdir, stem):
        # `_ecrire` ferme la figure : on l enregistre nous-mêmes et on la garde
        # ouverte, sinon la mesure porterait sur une figure vide et passerait
        # toujours.
        gardees.append(fig)
        outdir.mkdir(parents=True, exist_ok=True)
        chemin = outdir / f"{stem}.png"
        fig.savefig(chemin, dpi=feed.DPI)
        return chemin

    feed._style()
    feed._ecrire = capturer
    try:
        construire()
        assert gardees, f"{nom} n'a produit aucune figure"
        # Mesurer avant de fermer : une figure fermee perd son moteur de rendu.
        fautes = _textes_hors_cadre(gardees[0])
    finally:
        feed._ecrire = vrai_ecrire
        plt.close("all")
    assert not fautes, "\n".join(f"{px} px de trop : « {txt} »" for px, txt in fautes)
