#!/usr/bin/env bash
set -euo pipefail

echo "[1/6] Waiting for cloud-init..."
cloud-init status --wait || true

echo "[2/6] Installing packages..."
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  gnupg \
  lsb-release

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  texlive-latex-base \
  texlive-latex-recommended \
  texlive-latex-extra \
  texlive-fonts-recommended \
  texlive-lang-german \
  nginx \
  python3 \
  python3-flask \
  python3-pip \
  unzip \
  zip

echo "[3/6] Creating Flask app..."
sudo mkdir -p /opt/weblatex/templates
sudo mkdir -p /var/www/weblatex

# Bundle demo project as ZIP into the image
DEMO_TMP=$(mktemp -d)
mkdir -p "$DEMO_TMP/chapters"

sudo tee "$DEMO_TMP/master.tex" > /dev/null << 'DEMO_MASTER'
\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\usepackage{graphicx}

\title{Web-LaTeX Editor}
\author{AppStore}
\date{\today}

\begin{document}
\maketitle
\tableofcontents
\newpage

\input{chapters/intro}
\input{chapters/example}

\end{document}
DEMO_MASTER

sudo tee "$DEMO_TMP/chapters/intro.tex" > /dev/null << 'DEMO_INTRO'
\section{Willkommen}
Dies ist das Demo-Projekt. Jeder Abschnitt liegt in einer eigenen Datei
im Verzeichnis \texttt{chapters/}.

Bearbeite \texttt{master.tex} im Editor und kompiliere mit \textbf{Ctrl+Enter}.
DEMO_INTRO

sudo tee "$DEMO_TMP/chapters/example.tex" > /dev/null << 'DEMO_EXAMPLE'
\section{Beispiel}
Eine einfache Liste:
\begin{itemize}
  \item \texttt{master.tex} -- Einstiegspunkt, bindet alle Kapitel ein
  \item \texttt{chapters/intro.tex} -- Einleitung
  \item \texttt{chapters/example.tex} -- Dieser Abschnitt
\end{itemize}

Eine Formel: $E = mc^2$
DEMO_EXAMPLE

(cd "$DEMO_TMP" && sudo zip -r /opt/weblatex/demo_project.zip .)
rm -rf "$DEMO_TMP"
sudo chown www-data:www-data /opt/weblatex/demo_project.zip

sudo tee /opt/weblatex/app.py > /dev/null << 'PYEOF'
import os
import subprocess
from functools import wraps
from flask import Flask, request, jsonify, send_file, render_template, session, redirect, url_for

app = Flask(__name__)

# Persistent secret key — prevents session invalidation on service restart
_secret_path = '/etc/weblatex/flask_secret'
if os.path.exists(_secret_path):
    with open(_secret_path, 'rb') as _f:
        app.secret_key = _f.read()
else:
    app.secret_key = os.urandom(32)

BASE_DIR = '/var/www/weblatex'
USERS_DIR = '/etc/weblatex/users'

def email_to_dirname(email):
    return email.replace('@', '_').replace('.', '-')

def get_user_dir(email):
    return os.path.join(BASE_DIR, email_to_dirname(email))

def load_credentials():
    creds = {}
    if not os.path.isdir(USERS_DIR):
        return creds
    for fname in os.listdir(USERS_DIR):
        if not fname.endswith('.env'):
            continue
        try:
            user_data = {}
            with open(os.path.join(USERS_DIR, fname), encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        k, v = line.split('=', 1)
                        user_data[k.strip()] = v.strip()
            if 'EMAIL' in user_data and 'PASSWORD' in user_data:
                creds[user_data['EMAIL']] = user_data['PASSWORD']
        except (OSError, PermissionError):
            continue
    return creds

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
    if username in creds and creds[username] == password:
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
    os.makedirs(user_dir, exist_ok=True)
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
    app.run(host='127.0.0.1', port=5000)
PYEOF

echo "[4/6] Creating HTML templates..."
sudo tee /opt/weblatex/templates/login.html > /dev/null << 'LOGINEOF'
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>Web-LaTeX — Login</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: sans-serif; background: #1e1e2e; color: #cdd6f4;
           display: flex; align-items: center; justify-content: center; height: 100vh; }
    .card { background: #181825; border: 1px solid #313244; border-radius: 10px;
            padding: 40px; width: 360px; }
    h1 { color: #cba6f7; font-size: 1.4rem; margin-bottom: 8px; }
    p  { color: #6c7086; font-size: 0.85rem; margin-bottom: 28px; }
    label { display: block; font-size: 0.85rem; color: #a6adc8; margin-bottom: 6px; }
    input { width: 100%; padding: 10px 12px; background: #313244; border: 1px solid #45475a;
            border-radius: 6px; color: #cdd6f4; font-size: 0.95rem; margin-bottom: 16px; }
    input:focus { outline: none; border-color: #cba6f7; }
    button { width: 100%; padding: 11px; background: #cba6f7; color: #1e1e2e;
             font-weight: 700; font-size: 1rem; border: none; border-radius: 6px; cursor: pointer; }
    button:hover { background: #b4befe; }
    .error { background: #3b1b1b; color: #f38ba8; border-radius: 6px;
             padding: 10px 14px; font-size: 0.85rem; margin-bottom: 16px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Web-LaTeX Editor</h1>
    <p>Bitte melde dich mit deinen Zugangsdaten an.</p>
    {% if error %}
    <div class="error">Benutzername oder Passwort falsch.</div>
    {% endif %}
    <form method="POST" action="/login">
      <label for="username">E-Mail</label>
      <input type="email" id="username" name="username" autocomplete="username" required>
      <label for="password">Passwort</label>
      <input type="password" id="password" name="password" autocomplete="current-password" required>
      <button type="submit">Anmelden</button>
    </form>
  </div>
</body>
</html>
LOGINEOF

sudo tee /opt/weblatex/templates/index.html > /dev/null << 'HTMLEOF'
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>Web-LaTeX Editor</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/dracula.min.css">
  <style>
    :root {
      --bg:       #0f1117;
      --surface:  #161b22;
      --border:   #21262d;
      --muted:    #484f58;
      --text:     #e6edf3;
      --text-dim: #8b949e;
      --accent:   #7c3aed;
      --accent-h: #6d28d9;
      --green:    #3fb950;
      --red:      #f85149;
      --amber:    #d29922;
      --blue:     #58a6ff;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column; }

    /* ── Header ── */
    header { padding: 0 16px; height: 48px; background: var(--surface);
             display: flex; align-items: center; gap: 10px;
             border-bottom: 1px solid var(--border); flex-shrink: 0; }
    header h1 { font-size: 0.95rem; font-weight: 600; color: var(--text);
                display: flex; align-items: center; gap: 6px; }
    header h1::before { content: ''; display: inline-block; width: 8px; height: 8px;
                        border-radius: 50%; background: var(--accent); }
    .btn { padding: 6px 14px; border: none; border-radius: 6px; cursor: pointer;
           font-size: 0.82rem; font-weight: 600; transition: background .15s; }
    .btn-compile { background: var(--accent); color: #fff; }
    .btn-compile:hover { background: var(--accent-h); }
    .btn-compile:disabled { background: var(--muted); color: var(--text-dim); cursor: not-allowed; }
    .btn-logout { background: transparent; color: var(--text-dim);
                  border: 1px solid var(--border); margin-left: auto; }
    .btn-logout:hover { color: var(--red); border-color: var(--red); }
    .user-badge { font-size: 0.75rem; color: var(--text-dim);
                  background: var(--border); padding: 3px 8px; border-radius: 20px; }
    .status { font-size: 0.78rem; font-weight: 500; }
    .status.ok      { color: var(--green); }
    .status.err     { color: var(--red); }
    .status.saving  { color: var(--amber); }

    /* ── Layout ── */
    main { display: flex; flex: 1; overflow: hidden; }

    /* ── Sidebar ── */
    .sidebar { width: 210px; background: var(--surface); border-right: 1px solid var(--border);
               display: flex; flex-direction: column; flex-shrink: 0; }
    .sidebar-header { padding: 8px 10px; font-size: 0.7rem; font-weight: 600;
                      color: var(--text-dim); text-transform: uppercase; letter-spacing: .06em;
                      border-bottom: 1px solid var(--border);
                      display: flex; align-items: center; justify-content: space-between; }
    .sidebar-actions { display: flex; gap: 2px; }
    .sidebar-actions button { background: none; border: none; color: var(--text-dim);
                               cursor: pointer; font-size: 0.9rem; padding: 3px 6px;
                               border-radius: 5px; line-height: 1; }
    .sidebar-actions button:hover { background: var(--border); color: var(--text); }
    .sidebar-section { padding: 8px 10px 3px; font-size: 0.65rem; color: var(--muted);
                       text-transform: uppercase; letter-spacing: .06em; }
    .file-list { flex: 1; overflow-y: auto; padding: 4px 0; }
    .file-item { padding: 5px 12px; font-size: 0.8rem; cursor: pointer; color: var(--text-dim);
                 white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                 border-left: 2px solid transparent; transition: all .1s; }
    .file-item:hover { background: var(--border); color: var(--text); }
    .file-item.active { background: rgba(124,58,237,.12); color: #a78bfa;
                        border-left-color: var(--accent); font-weight: 600; }
    .file-item.img-item { color: var(--blue); cursor: pointer; }
    .file-item.img-item:hover { background: var(--border); }

    /* ── Editor ── */
    .editor-pane { flex: 1; display: flex; flex-direction: column;
                   border-right: 1px solid var(--border); min-width: 0; }
    .editor-pane .CodeMirror { flex: 1; height: 100%; font-size: 13px; line-height: 1.65;
                                font-family: 'JetBrains Mono', 'Fira Code', monospace; }
    .editor-pane .CodeMirror-scroll { height: 100%; }

    /* ── Preview ── */
    .preview-pane { flex: 1; background: var(--surface); display: flex;
                    flex-direction: column; min-width: 0; }
    .preview-pane iframe { flex: 1; border: none; background: white; }
    .error-box { padding: 14px 16px; background: rgba(248,81,73,.08);
                 border-top: 1px solid rgba(248,81,73,.3); color: var(--red);
                 font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;
                 overflow-y: auto; max-height: 180px; }
    .error-box pre { white-space: pre-wrap; }

    /* ── Modal: New File ── */
    .modal-backdrop { display: none; position: fixed; inset: 0;
                      background: rgba(0,0,0,.7); z-index: 100;
                      align-items: center; justify-content: center; }
    .modal-backdrop.open { display: flex; }
    .modal { background: var(--surface); border: 1px solid var(--border);
             border-radius: 10px; padding: 22px; width: 340px;
             box-shadow: 0 20px 60px rgba(0,0,0,.5); }
    .modal h2 { font-size: 0.95rem; color: var(--text); margin-bottom: 14px; font-weight: 600; }
    .modal input[type=text] { width: 100%; padding: 8px 10px; background: var(--bg);
                               border: 1px solid var(--border); border-radius: 6px;
                               color: var(--text); font-size: 0.85rem; margin-bottom: 14px; }
    .modal input[type=text]:focus { outline: none; border-color: var(--accent); }
    .modal-btns { display: flex; gap: 8px; justify-content: flex-end; }
    .modal-btns button { padding: 6px 14px; border: none; border-radius: 6px;
                         cursor: pointer; font-size: 0.82rem; font-weight: 600; }
    .btn-ok     { background: var(--accent); color: #fff; }
    .btn-ok:hover { background: var(--accent-h); }
    .btn-cancel { background: var(--border); color: var(--text-dim); }
    .btn-cancel:hover { background: var(--muted); }

    /* ── Lightbox ── */
    .lightbox { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.85);
                z-index: 200; align-items: center; justify-content: center; cursor: zoom-out; }
    .lightbox.open { display: flex; }
    .lightbox img { max-width: 90vw; max-height: 90vh; border-radius: 6px;
                    box-shadow: 0 8px 40px rgba(0,0,0,.6); }
  </style>
</head>
<body>
  <header>
    <h1>Web-LaTeX Editor</h1>
    <button class="btn btn-compile" id="compileBtn" onclick="compile()">▶ Kompilieren</button>
    <span class="status" id="status"></span>
    <span class="user-badge">{{ username }}</span>
    <a href="/logout" class="btn btn-logout">Abmelden</a>
  </header>
  <main>
    <div class="sidebar">
      <div class="sidebar-header">
        <span>Explorer</span>
        <div class="sidebar-actions">
          <button onclick="openNewFileModal()" title="Neue .tex-Datei">＋</button>
          <button onclick="document.getElementById('imgUpload').click()" title="Bild hochladen">+ Bild</button>
          <input type="file" id="imgUpload" accept=".png,.jpg,.jpeg,.gif" style="display:none" onchange="uploadImage(this)">
        </div>
      </div>
      <div class="file-list" id="fileList"></div>
    </div>
    <div class="editor-pane">
      <textarea id="editor">{{ content }}</textarea>
    </div>
    <div class="preview-pane">
      <iframe id="preview" src="/pdf"></iframe>
      <div class="error-box" id="errorBox" style="display:none"><pre id="errorText"></pre></div>
    </div>
  </main>

  <!-- Modal: New File -->
  <div class="modal-backdrop" id="newFileModal" onclick="if(event.target===this)closeNewFileModal()">
    <div class="modal">
      <h2>Neue .tex-Datei erstellen</h2>
      <input type="text" id="newFileName" placeholder="z.B. chapters/methodik"
             onkeydown="if(event.key==='Enter')confirmNewFile()">
      <div class="modal-btns">
        <button class="btn-cancel" onclick="closeNewFileModal()">Abbrechen</button>
        <button class="btn-ok" onclick="confirmNewFile()">Erstellen</button>
      </div>
    </div>
  </div>

  <!-- Lightbox: Show image -->
  <div class="lightbox" id="lightbox" onclick="closeLightbox()">
    <img id="lightboxImg" src="" alt="">
  </div>

  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/stex/stex.min.js"></script>
  <script>
    const editor = CodeMirror.fromTextArea(document.getElementById('editor'), {
      mode: 'stex', theme: 'dracula', lineNumbers: true, lineWrapping: true,
      autofocus: true, extraKeys: { 'Ctrl-Enter': compile, 'Cmd-Enter': compile }
    });
    editor.setSize('100%', '100%');

    const fileCache = {};
    let currentFile = 'master.tex';

    async function loadFileList() {
      const res = await fetch('/files');
      const data = await res.json();
      const list = document.getElementById('fileList');
      list.innerHTML = '';

      if (data.tex && data.tex.length > 0) {
        const sec = document.createElement('div');
        sec.className = 'sidebar-section';
        sec.textContent = 'LaTeX';
        list.appendChild(sec);
        data.tex.forEach(f => {
          const item = document.createElement('div');
          item.className = 'file-item' + (f === currentFile ? ' active' : '');
          item.textContent = f;
          item.title = f;
          item.onclick = () => switchFile(f);
          list.appendChild(item);
        });
      }

      if (data.images && data.images.length > 0) {
        const sec = document.createElement('div');
        sec.className = 'sidebar-section';
        sec.textContent = 'Bilder';
        list.appendChild(sec);
        data.images.forEach(f => {
          const item = document.createElement('div');
          item.className = 'file-item img-item';
          item.textContent = f;
          item.title = 'Klicken zum Anzeigen · \\includegraphics{' + f + '}';
          item.onclick = () => openLightbox(f);
          list.appendChild(item);
        });
      }
    }

    function openLightbox(relpath) {
      document.getElementById('lightboxImg').src = '/image/' + relpath + '?t=' + Date.now();
      document.getElementById('lightbox').classList.add('open');
    }
    function closeLightbox() {
      document.getElementById('lightbox').classList.remove('open');
    }
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLightbox(); });

    function openNewFileModal() {
      document.getElementById('newFileName').value = '';
      document.getElementById('newFileModal').classList.add('open');
      setTimeout(() => document.getElementById('newFileName').focus(), 50);
    }
    function closeNewFileModal() {
      document.getElementById('newFileModal').classList.remove('open');
    }

    async function confirmNewFile() {
      const name = document.getElementById('newFileName').value.trim();
      if (!name) return;
      const res = await fetch('/new-file', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
      });
      const data = await res.json();
      closeNewFileModal();
      if (data.error) { alert(data.error); return; }
      await loadFileList();
      switchFile(data.name);
    }

    async function uploadImage(input) {
      const file = input.files[0];
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      setStatus('saving', 'Lädt hoch...');
      const res = await fetch('/upload-image', { method: 'POST', body: form });
      const data = await res.json();
      input.value = '';
      if (data.error) { setStatus('err', '✗ ' + data.error); return; }
      setStatus('ok', '✓ Bild hochgeladen');
      await loadFileList();
      setTimeout(() => { if (document.getElementById('status').textContent.startsWith('✓ Bild')) setStatus('', ''); }, 3000);
    }

    async function switchFile(filename) {
      fileCache[currentFile] = editor.getValue();
      document.querySelectorAll('.file-item').forEach(el => {
        el.classList.toggle('active', el.textContent === filename);
      });
      currentFile = filename;
      if (fileCache[filename] !== undefined) {
        editor.setValue(fileCache[filename]);
      } else {
        const res = await fetch('/file/' + filename);
        const d = await res.json();
        editor.setValue(d.content);
        fileCache[filename] = d.content;
      }
      editor.focus();
    }

    async function saveCurrentFile() {
      const content = editor.getValue();
      await fetch('/file/' + currentFile, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
      });
      fileCache[currentFile] = content;
    }

    function setStatus(cls, text) {
      const el = document.getElementById('status');
      el.className = cls ? 'status ' + cls : 'status';
      el.textContent = text;
    }

    async function compile() {
      // Save current file — all others were already auto-saved on keystroke
      await saveCurrentFile();
      const btn = document.getElementById('compileBtn');
      const errorBox = document.getElementById('errorBox');
      btn.disabled = true;
      setStatus('saving', 'Kompiliert...');
      errorBox.style.display = 'none';
      try {
        const res = await fetch('/compile', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          setStatus('ok', '✓ Erfolgreich');
          document.getElementById('preview').src = '/pdf?t=' + Date.now();
          errorBox.style.display = 'none';
        } else {
          setStatus('err', '✗ Fehler');
          document.getElementById('errorText').textContent = data.errors.join('\n');
          errorBox.style.display = 'block';
        }
      } catch (e) {
        setStatus('err', '✗ Verbindungsfehler');
      } finally {
        btn.disabled = false;
      }
    }

    // Auto-save on keystroke (500ms debounce)
    let saveTimer = null;
    editor.on('change', () => {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(saveCurrentFile, 500);
    });

    loadFileList();
  </script>
</body>
</html>
HTMLEOF

echo "[5/6] Creating systemd service..."
sudo tee /etc/systemd/system/weblatex.service > /dev/null << 'SVCEOF'
[Unit]
Description=Web-LaTeX Flask App
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/weblatex
ExecStart=/usr/bin/python3 /opt/weblatex/app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVCEOF

sudo chown -R www-data:www-data /opt/weblatex /var/www/weblatex
sudo mkdir -p /etc/weblatex/users
sudo chown root:www-data /etc/weblatex /etc/weblatex/users
sudo chmod 750 /etc/weblatex /etc/weblatex/users
sudo systemctl daemon-reload
sudo systemctl enable weblatex

echo "[6/6] Configuring nginx as reverse proxy..."
sudo tee /etc/nginx/sites-available/weblatex > /dev/null << 'NGINXEOF'
server {
    listen 80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        client_max_body_size 5M;
    }
}
NGINXEOF

sudo ln -sf /etc/nginx/sites-available/weblatex /etc/nginx/sites-enabled/weblatex
sudo rm -f /etc/nginx/sites-enabled/default

echo "Cleanup..."
sudo apt-get clean
sudo rm -rf /var/lib/apt/lists/*

sudo truncate -s 0 /etc/machine-id
sudo rm -f /var/lib/dbus/machine-id

echo "Provisioning finished. Image is ready for deployment."
