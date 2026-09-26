"""Kodu var ama saha DXF'inde hiçbir çizgide kullanılmamış nokta gruplarını
(bkz. survey.py::build_reconstruction_suggestions) kullanıcıya göstermek
için basit, bağımsız bir SVG önizlemesi çizer -- projedeki diğer her şey
gibi (DXF entity'leri, hatch çizgileri) elle hesaplanır, hiçbir çizim
kütüphanesine ihtiyaç duyulmaz.

Faz 1.17: `render_dxf_preview_svg` de aynı elle-hesaplama felsefesiyle,
generate_atasman()'ın ÜRETTİĞİ tam DXF'i (result['dxf_bytes']) ekranda küçük
bir sekmede gösterilebilecek bir SVG'ye çeviriyor -- per the user, "ekranda
ufak bir sekme çıksa net bir şekilde ön gösterim yapılabilir mi": indirmeden
önce/sonra dosyayı AutoCAD/NetCAD açmadan hızlıca göz gezdirebilmek için."""
from .config import BORDUR_CODE_MAP, OLUK_CODES
from .dxf_io import load_dxf_pairs, parse_entities, g, lwpolyline_vertices

_BORDUR_OLUK_CODES = set(BORDUR_CODE_MAP) | set(OLUK_CODES)


def render_run_preview_svg(run_ids, pts, width=420, height=320, pad=36):
    """`run_ids` sırasındaki noktaları AÇIK bir zincir olarak (sonuncudan
    ilkine KAPANMADAN) bir SVG önizlemesi olarak çizer: her nokta bir daire +
    numarası ile, kenarlar da eğer iki ucu da aynı bordür/oluk koduysa
    turuncu, değilse gri çizilir -- tam olarak generate_atasman'ın kendisinin
    bordür/oluk kenarı sayacağı mantığın aynısı (find_bordur_edges), sadece
    burada henüz bir aday değil, sadece bir görsel.

    Faz 1.8: eskiden `range(n)` ile SONUNCU noktadan İLK noktaya da bir
    kenar çiziliyordu (kapalı halkaymış gibi) -- kullanıcı gerçek bir örnekte
    (194,195,196,197 -- hepsi aynı bordür kodlu) bunun YANLIŞ olduğunu
    bildirdi: bu bir bordür HATTI, kapalı bir alan değil, 197 ile 194 asla
    birleşmeyecek. find_bordur_edges() (gerçek üretimde kullanılan, bu
    önizlemenin taklit etmeye çalıştığı fonksiyon) zaten `range(n-1)` ile
    HİÇBİR ZAMAN kapanmıyordu -- yani gerçek DXF çıktısı hep doğruydu, sadece
    bu önizleme yanlışlıkla fazladan bir kenar (ve üstelik aynı kodlu olduğu
    için TURUNCU/bordür renginde) gösteriyordu. Artık ikisi birebir aynı."""
    coords = [(pts[i][0], pts[i][1]) for i in run_ids]
    xs = [x for x, y in coords]
    ys = [y for x, y in coords]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    w_span = max(xmax - xmin, 1e-6)
    h_span = max(ymax - ymin, 1e-6)
    avail_w = width - 2 * pad
    avail_h = height - 2 * pad
    scale = min(avail_w / w_span, avail_h / h_span)

    def to_svg(x, y):
        # SVG y ekseni aşağı doğru büyür, saha Y'si kuzeye (yukarı) doğru --
        # doğal harita görünümü için dikeyde çeviriyoruz.
        sx = pad + (x - xmin) * scale
        sy = height - pad - (y - ymin) * scale
        return sx, sy

    n = len(run_ids)
    lines = []
    for k in range(n - 1):
        i1, i2 = run_ids[k], run_ids[k + 1]
        c1, c2 = pts[i1][3], pts[i2][3]
        is_bordur = c1 == c2 and c1 in _BORDUR_OLUK_CODES
        x1, y1 = to_svg(*coords[k])
        x2, y2 = to_svg(*coords[k + 1])
        color = '#c2542b' if is_bordur else '#8a8478'
        width_px = 2.5 if is_bordur else 1.5
        lines.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="{width_px}" />'
        )

    points_svg = []
    for i, (x, y) in zip(run_ids, coords):
        sx, sy = to_svg(x, y)
        code = pts[i][3] or '(kodsuz)'
        points_svg.append(
            f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="4.5" fill="#ffffff" stroke="#3a3730" stroke-width="1.3" />'
            f'<text x="{sx:.1f}" y="{sy - 8:.1f}" font-size="11" text-anchor="middle" fill="#22201c">{i}</text>'
            f'<text x="{sx:.1f}" y="{sy + 16:.1f}" font-size="9" text-anchor="middle" fill="#6b675f">{code}</text>'
        )

    body = ''.join(lines) + ''.join(points_svg)
    # width/height attribute'ları bilerek eklenmiyor: viewBox + CSS (.preview-svg)
    # sayesinde SVG dar telefon ekranlarında taşmadan küçülüyor.
    return (f'<svg viewBox="0 0 {width} {height}" class="preview-svg" '
            f'xmlns="http://www.w3.org/2000/svg" style="background:#faf9f6;border-radius:8px">'
            f'{body}</svg>')


# ---------------------------------------------------------------------------
# Faz 1.17: ÜRETİLMİŞ ataşman DXF'inin tam sayfa önizlemesi
# ---------------------------------------------------------------------------

# Katman adına göre renk -- ACI numarasını (62) çözmek/palet tutmak yerine,
# zaten kendi kodumuzun (generator.py/config.py) sabit olarak kullandığı
# katman adlarını doğrudan eşliyoruz; hangi katmanın ne anlama geldiğini
# ACI'den daha güvenilir şekilde bunlar söylüyor. Tanımadığı bir katman
# (şablonun kendi çerçeve/başlık kutusu çizgileri gibi) _DEFAULT_* rengine
# düşer -- gerçek içerikten (parça/bordür/arka plan) görsel olarak ayrılsın
# diye soluk gri.
_LAYER_COLORS = {
    'T_1_ANDEZİT_4CM': '#b08968',
    'T_2_ANDEZİT_6CM': '#9c6644',
    'T_3_KÜP_PARKE': '#a67c52',
    'T_6_İDAREDEN_KLTPRK': '#4d7ea8',
    'T_7_YERİNDE_KLTPRK': '#c9a45c',
    'T_4_İDRDN_BORDÜR': '#e67e22',
    'T_5_YERİNDE_BORDÜR': '#c0392b',
    'T_8_OLUK_TAŞI': '#8e44ad',
    'T_MİNHA': '#2ecc71',
    'Z_YAPI_RUHSTLI_PL': '#555555',
    'Z_YAPI_RUHSTSIZ_PL': '#999999',
    'ADAKENARI': '#bbbbbb',
    'Z_YOL_ADI': '#2980b9',
    'Z_KAPI_NO': '#16a085',
    'T_CADDE_SOKAK': '#111111',
    'Z_PARCA_ETIKET': '#b3453a',
}
_DEFAULT_LINE_COLOR = '#aaaaaa'
_DEFAULT_TEXT_COLOR = '#888888'


def _xml_escape(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
             .replace('"', '&quot;'))


def _read_preview_primitives(dxf_bytes):
    """`dxf_bytes` (generate_atasman()'ın result['dxf_bytes']'i) içindeki
    ENTITIES bölümünü, çizilebilir ilkellere (LINE/LWPOLYLINE/eski tip
    POLYLINE+VERTEX zinciri -> 'poly'; TEXT -> 'text') çevirir. Bu pipeline'ın
    kendi ürettiği/geçirdiği DXF'lerde başka entity tipi (INSERT hariç --
    şablondaki 1 adet logo/amblem bloğu, bilerek atlanıyor) çıkmıyor; bilinmeyen
    bir tip görülürse sessizce atlanır, önizleme hata vermez."""
    pairs = load_dxf_pairs(dxf_bytes)
    ents = parse_entities(pairs)
    primitives = []
    i, n = 0, len(ents)
    while i < n:
        e = ents[i]
        t = e['type']
        layer = (g(e, 8) or ['0'])[0]
        if t == 'LINE':
            xs, ys = g(e, 10), g(e, 20)
            x2s, y2s = g(e, 11), g(e, 21)
            if xs and ys and x2s and y2s:
                primitives.append({'kind': 'poly', 'layer': layer, 'closed': False,
                                    'pts': [(float(xs[0]), float(ys[0])),
                                            (float(x2s[0]), float(y2s[0]))]})
            i += 1
        elif t == 'LWPOLYLINE':
            pts = lwpolyline_vertices(e)
            closed = (g(e, 70) or ['0'])[0].strip() not in ('0', '')
            if len(pts) >= 2:
                primitives.append({'kind': 'poly', 'layer': layer, 'closed': closed, 'pts': pts})
            i += 1
        elif t == 'POLYLINE':
            flags = g(e, 70)
            closed = bool(flags) and (int(flags[0]) & 1) == 1
            j = i + 1
            pts = []
            while j < n and ents[j]['type'] == 'VERTEX':
                vx, vy = g(ents[j], 10), g(ents[j], 20)
                if vx and vy:
                    pts.append((float(vx[0]), float(vy[0])))
                j += 1
            if j < n and ents[j]['type'] == 'SEQEND':
                j += 1
            if len(pts) >= 2:
                primitives.append({'kind': 'poly', 'layer': layer, 'closed': closed, 'pts': pts})
            i = j
        elif t == 'TEXT':
            xs, ys, vals = g(e, 10), g(e, 20), g(e, 1)
            hs, rots = g(e, 40), g(e, 50)
            if xs and ys and vals:
                txt = vals[0]
                # "%%U" AutoCAD'in eski metin-içi altı çizme kontrol kodu --
                # generator.py bunu "%%UAYKOME NO" başlığında kullanıyor
                # (bkz. Faz 1.13); literal yazdırmak yerine gerçek altı
                # çizili görünüme çeviriyoruz.
                underline = '%%U' in txt or '%%u' in txt
                txt = txt.replace('%%U', '').replace('%%u', '')
                primitives.append({
                    'kind': 'text', 'layer': layer,
                    'pos': (float(xs[0]), float(ys[0])),
                    'h': float(hs[0]) if hs else 2.5,
                    'text': txt, 'rot': float(rots[0]) if rots else 0.0,
                    'underline': underline,
                })
            i += 1
        else:
            i += 1  # INSERT ve diğerleri: bilerek atlanıyor
    return primitives


def render_dxf_preview_svg(dxf_bytes, width=1000, height=700, pad=20):
    """Üretilmiş ataşman DXF'inin (result['dxf_bytes']) tüm sayfasını -- şablon
    çerçevesi/başlık kutusu, arka plan (bina/yol/kapı no), parça poligonları +
    taramaları, bordür/oluk hatları, parça etiketleri dahil -- tek bir SVG
    olarak çizer. result.html'deki "Ön gösterim" sekmesinde kullanılıyor;
    kullanıcı indirmeden/AutoCAD-NetCAD açmadan önce dosyanın doğru göründüğünü
    hızlıca kontrol edebilsin diye (per the user)."""
    try:
        primitives = _read_preview_primitives(dxf_bytes)
    except Exception:
        return '<p class="hint">Önizleme oluşturulamadı, ama dosya normal şekilde üretildi -- indirip AutoCAD/NetCAD\'de açabilirsiniz.</p>'
    if not primitives:
        return '<p class="hint">Önizlenecek çizim öğesi bulunamadı.</p>'

    xs_all, ys_all = [], []
    for p in primitives:
        if p['kind'] == 'poly':
            for x, y in p['pts']:
                xs_all.append(x)
                ys_all.append(y)
        else:
            x, y = p['pos']
            xs_all.append(x)
            ys_all.append(y)
    if not xs_all:
        return '<p class="hint">Önizlenecek çizim öğesi bulunamadı.</p>'

    xmin, xmax = min(xs_all), max(xs_all)
    ymin, ymax = min(ys_all), max(ys_all)
    w_span = max(xmax - xmin, 1e-6)
    h_span = max(ymax - ymin, 1e-6)
    scale = min((width - 2 * pad) / w_span, (height - 2 * pad) / h_span)

    def to_svg(x, y):
        sx = pad + (x - xmin) * scale
        sy = height - pad - (y - ymin) * scale
        return sx, sy

    body = []
    for p in primitives:
        if p['kind'] == 'poly':
            pts = p['pts']
            if len(pts) < 2:
                continue
            svg_pts = ' '.join(f"{sx:.1f},{sy:.1f}" for sx, sy in (to_svg(x, y) for x, y in pts))
            color = _LAYER_COLORS.get(p['layer'], _DEFAULT_LINE_COLOR)
            tag = 'polygon' if p['closed'] else 'polyline'
            body.append(f'<{tag} points="{svg_pts}" fill="none" stroke="{color}" stroke-width="1" />')
        else:
            sx, sy = to_svg(*p['pos'])
            font_px = max(p['h'] * scale, 4.5)
            color = _LAYER_COLORS.get(p['layer'], _DEFAULT_TEXT_COLOR)
            rot = -p['rot']  # y ekseni SVG'de çevrildiği için dönüş yönü de ters
            transform = f' transform="rotate({rot:.1f} {sx:.1f} {sy:.1f})"' if rot else ''
            deco = ' text-decoration="underline"' if p['underline'] else ''
            body.append(
                f'<text x="{sx:.1f}" y="{sy:.1f}" font-size="{font_px:.1f}" '
                f'fill="{color}"{deco}{transform}>{_xml_escape(p["text"])}</text>'
            )

    body_svg = ''.join(body)
    return (f'<svg viewBox="0 0 {width} {height}" class="preview-svg dxf-preview-svg" '
            f'xmlns="http://www.w3.org/2000/svg" '
            f'style="background:#ffffff;border:1px solid #ddd;border-radius:8px;width:100%;height:auto">'
            f'{body_svg}</svg>')
