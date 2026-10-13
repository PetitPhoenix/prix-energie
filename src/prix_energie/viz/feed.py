"""Second jeu de figures, destiné aux fils sociaux.

Les figures du dossier sont faites pour un écran large et une lecture suivie : six
séries, des légendes fines, une note de méthode sous l'axe. Dans une timeline, l'image
est vue petite et souvent sans le texte qui l'accompagne, et personne ne zoome.

Quatre règles, tirées de cette contrainte et non d'une préférence graphique :

- paysage 16:10 plutôt que 16:9, parce que le carré se fait recadrer et que le 16:9
  devient une bande illisible sur mobile ;
- trois séries au maximum, l'inverse de l'exhaustivité du dossier ;
- un titre qui décrit ce que montre la figure, sans commentaire : le post porte
  l'argument, l'image porte la mesure ;
- le point clé annoté sur la courbe, pas renvoyé à une légende.

Ce module ne réutilise pas les fonctions de `figures` : il en reprend la palette et
les données, mais chaque figure y est simplifiée différemment, et un paramètre de
plus sur chaque fonction du dossier aurait coûté plus cher que cette redite.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from prix_energie.journal import log
from prix_energie.viz.style import AXIS, BLEUS, GRID, INK, INK_2, MUTED, SERIES, SURFACE

FIGSIZE = (10.0, 6.25)   # 16:10, soit 1600x1000 à 160 dpi
# Au-delà, une ligne de source sort du cadre sans que matplotlib ne replie
# ni ne prévienne. Mesuré sur la police et la taille retenues ici.
LARGEUR_SOURCE = 110
DPI = 160


def _style() -> None:
    """Mêmes couleurs que le dossier, tout le reste à l'échelle du pouce carré."""
    plt.rcParams.update({
        # Police unique, livree avec matplotlib : une police du systeme ferait
        # dependre le rendu de la machine, donc differer entre le poste et la forge
        # qui publie.
        "font.family": ["DejaVu Sans"],
        "font.size": 17,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK_2,
        "axes.labelsize": 15,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 1.0,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": INK_2,
        "ytick.labelcolor": INK_2,
        "xtick.labelsize": 15,
        "ytick.labelsize": 15,
        "legend.frameon": False,
        "legend.fontsize": 15,
        "lines.linewidth": 3.2,
        "savefig.dpi": DPI,
        # Le dossier enregistre en bbox « tight », et ces rcParams sont globaux : sans
        # cette remise à zéro, chaque image du fil se fait rogner selon son contenu et
        # la série perd le cadrage commun que `_cadre` installe.
        "savefig.bbox": None,
    })


def _fr(x: float, n: int = 2) -> str:
    """Nombre à la française. Matplotlib formate en anglais, et un « 2.12 € » dans une
    image destinée à un fil francophone se voit immédiatement."""
    return f"{x:.{n}f}".replace(".", ",")


def _cadre(titre: str, gauche: float = 0.085, bas: float = 0.16):
    """Un titre, puis l'aire de tracé. Pas de ligne de commentaire sous le titre.

    L'image accompagne un texte qui porte déjà l'argument : une phrase de conclusion
    gravée dans le PNG la répéterait, et elle vieillirait mal puisqu'elle fige une
    lecture que le prochain mois de données peut démentir.
    """
    fig = plt.figure(figsize=FIGSIZE)
    fig.text(0.055, 0.945, titre, fontsize=23, fontweight="bold", color=INK,
             ha="left", va="top")
    # `gauche` s'élargit quand les étiquettes sont portées par l'axe des ordonnées :
    # des noms de postes ne tiennent pas dans la marge prévue pour des années.
    # `bas` laisse sous les graduations la place des lignes de `_source` : à 0,115,
    # les années de l'axe et la ligne des sources s'écrivaient l'une sur l'autre.
    ax = fig.add_axes((gauche, bas, 0.90 - gauche, 0.85 - bas))
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="x", visible=False)
    return fig, ax


def _source(fig, *lignes: str) -> None:
    """Autant de lignes que la méthode en demande, empilées vers le bas.

    Une seule ligne à cette taille dépasse la largeur de l'image au-delà d'environ
    cent dix caractères, et matplotlib ne replie pas : le texte sort du cadre sans
    prévenir. Chaque ligne est donc posée séparément.
    """
    # Empilées vers le bas depuis le haut du bandeau : la dernière doit rester dans
    # le cadre, et c'est elle qui sortait quand on empilait depuis le bas.
    for i, ligne in enumerate(lignes):
        if len(ligne) > LARGEUR_SOURCE:
            raise ValueError(f"ligne de source trop longue ({len(ligne)}) : {ligne[:40]}")
        fig.text(0.055, 0.085 - 0.024 * i, ligne, fontsize=12, color=MUTED,
                 ha="left", va="center")


def _bout(ax, x, serie, couleur, texte: str) -> None:
    """Valeur de fin, posée sur la courbe : la légende ne porte que les noms."""
    v = serie.dropna()
    if not len(v):
        return
    ax.annotate(texte, xy=(x[v.index[-1]], v.iloc[-1]), xytext=(10, 0),
                textcoords="offset points", fontsize=18, fontweight="bold",
                color=couleur, va="center", clip_on=False)


def _ecrire(fig, outdir: Path, stem: str) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{stem}.png"
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------------------
# Les cinq images du fil
# --------------------------------------------------------------------------------------

def prix_reel(sansplomb, outdir: Path, stem: str) -> Path | None:
    """Un seul carburant, deux lectures du même prix."""
    if sansplomb is None or "ttc_constants" not in sansplomb.columns:
        return None
    x = pd.to_datetime(sansplomb["mois"])
    courant = pd.to_numeric(sansplomb["ttc"], errors="coerce") / 100.0
    constant = pd.to_numeric(sansplomb["ttc_constants"], errors="coerce") / 100.0
    if not courant.notna().any():
        return None

    fig, ax = _cadre("Le prix du sans-plomb, avant et après inflation")
    ax.plot(x, constant, color=MUTED, linestyle=(0, (4, 3)),
            label="en pouvoir d'achat d'aujourd'hui")
    ax.plot(x, courant, color=SERIES[0], label="en euros du jour")
    _bout(ax, x, courant, SERIES[0], f"{_fr(courant.dropna().iloc[-1])} €")
    haut = constant.idxmax()
    ax.annotate(f"{_fr(constant.max())} € en {x[haut]:%Y}", xy=(x[haut], constant.max()),
                xytext=(0, 14), textcoords="offset points", fontsize=16,
                color=MUTED, ha="center")
    ax.set_ylim(0, float(max(courant.max(), constant.max())) * 1.2)
    ax.set_ylabel("€ par litre")
    ax.legend(loc="lower left", ncols=2)
    _source(fig, "Sources : Weekly Oil Bulletin, DGEC, INSEE.")
    return _ecrire(fig, outdir, stem)


def part_taxes(series: dict, outdir: Path, stem: str) -> Path | None:
    """La part de la fiscalité, seule grandeur comparable entre un litre et un kWh."""
    fig, ax = _cadre("Part des taxes dans le prix payé")
    tracees = 0
    for (nom, df), couleur in zip(series.items(), SERIES):
        if df is None or "ttc" not in df.columns:
            continue
        ttc = pd.to_numeric(df["ttc"], errors="coerce")
        if "accise" in df.columns and "tva" in df.columns:
            taxes = (pd.to_numeric(df["accise"], errors="coerce")
                     + pd.to_numeric(df["tva"], errors="coerce"))
        elif "hors_taxes" in df.columns:
            taxes = ttc - pd.to_numeric(df["hors_taxes"], errors="coerce")
        else:
            continue
        part = 100.0 * taxes / ttc
        if not part.notna().any():
            continue
        col = "mois" if "mois" in df.columns else "periode"
        x = pd.to_datetime(df[col])
        ax.plot(x, part, color=couleur, label=nom)
        _bout(ax, x, part, couleur, f"{part.dropna().iloc[-1]:.0f} %")
        tracees += 1
    if not tracees:
        plt.close(fig)
        return None
    ax.set_ylim(0, 100)
    ax.set_ylabel("% du prix payé")
    ax.legend(loc="lower left", ncols=3)
    _source(fig, "Sources : Weekly Oil Bulletin, DGEC, Eurostat.")
    return _ecrire(fig, outdir, stem)


def aval(sansplomb, gazole, outdir: Path, stem: str) -> Path | None:
    """Le prix hors taxes moins le brut, face au brut lui-même."""
    if sansplomb is None or "ht_constants" not in sansplomb.columns:
        return None
    fig, ax = _cadre("Du baril au réservoir, en centimes par litre")
    for df, couleur, nom in ((sansplomb, SERIES[0], "Sans-plomb"),
                             (gazole, SERIES[1], "Gazole")):
        if df is None or "ht_constants" not in df.columns:
            continue
        x = pd.to_datetime(df["mois"])
        v = (pd.to_numeric(df["ht_constants"], errors="coerce")
             - pd.to_numeric(df["brent_ceur_l_constants"], errors="coerce"))
        ax.plot(x, v, color=couleur, label=nom)
        _bout(ax, x, v, couleur, f"{v.dropna().iloc[-1]:.0f}")
    x = pd.to_datetime(sansplomb["mois"])
    brut = pd.to_numeric(sansplomb["brent_ceur_l_constants"], errors="coerce")
    ax.plot(x, brut, color=MUTED, linewidth=2.4, label="Pétrole brut")
    ax.set_ylim(bottom=0)
    ax.set_ylabel("centimes par litre, euros constants")
    ax.legend(loc="upper left", ncols=3)
    _source(fig, "Prix hors taxes moins coût du brut. "
                 "Sources : Weekly Oil Bulletin, DGEC, INSEE.")
    return _ecrire(fig, outdir, stem)


def cascade(sansplomb, stations_df, outdir: Path, stem: str,
            mois_glissants: int = 12) -> Path | None:
    """Le prix construit poste par poste, chaque étape avec sa dispersion.

    Un empilement de barres dirait les niveaux et s'arrêterait là. Ce qui compte ici
    est ailleurs : une boîte qui se décale sans s'élargir signale un poste stable, une
    boîte qui s'élargit un poste qui bouge d'un mois à l'autre. L'accise est plate par
    construction, le brut et le raffinage portent presque toute la variation, et la
    dernière ligne change de nature puisqu'elle disperse des stations et non des mois.
    """
    if sansplomb is None or "ttc" not in sansplomb.columns:
        return None
    besoin = ["brent_ceur_l", "raffinage_ceur_l", "ht", "accise", "tva", "ttc"]
    if any(c not in sansplomb.columns for c in besoin):
        return None
    d = sansplomb.dropna(subset=besoin).tail(mois_glissants)
    if len(d) < 4:
        return None
    n = lambda c: pd.to_numeric(d[c], errors="coerce") / 100.0  # noqa: E731
    brut, raff, ht = n("brent_ceur_l"), n("raffinage_ceur_l"), n("ht")
    etapes = [("Pétrole brut", brut, BLEUS[0]),
              ("+ Raffinage", brut + raff, BLEUS[1]),
              ("+ Logistique et marges", ht, BLEUS[2]),
              ("+ Accise", ht + n("accise"), SERIES[1]),
              ("+ TVA", n("ttc"), SERIES[2])]

    donnees = [v.to_numpy() for _, v, _ in etapes]
    libelles = [lab for lab, _, _ in etapes]
    couleurs = [c for _, _, c in etapes]
    if stations_df is not None and "sansplomb" in stations_df.columns:
        v = pd.to_numeric(stations_df["sansplomb"], errors="coerce").dropna()
        if len(v) > 100:
            donnees.append(v.to_numpy())
            libelles.append("Prix en station")
            couleurs.append(MUTED)

    fig, ax = _cadre("Le prix d'un litre de sans-plomb, poste par poste",
                     gauche=0.285, bas=0.235)
    positions = [-i for i in range(len(donnees))]
    bp = ax.boxplot(donnees, positions=positions, vert=False, widths=0.56,
                    patch_artist=True, whis=(10, 90), showfliers=False,
                    zorder=3, medianprops={"color": SURFACE, "linewidth": 2.6})
    for boite, couleur in zip(bp["boxes"], couleurs):
        boite.set_facecolor(couleur)
        boite.set_edgecolor(couleur)
    for cle in ("whiskers", "caps"):
        for trait, couleur in zip(bp[cle], [c for c in couleurs for _ in (0, 1)]):
            trait.set_color(couleur)
            trait.set_linewidth(2.0)

    # D'une ligne à l'autre, l'écart entre les deux médianes est exactement le poste
    # qu'on vient d'ajouter. Sans trait pour le dire, cet écart se lit comme un trou
    # dans la figure plutôt que comme la mesure qu'il est.
    medianes = [float(pd.Series(v).median()) for v in donnees]
    n_couts = len(etapes)
    for i in range(1, len(donnees)):
        poste = i < n_couts
        ax.plot([medianes[i - 1], medianes[i]], [positions[i - 1], positions[i]],
                color=MUTED, linewidth=1.6, zorder=1,
                linestyle=(0, (4, 3)) if poste else (0, (1, 4)))
        if poste:
            ax.annotate(f"+ {_fr(medianes[i] - medianes[i - 1])} €",
                        xy=((medianes[i - 1] + medianes[i]) / 2,
                            (positions[i - 1] + positions[i]) / 2),
                        xytext=(0, 0), textcoords="offset points", ha="center",
                        va="center", fontsize=14, color=INK_2, zorder=2,
                        bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1.6})

    # Les médianes alignées en colonne, à droite du plus long tracé : posées au bout
    # de chaque boîte, elles formaient un escalier qu'on lisait avant les boîtes.
    droite = max(float(pd.Series(v).quantile(0.90)) for v in donnees)
    for y, med in zip(positions, medianes):
        ax.annotate(f"{_fr(med)} €", xy=(droite, y), xytext=(22, 0),
                    textcoords="offset points", va="center", ha="left",
                    fontsize=17, fontweight="bold", color=INK)

    ax.set_yticks(positions)
    ax.set_yticklabels(libelles, fontsize=16)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, droite * 1.22)
    ax.set_ylim(min(positions) - 0.6, 0.6)
    ax.set_xlabel("€ par litre, cumulé")
    ax.grid(axis="x", visible=True)
    ax.grid(axis="y", visible=False)
    for side in ("left",):
        ax.spines[side].set_visible(False)
    _source(fig,
            f"Boîte : moitié centrale des {mois_glissants} derniers mois. "
            "Dernière ligne : des stations, non des mois.",
            "Sources : Weekly Oil Bulletin, DGEC, data.economie.gouv.fr.")
    return _ecrire(fig, outdir, stem)


def cout_km(cout, outdir: Path, stem: str) -> Path | None:
    """Le coût au kilomètre, et la forme en escalier du prix administré."""
    if cout is None or "essence" not in cout.columns:
        return None
    x = pd.to_datetime(cout["mois"])
    fig, ax = _cadre("Coût de 100 kilomètres par motorisation")
    for col, couleur, nom in (("essence", SERIES[0], "Essence"),
                              ("diesel", SERIES[1], "Gazole"),
                              ("electrique", SERIES[2], "Électrique")):
        if col not in cout.columns:
            continue
        v = pd.to_numeric(cout[col], errors="coerce")
        if not v.notna().any():
            continue
        ax.plot(x, v, color=couleur, label=nom)
        _bout(ax, x, v, couleur, f"{_fr(v.dropna().iloc[-1])} €")
    ax.set_ylim(bottom=0)
    ax.set_ylabel("€ pour 100 km, euros du jour")
    ax.legend(loc="upper left", ncols=3)
    _source(fig, "Consommations conventionnelles, recharge à domicile au tarif réglementé.",
                 "Sources : Weekly Oil Bulletin, CRE.")
    return _ecrire(fig, outdir, stem)


def generer(bundle, outdir: Path) -> list[Path]:
    """Les cinq images du fil, dans `sortie/feed`."""
    _style()
    out = []
    for p in (prix_reel(bundle.sansplomb, outdir, "prix_reel"),
              part_taxes({"Sans-plomb": bundle.sansplomb, "Gazole": bundle.gazole,
                          "Électricité": bundle.elec_mensuel}, outdir, "part_taxes"),
              aval(bundle.sansplomb, bundle.gazole, outdir, "aval"),
              cascade(bundle.sansplomb, bundle.stations, outdir, "cascade"),
              cout_km(bundle.cout_km, outdir, "cout_100km")):
        if p:
            out.append(p)
            log.info("Figure feed : %s", p.name)
    return out
