"""Bir kerelik dönüşüm scripti (Faz 1.10): Konya Büyükşehir Belediyesi'nin
acikveri.konya.bel.tr açık veri portalından indirilen WGS84 (enlem/boylam)
mahalle sınırları GeoJSON'unu, projedeki her şeyin kullandığı ITRF96 TM33
(EPSG:5255) projeksiyonuna çevirip data/reference/mahalleler_konya.json
olarak kaydeder.

Kullanım: python3 scripts/convert_mahalle_geojson.py <indirilen.geojson>

pyproj kurulamadığı için (bu ortamda PyPI'a erişim yok) dönüşüm, EPSG:5255'in
resmi parametreleriyle (GRS80 elipsoit, merkezi meridyen 33°D, ölçek 1.0,
false easting 500000) elle yazılmış standart Transverse Mercator (Snyder
1987) formülüyle yapılıyor. Gerçek bir projedeki nokta (EMİRGAZİ
Mahallesi'nde X=459289 Y=4194254) ile doğrulandı: eski mahalleler.dxf'teki
EMİRGAZİ sınırına olan mesafe (123.4066 m) ile bu dönüşümden çıkan
EMİRGAZİ sınırına olan mesafe (123.4074 m) santimetre altı farkla eşleşiyor.
"""
import json
import math
import sys
import os

LON0_DEG = 33.0
K0 = 1.0
FALSE_EASTING = 500000.0
FALSE_NORTHING = 0.0
A = 6378137.0
F = 1 / 298.257222101


def latlon_to_tm33(lat_deg, lon_deg):
    e2 = F * (2 - F)
    ep2 = e2 / (1 - e2)
    phi = math.radians(lat_deg)
    lam = math.radians(lon_deg)
    lam0 = math.radians(LON0_DEG)
    N = A / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    T = math.tan(phi) ** 2
    C = ep2 * math.cos(phi) ** 2
    Ac = (lam - lam0) * math.cos(phi)
    M = A * (
        (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
        - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
        + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
        - (35 * e2 ** 3 / 3072) * math.sin(6 * phi)
    )
    easting = FALSE_EASTING + K0 * N * (
        Ac + (1 - T + C) * Ac ** 3 / 6
        + (5 - 18 * T + T ** 2 + 72 * C - 58 * ep2) * Ac ** 5 / 120
    )
    northing = FALSE_NORTHING + K0 * (
        M + N * math.tan(phi) * (
            Ac ** 2 / 2 + (5 - T + 9 * C + 4 * C ** 2) * Ac ** 4 / 24
            + (61 - 58 * T + T ** 2 + 600 * C - 330 * ep2) * Ac ** 6 / 720
        )
    )
    return round(easting, 2), round(northing, 2)


def rings_of(geometry):
    """Bir Polygon ya da MultiPolygon geometrisinin (delikler hariç, sadece
    dış halka) her parçasını ayrı bir halka olarak döner."""
    if geometry['type'] == 'Polygon':
        yield geometry['coordinates'][0]
    elif geometry['type'] == 'MultiPolygon':
        for poly in geometry['coordinates']:
            yield poly[0]


def main(src_path, dst_path):
    with open(src_path, 'rb') as f:
        raw = f.read()
    # Faz 1.10: dosyanın büyük çoğunluğu (mahalle isimleri) UTF-8, ama
    # tepedeki tek bir "name" alanı (bir Windows dosya yolu yorumu, bize
    # hiç lazım değil) cp1254 ham baytlarla yazılmış -- errors='replace'
    # sadece o ilgisiz alanı bozuyor, gerçek mahalle isimleri sapasağlam.
    data = json.loads(raw.decode('utf-8', errors='replace'))

    boundaries = []
    for feat in data['features']:
        name = feat['properties'].get('ADI_NUMARA')
        if not name:
            continue
        for ring in rings_of(feat['geometry']):
            poly = [list(latlon_to_tm33(lat, lon)) for lon, lat, *_ in ring]
            boundaries.append({'name': name, 'poly': poly})

    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    with open(dst_path, 'w', encoding='utf-8') as f:
        json.dump(boundaries, f, ensure_ascii=False, separators=(',', ':'))

    print(f"{len(boundaries)} sınır yazıldı -> {dst_path}")
    names = {b['name'] for b in boundaries}
    print(f"{len(names)} benzersiz mahalle adı")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Kullanım: python3 convert_mahalle_geojson.py <indirilen.geojson>")
        sys.exit(1)
    main(sys.argv[1], os.path.join(os.path.dirname(__file__), '..', 'data', 'reference', 'mahalleler_konya.json'))
