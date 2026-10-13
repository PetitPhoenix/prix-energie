"""Commission européenne – Weekly Oil Bulletin – historique depuis 2005.

Le fichier « Oil Bulletin Prices History » contient, par pays, les prix moyens
hebdomadaires à la pompe (prix du lundi) *avec* toutes taxes et *hors toutes taxes*
(accise et TVA exclues), en €/1000 l, pour Euro-super 95 et gazole routier notamment.

Le format des onglets a varié au fil des ans ; deux mises en page sont gérées.

1. Mise en page « large » (en vigueur depuis 2026) : une seule ligne d'en-tête en
   ligne 0 portant des jetons ``<PAYS>_price_<wo|with>_tax_<carburant>``, une ligne
   par date en colonne 0 (ordre décroissant) et les pays déployés horizontalement
   sur ~226 colonnes. La largeur des blocs pays varie : les pays hors zone euro
   intercalent une colonne ``exchange_rate``. On cible donc les jetons d'en-tête,
   jamais des positions.
2. Mise en page « verticale » (historique) : les blocs pays sont empilés, repérés
   par une ligne « FR »/« France » suivie d'un en-tête contenant « Euro-super ».
   Conservée en secours pour les fichiers déjà en cache.
"""
from __future__ import annotations

import io
import re

import pandas as pd

from prix_energie.donnees.fetch import DownloadError, fetch
from prix_energie.journal import Journal, log
from prix_energie.config import WOB_HISTORY_URL, WOB_LANDING_URL
from prix_energie.donnees.contracts import Contract, check

# Prix à la pompe en c€/l après conversion depuis les €/1000 l de la source.
# Bornes larges : elles visent une erreur d'unité ou de colonne, pas une variation de marché.
CONTRACT = Contract(
    name="WOB",
    key="date",
    required=("sp95_ht", "sp95_ttc", "gazole_ht", "gazole_ttc"),
    bounds={"sp95_ht": (5.0, 300.0), "sp95_ttc": (30.0, 400.0),
            "gazole_ht": (5.0, 300.0), "gazole_ttc": (30.0, 400.0)},
    freq="W",
    min_rows=500,
)

COUNTRY_TOKENS = {"fr", "france"}
COUNTRY = "FR"
# Jeton d'en-tête de la mise en page large, p. ex. « FR_price_wo_tax_euro95 ».
WIDE_TOKEN = re.compile(
    r"^(?P<ctr>[A-Za-z]{2,3})_price_(?P<kind>wo|with)_tax_(?P<fuel>euro95|diesel)$", re.I
)
WIDE_FUEL = {"euro95": "sp95", "diesel": "gazole"}
COL_PATTERNS = {
    "sp95": re.compile(r"euro.?super", re.I),
    "gazole": re.compile(r"(automotive|auto|diesel).*gas.?oil|gas.?oil.*(automotive|auto|diesel)|^gas.?oil$|gazole|diesel", re.I),
}


def _classify_sheet(name: str) -> str | None:
    n = name.lower()
    if "tax" not in n:
        return None
    if re.search(r"\bwo\b|without|w/o|hors|excl", n):
        return "ht"
    if "with" in n or "avec" in n or "incl" in n:
        return "ttc"
    return None


def _resolve_history_url(offline: bool) -> str:
    """Le lien direct est stable depuis 2021 ; en secours, on cherche un lien
    'History' sur la page de garde du bulletin."""
    try:
        fetch(WOB_HISTORY_URL, offline=offline)
        return WOB_HISTORY_URL
    except DownloadError:
        html = fetch(WOB_LANDING_URL, offline=offline).decode("utf-8", "ignore")
        for m in re.finditer(r'href="([^"]+)"', html):
            href = m.group(1)
            if re.search(r"histor", href, re.I) and re.search(r"xls", href, re.I):
                return href if href.startswith("http") else "https://energy.ec.europa.eu" + href
        raise


def _parse_wide(sheet: pd.DataFrame, country: str = COUNTRY) -> tuple[str, pd.DataFrame] | None:
    """Mise en page large : retourne ('ht'|'ttc', DataFrame date/sp95/gazole), ou None.

    Le type (hors taxes / toutes taxes) est déduit du jeton d'en-tête et non du nom
    de l'onglet : c'est la source la plus fiable des deux.
    """
    if sheet.shape[0] < 10:
        return None
    header = [str(v).strip() for v in sheet.iloc[0].tolist()]
    kinds: set[str] = set()
    cols: dict[str, int] = {}
    for j, name in enumerate(header):
        m = WIDE_TOKEN.match(name)
        if m is None or m.group("ctr").upper() != country.upper():
            continue
        kinds.add("ht" if m.group("kind").lower() == "wo" else "ttc")
        cols[WIDE_FUEL[m.group("fuel").lower()]] = j
    if len(kinds) != 1 or "sp95" not in cols or "gazole" not in cols:
        return None

    body = sheet.iloc[3:]  # 0 = jetons, 1 = libellés multilingues, 2 = unités
    date_col, best = None, 0
    for j in range(min(4, sheet.shape[1])):
        col = body.iloc[:, j]
        # une colonne de prix serait sinon convertie en epochs nanosecondes et l'emporterait
        if pd.api.types.is_numeric_dtype(col):
            continue
        parsed = pd.to_datetime(col, errors="coerce")
        n = int(parsed.dt.year.between(1990, 2100).sum())
        if n > best:
            date_col, best = j, n
    if date_col is None or best < 50:
        return None

    unit = str(sheet.iat[2, cols["sp95"]]).strip().lower()
    if "1000" not in unit:
        log.warning("WOB : unité inattendue '%s' pour %s (attendu '1000 l') : vérifier la conversion",
                    unit, country)

    out = pd.DataFrame({
        "date": pd.to_datetime(body.iloc[:, date_col], errors="coerce"),
        "sp95": pd.to_numeric(body.iloc[:, cols["sp95"]], errors="coerce"),
        "gazole": pd.to_numeric(body.iloc[:, cols["gazole"]], errors="coerce"),
    }).dropna(subset=["date"]).sort_values("date")
    if len(out) < 50:
        return None
    return kinds.pop(), out.reset_index(drop=True)


def _parse_country_block(sheet: pd.DataFrame) -> pd.DataFrame | None:
    nrow = sheet.shape[0]
    starts = []
    for i in range(nrow):
        vals = [str(v).strip().lower() for v in sheet.iloc[i].tolist() if pd.notna(v)]
        if any(v in COUNTRY_TOKENS for v in vals):
            starts.append(i)
    for s in starts:
        # en-tête dans les 6 lignes suivantes (ou la ligne elle-même)
        for h in range(s, min(s + 7, nrow)):
            row = sheet.iloc[h]
            names = [str(v) for v in row.tolist()]
            if any(COL_PATTERNS["sp95"].search(n) for n in names):
                colmap = {}
                for j, n in enumerate(names):
                    for key, pat in COL_PATTERNS.items():
                        if key not in colmap and pat.search(n) and not re.search(r"heating|chauffage|non.?road", n, re.I):
                            colmap[key] = j
                if "sp95" not in colmap or "gazole" not in colmap:
                    continue
                # colonne de dates : première colonne avec des dates après l'en-tête
                body = sheet.iloc[h + 1:]
                date_col = None
                for j in range(sheet.shape[1]):
                    parsed = pd.to_datetime(body.iloc[:60, j], errors="coerce")
                    if parsed.notna().sum() >= 20:
                        date_col = j
                        break
                if date_col is None:
                    continue
                dates = pd.to_datetime(body.iloc[:, date_col], errors="coerce")
                # fin du bloc = 3 lignes consécutives sans date
                stop = len(dates)
                miss = 0
                for k, ok in enumerate(dates.notna().tolist()):
                    miss = 0 if ok else miss + 1
                    if miss >= 3:
                        stop = k - 2
                        break
                blk = body.iloc[:stop]
                d = pd.to_datetime(blk.iloc[:, date_col], errors="coerce")
                out = pd.DataFrame({
                    "date": d,
                    "sp95": pd.to_numeric(blk.iloc[:, colmap["sp95"]], errors="coerce"),
                    "gazole": pd.to_numeric(blk.iloc[:, colmap["gazole"]], errors="coerce"),
                }).dropna(subset=["date"])
                if len(out) >= 50:
                    return out.reset_index(drop=True)
    return None


def load_wob(journal: Journal, offline: bool = False) -> pd.DataFrame:
    """Retourne un DataFrame hebdomadaire : date, sp95_ht, sp95_ttc, gazole_ht, gazole_ttc (c€/l)."""
    url = _resolve_history_url(offline)
    raw = fetch(url, offline=offline)
    xls = pd.ExcelFile(io.BytesIO(raw))
    parts: dict[str, pd.DataFrame] = {}
    for name in xls.sheet_names:
        kind = _classify_sheet(name)
        if kind is None or kind in parts:
            continue
        sheet = xls.parse(name, header=None)
        wide = _parse_wide(sheet)
        if wide is not None:
            kind_hdr, blk = wide
            if kind_hdr != kind:
                log.warning("WOB : onglet '%s' classé %s d'après son nom mais %s d'après ses "
                            "en-têtes ; on retient %s", name, kind, kind_hdr, kind_hdr)
            kind = kind_hdr
            layout = "large"
        else:
            blk = _parse_country_block(sheet)
            layout = "verticale"
        if blk is not None and kind not in parts:
            parts[kind] = blk
            log.info("WOB : onglet '%s' (mise en page %s) → %s, %d semaines (%s → %s)",
                     name, layout, kind, len(blk), blk.date.min().date(), blk.date.max().date())
    if "ht" not in parts or "ttc" not in parts:
        manque = " et ".join(k.upper() for k in ("ht", "ttc") if k not in parts)
        raise RuntimeError(
            f"WOB : bloc {COUNTRY} introuvable ({manque} manquant). Les onglets ont bien été "
            f"reconnus, c'est la mise en page interne qui n'est pas comprise. "
            f"Onglets : {xls.sheet_names}")
    ht = parts["ht"].rename(columns={"sp95": "sp95_ht", "gazole": "gazole_ht"})
    ttc = parts["ttc"].rename(columns={"sp95": "sp95_ttc", "gazole": "gazole_ttc"})
    df = ht.merge(ttc, on="date", how="outer").sort_values("date")
    # €/1000 l → c€/l
    for c in ("sp95_ht", "sp95_ttc", "gazole_ht", "gazole_ttc"):
        df[c] = df[c] / 10.0
    df = check(df.reset_index(drop=True), CONTRACT, journal)
    # contrôles de vraisemblance
    bad = df[(df.sp95_ttc < df.sp95_ht) | (df.gazole_ttc < df.gazole_ht)]
    if len(bad):
        journal.note("ERREUR", "WOB", f"{len(bad)} semaines avec TTC < HT (vérifier l'unité / le bloc pays).")
    journal.source("Carburants – prix hebdo HT et TTC France (2005→)", "Commission européenne, DG ENER, Weekly Oil Bulletin",
                   url, "Prix moyens nationaux du lundi, €/1000 l convertis en c€/l. 'HT' = hors accise et hors TVA.")
    journal.note("DEFINITION", "WOB", "Euro-super 95 déclaré par la France = SP95 (E5). Prix du lundi, "
                 "moyenne nationale pondérée déclarée par la DGEC ; la base DGEC publie des prix du vendredi : "
                 "les deux ne coïncident pas exactement semaine à semaine.")
    journal.note("METHODE", "WOB", "L'accise n'est pas publiée dans l'historique : elle est déduite par "
                 "accise = TTC − HT − TVA avec TVA = TTC × t/(1+t). Elle intègre donc la moyenne des "
                 "modulations régionales et les arrondis de la moyenne nationale.")
    return df.reset_index(drop=True)
