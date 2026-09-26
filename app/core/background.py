"""Streaming extraction of background/underlay content (buildings, parcel
edges, road-name and address-number text) from a district-wide cadastral DXF,
clipped to a given real-world bounding box.

Reads the file line-by-line rather than loading it into memory: the source
files this was built against run to ~240MB / ~29M lines, which is infeasible
to parse with the whole-file dxf_io.load_dxf_pairs() helper.
"""
from .geometry import clip_line
from .text_metrics import estimate_text_width

INTEREST_LAYERS = {
    'Z_YAPI_RUHSTLI_PL', 'Z_YAPI_RUHSTSIZ_PL', 'Z_YOL_ADI', 'Z_KAPI_NO', 'ADAKENARI',
}


def _text_footprint(cur_pairs):
    """Kaba (yaklaşık) genişlik/yükseklik -- yazı tipi metriği DXF'te yok,
    genişlik text_metrics.estimate_text_width() ile (karakter sınıfına göre
    ölçülmüş Times New Roman oranlarıyla) tahmin ediliyor. Amaç piksel-hassas
    bir kutu değil, "bu yazı kutuya rahat sığar mı" sorusuna kaba ama güvenli
    bir cevap vermek (bkz. extract_background docstring'indeki Faz 1.12 notu).

    Faz 1.26: per the user, gerçek bir üretimde sokak adı yazısı ("...Sokak")
    hâlâ iç şablonun dışına taşıyordu -- kök sebep tam olarak Faz 1.12'nin
    çözmeye çalıştığı sorunun KENDİSİYDİ, sadece eski sabit oran (0.6*yükseklik)
    gerçek Times New Roman genişliğinin yaklaşık %60-70'i kadardı (bkz.
    generator.py::CADDE_CHAR_W_RATIO'nun üstündeki Faz 1.24 notu -- aynı
    yanlış varsayım, iki farklı yerde). Sokak isimleri çoğunlukla Title Case
    ("Beka Sokak") -- ne CADDE_CHAR_W_RATIO'nun büyük-harf-özel 1.0'ı, ne de
    eski düz 0.6 buraya doğrudan uyuyordu; text_metrics'in karışık büyük/
    küçük harf oranı bu yüzden paylaşıldı."""
    h = 0.0
    val = ''
    for c2, v in cur_pairs:
        if c2 == '40':
            try:
                h = float(v)
            except ValueError:
                pass
        elif c2 == '1':
            val = v
    w = estimate_text_width(val, h) if val else 0.0
    return w, h


def extract_background(path, xmin, xmax, ymin, ymax, interest_layers=None):
    """Scan `path` (a district-wide DXF) and return a list of raw entities
    (each a list of (code, value) pairs) from `interest_layers` that fall
    inside [xmin,xmax] x [ymin,ymax]. TEXT is kept only if it fits ENTIRELY
    inside the box (insertion point + a safety margin on every side, sized to
    its own estimated width/height -- see _text_footprint); LINE is clipped
    to the box (Liang-Barsky); POLYLINE is kept whole (with its raw
    VERTEX/SEQEND pairs) if any vertex falls inside the box -- callers are
    expected to clip it further (Sutherland-Hodgman) once they've converted
    it to a plain vertex list.

    Faz 1.12: TEXT used to be kept whenever its raw insertion point (10,20)
    was inside the box, with no regard for the glyphs' own extent. A sokak
    adı/kapı no label whose anchor sits close to the work-area edge would
    then print HALF outside the frame -- exactly the user's screenshot
    ("aşağıda ... sokak ismi dışarda kalmış"). We don't know the real DXF's
    text justification (normal insertion-point semantics vary -- some
    exports anchor bottom-left, some top-left, etc.), so rather than guess
    which direction a given label extends, a label is now required to fit
    with margin on ALL four sides before it's kept; one that's genuinely
    too close to the edge is dropped cleanly instead of showing cut in half.
    """
    interest_layers = interest_layers or INTEREST_LAYERS

    def in_bbox(x, y):
        return xmin <= x <= xmax and ymin <= y <= ymax

    kept_entities = []
    cur_type = None
    cur_layer = None
    cur_pairs = []
    cur_poly_pairs = None
    cur_vertex_pairs = []
    in_entities = False
    in_polyline = False

    with open(path, 'r', encoding='cp1254', errors='replace') as f:
        code = None
        prev_was_section = False
        for raw in f:
            val = raw.rstrip('\r\n')
            if code is None:
                code = val
                continue
            c = code.strip()
            code = None

            if c == '0' and val == 'SECTION':
                prev_was_section = True
                continue
            if c == '2' and prev_was_section:
                prev_was_section = False
                if val == 'ENTITIES':
                    in_entities = True
                continue

            if c == '0':
                if not in_entities:
                    continue

                if in_polyline:
                    if val == 'VERTEX':
                        cur_vertex_pairs.append([])
                        continue
                    elif val == 'SEQEND':
                        verts = []
                        for vp in cur_vertex_pairs:
                            xs = [v for c2, v in vp if c2 == '10']
                            ys = [v for c2, v in vp if c2 == '20']
                            if xs and ys:
                                try:
                                    verts.append((float(xs[0]), float(ys[0])))
                                except ValueError:
                                    pass
                        if cur_layer in interest_layers and any(in_bbox(x, y) for x, y in verts):
                            full = list(cur_poly_pairs)
                            for vp in cur_vertex_pairs:
                                full.append(('0', 'VERTEX'))
                                full.extend(vp)
                            full.append(('0', 'SEQEND'))
                            kept_entities.append(full)
                        in_polyline = False
                        cur_poly_pairs = None
                        cur_vertex_pairs = []
                        cur_layer = None
                        continue

                if cur_type == 'TEXT' and cur_pairs:
                    xs = [v for c2, v in cur_pairs if c2 == '10']
                    ys = [v for c2, v in cur_pairs if c2 == '20']
                    if cur_layer in interest_layers and xs and ys:
                        try:
                            x0, y0 = float(xs[0]), float(ys[0])
                            w, h = _text_footprint(cur_pairs)
                            if (xmin + w <= x0 <= xmax - w
                                    and ymin + h <= y0 <= ymax - h):
                                kept_entities.append(list(cur_pairs))
                        except ValueError:
                            pass
                elif cur_type == 'LINE' and cur_pairs:
                    try:
                        x1 = float([v for c2, v in cur_pairs if c2 == '10'][0])
                        y1 = float([v for c2, v in cur_pairs if c2 == '20'][0])
                        x2 = float([v for c2, v in cur_pairs if c2 == '11'][0])
                        y2 = float([v for c2, v in cur_pairs if c2 == '21'][0])
                    except (IndexError, ValueError):
                        x1 = y1 = x2 = y2 = None
                    if cur_layer in interest_layers and x1 is not None:
                        clipped = clip_line(x1, y1, x2, y2, xmin, xmax, ymin, ymax)
                        if clipped is not None:
                            cx1, cy1, cx2, cy2 = clipped
                            new_pairs = []
                            for c2, v in cur_pairs:
                                if c2 == '10':
                                    new_pairs.append((c2, repr(cx1)))
                                elif c2 == '20':
                                    new_pairs.append((c2, repr(cy1)))
                                elif c2 == '11':
                                    new_pairs.append((c2, repr(cx2)))
                                elif c2 == '21':
                                    new_pairs.append((c2, repr(cy2)))
                                else:
                                    new_pairs.append((c2, v))
                            kept_entities.append(new_pairs)

                if val == 'ENDSEC':
                    break

                if val == 'POLYLINE':
                    in_polyline = True
                    cur_poly_pairs = [('0', 'POLYLINE')]
                    cur_vertex_pairs = []
                    cur_layer = None
                    cur_type = None
                    cur_pairs = []
                else:
                    cur_type = val
                    cur_layer = None
                    cur_pairs = [('0', val)]
                continue

            if not in_entities:
                continue

            if in_polyline:
                if cur_vertex_pairs:
                    cur_vertex_pairs[-1].append((c, val))
                else:
                    cur_poly_pairs.append((c, val))
                    if c == '8':
                        cur_layer = val
                continue

            if cur_type is not None:
                cur_pairs.append((c, val))
                if c == '8':
                    cur_layer = val

    return kept_entities
