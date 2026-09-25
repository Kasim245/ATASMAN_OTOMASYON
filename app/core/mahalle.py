"""Mahalle (neighborhood) boundary lookup: given a real-world point, which
mahalle polygon contains it.

Source file structure (Mahalleler.DXF, ~5.5MB/700K lines -- small enough to
load whole, unlike the 239MB KARATAY background file): 67 closed boundary
polygons on layer Z_NMAHALLE_PL (old-style POLYLINE/VERTEX/SEQEND), and 67
TEXT entities on layer AADI carrying each mahalle's name, positioned
somewhere *inside* its own polygon (not on a fixed/predictable spot, and not
necessarily near any particular street within it -- so, unlike the street
name lookup in survey.py, this can NOT be done by nearest-label distance; it
has to be a real point-in-polygon test). Verified 67/67 texts pair uniquely
with a containing polygon, and the pairing correctly places the Akabe 4/45
cluster's centroid inside the AKABE polygon.
"""
from .dxf_io import load_dxf_pairs, parse_entities, g
from .geometry import point_in_polygon, point_to_polygon_distance

BOUNDARY_LAYER = 'Z_NMAHALLE_PL'
NAME_LAYER = 'AADI'

# Faz 1.8: per the user ("yine bana mahalle bilgisini soruyor"), kesin
# point-in-polygon testi TEK BAŞINA yeterli değildi -- bir işin merkezi,
# sınır çiziminin basitleştirilmesi/dijitalleştirme hassasiyeti yüzünden
# gerçek mahalle sınırının hemen (birkaç metre) DIŞINDA kalabiliyor, bu da
# gereksiz yere "mahalleyi elle girin" sorusuna düşürüyordu. Bu yüzden kesin
# eşleşme yoksa, en yakın sınıra bu mesafeden daha yakınsa yine de o mahalle
# öneriliyor -- ama bunun ötesinde (gerçekten başka/kapsanmayan bir bölgede)
# hâlâ None dönüp kullanıcıya soruluyor, rastgele bir mahalleye
# yapıştırılmıyor.
NEARBY_FALLBACK_M = 30.0


def load_mahalle_boundaries(path):
    """Returns a list of {'name': str, 'poly': [(x,y), ...]} -- one per
    mahalle, name already resolved by point-in-polygon pairing."""
    pairs = load_dxf_pairs(path)
    ents = parse_entities(pairs)

    polys = []
    curp = None
    for e in ents:
        if e['type'] == 'POLYLINE':
            if g(e, 8) and g(e, 8)[0] == BOUNDARY_LAYER:
                curp = {'v': []}
                polys.append(curp)
            else:
                curp = None
        elif e['type'] == 'VERTEX' and curp is not None:
            curp['v'].append((float(g(e, 10)[0]), float(g(e, 20)[0])))
        elif e['type'] == 'SEQEND':
            curp = None

    names = []
    for e in ents:
        if e['type'] == 'TEXT' and g(e, 8) and g(e, 8)[0] == NAME_LAYER:
            val = g(e, 1)
            x = g(e, 10)
            y = g(e, 20)
            if val and x and y:
                names.append((val[0], float(x[0]), float(y[0])))

    boundaries = []
    for name, tx, ty in names:
        for p in polys:
            if len(p['v']) >= 3 and point_in_polygon(tx, ty, p['v']):
                boundaries.append({'name': name, 'poly': p['v']})
                break
    return boundaries


def find_mahalle(x, y, boundaries):
    """Which mahalle (if any) contains (x, y). Kesin point-in-polygon
    eşleşmesi yoksa, en yakın sınıra NEARBY_FALLBACK_M'den daha yakınsa yine
    o mahalle döner (bkz. yukarıdaki NEARBY_FALLBACK_M yorumu) -- gerçekten
    hiçbir mahalleye (ne içeride ne yakında) düşmüyorsa None döner ve
    kullanıcıya elle sorulur."""
    for b in boundaries:
        if point_in_polygon(x, y, b['poly']):
            return b['name']
    if not boundaries:
        return None
    nearest = min(boundaries, key=lambda b: point_to_polygon_distance(x, y, b['poly']))
    if point_to_polygon_distance(x, y, nearest['poly']) <= NEARBY_FALLBACK_M:
        return nearest['name']
    return None
