"""Security tests of the running editor, executed INSIDE the container by .github/smoke-test.sh:

    docker exec -i wl python3 - < .github/test-hardening.py

The app listens on [::1]:8080 and was started with WEBLATEX_USER/WEBLATEX_PASSWORD and
WEBLATEX_COOKIE_SECURE=0 (plain HTTP to localhost). Hostile files are built here.
"""

import http.client
import io
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import zipfile
import zlib

HOST, PORT = "::1", 8080
USER, PASSWORD = os.environ["WEBLATEX_USER"], os.environ["WEBLATEX_PASSWORD"]
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print("FAIL:", message)


class Client:
    def __init__(self):
        self.cookie = None

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(HOST, PORT, timeout=120)
        headers = dict(headers or {})
        if self.cookie:
            headers["Cookie"] = self.cookie
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        for key, value in response.getheaders():
            if key.lower() == "set-cookie":
                self.cookie = value.split(";")[0]
        return response, data

    def json(self, method, path, payload):
        return self.request(method, path, json.dumps(payload).encode(), {"Content-Type": "application/json"})

    def upload(self, filename, content):
        boundary = "----x"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        return self.request("POST", "/upload-image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})


def png(width=1, height=1, trailing=b""):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00" * 5)) + chunk(b"IEND", b"") + trailing


# ---- nobody gets in without the password
anonymous = Client()
for method, path in [("GET", "/files"), ("POST", "/compile"), ("GET", "/file/master.tex"), ("GET", "/pdf"), ("POST", "/upload-image"), ("GET", "/image/x.png")]:
    response, _ = anonymous.request(method, path)
    check(response.status == 302 and "/login" in response.getheader("Location", ""), f"{method} {path} without login: {response.status}")

response, _ = anonymous.request("POST", "/login", b"username=" + USER.encode() + b"&password=wrong", {"Content-Type": "application/x-www-form-urlencoded"})
check(response.status == 302 and "error=1" in response.getheader("Location", ""), "a wrong password is refused")

# ---- login, cookie and headers
client = Client()
response, _ = client.request("POST", "/login", f"username={USER}&password={PASSWORD}".encode(), {"Content-Type": "application/x-www-form-urlencoded"})
check(response.status == 302 and client.cookie, "login works")
cookie_header = [v for k, v in response.getheaders() if k.lower() == "set-cookie"][0]
check("HttpOnly" in cookie_header and "SameSite=Lax" in cookie_header, f"session cookie flags: {cookie_header}")
response, _ = client.request("GET", "/")
check(response.getheader("X-Content-Type-Options") == "nosniff", "X-Content-Type-Options")
check(response.getheader("X-Frame-Options") == "SAMEORIGIN", "X-Frame-Options")
check(response.getheader("Referrer-Policy") == "same-origin", "Referrer-Policy")
check(response.getheader("Cache-Control") == "no-store", "Cache-Control on the editor page")

secure_default = subprocess.run(
    ["python3", "-c", "import app; print(app.app.config['SESSION_COOKIE_SECURE'])"],
    cwd="/opt/weblatex", capture_output=True, text=True,
    env={**os.environ, "WEBLATEX_DATA": "/tmp/wl-secure-check", "WEBLATEX_COOKIE_SECURE": ""},
)
check(secure_default.stdout.strip() == "True", f"the cookie is Secure by default: {secure_default.stdout} {secure_default.stderr[-200:]}")

# ---- paths: nothing outside the person's project directory
user_dir = f"/home/latex/projects/{USER.replace('@', '_').replace('.', '-')}"
sibling = user_dir + "-evil"
os.makedirs(sibling, exist_ok=True)
with open(sibling + "/secret.tex", "w") as handle:
    handle.write("not yours")
for path in ["/file/../../../../etc/passwd", "/file/..%2f..%2f..%2fetc%2fpasswd", "/file/../" + os.path.basename(sibling) + "/secret.tex", "/file/%2e%2e/%2e%2e/.flask_secret"]:
    response, data = client.request("GET", path)
    check(response.status in (403, 404) and b"root:" not in data and b"not yours" not in data, f"GET {path}: {response.status}")
for path in ["/file/../../evil.tex", "/file/../" + os.path.basename(sibling) + "/new.tex"]:
    response, _ = client.json("POST", path, {"content": "x"})
    check(response.status in (403, 404), f"POST {path}: {response.status}")
check(not os.path.exists("/home/latex/projects/evil.tex") and not os.path.exists(sibling + "/new.tex"), "something was written outside the project")
response, _ = client.json("POST", "/new-file", {"name": "../../outside"})
check(response.status == 403, f"new-file with traversal: {response.status}")
response, _ = client.request("POST", "/new-file", b"not json", {"Content-Type": "application/json"})
check(response.status == 400, f"new-file with a broken body: {response.status}")
response, _ = client.request("POST", "/file/a.tex", b"not json", {"Content-Type": "application/json"})
check(response.status == 400, f"save with a broken body: {response.status}")
response, _ = client.json("POST", "/file/a.tex", {"content": ["not", "text"]})
check(response.status == 400, f"save with a non-text content: {response.status}")
response, _ = client.json("POST", "/file/chapters/ok.tex", {"content": "fine"})
check(response.status == 200, f"saving a normal file: {response.status}")

# ---- image upload
response, data = client.upload("../../evil.png", png())
check(response.status == 200 and json.loads(data)["name"] == "images/evil.png", f"a path in the file name is cut off: {response.status} {data[:80]}")
check(not os.path.exists("/home/latex/evil.png") and os.path.exists(user_dir + "/images/evil.png"), "image stored under images/ only")
damaged = bytearray(png())
damaged[20] ^= 1
for label, filename, content, expected in [
    ("PNG with a damaged chunk", "a.png", bytes(damaged), 422),
    ("text named .png", "a.png", b"<html>not an image</html>", 422),
    ("PNG with an archive appended", "a.png", png(trailing=b"PK\x03\x04appended"), 422),
    ("PNG announcing 40000 x 40000 pixels", "a.png", png(40000, 40000), 422),
    ("JPEG without frame header", "a.jpg", b"\xff\xd8\xff\xe0\x00\x04ab\xff\xd9", 422),
    ("PNG named .jpg", "a.jpg", png(), 422),
    ("a .php file", "a.php", b"<?php ?>", 415),
    ("no extension", "noext", png(), 415),
    ("hidden file name", ".png", png(), 415),
]:
    response, _ = client.upload(filename, content)
    check(response.status == expected, f"{label}: expected {expected}, got {response.status}")
try:
    response, _ = client.upload("big.png", png() + b"\x00" * (13 * 1024 * 1024))
    check(response.status == 413, f"a body over the limit: {response.status}")
except (BrokenPipeError, ConnectionResetError):
    pass  # the server answered 413 and hung up while the body was still being sent: refused as well
response, _ = client.request("GET", "/image/master.tex")
check(response.status == 403, f"/image serves only images: {response.status}")
response, _ = client.request("GET", "/image/images/evil.png")
check(response.status == 200 and response.getheader("Content-Type", "").startswith("image/png"), "a stored image is served")

# ---- the TeX compiler is locked down
def compile_with(master):
    client.json("POST", "/file/master.tex", {"content": master})
    response, data = client.request("POST", "/compile")
    log = ""
    try:
        with open(user_dir + "/master.log", errors="replace") as handle:
            log = handle.read()
    except OSError:
        pass
    return response.status, json.loads(data), log


status, result, _ = compile_with("\\documentclass{article}\\begin{document}Hello \\LaTeX\\end{document}")
check(result.get("success") is True, f"a normal document compiles: {result}")
response, pdf = client.request("GET", "/pdf")
check(pdf[:5] == b"%PDF-", "the PDF is served")

for label, body in [
    ("reading /etc/passwd", "\\documentclass{article}\\begin{document}\\input{/etc/passwd}\\end{document}"),
    ("reading a parent directory", "\\documentclass{article}\\begin{document}\\input{../../.flask_secret}\\end{document}"),
    ("reading the environment", "\\documentclass{article}\\begin{document}\\input{/proc/self/environ}\\end{document}"),
]:
    status, result, log = compile_with(body)
    check("root:x:" not in log and PASSWORD not in log, f"{label}: the file content reached the log")
    check(result.get("success") is not True, f"{label}: the compile should fail, got {result}")

os.makedirs("/tmp/wl-pwn", exist_ok=True)
status, result, log = compile_with("\\documentclass{article}\\begin{document}\\immediate\\write18{touch /tmp/wl-pwn/shell}\\end{document}")
check(not os.path.exists("/tmp/wl-pwn/shell"), "shell escape ran a command")
status, result, log = compile_with("\\documentclass{article}\\begin{document}\\newwrite\\f\\immediate\\openout\\f=../../escape.txt \\immediate\\write\\f{x}\\end{document}")
check(not os.path.exists("/home/latex/escape.txt") and not os.path.exists("/home/escape.txt"), "TeX wrote outside the project")

# ---- the starter ZIP: unpacked safely, or the demo project is used
def starter_case(label, data, expect_master=None, expect_files=()):
    base = f"/tmp/wl-starter-{label}"
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    zip_path = base + "/starter.zip"
    with open(zip_path, "wb") as handle:
        handle.write(data)
    run = subprocess.run(
        ["python3", "-c", "import app; app.ensure_workspace('%s/home/proj')" % base],
        cwd="/opt/weblatex", capture_output=True, text=True,
        env={**os.environ, "WEBLATEX_DATA": base + "/data", "WEBLATEX_STARTER": zip_path},
    )
    check(run.returncode == 0, f"{label}: ensure_workspace failed: {run.stderr[-300:]}")
    master = base + "/home/proj/master.tex"
    check(os.path.exists(master), f"{label}: no master.tex")
    if os.path.exists(master) and expect_master is not None:
        check(expect_master in open(master).read(), f"{label}: unexpected master.tex")
    for name in expect_files:
        check(os.path.exists(base + "/home/proj/" + name), f"{label}: missing {name}")
    return base, run


def make_zip(entries, compress=zipfile.ZIP_DEFLATED):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, value in entries.items():
            content, mode = value if isinstance(value, tuple) else (value, 0o100644)
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = compress
            z.writestr(info, content)
    return buf.getvalue()


starter_case("good", make_zip({"master.tex": b"% my starter\n\\documentclass{article}\\begin{document}x\\end{document}", "chapters/a.tex": b"a"}), "my starter", ["chapters/a.tex"])
base, run = starter_case("slip", make_zip({"master.tex": b"% evil starter", "../../escape.txt": b"x"}), "Web-LaTeX")
check(not os.path.exists(base + "/escape.txt") and not os.path.exists(base + "/home/escape.txt"), "slip: a file escaped")
check("starter ZIP not used" in run.stdout, "slip: the rejection is logged")
base, _ = starter_case("symlink", make_zip({"master.tex": b"% evil", "lnk": (b"/etc", stat.S_IFLNK | 0o777)}), "Web-LaTeX")
check(not os.path.islink(base + "/home/proj/lnk"), "symlink: a link was created")
starter_case("bomb", make_zip({"master.tex": b"% x", "big.bin": b"\x00" * (100 * 1024 * 1024)}), "Web-LaTeX")
starter_case("notzip", b"this is not a zip at all", "Web-LaTeX")
starter_case("empty", make_zip({}), "Web-LaTeX")

for path in ("/tmp/wl-pwn", sibling):
    shutil.rmtree(path, ignore_errors=True)
for name in os.listdir("/tmp"):
    if name.startswith("wl-starter-") or name.startswith("wl-secure"):
        shutil.rmtree("/tmp/" + name, ignore_errors=True)

if failures:
    print(f"{len(failures)} hardening test(s) failed")
    sys.exit(1)
print("hardening tests: all passed")
