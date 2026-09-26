"""Street-name assignment via the ADAKENARI (ada/parsel kenarı -- block edge)
line network, as a more reliable alternative to straight-line
nearest-label-to-centroid (survey.py::_nearest_label).

Faz 1.13: the user reported a real, concrete failure -- a piece cluster
sitting on Ergener Sokak got labeled "Hasansevinç Sokak" instead, because
that neighbouring street's sign happened to be euclidean-closer to the
cluster's centroid than Ergener's own sign is. Straight-line distance
doesn't know about the road network: it can "cut the corner" across a block
and jump to a different street's sign near an intersection.

This module answers a different, more physically meaningful question:
walking along the actual block-edge lines (ADAKENARI), which named street's
sign is closest? A multi-source Dijkstra seeded from every Z_YOL_ADI label's
nearest point on the network spreads each street's name outward along the
edges it's actually connected to -- a piece near a corner only picks up the
NEIGHBOURING street's name if the network path to it is genuinely shorter
than the path back to its own street's sign, not just because the sign
itself happens to sit a few metres closer as the crow flies.

No new data source needed: ADAKENARI is already pulled from the same
background cadastral DXF as the Z_YOL_ADI labels themselves (background.py).
"""
import collections
import heapq
import math


def _snap_key(pt, tol=0.3):
    """Grid-snap so line segments that share an endpoint (down to normal
    survey rounding noise) merge into ONE graph node instead of staying as
    disconnected points -- without this, the network is just isolated
    segments and nothing propagates anywhere."""
    return (round(pt[0] / tol), round(pt[1] / tol))


def build_street_network(edge_segments, street_labels):
    """edge_segments: [(x1,y1,x2,y2), ...] (ADAKENARI lines).
    street_labels: [(name, x, y), ...] (Z_YOL_ADI text entries).

    Returns (nodes, adj, label_entries):
      nodes: {node_key: (x, y)}
      adj: {node_key: [(neighbor_key, weight), ...]}
      label_entries: [(nearest_node_key, name, entry_dist), ...] -- entry_dist
        is the straight-line hop from the label's own text position onto the
        network (unavoidable: the label sits beside the road, not exactly on
        it), everything past that point is real network distance.
    """
    nodes = {}
    adj = collections.defaultdict(list)

    def node_key(pt):
        k = _snap_key(pt)
        if k not in nodes:
            nodes[k] = pt
        return k

    for x1, y1, x2, y2 in edge_segments:
        k1 = node_key((x1, y1))
        k2 = node_key((x2, y2))
        if k1 == k2:
            continue
        w = math.hypot(x2 - x1, y2 - y1)
        adj[k1].append((k2, w))
        adj[k2].append((k1, w))

    label_entries = []
    if nodes:
        for name, lx, ly in street_labels:
            nk = min(nodes, key=lambda k: (nodes[k][0] - lx) ** 2 + (nodes[k][1] - ly) ** 2)
            nx, ny = nodes[nk]
            label_entries.append((nk, name, math.hypot(nx - lx, ny - ly)))

    return nodes, adj, label_entries


def assign_street_names(nodes, adj, label_entries):
    """Multi-source Dijkstra from every labelled node at once: every node in
    the network ends up owned by whichever street's sign is closest to it by
    NETWORK distance (edge length), not straight-line distance. Returns
    {node_key: (street_name, network_dist)}."""
    dist = {}
    owner = {}
    pq = []
    for nk, name, entry_dist in label_entries:
        if entry_dist < dist.get(nk, math.inf):
            dist[nk] = entry_dist
            owner[nk] = name
            heapq.heappush(pq, (entry_dist, nk))
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, math.inf):
            continue
        for v, w in adj.get(u, ()):
            nd = d + w
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                owner[v] = owner[u]
                heapq.heappush(pq, (nd, v))
    return {k: (owner[k], dist[k]) for k in owner}


def nearest_network_street(px, py, nodes, node_street):
    """The street name assigned (via assign_street_names) to whichever
    network node is euclidean-nearest to (px, py) -- this is how a piece
    cluster's centroid finally reads off "which street's curb is this join
    to", after the network has done the work of respecting actual road
    topology instead of jumping across a block."""
    if not node_street:
        return None, None
    nk = min(node_street, key=lambda k: (nodes[k][0] - px) ** 2 + (nodes[k][1] - py) ** 2)
    name, d = node_street[nk]
    return name, d
