"""Per-template-scale constants and the shared code/material-item tables.

Per the user: there's only ever one physical ataşman sheet layout (the CIZPEN
title-block frame we have from the 250-scale reference) -- a coarser plot
scale doesn't need its own blank DXF file, it's the same sheet printed at a
coarser plot scale, so the SAME template geometry just covers more
real-world ground per drawing unit. Concretely: the 250 template's 'scale'
(4.0 m per template-local unit) corresponds to plot scale 1/250, so 1/1000
uses the identical file with scale = 4.0 * (1000/250) = 16.0 -- everything
else (work_area_local, placeholder positions/text) is unchanged, because
it's literally the same drawing.

Faz 1.1: per the user, 1/1000 is a hard ceiling -- a survey batch too large
even for that must never be silently drawn at some coarser, unreadable
scale. So TEMPLATES only ever offers 250 and 1000 (see below); anything
bigger is rejected upstream by survey.py::suggest_scale() returning None,
which main.py/clusters.html surface as a "doesn't fit any template" warning
that asks the user to re-split the batch (via /regroup) instead of guessing.
"""
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')

# district-wide mahalle boundary reference (67 mahalle, ~5.5MB) -- small
# enough to bundle in the repo, unlike the 239MB KARATAY background file,
# which stays a per-request user upload for now.
# Faz 1.10: artık DXF değil, Konya Büyükşehir'in açık veri portalından
# indirilen ve TM33'e dönüştürülen JSON (bkz. mahalle.py, scripts/
# convert_mahalle_geojson.py) -- eski mahalleler.dxf sadece Karatay'ın 67
# mahallesini içeriyordu ve bazı gerçek noktaları kapsamıyordu.
MAHALLE_BOUNDARIES_PATH = os.path.join(DATA_DIR, 'reference', 'mahalleler_konya.json')

# runtime state (not source data) -- accumulated ataşman records + unit-price
# settings, used to compile the İcmal hakediş Excel. Kept outside data/ and
# git-ignored: this grows/changes as the app is used, unlike everything else
# in data/ which is fixed reference material committed to the repo.
#
# DATA_DISK_PATH lets this point at a mounted persistent disk in production
# (Render's filesystem is otherwise wiped on every deploy/restart) --
# defaults to the local instance/ folder for development, where no such
# disk exists. On Render this is set to the disk's mount path (see README's
# deployment section), so the SQLite file survives restarts.
_DATA_DISK = os.environ.get('DATA_DISK_PATH') or os.path.join(os.path.dirname(DATA_DIR), 'instance')
DB_PATH = os.path.join(_DATA_DISK, 'atasman_kayitlari.db')

# Faz 1.6: üretilen her ataşman DXF'inin kalıcı bir kopyası -- aynı _DATA_DISK
# üzerinde (Render'da kalıcı disk, yerelde instance/), üretim anındaki oturumun
# geçici tempdir'inden (main.py::_session_dir, sunucu yeniden başlayınca/
# deploy'da silinir) FARKLI olarak sunucu yeniden başlasa bile silinmiyor.
# "İndirilecek Dosyalar" sayfası (main.py::dosyalarim) ataşmanları buradan
# okuyup tekrar indirtebiliyor -- veritabanındaki atasmanlar.dosya_yolu
# kolonu bu dizine GÖRE (relative) bir yol tutuyor, mutlak değil, ki disk
# bağlama noktası (DATA_DISK_PATH) ileride değişirse eski kayıtlar bozulmasın.
ATASMAN_CIKTI_DIR = os.path.join(_DATA_DISK, 'uretilen_atasmanlar')

_BASE_SCALE = 250
_BASE_TEMPLATE = {
    'path': os.path.join(DATA_DIR, 'templates', 'sablon_250.dxf'),
    # real-world meters per one template-local drawing unit, at plot scale 1/250
    'scale': 4.0,
    # the *inner* "imalat alanı" work-area rectangle on layer T_KLİŞE, in
    # template-local coordinates -- this is the box new content is
    # centered in and background content is clipped to. NOT the outer
    # CIZPEN paper/title-block frame, which is larger.
    'work_area_local': {'xmin': -11.18, 'xmax': 32.79, 'ymin': -20.18, 'ymax': 30.95},
    # local position of the "Ataşman No" text cell (left-aligned with "Kroki No")
    'atasman_no_x_local': -12.91117657431584,
    # local position of the cadde/sokak name cell (same title block, under mahalle)
    'cadde_local': (-6.128022938977493, 35.7),
    'cadde_text_height_local': 0.42,
    # blank-template placeholder strings on layer T_KLİŞE, and what each
    # one is replaced by (job data is substituted in at generation time)
    'mahalle_placeholder': '-İSİM- MH.',
    'atasman_no_placeholder': '1',
    'tarih_placeholder': 'İMALATıN BITIŞ TARIHI : 00/05/2025',
    'aykome_prefix_placeholder': 'Aykome No: ',
    # leftover junk text in the blank template (residue from the real
    # drawing it was derived from) -- always stripped, unrelated to any
    # job's own data
    'text_remove_literal': {'10418. SK', '%%UAYKOME NO', 'KBF'},
    # old cadde/sokak placeholder position is removed (it's the "10418. SK"
    # text above); the actual cadde/sokak text is redrawn on its own new
    # layer at this nearby position, matching the real reference example
    'sokak_placeholder': '10418. SK',
}

# 1/250 şablonu tek kaynak: diğer ölçekler aynı dosyayı, sadece 'scale'
# oranlanmış olarak kullanır (bkz. modül docstring'i). Yeni bir DXF şablonu
# gerekmiyor -- CIZPEN çerçevesi aynı, sadece kapsadığı arazi büyüyor.
#
# Faz 1.1: kullanıcının belirttiği sabit ÜST SINIR -- 1/1000'den daha kaba
# (1500, 2000...) bir ölçek ASLA otomatik seçilmemeli. Böyle bir küme
# suggest_scale()'e göre "hiçbir şablona sığmıyor" sayılır ve clusters.html
# ekranında kullanıcıya sorulur/uyarılır (bkz. main.py::generate ve
# clusters.html) -- sessizce çok kaba bir ölçekte (okunaksız) üretim yapmak
# yerine. Daha büyük bir alanı tek ataşmanda değil, birden çok ayrı ataşmana
# bölerek üretmek gerekiyor (bkz. survey.py::CLUSTER_RADIUS_M, describe_clusters).
#
# Faz 1.2: ara ölçek 1/500 eklendi -- kullanıcı, bir yüklemedeki farklı
# gruplara farklı ölçeklerin uygun olabileceğini belirtti (ör. birbirine çok
# yakın 3 parça 1/250'ye sığar, biraz daha yayılmış 5 parça ancak 1/500'e
# sığar, geniş bir alana yayılmış 7 parça da 1/1000 gerektirir) -- artık
# gruplama bu üç ölçeği de göz önünde bulundurarak her grup için MÜMKÜN OLAN
# EN İNCE ölçeği seçiyor, sabit tek bir ölçek varsaymıyor.
TEMPLATES = {str(_BASE_SCALE): dict(_BASE_TEMPLATE)}
for _plot_scale in (500, 1000):
    _tpl = dict(_BASE_TEMPLATE)
    _tpl['scale'] = _BASE_TEMPLATE['scale'] * (_plot_scale / _BASE_SCALE)
    TEMPLATES[str(_plot_scale)] = _tpl

# ---- shared ortak nokta kod tablosu (field-collected point codes) ----
# küp taşı bordür/oluk gibi bir kenar/uzunluk kalemi DEĞİL -- parke gibi
# tüm parça alanı üzerinden ödeniyor (T3 - Küp Parke, m²), bu yüzden
# eprk/yprk ile aynı PARKE_CODE_MAP'te.
PARKE_CODE_MAP = {'eprk': 'T7', 'yprk': 'T6', 'küp': 'T3'}
BORDUR_CODE_MAP = {'ebrdr': 'T5', 'ybrdr': 'T4'}
OLUK_CODES = {'olk'}
MINHA_CODES = {'m70'}

# Gerçek saha verisinde aynı malzeme için farklı yazımlar görülebiliyor --
# ör. "Ybrdr" (büyük harf) ya da "oluk"/"minha" (kısaltmasız) -- kod eşleşmesi
# points.py::load_ncn() içinde her zaman küçük harfe çevrilip bu tablodan
# geçiriliyor, böylece yukarıdaki kanonik kodlarla (ebrdr/ybrdr/olk/m70)
# birebir aynı şekilde çalışıyor. Yeni bir yazım farkı görülürse buraya bir
# satır eklemek yeterli -- eşleşme mantığının geri kalanı hiç değişmez.
CODE_ALIASES = {
    'oluk': 'olk',
    'minha': 'm70',
}

# bordür/oluk taşının gerçek genişliği: sahada ölçülen parke kenar noktalarına
# paralel, bu kadar dışa kaydırılarak çizilir (kullanıcının anlattığı NetCAD
# alışkanlığıyla aynı: alanı ölçtükten sonra bordür/oluk hattı buraya paralel
# 12cm atılıyor). SADECE çizim konumunu etkiler -- uzunluk (hakediş miktarı)
# ham nokta-nokta mesafesinden hesaplanır ve bu ofsetten etkilenmez (düz bir
# hattı yana kaydırmak uzunluğunu değiştirmez). 30cm oluk değeri "~30cm" olarak
# hatırlanıyor -- kesin değeri kullanıcıyla teyit edilmeli. Küp artık bir
# alan kalemi olduğu için (yukarı bakın) bu ofset küpe hiç uygulanmıyor.
BORDUR_OFFSET_M = 0.12
OLUK_OFFSET_M = 0.30

POINT_CODE_TABLE = [
    {'kod': 'eprk', 'aciklama': 'Eski (yerinde) parke', 'kalem': 'T7 - Yerinde'},
    {'kod': 'yprk', 'aciklama': 'Yeni (idareden) parke', 'kalem': 'T6 - İdareden'},
    {'kod': 'ebrdr', 'aciklama': 'Eski (yerinde) bordür', 'kalem': 'T5 - Yerinde'},
    {'kod': 'ybrdr', 'aciklama': 'Yeni (idareden) bordür', 'kalem': 'T4 - İdareden'},
    {'kod': 'olk', 'aciklama': 'Oluk taşı', 'kalem': 'T8 - Oluk Taşı'},
    {'kod': 'küp', 'aciklama': 'Küp taşı (alan üzerinden)', 'kalem': 'T3 - Küp Parke'},
    {'kod': 'm70', 'aciklama': 'Minha (rögar)', 'kalem': 'Minha'},
]

# malzeme kalemi kodu (item code) prefixes: eski parke=EP, yeni parke=YP,
# eski bordur=EB, yeni bordur=YB, oluk=O, küp=KP, minha=M. Computed for
# internal bookkeeping only -- NOT drawn as visible DXF text (rejected by the
# user: NetCAD's own "Adı" object-name field is where this belongs, but that
# field doesn't round-trip through DXF export at all; tracked as a known gap).
ITEM_PREFIX = {'T7': 'EP', 'T6': 'YP', 'T5': 'EB', 'T4': 'YB', 'T8': 'O', 'T3': 'KP', 'Minha': 'M'}

# prefix -> okunabilir açıklama (sonuç ekranında gösterilir)
PREFIX_LABELS = {
    'EP': 'Eski Parke', 'YP': 'Yeni Parke', 'EB': 'Eski Bordür',
    'YB': 'Yeni Bordür', 'O': 'Oluk Taşı', 'KP': 'Küp Parke', 'M': 'Minha',
}

# sahada kod girilmemiş (veya bilinmeyen bir kod girilmiş) bir parça
# bulunduğunda kullanıcıya sorulan seçenekler -- (kalem, tür, açıklama).
# 'area' seçilirse tüm poligon alanı o kaleme (T7/T6/T3) yazılır; 'length'
# seçilirse -- hangi kenarın bordür/oluk olduğu koddan bilinemediği için --
# poligonun tüm çevresi, kenar kenar, o kaleme (T5/T4/T8) yazılır.
MANUAL_PIECE_CHOICES = [
    ('T7', 'area', 'Eski (yerinde) parke'),
    ('T6', 'area', 'Yeni (idareden) parke'),
    ('T3', 'area', 'Küp taşı'),
    ('T5', 'length', 'Eski (yerinde) bordür (parçanın tüm çevresi)'),
    ('T4', 'length', 'Yeni (idareden) bordür (parçanın tüm çevresi)'),
    ('T8', 'length', 'Oluk taşı (parçanın tüm çevresi)'),
]

LAYER_TO_KEY = {
    'T_1_ANDEZİT_4CM': 'T1', 'T_2_ANDEZİT_6CM': 'T2', 'T_3_KÜP_PARKE': 'T3',
    'T_4_İDRDN_BORDÜR': 'T4', 'T_5_YERİNDE_BORDÜR': 'T5', 'T_6_İDAREDEN_KLTPRK': 'T6',
    'T_7_YERİNDE_KLTPRK': 'T7', 'T_8_OLUK_TAŞI': 'T8', 'T_MİNHA': 'Minha',
}

# parke-ailesi (tüm parça alanı üzerinden ödenen) kalemlerin çizileceği katman
PARKE_LAYER = {'T7': 'T_7_YERİNDE_KLTPRK', 'T6': 'T_6_İDAREDEN_KLTPRK', 'T3': 'T_3_KÜP_PARKE'}
BORDUR_LAYER = {'T4': 'T_4_İDRDN_BORDÜR', 'T5': 'T_5_YERİNDE_BORDÜR', 'T8': 'T_8_OLUK_TAŞI'}

# LAYER table entries the blank template is missing, needed for background
# (imar planı altlığı) content pulled in from a district-wide cadastral DXF.
# ACI color codes matched against the real Akabe_45.Dxf reference file.
# Faz 1.8: Z_YOL_ADI/Z_KAPI_NO renk 7'den 250'ye değiştirildi -- kullanıcının
# "yazılar gözükmüyor" şikayetiyle gönderdiği ekran görüntüsünde, renk 7
# (AutoCAD'in "beyaz/siyah" -- arka plana göre kendini ayarlayan, adaptif
# rengi) kullanılan HER ŞEY (klişedeki tüm yazılar + sokak isimleri + kapı
# no'lar) görünmüyordu, buna karşılık başka renkteki her şey (binalar: 32/132,
# ada kenarı/cadde-sokak: 18) normal görünüyordu -- kullanıcının DXF görüntüleyicisi
# bu adaptif rengi (muhtemelen) her zaman literal beyaz olarak çiziyor, siyah
# kağıt üzerinde görünmez oluyor. 250, ACI paletinde sabit (arka plana göre
# DEĞİŞMEYEN) çok koyu gri/siyaha yakın bir renk -- artık hiçbir görüntüleyici
# konvansiyonuna bağımlı değil.
NEW_LAYERS = [
    ('Z_YAPI_RUHSTLI_PL', '32'),
    ('Z_YAPI_RUHSTSIZ_PL', '132'),
    ('Z_YOL_ADI', '250'),
    ('Z_KAPI_NO', '250'),
    ('ADAKENARI', '18'),
    ('T_CADDE_SOKAK', '18'),
]
