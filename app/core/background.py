"""Streaming extraction of background/underlay content (buildings, parcel
edges, road-name and address-number text) from a district-wide cadastral DXF,
clipped to a given real-world bounding box.

Reads the file line-by-line rather than loading it into memory: the source
files this was built against run to ~240MB / ~29M lines, which is infeasible
to parse with the whole-file dxf_io.load_dxf_pairs() helper.
"""
from .geometry import clip_line

INTEREST_LAYERS = {
    'Z_YAPI_RUHSTLI_PL', 'Z_YAPI_RUHSTSIZ_PL', 'Z_YOL_ADI', 'Z_KAPI_NO', 'ADAKENARI',
}


def extract_background(path, xmin, xmax, ymin, ymax, interest_layers=None):
    """Scan `path` (a district-wide DXF) and return a list of raw entities
    (each a list of (code, value) pairs) from `interest_layers` that fall
    inside [xmin,xmax] x [ymin,ymax]. TEXT is kept if its insertion point is
    inside the box; LINE is clipped to the box (Liang-Barsky); POLYLINE is
    kept whole (with its raw VERTEX/SEQEND pairs) if any vertex falls inside
    the box -- callers are expected to clip it further (Sutherland-Hodgman)
    once they've converted it to a plain vertex list.
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
                            if in_bbox(float(xs[0]), float(ys[0])):
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
