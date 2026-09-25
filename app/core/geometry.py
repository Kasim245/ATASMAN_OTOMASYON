"""Pure geometry helpers: areas, distances, diagonal hatch-line generation,
and rectangle clipping (Sutherland-Hodgman for polygons, Liang-Barsky for
lines). No DXF-specific code lives here.
"""
import math


def area2d(v):
    return abs(sum(v[i][0] * v[(i + 1) % len(v)][1] - v[(i + 1) % len(v)][0] * v[i][1]
                   for i in range(len(v)))) / 2


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_segment_distance(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - cx, py - cy)


def point_to_polygon_distance(px, py, poly):
    """En yakın kenara olan mesafe (poligonun İÇİNDE olsa bile 0 değil, en
    yakın sınıra olan mesafeyi döner) -- mahalle.py::find_mahalle'nin sınırın
    hemen dışında kalan (dijitalleştirme/basitleştirme kaynaklı ufak
    boşluklar) noktalar için toleranslı bir yedek eşleşme yapabilmesi için."""
    n = len(poly)
    return min(_point_segment_distance(px, py, poly[i][0], poly[i][1],
                                        poly[(i + 1) % n][0], poly[(i + 1) % n][1])
               for i in range(n))


def polygon_hatch_lines(verts, angle_deg=135.0, spacing=0.4):
    """Real LINE segments filling a (possibly concave) polygon with a diagonal
    hatch, via perpendicular-projection scanlines clipped to every edge.

    Deliberately NOT a DXF HATCH entity: NetCAD was found to render a HATCH
    entity fully solid regardless of its declared pattern, so the hatch is
    drawn as literal geometry instead -- this renders identically everywhere.
    """
    rad = math.radians(angle_deg)
    d = (math.cos(rad), math.sin(rad))
    nrm = (-math.sin(rad), math.cos(rad))
    n = len(verts)
    edges = [(verts[i], verts[(i + 1) % n]) for i in range(n)]
    projs_n = [x * nrm[0] + y * nrm[1] for x, y in verts]
    nmin, nmax = min(projs_n), max(projs_n)
    segments = []
    offset = nmin + spacing / 2.0
    while offset <= nmax:
        p0 = (offset * nrm[0], offset * nrm[1])
        ts = []
        for (x1, y1), (x2, y2) in edges:
            ex, ey = x2 - x1, y2 - y1
            denom = d[0] * (-ey) - d[1] * (-ex)
            if abs(denom) < 1e-9:
                continue
            rhsx, rhsy = x1 - p0[0], y1 - p0[1]
            t = (rhsx * (-ey) - rhsy * (-ex)) / denom
            s = (d[0] * rhsy - d[1] * rhsx) / denom
            if -1e-9 <= s <= 1 + 1e-9:
                ts.append(t)
        ts.sort()
        for i in range(0, len(ts) - 1, 2):
            t1, t2 = ts[i], ts[i + 1]
            p1 = (p0[0] + t1 * d[0], p0[1] + t1 * d[1])
            p2 = (p0[0] + t2 * d[0], p0[1] + t2 * d[1])
            segments.append((p1, p2))
        offset += spacing
    return segments


def offset_edge_outward(p1, p2, centroid, distance):
    """Shift the segment p1->p2 sideways by `distance`, choosing whichever of
    the two perpendicular directions points away from `centroid` -- used to
    draw a bordür/oluk taşı as a parallel line next to the parke edge it was
    surveyed along, offset by the item's real width (12cm bordür, ~30cm
    oluk), instead of directly on top of the raw field points. A pure
    sideways shift of a straight segment doesn't change its length, so this
    only affects where the line is drawn, never the billed miktar."""
    if distance == 0:
        return p1, p2
    (x1, y1), (x2, y2) = p1, p2
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return p1, p2
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    cx, cy = centroid
    d_plus = math.hypot((mx + nx) - cx, (my + ny) - cy)
    d_minus = math.hypot((mx - nx) - cx, (my - ny) - cy)
    if d_minus > d_plus:
        nx, ny = -nx, -ny
    return (x1 + nx * distance, y1 + ny * distance), (x2 + nx * distance, y2 + ny * distance)


def point_in_polygon(x, y, poly):
    """Ray-casting point-in-polygon test against a (possibly large/irregular,
    not-necessarily-convex) closed polygon given as a list of (x,y) vertices."""
    n = len(poly)
    inside = False
    x1, y1 = poly[0]
    for i in range(1, n + 1):
        x2, y2 = poly[i % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
        x1, y1 = x2, y2
    return inside


def clip_polygon(poly, xmin, xmax, ymin, ymax):
    """Sutherland-Hodgman clip of a polygon against an axis-aligned rectangle."""
    def clip_edge(pts, inside, intersect):
        if not pts:
            return []
        out = []
        n = len(pts)
        for i in range(n):
            cur = pts[i]
            prev = pts[i - 1]
            cur_in = inside(cur)
            prev_in = inside(prev)
            if cur_in:
                if not prev_in:
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif prev_in:
                out.append(intersect(prev, cur))
        return out

    def vx(a, b, x):
        t = (x - a[0]) / (b[0] - a[0])
        return (x, a[1] + t * (b[1] - a[1]))

    def hy(a, b, y):
        t = (y - a[1]) / (b[1] - a[1])
        return (a[0] + t * (b[0] - a[0]), y)

    poly = clip_edge(poly, lambda p: p[0] >= xmin, lambda a, b: vx(a, b, xmin))
    poly = clip_edge(poly, lambda p: p[0] <= xmax, lambda a, b: vx(a, b, xmax))
    poly = clip_edge(poly, lambda p: p[1] >= ymin, lambda a, b: hy(a, b, ymin))
    poly = clip_edge(poly, lambda p: p[1] <= ymax, lambda a, b: hy(a, b, ymax))
    return poly


def clip_line(x1, y1, x2, y2, xmin, xmax, ymin, ymax):
    """Liang-Barsky clip of a line segment against an axis-aligned rectangle.
    Returns a (possibly shortened) (x1,y1,x2,y2) tuple, or None if the segment
    doesn't intersect the rectangle at all."""
    dx, dy = x2 - x1, y2 - y1
    p = [-dx, dx, -dy, dy]
    q = [x1 - xmin, xmax - x1, y1 - ymin, ymax - y1]
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None
        else:
            t = qi / pi
            if pi < 0:
                if t > u2:
                    return None
                if t > u1:
                    u1 = t
            else:
                if t < u1:
                    return None
                if t < u2:
                    u2 = t
    if u1 > u2:
        return None
    return (x1 + u1 * dx, y1 + u1 * dy, x1 + u2 * dx, y1 + u2 * dy)
