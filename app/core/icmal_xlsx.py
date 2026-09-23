"""Builds the İcmal hakediş Excel report from the ataşman records accumulated
in db.py for one hakediş period, replicating the structure of the real
municipal reference file (İCMAL MG 4 Nolu Hakediş.xlsx): the same eight
material-item column groups (Tanım-1..8, each with a MİKTAR/BİRİM pair) plus
a GPS Alımı (ilk/son alım) group, one row per ataşman, and METRAJ / BİRİM
FİYAT / TUTAR summary rows at the bottom.

Validated against the real file: its own row for the Akabe 4/45 ataşman
(Tanım-5=15.39, Tanım-7=68.36) matches this pipeline's computed totals for
that exact job exactly.

"ilk Alım" (GPS Alımı) is left blank -- per the user, it's a separate,
manually-entered pre-work estimate, not something derivable from the as-built
survey data this system works from. "Son Alım" is filled with the same
Tanım-6 + Tanım-7 formula the real file uses.
"""
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import column_index_from_string, get_column_letter

# (T-code, "Tanım-N" label, description text, unit) -- description text and
# column order match the real reference file's own row 4.
ITEM_DEFS = [
    ('T1', 'Tanım-1', '4 cm Kalınlıkta Andezit Döşeme Yapımı (Malzeme Dahil)', 'm²'),
    ('T2', 'Tanım-2', '6 cm Kalınlıkta Andezit Döşeme Yapımı (Malzeme Dahil)', 'm²'),
    ('T3', 'Tanım-3', 'Küp granit kaplama döşenmesi (Malzeme Dahil)', 'm²'),
    ('T4', 'Tanım-4', 'Her Renk Beton Bordür Taşı Nakli ve Döşenmesi (Bordür Taşı İdareden)', 'm'),
    ('T5', 'Tanım-5', 'Her Renk Beton Bordür Taşı Döşenmesi (Yerindeki Malzemenin Döşenmesi)', 'm'),
    ('T6', 'Tanım-6', 'Her Renk Beton Parke Taşı Nakli ve Döşenmesi (Parke Taşı İdareden)', 'm²'),
    ('T7', 'Tanım-7', 'Her Renk Beton Parke Taşı Döşenmesi (Yerindeki Malzemenin Döşenmesi)', 'm²'),
    ('T8', 'Tanım-8', 'Her Renk Beton Oluk Taşı Temini, Nakli ve Döşenmesi (Malzeme Dahil)', 'm'),
]
ITEM_COLS = ['G', 'I', 'K', 'M', 'O', 'Q', 'S', 'U']  # miktar column of each pair

BOLD = Font(bold=True)
THIN = Side(style='thin')
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)


def _next_col(col, n=1):
    return get_column_letter(column_index_from_string(col) + n)


def build_icmal_workbook(hakedis_no, records, unit_prices):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Sayfa1'

    ws['E1'] = 'KARATAY BELEDİYESİ'
    ws['E1'].font = Font(bold=True, size=12)
    ws['E3'] = f'{hakedis_no} NOLU HAKEDİŞ'
    ws['E3'].font = Font(bold=True, size=12)

    header_row = 5
    for col, label in [('A', 'SIRA NO'), ('B', 'KROKİ NO'), ('C', 'PROJE NO'),
                        ('D', 'MAHALLE'), ('E', 'CADDE & SOKAK'), ('F', 'NO')]:
        c = ws[f'{col}{header_row}']
        c.value = label
        c.font = BOLD
        c.alignment = CENTER
        c.border = BOX

    for (key, tanim_label, aciklama, birim), col in zip(ITEM_DEFS, ITEM_COLS):
        col2 = _next_col(col)
        ws[f'{col}3'] = tanim_label
        ws[f'{col}3'].font = BOLD
        ws[f'{col}3'].alignment = CENTER
        ws.merge_cells(f'{col}3:{col2}3')
        ws[f'{col}4'] = aciklama
        ws[f'{col}4'].alignment = CENTER
        ws[f'{col}4'].font = Font(size=8)
        ws.merge_cells(f'{col}4:{col2}4')
        for cc, label in ((f'{col}{header_row}', 'MİKTAR'), (f'{col2}{header_row}', 'BİRİM')):
            ws[cc] = label
            ws[cc].font = BOLD
            ws[cc].alignment = CENTER
            ws[cc].border = BOX

    ws['W3'] = 'GPS Alımı'
    ws.merge_cells('W3:Z3')
    ws['W3'].font = BOLD
    ws['W3'].alignment = CENTER
    ws['W4'] = 'ilk Alım'
    ws.merge_cells('W4:X4')
    ws['W4'].alignment = CENTER
    ws['Y4'] = 'Son Alım'
    ws.merge_cells('Y4:Z4')
    ws['Y4'].alignment = CENTER
    for col, label in [('W', 'MİKTAR'), ('X', 'BİRİM'), ('Y', 'MİKTAR'), ('Z', 'BİRİM')]:
        c = ws[f'{col}{header_row}']
        c.value = label
        c.font = BOLD
        c.alignment = CENTER
        c.border = BOX

    all_border_cols = (['A', 'B', 'C', 'D', 'E', 'F']
                        + [c for pair in ITEM_COLS for c in (pair, _next_col(pair))]
                        + ['W', 'X', 'Y', 'Z'])

    data_start = header_row + 1
    r = data_start
    for i, rec in enumerate(records, start=1):
        ws[f'A{r}'] = i
        ws[f'B{r}'] = f"{rec['hakedis_no']}/{rec['sira_no']}"
        ws[f'C{r}'] = rec.get('aykome_no') or ''
        ws[f'D{r}'] = (rec.get('mahalle') or '').upper()
        ws[f'E{r}'] = (rec.get('cadde_sokak') or '').upper()
        ws[f'F{r}'] = rec.get('kapi_no') or ''
        for (key, _, _, birim), col in zip(ITEM_DEFS, ITEM_COLS):
            col2 = _next_col(col)
            val = rec.get(key.lower(), 0) or 0
            ws[f'{col}{r}'] = round(val, 2) if val else None
            ws[f'{col2}{r}'] = birim
        ws[f'Y{r}'] = f'=Q{r}+S{r}'
        ws[f'Z{r}'] = 'm²'
        for col in all_border_cols:
            ws[f'{col}{r}'].border = BOX
        r += 1

    data_end = r - 1
    metraj_row, fiyat_row, tutar_row = r + 1, r + 2, r + 3

    ws[f'F{metraj_row}'] = 'METRAJ'
    ws[f'F{metraj_row}'].font = BOLD
    ws[f'F{fiyat_row}'] = 'BİRİM FİYAT (TL)'
    ws[f'F{fiyat_row}'].font = BOLD
    ws[f'F{tutar_row}'] = 'TUTAR (TL)'
    ws[f'F{tutar_row}'].font = BOLD

    tutar_cells = []
    for (key, _, _, birim), col in zip(ITEM_DEFS, ITEM_COLS):
        col2 = _next_col(col)
        if data_end >= data_start:
            ws[f'{col}{metraj_row}'] = f'=SUM({col}{data_start}:{col}{data_end})'
        else:
            ws[f'{col}{metraj_row}'] = 0
        ws[f'{col}{metraj_row}'].font = BOLD
        ws[f'{col2}{metraj_row}'] = birim
        ws[f'{col}{fiyat_row}'] = unit_prices.get(key, 0)
        ws[f'{col2}{fiyat_row}'] = 'TL'
        ws[f'{col}{tutar_row}'] = f'={col}{fiyat_row}*{col}{metraj_row}'
        ws[f'{col}{tutar_row}'].font = BOLD
        ws[f'{col2}{tutar_row}'] = 'TL'
        tutar_cells.append(f'{col}{tutar_row}')

    ws[f'X{tutar_row}'] = 'GENEL TOPLAM'
    ws[f'X{tutar_row}'].font = BOLD
    ws[f'Y{tutar_row}'] = f"=SUM({','.join(tutar_cells)})"
    ws[f'Y{tutar_row}'].font = Font(bold=True, size=12)

    for col, w in {'A': 6, 'B': 9, 'C': 9, 'D': 12, 'E': 18, 'F': 8}.items():
        ws.column_dimensions[col].width = w
    for col in [c for pair in ITEM_COLS for c in (pair, _next_col(pair))] + ['W', 'X', 'Y', 'Z']:
        ws.column_dimensions[col].width = 9

    ws.freeze_panes = f'A{data_start}'
    return wb
