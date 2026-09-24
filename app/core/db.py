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
import os
import sqlite3
from datetime import datetime

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
    for k, v in DEFAULT_UNIT_PRICES.items():
        conn.execute("INSERT OR IGNORE INTO ayarlar (key, value) VALUES (?, ?)",
                     (f'birim_fiyat_{k}', str(v)))
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
    conn.commit()
    conn.close()


def save_atasman(hakedis_no, sira_no, mahalle, cadde_sokak, aykome_no, totals,
                  kapi_no='', kullanici_id=None):
    """Insert this ataşman's row, or overwrite it if (hakediş no, sıra no)
    already exists (e.g. the same ataşman was re-generated after a fix)."""
    conn = _connect()
    values = {k.lower(): float(totals.get(k, 0) or 0) for k in T_KEYS}
    col_names = ', '.join(values.keys())
    placeholders = ', '.join('?' for _ in values)
    update_cols = ', '.join(f'{k}=excluded.{k}' for k in values)
    conn.execute(f"""
        INSERT INTO atasmanlar (hakedis_no, sira_no, mahalle, cadde_sokak, aykome_no,
                                 kapi_no, kullanici_id, {col_names}, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, {placeholders}, ?)
        ON CONFLICT(hakedis_no, sira_no) DO UPDATE SET
            mahalle=excluded.mahalle, cadde_sokak=excluded.cadde_sokak,
            aykome_no=excluded.aykome_no, kapi_no=excluded.kapi_no,
            kullanici_id=excluded.kullanici_id,
            {update_cols}, created_at=excluded.created_at
    """, (hakedis_no, sira_no, mahalle, cadde_sokak, aykome_no, kapi_no, kullanici_id,
          *values.values(), datetime.now().isoformat(timespec='seconds')))
    conn.commit()
    conn.close()


def list_hakedis_numbers():
    conn = _connect()
    rows = conn.execute(
        "SELECT DISTINCT hakedis_no FROM atasmanlar ORDER BY hakedis_no"
    ).fetchall()
    conn.close()
    return [r['hakedis_no'] for r in rows]


def get_records(hakedis_no, kullanici_id=None):
    """kullanici_id verilirse sadece o kişinin kayıtları döner (Personel
    rolü için); Yönetici hepsini görebildiği için None bırakır. Her satıra
    ölçen kişinin adı da (varsa) eklenir -- eski kayıtlarda kullanici_id
    boş olabilir, bu durumda 'ad_soyad' None döner."""
    conn = _connect()
    query = """
        SELECT a.*, k.ad_soyad AS olcen_ad_soyad
        FROM atasmanlar a LEFT JOIN kullanicilar k ON k.id = a.kullanici_id
        WHERE a.hakedis_no = ?
    """
    params = [hakedis_no]
    if kullanici_id is not None:
        query += " AND a.kullanici_id = ?"
        params.append(kullanici_id)
    query += " ORDER BY CAST(a.sira_no AS INTEGER), a.sira_no"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unit_prices():
    conn = _connect()
    rows = conn.execute(
        "SELECT key, value FROM ayarlar WHERE key LIKE 'birim_fiyat_%'"
    ).fetchall()
    conn.close()
    out = dict(DEFAULT_UNIT_PRICES)
    out.update({r['key'].replace('birim_fiyat_', ''): float(r['value']) for r in rows})
    return out


def set_unit_prices(prices):
    conn = _connect()
    for k, v in prices.items():
        conn.execute("""
            INSERT INTO ayarlar (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (f'birim_fiyat_{k}', str(v)))
    conn.commit()
    conn.close()


def delete_record(record_id):
    conn = _connect()
    conn.execute("DELETE FROM atasmanlar WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()


def allocate_item_codes(hakedis_no, mahalle, prefix_counts):
    """prefix_counts: {'YP': 3, 'EB': 1, ...} -- how many of each item-code
    prefix this one ataşman has (generator.py's result['item_codes']).
    Returns {'YP': ['YP6', 'YP7', 'YP8'], 'EB': ['EB4']}: this mahalle's
    running counter per prefix, continued from wherever it last left off
    WITHIN THIS HAKEDİŞ (per the user: each new hakediş starts every
    mahalle's counters over at 1 again -- "1 nolu hakediş bitti, artık 2
    nolu hakedişte Akabe 1'den başlıyor") and persisted so the next
    ataşman in the SAME hakediş continues from here."""
    hakedis_key = (hakedis_no or '').strip()
    mahalle_key = (mahalle or '').strip().upper()
    conn = _connect()
    out = {}
    for prefix, count in prefix_counts.items():
        if not count:
            continue
        row = conn.execute(
            "SELECT son_no FROM mahalle_sayaclari WHERE hakedis_no = ? AND mahalle = ? AND prefix = ?",
            (hakedis_key, mahalle_key, prefix),
        ).fetchone()
        last = row['son_no'] if row else 0
        codes = [f"{prefix}{last + i}" for i in range(1, int(count) + 1)]
        new_last = last + int(count)
        conn.execute("""
            INSERT INTO mahalle_sayaclari (hakedis_no, mahalle, prefix, son_no) VALUES (?, ?, ?, ?)
            ON CONFLICT(hakedis_no, mahalle, prefix) DO UPDATE SET son_no = excluded.son_no
        """, (hakedis_key, mahalle_key, prefix, new_last))
        out[prefix] = codes
    conn.commit()
    conn.close()
    return out


def count_users():
    conn = _connect()
    n = conn.execute("SELECT COUNT(*) FROM kullanicilar").fetchone()[0]
    conn.close()
    return n


def create_user(ad_soyad, kullanici_adi, sifre_hash, rol):
    conn = _connect()
    conn.execute("""
        INSERT INTO kullanicilar (ad_soyad, kullanici_adi, sifre_hash, rol, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (ad_soyad.strip(), kullanici_adi.strip(), sifre_hash, rol,
          datetime.now().isoformat(timespec='seconds')))
    conn.commit()
    conn.close()


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


def list_users():
    conn = _connect()
    rows = conn.execute(
        "SELECT id, ad_soyad, kullanici_adi, rol, created_at FROM kullanicilar ORDER BY ad_soyad"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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


def get_mahalle_counters(hakedis_no, mahalle):
    """Current son_no per prefix for a mahalle within one hakediş (for display only)."""
    hakedis_key = (hakedis_no or '').strip()
    mahalle_key = (mahalle or '').strip().upper()
    conn = _connect()
    rows = conn.execute(
        "SELECT prefix, son_no FROM mahalle_sayaclari WHERE hakedis_no = ? AND mahalle = ? ORDER BY prefix",
        (hakedis_key, mahalle_key),
    ).fetchall()
    conn.close()
    return {r['prefix']: r['son_no'] for r in rows}
