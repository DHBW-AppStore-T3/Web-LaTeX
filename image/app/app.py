import hmac
import os
import shutil
import subprocess
import zipfile
from functools import wraps
from flask import Flask, request, jsonify, send_file, render_template, session, redirect, url_for

app = Flask(__name__)

# Pod runtime: one instance per person. Data lives on the storage volume, the
# login comes from the environment (the platform generates the password).
DATA_DIR = os.environ.get('WEBLATEX_DATA', '/home/latex')
BASE_DIR = os.path.join(DATA_DIR, 'projects')
STARTER_ZIP = os.environ.get('WEBLATEX_STARTER', '/opt/weblatex/starter/starter.zip')
DEMO_DIR = '/opt/weblatex/demo'

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

def email_to_dirname(email):
    return email.replace('@', '_').replace('.', '-')

def get_user_dir(email):
    return os.path.join(BASE_DIR, email_to_dirname(email))

def load_credentials():
    user = os.environ.get('WEBLATEX_USER', '')
    password = os.environ.get('WEBLATEX_PASSWORD', '')
    return {user: password} if user and password else {}

def ensure_workspace(user_dir):
    """First visit: unpack the team's starter ZIP (wizard upload), else the demo project."""
    os.makedirs(user_dir, exist_ok=True)
    if os.path.exists(os.path.join(user_dir, 'master.tex')):
        return
    if os.path.isfile(STARTER_ZIP) and os.path.getsize(STARTER_ZIP) > 0:
        try:
            root = os.path.realpath(user_dir)
            with zipfile.ZipFile(STARTER_ZIP) as z:
                for member in z.namelist():
                    target = os.path.realpath(os.path.join(user_dir, member))
                    if target != root and not target.startswith(root + os.sep):
                        raise ValueError('unsafe path in ZIP: ' + member)
                z.extractall(user_dir)
        except (zipfile.BadZipFile, ValueError, OSError):
            pass  # fall back to the demo project below
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
    creds = load_credentials()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    if username in creds and hmac.compare_digest(creds[username].encode(), password.encode()):
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
            ['pdflatex', '-interaction=nonstopmode', '-output-directory', user_dir, 'master.tex'],
            cwd=user_dir,
            capture_output=True, timeout=60, encoding='latin-1'
        )
        if result.returncode == 0:
            subprocess.run(
                ['pdflatex', '-interaction=nonstopmode', '-output-directory', user_dir, 'master.tex'],
                cwd=user_dir,
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
    except Exception as e:
        return jsonify({'success': False, 'errors': [str(e)]}), 500

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
    data = request.get_json()
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name fehlt'}), 400
    if not name.endswith('.tex'):
        name += '.tex'
    # Security check: prevent path traversal
    user_dir = get_user_dir(session['username'])
    full = os.path.realpath(os.path.join(user_dir, name))
    if not full.startswith(os.path.realpath(user_dir)):
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
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_IMG_EXTS:
        return jsonify({'error': f'Nur {", ".join(ALLOWED_IMG_EXTS)} erlaubt'}), 415
    user_dir = get_user_dir(session['username'])
    img_dir = os.path.join(user_dir, 'images')
    os.makedirs(img_dir, exist_ok=True)
    dest = os.path.realpath(os.path.join(img_dir, f.filename))
    if not dest.startswith(os.path.realpath(img_dir)):
        return 'Forbidden', 403
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size > MAX_IMG_BYTES:
        return jsonify({'error': 'Datei zu groß (max 10 MB)'}), 413
    f.save(dest)
    return jsonify({'success': True, 'name': os.path.relpath(dest, user_dir)})

@app.route('/file/<path:relpath>', methods=['GET'])
@login_required
def get_file(relpath):
    user_dir = get_user_dir(session['username'])
    full = os.path.realpath(os.path.join(user_dir, relpath))
    if not full.startswith(os.path.realpath(user_dir)):
        return 'Forbidden', 403
    if not os.path.exists(full):
        return 'Not found', 404
    with open(full, 'r', encoding='utf-8', errors='replace') as f:
        return jsonify({'content': f.read()})

@app.route('/file/<path:relpath>', methods=['POST'])
@login_required
def save_file(relpath):
    user_dir = get_user_dir(session['username'])
    full = os.path.realpath(os.path.join(user_dir, relpath))
    if not full.startswith(os.path.realpath(user_dir)):
        return 'Forbidden', 403
    os.makedirs(os.path.dirname(full), exist_ok=True)
    data = request.get_json()
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
    full = os.path.realpath(os.path.join(user_dir, relpath))
    if not full.startswith(os.path.realpath(user_dir)):
        return 'Forbidden', 403
    if not os.path.exists(full):
        return 'Not found', 404
    return send_file(full)

if __name__ == '__main__':
    app.run(host='::', port=8080)
