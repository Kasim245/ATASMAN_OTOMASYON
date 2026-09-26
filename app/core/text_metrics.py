"""Faz 1.26: paylaşılan (hand-rolled, kütüphanesiz) Times New Roman karakter
genişlik tahmini.

Şablonun metin stili (`sablon_250.dxf`'in STYLE tablosu) "times.ttf" --
Times New Roman -- kullanıyor, ve DXF formatı bir TEXT satırının gerçek
piksel/çizim genişliğini hiç saklamıyor (sadece yükseklik -- kod 40). Daha
önce (Faz 1.13/1.24, bkz. generator.py::CADDE_CHAR_W_RATIO) BÜYÜK HARF
sokak isimleri için 0.65 sonra 1.0 sabit oranı kullanılmıştı; 1.0 doğru
çıktı ÇÜNKÜ o metin her zaman tamamen büyük harf (`.upper()` ile
zorlanıyor). Ama bu modül HEM parça etiketi satırları (ör. "Eski Parke:
4.37 m²" -- karışık büyük/küçük harf + rakam + noktalama) HEM DE arka
plandan gelen sokak isimleri (ör. "Beka Sokak" -- Title Case, hepsi büyük
harf DEĞİL) için kullanılıyor; tek bir düz oran ya küçük harfli metni
fazla geniş (gereksiz küçültme/kırpma), ya da büyük harfli metni fazla dar
(gerçek taşma riski -- background.py'nin `_text_footprint`'inde tam olarak
bu ikinci hata vardı: sabit 0.6, gerçek büyük harf oranının ~%60'ı kadar).

Bunun yerine karakter SINIFINA göre ayrı ayrı ölçülmüş oranlar kullanılıyor
(yöntem: PIL ImageFont.getlength(), `/usr/share/fonts/truetype/liberation/
LiberationSerif-Regular.ttf` -- Times New Roman'la metrik olarak eşleniği,
bu ortamda gerçek times.ttf mevcut/kurulabilir değil) -- her karakterin
genişliği kendi sınıfının ölçülmüş oranıyla * yükseklik olarak toplanıyor.
Tanınmayan bir karakter (örn. nadir bir sembol) en GENİŞ sınıfa (büyük
harf) düşer -- amaç yine "kaba ama güvenli" bir üst sınır, düşük tahmin
(taşma) riskinden kaçınmak, gereğinden fazla küçültmek/kırpmak değil."""

# Ölçülen oranlar (genişlik / BÜYÜK HARF kap-yüksekliği), yuvarlanmış:
CHAR_W_RATIO_UPPER = 1.00   # A-Z + Turkish ÇĞİÖŞÜ (ölçülen: 1.0046)
CHAR_W_RATIO_LOWER = 0.70   # a-z + Turkish çğıöşü (ölçülen: 0.6943)
CHAR_W_RATIO_DIGIT = 0.77   # 0-9 (ölçülen: 0.7634)
CHAR_W_RATIO_SPACE = 0.40   # ' ' (ölçülen: 0.3817, güvenlik payıyla yukarı yuvarlandı)
CHAR_W_RATIO_PUNCT = 0.56   # : . , ( ) % - / (ölçülen: 0.5511)
CHAR_W_RATIO_SQ = 0.46      # '²' (ölçülen: 0.4577)

_PUNCT_CHARS = set(':.,()%-/')


def estimate_text_width(text, height):
    """`text`'in (yaklaşık) gerçek çizim genişliğini tahmin eder -- `height`
    o metnin DXF TEXT yüksekliği (kod 40), zaten hedef birimde (template
    lokal ya da gerçek dünya -- çağıran hangi birimde çalışıyorsa)."""
    text = text.replace('%%U', '').replace('%%u', '')
    total = 0.0
    for ch in text:
        if ch == ' ':
            r = CHAR_W_RATIO_SPACE
        elif ch == '²':
            r = CHAR_W_RATIO_SQ
        elif ch in _PUNCT_CHARS:
            r = CHAR_W_RATIO_PUNCT
        elif ch.isdigit():
            r = CHAR_W_RATIO_DIGIT
        elif ch.islower():
            r = CHAR_W_RATIO_LOWER
        else:
            r = CHAR_W_RATIO_UPPER  # büyük harf + tanınmayan her şey
        total += r * height
    return total
