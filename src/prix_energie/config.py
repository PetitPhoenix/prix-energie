"""Paramètres centralisés : URLs des sources, constantes fiscales, choix méthodologiques.

Tout ce qui est un *choix* (date de chaînage SP95→E10, consommation de référence pour
le TRV, profondeur de l'archive NPG) est ici, et documenté dans la feuille « Lisez-moi »
du classeur produit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- chemins
CACHE_DIR = Path(".cache_prix_energie")   # téléchargements bruts (rejouables hors-ligne)
OUTPUT_XLSX = Path("prix_energie_france.xlsx")

# --------------------------------------------------------------------------- sources
# Commission européenne – DG ENER – Weekly Oil Bulletin, historique depuis 2005
# (prix moyens hebdomadaires nationaux HT et TTC, €/1000 l). Lien relevé dans les
# newsletters ENER-OIL-BULLETIN 2025 ; la page de garde est scrutée en secours.
WOB_HISTORY_URL = (
    "https://energy.ec.europa.eu/document/download/"
    "906e60ca-8b6a-44e7-8589-652854d2fd3f_en"
    "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx"
)
WOB_LANDING_URL = "https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en"

# Ministère de la Transition écologique – DGEC – page « Prix des produits pétroliers »
# (fichiers xlsx : Brent daté mensuel, marge brute de raffinage depuis 2015,
# prix HTT/TTC depuis 2020 ; tableau HTML des coûts de transport-distribution annuels).
DGEC_PAGE_URL = "https://www.ecologie.gouv.fr/politiques-publiques/prix-produits-petroliers"
# Note hebdomadaire DGEC « Cours, prix et marges des produits pétroliers » (PDF).
# Nom de fichier observé : NPG-YYYY.MM.DD.pdf (parfois suffixe _0). Date = vendredi.
DGEC_NPG_URL_TEMPLATE = "https://www.ecologie.gouv.fr/sites/default/files/documents/NPG-{date}.pdf"
DGEC_NPG_SUFFIXES = ("", "_0", "_1")

# Eurostat – API JSON-stat 2.0
EUROSTAT_API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}"
EUROSTAT_DATASETS = {
    # prix semestriels ménages, nouvelle méthodologie (2007S1 →), 3 niveaux de taxes
    "nrg_pc_204": {"geo": "FR", "nrg_cons": "KWH2500-4999", "currency": "EUR", "unit": "KWH"},
    # composantes annuelles (2017 →) : fourniture, réseau, taxes détaillées, TVA
    "nrg_pc_204_c": {"geo": "FR", "nrg_cons": "KWH2500-4999", "currency": "EUR"},
    # ancienne méthodologie (1985 → 2007), consommateurs-types Da..De
    "nrg_pc_204_h": {"geo": "FR", "currency": "EUR"},
}

# CRE – data.gouv.fr – Historique des TRV électricité résidentiels (depuis 2012)
CRE_TRV_DATASET_URL = (
    "https://www.data.gouv.fr/fr/datasets/"
    "historique-des-tarifs-reglementes-de-vente-delectricite-pour-les-consommateurs-residentiels/"
)
CRE_TRV_RESOURCES = {
    # identifiants des ressources relevés sur la page du jeu de données (sept. 2026)
    "base": "https://www.data.gouv.fr/api/1/datasets/r/c13d05e5-9e55-4d03-bf7e-042a2ade7e49",
    "hphc": "https://www.data.gouv.fr/api/1/datasets/r/f7303b3a-93c7-4242-813d-84919034c416",
    "tempo": "https://www.data.gouv.fr/api/1/datasets/r/0c3d1d36-c412-4620-8566-e5cbb4fa2b5a",
    "doc": "https://www.data.gouv.fr/api/1/datasets/r/82756653-3ae3-4ae4-a256-77fe0ab0800f",
}

# Secours NON européen pour le Brent (Federal Reserve Bank of St. Louis, série EIA).
# Utilisé uniquement si le fichier DGEC est introuvable, et signalé comme tel.
FRED_BRENT_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"

# --------------------------------------------------------------------------- fiscalité
# Taux normal de TVA applicable aux carburants en France métropolitaine.
# (Loi de finances : 20,6 % → 19,6 % au 01/04/2000 ; 19,6 % → 20 % au 01/01/2014.)
VAT_RATES = [
    ("1982-07-01", 0.186),
    ("1995-08-01", 0.206),
    ("2000-04-01", 0.196),
    ("2014-01-01", 0.200),
]

# --------------------------------------------------------------------------- méthodo
@dataclass
class Choices:
    # Période couverte
    start: str = "1985-01"
    # Date de chaînage sans-plomb : SP95 (E5) avant, SP95-E10 après. La rupture est
    # explicitement signalée et le saut de niveau à la date de chaînage est calculé.
    sp_e10_chain: str = "2020-01"
    # Consommation annuelle de référence pour transformer le TRV (part fixe + part
    # variable) en un prix moyen par kWh. Bande Eurostat DC = 2 500–4 999 kWh.
    trv_ref_kwh: float = 3500.0
    trv_power_kva: int = 6
    # Nombre de notes hebdomadaires NPG (PDF) à tenter de lire en remontant depuis
    # aujourd'hui. 0 = désactivé. ~52 par an ; l'archive en ligne est limitée.
    npg_weeks: int = 0
    # Masses volumiques utilisées par la DGEC pour convertir $/t en c€/l (kg/l) :
    # eurosuper 0,755 ; gazole 0,845. Sources : convention DGEC/CPDP.
    density_eurosuper: float = 0.755
    density_gasoil: float = 0.845
    # Euros constants : mois de référence de l'IPC ("AAAA-MM") ; None = dernier mois disponible
    ipc_ref: str | None = None
    # Fichier IPC fourni à la main (csv INSEE) et idbank de la nouvelle base 2025 (raccord)
    ipc_csv: str | None = None
    ipc_idbank_2025: str | None = None
    # Fichier de l'IPC base 2025, quand l'API BDM est inaccessible
    ipc_csv_2025: str | None = None
    # Export manuel de la base DGEC (prix 1985 →) pour remonter avant 2005
    dgec_base: str | None = None
    # --- cas de base pour ramener les prix à un coût au kilomètre ------------------
    # Un litre et un kilowattheure n'ont pas de commune mesure ; le coût de 100 km en a
    # une. Ces trois consommations sont des CONVENTIONS, pas des mesures : elles sont
    # affichées partout où le résultat est présenté, et se changent en ligne de commande.
    # Ordres de grandeur d'un véhicule particulier moyen en usage mixte.
    conso_essence_l_100km: float = 6.5
    conso_diesel_l_100km: float = 5.5
    # Au compteur du logement, pertes de charge comprises (le véhicule en consomme moins).
    conso_ve_kwh_100km: float = 18.0
    # Extras : liste libre de notes utilisateur à reporter dans le classeur
    notes: list[str] = field(default_factory=list)


BARREL_LITRES = 158.987
