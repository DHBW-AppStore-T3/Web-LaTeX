#!/usr/bin/env bash
# Smoke test: login, open, compile, PDF in the platform's security context, then the security tests. Run by the central pipeline
# (DHBW-AppStore-T3/app-registry) against the locally built image, before the Trivy scan and before any push.
# IMAGE and PLATFORM_RUN_FLAGS (--user 1000:1000 --read-only --cap-drop ALL --security-opt no-new-privileges
# --network host) come from the pipeline; the pipeline removes the container afterwards.
set -euo pipefail

# shellcheck disable=SC2086  # PLATFORM_RUN_FLAGS is meant to split into words
docker run -d --name wl $PLATFORM_RUN_FLAGS \
  --tmpfs /tmp:exec,size=512m --tmpfs /home/latex:uid=1000,gid=1000,exec \
  -e WEBLATEX_USER=ci-user -e WEBLATEX_PASSWORD=ci-smoke-test \
  -e WEBLATEX_COOKIE_SECURE=0 \
  "$IMAGE"

ok=0
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null "http://[::1]:8080/login"; then ok=1; break; fi
  sleep 2
done
docker logs wl
[ "$ok" = 1 ]

jar=$(mktemp)
pdf=$(mktemp)
curl -fsS -c "$jar" -b "$jar" -o /dev/null -d "username=ci-user&password=ci-smoke-test" "http://[::1]:8080/login"
curl -fsS -c "$jar" -b "$jar" -o /dev/null "http://[::1]:8080/"
compile=$(curl -fsS -c "$jar" -b "$jar" -X POST "http://[::1]:8080/compile")
echo "$compile"
grep -q '"success":true' <<<"$compile"
curl -fsS -c "$jar" -b "$jar" -o "$pdf" "http://[::1]:8080/pdf"
[ "$(head -c 4 "$pdf")" = "%PDF" ]

# Security tests of the running app (access without login, paths, uploads, the TeX compiler, hostile starter
# ZIPs), executed in the container as the platform's unprivileged user. The session cookie is Secure in
# production; the container above runs with WEBLATEX_COOKIE_SECURE=0 because this test speaks plain HTTP.
docker exec -i wl python3 - < .github/test-hardening.py
