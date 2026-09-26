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
components on piece centroids), then looks up ONE street label per whole
cluster's centroid -- which is exactly the approach already validated
earlier (nearest label ~31m away vs ~75m for the next street, computed on
the 7-piece group's centroid).

Faz 1.13: even at the CLUSTER level, straight-line nearest-label can still
pick the wrong street right at a corner/intersection, if a neighbouring
street's sign happens to sit euclidean-closer than the cluster's own
street's sign (confirmed by a real user report -- a cluster on Ergener Sokak
got labeled Hasansevinç Sokak, whose sign was ~44m away vs Ergener's own
~66m by ROAD, even though Ergener's sign was reachable). See
streetnet.py + _street_for_centroid(): the ADAKENARI block-edge network is
used to measure "closest by walking the actual curb", which respects real
street topology instead of cutting across a block; falls back to plain
nearest-label where the network doesn't reach nearby (fragmented/no data).
"""
import collections
import math

from .dxf_io import load_dxf_pairs, parse_entities, g, lwpolyline_vertices
from .points import (
    load_ncn, match_points_to_ncn, classify_polygon, find_bordur_edges, find_orphan_runs,
    find_codeless_orphan_runs,
)
from .geometry import area2d, dist, offset_edge_outward, point_in_polygon
from .config import (
    BORDUR_CODE_MAP, OLUK_CODES, MINHA_CODES, TEMPLATES,
    BORDUR_OFFSET_M, OLUK_OFFSET_M,
)
from .background import extract_background
from .mahalle import load_mahalle_boundaries, find_mahalle
from .streetnet import build_street_network, assign_street_names, nearest_network_street

# Faz 1.13: bir parça kümesinin merkezine, ADAKENARI ağı üzerinden ("hangi
# ada kenarına bağlıyım") ulaşılan sokak etiketi, o kümenin kendi ada
# kenarından bu kadar (metre) uzaktaysa güvenilir sayılır -- daha uzaksa
# ağda o civarda kullanışlı bir veri yok demektir (bkz. streetnet.py'nin
# "bağlı bileşen" notu: ADAKENARI citywide tek bir ağ değil, genelde blok
# blok kopuk parçalardan oluşuyor), o zaman düz "en yakın etiket" yöntemine
# geri dönülür.
STREET_NETWORK_MAX_GAP_M = 50.0

# Pieces within this many meters of each other (single-link) are assumed to
# be the same field job. Chosen empirically against the Akabe 4/45 fixture:
# it cleanly recovers that 7-piece group (max internal gap ~95m) while
# keeping every other street's pieces separate there (nearest piece
# belonging to a different job sits ~190m+ away).
#
# Confirmed against a second real batch (Necmetin, Emirgazi Mh.) that NO
# single fixed radius can be correct for every batch, so this constant is a
# starting GUESS only -- main.py's /regroup route lets the user re-cluster
# the same upload with a different radius from the clusters.html screen when
# the guess is visibly wrong (e.g. one giant group spanning several streets,
# or a real single job split into too many pieces), without re-uploading
# anything.
#
# Faz 1.1: the previous default of 150.0 was demonstrably too loose -- it
# collapsed the real necmetin upload's 70 pieces into a single cluster
# (should have been several separate ataşman jobs). Re-measured against
# both real fixtures on 2026-09-24: Akabe's one legitimate 7-piece group
# needs >=95m to stay merged (unchanged finding); necmetin cleanly splits
# into 3 groups (sizes 1/21/48) anywhere in the 85-95m range, and further
# fragments below 80m without a clear "correct" split point of its own. So
# 95.0 is the tightest value that keeps Akabe correct while giving necmetin
# a real, useful split instead of one giant blob -- not a proof that 95m is
# universally right, just a better starting guess than 150m. /regroup
# remains the mitigation when a batch still needs a different radius.
CLUSTER_RADIUS_M = 95.0


def _build_candidate(verts, ids, pts):
    """Bir kapalı halkayı (ham koordinatlar + eşleşen nokta id'leri) bir aday
    sözlüğüne çevirir -- hem gerçek saha DXF'inden gelen kapalı çizgiler hem
    de kodu var ama çizgisi hiç çizilmemiş noktalardan yeniden inşa edilen
    (reconstructed) şekiller için ORTAK yol. `ids` bazı girdilerde None
    içerebilir (DXF'teki bir köşe hiçbir NCN noktasına yeterince yakın
    değilse); reconstruction yolunda hepsi gerçek id'dir.

    Poligon sadece minha (m70) kodlu noktalardan oluşuyorsa None döner ve
    ikinci eleman (verts, area, centroid) minha bilgisini taşır -- çağıran
    bunu minha_polys listesine ekler."""
    cx = sum(x for x, y in verts) / len(verts)
    cy = sum(y for x, y in verts) / len(verts)
    matched_codes = [pts[i][3] for i in ids if i is not None]

    if matched_codes and all(c in MINHA_CODES for c in matched_codes):
        return None, (verts, area2d(verts), (cx, cy))

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
    # kodu hiç tanınmayan bir parça (ne parke kodu ne bordür/oluk kenarı
    # bulundu) artık SESSİZCE atılmıyor -- kullanıcıya sorulmak üzere
    # 'unclassified' işaretiyle kümeye dahil ediliyor (bkz.
    # classify_unclassified_piece ve main.py::generate). Alanı yine de
    # hesaplayıp saklıyoruz ki kullanıcı "bu bir parke" derse hazır olsun.
    #
    # Kapalı bir şeklin köşelerinin HİÇBİRİNDE parke kodu yoksa (parke_key
    # None) ama TÜMÜ ya da bir kısmı bordür/oluk kodluysa -- kullanıcının
    # kendisinin işaret ettiği gerçek bir belirsizlik: bu ya sahada gerçekten
    # sadece bordür/oluk olarak ölçülmüş bir şekil (ör. bir oluk kanalı), ya
    # da bir kodlama hatası (aslında içi parke olması gerekirken tüm köşeler
    # yanlışlıkla bordür/oluk kodlanmış). Geometri tek başına bunu
    # çözemeyeceği için (uzunluk mu, alan mı ödenecek -- büyük fark yaratır)
    # bu da SESSİZCE bordür/oluk kabul edilmiyor, aynı 'unclassified'
    # onay akışına (review_reason='full_bordur_no_parke') dahil ediliyor --
    # tespit edilen bordür/oluk kırılımı (piece_bordur) saklanıyor ki
    # kullanıcı "evet doğru" derse tekrar hesaplamaya gerek kalmasın.
    review_reason = None
    if not parke_key:
        review_reason = 'full_bordur_no_parke' if piece_bordur else 'no_code'
    unclassified = review_reason is not None
    # Faz 1.4: 2 noktalık bir grup (ör. kodsuz+çizgisiz bir öneri) "kapalı
    # şekil" değil, düz bir hat -- area2d() bunun için hep 0 döner (bkz.
    # geometry.area2d), bu yüzden clusters.html'de "~0.0 m² alanlı kapalı
    # şekil" gibi yanıltıcı bir metin göstermek yerine gerçek uzunluğu
    # gösterebilmek için burada ayrıca hesaplanıp saklanıyor.
    approx_length = dist(verts[0], verts[1]) if len(verts) == 2 else None
    candidate = {
        'verts': verts,
        'area': area2d(verts) if (parke_key or unclassified) else 0.0,
        'approx_length': approx_length,
        'parke_key': parke_key,
        'piece_bordur': piece_bordur,
        'cx': cx, 'cy': cy,
        'ymin': min(y for x, y in verts),
        'minha_area': 0.0,
        'minha_shapes': [],
        'unclassified': unclassified,
        'review_reason': review_reason,
    }
    return candidate, None


def _standalone_line_candidates(ents_survey, pts, consumed_ids, existing_candidates):
    """Kapalı bir parça poligonunun KENARI olarak değil, sahada doğrudan
    bağımsız bir LINE olarak (ya da art arda birkaç LINE'dan oluşan "çoklu
    doğru" olarak) ölçülmüş bordür/oluk kayıtlarını bulur.

    find_bordur_edges() SADECE bir poligonun vertex_ids listesindeki ardışık
    aynı kodlu köşe çiftlerini yakalıyor -- yanında hiç parke alanı ölçülmemiş
    (veya parke alanı bambaşka bir çizgide, bordürden bağımsız ölçülmüş) bir
    bordür/oluk hattının tek başına bir LINE entity olarak durduğu durumu hiç
    görmüyordu (gerçek necmetin.dxf'te böyle 30 LINE bulundu: 24 ybrdr,
    3 olk, 1 m70, 1 yprk -- bir kısmı art arda ekleniyor, tek bir sürekli
    bordür/oluk hattı oluşturuyor).

    Her uygun LINE, kendi başına bir "aday" (candidate) haline getirilir --
    tıpkı bir parçanın elle 'uzunluk' seçilmiş hali gibi (parke_key yok,
    sadece piece_bordur dolu) -- böylece totals_from_candidates() ve
    generator.py'deki çizim adımı hiçbir özel durum eklemeden bunları da
    otomatik olarak işler.

    'Dışa doğru' kayma yönü için bir parça poligonunun aksine doğal bir
    centroid yok -- en yakın gerçek parke parçası (varsa, 30m içindeyse) ona
    göre kaydırılıyor; yoksa hattın kendi orta noktası kullanılıyor (bu
    durumda hangi tarafa kayacağı rastgele ama tutarlı olur -- SADECE çizim
    konumunu etkiler, hakediş miktarını (ham nokta mesafesi) hiç etkilemez)."""
    target_codes = dict(BORDUR_CODE_MAP)
    for code in OLUK_CODES:
        target_codes[code] = 'T8'

    out = []
    for e in ents_survey:
        if e['type'] != 'LINE':
            continue
        x1, y1, x2, y2 = g(e, 10), g(e, 20), g(e, 11), g(e, 21)
        if not (x1 and y1 and x2 and y2):
            continue
        p1 = (float(x1[0]), float(y1[0]))
        p2 = (float(x2[0]), float(y2[0]))
        ids = match_points_to_ncn([p1, p2], pts)
        if ids[0] is None or ids[1] is None:
            continue
        c1, c2 = pts[ids[0]][3], pts[ids[1]][3]
        if c1 != c2 or c1 not in target_codes:
            continue
        consumed_ids.update(ids)
        key = target_codes[c1]
        mx, my = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
        ref = (mx, my)
        pool = existing_candidates + out
        if pool:
            nearest = min(pool, key=lambda c: (c['cx'] - mx) ** 2 + (c['cy'] - my) ** 2)
            if dist((nearest['cx'], nearest['cy']), (mx, my)) <= 30.0:
                ref = (nearest['cx'], nearest['cy'])
        offset_m = OLUK_OFFSET_M if key == 'T8' else BORDUR_OFFSET_M
        p1o, p2o = offset_edge_outward(p1, p2, ref, offset_m)
        out.append({
            'verts': [p1, p2],
            'area': 0.0,
            'parke_key': None,
            'piece_bordur': [(key, p1, p2, dist(p1, p2), p1o, p2o)],
            'cx': mx, 'cy': my,
            'ymin': min(p1[1], p2[1]),
            'minha_area': 0.0,
            'minha_shapes': [],
            'unclassified': False,
            'review_reason': None,
        })
    return out


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

    `saha_dxf` may be None (or the file may contain zero polylines) -- some
    field batches only ever get as far as the coded point file, NetCAD'de
    hiç alan/çizgi çizilmeden kalmış olabilir. Bu durumda candidates boş
    döner ve pts'teki HİÇBİR nokta "consumed" sayılmaz -- kodu olan her nokta
    build_reconstruction_suggestions() tarafından yeniden inşa adayı olarak
    değerlendirilir.

    Returns (candidates, pts, consumed_ids) -- pts ve consumed_ids,
    main.py'nin build_reconstruction_suggestions() çağırıp "kodu var ama
    çizgisi hiç çizilmemiş" noktaları bulması için gerekli.
    """
    pts = load_ncn(ncn)
    consumed_ids = set()
    polys = []
    if saha_dxf:
        pairs_survey = load_dxf_pairs(saha_dxf)
        ents_survey = parse_entities(pairs_survey)
        curp = None
        for e in ents_survey:
            if e['type'] == 'POLYLINE':
                # eski tip: köşeler ayrı VERTEX entity'leri olarak, SEQEND'e
                # kadar art arda gelir.
                flag = int(g(e, 70)[0]) if g(e, 70) else 0
                curp = {'flag': flag, 'v': []}
                polys.append(curp)
            elif e['type'] == 'VERTEX' and curp is not None:
                curp['v'].append((float(g(e, 10)[0]), float(g(e, 20)[0])))
            elif e['type'] == 'SEQEND':
                curp = None
            elif e['type'] == 'LWPOLYLINE':
                # yeni tip (NetCAD'in güncel sürümlerinin varsayılan çıktısı):
                # köşeler alt-entity değil, doğrudan bu entity'nin kendi kod
                # listesinde -- tek adımda tam bir polyline.
                flag = int(g(e, 70)[0]) if g(e, 70) else 0
                polys.append({'flag': flag, 'v': lwpolyline_vertices(e)})

    candidates = []
    minha_polys = []  # [(verts, area, centroid)], matched to a host piece below
    for p in polys:
        verts = p['v']
        if len(verts) < 3:
            continue
        ids = match_points_to_ncn(verts, pts)
        # bu noktalar DXF'te bir çizgide kullanılmış -- hangi çizgi olursa
        # olsun (kapalı olmasa bile), yeniden inşa önerisine dahil edilmesin.
        consumed_ids.update(i for i in ids if i is not None)
        if not p['flag'] & 1:
            continue
        candidate, minha_info = _build_candidate(verts, ids, pts)
        if candidate is None:
            minha_polys.append(minha_info)
            continue
        candidates.append(candidate)

    # match each minha polygon to the parke piece it geometrically sits
    # inside of (first candidate whose polygon contains the minha's centroid)
    for verts, area, (mcx, mcy) in minha_polys:
        for c in candidates:
            if len(c['verts']) >= 3 and point_in_polygon(mcx, mcy, c['verts']):
                c['minha_area'] += area
                c['minha_shapes'].append(verts)
                break

    # parke alanı olmayıp doğrudan bağımsız LINE(ler) olarak ölçülmüş
    # bordür/oluk kayıtları (bkz. _standalone_line_candidates docstring) --
    # şu ana kadar bulunan gerçek parçalardan sonra çalıştırılıyor ki "en
    # yakın parça" referansı (dışa kayma yönü için) elde mevcut olsun.
    if saha_dxf:
        candidates.extend(_standalone_line_candidates(ents_survey, pts, consumed_ids, candidates))

    return candidates, pts, consumed_ids


def build_reconstruction_suggestions(pts, consumed_ids):
    """Kodu olup saha DXF'inde hiçbir çizgide kullanılmamış noktaları
    (find_orphan_runs) bulur, her ardışık numaralı grubu -- sanki gerçek bir
    DXF'ten gelmiş gibi -- bir aday sözlüğüne çevirir. Bunlar hemen
    candidates listesine EKLENMEZ: main.py önce kullanıcıya bir görsel
    gösterip onay/atla seçimi aldırır (bkz. reconstruct.html, /reconstruct),
    sonra sadece onaylananlar gerçek candidates listesine katılır.

    Faz 1.4: AYRICA kodu da tamamen boş VE hiçbir çizgide kullanılmamış nokta
    gruplarını da (find_codeless_orphan_runs) arar -- ör. 193,194,195,196
    gibi ardışık noktaların ne bir kodu ne bir DXF alanı/çizgisi olması.
    Eskiden bunlar "muhtemelen ilgisiz/referans nokta" varsayımıyla tamamen
    sessizce elenirdi; artık bunlar da kullanıcıya "bu ne, bordür mü?" diye
    sorulmak üzere öneri listesine ekleniyor -- 'codeless': True ile
    işaretlenip kodlu önerilerden ayırt ediliyor (reconstruct.html'de farklı
    başlık/metinle gösteriliyor, çünkü kodlu öneride en azından hangi tür
    olduğu (bordür/oluk/parke) koddan tahmin edilebilirken kodsuzda hiç
    tahmin yok -- kullanıcı sıfırdan seçmeli). Onaylanınca akış aynı: mevcut
    _build_candidate + classify_unclassified_piece (kodsuz parça onay
    ekranı) üzerinden bordür/oluk/parke/atla seçilir.

    Her öneri: {'ids': [1,2,...,15], 'candidate': {...} veya None (poligon
    tamamen minha kodluysa -- bu, tek başına anlamsız olduğu için atlanır),
    'codeless': True/False}.
    """
    suggestions = []
    for run in find_orphan_runs(pts, consumed_ids):
        verts = [pts[i][:2] for i in run]
        candidate, minha_info = _build_candidate(verts, run, pts)
        if candidate is None:
            continue  # tamamen minha kodlu bir grup tek başına anlamlı değil
        suggestions.append({'ids': run, 'candidate': candidate, 'codeless': False})
    for run in find_codeless_orphan_runs(pts, consumed_ids):
        verts = [pts[i][:2] for i in run]
        candidate, minha_info = _build_candidate(verts, run, pts)
        if candidate is None:
            continue
        suggestions.append({'ids': run, 'candidate': candidate, 'codeless': True})
    return suggestions


def classify_unclassified_piece(candidate, choice_key, choice_kind):
    """Kullanıcı, kodu tanınmayan bir parça için ne olduğunu (T7/T6/T3 =
    alan, T5/T4/T8 = uzunluk) elle seçtiğinde bu parçayı normal bir aday
    gibi kullanılabilir hale getirir -- generate() içinde, generate_atasman
    çağrılmadan HEMEN ÖNCE çağrılır.

    'area' seçimi: tüm poligon o parke kalemiymiş gibi sayılır (aynı
    eprk/yprk/küp koduymuş gibi). 'length' seçimi: hangi kenarın bordür/oluk
    olduğu koddan bilinemediği için parçanın TÜM çevresi, kenar kenar, o
    kaleme yazılır -- her kenar, ölçülen bordür/oluk taşları ile aynı
    şekilde (12cm/30cm) dışa doğru kaydırılarak çizilir."""
    verts = candidate['verts']
    cx, cy = candidate['cx'], candidate['cy']
    if choice_kind == 'area':
        candidate['parke_key'] = choice_key
        candidate['area'] = area2d(verts)
        candidate['piece_bordur'] = []
    else:
        offset_m = OLUK_OFFSET_M if choice_key == 'T8' else BORDUR_OFFSET_M
        n = len(verts)
        # n==2 (ör. Faz 1.4'te eklenen kodsuz+çizgisiz 2 noktalık bir öneri,
        # veya herhangi bir çift-noktalı parça): tek bir kenar var, iki uç
        # nokta arasında gidiş VE dönüş -- döngü kapalı bir halkaymış gibi
        # `range(n)` ile gezilirse (k=0: p0->p1, k=1: p1->p0 mod n) aynı kenar
        # iki kez -- ters yönde de olsa -- eklenip TOT[bkey]'de uzunluk
        # ikiye katlanırdı. Kapalı bir halka değil, tek bir açık kenar
        # olduğu için sadece bir kez ekleniyor.
        n_edges = 1 if n == 2 else n
        edges = []
        for k in range(n_edges):
            p1, p2 = verts[k], verts[(k + 1) % n]
            p1o, p2o = offset_edge_outward(p1, p2, (cx, cy), offset_m)
            edges.append((choice_key, p1, p2, dist(p1, p2), p1o, p2o))
        candidate['piece_bordur'] = edges
        candidate['parke_key'] = None
        candidate['area'] = 0.0
    candidate['unclassified'] = False
    candidate['review_reason'] = None


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


# Faz 1.2: DENENDİ VE GERÇEK VERİYLE ÇÜRÜTÜLDÜ -- "sadece bbox mevcut en
# kaba şablona (1/1000) sığıyor mu" kıstasına göre (bir yakınlık/mesafe
# kavramı hiç kullanmadan) MST ile birleştiren bir cluster_candidates_by_scale()
# denendi, çünkü kullanıcı "yakınlık meselesine girmeyelim" dedi. Necmetin
# dosyasıyla test edilince bu YANLIŞ ÇIKTI: dosyadaki 3 ayrı, gerçek sokağın
# TOPLAM bbox'ı (509m x 345m) tek bir 1/1000 çerçevesine (703m x 818m)
# rahatça sığıyor -- yani "bbox çerçeveye sığıyor mu" sorusu tek başına 3
# ayrı işi TEK bir dev ataşmana geri birleştiriyordu (tam olarak Issue #1'in
# kendisi). Bu yüzden bir miktar "bunlar gerçekten birbirine yakın/bağlı mı"
# sinyali OLMADAN doğru gruplama matematiksel olarak mümkün değil -- iki
# gerçek dosyada (Akabe, necmetin) IQR/medyan tabanlı otomatik eşik denemeleri
# de tutarsız çıktı (bkz. bu fonksiyonun git geçmişindeki deneme). Bu yüzden
# aşağıdaki cluster_candidates() + CLUSTER_RADIUS_M (deneyle doğrulanmış,
# her iki gerçek dosyada da doğru ayrımı veren 95m) hâlâ kullanılıyor -- ama
# artık kullanıcıya "yakınlık mesafesi" olarak gösterilmiyor: otomatik/dahili
# bir sinyal, kullanıcının normalde hiç görmediği/ayarlamadığı bir şey (bkz.
# main.py/clusters.html -- elle mesafe girme sadece "ileri düzey" bir kaçış
# yolu). Her grubun HANGİ ÖLÇEĞİ (1/250, 1/500, 1/1000) kullanacağı ise zaten
# tamamen otomatik ve gruplamadan bağımsız: suggest_scale(), her grubun kendi
# bbox'ına göre en ince sığanı seçiyor -- kullanıcının istediği "bazı gruplar
# 1/250, bazıları 1/500, bazıları 1/1000 olsun" davranışı zaten bu adımda var.


def _extract_labels_and_network(background_dxf_path, xmin, xmax, ymin, ymax):
    """Tek bir art alan taramasından hem düz etiket listelerini (street_labels,
    kapi_no_labels -- eski/yedek yöntem için) hem de ADAKENARI ağını (nodes,
    node_street -- Faz 1.13'ün ağ-mesafesi tabanlı sokak atamasi için) üretir.
    describe_clusters() ve describe_one_group() arasında ortak (ikisi de aynı
    şekilde hesaplasın diye)."""
    street_labels, kapi_no_labels = [], []
    nodes, node_street = {}, {}
    if not background_dxf_path:
        return street_labels, kapi_no_labels, nodes, node_street

    labels_raw = extract_background(background_dxf_path, xmin, xmax, ymin, ymax,
                                     interest_layers={'Z_YOL_ADI', 'Z_KAPI_NO', 'ADAKENARI'})
    edge_segments = []
    for ent in labels_raw:
        etype = ent[0][1]
        layer = [v for c, v in ent if c == '8']
        if not layer:
            continue
        if etype == 'TEXT':
            val = [v for c, v in ent if c == '1']
            x = [v for c, v in ent if c == '10']
            y = [v for c, v in ent if c == '20']
            if val and x and y:
                entry = (val[0], float(x[0]), float(y[0]))
                if layer[0] == 'Z_YOL_ADI':
                    street_labels.append(entry)
                elif layer[0] == 'Z_KAPI_NO':
                    kapi_no_labels.append(entry)
        elif etype == 'LINE' and layer[0] == 'ADAKENARI':
            x1 = [v for c, v in ent if c == '10']
            y1 = [v for c, v in ent if c == '20']
            x2 = [v for c, v in ent if c == '11']
            y2 = [v for c, v in ent if c == '21']
            if x1 and y1 and x2 and y2:
                edge_segments.append((float(x1[0]), float(y1[0]), float(x2[0]), float(y2[0])))

    if edge_segments and street_labels:
        nodes, adj, label_entries = build_street_network(edge_segments, street_labels)
        node_street = assign_street_names(nodes, adj, label_entries)
    return street_labels, kapi_no_labels, nodes, node_street


def _street_for_centroid(cx, cy, street_labels, nodes, node_street):
    """Faz 1.13: önce ADAKENARI ağı üzerinden (gerçek yol topolojisine saygılı)
    dene; ağdaki en yakın düğüm makul mesafedeyse (STREET_NETWORK_MAX_GAP_M)
    onu kullan -- değilse (o civarda kullanışlı ağ verisi yoksa) düz "en yakın
    etiket" yöntemine geri dön. Bkz. streetnet.py docstring'i: düz yöntem bir
    köşede öz sokağından ÇOK daha yakın duran KOMŞU bir sokak tabelasına
    atlayabiliyordu (gerçek kullanıcı örneğiyle doğrulandı) -- ağ mesafesi bu
    köşeyi "dolaşarak" doğru sokağı buluyor."""
    if node_street:
        nk = min(node_street, key=lambda k: (nodes[k][0] - cx) ** 2 + (nodes[k][1] - cy) ** 2)
        gap = math.hypot(nodes[nk][0] - cx, nodes[nk][1] - cy)
        if gap <= STREET_NETWORK_MAX_GAP_M:
            name, net_dist = node_street[nk]
            return name, net_dist
    return _nearest_label(cx, cy, street_labels)


def _nearest_label(cx, cy, labels):
    if not labels:
        return None, None
    name, lx, ly = min(labels, key=lambda l: (l[1] - cx) ** 2 + (l[2] - cy) ** 2)
    return name, math.hypot(lx - cx, ly - cy)


def describe_clusters(candidates, background_dxf_path=None, mahalle_boundaries_path=None,
                       radius=None):
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

    Faz 1.2: radius=None (varsayılan, normal kullanım) -- deneyle doğrulanmış
    dahili mesafe sinyali (CLUSTER_RADIUS_M) otomatik kullanılır; kullanıcıya
    "yakınlık mesafesi" olarak hiç gösterilmiyor/sorulmuyor (bkz. bu modülün
    yukarıdaki "DENENDİ VE ÇÜRÜTÜLDÜ" notu -- salt bbox/ölçek uyumuna bakan,
    mesafe kavramı hiç kullanmayan bir yöntem gerçek veriyle yanlış çıktı).
    radius bir sayı olarak verilirse (main.py::/regroup'un "ileri düzey" elle
    geçersiz kılma seçeneği), o değer kullanılır -- otomatik sonuç gerçekten
    yanlışsa (örn. iki farklı sokağı tek grupta topluyorsa) elle müdahale
    imkânı olarak. Her iki durumda da her grubun hangi ÖLÇEĞİ (1/250, 1/500,
    1/1000) kullanacağı ayrı ve tamamen otomatik bir adım: suggest_scale(),
    grubun kendi bbox'ına göre en ince sığanı seçiyor -- aynı yüklemede bazı
    gruplar 1/250, bazıları 1/1000 çıkabilir, hepsi aynı anda.
    Returns a list of dicts, largest piece_count first."""
    clusters = cluster_candidates(candidates, radius=radius if radius is not None else CLUSTER_RADIUS_M)
    mahalle_boundaries = load_mahalle_boundaries(mahalle_boundaries_path) if mahalle_boundaries_path else []

    street_labels, kapi_no_labels, nodes, node_street = [], [], {}, {}
    if background_dxf_path and clusters:
        all_x = [c['cx'] for cl in clusters for c in cl]
        all_y = [c['cy'] for cl in clusters for c in cl]
        pad = 300.0
        street_labels, kapi_no_labels, nodes, node_street = _extract_labels_and_network(
            background_dxf_path, min(all_x) - pad, max(all_x) + pad,
            min(all_y) - pad, max(all_y) + pad)

    out = [_group_dict(cl, street_labels, kapi_no_labels, mahalle_boundaries, nodes, node_street)
           for cl in clusters]
    return sorted(out, key=lambda g: -g['piece_count'])


def _group_dict(cl, street_labels, kapi_no_labels, mahalle_boundaries, nodes=None, node_street=None):
    """Bir tek kümenin (candidates listesi) gösterim sözlüğünü üretir --
    describe_clusters()'ın ana döngüsünden ve (Faz 1.3) describe_one_group()'tan
    ortak kullanılıyor, ikisi de aynı alanları aynı şekilde hesaplasın diye."""
    centroid = (sum(c['cx'] for c in cl) / len(cl), sum(c['cy'] for c in cl) / len(cl))
    bbox = _bbox(cl)
    street, street_dist = _street_for_centroid(*centroid, street_labels, nodes or {}, node_street or {})
    kapi_no, kapi_no_dist = _nearest_label(*centroid, kapi_no_labels)
    mahalle, mahalle_dist = (find_mahalle(*centroid, mahalle_boundaries)
                              if mahalle_boundaries else (None, None))
    return {
        'candidates': cl,
        'piece_count': sum(1 for c in cl if c['parke_key']),
        'bordur_count': sum(1 for c in cl if c['piece_bordur']),
        'unclassified_count': sum(1 for c in cl if c.get('unclassified')),
        'total_area': round(sum(c['area'] for c in cl if c['parke_key']), 2),
        'centroid': centroid,
        'bbox': bbox,
        'suggested_street': street,
        'street_dist_m': round(street_dist, 1) if street_dist is not None else None,
        'suggested_kapi_no': kapi_no,
        'kapi_no_dist_m': round(kapi_no_dist, 1) if kapi_no_dist is not None else None,
        'suggested_mahalle': mahalle,
        'mahalle_dist_m': round(mahalle_dist, 1) if mahalle_dist is not None else None,
        'suggested_scale': suggest_scale(bbox),
    }


def describe_one_group(candidates, background_dxf_path=None, mahalle_boundaries_path=None):
    """Faz 1.3: kullanıcı küme ekranında birden fazla kümeyi elle seçip
    "bunlar aslında aynı iş" diyerek birleştirdiğinde (bkz. main.py::
    /merge-groups), yeni birleşmiş kümenin bbox/mahalle/cadde/ölçek gibi
    bilgilerini describe_clusters() ile AYNI mantıkla tek bir candidates
    listesi için yeniden hesaplar. describe_clusters()'tan farklı olarak
    (orada verimlilik için TÜM kümelerin ortak bbox'ı için TEK bir art alan
    taraması yapılıyor) burada sadece bu TEK birleşmiş kümenin kendi bbox'ı
    + payı için ayrı bir tarama yapılıyor -- nadir/istek üzerine çalışan bir
    işlem olduğu için bu kabul edilebilir bir maliyet."""
    if not candidates:
        return None
    mahalle_boundaries = load_mahalle_boundaries(mahalle_boundaries_path) if mahalle_boundaries_path else []
    street_labels, kapi_no_labels, nodes, node_street = [], [], {}, {}
    if background_dxf_path:
        bbox = _bbox(candidates)
        pad = 300.0
        street_labels, kapi_no_labels, nodes, node_street = _extract_labels_and_network(
            background_dxf_path, bbox[0] - pad, bbox[1] + pad, bbox[2] - pad, bbox[3] + pad)
    return _group_dict(candidates, street_labels, kapi_no_labels, mahalle_boundaries, nodes, node_street)


def merge_bordur_chains(bordur_lines, tol=0.05):
    """Faz 1.1 (Issue #4): aynı bkey'e (T4/T5/T8) ait, birbirine komşu
    parke parçalarından gelen ayrı bordür/oluk kenarlarını -- kullanıcının
    2. resimde gösterdiği gibi, parkelere paralel ama birbirinden kopuk kısa
    çizgiler yerine -- TEK bir kesintisiz hatta zincirler.

    Zincirleme, kenarların HAM (ofsetsiz) uç noktalarına (p1/p2) bakarak
    yapılır -- iki kenar, ham uçları `tol` metre içinde çakışıyorsa aynı
    hattın parçası sayılır (komşu parçaların paylaştığı gerçek saha noktası).
    Ama çizilecek olan, o kenarların OFSETLİ (p1o/p2o) konumu -- bordür taşının
    kendi genişliği kadar dışa kaydırılmış hali (bkz. config.py::BORDUR_OFFSET_M/
    OLUK_OFFSET_M) -- sırayla art arda eklenerek tek bir sürekli polyline
    oluşturuluyor. Ödeme miktarı (TOT[bkey]) buradan HİÇ etkilenmiyor: her
    kenarın uzunluğu zaten totals_from_candidates() içinde ayrı ayrı
    toplanmış durumda, birleştirme sadece ÇİZİM için.

    Farklı bkey'ler asla birleştirilmiyor (T4 ile T5 fiziksel olarak farklı
    malzeme). Dallanma/kavşak gibi 2'den fazla kenarın aynı noktada
    birleştiği nadir durumlarda basitçe ilk uygun eşleşme izlenir -- kusursuz
    bir topoloji çözümü değil, ama gerçek saha verisinde (bkz.
    _standalone_line_candidates docstring'i) bordür/oluk hatları neredeyse
    hep düz bir zincir, kavşak değil.

    Dönüş: {bkey: [ [ (x,y), ... ] , ... ]} -- her bkey için, çizilecek
    zincirlerin (her biri en az 2 noktalı) listesi. Zincirlenecek komşusu
    bulunamayan tek bir kenar, tek başına 2 noktalı bir "zincir" olarak
    döner -- eskisi gibi (tek bir LINE yerine artık 2 noktalı bir
    LWPOLYLINE, görsel olarak aynı)."""
    def keyf(p):
        return (round(p[0] / tol), round(p[1] / tol))

    by_bkey = collections.defaultdict(list)
    for bkey, p1, p2, d, p1o, p2o in bordur_lines:
        by_bkey[bkey].append((p1, p2, p1o, p2o))

    result = {}
    for bkey, edges in by_bkey.items():
        endpoint_map = collections.defaultdict(list)
        for idx, (p1, p2, p1o, p2o) in enumerate(edges):
            endpoint_map[keyf(p1)].append(idx)
            endpoint_map[keyf(p2)].append(idx)

        used = [False] * len(edges)
        chains = []
        for start in range(len(edges)):
            if used[start]:
                continue
            used[start] = True
            p1, p2, p1o, p2o = edges[start]
            chain = collections.deque([p1o, p2o])

            # ileri yönde (p2 ucundan) zincirle
            raw_end = p2
            while True:
                nxt = next((i for i in endpoint_map[keyf(raw_end)] if not used[i]), None)
                if nxt is None:
                    break
                used[nxt] = True
                q1, q2, q1o, q2o = edges[nxt]
                if keyf(q1) == keyf(raw_end):
                    chain.append(q2o)
                    raw_end = q2
                else:
                    chain.append(q1o)
                    raw_end = q1

            # geri yönde (p1 ucundan) zincirle
            raw_end = p1
            while True:
                nxt = next((i for i in endpoint_map[keyf(raw_end)] if not used[i]), None)
                if nxt is None:
                    break
                used[nxt] = True
                q1, q2, q1o, q2o = edges[nxt]
                if keyf(q1) == keyf(raw_end):
                    chain.appendleft(q2o)
                    raw_end = q2
                else:
                    chain.appendleft(q1o)
                    raw_end = q1

            chains.append(list(chain))
        result[bkey] = chains
    return result


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
                                  c['verts'], c['piece_bordur'], c.get('aykome_no')))
        minha_area = c.get('minha_area', 0.0)
        if minha_area:
            TOT['Minha'] += round(minha_area, 2)
            if c['parke_key']:
                TOT_NET[c['parke_key']] -= round(minha_area, 2)
            minha_shapes.extend(c.get('minha_shapes', []))
    return TOT, TOT_NET, piece_labels, bordur_lines, minha_shapes
