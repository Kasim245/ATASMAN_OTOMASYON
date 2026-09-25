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
    only the text height is."""
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
        else:
            new_ent.append((cc, val))
    return new_ent
