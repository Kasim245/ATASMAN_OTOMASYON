"""Field-collected point file (NCN) loading and code-based piece classification."""
import re
import math
import collections

from .geometry import dist
from .config import PARKE_CODE_MAP, MINHA_CODES


def load_ncn(path_or_bytes):
    """Parse an NCN point file: `id  id  Y  X  Z  0  "kod"  ""  ""` per line."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        raw = bytes(path_or_bytes)
    else:
        with open(path_or_bytes, 'rb') as f:
            raw = f.read()
    pts = {}
    for line in raw.decode('cp1254').splitlines():
        m = re.match(r'\s*(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+\d+\s+"([^"]*)"', line)
        if m:
            pts[int(m[1])] = (float(m[2]), float(m[3]), float(m[4]), m[5])
    return pts


def match_points_to_ncn(vertices, pts, tol=0.01):
    """For each (x,y) vertex from the survey DXF, find the nearest NCN point
    and return its id if within `tol` meters, else None."""
    ids = []
    for x, y in vertices:
        best = min(pts.items(), key=lambda kv: (kv[1][0] - x) ** 2 + (kv[1][1] - y) ** 2)
        d = math.hypot(best[1][0] - x, best[1][1] - y)
        ids.append(best[0] if d < tol else None)
    return ids


def classify_polygon(vertex_ids, pts):
    """Which parke-family area item (T6/T7 parke, T3 küp -- all whole-polygon
    area items, unlike bordür/oluk which are edge/length items) this closed
    piece belongs to, based on the codes of its own vertices."""
    codes = [pts[i][3] for i in vertex_ids if i is not None]
    cnt = collections.Counter(codes)
    parke_key = None
    for code in PARKE_CODE_MAP:
        if cnt.get(code, 0) > 0:
            parke_key = PARKE_CODE_MAP[code]
    minha = any(c in MINHA_CODES for c in codes)
    return parke_key, minha, cnt


def find_orphan_runs(pts, consumed_ids):
    """Kodu olup saha DXF'inde hiçbir çizgide kullanılmamış (consumed_ids'te
    olmayan) nokta id'lerini bulur, sahada genelde bir şeklin etrafında
    sırayla numaralandıkları varsayımıyla ARDIŞIK numaralara göre gruplar
    (örn. 1,2,3...15 -> tek bir grup; sonra 20,21..28 -> ayrı bir grup).
    Kodu tamamen boş VE hiç kullanılmamış noktalar (muhtemelen ilgisiz/
    referans noktalar) bu gruplamaya dahil edilmez. En az 3 noktası olmayan
    bir grup kapalı bir şekil oluşturamayacağı için elenir."""
    orphan_ids = sorted(i for i, (x, y, z, code) in pts.items()
                         if i not in consumed_ids and code)
    runs = []
    cur = []
    for i in orphan_ids:
        if cur and i != cur[-1] + 1:
            runs.append(cur)
            cur = []
        cur.append(i)
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= 3]


def find_bordur_edges(vertex_ids, pts, target_codes):
    """Consecutive-vertex runs (in original polyline order) sharing the same
    bordur/oluk code -> one (p1, p2, code) edge per such run."""
    n = len(vertex_ids)
    edges = []
    for k in range(n - 1):
        i1, i2 = vertex_ids[k], vertex_ids[(k + 1) % n]
        if i1 is None or i2 is None:
            continue
        c1, c2 = pts[i1][3], pts[i2][3]
        if c1 == c2 and c1 in target_codes:
            edges.append((pts[i1][:2], pts[i2][:2], c1))
    return edges
