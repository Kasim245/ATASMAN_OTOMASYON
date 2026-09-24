"""Faz 1 MVP web app: tek kullanıcı, girişsiz -- nokta dosyası + saha DXF'i
yükle, tespit edilen iş kümelerinden birini seç, bilgileri doldur, ataşman
DXF'ini indir.

Flask ile yazıldı (FastAPI değil): bu geliştirme ortamının ağ erişimi PyPI'a
kapalı olduğu için FastAPI kurulamadı, ama Flask + Jinja2 + python-multipart
zaten hazır kurulu geliyordu -- işlevsel olarak fark yok, ikisi de aynı işi
görüyor. Gerçek sunucuya (Render) taşınırken bu hiçbir şeyi değiştirmez.
"""
import os
import secrets
import shutil
import tempfile
import uuid

from flask import Flask, render_template, request, send_file, redirect, url_for, flash, session, g

from .core.survey import (
    parse_survey_candidates, describe_clusters, classify_unclassified_piece,
    build_reconstruction_suggestions, CLUSTER_RADIUS_M,
)
from .core.preview import render_run_preview_svg
from .core.generator import AtasmanInput, generate_atasman
from .core.config import (
    TEMPLATES, POINT_CODE_TABLE, MAHALLE_DXF_PATH, PREFIX_LABELS, MANUAL_PIECE_CHOICES,
)
from .core.db import (
    init_db, save_atasman, list_hakedis_numbers, get_records,
    get_unit_prices, set_unit_prices, delete_record, T_KEYS,
    allocate_item_codes, count_users, create_user, get_user_by_username,
    get_user_by_id, get_user_by_email, update_user_info, set_user_password,
    create_password_token, get_password_token, kullan_password_token,
    list_users, user_atasman_stats, per_user_atasman_counts,
    list_isler, get_is_by_id, get_user_isler, set_user_isler,
)
from .core.icmal_xlsx import build_icmal_workbook
from .core.mailer import send_mail, MailGonderilemedi
from .core import auth

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-me')
init_db()

_LOGO_PATH = os.path.join(app.static_folder, 'logo.png')


@app.context_processor
def _inject_branding():
    # kullanıcı kendi logosunu app/static/logo.png olarak eklediğinde başlıkta
    # otomatik görünür -- dosya yoksa sadece yazı gösterilir, kırık resim
    # ikonu çıkmaz. nav_isler/nav_current_is da her sayfada üst menüdeki iş
    # değiştiriciyi çizebilmek için buradan geliyor (bkz. _resolve_current_is).
    return {'has_logo': os.path.exists(_LOGO_PATH),
            'nav_isler': getattr(g, 'isler', []),
            'nav_current_is': getattr(g, 'current_is', None)}


@app.before_request
def _require_setup_or_login():
    """Sistemde hiç kullanıcı yoksa (ilk çalıştırma), her istek /kurulum'a
    yönlendirilir -- ilk Yönetici hesabı oluşturulana kadar başka hiçbir
    sayfa açılamaz. Kurulum bittikten sonra bu kontrol hep False döner ve
    normal @auth.login_required kontrolleri devreye girer."""
    if request.endpoint in ('kurulum', 'static'):
        return None
    if count_users() == 0:
        return redirect(url_for('kurulum'))
    if session.get('user_id'):
        g.isler, g.current_is = _resolve_current_is()
    else:
        g.isler, g.current_is = [], None
    return None

# In-memory session store: Faz 1 is single-user/single-process, so this is
# fine. Faz 2 (çok kullanıcılı) replaces this with the real database. The
# İcmal ataşman kayıtları ise db.py üzerinden SQLite'a kalıcı yazılır --
# hakediş dönemi boyunca (haftalarca) hatırlanması gerektiği için bu geçici
# in-memory store'a değil, diske yazılır.
SESSIONS = {}


def _session_dir(session_id):
    return os.path.join(tempfile.gettempdir(), 'atasman-app-sessions', session_id)


def _my_isler():
    """Oturumdaki kullanıcının çalışabileceği işler -- yönetici dahil HERKES
    sadece kendine atanmış işleri görür (Personel sayfasındaki iş işaretleme
    kutularıyla belirlenir). Bilinçli bir tercih: bu sistem başka firmalara
    da satılacağı için bir firmanın yöneticisi otomatik olarak o firmanın
    HER işini görmemeli -- hangi işleri kimin (kendisi dahil) yöneteceğine
    yine kendisi karar veriyor. Yeni kurulan bir hesapta ilk yönetici tüm
    işlere otomatik atanır (bkz. kurulum() ve db.py::init_db migration)."""
    return get_user_isler(session['user_id'])


def _resolve_current_is():
    """Oturumdaki kullanıcının şu an hangi iş havuzunda çalıştığını belirler.
    Ataşman üretim ekranındaki eski seçici kaldırıldı (per the user: farklı
    işlerin sistemleri/havuzları -- hakediş numaraları, mahalle sayaçları,
    birim fiyatlar -- birbirinden tamamen ayrı olmalı, ama bunu her dosya
    yüklemede yeniden seçtirmek yerine, üst menüdeki iş değiştiriciden
    seçilip oturumda hatırlanıyor). Tek işi olan personel için otomatik
    seçilir, hiç bir şey seçilmemiş/geçersizse listenin ilk işi kullanılır."""
    isler = _my_isler()
    if not isler:
        return isler, None
    current_id = session.get('current_is_id')
    current = next((i for i in isler if i['id'] == current_id), None)
    if not current:
        current = isler[0]
        session['current_is_id'] = current['id']
    return isler, current


@app.post('/is-degistir')
@auth.login_required
def is_degistir():
    """Üst menüdeki iş değiştirici -- kullanıcı birden fazla işe atanmışsa
    şu an hangi işin havuzunda (hakediş numaraları, mahalle sayaçları, birim
    fiyatlar) çalıştığını buradan değiştirir, bulunduğu sayfaya geri döner."""
    is_id = request.form.get('is_id', type=int)
    musait = {i['id']: i for i in _my_isler()}
    secili = musait.get(is_id)
    if secili:
        session['current_is_id'] = secili['id']
        flash(f'"{secili["ad"]}" işine geçtiniz.')
    else:
        flash('Bu işe erişiminiz yok.')
    next_url = request.form.get('next') or url_for('panel')
    return redirect(next_url)


def _render_clusters(session_id, candidates, hakedis_no, radius=None):
    """candidates listesinden (yeniden inşa edilip onaylanmış parçalar dahil
    edilmiş haliyle) kümeleri hesaplar, oturuma kaydeder, küme ekranını
    döner -- hem /analyze (yeniden inşa önerisi yoksa direkt) hem de
    /reconstruct (öneriler onaylandıktan sonra) hem de /regroup (kullanıcı
    yakınlık mesafesini elle değiştirdiğinde) tarafından kullanılır.

    `candidates` ve kullanılan `radius`, oturuma kaydediliyor (`sess['candidates']`,
    `sess['cluster_radius']`) ki /regroup, dosyaları yeniden yükletmeden AYNI
    parça listesini farklı bir mesafeyle yeniden kümeleyebilsin -- tek bir
    sabit mesafenin her saha dosyası için doğru olamayacağı gerçek verilerle
    doğrulandı (bkz. survey.py::CLUSTER_RADIUS_M yorumu), o yüzden kesin
    cevap yerine değiştirilebilir bir ilk tahmin sunuluyor."""
    if radius is None:
        radius = CLUSTER_RADIUS_M
    sess = SESSIONS[session_id]
    groups = describe_clusters(candidates, sess.get('bg_path'), sess.get('mahalle_dxf_path'),
                                radius=radius)
    if not groups:
        flash('Saha DXF\'inde tanınan hiçbir parke/bordür/oluk parçası bulunamadı '
              '(nokta dosyasındaki kodlarla saha DXF\'indeki kapalı çizgiler eşleşmedi).')
        return redirect(url_for('index'))
    sess['groups'] = groups
    sess['candidates'] = candidates
    sess['cluster_radius'] = radius
    return render_template('clusters.html', session_id=session_id, groups=groups,
                            hakedis_no=hakedis_no, templates=TEMPLATES, enumerate=enumerate,
                            manual_piece_choices=MANUAL_PIECE_CHOICES, cluster_radius=radius)


@app.route('/kurulum', methods=['GET', 'POST'])
def kurulum():
    # count_users() > 0 olduktan sonra bu sayfa artık kullanılamaz -- ilk
    # Yönetici hesabı bir kere oluşturulur, sonrası /personel'den yönetilir.
    if count_users() > 0:
        return redirect(url_for('giris'))
    if request.method == 'POST':
        ad_soyad = request.form.get('ad_soyad', '').strip()
        kullanici_adi = request.form.get('kullanici_adi', '').strip()
        email = request.form.get('email', '').strip()
        sifre = request.form.get('sifre', '')
        sifre2 = request.form.get('sifre2', '')
        if not ad_soyad or not kullanici_adi or not sifre:
            flash('Tüm alanları doldurmalısınız.')
        elif sifre != sifre2:
            flash('Girdiğiniz iki şifre birbiriyle uyuşmuyor.')
        elif len(sifre) < 4:
            flash('Şifre en az 4 karakter olmalı.')
        else:
            yeni_id = create_user(ad_soyad, kullanici_adi, auth.hash_password(sifre), 'yonetici',
                                   email=email)
            # ilk yönetici, sistemi kurup henüz kimseye iş dağıtmamışken
            # kilitli kalmasın diye baştan TÜM işlere atanır -- daha sonra
            # Personel sayfasından kendi ve başkalarının atamalarını
            # istediği gibi düzenleyebilir.
            set_user_isler(yeni_id, [i['id'] for i in list_isler()])
            flash('Yönetici hesabınız oluşturuldu, şimdi giriş yapabilirsiniz.')
            return redirect(url_for('giris'))
    return render_template('kurulum.html')


@app.route('/giris', methods=['GET', 'POST'])
def giris():
    if session.get('user_id'):
        return redirect(url_for('panel'))
    next_url = request.values.get('next') or url_for('panel')
    if request.method == 'POST':
        kullanici_adi = request.form.get('kullanici_adi', '').strip()
        sifre = request.form.get('sifre', '')
        user = get_user_by_username(kullanici_adi) if kullanici_adi else None
        if not user or not auth.verify_password(user['sifre_hash'], sifre):
            flash('Kullanıcı adı veya şifre hatalı.')
        else:
            session['user_id'] = user['id']
            session['ad_soyad'] = user['ad_soyad']
            session['rol'] = user['rol']
            return redirect(request.form.get('next') or url_for('panel'))
    return render_template('giris.html', next_url=next_url)


@app.get('/cikis')
def cikis():
    session.clear()
    flash('Çıkış yapıldı.')
    return redirect(url_for('giris'))


@app.get('/panel')
@auth.login_required
def panel():
    is_admin = auth.is_admin()
    own_stats = user_atasman_stats(None if is_admin else session['user_id'])
    per_user = per_user_atasman_counts() if is_admin else None
    return render_template('panel.html', is_admin=is_admin, own_stats=own_stats, per_user=per_user)


@app.get('/hakkinda')
@auth.login_required
def hakkinda():
    return render_template('hakkinda.html')


@app.get('/yardim')
@auth.login_required
def yardim():
    return render_template('yardim.html')


def _sifre_baglantisi_gonder(kullanici, konu, govde_onsoz, gecerlilik_saat):
    """create_password_token() + send_mail() ortak akışı -- hem yeni hesap
    açılışında hem de şifre sıfırlama isteklerinde kullanılır. Mail
    gönderilemezse (SMTP ayarlanmamışsa ya da sandbox/ağ engeli varsa)
    işlemi durdurmuyoruz -- bağlantıyı doğrudan ekranda göstererek
    yöneticinin elle iletebilmesini sağlıyoruz."""
    token = create_password_token(kullanici['id'], gecerlilik_saat=gecerlilik_saat)
    link = url_for('sifre_belirle', token=token, _external=True)
    govde = (f"Merhaba {kullanici['ad_soyad']},\n\n{govde_onsoz}\n\n{link}\n\n"
             f"Bu bağlantı {gecerlilik_saat} saat geçerlidir.")
    try:
        send_mail(kullanici['email'], konu, govde)
        return True, link
    except MailGonderilemedi as exc:
        flash(f"Mail gönderilemedi ({exc}). Bağlantıyı kendiniz iletin: {link}")
        return False, link


@app.route('/personel', methods=['GET', 'POST'])
@auth.admin_required
def personel():
    if request.method == 'POST':
        ad_soyad = request.form.get('ad_soyad', '').strip()
        kullanici_adi = request.form.get('kullanici_adi', '').strip()
        email = request.form.get('email', '').strip()
        rol = request.form.get('rol', 'personel')
        meslek = request.form.get('meslek', '').strip()
        telefon = request.form.get('telefon', '').strip()
        is_ids = [int(i) for i in request.form.getlist('is_ids') if i.isdigit()]
        if rol not in ('personel', 'yonetici'):
            rol = 'personel'
        if not ad_soyad or not kullanici_adi or not email:
            flash('Ad Soyad, kullanıcı adı ve e-posta zorunludur.')
        elif get_user_by_username(kullanici_adi):
            flash(f'"{kullanici_adi}" kullanıcı adı zaten alınmış, başka bir tane seçin.')
        elif get_user_by_email(email):
            flash(f'"{email}" e-postası zaten başka bir hesapta kayıtlı.')
        else:
            # Şifreyi yönetici belirlemiyor -- hesaba geçici, kullanılamaz bir
            # şifre atanır, kişi kendi şifresini e-postasına gelen bağlantıdan
            # kendisi belirler (bkz. core/mailer.py, /sifre-belirle).
            gecici_hash = auth.hash_password(secrets.token_urlsafe(24))
            yeni_id = create_user(ad_soyad, kullanici_adi, gecici_hash, rol,
                                   meslek=meslek, telefon=telefon, email=email)
            set_user_isler(yeni_id, is_ids)
            kullanici = get_user_by_id(yeni_id)
            basarili, link = _sifre_baglantisi_gonder(
                kullanici, 'Ataşman Otomasyonu hesabınız oluşturuldu',
                f"Ataşman Otomasyonu'nda sizin için bir hesap açıldı (kullanıcı adınız: "
                f"{kullanici_adi}). Şifrenizi belirlemek için aşağıdaki bağlantıya tıklayın:",
                gecerlilik_saat=72,
            )
            if basarili:
                flash(f'{ad_soyad} için hesap oluşturuldu, şifre belirleme bağlantısı {email} adresine gönderildi.')
            else:
                flash(f'{ad_soyad} için hesap oluşturuldu.')
    tum_isler = list_isler()
    users = list_users()
    for u in users:
        u['is_ids'] = [i['id'] for i in get_user_isler(u['id'])]
    return render_template('personel.html', users=users, isler=tum_isler)


@app.post('/personel/<int:user_id>/guncelle')
@auth.admin_required
def personel_guncelle(user_id):
    """Personel tablosundaki açılır panelden -- bir personelin (yönetici
    dahil, kendisi dahil) meslek/telefon/e-posta bilgisi ve hangi işlerde
    çalışabileceği sonradan değiştirilir. Kayıt oluşturulduktan sonra yeni
    bir iş eklenip birine atanmak istendiğinde, ya da e-postası olmayan
    eski bir hesaba e-posta eklenmesi gerektiğinde kullanılır."""
    kullanici = get_user_by_id(user_id)
    if not kullanici:
        flash('Personel bulunamadı.')
        return redirect(url_for('personel'))
    meslek = request.form.get('meslek', '').strip()
    telefon = request.form.get('telefon', '').strip()
    email = request.form.get('email', '').strip()
    is_ids = [int(i) for i in request.form.getlist('is_ids') if i.isdigit()]
    if not email:
        flash('E-posta zorunludur.')
        return redirect(url_for('personel'))
    mevcut = get_user_by_email(email)
    if mevcut and mevcut['id'] != user_id:
        flash(f'"{email}" e-postası zaten başka bir hesapta kayıtlı.')
        return redirect(url_for('personel'))
    update_user_info(user_id, meslek, telefon, email)
    set_user_isler(user_id, is_ids)
    flash(f'{kullanici["ad_soyad"]} için bilgiler güncellendi.')
    return redirect(url_for('personel'))


@app.post('/personel/<int:user_id>/sifre-sifirla')
@auth.admin_required
def personel_sifre_sifirla(user_id):
    """Personel listesinden -- şifreyi görmeden, o kişiye yeni bir şifre
    belirleme bağlantısı gönderir (bkz. üstteki açıklama: yönetici şifreyi
    hiçbir zaman göremez/belirleyemez, sadece bu süreci başlatabilir)."""
    kullanici = get_user_by_id(user_id)
    if not kullanici:
        flash('Personel bulunamadı.')
        return redirect(url_for('personel'))
    if not kullanici.get('email'):
        flash(f'{kullanici["ad_soyad"]} için kayıtlı e-posta yok -- önce e-posta ekleyip kaydedin.')
        return redirect(url_for('personel'))
    basarili, link = _sifre_baglantisi_gonder(
        kullanici, 'Ataşman Otomasyonu şifre sıfırlama',
        "Şifrenizi sıfırlamak için aşağıdaki bağlantıya tıklayın. Bu isteği siz "
        "yapmadıysanız yöneticinizle iletişime geçin.",
        gecerlilik_saat=2,
    )
    if basarili:
        flash(f'{kullanici["ad_soyad"]} için şifre sıfırlama bağlantısı {kullanici["email"]} adresine gönderildi.')
    return redirect(url_for('personel'))


@app.route('/sifre-belirle/<token>', methods=['GET', 'POST'])
def sifre_belirle(token):
    """Hem yeni hesap açılışında hem de şifre sıfırlamada kullanılan aynı
    sayfa -- geçerli bir token'sız (süresi dolmuş/kullanılmış/uydurma)
    buraya girilemez."""
    kayit = get_password_token(token)
    if not kayit:
        flash('Bu bağlantının süresi dolmuş ya da daha önce kullanılmış. Yeni bir bağlantı isteyin.')
        return redirect(url_for('sifre_unuttum'))
    if request.method == 'POST':
        sifre = request.form.get('sifre', '')
        sifre2 = request.form.get('sifre2', '')
        if sifre != sifre2:
            flash('Girdiğiniz iki şifre birbiriyle uyuşmuyor.')
        elif len(sifre) < 4:
            flash('Şifre en az 4 karakter olmalı.')
        else:
            set_user_password(kayit['kullanici_id'], auth.hash_password(sifre))
            kullan_password_token(token)
            flash('Şifreniz belirlendi, şimdi giriş yapabilirsiniz.')
            return redirect(url_for('giris'))
    return render_template('sifre_belirle.html', ad_soyad=kayit['ad_soyad'])


@app.route('/sifre-unuttum', methods=['GET', 'POST'])
def sifre_unuttum():
    """Personelin kendi kendine şifre sıfırlama isteği -- hangi kullanıcı
    adı/e-postanın var olup olmadığını ele vermemek için sonuç her zaman
    aynı genel mesajı gösterir."""
    if request.method == 'POST':
        girilen = request.form.get('kullanici_adi_veya_email', '').strip()
        kullanici = get_user_by_username(girilen) or get_user_by_email(girilen)
        if kullanici and kullanici.get('email'):
            _sifre_baglantisi_gonder(
                kullanici, 'Ataşman Otomasyonu şifre sıfırlama',
                "Şifrenizi sıfırlamak için aşağıdaki bağlantıya tıklayın. Bu isteği siz "
                "yapmadıysanız bu maili yok sayabilirsiniz.",
                gecerlilik_saat=2,
            )
        flash('Hesabınıza kayıtlı bir e-posta varsa, şifre sıfırlama bağlantısı gönderildi.')
        return redirect(url_for('giris'))
    return render_template('sifre_unuttum.html')


@app.get('/')
@auth.login_required
def index():
    return render_template('upload.html', templates=TEMPLATES, point_codes=POINT_CODE_TABLE,
                            current_hakedis_no=session.get('current_hakedis_no', ''))


@app.post('/analyze')
@auth.login_required
def analyze():
    hakedis_no = request.form.get('hakedis_no', '').strip()
    ncn_file = request.files.get('ncn')
    saha_file = request.files.get('saha_dxf')
    bg_file = request.files.get('background_dxf')

    # Hangi iş (proje) için üretim yapılıyor -- artık bu ekranda ayrıca
    # sorulmuyor, üst menüdeki iş değiştiriciden seçilip oturumda hatırlanan
    # (g.current_is, bkz. _resolve_current_is) iş kullanılıyor. Personel
    # sadece kendine atanmış işleri seçebiliyor zaten (o iş değiştiricide
    # bile görünmüyor), burada yine de savunma amaçlı kontrol ediliyor.
    secili_is = g.current_is
    if not secili_is:
        flash('Hiçbir işe atanmamışsınız. Yöneticinizden sizi bir işe atamasını isteyin.')
        return redirect(url_for('index'))
    if not secili_is['aktif']:
        flash(f'"{secili_is["ad"]}" için ataşman üretimi henüz sisteme eklenmedi -- '
              f'yakında entegre edilecek. Üst menüdeki iş değiştiriciden aktif bir işe geçebilirsiniz.')
        return redirect(url_for('index'))

    if not hakedis_no:
        flash('Hangi hakedişte olduğunuzu girmelisiniz.')
        return redirect(url_for('index'))
    if not ncn_file or not ncn_file.filename:
        flash('Nokta dosyası (.ncn) seçmelisiniz.')
        return redirect(url_for('index'))
    # saha_dxf artık ZORUNLU DEĞİL: bazen sahada noktalar kodlarıyla
    # ölçülmüş ama NetCAD'de hiç alan/çizgi çizilmemiş oluyor -- bu durumda
    # sadece nokta dosyasından, kodu olup hiç kullanılmayan noktaları
    # bulup kullanıcıya "bunları birleştireyim mi" diye soruyoruz (aşağıda).

    # bir sonraki dosya yüklemesinde bu hakediş no'yu ve seçili işi tekrar
    # hatırlat -- kullanıcı değiştirene kadar her seferinde yeniden seçmesin.
    session['current_hakedis_no'] = hakedis_no
    session['current_is_id'] = secili_is['id']

    session_id = uuid.uuid4().hex
    sdir = _session_dir(session_id)
    os.makedirs(sdir, exist_ok=True)

    ncn_path = os.path.join(sdir, 'points.ncn')
    ncn_file.save(ncn_path)

    saha_path = None
    if saha_file and saha_file.filename:
        saha_path = os.path.join(sdir, 'saha.dxf')
        saha_file.save(saha_path)

    bg_path = None
    if bg_file and bg_file.filename:
        bg_path = os.path.join(sdir, 'background.dxf')
        bg_file.save(bg_path)

    mahalle_dxf_path = MAHALLE_DXF_PATH if os.path.exists(MAHALLE_DXF_PATH) else None
    try:
        candidates, pts, consumed_ids = parse_survey_candidates(ncn_path, saha_path)
        suggestions = build_reconstruction_suggestions(pts, consumed_ids)
    except Exception as exc:
        shutil.rmtree(sdir, ignore_errors=True)
        flash(f"Dosyalar okunurken hata oluştu: {exc}")
        return redirect(url_for('index'))

    SESSIONS[session_id] = {
        'ncn_path': ncn_path, 'saha_path': saha_path, 'bg_path': bg_path,
        'mahalle_dxf_path': mahalle_dxf_path, 'hakedis_no': hakedis_no, 'is_id': secili_is['id'],
        'base_candidates': candidates, 'pts': pts,
    }

    if suggestions:
        # kodu var ama hiç çizgisi çizilmemiş nokta grupları bulundu --
        # önce kullanıcıya görsel önizleme + onay/atla sorusu gösteriyoruz,
        # kümeleme ancak bundan sonra yapılıyor (bkz. /reconstruct).
        SESSIONS[session_id]['pending_suggestions'] = suggestions
        previews = [render_run_preview_svg(s['ids'], pts) for s in suggestions]
        return render_template('reconstruct.html', session_id=session_id,
                                hakedis_no=hakedis_no,
                                suggestions=suggestions, previews=previews,
                                manual_piece_choices=MANUAL_PIECE_CHOICES,
                                enumerate=enumerate, zip=zip)

    result = _render_clusters(session_id, candidates, hakedis_no)
    if not SESSIONS[session_id].get('groups'):
        shutil.rmtree(sdir, ignore_errors=True)
        SESSIONS.pop(session_id, None)
    return result


@app.post('/reconstruct')
@auth.login_required
def reconstruct():
    """Kullanıcı, kodu var ama saha DXF'inde hiç çizgisi olmayan nokta
    gruplarından hangilerini "evet, bunları birleştir" dediğini bildirdikten
    sonra (bkz. reconstruct.html), onaylananları normal candidates listesine
    katıp küme ekranına geçer. Onaylanmayanlar sessizce dışarıda kalır --
    başka bir şeyi bozmaz, sadece kullanılmamış nokta olarak kalırlar."""
    session_id = request.form.get('session_id')
    sess = SESSIONS.get(session_id)
    if not sess or 'pending_suggestions' not in sess:
        flash('Oturum süresi doldu, dosyaları tekrar yükleyin.')
        return redirect(url_for('index'))

    confirmed = []
    for idx, s in enumerate(sess['pending_suggestions']):
        if request.form.get(f'confirm_{idx}'):
            confirmed.append(s['candidate'])

    merged = sess['base_candidates'] + confirmed
    result = _render_clusters(session_id, merged, sess['hakedis_no'])
    if not sess.get('groups'):
        shutil.rmtree(_session_dir(session_id), ignore_errors=True)
        SESSIONS.pop(session_id, None)
    return result


@app.post('/regroup')
@auth.login_required
def regroup():
    """Kullanıcı, tespit ekranındaki otomatik gruplamanın yanlış olduğunu
    (birbirinden farklı işleri tek ataşmanda birleştirdiğini, ya da tek bir
    işi gereksiz yere parçaladığını) düşünürse, dosyaları yeniden yüklemeden,
    AYNI parça listesini farklı bir yakınlık mesafesiyle yeniden kümelemesini
    sağlar -- tek bir sabit mesafenin her saha dosyası için doğru
    olamayacağı gerçek verilerle doğrulandı (bkz. survey.py::CLUSTER_RADIUS_M)."""
    session_id = request.form.get('session_id')
    sess = SESSIONS.get(session_id)
    if not sess or 'candidates' not in sess:
        flash('Oturum süresi doldu, dosyaları tekrar yükleyin.')
        return redirect(url_for('index'))
    try:
        radius = float(request.form.get('cluster_radius', '').replace(',', '.'))
        if radius <= 0:
            raise ValueError
    except ValueError:
        flash('Yakınlık mesafesi pozitif bir sayı olmalı (örn. 60).')
        return _render_clusters(session_id, sess['candidates'], sess['hakedis_no'],
                                 radius=sess.get('cluster_radius'))
    return _render_clusters(session_id, sess['candidates'], sess['hakedis_no'], radius=radius)


@app.post('/generate')
@auth.login_required
def generate():
    session_id = request.form.get('session_id')
    sess = SESSIONS.get(session_id)
    if not sess:
        flash('Oturum süresi doldu, dosyaları tekrar yükleyin.')
        return redirect(url_for('index'))

    try:
        group_idx = int(request.form.get('group_idx'))
        group = sess['groups'][group_idx]
    except (TypeError, ValueError, IndexError):
        flash('Geçersiz seçim.')
        return redirect(url_for('index'))

    # kodu tanınmayan parçalar için kullanıcının bu formda seçtiği türü
    # (parke/bordür/oluk/atla) uygula -- generate_atasman çağrılmadan önce,
    # aday hala 'unclassified' ise ne olduğunu öğrenmiş oluyoruz.
    for idx, cand in enumerate(group['candidates']):
        if not cand.get('unclassified'):
            continue
        choice = request.form.get(f'piece_type_{idx}', 'skip')
        if choice == 'keep':
            # kullanıcı, koddan otomatik tespit edilen bordür/oluk kırılımının
            # (review_reason='full_bordur_no_parke') doğru olduğunu onayladı --
            # piece_bordur zaten hesaplanmış haliyle kalıyor, sadece onay
            # ekranına tekrar düşmesin diye işaretleniyor.
            cand['unclassified'] = False
            cand['review_reason'] = None
            continue
        if choice == 'skip' or ':' not in choice:
            continue
        choice_key, choice_kind = choice.split(':', 1)
        classify_unclassified_piece(cand, choice_key, choice_kind)

    template_scale = request.form.get('template_scale') or group.get('suggested_scale')
    if template_scale not in TEMPLATES:
        flash(f"Bu küme hiçbir mevcut şablona sığmıyor "
              f"(bbox={group['bbox']}). Şu an sadece 250 ölçek şablonu mevcut.")
        return redirect(url_for('index'))

    inp = AtasmanInput(
        template_scale=template_scale,
        candidates=group['candidates'],
        mahalle=request.form.get('mahalle', '').strip(),
        cadde_sokak=request.form.get('cadde_sokak', '').strip(),
        hakedis_no=request.form.get('hakedis_no', '').strip(),
        sira_no=request.form.get('sira_no', '').strip(),
        imalat_bitis_tarihi=request.form.get('imalat_bitis_tarihi', '').strip(),
        aykome_no=request.form.get('aykome_no', '').strip(),
        background_dxf_path=sess['bg_path'],
    )

    try:
        result = generate_atasman(inp)
    except Exception as exc:
        flash(f"Üretim sırasında hata oluştu: {exc}")
        return redirect(url_for('index'))

    # Ataşmanın verilerini İcmal için kalıcı kaydet -- DXF indirmeyi
    # engellemesin diye kayıt hatası sessizce yutuluyor, sadece kullanıcıya
    # bilgi veriliyor.
    try:
        # İcmal, parke kalemlerini minha alanı düşülmüş (NET) haliyle alır --
        # ataşman DXF'inin kendi başlık bloğu ise GROSS (result['totals']) ile
        # doldu, ayrıca ayrı bir Minha toplamı gösteriyor.
        save_atasman(inp.hakedis_no, inp.sira_no, inp.mahalle, inp.cadde_sokak,
                     inp.aykome_no, result['totals_net'],
                     kapi_no=request.form.get('kapi_no', '').strip(),
                     kullanici_id=session.get('user_id'), is_id=sess.get('is_id'))
    except Exception as exc:
        flash(f"DXF üretildi, ama İcmal kaydı tutulamadı: {exc}")

    out_name = f"atasman_{inp.hakedis_no}-{inp.sira_no}_{inp.mahalle}.dxf".replace(' ', '_')
    sdir = _session_dir(session_id)
    out_path = os.path.join(sdir, out_name)
    with open(out_path, 'wb') as f:
        f.write(result['dxf_bytes'])

    # bu ataşmandaki her kalemden kaç tane olduğunu (generator.py) mahallenin
    # kendi kalıcı, hiç durmayan sayacına göre gerçek koda çevir (YP6, YP7...)
    # -- NetCAD'in "Adı" alanı DXF ile yazılamadığı için bu kodlar çizime
    # değil, bu sonuç ekranına yazılıyor; kullanıcı NetCAD'de elle giriyor.
    try:
        item_codes = allocate_item_codes(inp.hakedis_no, inp.mahalle, result.get('item_codes', {}),
                                          is_id=sess.get('is_id'))
    except Exception as exc:
        item_codes = {}
        flash(f"Malzeme kalemi kodları atanamadı: {exc}")

    return render_template('result.html', session_id=session_id, dosya=out_name,
                            item_codes=item_codes, prefix_labels=PREFIX_LABELS,
                            mahalle=inp.mahalle, cadde_sokak=inp.cadde_sokak,
                            hakedis_no=inp.hakedis_no, sira_no=inp.sira_no,
                            totals=result['totals'], minha_count=result.get('minha_count', 0))


@app.get('/indir')
@auth.login_required
def indir_dosya():
    session_id = request.args.get('session_id', '')
    dosya = os.path.basename(request.args.get('dosya', ''))
    sdir = _session_dir(session_id)
    path = os.path.join(sdir, dosya)
    if not dosya or not os.path.isfile(path):
        flash('Dosya bulunamadı, ataşmanı tekrar üretin.')
        return redirect(url_for('index'))
    return send_file(path, as_attachment=True, download_name=dosya)


@app.get('/icmal')
@auth.login_required
def icmal_index():
    # Her iş kendi hakediş/kayıt havuzunu tutar -- üst menüde şu an seçili
    # olan işin (g.current_is) dışındaki kayıtlar hiç görünmez. Personel
    # ayrıca sadece kendi ürettiği ataşmanları görür; Yönetici hepsini.
    own_id = None if auth.is_admin() else session['user_id']
    hakedis_no = request.args.get('hakedis_no', '').strip()
    current_is = g.current_is
    hakedis_list = list_hakedis_numbers(current_is['id']) if current_is else []
    records = get_records(hakedis_no, current_is['id'], kullanici_id=own_id) \
        if hakedis_no and current_is else []
    unit_prices = get_unit_prices(current_is['id']) if current_is else {}
    return render_template('icmal.html', hakedis_list=hakedis_list, hakedis_no=hakedis_no,
                            records=records, unit_prices=unit_prices, t_keys=T_KEYS)


@app.post('/icmal/birim-fiyat')
@auth.admin_required
def icmal_birim_fiyat():
    if not g.current_is:
        flash('Birim fiyat güncellemek için önce bir işe atanmış olmalısınız.')
        return redirect(url_for('icmal_index'))
    prices = {}
    for k in T_KEYS:
        v = request.form.get(f'fiyat_{k}', '').strip()
        if v:
            try:
                prices[k] = float(v.replace(',', '.'))
            except ValueError:
                pass
    set_unit_prices(g.current_is['id'], prices)
    flash('Birim fiyatlar güncellendi.')
    return redirect(url_for('icmal_index', hakedis_no=request.form.get('hakedis_no', '')))


@app.post('/icmal/sil')
@auth.admin_required
def icmal_sil():
    record_id = request.form.get('record_id')
    hakedis_no = request.form.get('hakedis_no', '')
    if record_id:
        delete_record(int(record_id))
        flash('Kayıt silindi.')
    return redirect(url_for('icmal_index', hakedis_no=hakedis_no))


@app.get('/icmal/indir')
@auth.admin_required
def icmal_indir():
    hakedis_no = request.args.get('hakedis_no', '').strip()
    if not hakedis_no:
        flash('Hakediş no seçmelisiniz.')
        return redirect(url_for('icmal_index'))
    if not g.current_is:
        flash('İndirmek için önce bir işe atanmış olmalısınız.')
        return redirect(url_for('icmal_index'))
    records = get_records(hakedis_no, g.current_is['id'])
    if not records:
        flash(f"{hakedis_no} nolu hakedişte kayıtlı ataşman yok.")
        return redirect(url_for('icmal_index'))
    unit_prices = get_unit_prices(g.current_is['id'])
    wb = build_icmal_workbook(hakedis_no, records, unit_prices)
    sdir = os.path.join(tempfile.gettempdir(), 'atasman-app-sessions')
    os.makedirs(sdir, exist_ok=True)
    out_path = os.path.join(sdir, f"icmal_{hakedis_no}.xlsx")
    wb.save(out_path)
    return send_file(out_path, as_attachment=True,
                      download_name=f"ICMAL_{hakedis_no}_NOLU_HAKEDIS.xlsx")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)), debug=True)
