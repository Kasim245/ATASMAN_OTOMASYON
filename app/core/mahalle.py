"""Mahalle (neighborhood) boundary lookup: given a real-world point, which
mahalle polygon contains it.

Faz 1.10: eskiden bu sınırlar elle hazırlanmış Mahalleler.DXF'ten (sadece
Karatay'ın 67 mahallesi) okunuyordu. Kullanıcının kendi gerçek verisinde bu
dosyanın sınırları bazı noktaları kapsamıyordu (bkz. mahalle_dist_m
yedeği, Faz 1.8/1.9). Kullanıcı, Konya Büyükşehir Belediyesi'nin açık veri
portalından (acikveri.konya.bel.tr) TÜM Konya'nın (1160 mahalle, tüm
ilçeler) resmi, güncel sınırlarını içeren bir GeoJSON indirdi -- bu WGS84
(enlem/boylam) cinsindendi, projedeki her şeyin kullandığı ITRF96 TM33'e
(EPSG:5255) `scripts/convert_mahalle_geojson.py` ile bir kerelik dönüştürülüp
data/reference/mahalleler_konya.json olarak kaydedildi (basit bir liste:
[{'name':..., 'poly': [[x,y],...]}, ...] -- artık DXF ayrıştırmaya gerek
yok). Eski EMİRGAZİ sınırıyla gerçek bir saha noktası (X=459289, Y=4194254)
üzerinden karşılaştırılıp doğrulandı (santimetre altı fark)."""
import json

from .geometry import point_in_polygon, point_to_polygon_distance

# Faz 1.8 (ilk deneme): kesin point-in-polygon testi TEK BAŞINA yeterli
# değildi -- bir işin merkezi, sınır çiziminin basitleştirilmesi/
# dijitalleştirme hassasiyeti yüzünden gerçek mahalle sınırının hemen
# DIŞINDA kalabiliyor. İlk denemede 30m'nin ötesinde hâlâ None dönüp
# kullanıcıya soruluyordu -- kullanıcı bunun kendi gerçek verisinde HÂLÂ
# çalışmadığını bildirdi (merkez sınırdan 30m'den daha uzakta kalan
# durumlar var). Artık aşağıdaki find_mahalle() HİÇBİR ZAMAN None dönmüyor
# (boundaries doluysa) -- cadde/sokak ve kapı no önerileri gibi, kesin
# olmayan bir öneri de mesafesiyle birlikte gösterilip kullanıcının gözden
# geçirmesi isteniyor (bkz. survey.py::_group_dict, clusters.html), alan
# hiçbir zaman zorunlu-boş kalmıyor.


def load_mahalle_boundaries(path):
    """Returns a list of {'name': str, 'poly': [(x,y), ...]} -- one per
    mahalle sınır parçası (bir mahalle birden fazla ayrı parçadan -- ör.
    anklav -- oluşuyorsa, o mahalle adıyla birden fazla giriş olabilir,
    find_mahalle zaten tüm listeyi tarıyor)."""
    with open(path, encoding='utf-8') as f:
        raw = json.load(f)
    return [{'name': b['name'], 'poly': [tuple(p) for p in b['poly']]} for b in raw]


def find_mahalle(x, y, boundaries):
    """(x, y) hangi mahallenin İÇİNDE -- kesin eşleşme (name, None) döner
    (mesafe gösterilmeye gerek yok, tam eşleşme). Hiçbir poligonun içinde
    değilse (67 sınırdan hiçbiri kapsamıyorsa) artık None dönüp kullanıcıyı
    sıfırdan yazmaya zorlamıyor -- en yakın mahalle sınırı (name, mesafe_m)
    olarak öneriliyor, tıpkı cadde/sokak ve kapı no önerileri gibi; ekranda
    bu mesafe gösterilip kullanıcının "doğru mu?" diye gözden geçirmesi
    isteniyor, ama alan hep dolu geliyor -- boundaries boşsa (None, None)."""
    for b in boundaries:
        if point_in_polygon(x, y, b['poly']):
            return b['name'], None
    if not boundaries:
        return None, None
    nearest = min(boundaries, key=lambda b: point_to_polygon_distance(x, y, b['poly']))
    return nearest['name'], point_to_polygon_distance(x, y, nearest['poly'])
