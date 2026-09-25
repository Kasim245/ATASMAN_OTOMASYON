"""Panelim (kişisel/yönetici analiz) ekranı için basit, bağımsız SVG
grafikler -- projedeki her yerde olduğu gibi (bkz. preview.py) hiçbir
çizim/grafik kütüphanesine ihtiyaç duyulmadan elle çizilir. Chart.js vb.
bir JS kütüphanesi eklemek yerine bu yol seçildi çünkü: (1) internet
erişimi kısıtlı bir ortamda geliştiriliyor, npm/CDN bağımlılığı istemiyoruz,
(2) sunucu tarafında üretilen SVG, JS'siz de (yavaş bağlantı, eski tarayıcı)
her zaman doğru görünür.
"""

BAR_COLOR = '#8a5a2b'      # --accent
BAR_COLOR_DARK = '#6e4620'  # --accent-dark
COMPARE_COLOR = '#9aa4b2'   # nötr gri -- "ekip ortalaması" için, rekabetçi
                            # bir renk (kırmızı/yeşil) kullanılmıyor bilhassa.
GRID_COLOR = '#e2e5e9'
TEXT_COLOR = '#5c6472'
INK_COLOR = '#1c2128'


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def render_weekly_bar_chart_svg(labels, values, width=680, height=220, value_fmt='{:.0f}'):
    """Haftalık üretim trendi -- her çubuk bir hafta, üstünde değeri yazılı.
    `labels`/`values` aynı uzunlukta, eskiden yeniye sıralı olmalı."""
    n = len(values)
    if n == 0:
        return '<svg></svg>'
    pad_left, pad_right, pad_top, pad_bottom = 8, 8, 26, 28
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    vmax = max(values) or 1
    gap_ratio = 0.35
    bar_w = plot_w / (n + (n - 1) * gap_ratio) if n else 0
    gap = bar_w * gap_ratio

    bars = []
    for i, (label, val) in enumerate(zip(labels, values)):
        x = pad_left + i * (bar_w + gap)
        bar_h = (val / vmax) * plot_h if vmax else 0
        y = pad_top + (plot_h - bar_h)
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(bar_h, 0):.1f}" '
            f'rx="3" fill="{BAR_COLOR}"></rect>'
        )
        if val:
            bars.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" font-size="11" font-weight="700" '
                f'fill="{INK_COLOR}" text-anchor="middle">{value_fmt.format(val)}</text>'
            )
        bars.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - 8:.1f}" font-size="10" fill="{TEXT_COLOR}" '
            f'text-anchor="middle">{_esc(label)}</text>'
        )

    baseline_y = pad_top + plot_h
    svg = (
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Haftalık üretim grafiği">'
        f'<line x1="{pad_left}" y1="{baseline_y}" x2="{width - pad_right}" y2="{baseline_y}" '
        f'stroke="{GRID_COLOR}" stroke-width="1"></line>'
        + ''.join(bars) +
        '</svg>'
    )
    return svg


def render_compare_bars_svg(rows, width=560, height=None, value_fmt='{:.0f}', unit=''):
    """'Sen vs Ekip Ortalaması' gibi yatay çubuk karşılaştırmaları.
    `rows`: [(etiket, değer, renk), ...] -- ilk satır genelde 'Sen', ikincisi
    'Ekip ortalaması' olacak şekilde çağrılır."""
    n = len(rows)
    row_h = 40
    pad_top, pad_bottom = 8, 8
    if height is None:
        height = pad_top + pad_bottom + n * row_h
    label_w = 150
    pad_right = 70
    plot_w = width - label_w - pad_right
    vmax = max((v for _, v, _ in rows), default=0) or 1

    parts = []
    for i, (label, val, color) in enumerate(rows):
        y = pad_top + i * row_h
        bar_h = row_h - 14
        bar_w = (val / vmax) * plot_w if vmax else 0
        parts.append(
            f'<text x="{label_w - 10}" y="{y + bar_h / 2 + 4:.1f}" font-size="12.5" font-weight="600" '
            f'fill="{INK_COLOR}" text-anchor="end">{_esc(label)}</text>'
        )
        parts.append(
            f'<rect x="{label_w}" y="{y}" width="{plot_w:.1f}" height="{bar_h}" rx="4" fill="{GRID_COLOR}"></rect>'
        )
        parts.append(
            f'<rect x="{label_w}" y="{y}" width="{max(bar_w, 2):.1f}" height="{bar_h}" rx="4" fill="{color}"></rect>'
        )
        parts.append(
            f'<text x="{label_w + plot_w + 10}" y="{y + bar_h / 2 + 4:.1f}" font-size="12.5" font-weight="700" '
            f'fill="{INK_COLOR}">{value_fmt.format(val)}{_esc(unit)}</text>'
        )

    svg = (
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Karşılaştırma grafiği">' + ''.join(parts) + '</svg>'
    )
    return svg
