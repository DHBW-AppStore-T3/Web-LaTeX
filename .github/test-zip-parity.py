"""ZIP-parity test: run Web-LaTeX's safe_zip.unpack() against the shared hostile archives.

This script is run INSIDE the container (via docker exec -i) by the CI smoke test, using the
same archive set that the AppStore backend and Online-IDE also run (.github#13, item 3.3).

Usage (from smoke-test.sh, which fetches the pinned hostile_archives.py and passes it in the
environment variable HOSTILE_ARCHIVES_SRC):

    docker exec -i -e HOSTILE_ARCHIVES_SRC="$(cat hostile_archives.py)" wl python3 - < .github/test-zip-parity.py

Every archive must make the image's own /opt/weblatex/safe_zip.py raise Rejected and leave nothing behind.
"""

from __future__ import annotations

import os
import shutil
import sys

# safe_zip is part of the image; import it directly by file path to avoid
# conflicts with the 'app' Flask application that is already loaded.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("safe_zip", "/opt/weblatex/safe_zip.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
Rejected = _mod.Rejected
unpack = _mod.unpack

WORK = "/tmp/zip-parity-test"
failures = []
counter = [0]


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)
        print("FAIL:", message)


# ---------------------------------------------------------------------------
# Hostile archives: the single source of truth is appstore_upload_utils.hostile_archives, fetched by
# smoke-test.sh at a pinned commit, sha256-verified, and handed in through HOSTILE_ARCHIVES_SRC.
# ---------------------------------------------------------------------------

_src = os.environ.get("HOSTILE_ARCHIVES_SRC", "")
if not _src:
    sys.exit("HOSTILE_ARCHIVES_SRC is not set (smoke-test.sh passes the pinned hostile_archives.py)")
_ns: dict = {"__name__": "hostile_archives"}
exec(compile(_src, "hostile_archives.py", "exec"), _ns)
HOSTILE_ARCHIVES = _ns["HOSTILE_ARCHIVES"]
if len(HOSTILE_ARCHIVES) < 20:
    sys.exit(f"only {len(HOSTILE_ARCHIVES)} hostile archives loaded; refusing to run a weakened test")
print(f"loaded {len(HOSTILE_ARCHIVES)} hostile archives")


# ---------------------------------------------------------------------------
# Run each hostile archive through safe_zip.unpack()
# ---------------------------------------------------------------------------

os.makedirs(WORK, exist_ok=True)

for label, archive_bytes in HOSTILE_ARCHIVES:
    counter[0] += 1
    base = f"{WORK}/case{counter[0]}"
    os.makedirs(base)
    zip_path = f"{base}/a.zip"
    with open(zip_path, "wb") as fh:
        fh.write(archive_bytes)
    dest = f"{base}/out"

    rejected = False
    try:
        unpack(zip_path, dest)
    except Rejected:
        rejected = True

    written: list[str] = []
    if os.path.exists(dest):
        for root, dirs, files in os.walk(dest):
            written += [os.path.relpath(os.path.join(root, f), dest) for f in files + dirs]

    check(rejected, f"{label}: safe_zip accepted the archive (expected Rejected)")
    check(written == [], f"{label}: files were written despite rejection: {written}")
    if rejected and not written:
        print(f"OK: {label}")

shutil.rmtree(WORK, ignore_errors=True)

if failures:
    print(f"\n{len(failures)} parity test(s) FAILED")
    sys.exit(1)
print("\nzip parity tests: all passed")
