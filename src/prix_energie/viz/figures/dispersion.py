"""Figures de dispersion : boîtes à moustaches et fenêtre glissante."""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pandas as pd

from prix_energie.viz.style import AXIS, FIGSIZE, INK, INK_2, MUTED, SERIES, SURFACE, _finish
from prix_energie.viz.figures.communs import _meta_stations, _trace_prolonge



def cascade_couts(sansplomb: pd.DataFrame | None, gazole: pd.DataFrame | None,
                  outdir: Path, stem: str, mois_glissants: int = 12,
                  stations: pd.DataFrame | None = None) -> Path | None:
    """Le prix se construit étage par étage, chaque étage avec sa dispersion.

    Une décomposition ordinaire montre ce que pèse chaque poste. Celle-ci montre autre
    chose : à quel étage la variabilité entre dans le prix. La boîte s'élargit quand on
    ajoute un poste qui bouge, se translate sans changer de taille quand on ajoute un
    montant fixe. L'accise se reconnaît ainsi à l'œil : la boîte monte de soixante
    centimes sans gagner un millimètre de hauteur.

    L'avant-dernier étage est le prix payé réellement mesuré, posé à côté du prix
    reconstitué : l'écart entre les deux est celui que la décomposition ne sait pas
    expliquer.

    Le dernier étage change de nature, et c'est tout son intérêt. Les précédents
    dispersent douze moyennes nationales dans le temps ; celui-là disperse dix mille
    stations un même jour. Mis côte à côte, ils disent lequel des deux écarts pèse le
    plus sur ce qu'un automobiliste paie : et ce n'est pas celui que le dossier suit
    depuis vingt ans.
    """
    ETAGES = [("Pétrole brut", ["brent_ceur_l"]),
              ("+ Raffinage", ["brent_ceur_l", "raffinage_ceur_l"]),
              ("+ Acheminement", ["brent_ceur_l", "raffinage_ceur_l", "transport"]),
              ("+ Accise", ["brent_ceur_l", "raffinage_ceur_l", "transport", "accise"]),
              ("+ TVA", ["brent_ceur_l", "raffinage_ceur_l", "transport", "accise", "tva"]),
              ("Prix payé\n(moyenne du mois)", ["ttc"])]
    COL_STATION = {"Sans-plomb": "sansplomb", "Gazole": "gazole"}
    jeux = []
    for nom, d in (("Sans-plomb", sansplomb), ("Gazole", gazole)):
        if d is None or not len(d):
            continue
        e = d.copy()
        e["mois"] = pd.to_datetime(e["mois"])
        e = e.sort_values("mois").dropna(subset=["ttc"]).tail(mois_glissants)
        e["transport"] = pd.to_numeric(e.get("transport_distribution"), errors="coerce")
        if "transport_annuel_ceur_l" in e.columns:
            e["transport"] = e["transport"].fillna(
                pd.to_numeric(e["transport_annuel_ceur_l"], errors="coerce"))
        if len(e):
            jeux.append((nom, e))
    if len(jeux) < 2:
        return None

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ecart, largeur = 0.17, 0.30
    for k, ((nom, e), couleur) in enumerate(zip(jeux, (SERIES[0], SERIES[1]))):
        donnees, positions = [], []
        for i, (_, cols) in enumerate(ETAGES):
            cumul = None
            for c in cols:
                v = pd.to_numeric(e[c], errors="coerce")
                cumul = v if cumul is None else cumul + v
            cumul = (cumul / 100.0).dropna()
            if len(cumul):
                donnees.append(cumul.values)
                positions.append(i + (ecart if k else -ecart))
        if not donnees:
            continue
        bp = ax.boxplot(donnees, positions=positions, widths=largeur, patch_artist=True,
                        medianprops={"color": SURFACE, "linewidth": 1.4},
                        whiskerprops={"color": couleur, "linewidth": 1.1},
                        capprops={"color": couleur, "linewidth": 1.1},
                        flierprops={"marker": ".", "markersize": 4,
                                    "markerfacecolor": couleur, "markeredgecolor": "none"})
        for boite in bp["boxes"]:
            boite.set(facecolor=couleur, alpha=0.55, edgecolor=couleur, linewidth=1.1)
        bp["boxes"][0].set_label(nom)
        # Médianes reliées : le trait montre le prix se construire d'un étage à l'autre.
        medianes = [float(pd.Series(v).median()) for v in donnees]
        ax.plot(positions, medianes, color=couleur, linewidth=1.0, alpha=0.6,
                linestyle=(0, (3, 2)), zorder=1)
        # Position du dernier mois dans chaque boîte : c'est lui qui se compare aux
        # stations, relevées le même mois, et non la médiane des douze.
        for pos, serie in zip(positions, donnees):
            ax.plot([pos], [float(serie[-1])], marker="D", markersize=4.5, color=INK,
                    zorder=6, markeredgecolor=SURFACE, markeredgewidth=0.7)

    # Dernier étage : la dispersion entre stations, à part et signalée comme telle.
    n_stations = 0
    if stations is not None and len(stations):
        i = len(ETAGES)
        for k, ((nom, _e), couleur) in enumerate(zip(jeux, (SERIES[0], SERIES[1]))):
            col = COL_STATION.get(nom)
            if col is None or col not in stations.columns:
                continue
            v = pd.to_numeric(stations[col], errors="coerce").dropna()
            if not len(v):
                continue
            n_stations = max(n_stations, len(v))
            bp = ax.boxplot([v.values], positions=[i + (ecart if k else -ecart)],
                            widths=largeur, patch_artist=True,
                            medianprops={"color": SURFACE, "linewidth": 1.4},
                            whiskerprops={"color": couleur, "linewidth": 1.1},
                            capprops={"color": couleur, "linewidth": 1.1},
                            flierprops={"marker": ".", "markersize": 2.5,
                                        "markerfacecolor": couleur,
                                        "markeredgecolor": "none", "alpha": 0.5})
            for boite in bp["boxes"]:
                boite.set(facecolor=couleur, alpha=0.30, edgecolor=couleur,
                          linewidth=1.1, hatch="///")
        if n_stations:
            fen = _meta_stations(stations, "fraicheur_jours")
            ETAGES = ETAGES + [(f"Prix en station\n({fen} jours)" if fen
                                else "Prix en station", None)]
            # Trait de séparation : à gauche le temps, à droite la géographie.
            ax.axvline(len(ETAGES) - 1.5, color=AXIS, linewidth=1.0,
                       linestyle=(0, (2, 3)), zorder=0)

    dernier = max(pd.to_datetime(e["mois"]).max() for _, e in jeux)
    debut = min(pd.to_datetime(e["mois"]).min() for _, e in jeux)
    ax.set_xticks(range(len(ETAGES)))
    ax.set_xticklabels([lab for lab, _ in ETAGES], fontsize=8.5)
    ax.set_xlim(-0.6, len(ETAGES) - 0.4)
    ax.set_ylim(bottom=0)
    ax.grid(axis="x", visible=False)
    poignees, etiquettes = ax.get_legend_handles_labels()
    poignees.append(Line2D([], [], marker="D", linestyle="none", markersize=5,
                           color=INK, markeredgecolor=SURFACE, markeredgewidth=0.7))
    etiquettes.append(f"Dernier mois ({dernier:%m/%Y})")
    ax.legend(poignees, etiquettes, loc="upper left", fontsize=8, labelcolor=INK_2,
              frameon=False)
    note = (f"Chaque boîte cumule les postes situés à sa gauche. Période "
            f"{debut:%m/%Y} – {dernier:%m/%Y}.")
    if n_stations:
        ref = _meta_stations(stations, "maj_reference")
        ref = pd.Timestamp(ref) if ref is not None else None
        jours = _meta_stations(stations, "fraicheur_jours")
        note += (f" À droite du pointillé, {n_stations} stations"
                 + (f" au {ref:%d/%m/%Y}" if ref is not None else "")
                 + (f", fenêtre de {jours} jours" if jours else "") + ".")
    _finish(ax, f"Décomposition progressive des coûts, {mois_glissants} mois glissants",
            "€/l, cumulé",
            note + " Sources : Weekly Oil Bulletin, DGEC, INSEE, data.economie.gouv.fr.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def postes_dispersion(sansplomb: pd.DataFrame | None, gazole: pd.DataFrame | None,
                      outdir: Path, stem: str, mois_glissants: int = 12) -> Path | None:
    """Dispersion de chaque poste du prix sur une année, les deux carburants côte à côte.

    La question à laquelle cette figure répond : d'où vient la variabilité du prix ?
    Une boîte large désigne un poste qui bouge, une boîte écrasée un poste qui ne bouge
    pas. L'accise se réduit à un trait, le pétrole brut s'étale : on lit en une seconde
    ce qu'une courbe superposée à sept autres ne montrait pas.

    La distribution porte sur les douze derniers mois connus, et non sur l'année civile :
    une année en cours n'offrirait que les mois écoulés, et la dispersion se réduirait à
    mesure qu'on avance dedans. Douze mois glissants couvrent toujours un cycle complet.

    Les composantes n'étant publiées qu'au mois, un mois isolé n'aurait qu'une valeur par
    poste et aucune dispersion : c'est pourquoi la fenêtre est nécessairement large. Le
    losange marque le dernier mois connu, pour situer le présent dans la distribution.
    """
    # Le second membre de chaque libellé est la granularité de la source. Sans elle,
    # on comparerait des dispersions qui ne mesurent pas la même chose : celle de
    # l'accise reflète un barème fixe, celle du transport un changement de méthode,
    # celle du prix payé une vraie variation de marché.
    POSTES = [("Pétrole brut", "brent_ceur_l", "mensuel"),
              ("Raffinage", "raffinage_ceur_l", "mensuel"),
              ("Transport-distribution", "transport", "annuel, reconduit"),
              ("Accise", "accise", "barème"),
              ("TVA", "tva", "calculée"),
              ("Prix payé", "ttc", "relevés hebdo.")]
    jeux = []
    for nom, d in (("Sans-plomb", sansplomb), ("Gazole", gazole)):
        if d is None or not len(d):
            continue
        e = d.copy()
        e["mois"] = pd.to_datetime(e["mois"])
        e = e.sort_values("mois").dropna(subset=["ttc"]).tail(mois_glissants)
        if not len(e):
            continue
        # L'acheminement vient de la cotation quand elle existe, de la moyenne annuelle
        # sinon : c'est la même grandeur, mesurée avec deux précisions différentes.
        e["transport"] = pd.to_numeric(e.get("transport_distribution"), errors="coerce")
        if "transport_annuel_ceur_l" in e.columns:
            e["transport"] = e["transport"].fillna(
                pd.to_numeric(e["transport_annuel_ceur_l"], errors="coerce"))
        jeux.append((nom, e))
    if len(jeux) < 2:
        return None

    fig, ax = plt.subplots(figsize=FIGSIZE)
    largeur, ecart = 0.30, 0.17
    couleurs = (SERIES[0], SERIES[1])
    for k, ((nom, e), couleur) in enumerate(zip(jeux, couleurs)):
        donnees, positions = [], []
        for i, (_, col, _g) in enumerate(POSTES):
            v = pd.to_numeric(e[col], errors="coerce").dropna() / 100.0
            if len(v):
                donnees.append(v.values)
                positions.append(i + (ecart if k else -ecart))
        if not donnees:
            continue
        bp = ax.boxplot(donnees, positions=positions, widths=largeur, patch_artist=True,
                        medianprops={"color": SURFACE, "linewidth": 1.4},
                        whiskerprops={"color": couleur, "linewidth": 1.1},
                        capprops={"color": couleur, "linewidth": 1.1},
                        flierprops={"marker": ".", "markersize": 4,
                                    "markerfacecolor": couleur, "markeredgecolor": "none"})
        for boite in bp["boxes"]:
            boite.set(facecolor=couleur, alpha=0.55, edgecolor=couleur, linewidth=1.1)
        bp["boxes"][0].set_label(nom)
        # Dernier mois connu : un losange sur la boîte, pour situer le présent.
        for i, (_, col, _g) in enumerate(POSTES):
            v = pd.to_numeric(e[col], errors="coerce").dropna()
            if len(v):
                ax.plot([i + (ecart if k else -ecart)], [float(v.iloc[-1]) / 100.0],
                        marker="D", markersize=4.5, color=INK, zorder=6,
                        markeredgecolor=SURFACE, markeredgewidth=0.7)

    dernier = max(pd.to_datetime(e["mois"]).max() for _, e in jeux)
    debut = min(pd.to_datetime(e["mois"]).min() for _, e in jeux)
    ax.set_xticks(range(len(POSTES)))
    ax.set_xticklabels([f"{lab}\n({gran})" for lab, _, gran in POSTES], fontsize=8)
    ax.set_xlim(-0.6, len(POSTES) - 0.4)
    ax.set_ylim(bottom=0)
    ax.grid(axis="x", visible=False)
    # Le losange entre dans la légende : il porte une information que la note sous la
    # figure explique, mais qu'un lecteur pressé cherche d'abord au-dessus du tracé.
    poignees, etiquettes = ax.get_legend_handles_labels()
    poignees.append(Line2D([], [], marker="D", linestyle="none", markersize=5,
                           color=INK, markeredgecolor=SURFACE, markeredgewidth=0.7))
    etiquettes.append(f"Dernier mois connu ({dernier:%m/%Y})")
    ax.legend(poignees, etiquettes, loc="upper left", fontsize=8, labelcolor=INK_2,
              frameon=False)
    _finish(ax, f"Dispersion du coût par poste, {mois_glissants} mois glissants", "€/l",
            f"Boîte : moitié centrale des mois ; trait : médiane. Période "
            f"{debut:%m/%Y} – {dernier:%m/%Y}. Sources : Weekly Oil Bulletin, DGEC, INSEE.")
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def zoom_recent(df: pd.DataFrame | None, nom: str, outdir: Path, stem: str,
                mois_glissants: int = 12) -> Path | None:
    """Toutes les composantes des derniers mois, sur un même axe, en euros par litre.

    Figure de contrôle plus que de démonstration : elle met côte à côte ce qu'on
    reconstitue (brut + raffinage + acheminement) et ce qui est mesuré (le prix hors
    taxes publié), puis les deux étages de fiscalité et le prix payé. Si le trait du
    haut ne tombe pas sur le prix affiché à la pompe, la décomposition est fausse
    quelque part, et la figure dit où.

    Rien n'est empilé : chaque poste garde sa propre ligne de base, donc se lit en
    niveau et se compare aux autres, ce qu'un empilement interdit.

    Fenêtre glissante et non année civile : en début d'année, une figure « année en
    cours » n'aurait qu'un ou deux points, et sa lecture changerait de nature au fil
    des mois. Douze mois couvrent toujours un cycle, et la période est datée dans la
    note plutôt que dans le titre.
    """
    if df is None or not len(df):
        return None
    d = df.copy()
    d["mois"] = pd.to_datetime(d["mois"])
    d = d.sort_values("mois").dropna(subset=["ttc"]).tail(mois_glissants)
    if not len(d):
        return None
    num = lambda c: pd.to_numeric(d[c], errors="coerce") / 100.0 if c in d.columns else None  # noqa: E731

    brut, raff = num("brent_ceur_l"), num("raffinage_ceur_l")
    # La cotation Rotterdam vaut brut + raffinage. Quand les notes hebdomadaires la
    # donnent pour un mois que les séries mensuelles ne couvrent pas encore, elle
    # permet de boucler ce mois-là, sans pouvoir en séparer les deux postes.
    cotation = num("cotation")
    detail_absent = (brut.isna() | raff.isna()) if brut is not None and raff is not None else None

    # Acheminement : mesuré quand la cotation du mois est connue (hors-taxes − cotation),
    # sinon la moyenne annuelle publiée, sinon la dernière connue reconduite. Les deux
    # derniers cas sont des extrapolations et se tracent en tirets.
    transp = num("transport_distribution")
    reconduit = pd.Series(False, index=d.index)
    annuel = num("transport_annuel_ceur_l")
    if transp is None:
        transp = pd.Series(float("nan"), index=d.index)
    if annuel is not None:
        manque = transp.isna() & annuel.notna()
        transp = transp.where(~manque, annuel)
        reconduit |= manque
    if transp.isna().any():
        ref = pd.to_numeric(df.get("transport_annuel_ceur_l"), errors="coerce").dropna()
        if not len(ref):
            return None
        manque = transp.isna()
        transp = transp.where(~manque, float(ref.iloc[-1]) / 100.0)
        reconduit |= manque
    lib_transp = "Transport-distribution"
    if reconduit.any():
        lib_transp += " (partiellement reconduit)" if not reconduit.all() else " (reconduit)"

    # La somme boucle avec le détail quand il existe, avec la cotation sinon.
    base = (brut + raff)
    if cotation is not None:
        base = base.where(base.notna(), cotation)
    somme = base + transp
    x = d["mois"]
    fig, ax = plt.subplots(figsize=FIGSIZE)

    ttc, ht = num("ttc"), num("ht")
    # Enveloppe des relevés du mois : la moyenne mensuelle est inférieure au prix de fin
    # de mois quand le prix monte, donc à ce que le conducteur a payé en dernier.
    lo, hi = num("ttc_min"), num("ttc_max")
    if lo is not None and hi is not None and lo.notna().any():
        ax.fill_between(x, lo, hi, color=INK, alpha=0.13, linewidth=0,
                        label="Du premier au dernier relevé du mois", zorder=3)
    ax.plot(x, ttc, color=INK, linewidth=2.8, label="Prix payé (moyenne du mois)", zorder=6)
    ax.plot(x, ht, color=INK_2, linewidth=1.8, label="Prix hors taxes (publié)", zorder=5)
    ax.plot(x, somme, color=MUTED, linewidth=1.6, linestyle=(0, (4, 3)),
            label="Brut + raffinage + acheminement", zorder=4)
    # Le style ne sert plus qu'à une chose : plein pour une valeur mesurée, tirets pour
    # une valeur reconstituée. Les postes se distinguent donc par la seule couleur, d'où
    # le choix de teintes franchement séparées à l'intérieur de la famille bleue.
    # Huit séries sur un même axe : la famille chromatique du reste du dossier (tout le
    # hors-taxes en bleu) donnerait ici trois bleus voisins, indistinguables en trait
    # fin. Cette figure de contrôle prend donc des teintes franchement séparées, et
    # réserve le pointillé à une seule information : la valeur est reconstituée.
    reconstruit = (d["brent_reconstitue"].fillna(False).astype(bool)
                   if "brent_reconstitue" in d.columns else pd.Series(False, index=d.index))
    _trace_prolonge(ax, x, brut, reconstruit, SERIES[0], "Pétrole brut")
    ax.plot(x, raff, color=SERIES[3], linewidth=1.8, label="Raffinage")
    if detail_absent is not None and detail_absent.any() and cotation is not None:
        agrege = cotation.where(detail_absent)
        if agrege.notna().any():
            ax.plot(x, agrege, color=SERIES[0], linewidth=2.0, linestyle=(0, (2, 1.6)),
                    marker="o", markersize=4.5,
                    label="Cotation Rotterdam (brut + raffinage)")
    _trace_prolonge(ax, x, transp, reconduit, SERIES[6], lib_transp)
    for lab, col, couleur in (("Accise", "accise", SERIES[1]), ("TVA", "tva", SERIES[2])):
        v = num(col)
        if v is not None and v.notna().any():
            ax.plot(x, v, color=couleur, linewidth=1.8, label=lab)

    # Valeur de fin de chaque poste, écrite à droite de sa courbe. Plusieurs se touchent
    # : en septembre l'accise et le pétrole brut ne sont séparés que de cinq millièmes
    # d'euro : donc les étiquettes qui se chevaucheraient sont écartées verticalement,
    # la valeur imprimée restant celle du poste.
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    # Le millésime figure sur chaque graduation : la fenêtre est à cheval sur deux
    # années, et « janv. » seul ne dirait pas laquelle.
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    for lab in ax.get_xticklabels():
        lab.set_fontsize(7.5)
    # Marge à droite pour les étiquettes, sans aller jusqu'au mois suivant : un tick
    # supplémentaire ferait croire à une donnée manquante.
    ax.set_xlim(x.min() - pd.DateOffset(days=8), x.max() + pd.DateOffset(days=8))
    # Plafond fixe à 3 €/l : l'échelle ne dépend plus des valeurs de l'année, donc les
    # deux carburants se comparent d'une figure à l'autre sans recalibrer l'œil.
    ax.set_ylim(0, 3.0)
    # Légende hors de l'aire de tracé : avec huit séries, aucune position intérieure ne
    # laisse les courbes tranquilles. Le titre remonte d'autant.
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.005), ncols=3, fontsize=8,
              labelcolor=INK_2, frameon=False, borderaxespad=0)
    titre = f"{nom} – toutes les composantes du prix, douze derniers mois"
    _finish(ax, titre, "€/l (euros courants)",
            f"Période {x.min():%m/%Y} – {x.max():%m/%Y}. Sources : Weekly Oil Bulletin, "
            "DGEC, INSEE. Aucune autre taxe que l'accise et la TVA ne pèse sur les "
            "carburants.")
    ax.set_title(titre, pad=56)
    path = outdir / f"{stem}.png"
    fig.savefig(path)
    plt.close(fig)
    return path
