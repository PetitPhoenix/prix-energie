"""Comparaison d'une série avec la version déjà écrite, avant écrasement.

Un producteur peut, d'une semaine à l'autre, raccourcir un historique, renommer une
colonne ou retirer un onglet. Le script le suivrait sans broncher et le CSV en sortie
perdrait des années de données : silencieusement, puisque le fichier aurait l'air
normal. On compare donc systématiquement avant d'écrire.

Deux natures d'écart, traitées différemment :

  * PERTE    : clés ou colonnes présentes avant et absentes maintenant. Anormal :
               bloque l'écriture par défaut.
  * RÉVISION : valeurs modifiées sur des clés communes. Légitime (l'INSEE révise,
               la DGEC consolide ses provisoires) : signalé, mais n'empêche rien.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Colonnes candidates comme clé de comparaison, par ordre de préférence.
CLES = ("mois", "date", "periode", "annee")
# Écart relatif au-delà duquel une valeur est considérée comme révisée.
TOLERANCE = 1e-6


@dataclass
class Ecart:
    fichier: str
    nature: str          # "PERTE" ou "REVISION"
    quoi: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.nature}] {self.fichier} – {self.quoi} : {self.detail}"


def _cle(df: pd.DataFrame) -> str | None:
    return next((c for c in CLES if c in df.columns), None)


def _indexer(df: pd.DataFrame, cle: str, garder: set[str]) -> pd.DataFrame:
    """Restreint `df` aux clés de `garder` et indexe dessus, pour aligner deux versions."""
    k = df[cle].astype(str)
    out = df[k.isin(garder)].copy()
    out.index = pd.Index(k[k.isin(garder)], name=cle)
    return out[~out.index.duplicated(keep="first")]


def comparer(ancien: pd.DataFrame, nouveau: pd.DataFrame, fichier: str) -> list[Ecart]:
    """Écarts entre la version sur disque et celle qu'on s'apprête à écrire."""
    ecarts: list[Ecart] = []

    perdues = [c for c in ancien.columns if c not in nouveau.columns]
    if perdues:
        ecarts.append(Ecart(fichier, "PERTE", "colonnes disparues", ", ".join(map(str, perdues))))

    cle = _cle(ancien)
    if cle is None or cle not in nouveau.columns:
        # Sans clé commune, on se rabat sur le nombre de lignes.
        if len(nouveau) < len(ancien):
            ecarts.append(Ecart(fichier, "PERTE", "lignes",
                                f"{len(ancien)} → {len(nouveau)} ({len(ancien) - len(nouveau)} de moins)"))
        return ecarts

    a_cles = set(ancien[cle].astype(str))
    n_cles = set(nouveau[cle].astype(str))
    manquantes = sorted(a_cles - n_cles)
    if manquantes:
        apercu = ", ".join(manquantes[:5]) + ("…" if len(manquantes) > 5 else "")
        ecarts.append(Ecart(fichier, "PERTE", f"{len(manquantes)} clé(s) disparue(s)", apercu))

    ajoutees = len(n_cles - a_cles)

    # Révisions sur les clés communes, colonnes numériques seulement.
    communes = a_cles & n_cles
    if communes:
        a = _indexer(ancien, cle, communes)
        n = _indexer(nouveau, cle, communes)
        for col in ancien.columns:
            if col == cle or col not in nouveau.columns:
                continue
            # astype(float) : certaines colonnes sont booléennes (cotation_provisoire)
            # et la soustraction n'est pas définie sur des booléens numpy.
            va = pd.to_numeric(a[col], errors="coerce").astype("float64")
            vn = pd.to_numeric(n[col], errors="coerce").astype("float64").reindex(va.index)
            if va.notna().sum() == 0:
                continue
            ecart = (va - vn).abs()
            ref = va.abs().clip(lower=1e-12)
            change = (ecart / ref > TOLERANCE) & va.notna() & vn.notna()
            # Une valeur qui existait et devient vide est une perte, pas une révision.
            vidage = va.notna() & vn.isna()
            if vidage.any():
                ecarts.append(Ecart(fichier, "PERTE", f"colonne '{col}' vidée",
                                    f"{int(vidage.sum())} valeur(s) devenue(s) vide(s)"))
            if change.any():
                i = change.idxmax()
                ecarts.append(Ecart(fichier, "REVISION", f"colonne '{col}'",
                                    f"{int(change.sum())} valeur(s) modifiée(s) "
                                    f"(ex. {i} : {va[i]:.4g} → {vn[i]:.4g})"))

    if ajoutees and not any(e.nature == "PERTE" for e in ecarts):
        ecarts.append(Ecart(fichier, "REVISION", "lignes ajoutées", f"{ajoutees} nouvelle(s)"))
    return ecarts


def lire_existant(path: Path, sep: str) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path, sep=sep, encoding="utf-8")
    except Exception:  # noqa: BLE001 : un fichier illisible ne doit pas bloquer l'écriture
        return None


def pertes(ecarts: list[Ecart]) -> list[Ecart]:
    return [e for e in ecarts if e.nature == "PERTE"]
