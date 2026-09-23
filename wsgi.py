"""Entry point for a production WSGI server (gunicorn), and for `python wsgi.py`
during local development.

    Local dev:  python wsgi.py
    Render:     gunicorn wsgi:app
"""
from app.main import app

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)), debug=True)
