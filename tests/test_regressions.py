"""Tests de non-régression des défauts constatés en septembre 2026.

Chacun reproduit la forme exacte du fichier producteur qui avait piégé le parseur,
sans réseau.
"""
from __future__ import annotations

import pandas as pd
import pytest

from prix_energie.common import first_numeric_table
from prix_energie.donnees.contracts import Contract, ContractError, check
from prix_energie.donnees.fetch import UA
from prix_energie.donnees.guard import comparer, pertes
from prix_energie.donnees.sources.dgec import _pick
from prix_energie.journal import Journal
from prix_energie.modele.decomposition import decompose


# --------------------------------------------------------------------- bug 1 : _pick
LIENS = [
    "https://www.ecologie.gouv.fr/sites/default/files/documents/"
    "Historique%20de%20la%20marge%20brute%20de%20raffinage%20sur%20Brent.xlsx",
    "https://www.ecologie.gouv.fr/sites/default/files/documents/"
    "Historique%20du%20cours%20du%20Brent%20depuis%202015_0.xlsx",
    "https://www.ecologie.gouv.fr/sites/default/files/documents/"
    "Prix%20HTT%20et%20TTC%20depuis%20janvier%202020_0.xlsx",
]


def test_pick_ne_confond_pas_htt_et_https():
    """« htt » est une sous-chaîne de « https » : le motif doit porter sur le nom seul."""
    assert "Prix%20HTT" in _pick(LIENS, r"\bhtt\b")


def test_pick_exclut_la_marge_pour_le_brent():
    """Le fichier de marge s'appelle « ... raffinage sur Brent ... »."""
    assert "cours%20du%20Brent" in _pick(LIENS, r"^(?!.*marge).*brent")


def test_pick_rend_none_si_aucun_match():
    assert _pick(LIENS, r"introuvable") is None


# ------------------------------------------------- bug 2 : deux granularités empilées
def _feuille_dgec_deux_blocs() -> pd.DataFrame:
    """Reproduit la feuille Brent : moyennes mensuelles, 3 lignes vides, moyennes annuelles.

    Le piège tient à ce que `pd.to_datetime("2015")` vaut 2015-01-01 : sans borne de
    bloc, chaque janvier se retrouve en double avec une moyenne annuelle.
    """
    lignes: list[list] = [["COURS MOYENS MENSUELS", None], ["Moyennes mensuelles", "en $/b"]]
    for annee in (2015, 2016):
        for mois in range(1, 13):
            lignes.append([pd.Timestamp(annee, mois, 1), 50.0 + mois])
    lignes += [[None, None]] * 3
    lignes.append(["MOYENNES ANNUELLES", None])
    for annee in (2015, 2016):
        lignes.append([str(annee), 99.0])
    return pd.DataFrame(lignes)


def test_bloc_annuel_non_melange_au_mensuel():
    tab = first_numeric_table(_feuille_dgec_deux_blocs(), min_dates=12)
    assert tab is not None
    dates = pd.to_datetime(tab["date"])
    assert len(tab) == 24, "seules les 24 lignes mensuelles doivent être retenues"
    assert not dates.duplicated().any(), "un janvier en double = bloc annuel avalé"
    assert 99.0 not in list(tab.iloc[:, 1]), "valeur annuelle présente dans la table mensuelle"


def test_contrat_refuse_une_cle_dupliquee():
    """Deuxième filet : même si un parseur laisse passer des doublons, le contrat coupe."""
    df = pd.DataFrame({"date": pd.to_datetime(["2015-01-01", "2015-01-01", "2015-02-01"]),
                       "v": [1.0, 2.0, 3.0]})
    with pytest.raises(ContractError, match="doublon"):
        check(df, Contract(name="test", key="date"), Journal())


# ------------------------------------------------------- bug 3 : contrat sur le format
def test_contrat_signale_les_colonnes_manquantes():
    df = pd.DataFrame({"date": pd.to_datetime(["2020-01-01"]), "autre": [1.0]})
    with pytest.raises(ContractError, match="absentes"):
        check(df, Contract(name="test", key="date", required=("sp95_ht",)), Journal())


def test_contrat_signale_une_unite_suspecte():
    """Des €/1000 l rangés dans une colonne de c€/l : 20x trop grand."""
    df = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=3, freq="MS"),
                       "ttc": [2172.0, 2180.0, 2190.0]})
    with pytest.raises(ContractError, match="hors de"):
        check(df, Contract(name="test", key="date", bounds={"ttc": (20.0, 400.0)}), Journal())


# ------------------------------------------------ décomposition (ex-formules Excel)
def test_accise_deduite_correspond_au_bareme_2005():
    """Contrôle externe : TICPE 2005 = 41,69 c€/l sur le gazole, 58,92 sur le SP95.

    C'est le seul vrai test de la chaîne HT/TTC : il croise d'un coup le bloc pays,
    l'unité et le taux de TVA.
    """
    df = pd.DataFrame({
        "mois": pd.to_datetime(["2005-01-01", "2005-01-01"]),
        "ttc": [92.1864, 104.3724],
        "ht": [35.3890, 28.3478],
        "taux_tva": [0.196, 0.196],
    })
    out = decompose(df, Journal(), "test")
    assert out.loc[0, "accise"] == pytest.approx(41.69, abs=0.01)
    assert out.loc[1, "accise"] == pytest.approx(58.92, abs=0.01)


def test_decomposition_reconstitue_le_ttc():
    df = pd.DataFrame({"mois": pd.to_datetime(["2024-06-01"]), "ttc": [180.0],
                       "ht": [70.0], "taux_tva": [0.20]})
    out = decompose(df, Journal(), "test")
    somme = out.loc[0, "ht_non_decompose"] + out.loc[0, "accise"] + out.loc[0, "tva"]
    assert somme == pytest.approx(180.0, abs=1e-9)


def test_transport_distribution_exclusif_du_ht_non_decompose():
    """Les deux colonnes ne doivent jamais être renseignées sur la même ligne."""
    df = pd.DataFrame({"mois": pd.to_datetime(["2024-06-01", "2024-07-01"]),
                       "ttc": [180.0, 180.0], "ht": [70.0, 70.0],
                       "taux_tva": [0.20, 0.20], "cotation": [45.0, None]})
    out = decompose(df, Journal(), "test")
    assert out.loc[0, "transport_distribution"] == pytest.approx(25.0)
    assert pd.isna(out.loc[0, "ht_non_decompose"])
    assert pd.isna(out.loc[1, "transport_distribution"])
    assert out.loc[1, "ht_non_decompose"] == pytest.approx(70.0)


# ------------------------------------------------ garde-fou contre la perte de données
def _serie(n: int = 12, debut: str = "2020-01-01") -> pd.DataFrame:
    mois = pd.date_range(debut, periods=n, freq="MS")
    # Colonnes en flottants : un prix révisé ne rentrerait pas dans une colonne d'entiers.
    return pd.DataFrame({"mois": mois.astype(str),
                         "ttc": [100.0 + i for i in range(n)],
                         "accise": [60.0] * n})


def test_perte_de_lignes_detectee():
    a = _serie(12)
    e = pertes(comparer(a, a.iloc[6:], "t.csv"))
    assert len(e) == 1 and "6 clé(s) disparue(s)" in e[0].quoi


def test_perte_de_colonne_detectee():
    a = _serie()
    e = pertes(comparer(a, a.drop(columns=["accise"]), "t.csv"))
    assert len(e) == 1 and "accise" in e[0].detail


def test_colonne_videe_compte_comme_perte():
    """Une valeur qui existait et devient vide est une perte, pas une révision."""
    a = _serie()
    n = a.copy()
    n.loc[:3, "accise"] = None
    assert pertes(comparer(a, n, "t.csv"))


def test_revision_de_valeur_ne_bloque_pas():
    """Les producteurs révisent leurs provisoires : c'est signalé, pas bloquant."""
    a = _serie()
    n = a.copy()
    n.loc[2, "ttc"] = n.loc[2, "ttc"] * 1.05
    diff = comparer(a, n, "t.csv")
    assert diff and not pertes(diff)


def test_ajout_de_mois_ne_bloque_pas():
    a = _serie(12)
    assert not pertes(comparer(a, _serie(15), "t.csv"))


def test_user_agent_reste_ascii():
    """Un « é » dans le User-Agent faisait répondre 403 au pare-feu de data.gouv."""
    UA["User-Agent"].encode("ascii")

