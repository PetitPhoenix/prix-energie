"""Assemblage des séries : tables mensuelles carburants, tables électricité, indicateurs séparés."""
from __future__ import annotations

import re

import pandas as pd

from prix_energie.common import monthly_mean, vat_rate
from prix_energie.journal import Journal
from prix_energie.bundle import Bundle
from prix_energie.config import Choices
from prix_energie.donnees.contracts import Contract, check
from prix_energie.modele.decomposition import cout_100km, deflate, decompose, decompose_ht, elec_prolonge
from prix_energie.donnees.sources.cre_fred import load_cre_trv, load_fred_brent
from prix_energie.donnees.sources.dgec import load_dgec_page, load_npg_quotations
from prix_energie.donnees.sources.dgec_base import load_dgec_base
from prix_energie.donnees.sources.eurostat import load_eurostat
from prix_energie.donnees.sources.insee import load_brent_insee, load_ipc
from prix_energie.donnees.sources.stations import load_prix_stations
from prix_energie.donnees.sources.wob import load_wob




def _prolonger_brent_eur(brent, journal) -> None:
    """Complète les euros par baril sur les mois que seule la DGEC couvre.

    L'INSEE publie le Brent en dollars et en euros, mais avec un mois de retard sur la
    DGEC, qui ne donne que les dollars. Le dernier mois se retrouve donc sans euros,
    et toute la part « pétrole brut » du litre disparaît avec lui. Le taux de change
    du dernier mois commun est reconduit : sur un mois, il bouge de moins d'un pour
    cent, là où le baril vient de prendre dix dollars.
    """
    if brent is None or "brent_eur_bbl" not in brent.columns:
        return
    if "brent_usd_bbl_dgec" not in brent.columns:
        return
    import pandas as _pd
    usd = _pd.to_numeric(brent["brent_usd_bbl"], errors="coerce")
    eur = _pd.to_numeric(brent["brent_eur_bbl"], errors="coerce")
    dgec = _pd.to_numeric(brent["brent_usd_bbl_dgec"], errors="coerce")
    connus = usd.notna() & eur.notna() & (eur != 0)
    if not connus.any():
        return
    taux = float((usd[connus] / eur[connus]).iloc[-1])
    a_combler = eur.isna() & dgec.notna()
    if not a_combler.any():
        return
    brent.loc[a_combler, "brent_eur_bbl"] = dgec[a_combler] / taux
    # Marque portée jusqu'aux figures : une valeur reconstituée s'y trace en tirets,
    # pour qu'on ne la lise pas comme un relevé.
    brent["brent_eur_reconstitue"] = False
    brent.loc[a_combler, "brent_eur_reconstitue"] = True
    mois = ", ".join(f"{d:%Y-%m}" for d in _pd.to_datetime(brent.loc[a_combler, "date"]))
    journal.note("METHODE", "Brent",
                 f"Euros par baril reconstitués pour {mois} à partir du cours DGEC en "
                 f"dollars et du taux de change du dernier mois commun ({taux:.4f} $/€). "
                 "L'INSEE publie les euros avec un mois de retard sur la DGEC.")


def _extraire_produit(m: pd.DataFrame, prefixe: str) -> pd.DataFrame:
    """Isole un produit de la table mensuelle multi-produits, min et max compris.

    Les extrêmes du mois voyagent avec la moyenne : ils disent de combien le prix a
    bougé à l'intérieur du mois, ce qu'une moyenne seule ne peut pas montrer.
    """
    ren = {f"{prefixe}_ttc": "ttc", f"{prefixe}_ht": "ht"}
    for suffixe in ("_min", "_max"):
        ren[f"{prefixe}_ttc{suffixe}"] = f"ttc{suffixe}"
        ren[f"{prefixe}_ht{suffixe}"] = f"ht{suffixe}"
    cols = ["mois", "n_obs", "source"] + [c for c in ren if c in m.columns]
    return m[cols].rename(columns=ren).copy()


def _dgec_series(prix2020: pd.DataFrame, product_pat: str, level: str) -> pd.Series | None:
    """Cherche dans le fichier DGEC 2020→ la colonne 'onglet|entête' pour un produit et un niveau (htt/ttc)."""
    for c in prix2020.columns:
        if c == "date":
            continue
        # La DGEC écrit « H.T.T. » et « T.T.C. » avec des points : on retire ponctuation
        # et espaces avant de comparer, sinon aucun motif ne peut correspondre.
        n = re.sub(r"[.\s]", "", str(c).lower())
        if re.search(product_pat, n) and re.search(level, n):
            return prix2020.set_index("date")[c]
    return None


def _to_ceur_l(s: pd.Series | None, journal: Journal) -> pd.Series | None:
    """Ramène une série DGEC en c€/l d'après l'unité annoncée dans son en-tête.

    Le fichier « Prix HTT et TTC » est libellé en euros par litre (0,6277), alors que
    tout le reste de la chaîne travaille en centimes (62,77). Sans conversion, la série
    E10 entrerait 100 fois trop petite ; c'est le contrat sur les bornes de `ttc` qui
    l'a révélé. Une unité non reconnue n'est pas convertie au hasard : on la signale et
    on laisse le contrat trancher.
    """
    if s is None:
        return None
    n = str(s.name).lower()
    if "euro par litre" in n or "€/l" in n or "eur/l" in n:
        return s * 100.0
    if "c€/l" in n or "centime" in n:
        return s
    journal.note("ERREUR", "Prix DGEC 2020",
                 f"Unité non reconnue dans l'en-tête « {s.name} » : série laissée telle quelle.")
    return s


def build(choices: Choices, offline: bool = False) -> Bundle:
    j = Journal()
    b = Bundle(choices=choices, journal=j)
    start = pd.Timestamp(choices.start + "-01")

    # ------------------------------------------------------------------ carburants (WOB)
    wob = load_wob(j, offline)
    b.wob_weekly = wob
    m = monthly_mean(wob, "date", ["gazole_ht", "gazole_ttc", "sp95_ht", "sp95_ttc"])
    m["source"] = "WOB"
    if choices.dgec_base:
        base = load_dgec_base(choices.dgec_base, j)
        if base is not None:
            b.dgec_base = base
            cols = [c for c in ("gazole_ht", "gazole_ttc", "sp95_ht", "sp95_ttc") if c in base.columns]
            mb = monthly_mean(base, "date", cols)
            mb["source"] = "DGEC base"
            # la base DGEC couvre 1985 → aujourd'hui : elle devient la source primaire, le WOB sert de contrôle
            ov = m.merge(mb, on="mois", suffixes=("_wob", "_dgec"))
            for c in cols:
                if len(ov):
                    d = ov[f"{c}_wob"] - ov[f"{c}_dgec"]
                    j.note("METHODE", "Carburants", f"Contrôle WOB − base DGEC pour {c} sur {len(ov)} mois communs : "
                           f"écart moyen {d.mean():+.2f} c€/l, écart max {d.abs().max():.2f} c€/l.")
            missing = [c for c in ("gazole_ht", "gazole_ttc", "sp95_ht", "sp95_ttc") if c not in cols]
            if missing:
                j.note("INDISPONIBLE", "Base DGEC", f"Colonnes absentes de l'export : {missing}, complétées par le WOB.")
                for c in missing:
                    mb = mb.merge(m[["mois", c]], on="mois", how="left")
            # prolongation par le WOB si l'export s'arrête avant la dernière semaine WOB
            tail = m[m.mois > mb.mois.max()]
            if len(tail):
                j.note("RUPTURE", "Carburants", f"Export DGEC arrêté en {mb.mois.max():%Y-%m} ; {len(tail)} mois "
                       "suivants pris dans le WOB (voir colonne Source prix).")
            m = pd.concat([mb, tail], ignore_index=True)
            j.note("DEFINITION", "Carburants", "Source primaire = base DGEC (prix du vendredi, 1985→) ; le Weekly Oil "
                   "Bulletin (prix du lundi) est conservé en feuille Brut_WOB_hebdo pour contrôle.")
    else:
        j.note("INDISPONIBLE", "Carburants avant 2005", "Le Weekly Oil Bulletin commence en 2005. Les prix 1985→2004 "
               "(HT et TTC) sont dans la base en ligne de la DGEC, sans fichier téléchargeable : exporter la base "
               "(tuto sur la page Prix des produits pétroliers) et la passer avec --dgec-base ; elle devient alors "
               "la source primaire sur toute la période.")
    m = m[m.mois >= start]

    # ------------------------------------------------------------------ DGEC
    dg = load_dgec_page(j, offline)
    b.td_annuel = dg["td_annuel"]
    b.marge = dg["marge"]
    # Brent : INSEE (longue, $/b et €/b) en priorité ; DGEC en contrôle ; FRED en dernier secours
    b.brent = load_brent_insee(j, offline)
    b.brent_source = "INSEE (Brent spot)"
    if dg["brent"] is not None and len(dg["brent"]) > 24:
        if b.brent is None:
            b.brent, b.brent_source = dg["brent"], "DGEC / Reuters"
        else:
            b.brent = b.brent.merge(dg["brent"].rename(columns={"brent_usd_bbl": "brent_usd_bbl_dgec"}), on="date", how="outer").sort_values("date")
            _prolonger_brent_eur(b.brent, j)
    if b.brent is None:
        b.brent = load_fred_brent(j, offline)
        b.brent_source = "EIA via FRED (secours)"
    b.ipc = load_ipc(j, offline, choices.ipc_csv, choices.ipc_idbank_2025, choices.ipc_csv_2025)
    b.stations = load_prix_stations(j, offline)
    b.cotations = load_npg_quotations(j, choices.npg_weeks, offline)
    # Les notes hebdomadaires publient aussi la marge de raffinage du mois, que la série
    # mensuelle DGEC ne couvre pas encore : sans elle, le dernier mois n'a pas de détail
    # brut / raffinage et la courbe s'interrompt.
    # Même chose pour le cours du Brent : la note le donne en moyenne hebdomadaire,
    # ce qui vaut mieux qu'un trou sur le dernier mois. La valeur est marquée
    # reconstituée, donc tracée en pointillé.
    if b.brent is not None and b.cotations is not None and "brent" in getattr(b.cotations, "attrs", {}):
        bt = b.cotations.attrs["brent"]
        manquants = bt[~bt["date"].isin(pd.to_datetime(b.brent["date"]))]
        if len(manquants):
            ajout = manquants.copy()
            ajout["brent_eur_reconstitue"] = True
            b.brent = pd.concat([b.brent, ajout], ignore_index=True).sort_values("date")
            b.brent["brent_eur_reconstitue"] = b.brent["brent_eur_reconstitue"].fillna(False)

    if b.cotations is not None and "marge" in getattr(b.cotations, "attrs", {}):
        mg = b.cotations.attrs["marge"]
        if b.marge is None:
            b.marge = mg[["date", "marge_eur_t"]].copy()
        else:
            manquants = mg[~mg["date"].isin(pd.to_datetime(b.marge["date"]))]
            if len(manquants):
                b.marge = pd.concat([b.marge, manquants[["date", "marge_eur_t"]]],
                                    ignore_index=True).sort_values("date")
    if b.cotations is None:
        j.note("INDISPONIBLE", "Cotations Rotterdam",
               "Aucune série mensuelle longue des cotations Rotterdam n'est publiée en open data par la DGEC/SDES "
               "(données Reuters). Seules options : (a) lecture des notes hebdomadaires PDF (option --npg-weeks), "
               "(b) tableau DGEC des coûts annuels de transport-distribution 2015→ (feuille TD_annuel), dont on "
               "déduit une cotation annuelle = HTT − T-D. Faute de cotation, la composante 'HT non décomposé' "
               "regroupe cotation + transport-distribution.")

    # ------------------------------------------------------------------ gazole
    gz = _extraire_produit(m, "gazole")
    # Le gazole restait sur le Weekly Oil Bulletin (prix du lundi) quand le sans-plomb
    # était déjà passé au fichier DGEC (prix du vendredi) : les deux carburants ne
    # finissaient pas à la même date, et le gazole ratait la dernière semaine publiée.
    # Même source et mêmes dates pour les deux, à partir de la date de chaînage.
    if dg["prix2020"] is not None:
        gz_ht = _to_ceur_l(_dgec_series(dg["prix2020"], r"gazole", r"htt|hors"), j)
        gz_ttc = _to_ceur_l(_dgec_series(dg["prix2020"], r"gazole", r"ttc"), j)
        if gz_ht is not None and gz_ttc is not None:
            wk = pd.DataFrame({"date": gz_ht.index, "ht": gz_ht.values,
                               "ttc": gz_ttc.reindex(gz_ht.index).values}).dropna()
            gz_dgec = monthly_mean(wk, "date", ["ht", "ttc"])
            gz_dgec["source"] = "DGEC"
            bascule = pd.Timestamp(choices.sp_e10_chain + "-01")
            ov = gz.merge(gz_dgec, on="mois", suffixes=("_wob", "_dgec"))
            if len(ov):
                ec = ov["ttc_dgec"] - ov["ttc_wob"]
                j.note("METHODE", "Gazole",
                       f"Prix DGEC (vendredi) substitués au Weekly Oil Bulletin (lundi) "
                       f"à partir de {choices.sp_e10_chain}, pour aligner le gazole sur le "
                       f"sans-plomb. Contrôle sur {len(ov)} mois communs : écart moyen "
                       f"{ec.mean():+.2f} c€/l, écart maximal {ec.abs().max():.2f} c€/l.")
            gz = pd.concat([gz[gz.mois < bascule], gz_dgec[gz_dgec.mois >= bascule]],
                           ignore_index=True)
        else:
            j.note("INDISPONIBLE", "Gazole", "Colonnes gazole HTT/TTC non trouvées dans le "
                   "fichier DGEC 2020→ : la série reste celle du Weekly Oil Bulletin.")
    gz = _attach_cotation(gz, b.cotations, "gazole")
    b.gazole = _finalize_fuel(gz, j, "Gazole")

    # ------------------------------------------------------------------ sans-plomb
    e5 = _extraire_produit(m, "sp95")
    e5["produit"] = "SP95-E5"
    b.sp_e5 = _finalize_fuel(_attach_cotation(e5, b.cotations, "sp95"), j, "SP95-E5")

    chain = pd.Timestamp(choices.sp_e10_chain + "-01")
    e10 = None
    if dg["prix2020"] is not None:
        s_ht = _to_ceur_l(_dgec_series(dg["prix2020"], r"e10", r"htt|hors"), j)
        s_ttc = _to_ceur_l(_dgec_series(dg["prix2020"], r"e10", r"ttc"), j)
        if s_ht is not None and s_ttc is not None:
            wk = pd.DataFrame({"date": s_ht.index, "ht": s_ht.values, "ttc": s_ttc.reindex(s_ht.index).values}).dropna()
            e10 = monthly_mean(wk, "date", ["ht", "ttc"])
            e10["source"] = "DGEC"
            e10["produit"] = "SP95-E10"
            e10 = _finalize_fuel(_attach_cotation(e10, b.cotations, "sp95"), j, "SP95-E10")
            b.sp_e10_dgec = e10
            # saut de niveau E10 vs E5 (DGEC) au mois de chaînage, pour information
            s5_ttc = _to_ceur_l(_dgec_series(dg["prix2020"], r"e5|sp95(?!.*e10)", r"ttc"), j)
            if s5_ttc is not None:
                d5 = monthly_mean(pd.DataFrame({"date": s5_ttc.index, "ttc": s5_ttc.values}).dropna(), "date", ["ttc"])
                both = e10.merge(d5, on="mois", suffixes=("", "_e5"))
                row = both[both.mois == chain]
                if len(row):
                    gap = float(row.ttc.iloc[0] - row.ttc_e5.iloc[0])
                    j.note("RUPTURE", "Sans-plomb", f"Chaînage SP95-E5 → SP95-E10 en {choices.sp_e10_chain} : "
                           f"écart TTC E10 − E5 ce mois-là (source DGEC) = {gap:+.2f} c€/l.")
        else:
            j.note("INDISPONIBLE", "SP95-E10", f"Colonnes E10 HTT/TTC non trouvées dans le fichier DGEC 2020→ "
                   f"(colonnes : {[c for c in dg['prix2020'].columns][:12]}…).")
    if e10 is None:
        j.note("INDISPONIBLE", "SP95-E10", "Série E10 non chargée : la série sans-plomb reste SP95-E5 (WOB) sur toute la période.")
        b.sansplomb = b.sp_e5.copy()
    else:
        before = b.sp_e5[b.sp_e5.mois < chain]
        after = e10[e10.mois >= chain]
        b.sansplomb = pd.concat([before, after], ignore_index=True)
        j.note("DEFINITION", "Sans-plomb", "Le SP95-E10 est commercialisé depuis avril 2009 ; la DGEC ne publie en "
               "xlsx l'E10 que depuis 2020 (sa base en ligne remonte à 2009). Avant la date de chaînage, la série "
               "est le SP95-E5 (Weekly Oil Bulletin) ; l'accise E10 était inférieure à celle de l'E5 jusqu'en 2021, "
               "les composantes ne sont donc pas strictement comparables de part et d'autre du chaînage.")

    # ------------------------------------------------------------------ électricité
    es = load_eurostat(j, offline)
    b.elec_semestriel = es["semestriel"]
    b.elec_composantes = es["composantes"]
    b.elec_composantes_labels = es.get("composantes_labels", {})
    b.elec_ancienne = es["ancienne"]
    b.elec_bandes = es.get("bandes")
    b.elec_bandes_labels = es.get("bandes_labels", {})
    b.trv = load_cre_trv(j, choices, offline)

    # ------------------------------------------------------------------ ouverture du hors-taxes
    # Le « hors taxes » agrège brut + raffinage + distribution : on l'ouvre avec les
    # sources DGEC/INSEE, en exposant l'écart de bouclage plutôt qu'en le répartissant.
    for attr, name, densite, td_col in (
            ("gazole", "Gazole", choices.density_gasoil, "td_gazole"),
            ("sansplomb", "Sans-plomb", choices.density_eurosuper, "td_sp95_e5"),
            ("sp_e5", "SP95-E5", choices.density_eurosuper, "td_sp95_e5"),
            ("sp_e10_dgec", "SP95-E10", choices.density_eurosuper, "td_sp95_e10")):
        serie = getattr(b, attr)
        if serie is not None:
            setattr(b, attr, decompose_ht(serie, b.brent, b.marge, b.td_annuel,
                                          densite, td_col, j, name))

    # ------------------------------------------------------------------ euros constants
    # Fait ici, une fois l'IPC connu, et sur toutes les séries carburants à la fois.
    deflatables = ["ttc", "ht", "cotation", "transport_distribution", "ht_non_decompose",
                   "accise", "tva",
                   # composantes du hors-taxes, pour pouvoir les lire aussi à euro constant
                   "brent_ceur_l", "raffinage_ceur_l", "transport_annuel_ceur_l"]
    for attr, name in (("gazole", "Gazole"), ("sansplomb", "Sans-plomb"),
                       ("sp_e5", "SP95-E5"), ("sp_e10_dgec", "SP95-E10")):
        serie = getattr(b, attr)
        if serie is not None:
            setattr(b, attr, deflate(serie, b.ipc, deflatables, j, name, ref=choices.ipc_ref))

    # L'électricité aussi : ses séries n'étant ni mensuelles ni de même pas, chacune
    # est déflatée sur l'IPC moyen de sa propre période.
    elec = (("elec_semestriel", "Électricité semestriel", ["ttc", "hors_taxes", "hors_tva"], "S"),
            ("elec_composantes", "Électricité composantes",
             ["NRG_SUP", "NETC", "TAX_ENV", "TAX_CAP", "TAX_NUC", "TAX_RNW", "OTH", "VAT"], "Y"),
            ("elec_bandes", "Électricité bandes",
             ["KWH_LT1000", "KWH1000-2499", "KWH2500-4999", "KWH5000-14999",
              "KWH_GE15000", "TOT_KWH"], "S"))
    for attr, name, colonnes, freq in elec:
        serie = getattr(b, attr)
        if serie is not None:
            presentes = [c for c in colonnes if c in serie.columns]
            setattr(b, attr, deflate(serie, b.ipc, presentes, j, name,
                                     ref=choices.ipc_ref, date_col="periode", freq=freq))

    # Le Brent aussi se lit en euros constants : c'est un prix comme un autre.
    if b.brent is not None and "brent_eur_bbl" in b.brent.columns:
        b.brent = deflate(b.brent, b.ipc, ["brent_usd_bbl", "brent_eur_bbl"], j,
                          "Brent", ref=choices.ipc_ref, date_col="date", freq="M")

    # Électricité mensuelle, prolongée par le tarif réglementé là où Eurostat manque.
    if b.sansplomb is not None:
        b.elec_mensuel = elec_prolonge(b.elec_semestriel, b.trv, b.sansplomb["mois"], j)
        if b.elec_mensuel is not None:
            b.elec_mensuel = deflate(b.elec_mensuel, b.ipc,
                                     ["ttc", "hors_taxes", "tva", "taxes_hors_tva"], j,
                                     "Électricité mensuelle", ref=choices.ipc_ref,
                                     date_col="mois", freq="M")

    # Coût de 100 km : la seule mise en regard légitime des trois énergies.
    b.cout_km = cout_100km(b.sansplomb, b.gazole, b.elec_mensuel, b.trv, j,
                           choices.conso_essence_l_100km, choices.conso_diesel_l_100km,
                           choices.conso_ve_kwh_100km)

    if b.cout_km is not None:
        b.cout_km = deflate(b.cout_km, b.ipc, ["essence", "diesel", "electrique"], j,
                            "Coût au km", ref=choices.ipc_ref, date_col="mois", freq="M")

    for n in choices.notes:
        j.note("METHODE", "Utilisateur", n)
    return b


def _attach_cotation(df: pd.DataFrame, cot: pd.DataFrame | None, produit: str) -> pd.DataFrame:
    df = df.copy()
    if cot is None:
        df["cotation"] = pd.NA
        df["cotation_provisoire"] = pd.NA
        return df
    c = cot[cot.produit == produit][["mois", "cotation_ceur_l", "provisoire"]]
    df = df.merge(c, on="mois", how="left").rename(columns={"cotation_ceur_l": "cotation", "provisoire": "cotation_provisoire"})
    return df


def _finalize_fuel(df: pd.DataFrame, journal: Journal, name: str) -> pd.DataFrame:
    """Table mensuelle d'un carburant, validée puis décomposée en composantes de prix."""
    df = df.copy()
    df["mois"] = pd.to_datetime(df["mois"])
    df["annee"] = df.mois.dt.year
    df["taux_tva"] = df.mois.map(vat_rate)
    cols = ["mois", "annee", "n_obs", "source", "ttc", "ht", "taux_tva", "cotation", "cotation_provisoire"]
    if "produit" in df.columns:
        cols.insert(3, "produit")
    # Les extrêmes du mois ne sont pas produits par toutes les sources : on les garde
    # quand ils existent, sans les rendre obligatoires.
    cols += [c for c in ("ttc_min", "ttc_max", "ht_min", "ht_max") if c in df.columns]
    out = df[cols].sort_values("mois").reset_index(drop=True)
    out = check(out, Contract(name=name, key="mois", required=("ttc", "ht", "taux_tva"),
                              bounds={"ttc": (20.0, 400.0), "ht": (2.0, 300.0)},
                              freq="M", min_rows=12), journal)
    return decompose(out, journal, name)
