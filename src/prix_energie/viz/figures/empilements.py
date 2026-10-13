"""Figures en aires et en barres empilées : la structure d'un prix."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from prix_energie.journal import log

from prix_energie.viz.style import BLEUS, BLOC_INDETERMINE, FIGSIZE, INK, INK_2, SERIES, SURFACE, _finish
from prix_energie.viz.figures.communs import _available, _base_commune, _courbes, _en_indice, _marquer_fin, _plage, _postes_ht, _rupture


def decomposition_barres(df: pd.DataFrame, titre: str, outdir: Path, stem: str,
                         constants: bool = False, ref_label: str = "",
                         unite: str = "c€/l", detail: pd.DataFrame | None = None,
                         solde_label: str = "", repli_label: str = "Production et acheminement",
                         source: str = "", part: bool = False) -> Path | None:
    """Décomposition en barres empilées, moyennes annuelles, hors-taxes ouvert.

    Sur vingt ans de relevés mensuels, une aire empilée devient une masse bruitée où
    la structure du prix se perd. Une barre par année la rend au contraire lisible :
    on voit la part de chaque bloc et son évolution, au prix du détail infra-annuel
    que les sections précédentes reprennent.

    `detail` est une table annuelle des postes du hors-taxes, une colonne par poste,
    déjà libellée. Elle ne couvre pas forcément toute la période : le TURPE n'est
    publié qu'à partir de 2017, le raffinage qu'à partir de 2015 : et les années
    qu'elle ne couvre pas gardent un bloc unique plutôt qu'un trou dans la pile.
    """
    s_ = "_constants" if constants else ""
    date_col = "mois" if "mois" in df.columns else "periode"
    inter = next((c for c in ("accise", "taxes_hors_tva") if f"{c}{s_}" in df.columns), None)
    brut = next((c for c in ("ht_non_decompose", "ht", "hors_taxes")
                 if f"{c}{s_}" in df.columns), None)
    if inter is None or brut is None or f"tva{s_}" not in df.columns:
        return None
    d = df.copy()
    d["_an"] = pd.to_datetime(d[date_col]).dt.year
    cols = [f"{brut}{s_}", f"{inter}{s_}", f"tva{s_}"]
    an = d.groupby("_an")[cols].mean().dropna()
    if not len(an):
        return None

    # Bleu pour tout ce qui relève du hors-taxes, orange puis vert pour les deux étages
    # de la fiscalité : la pile garde la même lecture que partout ailleurs, en trois
    # familles, même quand la première en compte quatre.
    blocs, teinte = [], 0
    for lab, v in _postes_ht(an[cols[0]], detail, solde_label, repli_label):
        if lab == repli_label:
            blocs.append((lab, v, BLOC_INDETERMINE))
        else:
            blocs.append((lab, v, BLEUS[teinte % len(BLEUS)]))
            teinte += 1
    blocs += [("Taxes hors TVA", an[cols[1]], SERIES[1]), ("TVA", an[cols[2]], SERIES[2])]

    # En part, chaque année est ramenée à 100 : les niveaux disparaissent et les
    # mouvements relatifs apparaissent, ce qu'une pile en centimes ne montre pas. Un
    # bloc qui garde la même hauteur en centimes y décroît si le prix total monte.
    total = an[cols].sum(axis=1)
    if part:
        blocs = [(lab, 100.0 * v / total, couleur) for lab, v, couleur in blocs]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    annees = [str(a) for a in an.index]
    bas = pd.Series(0.0, index=an.index)
    hauteur_min = (100.0 if part else float(total.max())) * 0.055
    for lab, v, color in blocs:
        v = v.fillna(0.0)
        if not (v.abs() > 1e-9).any():
            continue
        ax.bar(annees, v, bottom=bas, color=color, label=lab, width=0.72,
               edgecolor=SURFACE, linewidth=0.8)
        # Valeur de chaque bloc au centre de son segment, quand il est assez haut.
        # Le bleu clair réclame de l'encre foncée, le bleu soutenu du blanc.
        encre = INK if color in BLEUS[2:] else SURFACE
        for i, (b, h) in enumerate(zip(bas, v)):
            if h >= hauteur_min:
                ax.annotate(f"{h:.0f}", xy=(i, b + h / 2), ha="center", va="center",
                            fontsize=7, color=encre, fontweight="bold")
        bas = bas + v
    if not part:
        # Le total n'a d'intérêt qu'en niveau : en part il vaut 100 partout.
        for i, t in enumerate(bas):
            ax.annotate(f"{t:.0f}", xy=(i, t), xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=7.5, color=INK)
    # En part, la pile plafonne à 100 et la légende n'a plus où se poser : on garde la
    # même réserve de hauteur qu'en niveau plutôt que de la faire chevaucher les barres.
    ax.set_ylim(0, 119.0 if part else float(bas.max()) * 1.16)
    if part:
        ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.tick_params(axis="x", labelrotation=45, labelsize=7.5)
    for lab in ax.get_xticklabels():
        lab.set_ha("right")
    ax.legend(loc="upper left", ncols=3, fontsize=8, labelcolor=INK_2)
    if part:
        u = "% du prix payé"
    else:
        u = (f"{unite} (euros constants {ref_label})".strip() if constants
             else f"{unite} (euros courants)")
    _finish(ax, titre, u, "Moyennes annuelles. "
            + (source or "Sources : Weekly Oil Bulletin, Eurostat, CRE."))
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def decomposition(df: pd.DataFrame, titre: str, outdir: Path, stem: str,
                  constants: bool = False, ref_label: str = "", rupture=None) -> Path | None:
    """Aires empilées : composantes du prix à la pompe.

    Même forme que la décomposition de l'électricité, pour que les trois produits
    se lisent de la même façon : un empilement dont la somme est le prix payé.
    """
    suffixe = "_constants" if constants else ""
    comp = _available(df, suffixe=suffixe)
    if not comp:
        log.warning("Figures : aucune composante renseignée pour %s", titre)
        return None
    if len(comp) > len(SERIES):
        # Tronquer en silence amputerait le total affiché d'une composante entière
        # (la TVA, en l'occurrence) : le graphique ne vaudrait plus le prix TTC.
        ecartees = [lab for _, lab in comp[len(SERIES):]]
        log.warning("Figures : %d composantes pour %d couleurs : %s non tracée(s). "
                    "Le total affiché est inférieur au prix TTC.",
                    len(comp), len(SERIES), ", ".join(ecartees))
        comp = comp[:len(SERIES)]

    # Ne tracer que les mois où toutes les composantes retenues sont connues. Un
    # `fillna(0)` y ferait tomber la pile à zéro : les deux derniers mois basculent
    # de `ht_non_decompose` vers `cotation`, qui vient d'être écartée du graphique -
    # et cette chute se lirait comme un prix nul.
    cols = [c for c, _ in comp]
    complet = df[cols].notna().all(axis=1)
    if not complet.all():
        log.info("Figures : %d mois sur %d écartés du graphique (composante manquante)",
                 int((~complet).sum()), len(df))
    d = df.loc[complet]
    if not len(d):
        return None
    x = pd.to_datetime(d["mois"])
    ys = [pd.to_numeric(d[c], errors="coerce").values for c, _ in comp]
    labels = [lab for _, lab in comp]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    # Le liseré couleur-surface sépare les bandes sans ajouter d'encre.
    ax.stackplot(x, *ys, labels=labels, colors=SERIES[:len(ys)],
                 edgecolor=SURFACE, linewidth=0.8)

    # Libellé direct au dernier point, au milieu de chaque bande.
    cum = 0.0
    for (col, lab), y in zip(comp, ys):
        milieu = cum + y[-1] / 2.0
        cum += y[-1]
        if y[-1] > 0:
            ax.annotate(lab, xy=(x.iloc[-1], milieu), xytext=(6, 0),
                        textcoords="offset points", va="center",
                        fontsize=8, color=INK_2)

    if rupture is not None:
        _rupture(ax, rupture[0], rupture[1], rupture[2])
    ax.set_xlim(*_plage(x.min(), x.max()))
    ax.set_ylim(bottom=0)
    _marquer_fin(ax, x.max())
    ax.legend(loc="upper left", ncols=min(len(labels), 3), fontsize=8, labelcolor=INK_2)
    unite = f"c€/l (euros constants {ref_label})".strip() if constants else "c€/l (euros courants)"
    _finish(ax, titre, unite,
            "Sources : Commission européenne (Weekly Oil Bulletin), DGEC.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def composantes_taxes(df: pd.DataFrame, titre: str, outdir: Path, stem: str,
                      constants: bool = False, ref_label: str = "",
                      unite: str = "c€/l", indice: bool = False, base_date=None,
                      rupture=None) -> Path | None:
    """Les deux étages de la fiscalité, suivis séparément.

    Pendant exact de `composantes_ht` : même forme, même hiérarchie de traits, le
    total en noir et les composantes en couleur. C'est ici que se lisent les décisions
    publiques : une accise se change par décision, un prix de marché non.
    """
    s = "_constants" if constants else ""
    # Carburants et électricité n'utilisent pas les mêmes colonnes, mais les deux
    # couches sont les mêmes : une taxe assise sur le volume, puis la TVA par-dessus.
    intermediaire = next((c for c in ("accise", "taxes_hors_tva") if f"{c}{s}" in df.columns), None)
    if intermediaire is None or f"tva{s}" not in df.columns:
        return None
    date_col = "mois" if "mois" in df.columns else "periode"
    num = lambda c: pd.to_numeric(df[c], errors="coerce")  # noqa: E731
    inter, tva = num(f"{intermediaire}{s}"), num(f"tva{s}")
    complet = inter.notna() & tva.notna()
    if not complet.any():
        return None
    d = df.loc[complet]
    inter, tva = inter[complet], tva[complet]
    unite_txt = f"{unite} (euros constants {ref_label})".strip() if constants \
        else f"{unite} (euros courants)"
    series = [("Taxes hors TVA", inter), ("TVA", tva)]
    if indice:
        mois = pd.to_datetime(d[date_col])
        b = None
        if base_date is not None:
            candidats = d.index[mois <= pd.Timestamp(base_date)]
            b = candidats[-1] if len(candidats) else None
        if b is None:
            b = _base_commune(series)
        d_base = pd.to_datetime(d[date_col]).loc[b] if b in d.index else None
        tot = _en_indice([("Total des taxes", inter + tva)], b)
        return _courbes(pd.to_datetime(d[date_col]), _en_indice(series, b),
                        titre, "indice, base 100",
                        "Sources : Weekly Oil Bulletin, Eurostat, CRE.",
                        outdir, stem, total=tot[0] if tot else None, base_indice=d_base, rupture=rupture)
    return _courbes(
        pd.to_datetime(d[date_col]), series,
        titre, unite_txt,
        "Sources : Weekly Oil Bulletin, Eurostat, CRE.",
        outdir, stem, total=("Total des taxes", inter + tva), rupture=rupture)


def composantes_ht(df: pd.DataFrame, titre: str, outdir: Path, stem: str,
                   constants: bool = False, ref_label: str = "",
                   indice: bool = False, base_date=None, rupture=None) -> Path | None:
    """Ce qu'il y a dans le prix hors taxes : brut, raffinage, acheminement.

    En euros constants, on lit l'évolution réelle : une hausse du transport-distribution
    qui suit l'inflation n'est pas un renchérissement, alors qu'elle en a l'air en
    euros courants.
    """
    suffixe = "_constants" if constants else ""
    besoin = tuple(f"{c}{suffixe}" for c in
                   ("brent_ceur_l", "raffinage_ceur_l", "transport_annuel_ceur_l"))
    if not all(c in df.columns for c in besoin):
        return None
    d = df[df[list(besoin)].notna().any(axis=1)]
    if not len(d):
        log.info("Figures : aucune décomposition du hors-taxes pour %s", titre)
        return None
    num = lambda c: pd.to_numeric(d[c], errors="coerce")  # noqa: E731
    note = "Sources : INSEE (Brent), DGEC (raffinage, transport-distribution)."
    composantes = [("Pétrole brut (Brent)", num(f"brent_ceur_l{suffixe}")),
                   ("Raffinage", num(f"raffinage_ceur_l{suffixe}")),
                   ("Transport-distribution", num(f"transport_annuel_ceur_l{suffixe}"))]
    cumul = pd.concat([v for _, v in composantes], axis=1).sum(axis=1, min_count=3)
    # Écart recalculé sur les colonnes réellement tracées : en euros constants, celui
    # des euros courants serait faux de tout le déflateur.
    ecart = (num(f"ht{suffixe}") - cumul).dropna()
    if len(ecart):
        note += (f" Écart de bouclage moyen : {ecart.mean():+.2f} c€/l "
                 f"({100 * ecart.mean() / num(f'ht{suffixe}').mean():+.0f} % du hors-taxes).")
    unite = f"c€/l (euros constants {ref_label})".strip() if constants else "c€/l (euros courants)"
    if indice:
        # Le total garde son rôle et son trait noir : l'indexer avec les composantes
        # lui ferait prendre un slot de couleur et décalerait toutes les autres.
        mois = pd.to_datetime(d["mois"])
        b = None
        if base_date is not None:
            candidats = d.index[mois <= pd.Timestamp(base_date)]
            b = candidats[-1] if len(candidats) else None
        if b is None:
            b = _base_commune(composantes + [("ht", num(f"ht{suffixe}"))])
        tot = _en_indice([("Prix hors taxes", num(f"ht{suffixe}"))], b)
        d_base = pd.to_datetime(d["mois"]).loc[b] if b in d.index else None
        return _courbes(pd.to_datetime(d["mois"]), _en_indice(composantes, b),
                        titre, "indice, base 100", note, outdir, stem,
                        total=tot[0] if tot else None, base_indice=d_base, rupture=rupture)
    return _courbes(
        pd.to_datetime(d["mois"]), composantes,
        titre, unite, note, outdir, stem,
        total=("Prix hors taxes", num(f"ht{suffixe}")),
        somme=("Somme des trois composantes", cumul), rupture=rupture)


def electricite_composantes(df: pd.DataFrame | None, outdir: Path, stem: str) -> Path | None:
    """Décomposition Eurostat du prix de l'électricité, TURPE et taxes séparés.

    Les codes Eurostat sont opaques : NETC est le coût des réseaux, c'est-à-dire le
    TURPE ; TAX_ENV porte l'accise sur l'électricité (ex-CSPE/TICFE). On agrège les
    taxes résiduelles plutôt que d'aligner sept courbes presque plates.
    """
    if df is None or not len(df):
        return None
    d = df.copy()
    num = lambda c: pd.to_numeric(d[c], errors="coerce") if c in d.columns else None  # noqa: E731
    # TAX_FEE_LEV_CHRG est volontairement exclu : c'est un agrégat qui recoupe les
    # autres postes de taxes, pas un poste supplémentaire. Contrôle sur 2017-2025 :
    # sans lui, la somme des composantes colle au prix TTC observé à 0,04 c€/kWh près ;
    # avec lui, elle le dépasse de 6,13 c€/kWh, soit près d'un quart du prix.
    autres = [c for c in ("TAX_CAP", "TAX_NUC", "TAX_RNW", "OTH") if c in d.columns]
    somme_autres = d[autres].apply(pd.to_numeric, errors="coerce").sum(axis=1) if autres else None
    composantes = [("Fourniture d'énergie", num("NRG_SUP")),
                   ("Réseau (TURPE)", num("NETC")),
                   ("Accise sur l'électricité", num("TAX_ENV")),
                   ("Autres taxes et contributions", somme_autres),
                   ("TVA", num("VAT"))]
    # Ici les composantes Eurostat couvrent tout le prix : leur somme *est* le TTC,
    # il n'y a donc pas d'écart de bouclage à montrer.
    tracees = [(lab, v) for lab, v in composantes if v is not None and v.notna().any()]
    if not tracees:
        return None

    # Barres et non courbes : ces valeurs sont annuelles. Une ligne entre deux points
    # annuels dessinerait une progression continue au fil des mois, qui n'existe pas -
    # un tarif tient un palier puis change d'un coup. Et comme les composantes somment
    # exactement au TTC (contrôlé à 0,04 c€/kWh près), l'empilement dit vrai.
    annees = [f"{p:%Y}" for p in pd.to_datetime(d["periode"])]
    fig, ax = plt.subplots(figsize=FIGSIZE)

    bas = pd.Series(0.0, index=d.index)
    for (lab, v), color in zip(tracees, SERIES):
        vals = v.fillna(0.0)
        ax.bar(annees, vals, bottom=bas, color=color, label=lab,
               width=0.68, edgecolor=SURFACE, linewidth=0.8)
        bas = bas + vals
    for i, t in enumerate(bas):
        ax.annotate(f"{t:.1f}", xy=(i, t), xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=8, color=INK)
    ax.set_ylim(0, float(bas.max()) * 1.12)
    titre = "Électricité ménages – décomposition annuelle du prix (bande 2 500–4 999 kWh)"

    ax.legend(loc="upper left", ncols=3, fontsize=8, labelcolor=INK_2)
    _finish(ax, titre, "c€/kWh", "Source : Eurostat nrg_pc_204_c. Valeur au-dessus de chaque barre : prix TTC.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def bandes_consommation(df: pd.DataFrame | None, labels: dict, outdir: Path, stem: str) -> Path | None:
    """Prix TTC selon le volume consommé par le ménage.

    Le prix au kWh dépend fortement de la tranche : l'abonnement, fixe, pèse d'autant
    plus que la consommation est faible. La bande de référence retenue ailleurs
    (2 500–4 999 kWh) n'est donc représentative que d'un logement sans chauffage
    électrique : d'où cette comparaison.
    """
    if df is None or not len(df):
        return None
    # Des plus petits consommateurs aux plus gros : l'ordre des slots suit l'ordre
    # des tranches, pour que la lecture des couleurs suive celle du volume.
    ordre = ["KWH_LT1000", "KWH1000-2499", "KWH2500-4999", "KWH5000-14999", "KWH_GE15000"]
    courts = {"KWH_LT1000": "< 1 000 kWh", "KWH1000-2499": "1 000–2 499",
              "KWH2500-4999": "2 500–4 999 (référence)", "KWH5000-14999": "5 000–14 999",
              "KWH_GE15000": "≥ 15 000 kWh"}
    series = [(courts.get(c, labels.get(c, c)), pd.to_numeric(df[c], errors="coerce"))
              for c in ordre if c in df.columns]
    total = ("Toutes tranches", pd.to_numeric(df["TOT_KWH"], errors="coerce")) if "TOT_KWH" in df.columns else None
    return _courbes(
        pd.to_datetime(df["periode"]), series,
        "Électricité ménages – prix TTC selon la consommation annuelle", "c€/kWh",
        "Source : Eurostat nrg_pc_204, prix semestriels France.",
        outdir, stem, total=total, escalier=True)
