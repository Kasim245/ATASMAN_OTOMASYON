"""Low-level, hand-rolled DXF ASCII (group-code) reading/writing helpers.

No external DXF library is used anywhere in this project (ezdxf etc. are not
available in the environment this was first prototyped in, and the hand-rolled
approach turned out to be reliable enough for the narrow set of entity types
this pipeline needs: TEXT, LINE, LWPOLYLINE, and old-style POLYLINE/VERTEX for
*reading* background data only).
"""
import re


def load_dxf_pairs(path_or_bytes):
    """Read a whole DXF file into a flat list of (group_code:int, value:str) pairs.

    Accepts either a filesystem path (str) or raw bytes (e.g. an uploaded file
    already read into memory).
    """
    if isinstance(path_or_bytes, (bytes, bytearray)):
        raw = bytes(path_or_bytes)
    else:
        with open(path_or_bytes, 'rb') as f:
            raw = f.read()
    txt = raw.decode('cp1254', errors='replace').replace('\r\n', '\n').split('\n')
    pairs = []
    for i in range(0, len(txt) - 1, 2):
        line0 = txt[i].strip()
        try:
            c = int(line0)
        except ValueError:
            continue
        pairs.append((c, txt[i + 1].rstrip('\r')))
    return pairs


def pairs_to_bytes(pairs):
    lines = []
    for c, v in pairs:
        lines.append(str(c))
        lines.append(str(v))
    text = "\r\n".join(lines) + "\r\n"
    return text.encode('cp1254', errors='replace')


def parse_entities(pairs):
    """Split the ENTITIES section into a list of {'type', 'codes'} dicts (new-style parser)."""
    sec = None
    ents = []
    cur = None
    i = 0
    while i < len(pairs):
        c, v = pairs[i]
        if c == 0 and v == 'SECTION':
            sec = pairs[i + 1][1]
            i += 2
            continue
        if c == 0 and v == 'ENDSEC':
            sec = None
            i += 1
            continue
        if sec == 'ENTITIES':
            if c == 0:
                cur = {'type': v, 'codes': []}
                ents.append(cur)
            elif cur is not None:
                cur['codes'].append((c, v))
        i += 1
    return ents


def g(e, c):
    return [v for cc, v in e['codes'] if cc == c]


def find_entities_section_span(pairs):
    """Return (start_idx, end_idx) of the (0,'SECTION')..(0,'ENDSEC') pair for ENTITIES."""
    s = e = None
    for idx, (c, v) in enumerate(pairs):
        if c == 0 and v == 'SECTION' and pairs[idx + 1] == (2, 'ENTITIES'):
            s = idx
        if c == 0 and v == 'ENDSEC' and s is not None and e is None and idx > s:
            e = idx
    return s, e


def split_entities_raw(pairs, start, end):
    """Split the raw pair list between an ENTITIES SECTION/ENDSEC span into
    a list of entities, each a list of (code, value) pairs (old-style parser,
    used once we already know the exact span)."""
    ents = []
    cur = None
    for c, v in pairs[start + 2:end]:
        if c == 0:
            cur = [(c, v)]
            ents.append(cur)
        else:
            cur.append((c, v))
    return ents


def evget(ent, code):
    return [v for c, v in ent if c == code]


def fmt(x):
    return f"{x:.6f}"


class HandleCounter:
    """Allocates DXF entity handles starting from a base, avoiding collisions
    with whatever handles already exist in the template."""

    def __init__(self, start=0xF000):
        self._n = start

    def next(self):
        self._n += 1
        return format(self._n, 'X')
