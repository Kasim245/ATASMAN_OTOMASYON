"""Kodu var ama saha DXF'inde hiçbir çizgide kullanılmamış nokta gruplarını
(bkz. survey.py::build_reconstruction_suggestions) kullanıcıya göstermek
için basit, bağımsız bir SVG önizlemesi çizer -- projedeki diğer her şey
gibi (DXF entity'leri, hatch çizgileri) elle hesaplanır, hiçbir çizim
kütüphanesine ihtiyaç duyulmaz.
"""
from .config import BORDUR_CODE_MAP, OLUK_CODES

_BORDUR_OLUK_CODES = set(BORDUR_CODE_MAP) | set(OLUK_CODES)


def render_run_preview_svg(run_ids, pts, width=420, height=320, pad=36):
    """`run_ids` sırasındaki noktaları (kapalı halka olarak, sonuncudan
    ilkine dönerek) bir SVG önizlemesi olarak çizer: her nokta bir daire +
    numarası ile, kenarlar da eğer iki ucu da aynı bordür/oluk koduysa
    turuncu, değilse gri çizilir -- tam olarak generate_atasman'ın kendisinin
    bordür/oluk kenarı sayacağı mantığın aynısı (find_bordur_edges), sadece
    burada henüz bir aday değil, sadece bir görsel."""
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
    for k in range(n):
        i1, i2 = run_ids[k], run_ids[(k + 1) % n]
        c1, c2 = pts[i1][3], pts[i2][3]
        is_bordur = c1 == c2 and c1 in _BORDUR_OLUK_CODES
        x1, y1 = to_svg(*coords[k])
        x2, y2 = to_svg(*coords[(k + 1) % n])
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
