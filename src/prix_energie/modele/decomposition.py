"""Décomposition du prix et passage en euros constants.

Ce module reprend ce qui vivait dans les formules du classeur Excel
(`=F2*H2/(1+H2)`, `=F2-G2-K2`, `=IF(I2="","",G2-I2)`…). Tant que ce calcul était
une chaîne de caractères dans une cellule, il ne s'exécutait qu'à l'ouverture du
fichier : ni testable, ni relisible par le script, et invisible à l'inspection.

Conventions d'unités : carburants en c€/l, taux de TVA en fraction (0,20).
Le prix « HT » du Weekly Oil Bulletin est hors accise *et* hors TVA.

    ttc = ht + accise + tva
    tva = ttc x t / (1 + t)
    accise = ttc - ht - tva                     (déduite : non publiée dans l'historique)
    ht = cotation + transport_distribution      (si la cotation Rotterdam est connue)
"""
from __future__ import annotations

import pandas as pd

from prix_energie.common import vat_rate
from prix_energie.journal import Journal
from prix_energie.config import BARREL_LITRES

# L'accise est un résidu : ces bornes attrapent une inversion HT/TTC ou une erreur
# d'unité, pas une variation de barème. TICPE carburants observée : ~40 à ~70 c€/l.
ACCISE_BOUNDS = (20.0, 90.0)
# Au-delà, un écart d'un mois sur l'autre signale un changement de barème (ou un bug).
ACCISE_JUMP = 5.0

# Remise carburant de l'État, 2022 : bornes de validité et montant hors taxes en c€/l.
# Les sources la comptabilisent en réduction du prix hors taxes, pas de l'accise. Le
# prix payé est juste, mais le hors-taxes s'en trouve creusé pendant neuf mois : au
# point de tomber sous le coût du seul pétrole brut en septembre et octobre, ce qui
# ne peut pas arriver. On rebascule la remise vers l'accise, dont elle relève : le
# prix payé ne bouge pas, la structure redevient interprétable.
REMISE_2022 = (("2022-04-01", "2022-08-31", 15.0),
               ("2022-09-01", "2022-11-15", 25.0),
               ("2022-11-16", "2022-12-31", 8.33))


def _remise_carburant(mois: pd.Series) -> pd.Series:
    """Remise du mois en c€/l, au prorata des jours couverts.

    Deux des trois périodes commencent ou finissent en cours de mois : novembre 2022
    est à cheval sur 25 et 8,33 c€/l. Un mois entier au taux du 1er du mois décalerait
    la correction d'une quinzaine.
    """
    m = pd.to_datetime(mois, errors="coerce")
    out = pd.Series(0.0, index=m.index)
    for debut, fin, montant in REMISE_2022:
        d0, d1 = pd.Timestamp(debut), pd.Timestamp(fin)
        for i, ts in m.items():
            if pd.isna(ts):
                continue
            m0 = ts.replace(day=1)
            m1 = m0 + pd.offsets.MonthEnd(0)
            couverts = (min(m1, d1) - max(m0, d0)).days + 1
            if couverts > 0:
                out.at[i] += montant * couverts / ((m1 - m0).days + 1)
    return out


def decompose(df: pd.DataFrame, journal: Journal, name: str) -> pd.DataFrame:
    """Ajoute tva, accise, transport_distribution, ht_non_decompose.

    `transport_distribution` n'existe que si la cotation Rotterdam est connue ;
    sinon `ht_non_decompose` porte tout le hors-taxe, et les deux colonnes sont
    exclusives l'une de l'autre : c'est la convention du classeur d'origine.
    """
    out = df.copy()
    ttc = pd.to_numeric(out["ttc"], errors="coerce")
    ht = pd.to_numeric(out["ht"], errors="coerce")
    t = pd.to_numeric(out["taux_tva"], errors="coerce")

    # La remise est reversée au hors-taxes avant tout le reste : l'accise étant un
    # résidu, elle absorbe alors la correction d'elle-même, et le prix payé, qui lui
    # est mesuré, ne bouge pas d'un centime.
    remise = _remise_carburant(out["mois"]) if "mois" in out.columns else None
    if remise is not None and float(remise.max()) > 0:
        ht = ht + remise
        out["ht"] = ht
        out["remise_2022"] = remise
        n = int((remise > 0).sum())
        journal.note("METHODE", name,
                     f"Remise carburant 2022 reversée au prix hors taxes sur {n} mois "
                     f"(15 c€/l d'avril à août, 25 jusqu'au 15 novembre, 8,33 ensuite). "
                     "Les sources la déduisent du hors-taxes ; elle relève de l'accise, "
                     "sans quoi le hors-taxes passe sous le coût du brut en septembre.")

    out["tva"] = ttc * t / (1.0 + t)
    out["accise"] = ttc - ht - out["tva"]

    cot = pd.to_numeric(out.get("cotation"), errors="coerce") if "cotation" in out else pd.Series(pd.NA, index=out.index)
    has_cot = cot.notna()
    out["transport_distribution"] = (ht - cot).where(has_cot)
    out["ht_non_decompose"] = ht.where(~has_cot)

    _audit_accise(out, journal, name)
    return out


def _audit_accise(df: pd.DataFrame, journal: Journal, name: str) -> None:
    """Contrôle de vraisemblance sur l'accise déduite.

    Le classeur d'origine portait une colonne « Contrôle (somme − TTC) » qui ne
    pouvait rien détecter : l'accise y étant définie comme le résidu `ttc - ht - tva`,
    la somme des composantes vaut `ttc` par construction, quels que soient les prix.
    On contrôle donc l'accise elle-même, ce qui teste réellement le couple HT/TTC.
    """
    a = pd.to_numeric(df["accise"], errors="coerce").dropna()
    if a.empty:
        journal.note("INDISPONIBLE", name, "Accise non calculable : HT ou TTC manquant.")
        return

    lo, hi = ACCISE_BOUNDS
    bad = ~a.between(lo, hi)
    if bad.any():
        journal.note("ERREUR", name,
                     f"{int(bad.sum())} mois avec une accise déduite hors de [{lo}, {hi}] c€/l "
                     f"(min {a.min():.1f}, max {a.max():.1f}) : vérifier l'appariement HT/TTC et l'unité.")

    jumps = a.diff().abs()
    n = int((jumps > ACCISE_JUMP).sum())
    if n:
        # Attendu : hausses de TICPE, et la remise carburant de 2022 (-18 puis -30 c€/l).
        journal.note("METHODE", name,
                     f"{n} variation(s) mensuelle(s) d'accise supérieure(s) à {ACCISE_JUMP:.0f} c€/l : "
                     "changement de barème ou remise à la pompe (à confirmer au cas par cas).")


def decompose_ht(df: pd.DataFrame, brent: pd.DataFrame | None, marge: pd.DataFrame | None,
                 td_annuel: pd.DataFrame | None, densite: float, td_col: str,
                 journal: Journal, name: str) -> pd.DataFrame:
    """Décompose le prix hors taxes en matière première, raffinage et distribution.

    Le « hors taxes » du Weekly Oil Bulletin est un agrégat : il contient le pétrole
    brut, le coût du raffinage et l'acheminement jusqu'à la pompe. On l'ouvre avec
    trois sources indépendantes, d'où un écart de bouclage qu'on expose au lieu de
    le répartir :

        brent           $/b INSEE convertis en €/b, puis /159 l et x100   -> c€/l
        raffinage       marge brute DGEC en €/t, x densité, /10            -> c€/l
        transport       coûts DGEC, publiés en c€/l mais **annuels**
        écart           ht − (brent + raffinage + transport)

    Trois réserves, à garder en tête avant d'interpréter :
      * la marge DGEC est un indicateur *théorique* sur un panier de produits, pas la
        marge réalisée sur ce carburant précis ;
      * le coût de transport-distribution est une moyenne annuelle appliquée à chaque
        mois : il ne peut pas suivre les à-coups infra-annuels ;
      * les deux ne commencent qu'en 2015.
    """
    out = df.copy()
    for col in ("brent_ceur_l", "raffinage_ceur_l", "transport_annuel_ceur_l", "ecart_bouclage"):
        out[col] = pd.NA

    if brent is not None and "brent_eur_bbl" in brent.columns:
        b = brent.set_index(pd.to_datetime(brent["date"]))["brent_eur_bbl"].astype(float)
        out["brent_ceur_l"] = pd.to_datetime(out["mois"]).map(b) / BARREL_LITRES * 100.0
        if "brent_eur_reconstitue" in brent.columns:
            r = brent.set_index(pd.to_datetime(brent["date"]))["brent_eur_reconstitue"]
            out["brent_reconstitue"] = pd.to_datetime(out["mois"]).map(r).fillna(False)
    else:
        journal.note("INDISPONIBLE", name, "Brent en euros absent : coût de la matière première non isolé.")

    if marge is not None and "marge_eur_t" in marge.columns:
        m = marge.set_index(pd.to_datetime(marge["date"]))["marge_eur_t"].astype(float)
        out["raffinage_ceur_l"] = pd.to_datetime(out["mois"]).map(m) * densite / 10.0
    else:
        journal.note("INDISPONIBLE", name, "Marge de raffinage absente : coût du raffinage non isolé.")

    if td_annuel is not None and td_col in td_annuel.columns:
        t = td_annuel.set_index("annee")[td_col].astype(float)
        out["transport_annuel_ceur_l"] = out["mois"].dt.year.map(t)
    else:
        journal.note("INDISPONIBLE", name, "Coûts de transport-distribution absents.")

    parts = out[["brent_ceur_l", "raffinage_ceur_l", "transport_annuel_ceur_l"]]
    complet = parts.notna().all(axis=1)
    if complet.any():
        out.loc[complet, "ecart_bouclage"] = (
            pd.to_numeric(out.loc[complet, "ht"]) - parts[complet].sum(axis=1))
        e = pd.to_numeric(out["ecart_bouclage"], errors="coerce").dropna()
        negatifs = int((e < 0).sum())
        journal.note("METHODE", name,
                     f"Décomposition du hors-taxes sur {int(complet.sum())} mois : écart de bouclage "
                     f"moyen {e.mean():+.2f} c€/l (min {e.min():+.2f}, max {e.max():+.2f}).")
        if negatifs:
            journal.note("PROVISOIRE", name,
                         f"{negatifs} mois où brut + raffinage + transport dépassent le prix hors taxes "
                         "(écart négatif) : marge de raffinage théorique et transport annuel ne collent "
                         "pas au mois. Concentrés sur les épisodes de tension du raffinage.")
    return out


# Nombre de mois couverts par une observation, selon sa fréquence. Sert à moyenner
# l'IPC sur la bonne durée : déflater un prix annuel par l'IPC de janvier reviendrait
# à ignorer onze mois d'inflation.
MOIS_PAR_PERIODE = {"M": 1, "S": 6, "Y": 12}


def _ipc_periode(serie: pd.Series, debut: pd.Timestamp, mois: int) -> float:
    """IPC moyen sur les `mois` mois qui commencent à `debut`."""
    fin = debut + pd.DateOffset(months=mois - 1)
    fenetre = serie.loc[(serie.index >= debut) & (serie.index <= fin)]
    return float(fenetre.mean()) if len(fenetre) else float("nan")


def elec_prolonge(semestriel: pd.DataFrame | None, trv: pd.DataFrame | None,
                  mois: pd.Series, journal: Journal) -> pd.DataFrame | None:
    """Prix TTC de l'électricité, mensuel, prolongé par le tarif réglementé.

    Eurostat publie le prix moyen tous contrats avec près d'un an de délai ; la CRE
    publie le barème dès son entrée en vigueur. Sur les 27 semestres où les deux
    existent, ils s'écartent de 0,6 % en moyenne : assez peu pour que le barème
    prolonge la série sans la déformer, et bien assez pour que la jonction soit
    signalée plutôt que fondue dans la masse.
    """
    if semestriel is None or "ttc" not in semestriel.columns:
        return None
    out = pd.DataFrame({"mois": pd.to_datetime(mois).sort_values().unique()})
    idx_sem = pd.to_datetime(semestriel["periode"])
    fin_eurostat = idx_sem.max()
    paires = (("ttc", "prix_moyen_ttc_ceur_kwh"), ("hors_taxes", "prix_moyen_ht_ceur_kwh"),
              ("hors_tva", None))
    for col, _ in paires:
        if col in semestriel.columns:
            s = semestriel.set_index(idx_sem)[col].astype(float)
            # Un prix semestriel vaut pour tout son semestre : report en avant.
            out[col] = out["mois"].map(s).ffill()
            out.loc[out["mois"] > fin_eurostat + pd.DateOffset(months=5), col] = pd.NA
    out["source"] = "Eurostat"

    if trv is not None and "prix_moyen_ttc_ceur_kwh" in trv.columns:
        t = trv.sort_values("debut")
        bornes = pd.to_datetime(t["debut"])
        pos = bornes.searchsorted(out["mois"], side="right") - 1
        manque = out["ttc"].isna()
        for col, col_trv in paires:
            if col not in out.columns or col_trv is None or col_trv not in t.columns:
                continue
            vals = pd.to_numeric(t[col_trv], errors="coerce").values
            au_bareme = pd.Series([vals[i] if i >= 0 else float("nan") for i in pos],
                                  index=out.index)
            a_combler = out[col].isna() & au_bareme.notna()
            out.loc[a_combler, col] = au_bareme[a_combler]
        manque = manque & out["ttc"].notna()
        out.loc[manque, "source"] = "Tarif réglementé"
        if manque.any():
            journal.note("RUPTURE", "Électricité",
                         f"{int(manque.sum())} mois ({out.loc[manque, 'mois'].min():%Y-%m} → "
                         f"{out.loc[manque, 'mois'].max():%Y-%m}) pris au tarif réglementé, "
                         "le prix moyen Eurostat n'étant pas encore publié. Les deux mesures "
                         "diffèrent de 0,6 % en moyenne sur leur période commune.")

    # Décomposition en trois niveaux. La TVA est *mesurée* (ttc − hors_tva), pas
    # recalculée à 20 % : sur une facture d'électricité l'abonnement est taxé à 5,5 %
    # et la seule consommation à 20 %, si bien qu'un taux unique surestime la TVA et
    # rend négative la couche fiscale intermédiaire : six mois de 2023 le montraient,
    # l'accise étant alors ramenée à son minimum par le bouclier tarifaire.
    ttc = pd.to_numeric(out["ttc"], errors="coerce")
    if "hors_tva" in out.columns:
        out["tva"] = ttc - pd.to_numeric(out["hors_tva"], errors="coerce")
        # Mois repris au barème : Eurostat ne les couvre pas, on prolonge le taux
        # effectif du dernier mois mesuré plutôt que d'appliquer un taux théorique.
        part = (out["tva"] / ttc).ffill()
        out["tva"] = out["tva"].fillna(ttc * part)
    else:
        taux = out["mois"].map(vat_rate)
        out["tva"] = ttc * taux / (1.0 + taux)
    if "hors_taxes" in out.columns:
        out["taxes_hors_tva"] = (ttc - pd.to_numeric(out["hors_taxes"], errors="coerce")
                                 - out["tva"])
        negatifs = int((out["taxes_hors_tva"] < -0.01).sum())
        if negatifs:
            journal.note("ERREUR", "Électricité",
                         f"{negatifs} mois où la couche fiscale hors TVA ressort négative : "
                         "la TVA déduite dépasse l'écart entre prix TTC et prix hors taxes.")
    return out.dropna(subset=["ttc"]).reset_index(drop=True)


def cout_100km(sansplomb: pd.DataFrame | None, gazole: pd.DataFrame | None,
               elec_mensuel: pd.DataFrame | None, trv: pd.DataFrame | None,
               journal: Journal, essence_l: float, diesel_l: float,
               ve_kwh: float) -> pd.DataFrame | None:
    """Coût de 100 km pour trois motorisations, en euros courants.

    C'est la seule mise en regard légitime des trois énergies : un litre et un
    kilowattheure ne se comparent pas, le coût d'un trajet identique si. Les
    consommations sont des conventions déclarées dans `Choices`, pas des mesures -
    tout le résultat en dépend linéairement, et les changer change les niveaux sans
    changer les formes.

    Le prix de l'électricité retenu est le tarif réglementé, pas le prix moyen de
    marché : c'est celui que paie un particulier qui recharge chez lui, et il est
    connu jusqu'au barème en cours, là où la statistique de marché a un an de retard.
    """
    if sansplomb is None or gazole is None:
        return None
    base = pd.DataFrame({"mois": pd.to_datetime(sansplomb["mois"])})
    base["essence"] = pd.to_numeric(sansplomb["ttc"], errors="coerce") * essence_l / 100.0
    g = gazole.set_index(pd.to_datetime(gazole["mois"]))["ttc"]
    base["diesel"] = base["mois"].map(g).astype(float) * diesel_l / 100.0

    prix_elec, source_elec = None, ""
    if elec_mensuel is not None and "ttc" in elec_mensuel.columns:
        # La même série que partout ailleurs dans le dossier : sinon la courbe
        # électrique de cette figure démarrerait en 2012 (début du tarif réglementé)
        # là où toutes les autres démarrent en 2007.
        e = elec_mensuel.set_index(pd.to_datetime(elec_mensuel["mois"]))["ttc"].astype(float)
        prix_elec = base["mois"].map(e)
        source_elec = "prix moyen Eurostat prolongé par le tarif réglementé"
    elif trv is not None and "prix_moyen_ttc_ceur_kwh" in trv.columns:
        # Barèmes en paliers : chaque mois prend le tarif en vigueur ce mois-là.
        t = trv.sort_values("debut")
        bornes = pd.to_datetime(t["debut"])
        valeurs = pd.to_numeric(t["prix_moyen_ttc_ceur_kwh"], errors="coerce").values
        idx = bornes.searchsorted(base["mois"], side="right") - 1
        prix_elec = pd.Series([valeurs[i] if i >= 0 else float("nan") for i in idx],
                              index=base.index)
        source_elec = "tarif réglementé (CRE)"
    elif elec_mensuel is not None and "ttc" in elec_mensuel.columns:
        # Repli quand le tarif reglemente manque. La branche nommait encore
        # `elec_semestriel`, un parametre disparu de la signature : elle aurait
        # leve une NameError le jour ou le TRV aurait fait defaut.
        col = "periode" if "periode" in elec_mensuel.columns else "mois"
        s = elec_mensuel.set_index(pd.to_datetime(elec_mensuel[col]))["ttc"]
        prix_elec = base["mois"].map(s).ffill()
        source_elec = "prix moyen tous contrats (Eurostat)"

    if prix_elec is None:
        journal.note("INDISPONIBLE", "Coût au km", "Aucun prix d'électricité : véhicule "
                     "électrique non calculé.")
        return None
    base["electrique"] = prix_elec * ve_kwh / 100.0

    journal.note("METHODE", "Coût au km",
                 f"Coût de 100 km calculé avec {essence_l:g} l/100 km (essence), "
                 f"{diesel_l:g} l/100 km (gazole) et {ve_kwh:g} kWh/100 km (électrique, "
                 f"au compteur). Électricité valorisée au {source_elec}. Ces consommations "
                 "sont des conventions : elles fixent les niveaux, pas les évolutions.")
    return base.dropna(subset=["essence"]).reset_index(drop=True)


def deflate(df: pd.DataFrame, ipc: pd.DataFrame | None, cols: list[str], journal: Journal,
            name: str, ref: str | None = None, date_col: str = "mois",
            freq: str = "M") -> pd.DataFrame:
    """Ajoute `coef_deflateur` et une colonne `<col>_constants` pour chaque `cols`.

    `ref` est le mois de référence des euros constants ("AAAA-MM") ; par défaut le
    dernier mois d'IPC disponible. Les mois postérieurs au dernier IPC publié n'ont
    pas de déflateur : on le dit, au lieu de livrer des colonnes vides sans explication.
    """
    out = df.copy()
    if ipc is None or not len(ipc):
        journal.note("INDISPONIBLE", name, "Pas d'IPC : aucune colonne en euros constants.")
        for c in cols:
            out[f"{c}_constants"] = pd.NA
        out["coef_deflateur"] = pd.NA
        return out

    serie = ipc.set_index(pd.to_datetime(ipc["date"]))["ipc_base2015"].astype(float)
    ref_ts = pd.Timestamp(f"{ref}-01") if ref else serie.index.max()
    if ref_ts not in serie.index:
        journal.note("ERREUR", name,
                     f"Mois de référence {ref_ts:%Y-%m} absent de l'IPC "
                     f"({serie.index.min():%Y-%m} → {serie.index.max():%Y-%m}) : dernier mois utilisé.")
        ref_ts = serie.index.max()

    nb_mois = MOIS_PAR_PERIODE.get(freq, 1)
    idx = pd.to_datetime(out[date_col])
    if nb_mois == 1:
        base = float(serie.loc[ref_ts])
        denom = idx.map(serie)
    else:
        # Série non mensuelle : chaque observation vaut pour plusieurs mois, on la
        # rapporte à l'IPC moyen de sa propre période, et la référence à l'IPC moyen
        # d'une période de même longueur : sinon on comparerait des choses différentes.
        base = _ipc_periode(serie, ref_ts, nb_mois)
        denom = idx.map(lambda t: _ipc_periode(serie, pd.Timestamp(t), nb_mois))
        journal.note("METHODE", name,
                     f"Déflateur calculé sur l'IPC moyen de chaque période de {nb_mois} mois "
                     "(et non sur l'IPC du seul mois de début).")
    out["coef_deflateur"] = base / denom

    manquants = int(out["coef_deflateur"].isna().sum())
    if manquants:
        derniers = idx[out["coef_deflateur"].isna()]
        journal.note("INDISPONIBLE", name,
                     f"{manquants} mois sans déflateur ({derniers.min():%Y-%m} → {derniers.max():%Y-%m}) : "
                     f"l'IPC s'arrête en {serie.index.max():%Y-%m}. Colonnes en euros constants vides sur ces mois.")

    journal.note("METHODE", name,
                 f"Euros constants de {ref_ts:%Y-%m} : valeur constante = valeur courante "
                 f"x IPC({ref_ts:%Y-%m}) / IPC(mois).")
    for c in cols:
        if c in out.columns:
            out[f"{c}_constants"] = pd.to_numeric(out[c], errors="coerce") * out["coef_deflateur"]
    return out
