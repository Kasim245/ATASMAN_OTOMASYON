"""Basit SMTP posta gönderimi -- personel hesabı açıldığında ("şifreni
belirle" bağlantısı) ve şifre sıfırlama isteklerinde kullanılır.

Şifreleri artık yönetici belirlemiyor: personel eklendiğinde geçici,
kullanılamaz bir şifre atanıyor, ilgili kişiye bu adresten bir bağlantı
gidiyor, kendi şifresini kendisi belirliyor. Aynı şekilde biri şifresini
unuttuğunda ya da yöneticinin ona yeni bir bağlantı göndermesi gerektiğinde
de buradan gidiyor.

Gerçek gönderim için şu ortam değişkenleri gerekir -- hiçbiri kod içine
yazılmaz, Render'da (Environment sekmesinden) ve yerel geliştirmede (.env
ya da kabuk ortam değişkeni olarak) ayrı ayrı tanımlanır:
    SMTP_HOST      -- örn. smtp.gmail.com (Gmail/Workspace için varsayılan)
    SMTP_PORT      -- örn. 587 (varsayılan)
    SMTP_USER      -- gönderen adres (örn. bilgi@nordgismuhendislik.com)
    SMTP_PASSWORD  -- Google hesabında oluşturulan "uygulama şifresi"
                      (normal Gmail/Workspace şifresiyle SMTP girişine
                      izin verilmez -- Google hesap ayarları ->
                      Güvenlik -> Uygulama şifreleri'nden alınır)
    MAIL_FROM      -- (opsiyonel) gönderen olarak görünecek adres,
                      belirtilmezse SMTP_USER kullanılır

Bu değişkenler ayarlanmadıysa mail gönderilemez -- MailGonderilemedi
hatası fırlatılır, çağıran taraf (main.py) bunu yakalayıp bağlantıyı
yöneticiye ekranda göstererek elle iletmesini sağlıyor, yani mail
gönderimi çalışmasa bile hesap açma/şifre sıfırlama işlemi durmuyor.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage


class MailGonderilemedi(Exception):
    pass


def send_mail(to_addr, subject, text_body):
    host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    port = int(os.environ.get('SMTP_PORT', '587'))
    user = os.environ.get('SMTP_USER')
    password = os.environ.get('SMTP_PASSWORD')
    from_addr = os.environ.get('MAIL_FROM') or user

    if not user or not password:
        raise MailGonderilemedi(
            'SMTP_USER / SMTP_PASSWORD ortam değişkenleri ayarlanmamış.'
        )

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = to_addr
    msg.set_content(text_body)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)
    except Exception as exc:
        raise MailGonderilemedi(str(exc)) from exc
