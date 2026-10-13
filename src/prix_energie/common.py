"""Utilitaires partagés : taux de TVA, dates, repérage de tables dans un tableur."""
from __future__ import annotations

from datetime import date
from typing import Iterable

import pandas as pd


from prix_energie.config import VAT_RATES


# --------------------------------------------------------------------------- utilitaires
def vat_rate(d: pd.Timestamp | date) -> float:
    """Taux de TVA carburants en vigueur à la date d."""
    ts = pd.Timestamp(d)
    rate = VAT_RATES[0][1]
    for start, r in VAT_RATES:
        if ts >= pd.Timestamp(start):
            rate = r
    return rate


def to_month(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.to_period("M").dt.to_timestamp()


def monthly_mean(df: pd.DataFrame, date_col: str, cols: Iterable[str]) -> pd.DataFrame:
    """Moyenne mensuelle arithmétique des observations (hebdomadaires ou quotidiennes).

    Les extrêmes du mois sont conservés à côté de la moyenne. Un mois où le prix monte
    de sept centimes se résume mal par sa moyenne : elle est inférieure à ce que le
    conducteur a payé en fin de mois, et à ce qu'il a en tête.
    """
    cols = list(cols)
    g = df.assign(mois=to_month(df[date_col])).groupby("mois")
    out = (g[cols].mean(numeric_only=True)
           .join(g[cols].min(numeric_only=True).add_suffix("_min"))
           .join(g[cols].max(numeric_only=True).add_suffix("_max")))
    out["n_obs"] = g.size()
    return out.reset_index()


def find_date_column(df: pd.DataFrame, min_dates: int = 12) -> int | None:
    """Indice de la première colonne contenant au moins `min_dates` dates plausibles."""
    for i in range(df.shape[1]):
        col = df.iloc[:, i]
        parsed = pd.to_datetime(col, errors="coerce")
        if parsed.notna().sum() >= min_dates:
            return i
    return None


def _first_contiguous_block(dates: pd.Series, max_gap: int = 2) -> tuple[int, int] | None:
    """Bornes du premier bloc de lignes datées, une coupure étant `max_gap` lignes sans date.

    Les feuilles DGEC juxtaposent plusieurs tables : les moyennes mensuelles, puis,
    après quelques lignes vides, les moyennes annuelles. Sans cette borne, un parseur
    « toutes les lignes datées » mélange les deux granularités : d'autant que
    `pd.to_datetime("2015")` vaut 2015-01-01, ce qui met chaque janvier en double.
    """
    ok = dates.notna().tolist()
    idx = list(dates.index)
    start = next((i for i, v in enumerate(ok) if v), None)
    if start is None:
        return None
    end, miss = start, 0
    for i in range(start + 1, len(ok)):
        if ok[i]:
            end, miss = i, 0
        else:
            miss += 1
            if miss >= max_gap:
                break
    return idx[start], idx[end]


def _header_labels(raw: pd.DataFrame, first: int, depth: int = 2) -> pd.Series | None:
    """Étiquettes de colonnes, construites sur les `depth` lignes au-dessus des données.

    Les fichiers DGEC portent le niveau de prix (« PRIX DE VENTE H.T.T. ») sur une
    ligne, fusionnée sur tout son bloc, et le produit (« Super SP95-E10 ») sur la
    suivante. Lire la seule ligne basse donne six produits en double : un par niveau -
    et `df["Gazole"]` renvoie alors un DataFrame au lieu d'une Series. On propage donc
    la ligne haute vers la droite et on concatène les deux.
    """
    if not first or first <= 0:
        return None
    haut = max(0, first - depth)
    lignes = []
    for i in range(haut, first):
        row = raw.iloc[i].astype("object").where(lambda s: s.notna() & (s.astype(str).str.strip() != ""))
        # ffill = cellules fusionnées : la valeur ne figure que dans la première colonne
        lignes.append(row.ffill() if i < first - 1 else row)
    if not lignes:
        return None
    out = []
    for j in range(raw.shape[1]):
        parts = [str(l.iloc[j]).strip() for l in lignes
                 if pd.notna(l.iloc[j]) and str(l.iloc[j]).strip() not in ("", "nan")]
        out.append(" | ".join(dict.fromkeys(parts)))
    return pd.Series(out, index=range(raw.shape[1]))


def _unique(names: list[str]) -> list[str]:
    """Garantit l'unicité des noms de colonnes (suffixe _2, _3… en dernier recours)."""
    vus: dict[str, int] = {}
    out = []
    for n in names:
        if n in vus:
            vus[n] += 1
            out.append(f"{n}_{vus[n]}")
        else:
            vus[n] = 1
            out.append(n)
    return out


def first_numeric_table(raw: pd.DataFrame, min_dates: int = 12) -> pd.DataFrame | None:
    """Heuristique pour les xlsx « libres » : repère la colonne de dates, prend la ligne
    au-dessus de la première date comme en-tête, ne garde que les colonnes numériques.
    Seul le premier bloc contigu de lignes datées est retenu (voir _first_contiguous_block)."""
    ci = find_date_column(raw, min_dates)
    if ci is None:
        return None
    dates = pd.to_datetime(raw.iloc[:, ci], errors="coerce")
    span = _first_contiguous_block(dates)
    if span is None:
        return None
    lo, hi = span
    first = lo
    header_row = _header_labels(raw, first)
    keep_rows = dates.notna() & (dates.index >= lo) & (dates.index <= hi)
    dates = dates[keep_rows]
    body = raw.loc[keep_rows].copy()
    body.insert(0, "date", dates[dates.notna()].values)
    cols = ["date"]
    keep = [0]
    for j in range(raw.shape[1]):
        if j == ci:
            continue
        num = pd.to_numeric(body.iloc[:, j + 1], errors="coerce")
        if num.notna().sum() >= min_dates:
            name = str(header_row.iloc[j]).strip() if header_row is not None else f"col{j}"
            if name in ("nan", "None", ""):
                name = f"col{j}"
            cols.append(name)
            keep.append(j + 1)
    out = body.iloc[:, keep]
    out.columns = _unique(cols)
    cols = list(out.columns)
    for c in cols[1:]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.reset_index(drop=True)
