"""Faz 1 MVP web app: tek kullanıcı, girişsiz -- nokta dosyası + saha DXF'i
yükle, tespit edilen iş kümelerinden birini seç, bilgileri doldur, ataşman
DXF'ini indir.

Flask ile yazıldı (FastAPI değil): bu geliştirme ortamının ağ erişimi PyPI'a
kapalı olduğu için FastAPI kurulamadı, ama Flask + Jinja2 + python-multipart
zaten hazır kurulu geliyordu -- işlevsel olarak fark yok, ikisi de aynı işi
görüyor. Gerçek sunucuya (Render) taşınırken bu hiçbir şeyi değiştirmez.
"""
import os
import shutil
import tempfile
import uuid

from flask import Flask, render_template, request, send_file, redirect, url_for, flash, session

from .core.survey import parse_survey_candidates, describe_clusters
from .core.generator import AtasmanInput, generate_atasman
from .core.config import TEMPLATES, POINT_CODE_TABLE, MAHALLE_DXF_PATH, PREFIX_LABELS
from .core.db import (
    init_db, save_atasman, list_hakedis_numbers, get_records,
    get_unit_prices, set_unit_prices, delete_record, T_KEYS,
    allocate_item_codes,
)
from .core.icmal_xlsx import build_icmal_workbook

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-me')
init_db()

# In-memory session store: Faz 1 is single-user/single-process, so this is
# fine. Faz 2 (çok kullanıcılı) replaces this with the real database. The
# İcmal ataşman kayıtları ise db.py üzerinden SQLite'a kalıcı yazılır --
# hakediş dönemi boyunca (haftalarca) hatırlanması gerektiği için bu geçici
# in-memory store'a değil, diske yazılır.
SESSIONS = {}


def _session_dir(session_id):
    return os.path.join(tempfile.gettempdir(), 'atasman-app-sessions', session_id)


@app.get('/')
def index():
    return render_template('upload.html', templates=TEMPLATES, point_codes=POINT_CODE_TABLE,
                            current_hakedis_no=session.get('current_hakedis_no', ''))


@app.post('/analyze')
def analyze():
    hakedis_no = request.form.get('hakedis_no', '').strip()
    ncn_file = request.files.get('ncn')
    saha_file = request.files.get('saha_dxf')
    bg_file = request.files.get('background_dxf')

    if not hakedis_no:
        flash('Hangi hakedişte olduğunuzu girmelisiniz.')
        return redirect(url_for('index'))
    if not ncn_file or not ncn_file.filename:
        flash('Nokta dosyası (.ncn) seçmelisiniz.')
        return redirect(url_for('index'))
    if not saha_file or not saha_file.filename:
        flash('Saha DXF dosyası seçmelisiniz.')
        return redirect(url_for('index'))

    # bir sonraki dosya yüklemesinde bu hakediş no'yu tekrar hatırlat --
    # kullanıcı hakediş değiştirene kadar her seferinde yeniden yazmasın.
    session['current_hakedis_no'] = hakedis_no

    session_id = uuid.uuid4().hex
    sdir = _session_dir(session_id)
    os.makedirs(sdir, exist_ok=True)

    ncn_path = os.path.join(sdir, 'points.ncn')
    saha_path = os.path.join(sdir, 'saha.dxf')
    ncn_file.save(ncn_path)
    saha_file.save(saha_path)

    bg_path = None
    if bg_file and bg_file.filename:
        bg_path = os.path.join(sdir, 'background.dxf')
        bg_file.save(bg_path)

    mahalle_dxf_path = MAHALLE_DXF_PATH if os.path.exists(MAHALLE_DXF_PATH) else None
    try:
        candidates = parse_survey_candidates(ncn_path, saha_path)
        groups = describe_clusters(candidates, bg_path, mahalle_dxf_path)
    except Exception as exc:
        shutil.rmtree(sdir, ignore_errors=True)
        flash(f"Dosyalar okunurken hata oluştu: {exc}")
        return redirect(url_for('index'))

    if not groups:
        shutil.rmtree(sdir, ignore_errors=True)
        flash('Saha DXF\'inde tanınan hiçbir parke/bordür/oluk parçası bulunamadı '
              '(nokta dosyasındaki kodlarla saha DXF\'indeki kapalı çizgiler eşleşmedi).')
        return redirect(url_for('index'))

    SESSIONS[session_id] = {
        'ncn_path': ncn_path, 'saha_path': saha_path, 'bg_path': bg_path,
        'groups': groups, 'hakedis_no': hakedis_no,
    }
    return render_template('clusters.html', session_id=session_id, groups=groups,
                            hakedis_no=hakedis_no, templates=TEMPLATES, enumerate=enumerate)


@app.post('/generate')
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
                     kapi_no=request.form.get('kapi_no', '').strip())
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
        item_codes = allocate_item_codes(inp.hakedis_no, inp.mahalle, result.get('item_codes', {}))
    except Exception as exc:
        item_codes = {}
        flash(f"Malzeme kalemi kodları atanamadı: {exc}")

    return render_template('result.html', session_id=session_id, dosya=out_name,
                            item_codes=item_codes, prefix_labels=PREFIX_LABELS,
                            mahalle=inp.mahalle, cadde_sokak=inp.cadde_sokak,
                            hakedis_no=inp.hakedis_no, sira_no=inp.sira_no,
                            totals=result['totals'], minha_count=result.get('minha_count', 0))


@app.get('/indir')
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
def icmal_index():
    hakedis_no = request.args.get('hakedis_no', '').strip()
    hakedis_list = list_hakedis_numbers()
    records = get_records(hakedis_no) if hakedis_no else []
    unit_prices = get_unit_prices()
    return render_template('icmal.html', hakedis_list=hakedis_list, hakedis_no=hakedis_no,
                            records=records, unit_prices=unit_prices, t_keys=T_KEYS)


@app.post('/icmal/birim-fiyat')
def icmal_birim_fiyat():
    prices = {}
    for k in T_KEYS:
        v = request.form.get(f'fiyat_{k}', '').strip()
        if v:
            try:
                prices[k] = float(v.replace(',', '.'))
            except ValueError:
                pass
    set_unit_prices(prices)
    flash('Birim fiyatlar güncellendi.')
    return redirect(url_for('icmal_index', hakedis_no=request.form.get('hakedis_no', '')))


@app.post('/icmal/sil')
def icmal_sil():
    record_id = request.form.get('record_id')
    hakedis_no = request.form.get('hakedis_no', '')
    if record_id:
        delete_record(int(record_id))
        flash('Kayıt silindi.')
    return redirect(url_for('icmal_index', hakedis_no=hakedis_no))


@app.get('/icmal/indir')
def icmal_indir():
    hakedis_no = request.args.get('hakedis_no', '').strip()
    if not hakedis_no:
        flash('Hakediş no seçmelisiniz.')
        return redirect(url_for('icmal_index'))
    records = get_records(hakedis_no)
    if not records:
        flash(f"{hakedis_no} nolu hakedişte kayıtlı ataşman yok.")
        return redirect(url_for('icmal_index'))
    unit_prices = get_unit_prices()
    wb = build_icmal_workbook(hakedis_no, records, unit_prices)
    sdir = os.path.join(tempfile.gettempdir(), 'atasman-app-sessions')
    os.makedirs(sdir, exist_ok=True)
    out_path = os.path.join(sdir, f"icmal_{hakedis_no}.xlsx")
    wb.save(out_path)
    return send_file(out_path, as_attachment=True,
                      download_name=f"ICMAL_{hakedis_no}_NOLU_HAKEDIS.xlsx")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)), debug=True)
