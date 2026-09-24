"""Basit, elle yazılmış oturum/rol sistemi. Flask-Login gibi ek bir paket
kurmaya gerek yok -- werkzeug zaten Flask'ın kendi bağımlılığı ve şifre
hash'leme için (generate_password_hash/check_password_hash) yeterli. Flask'ın
kendi çerez tabanlı `session` nesnesi (aynı 'current_hakedis_no' hatırlatması
için kullanılan) burada da kullanıcı kimliğini tutuyor.

2 rol var: 'yonetici' (siz -- her şeyi görür/yönetir, birim fiyatları
düzenler, yeni personel ekler) ve 'personel' (Emre Olgun gibi -- sadece kendi
ürettiği ataşmanları görür/üretir)."""
import functools

from flask import session, redirect, url_for, flash, request
from werkzeug.security import generate_password_hash, check_password_hash

from . import db


def hash_password(raw):
    return generate_password_hash(raw)


def verify_password(hash_, raw):
    return check_password_hash(hash_, raw)


def current_user():
    """Oturumdaki kullanıcıyı (dict) döner, giriş yapılmamışsa None. Her
    çağrıda veritabanından tazeden okunur -- session sadece id/rol/ad_soyad
    gibi hızlı erişim için kısayolları tutar, tek doğru kaynak veritabanı."""
    uid = session.get('user_id')
    if not uid:
        return None
    return db.get_user_by_id(uid)


def is_admin():
    return session.get('rol') == 'yonetici'


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            flash('Devam etmek için giriş yapmalısınız.')
            return redirect(url_for('giris', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            flash('Devam etmek için giriş yapmalısınız.')
            return redirect(url_for('giris', next=request.path))
        if session.get('rol') != 'yonetici':
            flash('Bu sayfaya sadece yöneticiler erişebilir.')
            return redirect(url_for('panel'))
        return view(*args, **kwargs)
    return wrapped
