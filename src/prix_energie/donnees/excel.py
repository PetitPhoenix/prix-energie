"""Écriture du classeur : données, composantes calculées par formule, graphiques empilés."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from prix_energie.bundle import Bundle

FONT = "Arial"
HDR_FILL = PatternFill("solid", fgColor="DDEBF7")
NOTE_FILL = PatternFill("solid", fgColor="FFF2CC")
F_HDR = Font(name=FONT, bold=True, size=10)
F_TXT = Font(name=FONT, size=10)
F_TITLE = Font(name=FONT, bold=True, size=14)
F_FORMULA = Font(name=FONT, size=10, color="000000")
F_INPUT = Font(name=FONT, size=10, color="0000FF")


# --------------------------------------------------------------------------- helpers
def _cell(ws, r, c, v, font=F_TXT, fmt=None):
    if isinstance(v, float) and pd.isna(v):
        v = None
    if v is pd.NA or v is pd.NaT:
        v = None
    if isinstance(v, pd.Timestamp):
        v = v.to_pydatetime()
    cell = ws.cell(row=r, column=c, value=v)
    cell.font = font
    if fmt:
        cell.number_format = fmt
    return cell


def _headers(ws, row, names, widths=None):
    for i, n in enumerate(names, 1):
        c = _cell(ws, row, i, n, F_HDR)
        c.fill = HDR_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")
        if widths:
            ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]
    ws.row_dimensions[row].height = 42
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _write_df(ws, df: pd.DataFrame, row0: int = 1, date_fmt="yyyy-mm", num_fmt="0.00"):
    _headers(ws, row0, list(df.columns), [14] * len(df.columns))
    for i, rec in enumerate(df.itertuples(index=False), row0 + 1):
        for j, v in enumerate(rec, 1):
            fmt = None
            if isinstance(v, pd.Timestamp):
                fmt = date_fmt
            elif isinstance(v, float):
                fmt = num_fmt
            _cell(ws, i, j, v, F_INPUT if isinstance(v, (int, float)) else F_TXT, fmt)
    return row0 + len(df)


# --------------------------------------------------------------------------- carburants
FUEL_COLS = ["Mois", "Année", "Nb obs.", "Source prix", "Prix TTC (c€/l)", "Prix HT hors accise (c€/l)",
             "Taux TVA", "Cotation Rotterdam (c€/l)", "Cotation provisoire", "TVA (c€/l)", "Accise TICPE (c€/l)",
             "Transport-distribution (c€/l)", "HT non décomposé (c€/l)", "Contrôle (somme − TTC)",
             "Coef. déflateur IPC", "TTC € constants", "Cotation € constants", "Transport-distrib. € constants",
             "HT non décomposé € constants", "Accise € constants", "TVA € constants"]
# indices (1-based, hors décalage Produit) des colonnes utilisées par les graphiques
FUEL_STACK_NOMINAL = [8, 12, 13, 11, 10]
FUEL_STACK_CONSTANT = [17, 18, 19, 20, 21]


def _deflator_formula(date_cell: str) -> str:
    return f'=IFERROR(IPC!$E$3/INDEX(IPC!$B:$B,MATCH({date_cell},IPC!$A:$A,0)),"")'


def write_fuel_monthly(wb: Workbook, title: str, df: pd.DataFrame, has_ipc: bool) -> str:
    ws = wb.create_sheet(title)
    cols = FUEL_COLS.copy()
    has_prod = "produit" in df.columns
    if has_prod:
        cols.insert(3, "Produit")
    widths = [10, 7, 7] + ([11] if has_prod else []) + [10, 11, 11, 8, 12, 10, 10, 11, 13, 13, 11, 10, 11, 11, 12, 12, 11, 11]
    _headers(ws, 1, cols, widths)
    off = 1 if has_prod else 0
    L = lambda k: get_column_letter(k + off)  # noqa: E731
    for i, rec in enumerate(df.itertuples(index=False), 2):
        _cell(ws, i, 1, rec.mois, fmt="yyyy-mm")
        _cell(ws, i, 2, int(rec.annee))
        _cell(ws, i, 3, int(rec.n_obs))
        c = 4
        if has_prod:
            _cell(ws, i, c, rec.produit); c += 1
        _cell(ws, i, c, rec.source); c += 1
        _cell(ws, i, c, float(rec.ttc) if pd.notna(rec.ttc) else None, F_INPUT, "0.00"); c += 1
        _cell(ws, i, c, float(rec.ht) if pd.notna(rec.ht) else None, F_INPUT, "0.00"); c += 1
        _cell(ws, i, c, float(rec.taux_tva), F_INPUT, "0.0%"); c += 1
        _cell(ws, i, c, float(rec.cotation) if pd.notna(rec.cotation) else None, F_INPUT, "0.00"); c += 1
        _cell(ws, i, c, ("oui" if rec.cotation_provisoire is True else None) if pd.notna(rec.cotation) else None); c += 1
        ttc, ht, tva, cot = L(5), L(6), L(7), L(8)
        _cell(ws, i, c, f"={ttc}{i}*{tva}{i}/(1+{tva}{i})", F_FORMULA, "0.00"); c += 1                 # 10 TVA
        _cell(ws, i, c, f"={ttc}{i}-{ht}{i}-{L(10)}{i}", F_FORMULA, "0.00"); c += 1                     # 11 Accise
        _cell(ws, i, c, f'=IF({cot}{i}="","",{ht}{i}-{cot}{i})', F_FORMULA, "0.00"); c += 1             # 12 T-D
        _cell(ws, i, c, f'=IF({cot}{i}="",{ht}{i},"")', F_FORMULA, "0.00"); c += 1                       # 13 HT nd
        _cell(ws, i, c, f'=IF({cot}{i}="",{L(13)}{i},{cot}{i}+{L(12)}{i})+{L(11)}{i}+{L(10)}{i}-{ttc}{i}',
              F_FORMULA, "0.00"); c += 1                                                                  # 14 contrôle
        if has_ipc:
            _cell(ws, i, c, _deflator_formula(f"$A{i}"), F_FORMULA, "0.0000"); c += 1                   # 15 coef
            k = f"{L(15)}{i}"
            for src in (5, 8, 12, 13, 11, 10):                                                           # 16..21
                _cell(ws, i, c, f'=IF(OR({k}="",{L(src)}{i}=""),"",{L(src)}{i}*{k})', F_FORMULA, "0.00"); c += 1
    return ws.title


ANNUAL_COLS = ["Année", "Nb mois", "Nb mois avec cotation", "Cotation Rotterdam (c€/l)", "Transport-distribution (c€/l)",
               "HT non décomposé (c€/l)", "Accise TICPE (c€/l)", "TVA (c€/l)", "Prix TTC (c€/l)", "Prix HT (c€/l)"]


def write_fuel_annual(wb: Workbook, title: str, monthly_sheet: str, df: pd.DataFrame, has_prod: bool) -> str:
    """Moyennes annuelles par formules AVERAGEIFS sur la feuille mensuelle. La décomposition
    cotation / T-D n'est reportée que si tous les mois de l'année ont une cotation ; sinon la
    part 'HT non décomposé' porte tout le hors-taxes."""
    ws = wb.create_sheet(title)
    _headers(ws, 1, ANNUAL_COLS, [8, 8, 10, 12, 13, 13, 12, 10, 11, 11])
    off = 1 if has_prod else 0
    S = f"'{monthly_sheet}'!"
    col = lambda k: f"{S}${get_column_letter(k + off)}:${get_column_letter(k + off)}"  # noqa: E731
    yr = f"{S}$B:$B"
    years = sorted(df.annee.unique())
    for i, y in enumerate(years, 2):
        _cell(ws, i, 1, int(y), F_INPUT, "0")
        _cell(ws, i, 2, f"=COUNTIFS({yr},$A{i})", F_FORMULA, "0")
        _cell(ws, i, 3, f'=COUNTIFS({yr},$A{i},{col(8)},"<>")', F_FORMULA, "0")
        full = f"$C{i}=$B{i}"
        _cell(ws, i, 4, f'=IF({full},AVERAGEIFS({col(8)},{yr},$A{i}),"")', F_FORMULA, "0.00")
        _cell(ws, i, 5, f'=IF({full},AVERAGEIFS({col(6)},{yr},$A{i})-$D{i},"")', F_FORMULA, "0.00")
        _cell(ws, i, 6, f'=IF({full},"",AVERAGEIFS({col(6)},{yr},$A{i}))', F_FORMULA, "0.00")
        _cell(ws, i, 7, f"=AVERAGEIFS({col(11)},{yr},$A{i})", F_FORMULA, "0.00")
        _cell(ws, i, 8, f"=AVERAGEIFS({col(10)},{yr},$A{i})", F_FORMULA, "0.00")
        _cell(ws, i, 9, f"=AVERAGEIFS({col(5)},{yr},$A{i})", F_FORMULA, "0.00")
        _cell(ws, i, 10, f"=AVERAGEIFS({col(6)},{yr},$A{i})", F_FORMULA, "0.00")
    last = 1 + len(years)
    _cell(ws, last + 2, 1, "Une année incomplète (Nb mois < 12) est une moyenne partielle.", F_TXT).fill = NOTE_FILL
    return ws.title, last


def _stacked_chart(ws_src, title, y_title, cats_col, series_cols, first, last, anchor_ws, anchor, width=28, height=12,
                   gap=40, date_axis=False):
    ch = BarChart()
    ch.type = "col"
    ch.grouping = "stacked"
    ch.overlap = 100
    ch.gapWidth = gap
    if date_axis:
        ch.x_axis.number_format = "yyyy"
        ch.x_axis.tickLblSkip = 24
        ch.x_axis.tickMarkSkip = 12
    ch.title = title
    ch.y_axis.title = y_title
    ch.width, ch.height = width, height
    for c in series_cols:
        ref = Reference(ws_src, min_col=c, min_row=first - 1, max_row=last)  # inclut l'en-tête pour le nom
        ch.add_data(ref, titles_from_data=True)
    ch.set_categories(Reference(ws_src, min_col=cats_col, min_row=first, max_row=last))
    ch.legend.position = "b"
    anchor_ws.add_chart(ch, anchor)


def _line_chart(ws_src, title, y_title, cats_col, series_cols, first, last, anchor_ws, anchor, width=28, height=10):
    ch = LineChart()
    ch.title = title
    ch.y_axis.title = y_title
    ch.width, ch.height = width, height
    for c in series_cols:
        ch.add_data(Reference(ws_src, min_col=c, min_row=first - 1, max_row=last), titles_from_data=True)
    for sr in ch.series:
        sr.marker.symbol = "none"
        sr.smooth = False
        sr.graphicalProperties.line.width = 12000
    ch.set_categories(Reference(ws_src, min_col=cats_col, min_row=first, max_row=last))
    ch.x_axis.number_format = "yyyy"
    ch.legend.position = "b"
    anchor_ws.add_chart(ch, anchor)


# --------------------------------------------------------------------------- électricité
def write_elec_semestriel(wb: Workbook, df: pd.DataFrame, has_ipc: bool = False) -> tuple[str, int]:
    ws = wb.create_sheet("Elec_semestriel")
    _headers(ws, 1, ["Semestre", "Début", "Hors toutes taxes = fourniture + réseau (c€/kWh)", "Hors TVA (c€/kWh)",
                     "TTC (c€/kWh)", "Taxes et contributions hors TVA (c€/kWh)", "TVA (c€/kWh)", "Statut Eurostat",
                     "Contrôle"], [10, 10, 16, 12, 11, 16, 11, 10, 9])
    for i, r in enumerate(df.itertuples(index=False), 2):
        p = r.periode
        _cell(ws, i, 1, f"{p.year}-S{1 if p.month == 1 else 2}")
        _cell(ws, i, 2, p, fmt="yyyy-mm")
        _cell(ws, i, 3, float(r.hors_taxes) if pd.notna(r.hors_taxes) else None, F_INPUT, "0.00")
        _cell(ws, i, 4, float(r.hors_tva) if pd.notna(r.hors_tva) else None, F_INPUT, "0.00")
        _cell(ws, i, 5, float(r.ttc) if pd.notna(r.ttc) else None, F_INPUT, "0.00")
        _cell(ws, i, 6, f"=D{i}-C{i}", F_FORMULA, "0.00")
        _cell(ws, i, 7, f"=E{i}-D{i}", F_FORMULA, "0.00")
        _cell(ws, i, 8, r.statut or None)
        _cell(ws, i, 9, f"=C{i}+F{i}+G{i}-E{i}", F_FORMULA, "0.00")
        if has_ipc:
            _cell(ws, i, 10, f'=IFERROR(E{i}*IPC!$E$3/INDEX(IPC!$B:$B,MATCH($B{i},IPC!$A:$A,0)),"")', F_FORMULA, "0.00")
    if has_ipc:
        _cell(ws, 1, 10, "TTC € constants (c€/kWh)", F_HDR).fill = HDR_FILL
        ws.column_dimensions["J"].width = 13
    return ws.title, 1 + len(df)


def write_elec_composantes(wb: Workbook, df: pd.DataFrame, labels: dict) -> tuple[str, int, list[int]]:
    ws = wb.create_sheet("Elec_composantes_annuel")
    comp_cols = [c for c in df.columns if c not in ("periode", "statut")]
    names = ["Année"] + [f"{c} – {labels.get(c, c)} (c€/kWh)" for c in comp_cols] + ["Statut", "Total hors allègements (c€/kWh)"]
    _headers(ws, 1, names, [8] + [15] * len(comp_cols) + [8, 14])
    for i, r in enumerate(df.itertuples(index=False), 2):
        _cell(ws, i, 1, int(r.periode.year), F_INPUT, "0")
        for j, c in enumerate(comp_cols, 2):
            v = getattr(r, c)
            _cell(ws, i, j, float(v) if pd.notna(v) else None, F_INPUT, "0.00")
        _cell(ws, i, len(comp_cols) + 2, r.statut or None)
        # total = NRG_SUP + NETC + TAX_FEE_LEV_CHRG (agrégat des taxes) + VAT si ces codes existent
        parts = [get_column_letter(comp_cols.index(k) + 2) for k in ("NRG_SUP", "NETC", "TAX_FEE_LEV_CHRG", "VAT") if k in comp_cols]
        _cell(ws, i, len(comp_cols) + 3, "=" + "+".join(f"{p}{i}" for p in parts) if parts else None, F_FORMULA, "0.00")
    chart_cols = [comp_cols.index(k) + 2 for k in ("NRG_SUP", "NETC", "TAX_FEE_LEV_CHRG", "VAT") if k in comp_cols]
    return ws.title, 1 + len(df), chart_cols


# --------------------------------------------------------------------------- IPC
def write_ipc(wb: Workbook, ipc: pd.DataFrame, ref: str | None) -> None:
    ws = wb.create_sheet("IPC")
    _headers(ws, 1, ["Mois", "IPC base 2015 = 100", "", "Paramètre", "Valeur"], [10, 14, 3, 30, 12])
    for i, r in enumerate(ipc.itertuples(index=False), 2):
        _cell(ws, i, 1, r.date, fmt="yyyy-mm")
        _cell(ws, i, 2, float(r.ipc_base2015), F_INPUT, "0.00")
    ref_ts = pd.Timestamp(ref + "-01") if ref else ipc.date.max()
    _cell(ws, 2, 4, "Mois de référence des euros constants (modifiable)")
    c = _cell(ws, 2, 5, ref_ts, F_INPUT, "yyyy-mm"); c.fill = NOTE_FILL
    _cell(ws, 3, 4, "IPC du mois de référence")
    _cell(ws, 3, 5, "=INDEX($B:$B,MATCH($E$2,$A:$A,0))", F_FORMULA, "0.00")
    _cell(ws, 5, 4, "Toutes les colonnes « € constants » du classeur = valeur courante × E3 / IPC(mois).")
    ws.freeze_panes = "A2"


# --------------------------------------------------------------------------- lisez-moi
def write_readme(wb: Workbook, b: Bundle):
    ws = wb.active
    ws.title = "Lisez-moi"
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 60
    ws.column_dimensions["C"].width = 70
    ws.column_dimensions["D"].width = 70
    r = 1
    _cell(ws, r, 1, "Prix de l'énergie en France – évolution et décomposition", F_TITLE); r += 2
    intro = [
        ("Périmètre", "Gazole, sans-plomb (SP95-E5 chaîné SP95-E10), électricité ménages (TRV et prix moyens), Brent, marge brute de raffinage."),
        ("Unités", "Carburants : c€/l. Électricité : c€/kWh. Brent : $/b et €/b. Marge de raffinage : $/b, €/t, c€/l. "
                   "Toutes les valeurs sources sont en euros COURANTS ; les colonnes « € constants » sont déflatées par "
                   "l'IPC INSEE (feuille IPC, mois de référence modifiable en E2)."),
        ("Composantes carburants", "TVA = TTC × t/(1+t) ; Accise = TTC − HT − TVA ; Transport-distribution = HT − cotation Rotterdam "
                                   "(définition DGEC). Quand la cotation manque, 'HT non décomposé' = HT (cotation + T-D)."),
        ("Composantes électricité", "Eurostat semestriel : hors toutes taxes (fourniture + réseau), taxes hors TVA, TVA. "
                                    "Eurostat annuel 2017→ : énergie et fourniture, réseau, taxes et contributions, TVA. "
                                    "CRE 2012→ : TRV Bleu HT/TTC pour la consommation de référence."),
        ("Indicateurs séparés", "Le Brent et la marge brute de raffinage ne s'additionnent pas aux prix ; ils sont présentés "
                                "dans des feuilles et graphiques distincts."),
        ("Choix méthodologiques", f"Début {b.choices.start} ; chaînage E5→E10 en {b.choices.sp_e10_chain} ; TRV {b.choices.trv_power_kva} kVA "
                                  f"option Base, {b.choices.trv_ref_kwh:.0f} kWh/an ; notes NPG lues : {b.choices.npg_weeks}."),
        ("Cellules", "Bleu = valeur source ; noir = formule. Les feuilles *_annuel se recalculent depuis les feuilles mensuelles."),
        ("Aucune valeur inventée", "Toute composante absente d'une source publique est laissée vide et listée dans les notes ci-dessous."),
    ]
    for k, v in intro:
        _cell(ws, r, 1, k, F_HDR)
        c = _cell(ws, r, 2, v)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
        ws.row_dimensions[r].height = 32
        r += 1
    r += 1
    src, notes = b.journal.to_frames()
    _cell(ws, r, 1, "Sources", F_TITLE); r += 1
    _headers(ws, r, ["Série", "Producteur", "URL", "Détail"]); ws.freeze_panes = None; r += 1
    for rec in src.itertuples(index=False):
        for j, v in enumerate(rec, 1):
            c = _cell(ws, r, j, v)
            c.alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    r += 1
    _cell(ws, r, 1, "Notes : ruptures, définitions, valeurs provisoires, composantes indisponibles", F_TITLE); r += 1
    _headers(ws, r, ["Type", "Série", "Message"]); ws.freeze_panes = None; r += 1
    for rec in notes.itertuples(index=False):
        for j, v in enumerate(rec, 1):
            c = _cell(ws, r, j, v)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            if rec.Type in ("INDISPONIBLE", "RUPTURE", "ERREUR"):
                c.fill = NOTE_FILL
        ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=4)
        ws.row_dimensions[r].height = 45
        r += 1


# --------------------------------------------------------------------------- assemblage
def write_workbook(b: Bundle, path: Path) -> Path:
    wb = Workbook()
    write_readme(wb, b)
    g = wb.create_sheet("Graphiques")
    anchor_row = 1

    # -- carburants
    has_ipc = b.ipc is not None
    if has_ipc:
        write_ipc(wb, b.ipc, b.choices.ipc_ref)
    for label, df, sheet, has_prod in (("Gazole", b.gazole, "Gazole", False),
                                       (f"Sans-plomb (SP95-E5 puis SP95-E10 dès {b.choices.sp_e10_chain})", b.sansplomb, "SansPlomb", True)):
        if df is None:
            continue
        ms = write_fuel_monthly(wb, f"{sheet}_mensuel", df, has_ipc)
        ann, last = write_fuel_annual(wb, f"{sheet}_annuel", ms, df, has_prod=has_prod)
        off = 1 if has_prod else 0
        nrow = 1 + len(df)
        _stacked_chart(wb[ann], f"{label} – décomposition TTC, moyennes annuelles (c€/l courants)", "c€/l", 1,
                       [4, 5, 6, 7, 8], 2, last, g, f"A{anchor_row}")
        anchor_row += 26
        _stacked_chart(wb[ms], f"{label} – décomposition TTC, mensuel (c€/l courants)", "c€/l", 1,
                       [c + off for c in FUEL_STACK_NOMINAL], 2, nrow, g, f"A{anchor_row}", gap=0, date_axis=True)
        anchor_row += 26
        if has_ipc:
            _stacked_chart(wb[ms], f"{label} – décomposition TTC, mensuel (c€/l constants, réf. feuille IPC)", "c€/l constants", 1,
                           [c + off for c in FUEL_STACK_CONSTANT], 2, nrow, g, f"A{anchor_row}", gap=0, date_axis=True)
            anchor_row += 26
    if b.sp_e10_dgec is not None:
        write_fuel_monthly(wb, "SP95E10_DGEC_mensuel", b.sp_e10_dgec, has_ipc)

    # -- électricité
    if b.elec_semestriel is not None:
        name, last = write_elec_semestriel(wb, b.elec_semestriel, has_ipc)
        _stacked_chart(wb[name], "Électricité ménages (Eurostat, bande 2 500–5 000 kWh) – décomposition TTC (c€/kWh)",
                       "c€/kWh", 1, [3, 6, 7], 2, last, g, f"A{anchor_row}")
        anchor_row += 26
    if b.elec_composantes is not None:
        name, last, cols = write_elec_composantes(wb, b.elec_composantes, b.elec_composantes_labels)
        if cols:
            _stacked_chart(wb[name], "Électricité ménages – composantes (Eurostat annuel, 2017→, c€/kWh)", "c€/kWh", 1,
                           cols, 2, last, g, f"A{anchor_row}")
            anchor_row += 26
    if b.elec_ancienne is not None:
        ws = wb.create_sheet("Elec_ancienne_1985_2007")
        df = b.elec_ancienne.copy()
        labels = df.attrs.get("labels", {})
        df.columns = [f"{c} – {labels.get(c, '')} (c€/kWh)" if c != "periode" else "Date" for c in df.columns]
        _write_df(ws, df)
    if b.trv is not None:
        ws = wb.create_sheet("TRV_CRE")
        df = b.trv.copy()
        df.insert(0, "Grille du", df.debut.dt.strftime("%Y-%m"))
        df = df.rename(columns={
            "debut": "Début", "fin": "Fin", "puissance_kva": "kVA", "fixe_ht_eur_an": "Part fixe HT (€/an)",
            "var_ht": "Part variable HT (c€/kWh)", "fixe_ttc_eur_an": "Part fixe TTC (€/an)",
            "var_ttc": "Part variable TTC (c€/kWh)", "prix_moyen_ht_ceur_kwh": f"Prix moyen HT {b.choices.trv_ref_kwh:.0f} kWh (c€/kWh)",
            "prix_moyen_ttc_ceur_kwh": f"Prix moyen TTC {b.choices.trv_ref_kwh:.0f} kWh (c€/kWh)",
            "taxes_et_tva_ceur_kwh": "Taxes + TVA (c€/kWh)"})
        last = _write_df(ws, df, date_fmt="yyyy-mm-dd")
        _stacked_chart(ws, f"TRV Bleu Base {b.choices.trv_power_kva} kVA (CRE) – HT vs taxes+TVA, {b.choices.trv_ref_kwh:.0f} kWh/an",
                       "c€/kWh", 1, [9, 11], 2, last, g, f"A{anchor_row}")
        anchor_row += 26

    # -- indicateurs séparés
    if b.brent is not None:
        ws = wb.create_sheet("Brent_mensuel")
        df = b.brent.rename(columns={"date": "Mois", "brent_usd_bbl": f"Brent ($/b) – {b.brent_source}",
                                     "brent_eur_bbl": "Brent (€/b courants)", "brent_usd_bbl_dgec": "Brent daté ($/b) – DGEC (contrôle)"})
        last = _write_df(ws, df)
        series = [2]
        if "Brent (€/b courants)" in df.columns:
            ce = list(df.columns).index("Brent (€/b courants)") + 1
            series.append(ce)
            if has_ipc:
                k = len(df.columns) + 1
                _cell(ws, 1, k, "Brent (€/b constants)", F_HDR).fill = HDR_FILL
                ws.column_dimensions[get_column_letter(k)].width = 16
                E = get_column_letter(ce)
                for i in range(2, last + 1):
                    _cell(ws, i, k, f'=IFERROR({E}{i}*IPC!$E$3/INDEX(IPC!$B:$B,MATCH($A{i},IPC!$A:$A,0)),"")', F_FORMULA, "0.00")
                series.append(k)
        _line_chart(ws, f"Brent – moyennes mensuelles – source : {b.brent_source}", "par baril", 1, series, 2, last, g, f"A{anchor_row}")
        anchor_row += 22
    if b.marge is not None:
        ws = wb.create_sheet("Marge_raffinage")
        df = b.marge.rename(columns={"date": "Mois", "marge_usd_bbl": "Marge ($/b)", "marge_eur_t": "Marge (€/t)", "marge_ceur_l": "Marge (c€/l)"})
        last = _write_df(ws, df)
        ycol = next((i + 1 for i, c in enumerate(df.columns) if "$/b" in str(c)), 2)
        _line_chart(ws, "Marge brute de raffinage sur Brent (DGEC, mensuel, 2015→)", str(df.columns[ycol - 1]), 1, [ycol], 2, last, g, f"A{anchor_row}")
        anchor_row += 22
    if b.td_annuel is not None:
        ws = wb.create_sheet("TD_annuel_DGEC")
        df = b.td_annuel.rename(columns={"annee": "Année", "td_gazole": "T-D gazole (c€/l)", "td_sp95_e5": "T-D SP95-E5 (c€/l)", "td_sp95_e10": "T-D SP95-E10 (c€/l)"})
        last = _write_df(ws, df)
        # cotation annuelle déduite = HT annuel (feuille Gazole_annuel) − T-D
        if "T-D gazole (c€/l)" in df.columns and "Gazole_annuel" in wb.sheetnames:
            col_td = list(df.columns).index("T-D gazole (c€/l)") + 1
            k = len(df.columns) + 1
            _cell(ws, 1, k, "Cotation gazole déduite = HT annuel (WOB) − T-D (c€/l)", F_HDR).fill = HDR_FILL
            for i in range(2, last + 1):
                _cell(ws, i, k, f'=IFERROR(INDEX(Gazole_annuel!$J:$J,MATCH($A{i},Gazole_annuel!$A:$A,0))-{get_column_letter(col_td)}{i},"")',
                      F_FORMULA, "0.00")
            ws.column_dimensions[get_column_letter(k)].width = 26
    if b.cotations is not None:
        ws = wb.create_sheet("Cotations_NPG")
        df = b.cotations.rename(columns={"produit": "Produit", "mois": "Mois", "cotation_ceur_l": "Cotation Rotterdam (c€/l)",
                                          "provisoire": "Provisoire", "note": "Note DGEC du"})
        _write_df(ws, df, date_fmt="yyyy-mm")
    if b.wob_weekly is not None:
        ws = wb.create_sheet("Brut_WOB_hebdo")
        _write_df(ws, b.wob_weekly.rename(columns={"date": "Semaine (lundi)"}), date_fmt="yyyy-mm-dd")

    # ordre : Lisez-moi, Graphiques, puis le reste
    wb.move_sheet("Graphiques", offset=-(wb.sheetnames.index("Graphiques") - 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
