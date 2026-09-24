"""Persistent record of every generated ataşman's summary row (mahalle,
cadde/sokak, kroki no, T1-T8 miktarları), needed to compile the İcmal hakediş
Excel once a payment period is closed.

Why this exists: the İcmal is a rollup of EVERY ataşman produced during one
hakediş period (the real reference file had 50+ rows for "4 NOLU HAKEDİŞ"
alone), and that period can span weeks -- but Faz 1's web app otherwise
treats every request as independent and remembers nothing between them. This
module adds just enough persistence to bridge that gap, without waiting for
the full multi-user Faz 2 database: a single SQLite file (Python stdlib, no
install needed), one row per ataşman, keyed by (hakediş no, sıra no) so
re-generating the same ataşman overwrites its row instead of duplicating it.

Also holds the "ayarlar" (settings) table for unit prices (TL per m²/m per
item) -- per the user, these are fixed for the life of the contract, but
still editable from the /icmal page in case the contract is renegotiated.

And "mahalle_sayaclari": within one hakediş, each mahalle keeps its own
running counter per material-item prefix (EP=eski parke, YP=yeni parke,
EB=eski bordür, YB=yeni bordür, O=oluk, KP=küp, M=minha -- see ITEM_PREFIX
in config.py), e.g. Akabe's 6th yeni parke piece in hakediş 4 is "YP6" --
and this counter must keep incrementing seamlessly across ataşmanlar
generated weeks apart WITHIN THAT HAKEDİŞ, never restart per DXF. But per
the user, it's scoped to (hakediş no, mahalle, prefix), not just (mahalle,
prefix): when hakediş 1 closes and hakediş 2 starts, every mahalle's
counters start over at 1 -- so switching the "hangi hakediştesiniz" field
on the upload page is itself what resets them, nothing else has to happen.
generator.py only counts how many of each prefix exist WITHIN one ataşman
(it doesn't know about other ataşmanlar); this module is what turns that
per-ataşman count into actual persistent, per-hakediş sequential codes
(allocate_item_codes()), the same way save_atasman() turns a per-ataşman
totals dict into a persistent İcmal row.
"""
import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta

from .config import DB_PATH

T_KEYS = ['T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'T8']

# Matches row 130 of the real İCMAL MG 4 Nolu Hakediş.xlsx reference file.
DEFAULT_UNIT_PRICES = {
    'T1': 50, 'T2': 50, 'T3': 50, 'T4': 25, 'T5': 10, 'T6': 235, 'T7': 485, 'T8': 215,
}


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    cols_def = ', '.join(f'{k.lower()} REAL DEFAULT 0' for k in T_KEYS)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS atasmanlar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hakedis_no TEXT NOT NULL,
            sira_no TEXT NOT NULL,
            mahalle TEXT,
            cadde_sokak TEXT,
            aykome_no TEXT,
            kapi_no TEXT,
            {cols_def},
            created_at TEXT,
            UNIQUE(hakedis_no, sira_no)
        )
    """)
    conn.execute("CREATE TABLE IF NOT EXISTS ayarlar (key TEXT PRIMARY KEY, value TEXT)")
    # Birim fiyatlar artık işe göre ayrı tutuluyor (bkz. aşağıdaki "isler"
    # yorumu) -- varsayılan değerler burada önceden yazılmıyor, get_unit_prices()
    # zaten hiç kaydı olmayan bir iş için DEFAULT_UNIT_PRICES ile dolduruyor.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mahalle_sayaclari (
            hakedis_no TEXT NOT NULL,
            mahalle TEXT NOT NULL,
            prefix TEXT NOT NULL,
            son_no INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (hakedis_no, mahalle, prefix)
        )
    """)
    # Faz 2'nin başlangıcı: giriş/rol sistemi. Tek SQLite dosyasında, ayrı bir
    # veritabanı servisine geçmeden -- küçük bir ekip için bu yeterli.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kullanicilar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_soyad TEXT NOT NULL,
            kullanici_adi TEXT NOT NULL UNIQUE,
            sifre_hash TEXT NOT NULL,
            rol TEXT NOT NULL CHECK(rol IN ('yonetici', 'personel')),
            created_at TEXT NOT NULL
        )
    """)
    # eski (giriş sistemi öncesi) veritabanlarında atasmanlar tablosunda
    # kullanici_id kolonu yok -- varsa dokunma, yoksa ekle (veri kaybı olmaz).
    cols = [r[1] for r in conn.execute("PRAGMA table_info(atasmanlar)").fetchall()]
    if 'kullanici_id' not in cols:
        conn.execute("ALTER TABLE atasmanlar ADD COLUMN kullanici_id INTEGER")
    # Personelin mesleği (Harita Mühendisi, Tekniker, vs.) ve telefon numarası --
    # personel listesinde ve ileride iş atamalarında gösterilmek üzere.
    kcols = [r[1] for r in conn.execute("PRAGMA table_info(kullanicilar)").fetchall()]
    if 'meslek' not in kcols:
        conn.execute("ALTER TABLE kullanicilar ADD COLUMN meslek TEXT")
    if 'telefon' not in kcols:
        conn.execute("ALTER TABLE kullanicilar ADD COLUMN telefon TEXT")
    # Personelin e-postası -- artık hesap açılırken şifreyi yönetici belirlemiyor,
    # bu adrese bir "şifreni belirle" bağlantısı gönderiliyor (bkz. sifre_token
    # tablosu ve main.py::personel/sifre_belirle). Eski kayıtlarda boş kalır.
    if 'email' not in kcols:
        conn.execute("ALTER TABLE kullanicilar ADD COLUMN email TEXT")

    # Şifre belirleme/sıfırlama bağlantıları -- tek kullanımlık, süreli. Token'ın
    # kendisi (ham hali) sadece e-postaya konur; burada sadece hash'i saklanır,
    # böylece veritabanı okunsa bile linkler taklit edilemez.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sifre_token (
            token_hash TEXT PRIMARY KEY,
            kullanici_id INTEGER NOT NULL REFERENCES kullanicilar(id),
            olusturulma TEXT NOT NULL,
            son_kullanma TEXT NOT NULL,
            kullanildi INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Firmanın farklı iş/proje türleri -- per the user: aynı temel mantık
    # (nokta+saha DXF'ten ataşman üretimi) ama ataşman şablonu ve çıktı
    # kalemleri işe göre değişiyor. Şu an sadece "Karatay Aykome Parke Tamir
    # İşi" (aktif=1) gerçekten üretim yapabiliyor -- diğerleri kullanıcı
    # tarafından eğitilip sisteme entegre edilene kadar seçilebilir ama
    # "yakında" olarak işaretli kalıyor (aktif=0), bkz. main.py::analyze().
    conn.execute("""
        CREATE TABLE IF NOT EXISTS isler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad TEXT NOT NULL UNIQUE,
            aciklama TEXT,
            aktif INTEGER NOT NULL DEFAULT 0,
            sira INTEGER NOT NULL DEFAULT 0
        )
    """)
    if conn.execute("SELECT COUNT(*) FROM isler").fetchone()[0] == 0:
        for sira, (ad, aciklama, aktif) in enumerate([
            ('Karatay Aykome Parke Tamir İşi', 'Karatay Belediyesi -- parke/tretuvar tamirat işi', 1),
            ('Karatay Aykome Asfalt Tamir Yapım İşi', 'Karatay Belediyesi -- asfalt tamir/yapım işi', 0),
            ('Meram Belediyesi Köyler Parke Yapım İşi', 'Meram Belediyesi -- köylerde parke yapım işi', 0),
            ('Selçuklu Belediyesi Sıfır Parke Yapım İşi', 'Selçuklu Belediyesi -- sıfır parke yapım işi', 0),
        ], start=1):
            conn.execute(
                "INSERT INTO isler (ad, aciklama, aktif, sira) VALUES (?, ?, ?, ?)",
                (ad, aciklama, aktif, sira),
            )

    # personel <-> iş çoka-çok atama (bir personel birden fazla işte çalışabilir)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kullanici_isler (
            kullanici_id INTEGER NOT NULL REFERENCES kullanicilar(id),
            is_id INTEGER NOT NULL REFERENCES isler(id),
            PRIMARY KEY (kullanici_id, is_id)
        )
    """)
    # bu kavram sisteme yeni eklendiğinde (Personel'e iş ataması gelmeden
    # önce) oluşturulmuş, hiçbir işe atanmamış hesaplar sessizce erişimsiz
    # kalmasın diye otomatik atanır -- ama bu SADECE BİR KEZ, ilk geçişte
    # yapılır (aşağıdaki bayrakla işaretlenir). Yoksa bundan sonra bilerek
    # "hiçbir işe atanmasın" denilen yeni bir personel de her sunucu yeniden
    # başlatıldığında buraya sessizce geri eklenirdi. Yönetici hesapları
    # TÜM işlere atanır (sistem başka firmalara da satılacağı için artık
    # yöneticiler de -- tıpkı personel gibi -- sadece kendilerine atanmış
    # işleri görüyor, bkz. main.py::_my_isler; bu yüzden var olan tek
    # yönetici hiçbir şeye erişemez hale gelmesin diye baştan hepsine
    # atanıyor), personel hesapları eskisi gibi sadece ilk aktif işe.
    ilk_is = conn.execute("SELECT id FROM isler WHERE aktif = 1 ORDER BY sira LIMIT 1").fetchone()
    tum_is_idler = [r['id'] for r in conn.execute("SELECT id FROM isler").fetchall()]
    gecis_yapildi = conn.execute(
        "SELECT 1 FROM ayarlar WHERE key = 'isler_ilk_atama_yapildi'"
    ).fetchone()
    if ilk_is and not gecis_yapildi:
        atanmamislar = conn.execute("""
            SELECT k.id, k.rol FROM kullanicilar k
            WHERE NOT EXISTS (SELECT 1 FROM kullanici_isler ki WHERE ki.kullanici_id = k.id)
        """).fetchall()
        for r in atanmamislar:
            hedef_isler = tum_is_idler if r['rol'] == 'yonetici' else [ilk_is['id']]
            for is_id in hedef_isler:
                conn.execute(
                    "INSERT OR IGNORE INTO kullanici_isler (kullanici_id, is_id) VALUES (?, ?)",
                    (r['id'], is_id),
                )
        conn.execute(
            "INSERT OR IGNORE INTO ayarlar (key, value) VALUES ('isler_ilk_atama_yapildi', '1')"
        )

    # her ataşmanın hangi iş için üretildiği -- per the user, farklı işlerin
    # hakediş numaralandırması ve mahalle sayaçları birbirinden TAMAMEN
    # bağımsız olmalı (Karatay Parke'nin "6 nolu hakedişi" ile Asfalt'ın
    # "6 nolu hakedişi" aynı havuz değil). Bu yüzden essiz kombinasyon artık
    # sadece (hakediş no, sıra no) değil, (iş, hakediş no, sıra no).
    acols = [r[1] for r in conn.execute("PRAGMA table_info(atasmanlar)").fetchall()]
    if 'is_id' not in acols:
        conn.execute("ALTER TABLE atasmanlar ADD COLUMN is_id INTEGER")

    # eski kayıtlarda (bu kavram eklenmeden önce üretilmiş) is_id boş --
    # hepsi zaten tek işken üretildiği için ilk aktif işe atanır.
    if ilk_is:
        conn.execute("UPDATE atasmanlar SET is_id = ? WHERE is_id IS NULL", (ilk_is['id'],))

    # SQLite mevcut bir tablonun UNIQUE kısıtını değiştirmeye izin vermiyor --
    # kısıt hâlâ eski (hakedis_no, sira_no) haldeyse tabloyu yeni şemayla
    # baştan kurup verileri taşı.
    tbl_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='atasmanlar'"
    ).fetchone()
    if tbl_row and 'UNIQUE(is_id, hakedis_no, sira_no)' not in (tbl_row['sql'] or ''):
        conn.execute("ALTER TABLE atasmanlar RENAME TO atasmanlar_eski")
        conn.execute(f"""
            CREATE TABLE atasmanlar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hakedis_no TEXT NOT NULL,
                sira_no TEXT NOT NULL,
                mahalle TEXT,
                cadde_sokak TEXT,
                aykome_no TEXT,
                kapi_no TEXT,
                kullanici_id INTEGER,
                is_id INTEGER,
                {cols_def},
                created_at TEXT,
                UNIQUE(is_id, hakedis_no, sira_no)
            )
        """)
        aktarim_kolonlari = (['id', 'hakedis_no', 'sira_no', 'mahalle', 'cadde_sokak', 'aykome_no',
                               'kapi_no', 'kullanici_id', 'is_id']
                              + [k.lower() for k in T_KEYS] + ['created_at'])
        kol_listesi = ', '.join(aktarim_kolonlari)
        conn.execute(f"INSERT INTO atasmanlar ({kol_listesi}) SELECT {kol_listesi} FROM atasmanlar_eski")
        conn.execute("DROP TABLE atasmanlar_eski")

    # mahalle_sayaclari (malzeme kalemi sayaçları -- YP1, YP2...) da aynı
    # sebeple işe göre ayrılıyor: PRIMARY KEY'e is_id eklendi, bu da tabloyu
    # baştan kurmayı gerektiriyor.
    mcols = [r[1] for r in conn.execute("PRAGMA table_info(mahalle_sayaclari)").fetchall()]
    if 'is_id' not in mcols:
        conn.execute("ALTER TABLE mahalle_sayaclari RENAME TO mahalle_sayaclari_eski")
        conn.execute("""
            CREATE TABLE mahalle_sayaclari (
                is_id INTEGER NOT NULL,
                hakedis_no TEXT NOT NULL,
                mahalle TEXT NOT NULL,
                prefix TEXT NOT NULL,
                son_no INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (is_id, hakedis_no, mahalle, prefix)
            )
        """)
        if ilk_is:
            conn.execute("""
                INSERT INTO mahalle_sayaclari (is_id, hakedis_no, mahalle, prefix, son_no)
                SELECT ?, hakedis_no, mahalle, prefix, son_no FROM mahalle_sayaclari_eski
            """, (ilk_is['id'],))
        conn.execute("DROP TABLE mahalle_sayaclari_eski")

    # birim fiyatlar da işe göre ayrı (her sözleşmenin TL fiyatı farklı
    # olabilir) -- eskiden tek global anahtar (birim_fiyat_T1 vb.) kullanılıyordu,
    # var olan değerler varsa ilk aktif işe taşınıp eski anahtarlar silinir.
    eski_fiyatlar = conn.execute(
        "SELECT key, value FROM ayarlar WHERE key LIKE 'birim_fiyat_T_'"
    ).fetchall()
    if eski_fiyatlar:
        if ilk_is:
            for r in eski_fiyatlar:
                t_anahtari = r['key'].replace('birim_fiyat_', '', 1)
                conn.execute("""
                    INSERT INTO ayarlar (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """, (f"birim_fiyat_{ilk_is['id']}_{t_anahtari}", r['value']))
        for r in eski_fiyatlar:
            conn.execute("DELETE FROM ayarlar WHERE key = ?", (r['key'],))

    conn.commit()
    conn.close()


def save_atasman(hakedis_no, sira_no, mahalle, cadde_sokak, aykome_no, totals,
                  kapi_no='', kullanici_id=None, is_id=None):
    """Insert this ataşman's row, or overwrite it if (hakediş no, sıra no)
    already exists (e.g. the same ataşman was re-generated after a fix)."""
    conn = _connect()
    values = {k.lower(): float(totals.get(k, 0) or 0) for k in T_KEYS}
    col_names = ', '.join(values.keys())
    placeholders = ', '.join('?' for _ in values)
    update_cols = ', '.join(f'{k}=excluded.{k}' for k in values)
    conn.execute(f"""
        INSERT INTO atasmanlar (hakedis_no, sira_no, mahalle, cadde_sokak, aykome_no,
                                 kapi_no, kullanici_id, is_id, {col_names}, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, {placeholders}, ?)
        ON CONFLICT(is_id, hakedis_no, sira_no) DO UPDATE SET
            mahalle=excluded.mahalle, cadde_sokak=excluded.cadde_sokak,
            aykome_no=excluded.aykome_no, kapi_no=excluded.kapi_no,
            kullanici_id=excluded.kullanici_id, is_id=excluded.is_id,
            {update_cols}, created_at=excluded.created_at
    """, (hakedis_no, sira_no, mahalle, cadde_sokak, aykome_no, kapi_no, kullanici_id, is_id,
          *values.values(), datetime.now().isoformat(timespec='seconds')))
    conn.commit()
    conn.close()


def list_hakedis_numbers(is_id):
    """Sadece VERİLEN işin havuzundaki hakediş numaraları -- her işin
    hakediş numaralandırması kendi başına, birbirinden bağımsız."""
    conn = _connect()
    rows = conn.execute(
        "SELECT DISTINCT hakedis_no FROM atasmanlar WHERE is_id = ? ORDER BY hakedis_no", (is_id,)
    ).fetchall()
    conn.close()
    return [r['hakedis_no'] for r in rows]


def get_records(hakedis_no, is_id, kullanici_id=None):
    """kullanici_id verilirse sadece o kişinin kayıtları döner (Personel
    rolü için); Yönetici hepsini görebildiği için None bırakır. Her satıra
    ölçen kişinin adı da (varsa) eklenir -- eski kayıtlarda kullanici_id
    boş olabilir, bu durumda 'ad_soyad' None döner. is_id ile her zaman o
    işin havuzuyla sınırlandırılır -- başka bir işin aynı hakediş numarasını
    kullanan kayıtları asla karışmaz."""
    conn = _connect()
    query = """
        SELECT a.*, k.ad_soyad AS olcen_ad_soyad
        FROM atasmanlar a LEFT JOIN kullanicilar k ON k.id = a.kullanici_id
        WHERE a.hakedis_no = ? AND a.is_id = ?
    """
    params = [hakedis_no, is_id]
    if kullanici_id is not None:
        query += " AND a.kullanici_id = ?"
        params.append(kullanici_id)
    query += " ORDER BY CAST(a.sira_no AS INTEGER), a.sira_no"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unit_prices(is_id):
    """Bu işin birim fiyatları -- hiç özelleştirilmemişse DEFAULT_UNIT_PRICES
    ile doldurulur, her iş kendi sözleşme fiyatlarını bağımsız tutar."""
    conn = _connect()
    prefix = f'birim_fiyat_{is_id}_'
    rows = conn.execute(
        "SELECT key, value FROM ayarlar WHERE key LIKE ?", (prefix + '%',)
    ).fetchall()
    conn.close()
    out = dict(DEFAULT_UNIT_PRICES)
    out.update({r['key'][len(prefix):]: float(r['value']) for r in rows})
    return out


def set_unit_prices(is_id, prices):
    conn = _connect()
    for k, v in prices.items():
        conn.execute("""
            INSERT INTO ayarlar (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (f'birim_fiyat_{is_id}_{k}', str(v)))
    conn.commit()
    conn.close()


def delete_record(record_id):
    conn = _connect()
    conn.execute("DELETE FROM atasmanlar WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()


def allocate_item_codes(hakedis_no, mahalle, prefix_counts, is_id):
    """prefix_counts: {'YP': 3, 'EB': 1, ...} -- how many of each item-code
    prefix this one ataşman has (generator.py's result['item_codes']).
    Returns {'YP': ['YP6', 'YP7', 'YP8'], 'EB': ['EB4']}: this mahalle's
    running counter per prefix, continued from wherever it last left off
    WITHIN THIS HAKEDİŞ (per the user: each new hakediş starts every
    mahalle's counters over at 1 again -- "1 nolu hakediş bitti, artık 2
    nolu hakedişte Akabe 1'den başlıyor") and persisted so the next
    ataşman in the SAME hakediş continues from here. is_id ile ayrıca işe
    göre ayrı tutulur -- Karatay Parke'nin Akabe mahallesi ile başka bir
    işin (varsa) aynı isimli mahallesi birbirine karışmaz."""
    hakedis_key = (hakedis_no or '').strip()
    mahalle_key = (mahalle or '').strip().upper()
    conn = _connect()
    out = {}
    for prefix, count in prefix_counts.items():
        if not count:
            continue
        row = conn.execute(
            "SELECT son_no FROM mahalle_sayaclari WHERE is_id = ? AND hakedis_no = ? AND mahalle = ? AND prefix = ?",
            (is_id, hakedis_key, mahalle_key, prefix),
        ).fetchone()
        last = row['son_no'] if row else 0
        codes = [f"{prefix}{last + i}" for i in range(1, int(count) + 1)]
        new_last = last + int(count)
        conn.execute("""
            INSERT INTO mahalle_sayaclari (is_id, hakedis_no, mahalle, prefix, son_no) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(is_id, hakedis_no, mahalle, prefix) DO UPDATE SET son_no = excluded.son_no
        """, (is_id, hakedis_key, mahalle_key, prefix, new_last))
        out[prefix] = codes
    conn.commit()
    conn.close()
    return out


def count_users():
    conn = _connect()
    n = conn.execute("SELECT COUNT(*) FROM kullanicilar").fetchone()[0]
    conn.close()
    return n


def create_user(ad_soyad, kullanici_adi, sifre_hash, rol, meslek='', telefon='', email=''):
    conn = _connect()
    cur = conn.execute("""
        INSERT INTO kullanicilar (ad_soyad, kullanici_adi, sifre_hash, rol, meslek, telefon, email, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (ad_soyad.strip(), kullanici_adi.strip(), sifre_hash, rol,
          (meslek or '').strip(), (telefon or '').strip(), (email or '').strip(),
          datetime.now().isoformat(timespec='seconds')))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_user_by_username(kullanici_adi):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM kullanicilar WHERE kullanici_adi = ?", (kullanici_adi.strip(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = _connect()
    row = conn.execute("SELECT * FROM kullanicilar WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM kullanicilar WHERE email = ? COLLATE NOCASE", ((email or '').strip(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_info(kullanici_id, meslek, telefon, email):
    conn = _connect()
    conn.execute("""
        UPDATE kullanicilar SET meslek = ?, telefon = ?, email = ? WHERE id = ?
    """, ((meslek or '').strip(), (telefon or '').strip(), (email or '').strip(), kullanici_id))
    conn.commit()
    conn.close()


def set_user_password(kullanici_id, sifre_hash):
    conn = _connect()
    conn.execute("UPDATE kullanicilar SET sifre_hash = ? WHERE id = ?", (sifre_hash, kullanici_id))
    conn.commit()
    conn.close()


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_password_token(kullanici_id, gecerlilik_saat=48):
    """Şifre belirleme/sıfırlama bağlantısı için tek kullanımlık, süreli bir
    token üretir -- ham token'ı döner (bu, e-postaya konulacak; veritabanına
    sadece hash'i yazılır). Aynı kişi için önceki tüm bağlantılar geçersiz
    kılınır (birden fazla eski link aynı anda geçerli kalmasın diye)."""
    token = secrets.token_urlsafe(32)
    simdi = datetime.now()
    son_kullanma = (simdi + timedelta(hours=gecerlilik_saat)).isoformat(timespec='seconds')
    conn = _connect()
    conn.execute("DELETE FROM sifre_token WHERE kullanici_id = ?", (kullanici_id,))
    conn.execute("""
        INSERT INTO sifre_token (token_hash, kullanici_id, olusturulma, son_kullanma, kullanildi)
        VALUES (?, ?, ?, ?, 0)
    """, (_hash_token(token), kullanici_id, simdi.isoformat(timespec='seconds'), son_kullanma))
    conn.commit()
    conn.close()
    return token


def get_password_token(token):
    """Geçerli (süresi dolmamış, daha önce kullanılmamış) bir token ise
    ilgili kaydı (kullanıcı bilgileriyle birlikte) döner, değilse None."""
    conn = _connect()
    row = conn.execute("""
        SELECT t.*, k.ad_soyad, k.kullanici_adi FROM sifre_token t
        JOIN kullanicilar k ON k.id = t.kullanici_id
        WHERE t.token_hash = ?
    """, (_hash_token(token),)).fetchone()
    conn.close()
    if not row or row['kullanildi']:
        return None
    if row['son_kullanma'] < datetime.now().isoformat(timespec='seconds'):
        return None
    return dict(row)


def kullan_password_token(token):
    conn = _connect()
    conn.execute("UPDATE sifre_token SET kullanildi = 1 WHERE token_hash = ?", (_hash_token(token),))
    conn.commit()
    conn.close()


def list_users():
    conn = _connect()
    rows = conn.execute("""
        SELECT k.id, k.ad_soyad, k.kullanici_adi, k.rol, k.meslek, k.telefon, k.email, k.created_at,
               GROUP_CONCAT(i.ad, ', ') AS isler
        FROM kullanicilar k
        LEFT JOIN kullanici_isler ki ON ki.kullanici_id = k.id
        LEFT JOIN isler i ON i.id = ki.is_id
        GROUP BY k.id ORDER BY k.ad_soyad
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_isler(sadece_aktif=False):
    conn = _connect()
    query = "SELECT * FROM isler"
    if sadece_aktif:
        query += " WHERE aktif = 1"
    query += " ORDER BY sira"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_is_by_id(is_id):
    conn = _connect()
    row = conn.execute("SELECT * FROM isler WHERE id = ?", (is_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_isler(kullanici_id):
    """Bu personelin çalışabileceği işlerin listesi (yönetici için main.py
    tarafında tüm işler kullanılır, bu fonksiyon sadece personel rolü için
    çağrılır)."""
    conn = _connect()
    rows = conn.execute("""
        SELECT i.* FROM isler i
        JOIN kullanici_isler ki ON ki.is_id = i.id
        WHERE ki.kullanici_id = ?
        ORDER BY i.sira
    """, (kullanici_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_user_isler(kullanici_id, is_ids):
    """Bu personelin çalışabileceği işleri baştan tanımlar (var olan
    atamaların yerine geçer)."""
    conn = _connect()
    conn.execute("DELETE FROM kullanici_isler WHERE kullanici_id = ?", (kullanici_id,))
    for is_id in is_ids:
        conn.execute(
            "INSERT OR IGNORE INTO kullanici_isler (kullanici_id, is_id) VALUES (?, ?)",
            (kullanici_id, is_id),
        )
    conn.commit()
    conn.close()


def user_atasman_stats(kullanici_id=None):
    """Ana panel için: toplam ataşman sayısı ve son 30 gündeki sayı --
    kullanici_id verilirse sadece o kişinin, verilmezse herkesin (Yönetici
    paneli için)."""
    conn = _connect()
    where = "WHERE kullanici_id = ?" if kullanici_id is not None else ""
    params = (kullanici_id,) if kullanici_id is not None else ()
    total = conn.execute(f"SELECT COUNT(*) FROM atasmanlar {where}", params).fetchone()[0]
    son30 = conn.execute(f"""
        SELECT COUNT(*) FROM atasmanlar {where} {'AND' if where else 'WHERE'}
        created_at >= datetime('now', '-30 days')
    """, params).fetchone()[0]
    conn.close()
    return {'toplam': total, 'son_30_gun': son30}


def per_user_atasman_counts():
    """Yönetici paneli için: her personelin toplam kaç ataşman ürettiği."""
    conn = _connect()
    rows = conn.execute("""
        SELECT k.ad_soyad, COUNT(a.id) AS adet
        FROM kullanicilar k LEFT JOIN atasmanlar a ON a.kullanici_id = k.id
        GROUP BY k.id ORDER BY adet DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_mahalle_counters(hakedis_no, mahalle, is_id):
    """Current son_no per prefix for a mahalle within one hakediş (for display only)."""
    hakedis_key = (hakedis_no or '').strip()
    mahalle_key = (mahalle or '').strip().upper()
    conn = _connect()
    rows = conn.execute(
        "SELECT prefix, son_no FROM mahalle_sayaclari WHERE is_id = ? AND hakedis_no = ? AND mahalle = ? ORDER BY prefix",
        (is_id, hakedis_key, mahalle_key),
    ).fetchall()
    conn.close()
    return {r['prefix']: r['son_no'] for r in rows}
