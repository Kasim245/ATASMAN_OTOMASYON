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
  - draw the pieces, bordür/oluk lines, and any clipped background content
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
    for _, _, _, _, verts, _ in piece_labels:
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

    # ---- load template, patch T_KLİŞE layer color to black/white (7) ----
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
                        pairs[k] = (62, '7')
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
        tpl['aykome_prefix_placeholder']: f"Aykome No: {inp.aykome_no}",
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

    for key, a, (cx, cy), ymin, verts, piece_bordur in piece_labels:
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

    ccx, ccy = T(*tpl['cadde_local'])
    new_entities.append(text_entity('T_CADDE_SOKAK', (ccx, ccy),
                                     tpl['cadde_text_height_local'] * scale,
                                     inp.cadde_sokak.upper(), handles))

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
