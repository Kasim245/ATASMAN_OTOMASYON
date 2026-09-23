"""Per-template-scale constants and the shared code/material-item tables.

Per the user: there's only ever one physical ataşman sheet layout (the CIZPEN
title-block frame we have from the 250-scale reference) -- "1/1000", "1/1500",
"1/2000" don't need their own blank DXF files at all, they're the same sheet
printed at a coarser plot scale, so the SAME template geometry just covers
more real-world ground per drawing unit. Concretely: the 250 template's
'scale' (4.0 m per template-local unit) corresponds to plot scale 1/250, so
1/1000 uses the identical file with scale = 4.0 * (1000/250) = 16.0, and so
on -- everything else (work_area_local, placeholder positions/text) is
unchanged, because it's literally the same drawing.
"""
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')

# district-wide mahalle boundary reference (67 mahalle, ~5.5MB) -- small
# enough to bundle in the repo, unlike the 239MB KARATAY background file,
# which stays a per-request user upload for now.
MAHALLE_DXF_PATH = os.path.join(DATA_DIR, 'reference', 'mahalleler.dxf')

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
TEMPLATES = {str(_BASE_SCALE): dict(_BASE_TEMPLATE)}
for _plot_scale in (1000, 1500, 2000):
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
NEW_LAYERS = [
    ('Z_YAPI_RUHSTLI_PL', '32'),
    ('Z_YAPI_RUHSTSIZ_PL', '132'),
    ('Z_YOL_ADI', '7'),
    ('Z_KAPI_NO', '7'),
    ('ADAKENARI', '18'),
    ('T_CADDE_SOKAK', '18'),
]
