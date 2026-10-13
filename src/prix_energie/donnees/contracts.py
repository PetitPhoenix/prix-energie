"""Contrats de source : ce qu'une série doit vérifier pour être acceptée.

Remplace les heuristiques par une déclaration. Au lieu de deviner la structure d'un
fichier producteur et de livrer silencieusement ce qui en sort, chaque source déclare
ce qu'elle *doit* produire ; l'écart est alors traité selon sa gravité :

  * il rend la série inutilisable  -> ContractError, le build s'arrête ;
  * il la dégrade seulement        -> note au journal, la série passe.

Les trois défauts observés en septembre 2026 sont couverts :
  * fichier DGEC mal sélectionné (`_pick` matchait « htt » dans « https ») -> `required` ;
  * moyennes annuelles avalées par le parseur mensuel du Brent            -> `key` unique ;
  * bloc pays WOB introuvable                                             -> `min_rows`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from prix_energie.journal import Journal

# Écart attendu entre deux observations consécutives, en jours (min, max).
FREQ_DAYS = {"W": (7, 7), "M": (28, 31), "Q": (89, 92), "S": (181, 184), "Y": (365, 366)}


class ContractError(RuntimeError):
    """Violation rendant la série inutilisable : échouer vaut mieux que livrer du faux."""


@dataclass(frozen=True)
class Contract:
    """Ce qu'une série normalisée doit vérifier.

    `bounds` porte sur des ordres de grandeur, pas sur des seuils fins : il s'agit
    d'attraper un parseur qui a lu la mauvaise colonne (une marge en €/t rangée dans
    une colonne de c€/l), pas de valider l'économie.
    """

    name: str
    key: str = "date"
    required: tuple[str, ...] = ()
    bounds: dict[str, tuple[float, float]] = field(default_factory=dict)
    freq: str | None = None
    min_rows: int = 0
    # Part d'écarts inter-observations hors `freq` tolérée avant de noter un trou.
    # Le WOB saute réellement quelques semaines par an : 10 % évite un faux positif.
    max_gap_ratio: float = 0.10


def check(df: pd.DataFrame | None, contract: Contract, journal: Journal) -> pd.DataFrame:
    """Valide `df` contre `contract`. Retourne la série triée, ou lève ContractError."""
    c = contract
    if df is None:
        raise ContractError(f"{c.name} : aucune donnée produite.")
    if c.key not in df.columns:
        raise ContractError(f"{c.name} : colonne clé '{c.key}' absente (colonnes : {list(df.columns)}).")

    missing = [col for col in c.required if col not in df.columns]
    if missing:
        raise ContractError(
            f"{c.name} : colonnes attendues absentes {missing}. "
            f"Colonnes obtenues : {list(df.columns)}. "
            "Le producteur a probablement changé son format, ou le mauvais fichier a été retenu."
        )

    out = df.copy()

    # --- clé : ni trou, ni doublon. C'est ce qui attrape un bloc annuel avalé par
    # un parseur mensuel (11 janviers en double dans le Brent DGEC).
    if out[c.key].isna().any():
        n = int(out[c.key].isna().sum())
        raise ContractError(f"{c.name} : {n} ligne(s) sans valeur de clé '{c.key}'.")
    dup = out[c.key].duplicated(keep=False)
    if dup.any():
        ex = sorted(out.loc[dup, c.key].unique())[:5]
        raise ContractError(
            f"{c.name} : {int(dup.sum())} ligne(s) en doublon sur '{c.key}' "
            f"(ex. {[str(v)[:10] for v in ex]}). Deux granularités mélangées dans la même table ?"
        )

    if not out[c.key].is_monotonic_increasing:
        journal.note("METHODE", c.name, "Série reçue non triée sur la clé : triée à la lecture.")
        out = out.sort_values(c.key).reset_index(drop=True)

    if len(out) < c.min_rows:
        raise ContractError(f"{c.name} : {len(out)} ligne(s) pour un minimum de {c.min_rows}.")

    # --- ordres de grandeur
    for col, (lo, hi) in c.bounds.items():
        if col not in out.columns:
            continue
        v = pd.to_numeric(out[col], errors="coerce")
        bad = v.notna() & ~v.between(lo, hi)
        if bad.any():
            ex = [round(float(x), 2) for x in v[bad].head(3)]
            raise ContractError(
                f"{c.name} : {int(bad.sum())} valeur(s) de '{col}' hors de [{lo}, {hi}] "
                f"(ex. {ex}). Mauvaise colonne lue, ou mauvaise unité ?"
            )

    # --- régularité : dégrade, n'invalide pas
    if c.freq and len(out) > 2:
        lo, hi = FREQ_DAYS[c.freq]
        d = pd.to_datetime(out[c.key]).diff().dt.days.dropna()
        gaps = ~d.between(lo, hi)
        if gaps.any() and gaps.mean() > c.max_gap_ratio:
            journal.note(
                "RUPTURE", c.name,
                f"{int(gaps.sum())} écart(s) sur {len(d)} hors du pas attendu ({c.freq}, {lo}-{hi} j) : "
                f"série irrégulière ou granularités mélangées.")
        elif gaps.any():
            journal.note(
                "METHODE", c.name,
                f"{int(gaps.sum())} observation(s) manquante(s) dans la source (pas {c.freq}).")

    return out.reset_index(drop=True)


def coverage(df: pd.DataFrame, cols: list[str], journal: Journal, name: str,
             minimum: float = 0.90) -> None:
    """Note au journal les colonnes trop creuses pour être exploitables telles quelles."""
    for col in cols:
        if col not in df.columns or not len(df):
            continue
        filled = float(df[col].notna().mean())
        if filled == 0.0:
            journal.note("INDISPONIBLE", name, f"Colonne '{col}' entièrement vide.")
        elif filled < minimum:
            journal.note("PROVISOIRE", name,
                         f"Colonne '{col}' renseignée sur {filled:.0%} des lignes seulement.")
