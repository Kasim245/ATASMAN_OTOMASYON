"""Turns a raw (point file, survey DXF) pair into classified piece candidates,
groups them into spatial clusters (one cluster = one candidate ataşman), and
suggests a street name + template scale for each cluster.

Important, hard-won fact this module exists because of: a single survey DXF
export from NetCAD is often a whole day's/whole batch's field data, not one
ataşman's worth -- the real Akabe 4/45 test file contains 25 closed polygons
scattered across a ~2.7km x ~2.6km area (14 different streets), of which only
7 belong to the Ahmet Bilek Sk / Akabe 4/45 ataşman.

Per the user: which pieces belong to one ataşman is fundamentally a spatial
question, not a street-name question -- nearby pieces that fit together
inside one template frame are one job; the street name is just a label you
read off whichever Z_YOL_ADI text sits closest to that job as a whole (a
per-piece nearest-label lookup is NOT reliable on its own: on Akabe 4/45,
individual pieces near the block's corners are each closer to a *neighboring*
street's sign than to their own street's, even though they're clearly one
contiguous job -- confirmed by testing per-piece lookup against the real
file, which fractured the 7-piece group across 4 different street names).
So the pipeline here clusters by proximity FIRST (single-link / connected
components on piece centroids), then looks up ONE nearest-street label per
whole cluster's centroid -- which is exactly the approach already validated
earlier (nearest label ~31m away vs ~75m for the next street, computed on
the 7-piece group's centroid).
"""
import collections
import math

from .dxf_io import load_dxf_pairs, parse_entities, g
from .points import load_ncn, match_points_to_ncn, classify_polygon, find_bordur_edges
from .geometry import area2d, dist, offset_edge_outward, point_in_polygon
from .config import (
    BORDUR_CODE_MAP, OLUK_CODES, MINHA_CODES, TEMPLATES,
    BORDUR_OFFSET_M, OLUK_OFFSET_M,
)
from .background import extract_background
from .mahalle import load_mahalle_boundaries, find_mahalle

# Pieces within this many meters of each other (single-link) are assumed to
# be the same field job. Chosen empirically against the one real batch file
# available: it cleanly recovers the 7-piece Akabe 4/45 group (max internal
# gap ~95m) while keeping every other street's pieces separate (nearest
# piece belonging to a different job sits ~190m+ away). Revisit once more
# real multi-street batches are seen.
CLUSTER_RADIUS_M = 150.0


def parse_survey_candidates(ncn, saha_dxf):
    """Every closed polyline in the survey DXF that carries a recognized
    parke and/or bordür/oluk code, regardless of which street it belongs to.

    Minha (rögar/manhole, code m70) is its own small closed polygon, walked
    separately from the parke piece it sits inside of -- per the user, its
    area is looked up by simple point-in-polygon containment against the
    parke pieces already found, then handled two different ways: the
    ataşman DXF's own "Minha" title-block field gets the GROSS combined total
    across every minha found (regardless of which parke item each one sits
    in), while the parke piece it's inside of keeps its own GROSS area for
    the drawing/template -- the per-item NET-of-minha figure (parke minus
    the minha area inside it) is only computed for the İcmal Excel, in
    totals_from_candidates() below.
    """
    pts = load_ncn(ncn)
    pairs_survey = load_dxf_pairs(saha_dxf)
    ents_survey = parse_entities(pairs_survey)

    polys = []
    curp = None
    for e in ents_survey:
        if e['type'] == 'POLYLINE':
            flag = int(g(e, 70)[0]) if g(e, 70) else 0
            curp = {'flag': flag, 'v': []}
            polys.append(curp)
        elif e['type'] == 'VERTEX' and curp is not None:
            curp['v'].append((float(g(e, 10)[0]), float(g(e, 20)[0])))
        elif e['type'] == 'SEQEND':
            curp = None

    candidates = []
    minha_polys = []  # [(verts, area, centroid)], matched to a host piece below
    for p in polys:
        if not p['flag'] & 1:
            continue
        verts = p['v']
        if len(verts) < 3:
            continue
        ids = match_points_to_ncn(verts, pts)
        matched_codes = [pts[i][3] for i in ids if i is not None]
        cx = sum(x for x, y in verts) / len(verts)
        cy = sum(y for x, y in verts) / len(verts)

        if matched_codes and all(c in MINHA_CODES for c in matched_codes):
            minha_polys.append((verts, area2d(verts), (cx, cy)))
            continue

        parke_key, minha, cnt = classify_polygon(ids, pts)
        # bordür/oluk çizgisi, ölçülen parke kenarına paralel -- taşın kendi
        # genişliği kadar (12cm/30cm) parça poligonunun DIŞINA doğru kaydırılıp
        # çiziliyor (kullanıcının NetCAD'de elle yaptığı "alanı ölç, kenarına
        # paralel at" adımının otomatiği); bu sadece çizim konumu, uzunluk
        # (piece_bordur[...][3], hakediş miktarı) ham nokta mesafesinden.
        piece_bordur = []
        for p1, p2, code in find_bordur_edges(ids, pts, set(BORDUR_CODE_MAP)):
            p1o, p2o = offset_edge_outward(p1, p2, (cx, cy), BORDUR_OFFSET_M)
            piece_bordur.append((BORDUR_CODE_MAP[code], p1, p2, dist(p1, p2), p1o, p2o))
        for p1, p2, code in find_bordur_edges(ids, pts, OLUK_CODES):
            p1o, p2o = offset_edge_outward(p1, p2, (cx, cy), OLUK_OFFSET_M)
            piece_bordur.append(('T8', p1, p2, dist(p1, p2), p1o, p2o))
        if not parke_key and not piece_bordur:
            continue
        candidates.append({
            'verts': verts,
            'area': area2d(verts) if parke_key else 0.0,
            'parke_key': parke_key,
            'piece_bordur': piece_bordur,
            'cx': cx, 'cy': cy,
            'ymin': min(y for x, y in verts),
            'minha_area': 0.0,
            'minha_shapes': [],
        })

    # match each minha polygon to the parke piece it geometrically sits
    # inside of (first candidate whose polygon contains the minha's centroid)
    for verts, area, (mcx, mcy) in minha_polys:
        for c in candidates:
            if len(c['verts']) >= 3 and point_in_polygon(mcx, mcy, c['verts']):
                c['minha_area'] += area
                c['minha_shapes'].append(verts)
                break

    return candidates


def cluster_candidates(candidates, radius=CLUSTER_RADIUS_M):
    """Single-link spatial clustering (union-find) on piece centroids: two
    candidates in the same cluster if some chain of pairwise distances all
    <= radius connects them. Returns a list of candidate-lists."""
    n = len(candidates)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if dist((candidates[i]['cx'], candidates[i]['cy']),
                    (candidates[j]['cx'], candidates[j]['cy'])) <= radius:
                union(i, j)

    groups = collections.defaultdict(list)
    for i, c in enumerate(candidates):
        groups[find(i)].append(c)
    return list(groups.values())


def _bbox(cluster):
    xs = [x for c in cluster for x, y in c['verts']] + [p[0] for c in cluster for _, p1, p2, _, _, _ in c['piece_bordur'] for p in (p1, p2)]
    ys = [y for c in cluster for x, y in c['verts']] + [p[1] for c in cluster for _, p1, p2, _, _, _ in c['piece_bordur'] for p in (p1, p2)]
    return min(xs), max(xs), min(ys), max(ys)


def suggest_scale(bbox, margin=1.0):
    """Smallest available template scale whose work-area frame can contain
    this bbox (padded by `margin`), or None if it doesn't fit any of them.
    margin=1.0 (no inflation) matches the real Akabe 4/45 reference, whose
    piece cluster is only ~11m narrower than the 250-scale frame itself --
    the placement step centers the bbox in the frame with no extra
    clearance added, so requiring headroom here would reject a scale that
    demonstrably works in practice."""
    xmin, xmax, ymin, ymax = bbox
    need_w = (xmax - xmin) * margin
    need_h = (ymax - ymin) * margin
    best = None
    for key, tpl in sorted(TEMPLATES.items(), key=lambda kv: kv[1]['scale']):
        wa = tpl['work_area_local']
        frame_w = (wa['xmax'] - wa['xmin']) * tpl['scale']
        frame_h = (wa['ymax'] - wa['ymin']) * tpl['scale']
        if need_w <= frame_w and need_h <= frame_h:
            return key
    return best


def _nearest_label(cx, cy, labels):
    if not labels:
        return None, None
    name, lx, ly = min(labels, key=lambda l: (l[1] - cx) ** 2 + (l[2] - cy) ** 2)
    return name, math.hypot(lx - cx, ly - cy)


def describe_clusters(candidates, background_dxf_path=None, mahalle_dxf_path=None,
                       radius=CLUSTER_RADIUS_M):
    """Cluster candidates spatially, then for each cluster: bbox, centroid,
    total area/bordür length, a suggested template scale, (if a background
    DXF is given) the nearest street name AND nearest kapı no (bina numarası)
    to the cluster's own centroid -- both looked up once per cluster, never
    per individual piece, the same way and for the same reason: the imalatın
    önünde durduğu bina numarası is just whichever Z_KAPI_NO text sits
    closest to the job as a whole, exactly like the street name is whichever
    Z_YOL_ADI text sits closest to it -- and (if a mahalle boundary DXF is
    given) which mahalle polygon contains that same centroid (a real
    point-in-polygon test, not a nearest-label guess: the mahalle name text
    can sit anywhere inside its own large, irregular polygon, nowhere near
    any particular street in it).
    Returns a list of dicts, largest piece_count first."""
    clusters = cluster_candidates(candidates, radius=radius)
    mahalle_boundaries = load_mahalle_boundaries(mahalle_dxf_path) if mahalle_dxf_path else []

    street_labels = []
    kapi_no_labels = []
    if background_dxf_path and clusters:
        all_x = [c['cx'] for cl in clusters for c in cl]
        all_y = [c['cy'] for cl in clusters for c in cl]
        pad = 300.0
        labels_raw = extract_background(background_dxf_path,
                                         min(all_x) - pad, max(all_x) + pad,
                                         min(all_y) - pad, max(all_y) + pad,
                                         interest_layers={'Z_YOL_ADI', 'Z_KAPI_NO'})
        for ent in labels_raw:
            layer = [v for c, v in ent if c == '8']
            val = [v for c, v in ent if c == '1']
            x = [v for c, v in ent if c == '10']
            y = [v for c, v in ent if c == '20']
            if layer and val and x and y:
                entry = (val[0], float(x[0]), float(y[0]))
                if layer[0] == 'Z_YOL_ADI':
                    street_labels.append(entry)
                elif layer[0] == 'Z_KAPI_NO':
                    kapi_no_labels.append(entry)

    out = []
    for cl in clusters:
        centroid = (sum(c['cx'] for c in cl) / len(cl), sum(c['cy'] for c in cl) / len(cl))
        bbox = _bbox(cl)
        street, street_dist = _nearest_label(*centroid, street_labels)
        kapi_no, kapi_no_dist = _nearest_label(*centroid, kapi_no_labels)
        mahalle = find_mahalle(*centroid, mahalle_boundaries) if mahalle_boundaries else None
        out.append({
            'candidates': cl,
            'piece_count': sum(1 for c in cl if c['parke_key']),
            'bordur_count': sum(1 for c in cl if c['piece_bordur']),
            'total_area': round(sum(c['area'] for c in cl if c['parke_key']), 2),
            'centroid': centroid,
            'bbox': bbox,
            'suggested_street': street,
            'street_dist_m': round(street_dist, 1) if street_dist is not None else None,
            'suggested_kapi_no': kapi_no,
            'kapi_no_dist_m': round(kapi_no_dist, 1) if kapi_no_dist is not None else None,
            'suggested_mahalle': mahalle,
            'suggested_scale': suggest_scale(bbox),
        })
    return sorted(out, key=lambda g: -g['piece_count'])


def totals_from_candidates(candidates):
    """TOT / TOT_NET / piece_labels / bordur_lines / minha_shapes expected by
    generator.py, built from a (already street-filtered) list of candidates.

    TOT is GROSS -- used to fill the ataşman DXF's own template placeholders
    (parke items keep their full measured area; 'Minha' is the combined total
    of every minha polygon found, across all items). TOT_NET is what the
    İcmal Excel gets instead: per the user, each parke item's İcmal miktarı
    has any minha sitting inside it subtracted out (there's no separate
    'Minha' column in the İcmal -- see the real reference file -- it's netted
    into whichever T-item the minha was inside of)."""
    TOT = collections.defaultdict(float)
    TOT_NET = collections.defaultdict(float)
    piece_labels = []
    bordur_lines = []
    minha_shapes = []
    for c in candidates:
        for bkey, p1, p2, d, p1o, p2o in c['piece_bordur']:
            TOT[bkey] += round(d, 2)
            TOT_NET[bkey] += round(d, 2)
            bordur_lines.append((bkey, p1, p2, d, p1o, p2o))
        if c['parke_key']:
            TOT[c['parke_key']] += round(c['area'], 2)
            TOT_NET[c['parke_key']] += round(c['area'], 2)
            piece_labels.append((c['parke_key'], c['area'], (c['cx'], c['cy']), c['ymin'],
                                  c['verts'], c['piece_bordur']))
        minha_area = c.get('minha_area', 0.0)
        if minha_area:
            TOT['Minha'] += round(minha_area, 2)
            if c['parke_key']:
                TOT_NET[c['parke_key']] -= round(minha_area, 2)
            minha_shapes.extend(c.get('minha_shapes', []))
    return TOT, TOT_NET, piece_labels, bordur_lines, minha_shapes
