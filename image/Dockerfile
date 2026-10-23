# Web-LaTeX editor for the pod runtime (appstore.yaml). One container per person;
# the platform sets user (UID 1000), a read-only root filesystem and the login
# (env WEBLATEX_USER / WEBLATEX_PASSWORD).
FROM docker.io/library/python:3.12.15-slim-bookworm

# Same TeX Live selection as the former VM image (v1.x).
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      texlive-latex-base \
      texlive-latex-recommended \
      texlive-latex-extra \
      texlive-fonts-recommended \
      texlive-lang-german \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# The Flask app and the demo project come from the repo (they used to be
# heredocs in provision.sh). /opt/weblatex/starter is the mount point for the
# optional starter ZIP (wizard variable "starter").
COPY app /opt/weblatex
COPY demo /opt/weblatex/demo
RUN mkdir -p /opt/weblatex/starter

# HOME is the storage volume (mounted by the platform): projects, the session
# key and the TeX Live font cache (~/.texlive*) live there.
ENV HOME=/home/latex \
    WEBLATEX_DATA=/home/latex \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The cluster is IPv6-primary: listen on all families, not on 127.0.0.1.
# One worker with threads (compilation can take up to 2 x 60 s).
EXPOSE 8080
CMD ["gunicorn", "--bind", "[::]:8080", "--workers", "1", "--threads", "4", "--timeout", "150", "--chdir", "/opt/weblatex", "app:app"]
