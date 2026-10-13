"""Ministère de la Transition écologique – DGEC – page « Prix des produits pétroliers ».

La page expose (liens xlsx dont l'URL change à chaque mise à jour, d'où le scraping) :
  * moyennes mensuelles du Brent daté ($/b, source Reuters/DGEC) ;
  * historique de la marge brute de raffinage sur Brent depuis 2015 ($/b, €/t, c€/l) ;
  * prix HTT et TTC hebdomadaires depuis janvier 2020 (sp95-e5, sp95-e10, sp98, gazole…) ;
  * un tableau HTML des coûts moyens annuels de transport-distribution (c€/l) depuis 2015,
    définis par la DGEC comme HTT − cotation internationale du produit raffiné.

Et, en option, les notes hebdomadaires PDF « Cours, prix et marges » (NPG-AAAA.MM.JJ.pdf)
qui contiennent les cotations Rotterdam mensuelles en c€/l.
"""
from __future__ import annotations

import io
import re
from datetime import date, timedelta
from urllib.parse import unquote

import pandas as pd

from prix_energie.common import first_numeric_table
from prix_energie.donnees.fetch import DownloadError, fetch
from prix_energie.journal import Journal, log
from prix_energie.config import DGEC_NPG_SUFFIXES, DGEC_NPG_URL_TEMPLATE, DGEC_PAGE_URL
from prix_energie.donnees.contracts import Contract, ContractError, check

BASE = "https://www.ecologie.gouv.fr"

# Une clé mensuelle unique suffit à écarter le bloc « moyennes annuelles » que ces
# feuilles juxtaposent aux moyennes mensuelles sous le même en-tête de date.
CONTRACT_BRENT = Contract(name="Brent DGEC", key="date", required=("brent_usd_bbl",),
                          bounds={"brent_usd_bbl": (5.0, 300.0)}, freq="M", min_rows=24)
CONTRACT_MARGE = Contract(name="Marge raffinage", key="date", freq="M", min_rows=24,
                          bounds={"marge_usd_bbl": (-50.0, 200.0), "marge_eur_t": (-400.0, 1500.0)})
CONTRACT_PRIX2020 = Contract(name="Prix DGEC 2020", key="date", min_rows=100)


def _page_links(offline: bool) -> list[str]:
    html = fetch(DGEC_PAGE_URL, offline=offline).decode("utf-8", "ignore")
    links = []
    for m in re.finditer(r'href="([^"]+\.xlsx?[^"]*)"', html, re.I):
        href = m.group(1).replace("&amp;", "&")
        links.append(href if href.startswith("http") else BASE + href)
    return sorted(set(links)), html


def _pick(links: list[str], *patterns: str) -> str | None:
    """Premier lien dont le *nom de fichier décodé* satisfait tous les motifs.

    Le motif porte sur le nom seul, jamais sur l'URL entière : « htt » est une
    sous-chaîne de « https », si bien qu'un `re.search("htt", href)` matchait tous
    les liens et renvoyait le premier de la liste triée : en septembre 2026, le
    fichier de marge de raffinage au lieu des prix HTT/TTC. Le nom est aussi
    pourcent-décodé, pour que « %20 » redevienne un espace et que les frontières
    de mot (\\b) aient un sens.
    """
    for href in links:
        name = unquote(href.rsplit("/", 1)[-1]).lower()
        if all(re.search(p, name) for p in patterns):
            return href
    return None


def _read_all_sheets(raw: bytes) -> list[tuple[str, pd.DataFrame]]:
    xls = pd.ExcelFile(io.BytesIO(raw))
    return [(n, xls.parse(n, header=None)) for n in xls.sheet_names]


def load_dgec_page(journal: Journal, offline: bool = False) -> dict:
    """Retourne {'brent': df|None, 'marge': df|None, 'prix2020': df|None, 'td_annuel': df|None, 'links': [...]}."""
    out: dict = {"brent": None, "marge": None, "prix2020": None, "td_annuel": None, "links": []}
    try:
        links, html = _page_links(offline)
    except DownloadError as e:
        journal.note("ERREUR", "DGEC", f"Page inaccessible : {e}")
        return out
    out["links"] = links
    log.info("DGEC : %d liens xlsx trouvés", len(links))

    # ---- Brent daté, moyennes mensuelles
    # Le fichier de marge s'appelle « ... raffinage sur Brent ... » : on l'exclut explicitement.
    href_brent = _pick(links, r"^(?!.*marge).*brent")
    if href_brent:
        try:
            for name, sheet in _read_all_sheets(fetch(href_brent, offline=offline)):
                tab = first_numeric_table(sheet, min_dates=24)
                if tab is None:
                    tab = _parse_year_month_matrix(sheet)
                if tab is not None and tab.shape[1] >= 2:
                    val_col = tab.columns[1]
                    out["brent"] = check(tab[["date", val_col]].rename(columns={val_col: "brent_usd_bbl"}),
                                         CONTRACT_BRENT, journal)
                    break
            journal.source("Brent daté – moyennes mensuelles ($/b)", "DGEC / Reuters", href_brent,
                           "Moyenne des cours quotidiens de clôture à Londres.")
        except Exception as e:  # noqa: BLE001
            journal.note("ERREUR", "Brent DGEC", f"Lecture impossible : {e}")
    else:
        journal.note("INDISPONIBLE", "Brent DGEC", "Aucun lien xlsx 'Brent' trouvé sur la page DGEC.")

    # ---- Marge brute de raffinage sur Brent (depuis 2015)
    href_marge = _pick(links, r"marge", r"raffinage")
    if href_marge:
        try:
            for name, sheet in _read_all_sheets(fetch(href_marge, offline=offline)):
                tab = first_numeric_table(sheet, min_dates=24)
                if tab is None:
                    tab = _parse_year_month_matrix(sheet)
                if tab is not None:
                    tab = tab.rename(columns=_rename_marge_cols)
                    out["marge"] = check(tab, CONTRACT_MARGE, journal)
                    break
            journal.source("Marge brute de raffinage sur Brent (mensuel, 2015→)", "DGEC / Reuters", href_marge,
                           "Indicateur théorique : valorisation d'un panier Rotterdam − cotation Brent.")
            journal.note("RUPTURE", "Marge raffinage", "La DGEC a modifié le mode de calcul de l'indicateur ; "
                         "l'historique publié commence en 2015 (nouvelle méthode). Pas de série officielle "
                         "comparable avant 2015 : composante indisponible.")
        except Exception as e:  # noqa: BLE001
            journal.note("ERREUR", "Marge raffinage", f"Lecture impossible : {e}")
    else:
        journal.note("INDISPONIBLE", "Marge raffinage", "Aucun lien xlsx 'marge … raffinage' trouvé sur la page DGEC.")

    # ---- Prix HTT et TTC hebdomadaires depuis 2020 (contient sp95-e10)
    href_prix = _pick(links, r"\bhtt\b") or _pick(links, r"prix.*\bttc\b")
    if href_prix:
        try:
            frames = []
            for name, sheet in _read_all_sheets(fetch(href_prix, offline=offline)):
                tab = first_numeric_table(sheet, min_dates=24)
                if tab is not None:
                    tab.columns = ["date"] + [f"{name}|{c}" for c in tab.columns[1:]]
                    frames.append(tab)
            if frames:
                df = frames[0]
                for f in frames[1:]:
                    df = df.merge(f, on="date", how="outer")
                df = df.sort_values("date").reset_index(drop=True)
                # Garde-fou sur le *bon* fichier : sans colonne E10, c'est qu'on n'a pas
                # celui des prix. Le dire ici évite de le découvrir plus loin sous la
                # forme trompeuse « colonnes E10 non trouvées ».
                if not any(re.search(r"e10", str(c), re.I) for c in df.columns):
                    raise ContractError(
                        f"fichier retenu sans colonne E10 : {unquote(href_prix.rsplit('/', 1)[-1])} "
                        f"(colonnes : {[str(c)[:40] for c in df.columns][:6]}…). "
                        "Ce n'est pas le fichier « Prix HTT et TTC ».")
                out["prix2020"] = check(df, CONTRACT_PRIX2020, journal)
                journal.source("Carburants – prix HTT et TTC hebdo depuis 2020 (sp95-e5, sp95-e10, gazole…)", "DGEC",
                               href_prix, "Prix du vendredi, France métropolitaine hors Corse, c€/l.")
        except Exception as e:  # noqa: BLE001
            journal.note("ERREUR", "Prix DGEC 2020", f"Lecture impossible : {e}")
    else:
        journal.note("INDISPONIBLE", "Prix DGEC 2020", "Aucun lien xlsx 'Prix HTT et TTC' trouvé.")

    # ---- Coûts de transport-distribution annuels (tableau HTML)
    try:
        out["td_annuel"] = _parse_td_table(html)
        journal.source("Coûts moyens de transport-distribution (annuel, 2015→)", "DGEC", DGEC_PAGE_URL,
                       "Définition DGEC : prix HTT − cotation internationale du produit raffiné (Rotterdam), c€/l.")
    except Exception as e:  # noqa: BLE001
        journal.note("ERREUR", "Transport-distribution DGEC", f"Tableau HTML non lu : {e}")
    return out


def _rename_marge_cols(c: str) -> str:
    n = str(c).lower()
    if "$" in n and ("/b" in n or "bl" in n or "baril" in n):
        return "marge_usd_bbl"
    if "€/t" in n or "eur/t" in n or "/t" in n:
        return "marge_eur_t"
    if "c€" in n or "c€/l" in n or "cts" in n or "/l" in n:
        return "marge_ceur_l"
    return c


def _parse_year_month_matrix(sheet: pd.DataFrame) -> pd.DataFrame | None:
    """Format alternatif fréquent : années en lignes, 12 mois en colonnes (ou l'inverse)."""
    s = sheet.copy()
    years = pd.to_numeric(s.iloc[:, 0], errors="coerce")
    yr_rows = years.between(1980, 2100)
    if yr_rows.sum() >= 5 and s.shape[1] >= 13:
        rows = []
        for i in s.index[yr_rows]:
            y = int(years[i])
            for m in range(1, 13):
                v = pd.to_numeric(s.iloc[i, m], errors="coerce")
                if pd.notna(v):
                    rows.append({"date": pd.Timestamp(y, m, 1), "valeur": float(v)})
        if rows:
            return pd.DataFrame(rows)
    return None


def _parse_td_table(html: str) -> pd.DataFrame | None:
    """Tableau « Évolution des coûts moyens de transport-distribution en France en c€/l »."""
    try:
        tables = pd.read_html(io.StringIO(html), decimal=",", thousands=" ")
    except ValueError:
        return None
    for t in tables:
        t = t.copy()
        # Sans balises <th>, pandas numérote les colonnes 0,1,2… et la vraie ligne
        # d'en-tête reste la première ligne de données. Chercher « gazole » dans
        # `t.columns` ne pouvait donc jamais aboutir sur cette page.
        if all(str(c).strip().isdigit() for c in t.columns):
            t.columns = [str(v).strip() for v in t.iloc[0]]
            t = t.iloc[1:].reset_index(drop=True)
        cols = " ".join(str(c) for c in t.columns).lower()
        if "gazole" in cols and ("eurosuper" in cols or "sp95" in cols):
            t.columns = [str(c) for c in t.columns]
            t = t.rename(columns={t.columns[0]: "annee"})
            ren = {}
            for c in t.columns[1:]:
                lc = c.lower()
                if "gazole" in lc:
                    ren[c] = "td_gazole"
                elif "e10" in lc:
                    ren[c] = "td_sp95_e10"
                elif "e5" in lc or "sp95" in lc or "eurosuper" in lc:
                    ren[c] = "td_sp95_e5"
            t = t.rename(columns=ren)
            t["annee"] = pd.to_numeric(t["annee"], errors="coerce")
            for c in t.columns[1:]:
                t[c] = pd.to_numeric(t[c].astype(str).str.replace(",", ".", regex=False), errors="coerce")
            return t.dropna(subset=["annee"]).astype({"annee": int}).reset_index(drop=True)
    return None


# --------------------------------------------------------------------------- NPG (PDF)
MONTHS_FR = {"janv": 1, "févr": 2, "fevr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6, "juil": 7,
             "août": 8, "aout": 8, "sept": 9, "oct": 10, "nov": 11, "déc": 12, "dec": 12}
_MONTH_TOKEN = re.compile(r"(janv|févr|fevr|mars|avr|mai|juin|juil|août|aout|sept|oct|nov|déc|dec)\.?-(\d{2})", re.I)
_NUM = r"(-?\d{1,3}(?:\s?\d{3})*,\d{1,2})"


def _fr_num(s: str) -> float:
    return float(s.replace("\u202f", "").replace(" ", "").replace(",", "."))


def _last_fridays(n: int) -> list[date]:
    d = date.today()
    d -= timedelta(days=(d.weekday() - 4) % 7)  # dernier vendredi
    return [d - timedelta(weeks=k) for k in range(n)]


def load_npg_quotations(journal: Journal, weeks: int, offline: bool = False) -> pd.DataFrame | None:
    """Cotations Rotterdam mensuelles (c€/l) extraites des notes hebdomadaires DGEC.

    Chaque note donne, page 4, un tableau « Cotations internationales et prix hors toutes
    taxes » : pour le SP95-E5 puis le gazole, lignes France / U.E. 27 / Cotations, colonnes
    (mois en cours provisoire, mois précédent). On garde, pour chaque mois, la valeur issue
    de la note la plus récente (donc la moins provisoire). Lecture PDF = fragile : chaque
    valeur retenue est bornée (10–200 c€/l) et le mois de la note la plus récente est
    marqué provisoire.
    """
    if weeks <= 0:
        return None
    try:
        import pdfplumber  # noqa: WPS433
    except ImportError:
        journal.note("INDISPONIBLE", "Cotations Rotterdam (NPG)", "pdfplumber non installé : pip install pdfplumber")
        return None
    rows = []
    marges: list[dict] = []
    brents: list[dict] = []
    n_ok = 0
    for fri in _last_fridays(weeks):
        pdf_bytes = None
        for suf in DGEC_NPG_SUFFIXES:
            url = DGEC_NPG_URL_TEMPLATE.format(date=fri.strftime("%Y.%m.%d")).replace(".pdf", f"{suf}.pdf")
            try:
                pdf_bytes = fetch(url, offline=offline, ok_404=True)
            except DownloadError:
                pdf_bytes = None
            if pdf_bytes:
                break
        if not pdf_bytes:
            continue
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        except Exception as e:  # noqa: BLE001
            journal.note("ERREUR", "NPG", f"{fri}: PDF illisible ({e})")
            continue
        for r in _parse_npg_marge(text):
            marges.append({**r, "note": fri})
        for r in _parse_npg_brent(text):
            brents.append({**r, "note": fri})
        parsed = _parse_npg_text(text)
        if parsed:
            n_ok += 1
            for prod, (m_cur, v_cur, m_prev, v_prev) in parsed.items():
                rows.append({"produit": prod, "mois": m_cur, "cotation_ceur_l": v_cur, "note": fri, "provisoire": True})
                rows.append({"produit": prod, "mois": m_prev, "cotation_ceur_l": v_prev, "note": fri, "provisoire": False})
    if not rows:
        journal.note("INDISPONIBLE", "Cotations Rotterdam (NPG)", f"Aucune note lue sur {weeks} semaines tentées.")
        return None
    df = pd.DataFrame(rows).sort_values(["produit", "mois", "note"])
    # pour chaque (produit, mois) : dernière note disponible ; provisoire si aucune note
    # n'a fourni ce mois comme « mois précédent »
    agg = df.groupby(["produit", "mois"]).agg(cotation_ceur_l=("cotation_ceur_l", "last"),
                                                provisoire=("provisoire", "min"), note=("note", "last")).reset_index()
    journal.source("Cotations Rotterdam mensuelles (c€/l) – SP95-E5 et gazole", "DGEC / Reuters – notes hebdomadaires NPG",
                   DGEC_NPG_URL_TEMPLATE, f"{n_ok} notes PDF lues ; extraction texte, à contrôler.")
    journal.note("PROVISOIRE", "Cotations Rotterdam (NPG)",
                 "Les mois marqués provisoires n'ont été vus que comme 'mois en cours' d'une note.")
    if marges:
        mg = (pd.DataFrame(marges).sort_values(["date", "note"])
              .groupby("date").agg(marge_eur_t=("marge_eur_t", "last"),
                                   provisoire=("provisoire", "min")).reset_index())
        journal.note("METHODE", "Marge de raffinage",
                     f"{len(mg)} mois de marge brute lus dans les notes hebdomadaires "
                     f"({mg.date.min():%Y-%m} → {mg.date.max():%Y-%m}), en €/t, pour "
                     "prolonger la série mensuelle DGEC au-delà de sa dernière publication.")
        agg.attrs["marge"] = mg
    if brents:
        bt = (pd.DataFrame(brents).sort_values(["date", "note"])
              .groupby("date").agg(brent_eur_bbl=("brent_eur_bbl", "last")).reset_index())
        journal.note("PROVISOIRE", "Brent",
                     f"Cours en euros repris des notes hebdomadaires pour "
                     f"{', '.join(f'{d:%Y-%m}' for d in bt.date)} : c'est une moyenne de "
                     "semaine, pas de mois, en attendant la publication mensuelle.")
        agg.attrs["brent"] = bt
    return agg


def _parse_npg_brent(text: str) -> list[dict]:
    """Cours du Brent en euros par baril, lu dans la note hebdomadaire.

    Attention à la nature de la donnée : la note ne publie le Brent qu'en **moyenne
    hebdomadaire**, là où les séries INSEE et DGEC sont mensuelles. La valeur sert donc
    à renseigner le mois en cours tant qu'aucune moyenne mensuelle n'est publiée, et
    elle est marquée comme telle. Sur un mois où le cours bouge peu, l'écart est
    négligeable ; sur un mois de flambée, elle surestime le début du mois.

    Le tableau donne la semaine courante puis la précédente ; on ne garde que la
    première, datée au premier du mois de la note.
    """
    lignes = text.split("\n")
    for i, l in enumerate(lignes):
        if not re.search(r"Brent\s*\(en\s*.?/b\)", l):
            continue
        if "$" in l:                      # la ligne en dollars, pas celle qu'on veut
            continue
        vals = re.findall(_NUM, l)
        if not vals:
            continue
        # Date : le premier libellé de mois trouvé dans les lignes d'en-tête au-dessus.
        mois = None
        for j in range(max(0, i - 4), i):
            m = _MONTH_TOKEN.search(lignes[j])
            if m:
                mois = (MONTHS_FR[m.group(1)], 2000 + int(m.group(2)))
                break
        if mois is None:
            continue
        v = _fr_num(vals[0])
        if 5.0 <= v <= 400.0:
            return [{"date": pd.Timestamp(year=mois[1], month=mois[0], day=1),
                     "brent_eur_bbl": v}]
    return []

def _parse_npg_marge(text: str) -> list[dict]:
    """Marge brute de raffinage mensuelle, lue dans la note hebdomadaire.

    La note la publie en trois unités ; on prend les €/t, qui sont celles de la série
    mensuelle DGEC, donc directement comparables. Contrôle sur août 2026 : la note
    donne 246 €/t, la série mensuelle en donne 246,1.

    Le tableau porte le mois en cours puis le mois précédent, suivis d'une variation et
    d'une moyenne annuelle qu'on ignore. La valeur du mois en cours est provisoire.
    """
    lignes = text.split("\n")
    for i, l in enumerate(lignes):
        if "marge brute de raffinage" not in l.lower():
            continue
        mois = []
        for j in range(i, min(i + 5, len(lignes))):
            mois += [(MONTHS_FR[m.group(1)], 2000 + int(m.group(2)))
                     for m in _MONTH_TOKEN.finditer(lignes[j])]
        val = None
        for j in range(i, min(i + 10, len(lignes))):
            if re.match(r"\s*en\s*.?/t\b", lignes[j], re.I):
                # « en €/t 256 246 10 149 » : entiers séparés par des espaces. Un
                # motif tolérant les séparateurs de milliers lirait « 256 246 »
                # comme une seule valeur. La marge n'a jamais approché 1 000 €/t,
                # donc lire les entiers un par un est sans risque ici.
                val = re.findall(r"\d+", lignes[j])
                break
        if not val or len(mois) < 2:
            continue
        out = []
        for k, (m, y) in enumerate(mois[:2]):
            if k >= len(val):
                break
            try:
                v = float(val[k].replace(" ", "").replace(" ", ""))
            except ValueError:
                continue
            # Bornes larges : la marge observée va de quelques dizaines à ~400 €/t.
            if 20.0 <= v <= 900.0:
                out.append({"date": pd.Timestamp(year=y, month=m, day=1),
                            "marge_eur_t": v, "provisoire": k == 0})
        if out:
            return out
    return []

def _parse_npg_text(text: str) -> dict | None:
    """Extrait {'sp95': (mois, val, mois-1, val-1), 'gazole': (...)} du texte d'une note."""
    i = text.find("Cotations internationales et prix hors toutes taxes")
    if i < 0:
        return None
    seg = text[i:i + 3000]
    out = {}
    for prod, anchor in (("sp95", r"sans plomb.*?c€/l"), ("gazole", r"Gazole en c€/l")):
        m = re.search(anchor, seg, re.I | re.S)
        if not m:
            continue
        sub = seg[m.end():m.end() + 700]
        mm = _MONTH_TOKEN.findall(sub)
        cot = re.search(r"Cotations?\s+" + _NUM + r"\s+" + _NUM, sub, re.I)
        if len(mm) < 2 or not cot:
            continue
        (mo1, y1), (mo2, y2) = mm[0], mm[1]
        d1 = pd.Timestamp(2000 + int(y1), MONTHS_FR[mo1.lower().rstrip(".")], 1)
        d2 = pd.Timestamp(2000 + int(y2), MONTHS_FR[mo2.lower().rstrip(".")], 1)
        v1, v2 = _fr_num(cot.group(1)), _fr_num(cot.group(2))
        if not (10 <= v1 <= 200 and 10 <= v2 <= 200):
            continue
        out[prod] = (d1, v1, d2, v2)
    return out or None
