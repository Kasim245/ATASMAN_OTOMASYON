"""Builders for the handful of new DXF entities this pipeline writes.

Everything is a plain, self-contained entity (LWPOLYLINE, LINE, TEXT) --
old-style POLYLINE/VERTEX/SEQEND is deliberately avoided for anything we
generate ourselves: its owner-handle chain (VERTEX (330) must point at its
*own* parent POLYLINE's new handle, not modelspace) silently drops vertices
in NetCAD if it's wrong, and LWPOLYLINE has no such chain to get wrong.
"""
from .dxf_io import fmt


def lwpolyline_entity(layer, verts_xy, handles):
    ent = [(0, 'LWPOLYLINE'), (5, handles.next()), (330, '1F'), (100, 'AcDbEntity'),
           (8, layer), (100, 'AcDbPolyline'), (90, str(len(verts_xy))), (70, '1'), (43, '0.0')]
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


def rehome_background_entity(ent, handles):
    """Reassign handles/owners for a raw entity pulled from the background
    DXF, without touching anything else about it. Only entities with a
    single (5) handle and possibly multiple (330) owner refs (old-style
    POLYLINE/VERTEX/SEQEND, before conversion to LWPOLYLINE) need this;
    TEXT/LINE have exactly one of each."""
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
        else:
            new_ent.append((cc, val))
    return new_ent
