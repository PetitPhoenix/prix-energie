"""Figures de contrôle : déflateur, recoupement des sources, série longue."""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from prix_energie.bundle import Bundle

from prix_energie.viz.style import AXIS, DEBUT_DOSSIER, FIGSIZE, INK, INK_2, PLAGE, SERIES, _finish
from prix_energie.viz.figures.communs import _marquer_fin, _plage, _rupture


def inflation(ipc: pd.DataFrame | None, outdir: Path, stem: str) -> Path | None:
    """L'indice des prix, et ce que le changement de base lui fait.

    Les trois courbes sont tracées à leur valeur *publiée*, non ramenées à une base
    commune : c'est la seule façon de voir pourquoi la base 2025 passe plus bas. Elle
    ne mesure pas une inflation plus faible : elle compte à partir de 2025, quand la
    base 2015 comptait depuis 2015 et avait déjà accumulé vingt points.
    """
    if ipc is None or not len(ipc) or "ipc_base2015" not in ipc.columns:
        return None
    x = pd.to_datetime(ipc["date"])
    num = lambda c: pd.to_numeric(ipc[c], errors="coerce") if c in ipc.columns else None  # noqa: E731
    utilisee = num("ipc_base2015")
    b2015, b2025 = num("ipc_avant_raccord"), num("ipc_base2025_publie")
    bascule = None
    if "bascule_base" in ipc.columns and ipc["bascule_base"].notna().any():
        bascule = pd.to_datetime(ipc["bascule_base"].dropna().iloc[0])

    fig, ax = plt.subplots(figsize=FIGSIZE)
    for serie, couleur, libelle in ((b2015, SERIES[0], "Base 2015, telle que publiée"),
                                    (b2025, SERIES[2], "Base 2025, telle que publiée")):
        if serie is not None and serie.notna().any():
            ax.plot(x, serie, color=couleur, linewidth=3.4, alpha=0.4, label=libelle)
    # La série retenue passe par-dessus, en trait fin : on la voit suivre la base 2015,
    # puis prendre le relais de la base 2025 une fois celle-ci remontée au même niveau.
    ax.plot(x, utilisee, color=INK, linewidth=1.5, label="Série retenue dans le dossier")

    if bascule is not None:
        _rupture(ax, bascule, "changement de base", False)
        ligne = ipc.loc[x == bascule]
        if len(ligne) and b2025 is not None and ligne["ipc_base2025_publie"].notna().all():
            v15 = float(ligne["ipc_base2015"].iloc[0])
            v25 = float(ligne["ipc_base2025_publie"].iloc[0])
            if v25:
                ax.plot([bascule, bascule], [v25, v15], color=INK_2, linewidth=1.0)
                ecart = "x{:.4f}".format(v15 / v25)
                ax.annotate(ecart, xy=(bascule, (v15 + v25) / 2), xytext=(-26, 0),
                            textcoords="offset points", ha="right", va="center",
                            fontsize=8, color=INK_2)

    ax.set_xlim(*_plage(x.min(), x.max()))
    ax.set_ylim(bottom=0)
    _marquer_fin(ax, x.max())
    ax.legend(loc="upper left", ncols=3, fontsize=8, labelcolor=INK_2)
    _finish(ax, "Indice des prix à la consommation", "indice, valeur publiée",
            "Source : INSEE, IPC ensemble des ménages, France.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def serie_longue(bundle: Bundle, outdir: Path, stem: str) -> Path | None:
    """Les trois séries qui remontent avant le dossier, ramenées à une base commune.

    IPC, Brent et électricité commencent au début des années 1990, quinze ans avant
    les carburants. Comme leurs unités n'ont rien de comparable : un indice, un baril,
    un kilowattheure : seule une base 100 les met sur un même axe. La verticale de
    2005 rappelle où commence le reste du dossier.
    """
    series = []
    if bundle.ipc is not None and "ipc_base2015" in bundle.ipc.columns:
        series.append(("Inflation (IPC)", pd.to_datetime(bundle.ipc["date"]),
                       pd.to_numeric(bundle.ipc["ipc_base2015"], errors="coerce")))
    if bundle.brent is not None and "brent_eur_bbl" in bundle.brent.columns:
        series.append(("Brent (€/baril)", pd.to_datetime(bundle.brent["date"]),
                       pd.to_numeric(bundle.brent["brent_eur_bbl"], errors="coerce")))
    # Électricité : ancienne méthode puis méthode actuelle, bout à bout et sans raccord.
    a = bundle.elec_ancienne
    e = bundle.elec_mensuel
    if a is not None and "I_TAX" in a.columns and e is not None:
        xa, va = pd.to_datetime(a["periode"]), pd.to_numeric(a["I_TAX"], errors="coerce")
        xe, ve = pd.to_datetime(e["mois"]), pd.to_numeric(e["ttc"], errors="coerce")
        garder = xa < xe.min()
        series.append(("Électricité TTC", pd.concat([xa[garder], xe], ignore_index=True),
                       pd.concat([va[garder], ve], ignore_index=True)))
    if not series:
        return None

    # Base commune : le dernier mois où les trois existent.
    fin = min(x[v.notna()].max() for _, x, v in series)
    fig, ax = plt.subplots(figsize=FIGSIZE)
    for (lab, x, v), color in zip(series, SERIES):
        cand = v.index[(x <= fin) & v.notna()]
        if not len(cand):
            continue
        ref = v.loc[cand[-1]]
        if ref:
            ax.plot(x, v / ref * 100.0, color=color, label=lab, linewidth=1.8)
    _rupture(ax, DEBUT_DOSSIER, "début du dossier", False)
    _rupture(ax, pd.Timestamp("2007-07-01"), "définition électricité", True)
    ax.set_xlim(min(x.min() for _, x, _ in series), PLAGE["fin"] or fin)
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    for lab in ax.get_xticklabels():
        lab.set_rotation(45); lab.set_ha("right"); lab.set_fontsize(7.5)
    ax.legend(loc="upper left", ncols=3, fontsize=8, labelcolor=INK_2)
    _finish(ax, "Ce qui remonte avant 2005 – base 100 au dernier mois commun",
            "indice, base 100",
            "Sources : INSEE (IPC, Brent), Eurostat (électricité).")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def controle(bundle: Bundle, outdir: Path, stem: str) -> Path | None:
    """Écart relatif entre sources qui mesurent la même grandeur.

    Le dossier reconstitue plusieurs grandeurs par deux chemins indépendants : le
    Brent vient à la fois de l'INSEE et de la DGEC, le prix de l'électricité d'Eurostat
    et de la CRE, le hors-taxes des carburants est à la fois mesuré et recomposé. Tant
    que les deux chemins concordent, la chaîne se valide elle-même ; là où ils
    divergent, la figure dit de combien, et à partir de quand.
    """
    paires = []
    b = bundle.brent
    if b is not None and "brent_usd_bbl_dgec" in b.columns:
        v = b.dropna(subset=["brent_usd_bbl", "brent_usd_bbl_dgec"])
        if len(v):
            paires.append(("Brent : INSEE vs DGEC", pd.to_datetime(v["date"]),
                           100 * (v["brent_usd_bbl"] - v["brent_usd_bbl_dgec"]) / v["brent_usd_bbl"]))
    for nom, attr in (("Sans-plomb", "sansplomb"), ("Gazole", "gazole")):
        d = getattr(bundle, attr, None)
        if d is None or "ecart_bouclage" not in d.columns:
            continue
        v = d.dropna(subset=["ecart_bouclage", "ht"])
        if len(v):
            paires.append((f"{nom} hors taxes : mesuré vs recomposé",
                           pd.to_datetime(v["mois"]),
                           100 * pd.to_numeric(v["ecart_bouclage"]) / pd.to_numeric(v["ht"])))
    e = bundle.elec_mensuel
    if e is not None and bundle.trv is not None and "prix_moyen_ttc_ceur_kwh" in bundle.trv.columns:
        t = bundle.trv.sort_values("debut")
        bornes = pd.to_datetime(t["debut"])
        vals = pd.to_numeric(t["prix_moyen_ttc_ceur_kwh"], errors="coerce").values
        pos = bornes.searchsorted(pd.to_datetime(e["mois"]), side="right") - 1
        au_bareme = pd.Series([vals[i] if i >= 0 else float("nan") for i in pos], index=e.index)
        ttc = pd.to_numeric(e["ttc"], errors="coerce")
        garder = au_bareme.notna() & ttc.notna() & (e["source"] == "Eurostat")
        if garder.any():
            paires.append(("Électricité : Eurostat vs TRV",
                           pd.to_datetime(e.loc[garder, "mois"]),
                           100 * (ttc[garder] - au_bareme[garder]) / ttc[garder]))
    if not paires:
        return None

    fig, ax = plt.subplots(figsize=FIGSIZE)
    for (lab, x, y), color in zip(paires, SERIES):
        ax.plot(x, y, color=color, label=lab, linewidth=1.6)
    ax.axhline(0.0, color=INK, linewidth=1.2, zorder=1)
    for seuil in (-5, 5):
        ax.axhline(seuil, color=AXIS, linewidth=0.9, linestyle=(0, (2, 3)), zorder=0)
    ax.set_xlim(*_plage(min(x.min() for _, x, _ in paires), max(x.max() for _, x, _ in paires)))
    _marquer_fin(ax, max(x.max() for _, x, _ in paires))
    ax.legend(loc="lower left", ncols=2, fontsize=8, labelcolor=INK_2)
    _finish(ax, "Contrôle : écart entre sources mesurant la même grandeur",
            "écart relatif, %",
            "Pointillés : ±5 %.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path
