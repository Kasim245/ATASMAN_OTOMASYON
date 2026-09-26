"""Builds the İcmal hakediş Excel report from the ataşman records accumulated
in db.py for one hakediş period.

Faz 1.21: rewritten to be a structural/visual replica of the real company
İcmal file (kullanıcının yüklediği "İCMAL MG 5 Nolu Hakediş.xlsx" referans
dosyası) -- önceki sürüm sadece kavramsal olarak benziyordu (aynı Tanım-1..8
kolon eşlemesi, aynı GPS Alımı mantığı) ama başlık bloğu, hücre boyutları,
fontlar, birleştirilmiş hücreler ve alt toplam satırları referans dosyadan
belirgin şekilde farklıydı ("BU BİZİM YAPTIĞIMIZ İCMAL BİZİM İNDİRDİĞİMİZ
YAZILIMIN VERDİĞİ İLE ALAKASI YOK" -- kullanıcı geri bildirimi). Bu sürümde
referans dosya openpyxl ile hücre hücre incelenip (sütun genişlikleri, satır
yükseklikleri, birleştirilmiş hücre aralıkları, font/boyut/kalınlık, border
stilleri, sayı biçimleri, sayfa/print ayarları) buradaki sabitler doğrudan o
ölçümlerden alınmıştır:

  - Başlık bloğu artık tam genişlikte (A:Z birleşik) "T.C. / KARATAY
    BELEDİYESİ / FEN İŞLERİ MÜDÜRLÜĞÜ" satırı + "İhale Kayıt No" / "SAYFA
    NO:N" satırı + "Hakkediş No" / "<N> NOLU HAKEDİŞ" / Tanım-1..8 / GPS Alımı
    satırından oluşuyor (referans dosyadaki satır 1-5 bloğunun birebir aynısı).
  - Sütun genişlikleri ve başlık satırlarının yükseklikleri referans dosyadan
    ölçülen değerlerle birebir aynı (bkz. _COLUMN_WIDTHS, _HEADER_ROW_HEIGHTS).
  - Referans dosyada olduğu gibi bu başlık bloğu her 50 veri satırında bir
    (bir sonraki "sayfa"nın başında) "SAYFA NO:2", "SAYFA NO:3" ... diye
    artan sayfa numarasıyla tekrar ediliyor -- referans dosyadaki 103 satırlık
    örnekte tam olarak bu düzen (1-5 başlık, 6-55 veri, 56-60 başlık tekrarı,
    61-113 veri) görülüyor.
  - Alt toplam bloğu (METRAJ / birim fiyat / TUTAR) etiketleri ve TUTAR
    satırındaki "₺" biçimli genel toplam formülü referans dosyadaki gibi.
  - Sayfa/print ayarları (yatay, A4, Y/Z "Son Alım" kolonları print area
    dışında) referans dosyadan alındı.

"ilk Alım" (GPS Alımı) daha önceden belirlendiği gibi boş bırakılıyor -- bu
sahadan ölçülen bir veri değil, ayrı ve elle girilen bir ön tahmin ("Son
Alım" ise referans dosyadaki gibi Tanım-6 + Tanım-7 toplamı formülüyle
dolduruluyor).
"""
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import column_index_from_string, get_column_letter

FONT_NAME = 'Arial'

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

IDENTITY_COLS = [
    ('A', 'SIRA\nNO'), ('B', 'KROKİ\nNO'), ('C', 'PROJE\nNO'),
    ('D', 'MAHALLE'), ('E', 'CADDE\n&\nSOKAK'), ('F', 'NO'),
]

# Referans dosyadan ölçülen tam sütun genişlikleri (69e7d10d-_CMAL_MG_5_...xlsx).
_COLUMN_WIDTHS = {
    'A': 5.14, 'B': 6.57, 'C': 19.57, 'D': 17.43, 'E': 27.86, 'F': 8.0,
    'G': 9.57, 'H': 5.29, 'I': 11.71, 'J': 4.0, 'K': 11.71, 'L': 4.0,
    'M': 16.0, 'N': 4.0, 'O': 15.57, 'P': 4.29, 'Q': 14.86, 'R': 4.86,
    'S': 16.71, 'T': 5.71, 'U': 12.71, 'V': 4.0, 'W': 7.0, 'X': 4.0,
    'Y': 13.43, 'Z': 3.71,
}
# Referans dosyadaki 5 satırlık başlık bloğunun satır yükseklikleri
# (başlık, ihale/sayfa no, hakkediş/tanım, kimlik+açıklama, miktar/birim).
_HEADER_ROW_HEIGHTS = [43.5, 17.25, 17.25, 83.25, 15.0]
_DATA_ROW_HEIGHT = 15.0
_DATA_ROWS_PER_PAGE = 50  # referans dosyadaki tekrar aralığı

FONT_TITLE = Font(name=FONT_NAME, size=11, bold=True)
FONT_LABEL = Font(name=FONT_NAME, size=10, bold=True)        # İhale/Hakkediş No etiketleri + değerleri
FONT_SAYFANO = Font(name=FONT_NAME, size=10, bold=False)     # "SAYFA NO:N"
FONT_TANIM = Font(name=FONT_NAME, size=9, bold=False)        # "Tanım-N"
FONT_GPS_GROUP = Font(name=FONT_NAME, size=11, bold=True)    # "GPS Alımı" / "ilk Alım" / "Son Alım"
FONT_IDENTITY_LABEL = Font(name=FONT_NAME, size=9, bold=True)   # SIRA NO / KROKİ NO / ... / NO
FONT_ACIKLAMA = Font(name=FONT_NAME, size=9, bold=False)     # malzeme açıklama metni
FONT_MIKTAR_BIRIM = Font(name=FONT_NAME, size=8, bold=True)  # MİKTAR / BR. alt etiketleri
FONT_DATA = Font(name=FONT_NAME, size=8, bold=False)
FONT_SUMMARY_LABEL = Font(name=FONT_NAME, size=9, bold=False)
FONT_GRAND_TOTAL = Font(name=FONT_NAME, size=9, bold=False)

CENTER_WRAP = Alignment(horizontal='center', vertical='center', wrap_text=True)
RIGHT_WRAP = Alignment(horizontal='right', vertical='center', wrap_text=True)
CENTER_NOWRAP = Alignment(horizontal='center', vertical='center')

THIN = Side(style='thin')
MEDIUM = Side(style='medium')
THICK = Side(style='thick')

BORDER_TITLE = Border(bottom=MEDIUM)
BORDER_LABEL_LEFT = Border(left=MEDIUM, right=THIN, top=MEDIUM, bottom=THIN)
BORDER_LABEL_RIGHT = Border(left=THIN, right=MEDIUM, top=THIN, bottom=MEDIUM)
BORDER_SAYFANO = Border(left=MEDIUM, right=None, top=MEDIUM, bottom=None)
BORDER_TANIM_BOX = Border(left=MEDIUM, right=MEDIUM, top=MEDIUM, bottom=MEDIUM)
BORDER_MIKTAR_BIRIM = Border(left=THIN, right=THIN, top=MEDIUM, bottom=MEDIUM)
BORDER_GPS_OUTER_LEFT = Border(left=THICK, right=THICK, top=THICK, bottom=MEDIUM)
BORDER_GPS_INNER = Border(left=THICK, right=MEDIUM, top=MEDIUM, bottom=MEDIUM)
BORDER_DATA = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

NUM_FMT_MIKTAR = '0.00'
NUM_FMT_PARA = '#,##0.00'
NUM_FMT_TOPLAM = '#,##0.00\\ "₺"'


def _next_col(col, n=1):
    return get_column_letter(column_index_from_string(col) + n)


def _page_sizes(n, page_size=_DATA_ROWS_PER_PAGE, min_tail=5):
    """Kaç sayfa başlığı tekrar edeceğini ve her sayfaya kaç veri satırı
    düşeceğini belirler. Referans dosyada 103 kayıt TAM 50'şerli değil,
    50 + 53 olarak bölünmüştü (2. sayfa kalanı yutmuş, üçüncü küçük bir
    başlık bloğu için ayrı sayfa açılmamıştı). Bu yüzden basit "her 50'de
    bir böl" yerine: kalan, bir sonraki sayfayı `min_tail`'den az satıkla
    bitirecekse (örn. 103 -> 50 + 53), onu yeni bir sayfa açmak yerine
    mevcut sayfaya ekliyoruz -- 103 kayıtlık örnekte referans dosyadaki
    birebir aynı 50+53 bölünmesini üretir."""
    if n <= 0:
        return []
    pages = []
    remaining = n
    while remaining > page_size:
        if remaining - page_size <= min_tail:
            pages.append(remaining)
            remaining = 0
            break
        pages.append(page_size)
        remaining -= page_size
    if remaining > 0:
        pages.append(remaining)
    return pages


def _write_page_header(ws, top_row, hakedis_no, sayfa_no):
    """Referans dosyadaki 5 satırlık başlık bloğunu `top_row`'dan başlayarak
    yazar (sayfa 1 için top_row=1, sayfa 2 için top_row=56, sayfa 3 için
    top_row=111, ...). Sayfa numarası arttıkça sadece "SAYFA NO:N" değişir,
    geri kalan her şey birebir aynı tekrar eder."""
    r1, r2, r3, r4, r5 = top_row, top_row + 1, top_row + 2, top_row + 3, top_row + 4

    for i, h in enumerate(_HEADER_ROW_HEIGHTS):
        ws.row_dimensions[top_row + i].height = h

    # --- Satır 1: tam genişlik kurum başlığı ---
    ws.merge_cells(f'A{r1}:Z{r1}')
    c = ws[f'A{r1}']
    c.value = 'T.C.\nKARATAY BELEDİYESİ\nFEN İŞLERİ MÜDÜRLÜĞÜ'
    c.font = FONT_TITLE
    c.alignment = CENTER_WRAP
    c.border = BORDER_TITLE

    # --- Satır 2: İhale Kayıt No | (değer) | SAYFA NO:N ---
    ws.merge_cells(f'A{r2}:D{r2}')
    ws[f'A{r2}'] = 'İhale Kayıt No'
    ws[f'A{r2}'].font = FONT_LABEL
    ws[f'A{r2}'].alignment = CENTER_WRAP
    ws[f'A{r2}'].border = BORDER_LABEL_LEFT
    ws.merge_cells(f'E{r2}:F{r2}')
    ws[f'E{r2}'].border = BORDER_LABEL_RIGHT
    ws.merge_cells(f'G{r2}:Z{r2}')
    ws[f'G{r2}'] = f'SAYFA NO:{sayfa_no}'
    ws[f'G{r2}'].font = FONT_SAYFANO
    ws[f'G{r2}'].alignment = RIGHT_WRAP
    ws[f'G{r2}'].border = BORDER_SAYFANO

    # --- Satır 3: Hakkediş No | <N> NOLU HAKEDİŞ | Tanım-1..8 | GPS Alımı ---
    ws.merge_cells(f'A{r3}:D{r3}')
    ws[f'A{r3}'] = 'Hakkediş No'
    ws[f'A{r3}'].font = FONT_LABEL
    ws[f'A{r3}'].alignment = CENTER_WRAP
    ws[f'A{r3}'].border = BORDER_LABEL_LEFT
    ws.merge_cells(f'E{r3}:F{r3}')
    ws[f'E{r3}'] = f'{hakedis_no} NOLU HAKEDİŞ'
    ws[f'E{r3}'].font = FONT_LABEL
    ws[f'E{r3}'].alignment = CENTER_WRAP
    ws[f'E{r3}'].border = BORDER_LABEL_RIGHT
    for (_, tanim_label, _, _), col in zip(ITEM_DEFS, ITEM_COLS):
        col2 = _next_col(col)
        ws.merge_cells(f'{col}{r3}:{col2}{r3}')
        ws[f'{col}{r3}'] = tanim_label
        ws[f'{col}{r3}'].font = FONT_TANIM
        ws[f'{col}{r3}'].alignment = CENTER_WRAP
        ws[f'{col}{r3}'].border = BORDER_TANIM_BOX
        ws[f'{col2}{r3}'].border = BORDER_TANIM_BOX
    ws.merge_cells(f'W{r3}:Z{r3}')
    ws[f'W{r3}'] = 'GPS Alımı'
    ws[f'W{r3}'].font = FONT_GPS_GROUP
    ws[f'W{r3}'].alignment = CENTER_WRAP
    ws[f'W{r3}'].border = BORDER_GPS_OUTER_LEFT

    # --- Satır 4-5: kimlik kolonları (dikey birleşik) + malzeme açıklaması / MİKTAR-BR ---
    for col, label in IDENTITY_COLS:
        ws.merge_cells(f'{col}{r4}:{col}{r5}')
        c = ws[f'{col}{r4}']
        c.value = label
        c.font = FONT_IDENTITY_LABEL
        c.alignment = CENTER_WRAP
        c.border = BORDER_TANIM_BOX
        ws[f'{col}{r5}'].border = BORDER_TANIM_BOX

    for (_, _, aciklama, _), col in zip(ITEM_DEFS, ITEM_COLS):
        col2 = _next_col(col)
        ws.merge_cells(f'{col}{r4}:{col2}{r4}')
        ws[f'{col}{r4}'] = aciklama
        ws[f'{col}{r4}'].font = FONT_ACIKLAMA
        ws[f'{col}{r4}'].alignment = CENTER_WRAP
        ws[f'{col}{r4}'].border = BORDER_TANIM_BOX
        ws[f'{col2}{r4}'].border = BORDER_TANIM_BOX
        for cc, label in ((f'{col}{r5}', 'MİKTAR'), (f'{col2}{r5}', 'BR.')):
            ws[cc] = label
            ws[cc].font = FONT_MIKTAR_BIRIM
            ws[cc].alignment = CENTER_WRAP
            ws[cc].border = BORDER_MIKTAR_BIRIM

    ws.merge_cells(f'W{r4}:X{r4}')
    ws[f'W{r4}'] = 'ilk Alım'
    ws[f'W{r4}'].font = FONT_GPS_GROUP
    ws[f'W{r4}'].alignment = CENTER_WRAP
    ws[f'W{r4}'].border = BORDER_GPS_INNER
    ws[f'X{r4}'].border = BORDER_TANIM_BOX
    ws.merge_cells(f'Y{r4}:Z{r4}')
    ws[f'Y{r4}'] = 'Son Alım '
    ws[f'Y{r4}'].font = FONT_GPS_GROUP
    ws[f'Y{r4}'].alignment = CENTER_WRAP
    ws[f'Y{r4}'].border = BORDER_TANIM_BOX
    ws[f'Z{r4}'].border = BORDER_TANIM_BOX
    for col, label in [('W', 'MİKTAR'), ('X', 'BR.'), ('Y', 'MİKTAR'), ('Z', 'BR.')]:
        c = ws[f'{col}{r5}']
        c.value = label
        c.font = FONT_MIKTAR_BIRIM
        c.alignment = CENTER_WRAP
        c.border = BORDER_MIKTAR_BIRIM

    return r5  # bu bloktan sonraki ilk veri satırının bir öncesi


def build_icmal_workbook(hakedis_no, records, unit_prices):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Sayfa1'

    for col, w in _COLUMN_WIDTHS.items():
        ws.column_dimensions[col].width = w

    all_data_cols = (['A', 'B', 'C', 'D', 'E', 'F']
                      + [c for pair in ITEM_COLS for c in (pair, _next_col(pair))]
                      + ['W', 'X', 'Y', 'Z'])

    page_sizes = _page_sizes(len(records))

    top_row = 1
    sayfa_no = 1
    last_header_r5 = _write_page_header(ws, top_row, hakedis_no, sayfa_no)
    r = last_header_r5 + 1
    data_start = r
    kalan_bu_sayfada = page_sizes[0] if page_sizes else 0
    # METRAJ formülleri sayfa başlıklarının arasındaki metin hücrelerini
    # (SAYFA NO, Tanım-N, açıklama vb.) atlayıp SADECE gerçek veri
    # satırlarını toplasın diye her "sayfa"nın veri aralığı ayrı tutuluyor.
    data_segments = []  # [(seg_start, seg_end), ...]
    seg_start = r

    for i, rec in enumerate(records, start=1):
        if kalan_bu_sayfada == 0:
            data_segments.append((seg_start, r - 1))
            top_row = r + 1
            sayfa_no += 1
            last_header_r5 = _write_page_header(ws, top_row, hakedis_no, sayfa_no)
            r = last_header_r5 + 1
            seg_start = r
            kalan_bu_sayfada = page_sizes[sayfa_no - 1]

        ws.row_dimensions[r].height = _DATA_ROW_HEIGHT
        ws[f'A{r}'] = i
        ws[f'B{r}'] = f"{rec['hakedis_no']}/{rec['sira_no']}"
        ws[f'C{r}'] = rec.get('aykome_no') or 'KBF'
        ws[f'D{r}'] = (rec.get('mahalle') or '').upper()
        ws[f'E{r}'] = (rec.get('cadde_sokak') or '').upper()
        ws[f'F{r}'] = rec.get('kapi_no') or ''
        for (key, _, _, birim), col in zip(ITEM_DEFS, ITEM_COLS):
            col2 = _next_col(col)
            val = rec.get(key.lower(), 0) or 0
            # Referans dosyada bir kaleme uygulanmayan (0) satırlar boş değil,
            # literal "0.00" olarak yazılıyor -- bkz. gerçek dosyadaki 5/1
            # satırı (Tanım-1..5 hepsi "0.00", sadece Tanım-6/7 dolu).
            ws[f'{col}{r}'] = round(val, 2)
            ws[f'{col}{r}'].number_format = NUM_FMT_MIKTAR
            ws[f'{col2}{r}'] = birim
        # ilk Alım (GPS) boş bırakılıyor -- bkz. modül docstring.
        ws[f'X{r}'] = 'm²'
        ws[f'Y{r}'] = f'=Q{r}+S{r}'
        ws[f'Z{r}'] = 'm²'
        for col in all_data_cols:
            c = ws[f'{col}{r}']
            c.font = FONT_DATA
            c.alignment = CENTER_WRAP
            c.border = BORDER_DATA
        r += 1
        kalan_bu_sayfada -= 1

    data_end = r - 1
    if data_end >= seg_start:
        data_segments.append((seg_start, data_end))

    # Alt toplam bloğu için bir boşluk satırı bırakılıyor (referans dosyada
    # veri ile METRAJ satırı arasında boş/rezerv satırlar var).
    metraj_row, fiyat_row, tutar_row = r + 2, r + 3, r + 4

    ws[f'F{metraj_row}'] = 'METRAJ'
    ws[f'F{metraj_row}'].font = FONT_SUMMARY_LABEL
    ws[f'F{metraj_row}'].alignment = CENTER_NOWRAP
    ws[f'F{fiyat_row}'] = 'birim fiyat'
    ws[f'F{fiyat_row}'].font = FONT_SUMMARY_LABEL
    ws[f'F{fiyat_row}'].alignment = CENTER_NOWRAP
    ws[f'F{tutar_row}'] = 'TUTAR'
    ws[f'F{tutar_row}'].font = FONT_SUMMARY_LABEL
    ws[f'F{tutar_row}'].alignment = CENTER_NOWRAP

    tutar_cells = []
    for (key, _, _, birim), col in zip(ITEM_DEFS, ITEM_COLS):
        col2 = _next_col(col)
        if data_segments:
            ranges = ','.join(f'{col}{s}:{col}{e}' for s, e in data_segments)
            ws[f'{col}{metraj_row}'] = f'=SUM({ranges})'
        else:
            ws[f'{col}{metraj_row}'] = 0
        ws[f'{col}{metraj_row}'].font = FONT_SUMMARY_LABEL
        ws[f'{col}{metraj_row}'].alignment = CENTER_NOWRAP
        ws[f'{col2}{metraj_row}'] = birim
        ws[f'{col2}{metraj_row}'].font = FONT_SUMMARY_LABEL
        ws[f'{col2}{metraj_row}'].alignment = CENTER_NOWRAP

        ws[f'{col}{fiyat_row}'] = unit_prices.get(key, 0)
        ws[f'{col}{fiyat_row}'].number_format = NUM_FMT_PARA
        ws[f'{col}{fiyat_row}'].font = FONT_SUMMARY_LABEL
        ws[f'{col}{fiyat_row}'].alignment = CENTER_NOWRAP
        ws[f'{col2}{fiyat_row}'] = 'TL'
        ws[f'{col2}{fiyat_row}'].font = FONT_SUMMARY_LABEL
        ws[f'{col2}{fiyat_row}'].alignment = CENTER_NOWRAP

        ws[f'{col}{tutar_row}'] = f'={col}{fiyat_row}*{col}{metraj_row}'
        ws[f'{col}{tutar_row}'].number_format = NUM_FMT_PARA
        ws[f'{col}{tutar_row}'].font = FONT_SUMMARY_LABEL
        ws[f'{col}{tutar_row}'].alignment = CENTER_NOWRAP
        ws[f'{col2}{tutar_row}'] = 'TL'
        ws[f'{col2}{tutar_row}'].font = FONT_SUMMARY_LABEL
        ws[f'{col2}{tutar_row}'].alignment = CENTER_NOWRAP
        tutar_cells.append(f'{col}{tutar_row}')

    ws[f'Y{tutar_row}'] = f"=SUM({','.join(tutar_cells)})"
    ws[f'Y{tutar_row}'].font = FONT_GRAND_TOTAL
    ws[f'Y{tutar_row}'].number_format = NUM_FMT_TOPLAM

    # Referans dosyadaki gibi: yatay A4, "Son Alım" (Y/Z) kolonları print
    # area dışında, tek bir sayfa kırılması veri ile ilk başlık tekrarı
    # arasına denk geliyor (openpyxl otomatik sayfalar; burada elle bir
    # kırılma eklemeye gerek yok çünkü başlık bloğu zaten kendi satırlarını
    # yeniden yazıyor).
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    # Referans dosyada %56 küçültme ile bütün 8 Tanım grubu (+ ilk Alım)
    # yatay A4 sayfa genişliğine sığdırılmış (fitToPage=True, scale=56) --
    # bu olmadan sayfa yatayda bölünüp Tanım grupları ayrı sayfalara düşüyor.
    ws.page_setup.fitToPage = True
    ws.page_setup.scale = 56
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f'A1:X{tutar_row}'

    ws.freeze_panes = f'A{data_start}'
    return wb
