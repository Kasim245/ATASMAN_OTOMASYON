"""Main orchestrator: turns (point file + survey DXF + job info) into a
finished ataşman DXF, using a blank template of the given scale.

This is a generalized version of the hand-iterated generateN.py scripts from
the Akabe 4/45 prototype. Piece selection and street-grouping now happen
upstream in survey.py (a raw survey DXF export is often a whole day's/whole
batch's data covering many streets -- see that module's docstring); this
module takes an already street-filtered list of candidates and just needs to:
  - compute the placement offset (TX, TY) that centers this piece cluster in
    the template's work-area rectangle (this used to be hand-picked per
    drawing)
  - substitute mahalle/cadde/hakediş-sıra/tarih/aykome into the template's
    placeholder text (these used to be literal strings)
  - draw the pieces, bordür/oluk lines, per-piece alan/Aykome No etiketi, and
    any clipped background content
"""
import collections

from .config import TEMPLATES, PARKE_LAYER, BORDUR_LAYER, LAYER_TO_KEY, ITEM_PREFIX, NEW_LAYERS
from .dxf_io import (
    load_dxf_pairs, find_entities_section_span,
    split_entities_raw, evget, fmt, pairs_to_bytes, HandleCounter,
)
from .dxf_entities import lwpolyline_entity, line_entity, text_entity, rehome_background_entity
from .geometry import polygon_hatch_lines, clip_polygon
from .survey import totals_from_candidates, merge_bordur_chains
from .background import extract_background


class AtasmanInput:
    def __init__(self, template_scale, candidates, mahalle, cadde_sokak,
                 hakedis_no, sira_no, imalat_bitis_tarihi, aykome_no='',
                 background_dxf_path=None):
        self.template_scale = template_scale
        self.candidates = candidates          # street-filtered list from survey.py
        self.mahalle = mahalle
        self.cadde_sokak = cadde_sokak
        self.hakedis_no = hakedis_no
        self.sira_no = sira_no
        self.imalat_bitis_tarihi = imalat_bitis_tarihi
        self.aykome_no = aykome_no
        self.background_dxf_path = background_dxf_path


def _compute_placement(piece_labels, bordur_lines, work_area_local, scale):
    """Center the new piece cluster's real-world bounding box on the
    template's work-area rectangle; returns (TX, TY)."""
    xs, ys = [], []
    for _, _, _, _, verts, _, _ in piece_labels:
        for x, y in verts:
            xs.append(x)
            ys.append(y)
    for _, p1, p2, _, _, _ in bordur_lines:
        xs += [p1[0], p2[0]]
        ys += [p1[1], p2[1]]
    if not xs:
        raise ValueError("Saha DXF'inde tanınan hiçbir parke/bordür/oluk parçası bulunamadı.")
    rx = (min(xs) + max(xs)) / 2
    ry = (min(ys) + max(ys)) / 2
    lx = (work_area_local['xmin'] + work_area_local['xmax']) / 2
    ly = (work_area_local['ymin'] + work_area_local['ymax']) / 2
    tx = rx - scale * lx
    ty = ry - scale * ly
    return tx, ty


def generate_atasman(inp: AtasmanInput):
    tpl = TEMPLATES[inp.template_scale]
    scale = tpl['scale']

    TOT, TOT_NET, piece_labels, bordur_lines, minha_shapes = totals_from_candidates(inp.candidates)
    tx, ty = _compute_placement(piece_labels, bordur_lines, tpl['work_area_local'], scale)

    def T(x, y):
        return tx + scale * x, ty + scale * y

    # ---- load template, patch T_KLİŞE layer color ----
    # Faz 1.8: rengi eskiden '7'ye (AutoCAD'in arka plana göre kendini
    # ayarlayan "beyaz/siyah" adaptif rengi) sabitliyordu -- kullanıcının
    # ekran görüntüsünde bu rengi kullanan HER ŞEY (klişedeki tüm yazılar
    # dahil) görünmüyordu, kullanıcının DXF görüntüleyicisi bu adaptif
    # rengi (muhtemelen) her zaman literal beyaz çiziyor. '250' (ACI
    # paletinde sabit, çok koyu gri/siyaha yakın bir renk -- bkz.
    # config.py::NEW_LAYERS'daki aynı değişiklik) hiçbir görüntüleyici
    # konvansiyonuna bağımlı olmadan her zaman koyu/görünür kalır.
    pairs = load_dxf_pairs(tpl['path'])
    i = 0
    while i < len(pairs):
        if pairs[i] == (0, 'LAYER'):
            j = i + 1
            rec_start = i
            while j < len(pairs) and pairs[j][0] != 0:
                j += 1
            rec = pairs[rec_start:j]
            if (2, 'T_KLIŞE') in rec:
                for k in range(rec_start, j):
                    if pairs[k][0] == 62:
                        pairs[k] = (62, '250')
                        break
            i = j
        else:
            i += 1

    # ---- add missing LAYER table entries needed for background content ----
    layer_tbl_start = None
    for idx, (c, v) in enumerate(pairs):
        if (c, v) == (2, 'LAYER'):
            layer_tbl_start = idx
            break
    count_idx = layer_tbl_start + 4
    old_count = int(pairs[count_idx][1])
    pairs[count_idx] = (70, str(old_count + len(NEW_LAYERS)))

    endtab_idx = None
    k = layer_tbl_start
    while k < len(pairs):
        if pairs[k] == (0, 'ENDTAB'):
            endtab_idx = k
            break
        k += 1

    def layer_table_record(name, color, handle):
        return [(0, 'LAYER'), (5, handle), (330, '2'), (100, 'AcDbSymbolTableRecord'),
                (100, 'AcDbLayerTableRecord'), (2, name), (70, '0'), (62, color),
                (6, 'Continuous'), (370, '0'), (390, 'F'), (1001, 'AcAecLayerStandard'),
                (1000, ''), (1000, 'AL=0;')]

    new_layer_pairs = []
    for hi, (name, color) in enumerate(NEW_LAYERS):
        new_layer_pairs.extend(layer_table_record(name, color, f"D{hi + 1:02d}"))
    pairs = pairs[:endtab_idx] + new_layer_pairs + pairs[endtab_idx:]

    ent_start, ent_end = find_entities_section_span(pairs)
    ents_list = split_entities_raw(pairs, ent_start, ent_end)

    text_replace = {
        tpl['mahalle_placeholder']: f"{inp.mahalle.upper()} MH.",
        tpl['atasman_no_placeholder']: f"{inp.hakedis_no}/{inp.sira_no}",
        tpl['tarih_placeholder']: f"İMALATıN BİTİŞ TARİHİ : {inp.imalat_bitis_tarihi}",
        # Faz 1.13: boşsa "Aykome No: " diye yarım bırakmak yerine literal
        # "KBF" yazılıyor -- gerçek referans dosyada ("Aykome No: KBF")
        # doğrulandı, aynı düşüş parça etiketlerinde de kullanılıyor (bkz.
        # aşağıdaki piece_labels döngüsü).
        tpl['aykome_prefix_placeholder']: f"Aykome No: {inp.aykome_no or 'KBF'}",
    }
    text_remove = set(tpl['text_remove_literal']) | {tpl['sokak_placeholder']}

    out_entities = []
    for ent in ents_list:
        etype = ent[0][1]
        layer = (evget(ent, 8) or ['0'])[0]
        if etype == 'TEXT':
            val = evget(ent, 1)[0] if evget(ent, 1) else ''
            if val in text_remove and layer == 'T_KLIŞE':
                continue
        metraj_key = LAYER_TO_KEY.get(layer)
        is_atasman_no = (etype == 'TEXT' and layer == 'T_KLIŞE'
                         and evget(ent, 1) == [tpl['atasman_no_placeholder']])
        result = []
        for code, val in ent:
            if etype == 'TEXT' and code == 1:
                txt = val
                if txt in text_replace and layer == 'T_KLIŞE':
                    txt = text_replace[txt]
                if metraj_key and txt == '000.00' and TOT.get(metraj_key, 0) > 0:
                    txt = f"{TOT[metraj_key]:.2f}"
                result.append((code, txt))
            elif code == 10 and is_atasman_no:
                result.append((code, fmt(tx + scale * tpl['atasman_no_x_local'])))
            elif code in (10, 11) and etype in ('TEXT', 'LINE', 'INSERT'):
                x = float(val)
                result.append((code, fmt(tx + scale * x)))
            elif code in (20, 21) and etype in ('TEXT', 'LINE', 'INSERT'):
                y = float(val)
                result.append((code, fmt(ty + scale * y)))
            elif code == 40 and etype == 'TEXT':
                h = float(val)
                result.append((code, fmt(scale * h)))
            elif code in (41, 42) and etype == 'INSERT':
                s = float(val)
                result.append((code, fmt(scale * s)))
            elif code in (10, 20) and etype in ('LWPOLYLINE', 'VERTEX'):
                x = float(val)
                result.append((code, fmt(tx + scale * x) if code == 10 else fmt(ty + scale * x)))
            else:
                result.append((code, val))
        out_entities.append(result)

    # ---- new entities: parke pieces, bordür/oluk lines, cadde/sokak text ----
    handles = HandleCounter()
    new_entities = []
    TAG_H = 0.9
    LINE_SPACING = 1.35
    GAP = 1.6
    item_counters = collections.defaultdict(int)

    def next_item_code(key):
        prefix = ITEM_PREFIX.get(key, key)
        item_counters[prefix] += 1
        return f"{prefix}{item_counters[prefix]}"

    # Faz 1.13: gerçek Akabe 4/45 prototipinde (bu genel uygulamanın
    # modellendiği örnek) her parçanın altına 3 satırlık bir etiket
    # yazılıyormuş -- kullanıcının onaylayıp gösterdiği referans dosyada
    # doğrulandı: "%%UAYKOME NO" (altı çizili başlık), altında parçanın kendi
    # Aykome No'su (yoksa literal "KBF"), altında alanı ("X.XX m²") -- her
    # satır TAG_H yükseklikte, aralarında LINE_SPACING boşluk. Parça başına
    # AYRI bir Aykome No girilebiliyor (bkz. main.py::generate -- her
    # parçanın kendi 'aykome_no'su, boşsa taslak formundaki genel Aykome
    # No'ya, o da boşsa "KBF"ye düşer).
    BORDUR_TAG_LABEL = {'T4': 'Yeni Bordür', 'T5': 'Eski Bordür', 'T8': 'Oluk Taşı'}
    for key, a, (cx, cy), ymin, verts, piece_bordur, piece_aykome_no in piece_labels:
        layer = PARKE_LAYER[key]
        new_entities.append(lwpolyline_entity(layer, verts, handles))
        for p1, p2 in polygon_hatch_lines(verts, angle_deg=135.0, spacing=0.4):
            new_entities.append(line_entity(layer, p1, p2, handles))
        # item code computed for bookkeeping only -- NOT drawn as text (the
        # user assigns/tracks piece labels manually in NetCAD for now, since
        # NetCAD's own "Adı" field can't be set via DXF export)
        next_item_code(key)
        grouped = collections.defaultdict(lambda: {'d': 0.0, 'pts': []})
        for bkey, p1, p2, d, p1o, p2o in piece_bordur:
            grouped[bkey]['d'] += d
            grouped[bkey]['pts'] += [p1, p2]
        for bkey in grouped:
            next_item_code(bkey)

        # Yerleşim: parçanın hemen ALTINA (ymin'in GAP kadar aşağısına),
        # kendi katmanında (Z_PARCA_ETIKET, sabit okunur renk -- parçanın
        # malzeme rengine/tarama çizgilerine karışmasın diye). TAG_H/
        # LINE_SPACING/GAP "template-local" birimler gibi (tıpkı
        # cadde_text_height_local gibi) -- gerçek dünya boyutuna geçerken
        # `scale` ile çarpılıyor ki 1/1000 şablonda da 1/250'dekiyle aynı
        # kağıt-üstü boyutta kalsın.
        tag_lines = [
            '%%UAYKOME NO',
            piece_aykome_no or inp.aykome_no or 'KBF',
            f"{a:.2f} m²",
        ]
        for bkey, g in grouped.items():
            tag_lines.append(f"{BORDUR_TAG_LABEL.get(bkey, bkey)}: {g['d']:.2f} mt")
        tag_h = TAG_H * scale
        tag_y0 = ymin - GAP * scale
        for li, tag_val in enumerate(tag_lines):
            ty_ = tag_y0 - li * LINE_SPACING * scale
            new_entities.append(text_entity('Z_PARCA_ETIKET', (cx, ty_), tag_h, tag_val, handles))

    # bordür/oluk taşı, ölçülen parke kenarına DEĞİL, ona paralel + taşın
    # kendi genişliği kadar (12cm/30cm) dışa kaydırılmış konumuna çizilir --
    # uzunluk (d, hakediş miktarı) zaten ham nokta mesafesinden hesaplandı,
    # burada sadece çizim konumu değişiyor. Faz 1.1 (Issue #4): komşu
    # parçalardan gelen ayrı kenarlar artık tek tek LINE değil, birbirine
    # değen (ham uçları çakışan) kenarlar TEK bir kesintisiz LWPOLYLINE'a
    # zincirlenerek çiziliyor -- bkz. survey.py::merge_bordur_chains.
    for bkey, chains in merge_bordur_chains(bordur_lines).items():
        layer = BORDUR_LAYER[bkey]
        for chain_pts in chains:
            if len(chain_pts) >= 2:
                new_entities.append(lwpolyline_entity(layer, chain_pts, handles, closed=False))

    # minha (rögar) -- kendi küçük poligonu, hangi parke parçasının içindeyse
    # oraya paralel değil, tam kendi ölçülen konumuna çizilir; farklı bir
    # tarama açısıyla (45°) parke parçasından görsel olarak ayrılıyor.
    for verts in minha_shapes:
        new_entities.append(lwpolyline_entity('T_MİNHA', verts, handles))
        for p1, p2 in polygon_hatch_lines(verts, angle_deg=45.0, spacing=0.3):
            new_entities.append(line_entity('T_MİNHA', p1, p2, handles))
        next_item_code('Minha')

    # Faz 1.13: uzun cadde/sokak isimleri (ör. "ŞEHİT MUZAFFER ULUTAŞ SOKAK",
    # 27 karakter) sabit yükseklikte hücrenin sağ sınırını (cadde_max_x_local)
    # aşıp yan hücreye taşıyordu ("kutuda kayıyor" şikayeti) -- DXF'te gerçek
    # font metriği yok, karakter genişliği kaba/güvenli tarafta 0.65*yükseklik
    # olarak tahmin ediliyor; isim bu tahminle hücreye sığmıyorsa yazı, TAM
    # sığacak kadar (ve SADECE o kadar) küçültülüyor -- kısa isimler normal
    # (tam) boyutunda kalıyor.
    ccx, ccy = T(*tpl['cadde_local'])
    cadde_val = inp.cadde_sokak.upper()
    cadde_h_full = tpl['cadde_text_height_local'] * scale
    cadde_available_w = (tpl['cadde_max_x_local'] - tpl['cadde_local'][0]) * scale
    CADDE_CHAR_W_RATIO = 0.65
    needed_w = CADDE_CHAR_W_RATIO * cadde_h_full * max(len(cadde_val), 1)
    if needed_w > cadde_available_w > 0:
        cadde_h = cadde_available_w / (CADDE_CHAR_W_RATIO * max(len(cadde_val), 1))
    else:
        cadde_h = cadde_h_full
    new_entities.append(text_entity('T_CADDE_SOKAK', (ccx, ccy), cadde_h, cadde_val, handles))

    # ---- background (imar planı altlığı) content, clipped to this job's extent ----
    background_entities = []
    if inp.background_dxf_path:
        wa = tpl['work_area_local']
        bg_xmin, bg_ymin = T(wa['xmin'], wa['ymin'])
        bg_xmax, bg_ymax = T(wa['xmax'], wa['ymax'])
        bg_raw = extract_background(inp.background_dxf_path, bg_xmin, bg_xmax, bg_ymin, bg_ymax)
        # background metni (kapı no, sokak adı) 1/250 şablonda okunur şekilde
        # kalibre edildi; daha kaba ölçeklerde (1/1000) şablonun kendi metni
        # nasıl büyüyorsa (bkz. yukarıdaki kod==40 satırı) o kadar büyütülüyor
        # -- 250'de katsayı 1.0 (davranış değişmiyor), 1000'de 4.0 (bkz.
        # rehome_background_entity docstring'i, Issue #2).
        bg_text_scale = scale / TEMPLATES['250']['scale']
        for ent in bg_raw:
            etype = ent[0][1]
            if etype == 'POLYLINE':
                layer = [v for c2, v in ent if c2 == '8'][0]
                verts = []
                cur_vertex = None
                for c2, v in ent:
                    if c2 == '0' and v == 'VERTEX':
                        cur_vertex = {}
                        continue
                    if c2 == '0' and v == 'SEQEND':
                        cur_vertex = None
                        continue
                    if cur_vertex is not None:
                        cur_vertex[c2] = v
                        if c2 == '20':
                            verts.append((float(cur_vertex['10']), float(cur_vertex['20'])))
                clipped = clip_polygon(verts, bg_xmin, bg_xmax, bg_ymin, bg_ymax)
                if len(clipped) >= 3:
                    background_entities.append(lwpolyline_entity(layer, clipped, handles))
                continue
            background_entities.append(rehome_background_entity(ent, handles, text_scale=bg_text_scale))

    flat_existing = [pair for ent in out_entities for pair in ent]
    flat_bg = [pair for ent in background_entities for pair in ent]
    flat_new = [pair for ent in new_entities for pair in ent]
    full = (pairs[:ent_start] + [(0, 'SECTION'), (2, 'ENTITIES')]
            + flat_existing + flat_bg + flat_new + [(0, 'ENDSEC')] + pairs[ent_end + 1:])

    return {
        'dxf_bytes': pairs_to_bytes(full),
        # GROSS -- ataşman DXF'inin kendi başlık bloğu bunlarla dolduruldu
        # (parke kalemleri tam ölçülen alan, Minha ayrı toplam alan olarak).
        'totals': dict(TOT),
        # NET -- her parke kaleminden, içindeki minha alanı düşülmüş hali;
        # İcmal kaydı için bu kullanılıyor (gerçek İcmal dosyasının kendisi de
        # ayrı bir Minha sütunu taşımıyor, kalemin içine netlenmiş veriyor).
        'totals_net': dict(TOT_NET),
        'minha_count': len(minha_shapes),
        'item_codes': dict(item_counters),
        'piece_count': len(piece_labels),
        'bordur_count': len(bordur_lines),
        'placement': {'tx': tx, 'ty': ty, 'scale': scale},
    }
