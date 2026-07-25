#cloud-config

bootcmd:
  - mkdir -p /etc/weblatex/users
  - chown root:www-data /etc/weblatex /etc/weblatex/users
  - chmod 750 /etc/weblatex /etc/weblatex/users

write_files:
%{ if length(assignment_files) > 0 ~}
%{ for _, file in assignment_files ~}
  - path: /tmp/assignment/${file.name}
    permissions: '0644'
    owner: root:root
    encoding: b64
    content: ${file.content_b64}
%{ endfor ~}
%{ endif ~}

%{ for user in team_users ~}
  - path: /etc/weblatex/users/${replace(replace(user.email, "@", "_at_"), ".", "-")}.env
    permissions: '0640'
    owner: root:www-data
    encoding: b64
    content: ${base64encode("EMAIL=${user.email}\nPASSWORD=${user.password}\n")}
%{ endfor ~}

  - path: /usr/local/bin/weblatex-provision.sh
    permissions: '0700'
    owner: root:root
    content: |
      #!/bin/bash
      set -euo pipefail
      LOG="[weblatex-provision]"
      BASE_DIR="/var/www/weblatex"

      mkdir -p "$BASE_DIR"
      chown www-data:www-data "$BASE_DIR"
      chmod 755 "$BASE_DIR"

      # ── 1. Generate persistent Flask secret_key ─────────────────────────────
      if [ ! -f /etc/weblatex/flask_secret ]; then
          python3 -c "import os; open('/etc/weblatex/flask_secret','wb').write(os.urandom(32))"
          chown root:www-data /etc/weblatex/flask_secret
          chmod 640 /etc/weblatex/flask_secret
      fi

      # ── 2. Create per-user directory and seed initial documents ─────────────
      for envfile in /etc/weblatex/users/*.env; do
          [ -f "$envfile" ] || continue

          EMAIL=""
          while IFS='=' read -r key val; do
              case "$key" in
                  EMAIL) EMAIL="$val" ;;
              esac
          done < "$envfile"
          [ -z "$EMAIL" ] && continue

          UNAME=$(echo "$EMAIL" | sed 's/@/_/;s/\./-/g')
          UDIR="$BASE_DIR/$UNAME"
          mkdir -p "$UDIR"

          # process assignment_files
          if [ -d /tmp/assignment ] && [ "$(ls -A /tmp/assignment 2>/dev/null)" ]; then
              for srcfile in /tmp/assignment/*; do
                  fname=$(basename "$srcfile")
                  if echo "$fname" | grep -qi '\.zip$'; then
                      unzip -o "$srcfile" -d "$UDIR" > /tmp/unzip_"$UNAME".log 2>&1 || \
                          echo "$LOG WARNING: unzip failed for $fname"
                  else
                      cp "$srcfile" "$UDIR/$fname"
                  fi
              done
          fi

          # no assignment_files provided — fall back to demo ZIP bundled in the image
          if [ ! -f "$UDIR/master.tex" ]; then
              unzip -o /opt/weblatex/demo_project.zip -d "$UDIR" > /tmp/unzip_demo_"$UNAME".log 2>&1 || \
                  echo "$LOG WARNING: demo unzip failed for $UNAME"
          fi

          chown -R www-data:www-data "$UDIR"

          # pre-compile twice to resolve TOC/cross-references
          pdflatex -interaction=nonstopmode -output-directory="$UDIR" "$UDIR/master.tex" \
              > /tmp/pdflatex_"$UNAME"_1.log 2>&1 || true
          pdflatex -interaction=nonstopmode -output-directory="$UDIR" "$UDIR/master.tex" \
              > /tmp/pdflatex_"$UNAME"_2.log 2>&1 || true
          rm -f "$UDIR"/*.aux "$UDIR"/*.log "$UDIR"/*.out "$UDIR"/*.toc 2>/dev/null || true
          chown -R www-data:www-data "$UDIR"
      done

      rm -rf /tmp/assignment

      # ── 1. Start services ────────────────────────────────────────────────────
      echo "$LOG STEP 1: Starting services..."
      systemctl start weblatex
      systemctl enable weblatex

      for i in $(seq 1 30); do
          curl -sf http://127.0.0.1:5000/ > /dev/null 2>&1 && echo "$LOG Flask ready." && break
          sleep 2
      done

      # reload nginx, not restart — restart would not destroy Flask sessions but reload is sufficient
      systemctl reload nginx || systemctl start nginx

      HTTP_CODE=$(curl -s -o /dev/null -w "%%{http_code}" http://localhost/ || echo "000")
      echo "[weblatex-test] HTTP status: $HTTP_CODE (expected 200)"
      echo "$LOG All steps done."

runcmd:
  - bash /usr/local/bin/weblatex-provision.sh
