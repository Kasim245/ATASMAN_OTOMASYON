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
from .geometry import point_in_polygon

BOUNDARY_LAYER = 'Z_NMAHALLE_PL'
NAME_LAYER = 'AADI'


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
    """Which mahalle (if any) contains (x, y). Returns the name, or None if
    the point falls outside every boundary in the file."""
    for b in boundaries:
        if point_in_polygon(x, y, b['poly']):
            return b['name']
    return None
