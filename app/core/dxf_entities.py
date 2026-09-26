"""Builders for the handful of new DXF entities this pipeline writes.

Everything is a plain, self-contained entity (LWPOLYLINE, LINE, TEXT) --
old-style POLYLINE/VERTEX/SEQEND is deliberately avoided for anything we
generate ourselves: its owner-handle chain (VERTEX (330) must point at its
*own* parent POLYLINE's new handle, not modelspace) silently drops vertices
in NetCAD if it's wrong, and LWPOLYLINE has no such chain to get wrong.
"""
from .dxf_io import fmt


def lwpolyline_entity(layer, verts_xy, handles, closed=True):
    """closed=True (default): kapalı parke parçası poligonu (70=1). Bordür/
    oluk zincirleri (Issue #4, bkz. survey.py::merge_bordur_chains) AÇIK bir
    hat -- closed=False (70=0) -- olarak çizilir, tıpkı önceki tek tek LINE
    parçalarının uçtan uca birleşmiş hali gibi, ama artık tek bir sürekli
    varlık olarak."""
    ent = [(0, 'LWPOLYLINE'), (5, handles.next()), (330, '1F'), (100, 'AcDbEntity'),
           (8, layer), (100, 'AcDbPolyline'), (90, str(len(verts_xy))),
           (70, '1' if closed else '0'), (43, '0.0')]
    for x, y in verts_xy:
        ent.append((10, fmt(x)))
        ent.append((20, fmt(y)))
    return ent


def line_entity(layer, p1, p2, handles):
    return [(0, 'LINE'), (5, handles.next()), (330, '1F'), (100, 'AcDbEntity'),
            (8, layer), (100, 'AcDbLine'),
            (10, fmt(p1[0])), (20, fmt(p1[1])), (30, '0.0'),
            (11, fmt(p2[0])), (21, fmt(p2[1])), (31, '0.0')]


def text_entity(layer, pos, height, value, handles, rot=0.0):
    return [(0, 'TEXT'), (5, handles.next()), (330, '1F'), (100, 'AcDbEntity'),
            (8, layer), (100, 'AcDbText'),
            (10, fmt(pos[0])), (20, fmt(pos[1])), (30, '0.0'),
            (40, fmt(height)), (1, value), (50, fmt(rot)), (100, 'AcDbText')]


# Faz 1.28: bu katmandaki metinler HER ZAMAN saf siyah basılmalı (bkz. aşağıdaki
# FORCE_BLACK_LAYERS notu) -- şu an sadece cadde/sokak ismi (Z_YOL_ADI).
FORCE_BLACK_LAYERS = {'Z_YOL_ADI'}


def rehome_background_entity(ent, handles, text_scale=1.0):
    """Reassign handles/owners for a raw entity pulled from the background
    DXF, without touching anything else about it. Only entities with a
    single (5) handle and possibly multiple (330) owner refs (old-style
    POLYLINE/VERTEX/SEQEND, before conversion to LWPOLYLINE) need this;
    TEXT/LINE have exactly one of each.

    Faz 1.1: `text_scale` (default 1.0, no-op) scales a TEXT entity's height
    (code 40) exactly like the template's own text is scaled in generator.py
    -- background content otherwise keeps its native real-world size (it's a
    real building/parcel, not something we drew), but its ANNOTATION text
    (kapı no, sokak adı) was calibrated to be legible at the 1/250 template
    and becomes proportionally tiny/unreadable at coarser plot scales
    (Issue #2) unless enlarged by the same factor the template's own text
    is. Positions are only ever rehomed/translated here, never scaled --
    only the text height is.

    Faz 1.28: per the user -- gerçek bir üretimde cadde/sokak ismi ("... Sokak")
    hâlâ siyah basılmıyordu, Faz 1.26'da Z_YOL_ADI KATMANINA eklenen true-color
    (420, '0') tanımına rağmen. Kök sebep: bu fonksiyon her kod çiftini
    (5/330/40 dışında) OLDUĞU GİBİ geçiriyordu -- kaynak (kadastro) DXF'teki
    orijinal TEXT varlığı kendi ÜZERİNDE zaten bir renk taşıyorsa (62 ve/veya
    420 kodu, ör. o katmanı hazırlayan başka bir büro/yazılımın rengi), DXF
    spesifikasyonuna göre VARLIK renginin KATMAN rengine her zaman önceliği
    vardır -- yani katman tanımına eklenen (420, '0') pratikte hiç görünmüyordu.
    Çözüm: kaynaktan gelen varlığın kendi (62)/(420) kodları, katmanı
    FORCE_BLACK_LAYERS içindeyse tamamen ATILIYOR ve yerine saf siyahı zorlayan
    kendi (62)='250' (katmanın ACI rengiyle aynı -- palette'te gerçek siyah
    yok, bkz. config.py'deki Faz 1.8 notu -- true-color'ı desteklemeyen eski
    görüntüleyiciler için yedek) + (420)='0' (true color, RGB 0x000000, asıl
    zorlama) çifti ekleniyor; bu varlık düzeyinde olduğu için katman rengini
    de, varlığın kendi eski rengini de ezer."""
    layer_name = None
    for code, val in ent:
        if int(code) == 8:
            layer_name = val
            break
    force_black = layer_name in FORCE_BLACK_LAYERS

    new_ent = []
    top_handle = None
    owner_count = 0
    for code, val in ent:
        cc = int(code)
        if cc == 5:
            h = handles.next()
            if top_handle is None:
                top_handle = h
            new_ent.append((5, h))
        elif cc == 330:
            owner_count += 1
            new_ent.append((330, '1F' if owner_count == 1 else top_handle))
        elif cc == 40 and text_scale != 1.0:
            try:
                new_ent.append((40, fmt(float(val) * text_scale)))
            except ValueError:
                new_ent.append((cc, val))
        elif force_black and cc in (62, 420):
            # Kaynağın kendi varlık-düzeyi renk kodları atılıyor -- (8) katman
            # kodunun hemen ardından, yerlerine tek bir zorunlu siyah çifti
            # ekleniyor (bkz. aşağıdaki `cc == 8` dalı ve yukarıdaki not).
            continue
        else:
            new_ent.append((cc, val))
            if force_black and cc == 8:
                # 62='250': katmanın kendi ACI rengiyle aynı (bkz. config.py'deki
                # Faz 1.8 notu -- palette'te tam siyah yok, 250 en yakın/
                # kullanılan seçim), true-color'ı desteklemeyen eski
                # görüntüleyiciler için yedek. 420='0': asıl zorlama -- saf
                # siyah (RGB 0x000000), true-color destekleyen (R2004+) her
                # modern görüntüleyicide 62'yi ezer. AutoCAD'in kendi
                # yazdığı DXF'lerdeki geleneksel sıralamayı (renk kodları
                # katman kodundan hemen sonra) korumak için burada, dosyanın
                # sonuna eklemek yerine, ekleniyor.
                new_ent.append((62, '250'))
                new_ent.append((420, '0'))

    return new_ent
