"""Figures en courbes : l'évolution d'une grandeur dans le temps."""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from prix_energie.viz.style import AXIS, FIGSIZE, INK_2, MUTED, PLAGE, SERIES, SURFACE, _finish
from prix_energie.viz.figures.communs import _aval, _courbes, _en_indice, _libelle_vertical, _marquer_fin, _plage, _rupture



def energie_panneaux(produits: list[tuple[str, pd.DataFrame | None, str, str]],
                     outdir: Path, stem: str, constants: bool = False,
                     ref_label: str = "") -> Path | None:
    """Les trois énergies superposées, carburants à gauche et électricité à droite.

    Deux échelles verticales, à la demande : les carburants se mesurent en c€/l et
    l'électricité en c€/kWh. Le rapport entre les deux axes étant un choix de
    cadrage, l'endroit où les courbes se croisent ne veut rien dire ; seules les
    formes et les dates se comparent. L'unité de chaque axe est reprise dans la
    légende pour qu'on sache toujours quelle courbe se lit de quel côté.
    """
    suffixe = "_constants" if constants else ""
    dispo = [(nom, df, unite, col_ttc, col_ht) for nom, df, unite, col_ttc, col_ht in produits
             if df is not None and f"{col_ttc}{suffixe}" in df.columns
             and pd.to_numeric(df[f"{col_ttc}{suffixe}"], errors="coerce").notna().any()]
    if not dispo:
        return None

    unite_gauche = dispo[0][2]
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax_droite = None
    traces, x_max = [], None
    for (nom, df, unite, col_ttc, col_ht), color in zip(dispo, SERIES):
        if unite == unite_gauche:
            cible, cote = ax, ""
        else:
            if ax_droite is None:
                ax_droite = ax.twinx()
                ax_droite.set_ylabel(unite, color=INK_2, fontsize=9)
                ax_droite.grid(False)
                # Surtout pas de set_ylim ici : le figer avant d'avoir tracé désactive
                # l'ajustement automatique, et l'axe reste sur [0, 1] : les courbes
                # sortent alors du cadre sans aucun message.
                for side in ("top", "left"):
                    ax_droite.spines[side].set_visible(False)
                ax_droite.spines["right"].set_color(AXIS)
                ax_droite.tick_params(colors=MUTED, labelcolor=INK_2)
            cible, cote = ax_droite, ""
            # L'axe de droite prend la couleur de sa série : l'appartenance se lit
            # sans alourdir chaque entrée de légende d'une mention d'échelle.
            ax_droite.yaxis.label.set_color(color)
            ax_droite.spines["right"].set_color(color)
        date_col = "mois" if "mois" in df.columns else "periode"
        x = pd.to_datetime(df[date_col])
        ligne, = cible.plot(x, pd.to_numeric(df[f"{col_ttc}{suffixe}"], errors="coerce"),
                            color=color, label=f"{nom} TTC{cote}")
        traces.append(ligne)
        # Hors taxes : même couleur que son TTC, en pointillé. L'écart vertical entre
        # les deux traits d'une même couleur est la fiscalité du produit.
        col_ht_s = f"{col_ht}{suffixe}"
        if col_ht_s in df.columns and pd.to_numeric(df[col_ht_s], errors="coerce").notna().any():
            # Sous-total : même couleur que son prix payé, trait plus fin.
            l_ht, = cible.plot(x, pd.to_numeric(df[col_ht_s], errors="coerce"), color=color,
                               linestyle=(0, (4, 3)), linewidth=1.2,
                               label=f"{nom} hors taxes{cote}")
            traces.append(l_ht)
        x_max = x.max() if x_max is None else max(x_max, x.max())

    ax.set_ylim(bottom=0)
    if ax_droite is not None:
        # Recalculer les bornes à partir des données tracées, puis seulement caler
        # le bas sur zéro.
        ax_droite.relim()
        ax_droite.autoscale_view()
        ax_droite.set_ylim(0, ax_droite.get_ylim()[1])
    ax.set_xlim(*_plage(*mdates.num2date(ax.dataLim.intervalx)))
    if x_max is not None:
        _marquer_fin(ax, x_max)
    ax.legend(traces, [t.get_label() for t in traces], loc="upper left",
              ncols=2, fontsize=8, labelcolor=INK_2)
    titre = ("Prix TTC de l'énergie en France – euros constants " + ref_label).strip() if constants \
        else "Prix TTC de l'énergie en France – euros courants"
    _finish(ax, titre, unite_gauche,
            "Électricité : bande 2 500–4 999 kWh, échelle de droite. "
            "Sources : Weekly Oil Bulletin, DGEC, Eurostat, INSEE.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def accises_comparees(sansplomb: pd.DataFrame | None, gazole: pd.DataFrame | None,
                      outdir: Path, stem: str, constants: bool = False,
                      ref_label: str = "") -> Path | None:
    """Les deux accises sur un même axe, pour voir l'écart se refermer.

    Suivies séparément, on lit deux barèmes qui montent. Superposées, on lit autre
    chose : la distance entre eux, constante de 2005 à 2014, puis réduite de moitié
    en quatre ans. C'est cette distance qui est l'objet de la décision publique, et
    elle n'apparaît sur aucune des deux courbes prise isolément.
    """
    series = []
    for nom, d in (("Sans-plomb", sansplomb), ("Gazole", gazole)):
        if d is None or not len(d):
            continue
        col = "accise_constants" if constants else "accise"
        if col not in d.columns:
            continue
        v = pd.to_numeric(d[col], errors="coerce")
        if v.notna().any():
            series.append((nom, pd.to_datetime(d["mois"]), v))
    if len(series) < 2:
        return None

    fig, ax = plt.subplots(figsize=FIGSIZE)
    for (nom, x, v), couleur in zip(series, SERIES):
        ax.plot(x, v, color=couleur, label=nom, linewidth=1.8)
    # L'écart lui-même, en gris : c'est lui le sujet, pas les niveaux.
    (_, x1, v1), (_, x2, v2) = series
    commun = pd.DataFrame({"x": x1, "sp": v1}).merge(
        pd.DataFrame({"x": x2, "gz": v2}), on="x", how="inner")
    ax.fill_between(commun["x"], commun["gz"], commun["sp"], color=MUTED, alpha=0.18,
                    linewidth=0, label="Écart de fiscalité")

    ax.set_xlim(*_plage(commun["x"].min(), commun["x"].max()))
    ax.set_ylim(bottom=0)
    _marquer_fin(ax, commun["x"].max())
    ax.legend(loc="lower right", ncols=3, fontsize=8, labelcolor=INK_2)
    unite = f"c€/l (euros constants {ref_label})".strip() if constants else "c€/l (euros courants)"
    _finish(ax, "Accise sur les carburants" + (" – euros constants" if constants else ""),
            unite, "Sources : Weekly Oil Bulletin, DGEC.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def solde_compare(sansplomb: pd.DataFrame | None, gazole: pd.DataFrame | None,
                  outdir: Path, stem: str, constants: bool = False,
                  ref_label: str = "") -> Path | None:
    """Ce qui reste du prix hors taxes une fois retirés le brut et le raffinage.

    Ce reste couvre l'acheminement, la distribution, les marges, et tout ce que la
    décomposition ne sait pas attribuer. Les deux carburants partagent le même baril
    et la même marge de raffinage publiée : si leurs restes divergent, la cause est
    en aval de la raffinerie, et nulle part ailleurs.
    """
    series = []
    for nom, d in (("Sans-plomb", sansplomb), ("Gazole", gazole)):
        if d is None or not len(d):
            continue
        sfx = "_constants" if constants else ""
        cols = [f"ht{sfx}", f"brent_ceur_l{sfx}", f"raffinage_ceur_l{sfx}"]
        if not all(c in d.columns for c in cols):
            continue
        v = (pd.to_numeric(d[cols[0]], errors="coerce")
             - pd.to_numeric(d[cols[1]], errors="coerce")
             - pd.to_numeric(d[cols[2]], errors="coerce"))
        if v.notna().any():
            series.append((nom, pd.to_datetime(d["mois"]), v))
    if len(series) < 2:
        return None

    fig, ax = plt.subplots(figsize=FIGSIZE)
    for (nom, x, v), couleur in zip(series, SERIES):
        ax.plot(x, v, color=couleur, label=nom, linewidth=1.8)
    (_, x1, v1), (_, x2, v2) = series
    c = pd.DataFrame({"x": x1, "sp": v1}).merge(pd.DataFrame({"x": x2, "gz": v2}),
                                                on="x", how="inner").dropna()
    ax.fill_between(c["x"], c["sp"], c["gz"], color=MUTED, alpha=0.18, linewidth=0,
                    label="Écart entre les deux")

    ax.set_xlim(*_plage(c["x"].min(), c["x"].max()))
    ax.set_ylim(bottom=0)
    _marquer_fin(ax, c["x"].max())
    ax.legend(loc="upper left", ncols=3, fontsize=8, labelcolor=INK_2)
    unite = f"c€/l (euros constants {ref_label})".strip() if constants else "c€/l (euros courants)"
    _finish(ax, "Ce qui reste du prix hors taxes après le brut et le raffinage"
            + (" – euros constants" if constants else ""), unite,
            "Sources : Weekly Oil Bulletin, INSEE, DGEC.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def electricite_hors_taxes(composantes: pd.DataFrame | None, semestriel: pd.DataFrame | None,
                           outdir: Path, stem: str, constants: bool = False,
                           ref_label: str = "") -> Path | None:
    """Ce que contient le prix hors taxes de l'électricité : fourniture et réseau.

    Pendant de `composantes_ht` pour les carburants, même forme et même lecture : le
    total en trait noir, la somme des composantes en pointillé, les composantes en
    couleur. Ici les deux se superposent presque : fourniture + réseau reconstituent
    le prix hors taxes à moins de 0,1 c€/kWh : alors que pour les carburants le
    bouclage laisse un écart de plusieurs centimes.
    """
    if composantes is None or not len(composantes):
        return None
    d = composantes.copy()
    num = lambda c: pd.to_numeric(d[c], errors="coerce") if c in d.columns else None  # noqa: E731
    sfx = "_constants" if constants else ""
    fourniture, reseau = num("NRG_SUP" + sfx), num("NETC" + sfx)
    if fourniture is None or reseau is None:
        return None

    # Total mesuré indépendamment : le prix hors taxes du jeu semestriel, moyenné
    # par année pour être comparable aux composantes, qui sont annuelles.
    total = None
    if semestriel is not None and ("hors_taxes" + sfx) in semestriel.columns:
        s = semestriel.copy()
        s["annee"] = pd.to_datetime(s["periode"]).dt.year
        par_an = s.groupby("annee")["hors_taxes" + sfx].mean()
        total = pd.to_datetime(d["periode"]).dt.year.map(par_an)

    x = pd.to_datetime(d["periode"])
    fin = x.max() + pd.DateOffset(years=1)
    prolonge = lambda v: pd.concat([v, pd.Series([v.iloc[-1]])], ignore_index=True)  # noqa: E731
    x_prolonge = pd.concat([x, pd.Series([fin])], ignore_index=True)
    return _courbes(
        x_prolonge,
        [("Fourniture d'énergie", prolonge(fourniture)), ("Réseau (TURPE)", prolonge(reseau))],
        "Électricité – composition du prix hors taxes (valeurs annuelles)"
        + (" – euros constants" if constants else ""),
        f"c€/kWh (euros constants {ref_label})".strip() if constants else "c€/kWh",
        "Source : Eurostat nrg_pc_204_c (composantes) et nrg_pc_204 (prix hors taxes).",
        outdir, stem, escalier=True,
        total=("Prix hors taxes", prolonge(total)) if total is not None else None,
        somme=("Fourniture + réseau", prolonge(fourniture + reseau)))


def cout_km(df: pd.DataFrame | None, choices, outdir: Path, stem: str,
            constants: bool = False, ref_label: str = "") -> Path | None:
    """Coût de 100 km pour trois motorisations : la seule comparaison qui tienne.

    Ramener chaque énergie à un trajet identique est ce qui rend un litre et un
    kilowattheure comparables. Les consommations sont des conventions : elles fixent
    les niveaux, pas les formes, et figurent en toutes lettres sous la figure.
    """
    if df is None or not len(df):
        return None
    x = pd.to_datetime(df["mois"])
    series = [(f"Essence ({choices.conso_essence_l_100km:g} l/100 km)", "essence"),
              (f"Gazole ({choices.conso_diesel_l_100km:g} l/100 km)", "diesel"),
              (f"Électrique ({choices.conso_ve_kwh_100km:g} kWh/100 km)", "electrique")]
    sfx = "_constants" if constants else ""
    tracees = [(lab, pd.to_numeric(df[c + sfx], errors="coerce"))
               for lab, c in series if c + sfx in df.columns]
    if not tracees:
        return None
    return _courbes(
        x, tracees, "Coût de 100 kilomètres par motorisation"
        + (" – euros constants" if constants else ""),
        f"€ pour 100 km (euros constants {ref_label})".strip() if constants
        else "€ pour 100 km (euros courants)",
        "Prix TTC. Sources : Weekly Oil Bulletin, CRE.",
        outdir, stem)


def cout_km_indice(df: pd.DataFrame | None, outdir: Path, stem: str,
                   base_date=None) -> Path | None:
    """Coût de 100 km rapporté à sa dernière valeur connue.

    Troisième volet du triptyque courant / constant / indice, comme pour les niveaux :
    les trois motorisations partant du même point, ce sont leurs trajectoires qui se
    comparent, et non plus leurs écarts de niveau.
    """
    if df is None or not len(df):
        return None
    x = pd.to_datetime(df["mois"])
    series = [("Essence", "essence"), ("Gazole", "diesel"), ("Électrique", "electrique")]
    tracees = []
    for lab, c in series:
        if c not in df.columns:
            continue
        v = pd.to_numeric(df[c], errors="coerce")
        idx = None
        if base_date is not None:
            cand = df.index[(x <= pd.Timestamp(base_date)) & v.notna()]
            idx = cand[-1] if len(cand) else None
        if idx is None:
            idx = v.last_valid_index()
        if idx is not None and v.loc[idx]:
            tracees.append((lab, v / v.loc[idx] * 100.0))
    return _courbes(
        x, tracees,
        "Coût de 100 kilomètres, en indice", "indice, base 100",
        "Euros courants. Sources : Weekly Oil Bulletin, CRE.",
        outdir, stem, base_indice=base_date)


def electricite_taxes_detail(composantes: pd.DataFrame | None, outdir: Path,
                             stem: str) -> Path | None:
    """Le détail des taxes sur l'électricité, à l'exclusion de tout le reste.

    Ni la fourniture ni le réseau n'y figurent : le TURPE est un coût d'acheminement,
    pas une taxe, et sa place est dans le prix hors taxes. Seuls les postes réellement
    renseignés sont tracés : la nomenclature Eurostat en prévoit sept, la France en
    laisse plusieurs à zéro.
    """
    if composantes is None or not len(composantes):
        return None
    d = composantes.copy()
    num = lambda c: pd.to_numeric(d[c], errors="coerce") if c in d.columns else None  # noqa: E731
    postes = [("Accise sur l'électricité", "TAX_ENV"), ("Taxe capacité", "TAX_CAP"),
              ("Taxes nucléaire et renouvelables", "TAX_NUC"),
              ("Autres prélèvements", "OTH"), ("TVA", "VAT")]
    series = []
    for lab, col in postes:
        v = num(col)
        if v is not None and v.notna().any() and float(v.abs().max()) > 0.01:
            series.append((lab, v))
    if not series:
        return None
    x = pd.to_datetime(d["periode"])
    fin = x.max() + pd.DateOffset(years=1)
    prolonge = lambda v: pd.concat([v, pd.Series([v.iloc[-1]])], ignore_index=True)  # noqa: E731
    total = sum(v for _, v in series)
    return _courbes(
        pd.concat([x, pd.Series([fin])], ignore_index=True),
        [(lab, prolonge(v)) for lab, v in series],
        "Électricité – détail des taxes (valeurs annuelles)", "c€/kWh",
        "Source : Eurostat nrg_pc_204_c.",
        outdir, stem, escalier=True, total=("Total des taxes", prolonge(total)))


def energie_indice(produits: list[tuple[str, pd.DataFrame | None, str, str, str]],
                   outdir: Path, stem: str, ref_label: str = "", base_date=None) -> Path | None:
    """Les trois énergies ramenées à une base commune, en courants et en constants.

    Pendant des deux figures à double axe : en rapportant chaque prix à sa valeur au
    mois de référence : le même que celui des euros constants : les trois énergies
    tiennent sur une seule échelle, sans le choix de cadrage qu'impose un second axe.
    Pour un produit donné, l'écart entre le trait plein et le pointillé est la part
    de l'évolution qui n'est qu'inflation.
    """
    fig, ax = plt.subplots(figsize=FIGSIZE)
    traces, x_max, bases = [], None, []
    for (nom, df, _unite, col_ttc, _col_ht), color in zip(produits, SERIES):
        if df is None or col_ttc not in df.columns:
            continue
        date_col = "mois" if "mois" in df.columns else "periode"
        x = pd.to_datetime(df[date_col])
        for suffixe, style, largeur in (("", "-", 2.0), ("_constants", (0, (4, 3)), 1.7)):
            col = f"{col_ttc}{suffixe}"
            if col not in df.columns:
                continue
            v = pd.to_numeric(df[col], errors="coerce")
            # Base commune à toutes les figures en indice du dossier.
            ref_idx = None
            if base_date is not None:
                cand = df.index[(x <= pd.Timestamp(base_date)) & v.notna()]
                ref_idx = cand[-1] if len(cand) else None
            if ref_idx is None:
                ref_idx = v.last_valid_index()
            if ref_idx is None or not v.loc[ref_idx]:
                continue
            dernier = ref_idx
            base = v.loc[ref_idx]
            libelle = f"{nom}" + (" – constants" if suffixe else " – courants")
            ligne, = ax.plot(x, v / base * 100.0, color=color, linestyle=style,
                             linewidth=largeur, label=libelle)
            traces.append(ligne)
            if not suffixe:
                bases.append(f"{nom} {x.loc[dernier]:%Y-%m}")
        x_max = x.max() if x_max is None else max(x_max, x.max())
    if not traces:
        plt.close(fig)
        return None

    ax.axhline(100.0, color=AXIS, linewidth=1.0, zorder=0)
    if base_date is not None:
        ax.axvline(pd.Timestamp(base_date), color=AXIS, linewidth=1.0,
                   linestyle=(0, (2, 3)), zorder=0)
        _libelle_vertical(ax, base_date, f"base 100 : {pd.Timestamp(base_date):%m/%Y}", MUTED)
    ax.set_xlim(*_plage(*mdates.num2date(ax.dataLim.intervalx)))
    ax.set_ylim(bottom=0)
    if x_max is not None:
        _marquer_fin(ax, x_max)
    ax.legend(loc="upper left", ncols=3, fontsize=8, labelcolor=INK_2)
    # La date de base n'est rappelée en toutes lettres que si la verticale ne la porte
    # pas déjà : la répéter sous la figure n'apprendrait rien de plus.
    rappel = "" if base_date is not None else "Base de chaque série : " + ", ".join(bases) + ". "
    _finish(ax, "Prix TTC de l'énergie, en indice", "indice, base 100",
            rappel + f"Euros constants {ref_label}. ".strip() +
            " Sources : Weekly Oil Bulletin, DGEC, Eurostat, INSEE.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def part_taxes(series: dict[str, pd.DataFrame], outdir: Path, stem: str) -> Path | None:
    """Part des taxes dans le prix TTC, pour les trois énergies.

    Contrairement aux niveaux, un pourcentage se compare entre un litre et un
    kilowattheure : c'est la seule figure où les trois énergies tiennent
    légitimement sur un même axe.
    """
    fig, ax = plt.subplots(figsize=FIGSIZE)
    tracees, x_max = 0, None
    for (nom, df), color in zip(series.items(), SERIES):
        if df is None or "ttc" not in df.columns:
            continue
        ttc = pd.to_numeric(df["ttc"], errors="coerce")
        if "accise" in df.columns and "tva" in df.columns:
            # Carburants : accise déduite + TVA.
            taxes = pd.to_numeric(df["accise"], errors="coerce") + pd.to_numeric(df["tva"], errors="coerce")
        elif "hors_taxes" in df.columns:
            # Électricité : tout ce qui sépare le prix hors taxes du prix payé.
            taxes = ttc - pd.to_numeric(df["hors_taxes"], errors="coerce")
        else:
            continue
        part = 100.0 * taxes / ttc
        if part.notna().any():
            date_col = "mois" if "mois" in df.columns else "periode"
            x = pd.to_datetime(df[date_col])
            ax.plot(x, part, color=color, label=nom)
            x_max = x.max() if x_max is None else max(x_max, x.max())
            tracees += 1
    if not tracees:
        plt.close(fig)
        return None
    ax.set_xlim(*_plage(*mdates.num2date(ax.dataLim.intervalx)))
    ax.set_ylim(0, 100)
    if x_max is not None:
        _marquer_fin(ax, x_max)
    ax.legend(loc="lower left", ncols=3, fontsize=8, labelcolor=INK_2)
    _finish(ax, "Part des taxes dans le prix payé", "% du prix TTC",
            "Sources : Weekly Oil Bulletin, DGEC, Eurostat.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def brent(df: pd.DataFrame | None, outdir: Path, stem: str, source: str = "",
          constants: bool = False, indice: bool = False, ref_label: str = "",
          base_date=None) -> Path | None:
    """Brent en dollars et en euros sur un même axe.

    Les deux devises sont de magnitude voisine, donc un seul axe suffit : et l'écart
    entre les deux courbes se lit alors directement comme l'effet du taux de change.
    Deux échelles séparées auraient rendu cet écart arbitraire.
    """
    if df is None or "brent_usd_bbl" not in df.columns:
        return None
    sfx = "_constants" if constants else ""
    num = lambda c: pd.to_numeric(df[c + sfx], errors="coerce") if (c + sfx) in df.columns else None  # noqa: E731
    note = f"Sources : {source or 'DGEC / Reuters'}"
    if "brent_eur_bbl" in df.columns:
        note += ", INSEE pour la conversion en euros"
    note += "."
    series = [("Brent ($/baril)", num("brent_usd_bbl")), ("Brent (€/baril)", num("brent_eur_bbl"))]
    if indice:
        d_ = pd.to_datetime(df["date"])
        b = None
        if base_date is not None:
            cand = df.index[d_ <= pd.Timestamp(base_date)]
            b = cand[-1] if len(cand) else None
        return _courbes(d_, _en_indice(series, b), "Brent daté – en indice",
                        "indice, base 100", note, outdir, stem, base_indice=base_date)
    unite = f"par baril (euros constants {ref_label})".strip() if constants         else "par baril (USD ou EUR)"
    titre = "Brent daté – moyennes mensuelles" + (" – euros constants" if constants else "")
    return _courbes(pd.to_datetime(df["date"]), series, titre, unite, note, outdir, stem)


def electricite(df: pd.DataFrame | None, outdir: Path, stem: str,
                constants: bool = False, ref_label: str = "",
                ancienne: pd.DataFrame | None = None, rupture_source=None) -> Path | None:
    """Décomposition du prix de l'électricité : hors taxes, taxes hors TVA, TVA.

    Volontairement calquée sur la décomposition des carburants : même forme, mêmes
    couleurs dans le même ordre, même convention de somme : pour que les trois
    produits se comparent d'un coup d'œil malgré des unités différentes.
    """
    if df is None or not len(df):
        return None
    s = "_constants" if constants else ""
    d = df.copy()
    if "mois" in d.columns and "periode" not in d.columns:
        d = d.rename(columns={"mois": "periode"})
    # Eurostat fournit des niveaux cumulés : on repasse en composantes additives.
    if f"hors_tva{s}" in d.columns and f"ttc{s}" in d.columns:
        d[f"taxes_hors_tva{s}"] = (pd.to_numeric(d[f"hors_tva{s}"], errors="coerce")
                                   - pd.to_numeric(d[f"hors_taxes{s}"], errors="coerce"))
        d[f"tva{s}"] = (pd.to_numeric(d[f"ttc{s}"], errors="coerce")
                        - pd.to_numeric(d[f"hors_tva{s}"], errors="coerce"))
    # Avant 2007, Eurostat publiait des prix de consommateurs-types : même structure en
    # trois niveaux, mais un tarif appliqué à un profil conventionnel et non une moyenne
    # de contrats. On prolonge donc la figure sans raccorder, en marquant la rupture.
    rupture = None
    if not constants and ancienne is not None and "X_TAX" in ancienne.columns:
        a = ancienne.copy()
        a["hors_taxes"] = pd.to_numeric(a["X_TAX"], errors="coerce")
        a["tva"] = pd.to_numeric(a["I_TAX"], errors="coerce") - pd.to_numeric(a["X_VAT"], errors="coerce")
        a["taxes_hors_tva"] = pd.to_numeric(a["X_VAT"], errors="coerce") - a["hors_taxes"]
        a = a[["periode", "hors_taxes", "taxes_hors_tva", "tva"]].dropna()
        debut_actuel = pd.to_datetime(d["periode"]).min()
        a = a[pd.to_datetime(a["periode"]) < debut_actuel]
        if len(a):
            rupture = debut_actuel
            d = pd.concat([a, d], ignore_index=True).sort_values("periode")
    cols = [(f"hors_taxes{s}", "Hors taxes"), (f"taxes_hors_tva{s}", "Taxes hors TVA"),
            (f"tva{s}", "TVA")]
    present = [(c, lab) for c, lab in cols
               if c in d.columns and pd.to_numeric(d[c], errors="coerce").notna().any()]
    if not present:
        return None
    complet = d[[c for c, _ in present]].notna().all(axis=1)
    d = d.loc[complet]
    if not len(d):
        return None
    x = pd.to_datetime(d["periode"])
    ys = [pd.to_numeric(d[c], errors="coerce").values for c, _ in present]
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.stackplot(x, *ys, labels=[lab for _, lab in present], colors=SERIES[:len(ys)],
                 edgecolor=SURFACE, linewidth=0.8)
    if rupture_source is not None:
        _rupture(ax, rupture_source[0], rupture_source[1], rupture_source[2])
    if rupture is not None:
        _rupture(ax, rupture, "rupture méthodologique", True)
        ax.set_xlim(x.min(), PLAGE["fin"] or x.max())
    else:
        ax.set_xlim(*_plage(x.min(), x.max()))
    ax.set_ylim(bottom=0)
    _marquer_fin(ax, x.max())
    ax.legend(loc="upper left", ncols=3, fontsize=8, labelcolor=INK_2)
    titre = "Électricité ménages – décomposition du prix (bande 2 500–4 999 kWh)"
    unite = f"c€/kWh (euros constants {ref_label})".strip() if constants else "c€/kWh (euros courants)"
    _finish(ax, titre + (" – euros constants" if constants else ""), unite,
            "Sources : Eurostat nrg_pc_204 et nrg_pc_204_h, CRE (tarif réglementé).")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def aval_petrolier(sansplomb, gazole, outdir: Path, stem: str,
                   ref_label: str = "") -> Path | None:
    """Le coût de l'aval pétrolier, face au brut qu'il transforme.

    Trois courbes et pas davantage : les deux carburants, et le baril dont ils
    sortent. C'est la figure qui porte la thèse, elle doit se lire sans apprentissage.
    """
    if sansplomb is None or gazole is None:
        return None
    fig, ax = plt.subplots(figsize=FIGSIZE)
    x_max = None
    for df, couleur, libelle in ((sansplomb, SERIES[0], "Sans-plomb"),
                                 (gazole, SERIES[1], "Gazole")):
        if "ht_constants" not in df.columns:
            continue
        x = pd.to_datetime(df["mois"])
        v = _aval(df)
        if not v.notna().any():
            continue
        ax.plot(x, v, color=couleur, linewidth=1.6, label=f"{libelle}, aval")
        x_max = x.max() if x_max is None else max(x_max, x.max())
        # Le dernier point chiffré : sans lui le lecteur repart avec une forme, pas
        # avec un ordre de grandeur.
        der = v.dropna()
        if len(der):
            ax.annotate(f"{der.iloc[-1]:.0f}", xy=(x[der.index[-1]], der.iloc[-1]),
                        xytext=(6, 0), textcoords="offset points",
                        fontsize=9.5, color=couleur, va="center", fontweight="bold")
    brut = pd.to_numeric(sansplomb["brent_ceur_l_constants"], errors="coerce")
    ax.plot(pd.to_datetime(sansplomb["mois"]), brut, color=MUTED, linewidth=1.4,
            label="Pétrole brut, commun aux deux")

    if x_max is not None:
        ax.set_xlim(*_plage(pd.to_datetime(sansplomb["mois"]).min(), x_max))
        _marquer_fin(ax, x_max)
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", ncols=3, fontsize=8, labelcolor=INK_2)
    _finish(ax, "Ce que coûte le trajet du baril au réservoir, euros constants",
            f"c€/l (euros constants {ref_label})".strip(),
            "Prix hors taxes moins coût du brut. Sources : Weekly Oil Bulletin, "
            "DGEC, INSEE.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def courant_vs_constant(sansplomb, gazole, outdir: Path, stem: str,
                        ref_label: str = "", ref_date=None) -> Path | None:
    """Le même litre, en euros du jour et en euros d'aujourd'hui.

    Les deux lectures coexistent dans le dossier sans jamais se croiser sur une même
    figure. Or c'est leur écart qui explique qu'un record puisse ne pas en être un :
    le trait plein est ce que vous avez sorti du portefeuille, le pointillé ce que
    cela représentait en pouvoir d'achat.
    """
    if sansplomb is None or gazole is None:
        return None
    fig, ax = plt.subplots(figsize=FIGSIZE)
    x_min = x_max = None
    for df, couleur, nom in ((sansplomb, SERIES[0], "Sans-plomb"),
                             (gazole, SERIES[1], "Gazole")):
        if "ttc_constants" not in df.columns:
            continue
        x = pd.to_datetime(df["mois"])
        x_min = x.min() if x_min is None else min(x_min, x.min())
        x_max = x.max() if x_max is None else max(x_max, x.max())
        for col, style, suffixe in (("ttc", "-", "euros du jour"),
                                    ("ttc_constants", "--", "euros constants")):
            v = pd.to_numeric(df[col], errors="coerce") / 100.0
            ax.plot(x, v, color=couleur, linestyle=style, linewidth=1.5,
                    label=f"{nom}, {suffixe}")
            der = v.dropna()
            if len(der):
                ax.annotate(f"{der.iloc[-1]:.2f}", xy=(x[der.index[-1]], der.iloc[-1]),
                            xytext=(6, 0), textcoords="offset points", fontsize=9,
                            color=couleur, va="center", fontweight="bold")
    if x_min is None:
        plt.close(fig)
        return None
    ax.set_xlim(*_plage(x_min, x_max))
    ax.set_ylim(bottom=0)
    # Le mois de référence : c'est là que les deux lectures se rejoignent par
    # construction. Sans la verticale, le lecteur voit deux courbes converger sans
    # savoir que la convergence est une convention et non un résultat.
    if ref_date is not None:
        ax.axvline(pd.Timestamp(ref_date), color=MUTED, linewidth=0.9,
                   linestyle=(0, (2, 3)), zorder=5)
        _libelle_vertical(ax, ref_date, "pouvoir d'achat de référence", MUTED)
    ax.legend(loc="upper left", ncols=2, fontsize=8, labelcolor=INK_2)
    _finish(ax, "Le même litre, en euros du jour et en pouvoir d'achat",
            f"€/l (pointillé : euros constants {ref_label})".strip(),
            "Moyennes mensuelles. Sources : Weekly Oil Bulletin, DGEC, INSEE.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path
