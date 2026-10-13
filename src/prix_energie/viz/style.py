"""Palette, feuille de style et chrome commun à toutes les figures."""

from __future__ import annotations

import textwrap

import matplotlib.pyplot as plt
import pandas as pd


SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
BLEUS = ["#164a8c", "#2a78d6", "#71a8e6", "#b3cff3"]
BLOC_INDETERMINE = "#9aa7b4"
COMPOSANTES = [
    ("cotation", "Cotation Rotterdam"),
    ("transport_distribution", "Transport-distribution"),
    ("ht_non_decompose", "Hors taxes"),
    ("accise", "Taxes hors TVA"),
    ("tva", "TVA"),
]
FIGSIZE = (11, 5.5)
DEBUT_DOSSIER = pd.Timestamp("2005-01-01")
PLAGE = {"debut": DEBUT_DOSSIER, "fin": None}


def _style() -> None:
    plt.rcParams.update({
        # Police unique, livree avec matplotlib : une police du systeme ferait
        # dependre le rendu de la machine, donc differer entre le poste et la forge
        # qui publie.
        "font.family": ["DejaVu Sans"],
        "font.size": 9,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK_2,
        "axes.titlecolor": INK,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": INK_2,
        "ytick.labelcolor": INK_2,
        "legend.frameon": False,
        "lines.linewidth": 2.0,
        "savefig.dpi": 160,
        "savefig.bbox": "tight",
    })


def _finish(ax, title: str, ylabel: str, source: str) -> None:
    """Chrome commun : titre à gauche, axes discrets, mention de source.

    La note de source est ancrée au coin bas-gauche des *axes*, pas de la figure.
    Posée à x=0 de la figure elle débordait à gauche de la zone de tracé : plus à
    gauche que les étiquettes de l'axe Y : et le recadrage automatique s'alignait
    alors sur elle, décalant visuellement tous les graphiques vers la droite.
    """
    ax.set_title(title, pad=12)
    ax.set_ylabel(ylabel, color=INK_2)
    ax.set_xlabel("")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.grid(axis="x", visible=False)
    # Repliée à une largeur fixe : une note d'une seule ligne dépasserait à droite
    # et provoquerait le défaut symétrique.
    ax.annotate(textwrap.fill(source, 128), xy=(0, 0), xycoords="axes fraction",
                xytext=(0, -52), textcoords="offset points",
                fontsize=7.5, color=MUTED, ha="left", va="top", annotation_clip=False)
