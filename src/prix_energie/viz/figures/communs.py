"""Utilitaires partagés : axes, ruptures, repères, séries dérivées."""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from prix_energie.bundle import Bundle
from prix_energie.journal import log

from prix_energie.viz.style import AXIS, COMPOSANTES, FIGSIZE, INK, INK_2, MUTED, PLAGE, SERIES, SURFACE, _finish


def _plage(x_min, x_max):
    """Bornes à appliquer : celles du dossier si elles sont connues, sinon la série."""
    return (PLAGE["debut"] or x_min, PLAGE["fin"] or x_max)


def _marquer_fin(ax, x_max) -> None:
    """Garantit que la dernière période figure sur l'axe des abscisses.

    Matplotlib pose ses graduations à intervalle régulier et s'arrête avant la fin :
    une série qui court jusqu'à mi-2025 peut n'afficher que « 2024 » comme dernier
    repère, et se lire comme si elle s'arrêtait là. On ajoute donc la borne réelle.
    """
    d0, f0 = _plage(mdates.num2date(ax.get_xlim()[0]), x_max)
    debut = mdates.date2num(pd.Timestamp(d0))
    fin = mdates.date2num(pd.Timestamp(f0))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(debut, fin)
    # Une graduation par an sur vingt ans serre les étiquettes : on les incline
    # légèrement plutôt que d'en masquer une sur deux, pour garder un repère annuel.
    for lab in ax.get_xticklabels():
        lab.set_rotation(45)
        lab.set_ha("right")
        lab.set_fontsize(7.5)


def _available(df: pd.DataFrame, seuil: float = 0.10, suffixe: str = "") -> list[tuple[str, str]]:
    """Composantes assez renseignées pour être tracées.

    Une composante vide n'est pas tracée : une bande plate à zéro se lit comme une
    valeur nulle, pas comme une absence. Le seuil écarte aussi les composantes
    quasi vides : les cotations Rotterdam ne couvrent que les deux derniers mois -
    qui produiraient un trait invisible tout en consommant une couleur et une
    entrée de légende, décalant les couleurs de toutes les autres.
    """
    out = []
    for c, lab in COMPOSANTES:
        col = f"{c}{suffixe}"
        if col not in df.columns:
            continue
        part = float(pd.to_numeric(df[col], errors="coerce").notna().mean())
        if part >= seuil:
            out.append((col, lab))
        elif part > 0:
            log.info("Figures : composante '%s' écartée du graphique (%.1f %% des mois renseignés)",
                     col, 100 * part)
    return out


def _postes_ht(an: pd.Series, detail: pd.DataFrame | None, solde_label: str,
               repli_label: str) -> list[tuple[str, pd.Series]]:
    """Ouvre le bloc hors-taxes en sous-postes, année par année.

    Une année n'est détaillée que si *tous* les postes attendus y sont publiés : un
    détail partiel verserait dans le solde ce qu'on prétend nommer, et la barre dirait
    « transport-distribution » là où elle contient aussi le raffinage. Les années
    incomplètes gardent donc un bloc unique, nommé pour ce qu'il est.

    Le dernier poste est toujours un solde, pris par différence avec le hors-taxes
    mesuré. C'est ce qui fait qu'une barre empilée somme exactement au prix payé,
    là où les composantes publiées, venues de producteurs différents, ne bouclent pas.
    """
    if detail is None or detail.empty:
        return [(repli_label, an)]
    d = detail.reindex(an.index)
    complet = d.notna().all(axis=1)
    if not complet.any():
        return [(repli_label, an)]
    postes = [(lab, d[lab].where(complet, 0.0).fillna(0.0)) for lab in d.columns]
    somme = sum(v for _, v in postes)
    postes.append((solde_label, (an - somme).where(complet, 0.0)))
    # Les années non détaillées ne perdent pas leur hors-taxes : il repart en bloc.
    if (~complet).any():
        postes.insert(0, (repli_label, an.where(~complet, 0.0)))
    return postes


def _detail_annuel(df: pd.DataFrame | None, date_col: str, postes: list[tuple[str, str]],
                   suffixe: str = "") -> pd.DataFrame | None:
    """Moyennes annuelles des postes nommés, indexées par année et déjà libellées."""
    if df is None or not len(df) or date_col not in df.columns:
        return None
    cols = {lab: col + suffixe for lab, col in postes if (col + suffixe) in df.columns}
    if len(cols) != len(postes):
        return None
    d = df.copy()
    d["_an"] = pd.to_datetime(d[date_col]).dt.year
    out = d.groupby("_an")[list(cols.values())].mean()
    return out.rename(columns={v: k for k, v in cols.items()})


def _trace_prolonge(ax, x, v, reconstruit, couleur, label, largeur: float = 1.8) -> None:
    """Trace une série dont une partie est reconstituée : plein, puis tirets.

    Le point de jonction appartient aux deux segments, sinon la courbe se coupe en
    deux à l'endroit précis où elle doit rester continue.
    """
    if v is None or not v.notna().any():
        return
    rec = reconstruit.fillna(False).astype(bool)
    if not rec.any():
        ax.plot(x, v, color=couleur, linewidth=largeur, label=label)
        return
    mesure = v.where(~rec)
    premier = rec.idxmax()
    pos = list(v.index).index(premier)
    if pos > 0:
        mesure.loc[list(v.index)[pos - 1]] = v.loc[list(v.index)[pos - 1]]
    ax.plot(x, mesure, color=couleur, linewidth=largeur, label=label)
    prolonge = v.where(rec)
    if pos > 0:
        prolonge.loc[list(v.index)[pos - 1]] = v.loc[list(v.index)[pos - 1]]
    ax.plot(x, prolonge, color=couleur, linewidth=largeur, linestyle=(0, (2, 1.6)))


def _meta_stations(stations: pd.DataFrame, cle: str):
    """Métadonnée du jeu de stations, lue en colonne puis, à défaut, en attribut.

    Les colonnes survivent à l'écriture CSV, pas les attributs : une figure régénérée
    depuis les fichiers ne verrait rien sans ce détour.
    """
    if cle in stations.columns:
        v = stations[cle].dropna()
        if len(v):
            return v.iloc[0]
    autre = {"maj_reference": "reference"}.get(cle, cle)
    return (stations.attrs or {}).get(autre)


def _amplitude_mensuelle(serie, reconstruit=None, mini: int = 4):
    """Écart-type des variations d'un mois sur l'autre, ou None si non mesurable.

    Les points reconstruits sont écartés du calcul : une valeur reconduite ne varie
    pas, et le saut qu'elle produit en reprenant sa mesure n'est pas un mouvement de
    prix mais un changement de méthode. En dessous de quatre variations réelles, on
    renonce plutôt que d'afficher une dispersion tirée de deux points.
    """
    if serie is None:
        return None
    v = serie if reconstruit is None else serie.where(~reconstruit)
    diffs = v.diff().dropna()
    if len(diffs) < mini:
        return None
    s = float(diffs.std())
    return s if s > 0 else None


def _libelle_vertical(ax, date, libelle: str, couleur) -> None:
    """Libellé d'une verticale, posé au pied de l'axe.

    Toujours en bas : le haut de l'aire de tracé appartient à la légende, et un libellé
    vertical qui la traverse rend les deux illisibles. Le fond opaque le détache des
    aires empilées, qui montent jusqu'au plancher de l'axe.
    """
    ax.annotate(libelle, xy=(pd.Timestamp(date), 0.0), xycoords=("data", "axes fraction"),
                xytext=(-5, 5), textcoords="offset points", rotation=90,
                ha="left", va="bottom", fontsize=7, zorder=6, color=couleur,
                bbox={"facecolor": SURFACE, "alpha": 0.8, "edgecolor": "none", "pad": 1.0})


def _rupture(ax, date, libelle: str, definition: bool = True) -> None:
    """Marque une discontinuité sur l'axe du temps.

    Deux niveaux seulement : un trait noir quand la grandeur mesurée change de
    définition ou de produit : on ne compare plus la même chose de part et d'autre -
    et un trait gris fin quand seule la source change. Une série qui s'arrête n'a
    besoin d'aucune marque : son interruption se voit.
    """
    if date is None:
        return
    ax.axvline(pd.Timestamp(date), color=INK if definition else MUTED,
               linewidth=1.2 if definition else 0.9,
               linestyle=(0, (3, 3)) if definition else (0, (2, 3)), zorder=5)
    _libelle_vertical(ax, date, libelle, INK_2 if definition else MUTED)


def _courbes(x: pd.Series, series: list[tuple[str, pd.Series]], titre: str, ylabel: str,
             source: str, outdir: Path, stem: str, ymin: float | None = 0.0,
             total: tuple[str, pd.Series] | None = None,
             somme: tuple[str, pd.Series] | None = None,
             escalier: bool = False, base_indice=None, rupture=None) -> Path | None:
    """Tracé en courbes de plusieurs composantes sur un même axe.

    Forme choisie quand les composantes ne se somment pas exactement au total : un
    empilement affirmerait une addition qui n'est pas vraie, alors que des courbes
    comparent des niveaux sans rien prétendre de leur somme. Les libellés au dernier
    point tiennent lieu de second canal d'identité, la couleur ne portant jamais seule.

    `total` et `somme` sont tracés en encre neutre, pas dans une couleur de série :
    ce ne sont pas des composantes, et leur donner un slot catégoriel les ferait lire
    comme telles. Quand les deux diffèrent, l'écart entre le trait plein et le
    pointillé *est* l'écart de bouclage, lisible sans calcul.
    """
    tracees = [(lab, v) for lab, v in series if v is not None and v.notna().any()]
    if not tracees:
        return None
    fig, ax = plt.subplots(figsize=FIGSIZE)
    # « steps-post » quand chaque valeur vaut pour toute une période (un semestre, une
    # année) : relier deux relevés par un segment oblique dessinerait une variation
    # continue entre les deux, alors que le tarif tient un palier puis saute.
    style = {"drawstyle": "steps-post"} if escalier else {}

    # Identification par la légende seule : un libellé posé en fin de courbe mange de
    # la largeur au tracé, et d'une figure à l'autre il n'en mange pas la même, si bien
    # qu'aucune ne se superpose à la suivante.

    if total is not None and total[1] is not None and total[1].notna().any():
        ax.plot(x, total[1], color=INK, linewidth=2.6, label=total[0], zorder=5, **style)
    if somme is not None and somme[1] is not None and somme[1].notna().any():
        ax.plot(x, somme[1], color=MUTED, linewidth=1.6, linestyle=(0, (4, 3)),
                label=somme[0], zorder=4, **style)

    for (lab, v), color in zip(tracees, SERIES):
        ax.plot(x, v, color=color, label=lab, **style)
    # Repère de la base 100 : sans lui, rien ne dit à quelle date les courbes
    # convergent, ni que cette date est la même d'une figure à l'autre.
    if base_indice is not None:
        ax.axvline(pd.Timestamp(base_indice), color=AXIS, linewidth=1.0,
                   linestyle=(0, (2, 3)), zorder=0)
        _libelle_vertical(ax, base_indice, f"base 100 : {pd.Timestamp(base_indice):%m/%Y}", MUTED)
    if rupture is not None:
        _rupture(ax, rupture[0], rupture[1], rupture[2])
    ax.set_xlim(*_plage(x.min(), x.max()))
    if ymin is not None:
        ax.set_ylim(bottom=ymin)
    ax.legend(loc="upper left", ncols=min(len(tracees), 3), fontsize=8, labelcolor=INK_2)
    _marquer_fin(ax, x.max())
    _finish(ax, titre, ylabel, source)
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def _base_commune(series: list[tuple[str, pd.Series]]):
    """Dernier point où toutes les séries sont renseignées.

    Indexer chacune sur sa propre fin ferait converger vers 100 à des dates
    différentes : le transport-distribution s'arrête un an avant le Brent : et les
    trajectoires ne seraient plus comparables entre elles.
    """
    valides = [v for _, v in series if v is not None and v.notna().any()]
    if not valides:
        return None
    commun = valides[0].notna()
    for v in valides[1:]:
        commun = commun & v.notna()
    idx = commun[commun].index
    return idx[-1] if len(idx) else None


def _en_indice(series: list[tuple[str, pd.Series]],
               base=None) -> list[tuple[str, pd.Series]]:
    """Rapporte chaque série à une base 100 commune.

    Permet de comparer des composantes d'ordres de grandeur très différents : une TVA
    de 4 c€ et un hors-taxes de 100 c€ : en ne regardant que leurs trajectoires.
    """
    if base is None:
        base = _base_commune(series)
    out = []
    for lab, v in series:
        if v is None:
            continue
        ref = v.loc[base] if base is not None and base in v.index and pd.notna(v.loc[base]) else None
        if ref is None:
            dernier = v.last_valid_index()
            ref = v.loc[dernier] if dernier is not None else None
        if ref:
            out.append((lab, v / ref * 100.0))
    return out


def _base_globale(bundle: Bundle):
    """Date de référence commune à toutes les figures en indice.

    Chaque figure pourrait s'indexer sur sa propre fin, mais les séries ne finissent
    pas ensemble : le transport-distribution s'arrête un an avant le Brent. Les bases
    différeraient alors d'une figure à l'autre, et les trajectoires ne se
    compareraient plus entre figures. On retient donc le dernier mois où toutes les
    composantes du dossier sont renseignées.
    """
    dates = []
    for attr, cols in (("sansplomb", ["ttc", "ht", "accise", "tva", "brent_ceur_l",
                                     "raffinage_ceur_l", "transport_annuel_ceur_l"]),
                       ("elec_mensuel", ["ttc", "hors_taxes", "tva"])):
        df = getattr(bundle, attr, None)
        if df is None or "mois" not in df.columns:
            continue
        presentes = [c for c in cols if c in df.columns]
        if not presentes:
            continue
        complet = df[presentes].notna().all(axis=1)
        if complet.any():
            dates.append(pd.to_datetime(df.loc[complet, "mois"]).max())
    return min(dates) if dates else None


def _aval(df, suffixe: str = "_constants"):
    """Tout ce qui sépare le baril du prix hors taxes : raffinage, logistique, marges.

    Défini par soustraction de deux séries publiées, et non par la somme des postes
    détaillés. La somme passerait par la série de transport-distribution, qui est
    annuelle et reconduite, et par l'écart de bouclage que personne ne sait affecter.
    La soustraction ne doit rien ni à l'une ni à l'autre : elle vaut sur toute la
    période, pas seulement depuis 2015, et elle ne cache aucun résidu.
    """
    ht = pd.to_numeric(df[f"ht{suffixe}"], errors="coerce")
    brut = pd.to_numeric(df[f"brent_ceur_l{suffixe}"], errors="coerce")
    return ht - brut
