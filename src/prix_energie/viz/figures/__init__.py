"""Figures du dossier.

Le découpage suit ce que les figures font : `style` porte la palette et le
chrome, `communs` les utilitaires d'axes, puis `empilements`, `courbes` et
`dispersion` les trois familles de tracés, et `controle` les figures qui
servent à vérifier les données plutôt qu'à les montrer.

Ce module ne garde que le répartiteur.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from prix_energie.bundle import Bundle
from prix_energie.journal import log

from prix_energie.viz.style import PLAGE, _style
from prix_energie.viz.figures.communs import _base_globale, _detail_annuel
from prix_energie.viz.figures.empilements import bandes_consommation, composantes_ht, composantes_taxes, decomposition, decomposition_barres, electricite_composantes
from prix_energie.viz.figures.courbes import accises_comparees, aval_petrolier, brent, courant_vs_constant, cout_km, cout_km_indice, electricite, electricite_hors_taxes, electricite_taxes_detail, energie_panneaux, part_taxes, solde_compare
from prix_energie.viz.figures.dispersion import cascade_couts, postes_dispersion, zoom_recent
from prix_energie.viz.figures.controle import controle, inflation, serie_longue

def write_figures(bundle: Bundle, outdir: Path) -> list[Path]:
    """Produit toutes les figures possibles. Une série absente est sautée, pas simulée."""
    _style()
    outdir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []

    # Plage commune : de la première à la dernière observation du dossier.
    bornes = []
    # Le Brent est exclu du calcul : il remonte à 1990 et écraserait les vingt ans
    # qui intéressent le dossier. Il sera donc tronqué comme les autres, et sa note
    # le signale.
    for attr in ("sansplomb", "gazole", "elec_mensuel", "cout_km"):
        df = getattr(bundle, attr, None)
        if df is None:
            continue
        col = next((c for c in ("mois", "date", "periode") if c in df.columns), None)
        if col:
            d = pd.to_datetime(df[col])
            bornes.append((d.min(), d.max()))
    if bornes:
        PLAGE["fin"] = max(b[1] for b in bornes)
        log.info("Figures : axe du temps commun %s → %s",
                 f"{PLAGE['debut']:%Y-%m}", f"{PLAGE['fin']:%Y-%m}")

    base_g = _base_globale(bundle)
    if base_g is not None:
        log.info("Figures : base 100 commune fixée à %s", f"{base_g:%Y-%m}")
    ref, ref_ts = "", None
    if bundle.ipc is not None and len(bundle.ipc):
        ref_ts = pd.to_datetime(bundle.ipc["date"]).max()
        ref = f"({ref_ts:%Y-%m})"

    # Le hors-taxes des carburants ne s'ouvre qu'à partir de 2015 : avant, la marge de
    # raffinage n'est pas publiée, et nommer « transport-distribution » un solde qui
    # contiendrait aussi le raffinage serait faux.
    def barres_carburant(df: pd.DataFrame, constants: bool) -> dict:
        sfx = "_constants" if constants else ""
        return {"detail": _detail_annuel(df, "mois",
                                         [("Pétrole brut", "brent_ceur_l"),
                                          ("Raffinage", "raffinage_ceur_l")], sfx),
                "solde_label": "Transport-distribution",
                "repli_label": "Production et acheminement",
                "source": "Sources : Weekly Oil Bulletin, INSEE, DGEC."}

    chain = getattr(bundle.choices, "sp_e10_chain", None)
    rup_sp = ((pd.Timestamp(chain + "-01"), "SP95-E5 → SP95-E10", True) if chain else None)
    for attr, nom, stem in (("sansplomb", "Sans-plomb", "sansplomb"), ("gazole", "Gazole", "gazole")):
        df = getattr(bundle, attr)
        if df is None:
            continue
        rup = rup_sp if attr == "sansplomb" else None
        out += [p for p in (
            decomposition(df, f"{nom} – décomposition du prix à la pompe", outdir,
                          f"{stem}_decomposition", rupture=rup),
            decomposition(df, f"{nom} – décomposition du prix à la pompe – euros constants",
                          outdir, f"{stem}_decomposition_constants", constants=True, ref_label=ref, rupture=rup),
            composantes_ht(df, f"{nom} – composition du prix hors taxes", outdir, f"{stem}_hors_taxes", rupture=rup),
            composantes_ht(df, f"{nom} – prix hors taxes en euros constants", outdir,
                           f"{stem}_hors_taxes_constants", constants=True, ref_label=ref, rupture=rup),
            composantes_taxes(df, f"{nom} – accise et TVA", outdir, f"{stem}_taxes", rupture=rup),
            composantes_taxes(df, f"{nom} – accise et TVA, euros constants", outdir,
                              f"{stem}_taxes_constants", constants=True, ref_label=ref, rupture=rup),
            decomposition_barres(df, f"{nom} – structure du prix payé", outdir,
                                 f"{stem}_barres", **barres_carburant(df, False)),
            decomposition_barres(df, f"{nom} – structure du prix, euros constants", outdir,
                                 f"{stem}_barres_constants", constants=True, ref_label=ref,
                                 **barres_carburant(df, True)),
        ) if p]

    # Les trois énergies, une figure par unité monétaire.
    produits = [("Sans-plomb", bundle.sansplomb, "c€/l", "ttc", "ht"),
                ("Gazole", bundle.gazole, "c€/l", "ttc", "ht"),
                ("Électricité", bundle.elec_mensuel, "c€/kWh", "ttc", "hors_taxes")]
    for stem_p, en_constants in (("energie_courant", False), ("energie_constant", True)):
        p = energie_panneaux(produits, outdir, stem_p, constants=en_constants,
                             ref_label=ref)
        if p:
            out.append(p)
    p = part_taxes({"Sans-plomb": bundle.sansplomb, "Gazole": bundle.gazole,
                    "Électricité": bundle.elec_mensuel}, outdir, "part_taxes")
    if p:
        out.append(p)
    for stem_b, kw in (("brent", {}),
                       ("brent_constants", {"constants": True, "ref_label": ref})):
        p = brent(bundle.brent, outdir, stem_b, bundle.brent_source, **kw)
        if p:
            out.append(p)
    # Même forme que les carburants, en courant et en constant : six décompositions
    # comparables (deux carburants + l'électricité, x deux unités monétaires).
    # Série mensuelle prolongée de préférence au semestriel : même granularité que
    # les carburants, et couverture jusqu'au dernier barème connu.
    src_elec = bundle.elec_mensuel if bundle.elec_mensuel is not None else bundle.elec_semestriel
    rup_el = None
    if src_elec is not None and "source" in src_elec.columns:
        bascule = src_elec.loc[src_elec["source"] == "Tarif réglementé", "mois"]
        if len(bascule):
            rup_el = (pd.to_datetime(bascule).min(), "source : Eurostat → tarif réglementé", False)
    for stem_e, en_constants in (("electricite_decomposition", False),
                                 ("electricite_decomposition_constants", True)):
        p = electricite(src_elec, outdir, stem_e, constants=en_constants, ref_label=ref,
                        ancienne=bundle.elec_ancienne if not en_constants else None,
                        rupture_source=rup_el)
        if p:
            out.append(p)
    p = electricite_composantes(bundle.elec_composantes, outdir, "electricite_composantes")
    if p:
        out.append(p)
    for stem_a, en_const in (("accises_comparees", False),
                             ("accises_comparees_constants", True)):
        p = accises_comparees(bundle.sansplomb, bundle.gazole, outdir, stem_a,
                              constants=en_const, ref_label=ref)
        if p:
            out.append(p)
    for nom_z, df_z, stem_z in (("Sans-plomb", bundle.sansplomb, "zoom_12m_sansplomb"),
                                ("Gazole", bundle.gazole, "zoom_12m_gazole")):
        p = zoom_recent(df_z, nom_z, outdir, stem_z)
        if p:
            out.append(p)
    p = postes_dispersion(bundle.sansplomb, bundle.gazole, outdir, "postes_dispersion")
    if p:
        out.append(p)
    p = cascade_couts(bundle.sansplomb, bundle.gazole, outdir, "cascade_couts",
                      stations=bundle.stations)
    if p:
        out.append(p)
    for stem_s, en_const in (("solde_compare", False),
                             ("solde_compare_constants", True)):
        p = solde_compare(bundle.sansplomb, bundle.gazole, outdir, stem_s,
                          constants=en_const, ref_label=ref)
        if p:
            out.append(p)
    for stem_c, en_const in (("cout_100km", False), ("cout_100km_constants", True)):
        p = cout_km(bundle.cout_km, bundle.choices, outdir, stem_c,
                    constants=en_const, ref_label=ref)
        if p:
            out.append(p)
    p = cout_km_indice(bundle.cout_km, outdir, "cout_100km_indice", base_date=base_g)
    if p:
        out.append(p)
    p = inflation(bundle.ipc, outdir, "inflation")
    if p:
        out.append(p)
    if src_elec is not None:
        for stem_t, en_const in (("electricite_taxes", False),
                                 ("electricite_taxes_constants", True)):
            p = composantes_taxes(src_elec, "Électricité – accise et TVA"
                                  + (" – euros constants" if en_const else ""),
                                  outdir, stem_t, constants=en_const, ref_label=ref,
                                  unite="c€/kWh")
            if p:
                out.append(p)
        # Le hors-taxes de l'électricité s'ouvre en fourniture et réseau à partir de
        # 2017 seulement, date à laquelle Eurostat publie la ventilation.
        for stem_b, en_const in (("electricite_barres", False),
                                 ("electricite_barres_constants", True)):
            det = _detail_annuel(bundle.elec_composantes, "periode",
                                 [("Fourniture d'énergie", "NRG_SUP")],
                                 "_constants" if en_const else "")
            p = decomposition_barres(src_elec, "Électricité – structure du prix payé"
                                     + (", euros constants" if en_const else ""),
                                     outdir, stem_b, constants=en_const, ref_label=ref,
                                     unite="c€/kWh", detail=det,
                                     solde_label="Réseau (TURPE)",
                                     repli_label="Production et acheminement",
                                     source="Sources : Eurostat, CRE.")
            if p:
                out.append(p)
    # Mêmes blocs et mêmes couleurs que les barres en centimes : les deux figures ne
    # diffèrent que par l'unité, et se lisent donc l'une après l'autre sans réapprendre.
    for df_p, nom_p, stem_p in ((bundle.sansplomb, "Sans-plomb", "sansplomb_barres_part"),
                                (bundle.gazole, "Gazole", "gazole_barres_part")):
        if df_p is None:
            continue
        p = decomposition_barres(df_p, f"{nom_p} – part de chaque poste dans le prix payé",
                                 outdir, stem_p, constants=True, ref_label=ref,
                                 part=True, **barres_carburant(df_p, True))
        if p:
            out.append(p)
    p = electricite_taxes_detail(bundle.elec_composantes, outdir, "electricite_taxes_detail")
    if p:
        out.append(p)
    for stem_h, en_const in (("electricite_hors_taxes", False),
                             ("electricite_hors_taxes_constants", True)):
        p = electricite_hors_taxes(bundle.elec_composantes, bundle.elec_semestriel,
                                   outdir, stem_h, constants=en_const, ref_label=ref)
        if p:
            out.append(p)
    p = bandes_consommation(bundle.elec_bandes, getattr(bundle, "elec_bandes_labels", {}),
                            outdir, "electricite_bandes_consommation")
    if p:
        out.append(p)

    p = courant_vs_constant(bundle.sansplomb, bundle.gazole, outdir,
                            "courant_vs_constant", ref, ref_date=ref_ts)
    if p:
        out.append(p)
    p = aval_petrolier(bundle.sansplomb, bundle.gazole, outdir, "aval_petrolier", ref)
    if p:
        out.append(p)
    p = serie_longue(bundle, outdir, "serie_longue")
    if p:
        out.append(p)
    p = controle(bundle, outdir, "controle_sources")
    if p:
        out.append(p)

    for path in out:
        log.info("Figure : %s", path.name)
    return out
