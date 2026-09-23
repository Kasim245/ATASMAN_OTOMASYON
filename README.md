# Ataşman Otomasyonu

Saha ekibinin GNSS ile topladığı nokta dosyası + NetCAD saha DXF'inden,
otomatik olarak hakediş ataşman DXF'i üreten web uygulaması.

Bu proje, Claude ile birlikte Akabe Mahallesi / Ahmet Bilek Sokak (ataşman
4/45) örneği üzerinde geliştirilen tek-örnekli prototipin genelleştirilmiş,
çok-kullanıcılı web sürümüdür. Genel mimari kararları ve yol haritası için
[Online Sistem Mimarisi](https://claude.ai/code/artifact/270cdc50-ff85-48a5-bbe4-d06750973d91)
dokümanına bakın.

## Faz 1 (şu an burada) neler yapıyor

1. İlk soru: "hangi hakediştesiniz" (bir kere girilir, bir sonraki yüklemede
   tarayıcı hatırlar; değiştirilene kadar aynı kalır). Sonra nokta dosyası
   (.ncn) + saha DXF'i yükle (isteğe bağlı: imar planı altlığı DXF'i).
2. Sistem, saha DXF'indeki her kapalı çizgiyi nokta dosyasındaki kodlarla eşleştirip
   sınıflandırır (eski/yeni parke, küp -- üçü de tüm parça alanı üzerinden ödenen
   kalemler; bordür, oluk -- kenar/uzunluk kalemleri; minha -- parke parçasının
   içindeki kendi küçük poligonu), sonra birbirine yakın parçaları tek bir iş
   kümesi (potansiyel ataşman) olarak gruplar — çünkü gerçek saha dosyaları tek
   bir sokağı değil, günün/bölgenin tamamını içerebiliyor.
3. Her küme için en yakın cadde/sokak ismi ve en yakın kapı no (varsa imar
   planı altlığındaki Z_YOL_ADI / Z_KAPI_NO katmanlarından, ikisi de kümenin
   merkezine en yakın etikete bakılarak -- imalatın önünde durduğu bina
   numarası mantığıyla), mahalle adı (sınır dosyasındaki poligonlardan,
   point-in-polygon ile) ve uyan şablon ölçeği önerilir.
4. Kullanıcı doğru kümeyi seçip mahalle/hakediş/tarih/aykome bilgilerini girer
   (öneriler otomatik dolu gelir, gerekirse düzeltilebilir).
5. Sistem şablonu bu bilgilerle doldurur, parke alanlarını tarar, bordür/oluk
   çizgilerini çizer, (varsa) arka plan içeriğini kırpar ve bitmiş DXF'i indirir.
6. Bu ataşmanın verileri (mahalle, cadde, kroki no, T1-T8 miktarları) otomatik
   olarak İcmal kaydına eklenir (bkz. "İcmal (hakediş özeti)" bölümü), ve
   ataşmandaki her malzeme kalemine mahallenin kendi sürekli sayacından gerçek
   kod atanır (bkz. "Mahalle bazlı malzeme kalemi sayaçları" bölümü). Sonuç
   ekranında DXF indirme bağlantısı ve atanan kodlar birlikte gösterilir.

## Mahalle bazlı malzeme kalemi sayaçları

Her mahalle, HER HAKEDİŞ İÇİNDE kendi malzeme kalemi öneki (EP=eski parke,
YP=yeni parke, EB=eski bordür, YB=yeni bordür, O=oluk, KP=küp, M=minha) için
ayrı bir sayaç tutar -- hakediş 4'te Akabe'nin 6. yeni parke parçası her
zaman "YP6" olur, o hakediş içinde hangi ataşmanda üretildiğine bakılmaksızın,
haftalar sonra gelen bir sonraki ataşman kaldığı yerden devam eder
(`app/core/db.py::allocate_item_codes`, `mahalle_sayaclari` tablosu, anahtar:
hakediş no + mahalle + önek). Kullanıcının kuralı: bir hakediş kapanıp
yenisi başladığında sayaçlar sıfırdan başlar -- bunun için ayrı bir "kapat"
işlemi yok, sadece yükleme ekranındaki "hangi hakediştesiniz" alanını
değiştirmek yeterli, çünkü sayaç zaten hakediş no'ya göre ayrı tutuluyor.

generator.py kendi başına sadece "bu ataşmanda kaç tane YP var" gibi bir
SAYI üretir (o bir ataşmanın içinde neyle karşılaştığını bilir, başka
ataşmanları bilmez); bu sayıyı gerçek, kalıcı sıra numarasına çeviren adım
main.py'de, DXF üretildikten hemen sonra.

NetCAD'in kendi "Adı" (nesne adı) alanı DXF ile yazılamadığı için bu kodlar
çizime gömülmüyor -- ataşman üretildikten sonraki sonuç ekranında listeleniyor,
kullanıcı NetCAD'de ilgili parçalara elle giriyor.

## İcmal (hakediş özeti)

Her ataşman üretildiğinde, o ataşmanın satırı (`app/core/db.py`, SQLite --
Faz 2'nin tam veritabanını beklemeden eklenen hafif bir kalıcı kayıt) hakediş
numarasıyla birlikte saklanır. `/icmal` sayfasından bir hakediş numarası
seçilince o döneme ait tüm ataşmanlar listelenir; "İcmal Excel'ini indir"
gerçek İCMAL formatına (Tanım-1..8 + GPS Alımı sütunları, METRAJ/BİRİM
FİYAT/TUTAR toplam satırları) uyan bir `.xlsx` üretir (`app/core/icmal_xlsx.py`).
Aynı sayfadan birim fiyatlar (TL/m², TL/m -- sözleşme süresince sabit kabul
edilir) da güncellenebilir. "GPS Alımı → ilk Alım" sütunu elle girilen ayrı
bir ön-tahmin olduğu için boş bırakılır; "son Alım" gerçek dosyadaki gibi
`=Tanım-6+Tanım-7` formülüyle otomatik hesaplanır.

Aynı (hakediş no, sıra no) ile tekrar ataşman üretilirse (örn. bir hata
düzeltilip yeniden indirilirse) kayıt güncellenir, yinelenmez.

## Yerel çalıştırma

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python wsgi.py          # http://localhost:8000
```

## Yayına alma (Render)

1. Bu repoyu GitHub'a push edin (henüz push edilmedi -- kod burada, yerel git
   geçmişiyle hazır).
2. [render.com](https://render.com)'da "New +" → "Blueprint" seçin, bu GitHub
   reposunu gösterin. Repo kökündeki `render.yaml` her şeyi (web servisi,
   1 GB'lık kalıcı disk, rastgele bir `SECRET_KEY`) otomatik kurar -- elle
   alan doldurmaya gerek yok.
3. İlk deploy birkaç dakika sürer. Bittiğinde Render size `https://....onrender.com`
   şeklinde bir adres verir, uygulama orada çalışır.

Kalıcı disk neden gerekli: Render'ın standart (disksiz) sunucularında dosya
sistemi her yeniden başlatmada/deploy'da sıfırlanır -- İcmal kayıtları ve
mahalle malzeme sayaçları (SQLite, `app/core/db.py`) bu yüzden kaybolurdu.
`render.yaml`'daki disk + `DATA_DISK_PATH` ortam değişkeni (`app/core/config.py`)
bu veriyi `/data` altında kalıcı tutar. Bu, Render'ın "tek instance + kalıcı
disk" modeli olduğu için (yatay ölçeklenmiyor) -- Faz 1'in zaten tek-süreçli
varsayımıyla (in-memory `SESSIONS`) uyumlu; birden fazla sunucuya
ölçeklendirmek istendiğinde (Faz 2) bu SQLite dosyasının yerini gerçek bir
veritabanı (Supabase Postgres, planlandığı gibi) alması gerekecek.

## Klasör yapısı

```
app/
  core/            DXF okuma/yazma, geometri, kod tablosu, ana üretim mantığı
    config.py        şablon ölçeği sabitleri + ortak nokta kod tablosu
    dxf_io.py        ham DXF grup-kodu okuma/yazma
    dxf_entities.py  yeni DXF varlığı (LWPOLYLINE/LINE/TEXT) oluşturucular
    geometry.py      alan, mesafe, tarama çizgileri, dikdörtgene kırpma
    points.py        nokta dosyası okuma + kod bazlı sınıflandırma
    survey.py        saha DXF'indeki parçaları bulma + yakınlığa göre gruplama
    background.py    büyük imar planı altlığından bölge kırpma (satır satır okuma)
    mahalle.py       mahalle sınır dosyasından point-in-polygon ile mahalle tespiti
    generator.py     hepsini birleştirip bitmiş ataşman DXF'ini üreten ana fonksiyon
    db.py            İcmal kaydı + birim fiyat ayarları + mahalle malzeme sayaçları (SQLite)
    icmal_xlsx.py    İcmal hakediş Excel'ini (openpyxl ile) üreten fonksiyon
  templates/       Jinja2 sayfaları (yükleme formu, küme seçim ekranı, sonuç, İcmal sayfası)
  main.py          Flask uygulaması ve route'lar
render.yaml        Render "Blueprint" -- web servisi + kalıcı disk otomatik kurulumu
data/templates/    boş ataşman şablonları (şu an sadece 250 ölçek)
data/reference/    mahalle sınır dosyası (mahalleler.dxf)
instance/          çalışma zamanı verisi -- İcmal kayıtları (git'e girmez)
tests/fixtures/    yerel test için örnek veri (git'e girmez, bkz. .gitignore)
wsgi.py            gunicorn/yerel çalıştırma giriş noktası
```

## 1000/1500/2000 ölçek şablonları

Ayrı bir DXF dosyasına gerek yok: hepsi 250 ölçek şablonuyla AYNI dosyayı
kullanıyor (aynı CIZPEN başlık çerçevesi), sadece `TEMPLATES` sözlüğünde
`scale` değeri oranlanıyor (`app/core/config.py`, `_BASE_TEMPLATE` +
otomatik 1000/1500/2000 üretimi): 250 şablonun `scale`'i (4.0 m/birim)
1/250 baskı ölçeğine karşılık geliyor, 1/1000 için bu `4.0 * (1000/250) = 16.0`,
1/1500 için `24.0`, 1/2000 için `32.0`. Kullanıcının kendi tarifiyle: "cizpen
aynı, sadece ölçekle" -- iş kümesinin gerçek-dünya boyutuna göre hangi
ölçeğin sığdığına `suggest_scale()` zaten otomatik karar veriyor.

Eğer ileride gerçekten FARKLI bir başlık bloğu/çerçeve tasarımı olan yeni bir
şablon eklenecek olursa (bambaşka bir dosya, oranlama değil), o zaman
`TEMPLATES` sözlüğüne elle yeni bir anahtar eklenir: şablonun kendi
`work_area_local`, `atasman_no_x_local`, `cadde_local`, placeholder metinleri
o dosyadan ölçülüp girilir -- kod tarafında başka hiçbir şey değişmez.

## Neden Flask, mimari planda konuşulan FastAPI değil?

Bu geliştirme ortamının ağ erişimi PyPI'a kapalı olduğu için `fastapi` paketi
kurulamadı; ama Flask + Jinja2 + python-multipart zaten hazır kurulu geliyordu.
İşlevsel olarak ikisi de aynı işi görüyor, bu yüzden yerelde gerçekten test
edilebilen seçenekle devam edildi. Render'a taşırken bu bir şey değiştirmiyor.

## Minha (rögar) muamelesi

Minha kendi küçük kapalı poligonu (tüm noktaları m70 kodlu) olarak ölçülüyor;
sistem bunu, içinde bulunduğu parke parçasına point-in-polygon ile eşleştirip
iki farklı şekilde kullanıyor (kullanıcının tarif ettiği gibi): ataşman
DXF'inin kendi başlık bloğundaki "Minha" alanına, bulunan TÜM minha'ların
toplam alanı (hangi parke kaleminde olursa olsun) GROSS olarak yazılıyor,
parke kalemlerinin kendi alanları da değişmeden (GROSS) kalıyor. İcmal kaydı
ise farklı: her parke kaleminden, içindeki minha alanı düşülmüş (NET) miktar
kullanılıyor -- gerçek İcmal dosyasının da ayrı bir Minha sütunu olmadığı,
düşümün ilgili kaleme netlendiği için (`generator.py`'de `totals` = GROSS
çizim için, `totals_net` = NET İcmal için, ikisi de `survey.py::totals_from_candidates`'ta hesaplanıyor).

## Bilinen sınırlamalar (Faz 2/3'e bırakıldı)

- Bordür/oluk artık ölçülen kenara paralel, taşın kendi genişliği kadar (12cm
  bordür, 30cm oluk -- `config.py`'deki `BORDUR_OFFSET_M`/`OLUK_OFFSET_M`)
  parça poligonunun dışına kaydırılarak çiziliyor (`geometry.py::offset_edge_outward`);
  bu sadece çizim konumu, hakediş miktarı (uzunluk) ham nokta mesafesinden
  hesaplanmaya devam ediyor, ofsetten etkilenmiyor. Kaydırma yönü (dışa doğru)
  ve 30cm'lik oluk değeri makul varsayımlar -- ilk üretilen gerçek ataşmanı
  görünce yön/genişlik doğru mu diye kontrol edilmeli.
- Aykome No eşleştirmesi henüz yok (elle giriliyor; İcmal'deki "Proje No" olarak kullanılıyor).
- NetCAD'in "Adı" (nesne adı) alanı DXF ile yazılamıyor -- parça etiketleri NetCAD'de elle atanıyor.
- İcmal kaydı VE mahalle malzeme sayaçları Faz 1'in geçici (tek-süreçli) SQLite
  dosyasında tutuluyor; Faz 2'ye (gerçek çok-kullanıcılı veritabanı) geçildiğinde
  `db.py`'nin buraya taşınması gerekecek -- iki ekip aynı anda, farklı yerlerden
  bu Faz 1 sunucusuna yazamaz (tek süreç varsayımı).
- İcmal'deki "GPS Alımı → ilk Alım" sütunu sistem tarafından doldurulmuyor (elle girilen ayrı bir ön-tahmin).
