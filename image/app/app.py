import hmac
import os
import shutil
import subprocess
from functools import wraps

from flask import Flask, request, jsonify, send_file, render_template, session, redirect, url_for
from werkzeug.utils import secure_filename

import imagecheck
import safe_zip

app = Flask(__name__)

# Pod runtime: one instance per person. Data lives on the storage volume, the
# login comes from the environment (the platform generates the password).
DATA_DIR = os.environ.get('WEBLATEX_DATA', '/home/latex')
BASE_DIR = os.path.join(DATA_DIR, 'projects')
STARTER_ZIP = os.environ.get('WEBLATEX_STARTER', '/opt/weblatex/starter/starter.zip')
DEMO_DIR = '/opt/weblatex/demo'

# Hardening of the session and of what a request may carry.
app.config.update(
    # A request body (the image upload is the biggest one) never needs more than this.
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    # SameSite=Lax keeps other sites from making the browser send this cookie with a POST
    # (compile, save, upload). The platform serves the editor over HTTPS only; the smoke test
    # speaks plain HTTP to localhost and turns Secure off with WEBLATEX_COOKIE_SECURE=0.
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('WEBLATEX_COOKIE_SECURE', '1') != '0',
)

# Persistent secret key — prevents session invalidation on pod restart
_secret_path = os.path.join(DATA_DIR, '.flask_secret')
try:
    with open(_secret_path, 'rb') as _f:
        app.secret_key = _f.read()
except FileNotFoundError:
    app.secret_key = os.urandom(32)
    try:
        with open(_secret_path, 'wb') as _f:
            _f.write(app.secret_key)
        os.chmod(_secret_path, 0o600)
    except OSError:
        pass


@app.after_request
def security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    # The PDF preview is an iframe of the same origin; nobody else may frame the editor.
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    if request.method == 'GET' and response.mimetype in ('text/html', 'application/json'):
        response.headers.setdefault('Cache-Control', 'no-store')
    return response


def email_to_dirname(email):
    return email.replace('@', '_').replace('.', '-')

def get_user_dir(email):
    return os.path.join(BASE_DIR, email_to_dirname(email))

def load_credentials():
    user = os.environ.get('WEBLATEX_USER', '')
    password = os.environ.get('WEBLATEX_PASSWORD', '')
    return {user: password} if user and password else {}

def resolve_inside(base, relpath):
    """The real path of base/relpath, or None if it is not strictly inside base.

    A plain ``startswith`` is not enough: ``/data/user`` is a prefix of ``/data/user-other``.
    """
    root = os.path.realpath(base)
    full = os.path.realpath(os.path.join(root, relpath))
    if full == root or os.path.commonpath([root, full]) != root:
        return None
    return full

def ensure_workspace(user_dir):
    """First visit: unpack the team's starter ZIP (wizard upload), else the demo project."""
    os.makedirs(user_dir, exist_ok=True)
    if os.path.exists(os.path.join(user_dir, 'master.tex')):
        return
    if os.path.isfile(STARTER_ZIP) and os.path.getsize(STARTER_ZIP) > 0:
        try:
            safe_zip.unpack(STARTER_ZIP, user_dir)
        except (safe_zip.Rejected, OSError) as exc:
            print('web-latex: starter ZIP not used: %s' % exc, flush=True)  # fall back to the demo below
        if os.path.exists(os.path.join(user_dir, 'master.tex')):
            return
    shutil.copytree(DEMO_DIR, user_dir, dirs_exist_ok=True)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET'])
def login_page():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    error = request.args.get('error')
    return render_template('login.html', error=error)

@app.route('/login', methods=['POST'])
def do_login():
    # No lockout after wrong passwords: the platform generates a long random password, and a lockout
    # would let anyone who knows the address keep the real person out.
    creds = load_credentials()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    if username in creds and hmac.compare_digest(creds[username].encode(), password.encode()):
        session.clear()
        session['logged_in'] = True
        session['username'] = username
        return redirect(url_for('index'))
    return redirect(url_for('login_page', error='1'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/')
@login_required
def index():
    user_dir = get_user_dir(session['username'])
    ensure_workspace(user_dir)
    master = os.path.join(user_dir, 'master.tex')
    content = ''
    if os.path.exists(master):
        with open(master, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    return render_template('index.html', content=content, username=session['username'])

# pdflatex on a stranger's .tex file: no shell escape (\write18), and "paranoid" file access
# (no absolute paths, no parent directories, no dot files) for reading and writing. The environment
# variables are the way to override texmf.cnf for one call.
TEX_ENV = dict(os.environ, openin_any='p', openout_any='p', shell_escape='f')
TEX_COMMAND = ['pdflatex', '-no-shell-escape', '-interaction=nonstopmode', '-output-directory']

@app.route('/compile', methods=['POST'])
@login_required
def compile_tex():
    try:
        user_dir = get_user_dir(session['username'])
        os.makedirs(user_dir, exist_ok=True)
        master = os.path.join(user_dir, 'master.tex')
        if not os.path.exists(master):
            return jsonify({'success': False, 'errors': ['master.tex nicht gefunden']})
        for ext in ['aux', 'log', 'out', 'toc', 'pdf']:
            try:
                os.remove(os.path.join(user_dir, 'master.' + ext))
            except FileNotFoundError:
                pass
        result = subprocess.run(
            TEX_COMMAND + [user_dir, 'master.tex'],
            cwd=user_dir, env=TEX_ENV,
            capture_output=True, timeout=60, encoding='latin-1'
        )
        if result.returncode == 0:
            subprocess.run(
                TEX_COMMAND + [user_dir, 'master.tex'],
                cwd=user_dir, env=TEX_ENV,
                capture_output=True, timeout=60, encoding='latin-1'
            )
        pdf_path = os.path.join(user_dir, 'master.pdf')
        if os.path.exists(pdf_path):
            return jsonify({'success': True})
        log = result.stdout + result.stderr
        errors = [l for l in log.splitlines() if l.startswith('!') or 'Error' in l]
        return jsonify({'success': False, 'errors': errors[:20]})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'errors': ['Kompilierung hat zu lange gedauert (Timeout 60s)']})
    except Exception:
        app.logger.exception('compile failed')
        return jsonify({'success': False, 'errors': ['Interner Fehler beim Kompilieren']}), 500

@app.route('/files')
@login_required
def list_files():
    user_dir = get_user_dir(session['username'])
    tex_files = []
    img_files = []
    img_exts = {'.png', '.jpg', '.jpeg', '.gif'}
    for root, dirs, fnames in os.walk(user_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        for fname in sorted(fnames):
            rel = os.path.relpath(os.path.join(root, fname), user_dir)
            ext = os.path.splitext(fname)[1].lower()
            if fname.endswith('.tex'):
                tex_files.append(rel)
            elif ext in img_exts:
                img_files.append(rel)
    return jsonify({'tex': tex_files, 'images': img_files})

@app.route('/new-file', methods=['POST'])
@login_required
def new_file():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name fehlt'}), 400
    if not name.endswith('.tex'):
        name += '.tex'
    # Security check: prevent path traversal
    user_dir = get_user_dir(session['username'])
    full = resolve_inside(user_dir, name)
    if full is None:
        return 'Forbidden', 403
    if os.path.exists(full):
        return jsonify({'error': 'Datei existiert bereits'}), 409
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        f.write('')
    return jsonify({'success': True, 'name': os.path.relpath(full, user_dir)})

ALLOWED_IMG_EXTS = {'.png', '.jpg', '.jpeg', '.gif'}
MAX_IMG_BYTES = 10 * 1024 * 1024  # 10 MB

@app.route('/upload-image', methods=['POST'])
@login_required
def upload_image():
    if 'file' not in request.files:
        return jsonify({'error': 'Keine Datei'}), 400
    f = request.files['file']
    # Only the file name, no directories, no odd characters (the name ends up in \includegraphics).
    name = secure_filename(f.filename or '')
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_IMG_EXTS:
        return jsonify({'error': 'Nur %s erlaubt' % ', '.join(sorted(ALLOWED_IMG_EXTS))}), 415
    data = f.read(MAX_IMG_BYTES + 1)
    if len(data) > MAX_IMG_BYTES:
        return jsonify({'error': 'Datei zu groß (max 10 MB)'}), 413
    # The bytes must be the image the extension says: right container, sane size, nothing appended.
    try:
        imagecheck.inspect(data, ext)
    except imagecheck.Rejected as exc:
        return jsonify({'error': 'Ungültiges Bild: %s' % exc}), 422
    user_dir = get_user_dir(session['username'])
    img_dir = os.path.join(user_dir, 'images')
    os.makedirs(img_dir, exist_ok=True)
    dest = resolve_inside(img_dir, name)
    if dest is None:
        return 'Forbidden', 403
    with open(dest, 'wb') as out:
        out.write(data)
    return jsonify({'success': True, 'name': os.path.relpath(dest, user_dir)})

@app.route('/file/<path:relpath>', methods=['GET'])
@login_required
def get_file(relpath):
    user_dir = get_user_dir(session['username'])
    full = resolve_inside(user_dir, relpath)
    if full is None:
        return 'Forbidden', 403
    if not os.path.isfile(full):
        return 'Not found', 404
    with open(full, 'r', encoding='utf-8', errors='replace') as f:
        return jsonify({'content': f.read()})

@app.route('/file/<path:relpath>', methods=['POST'])
@login_required
def save_file(relpath):
    user_dir = get_user_dir(session['username'])
    full = resolve_inside(user_dir, relpath)
    if full is None:
        return 'Forbidden', 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('content', ''), str):
        return jsonify({'error': 'Ungültige Anfrage'}), 400
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(data.get('content', ''))
    return jsonify({'success': True})

@app.route('/pdf')
@login_required
def get_pdf():
    user_dir = get_user_dir(session['username'])
    pdf_path = os.path.join(user_dir, 'master.pdf')
    if os.path.exists(pdf_path):
        return send_file(pdf_path, mimetype='application/pdf')
    return 'No PDF available', 404

@app.route('/image/<path:relpath>')
@login_required
def get_image(relpath):
    user_dir = get_user_dir(session['username'])
    full = resolve_inside(user_dir, relpath)
    if full is None:
        return 'Forbidden', 403
    if os.path.splitext(full)[1].lower() not in ALLOWED_IMG_EXTS:
        return 'Forbidden', 403
    if not os.path.isfile(full):
        return 'Not found', 404
    return send_file(full)

if __name__ == '__main__':
    app.run(host='::', port=8080)
