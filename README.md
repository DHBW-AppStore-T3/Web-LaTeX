# Web-LaTeX Editor

Ein browserbasierter LaTeX-Editor mit vollständiger LaTeX-Umgebung, Syntax-Highlighting und Live-PDF-Preview. Die App läuft als Pods (`appstore.yaml`, App-Vertrag v2): **ein Editor-Pod je Person** mit eigenem Speicher (2 GiB), HTTPS-Link und eigenem Passwort unter „Meine Zugänge“.

## User-Management

Jede Person erhält ihren eigenen Pod und damit einen isolierten Workspace mit eigenem Projektverzeichnis. Projekte und Einstellungen liegen im persistenten Home-Verzeichnis und überstehen Pause/Fortsetzen und Neustart.

- **Login:** Benutzername und Passwort stehen unter „Meine Zugänge“ (der Benutzername ist der Plattform-Benutzername).

## Konfigurierbare Variablen

| Variable | Beschreibung | Pflicht |
|---|---|---|
| `starter` | ZIP-Datei pro Team mit dem Startprojekt (LaTeX-Dateien), `master.tex` im Root, max. 1 MiB | Nein |

Die ZIP wird beim ersten Öffnen im persönlichen Workspace entpackt (`image/app/safe_zip.py`, Regeln siehe „Sicherheit“). Ohne ZIP, oder wenn sie abgelehnt wird (Grund im Container-Log: `web-latex: starter ZIP not used: …`), startet der Editor mit dem mitgelieferten Demo-Projekt (`image/demo/`).

## Features

- Live-PDF-Preview nach dem Kompilieren
- Datei-Explorer mit Unterstützung für mehrere `.tex`-Dateien und Unterverzeichnisse
- Neue `.tex`-Dateien direkt im Browser anlegen
- Bilder (PNG, JPG, JPEG, GIF) hochladen und per `\includegraphics{}` einbinden
- Auto-Save (500ms Debounce)
- Kompilierung via `pdflatex` (zweifacher Lauf für TOC/Referenzen)

## Sicherheit

Das Backend prüft Uploads beim Anlegen des Deployments; die App prüft **noch einmal selbst**:

- **Starter-ZIP:** das ganze Archiv wird vor dem Schreiben geprüft (höchstens 2000 Einträge, 32 MiB je Eintrag, 64 MiB insgesamt, gezählt an den wirklich entpackten Bytes; Prüfsummen). Ein schlechter Eintrag verwirft das Archiv: absolute Pfade, `..`, Backslashes, Steuerzeichen, Links und Gerätedateien, verschlüsselte oder überlappende Einträge, doppelte Namen. Geschrieben werden nur normale Dateien und Verzeichnisse, zuerst in ein Staging-Verzeichnis; Vorhandenes wird nie überschrieben.
- **Bilder:** nur der Dateiname ohne Verzeichnisse (`secure_filename`); der Inhalt muss das Bild der Endung sein (PNG mit Chunk-Prüfsummen, JPEG, GIF), höchstens 100 Millionen Pixel, nichts hinter dem Dateiende. Anfragen sind auf 12 MiB begrenzt.
- **Pfade:** alle Datei-Routen lösen den Pfad auf und verlangen, dass er echt innerhalb des Projektverzeichnisses liegt (nicht nur dasselbe Präfix). `/image/...` liefert nur Bilder.
- **pdflatex** läuft ohne Shell-Escape und mit „paranoidem“ Dateizugriff: keine absoluten Pfade, keine Elternverzeichnisse, keine Punktdateien beim Lesen und Schreiben.
- **Sitzung und Header:** Cookie `HttpOnly`, `SameSite=Lax` und `Secure` (nur der Smoke-Test schaltet `Secure` mit `WEBLATEX_COOKIE_SECURE=0` ab, weil er HTTP spricht); `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`; die CodeMirror-Dateien vom CDN haben Subresource-Integrity-Hashes.

`.github/test-hardening.py` prüft das im Smoke-Test gegen die laufende App.

## Image und CI

Die Flask-App und die Templates liegen unter `image/app/`, das Demo-Projekt unter `image/demo/`. `image/Dockerfile` wird von `.github/workflows/ci.yml` gebaut (zentrale Pipeline aus `app-registry`: Vertrag, hadolint, Smoke-Test, Trivy) und mit dem Sicherheitskontext der Plattform getestet (UID 1000, Read-only-Root, keine Capabilities; `.github/smoke-test.sh`: Login, Demo-Projekt öffnen und kompilieren).

- **Pull Request:** das Image wird gebaut und getestet, aber nicht veröffentlicht.
- **Push auf `main`:** das Image wird zusätzlich nach GHCR gepusht. Den Digest zeigt die Zusammenfassung des Jobs.
- Nach einer Änderung den neuen Digest in `appstore.yaml` eintragen und eine neue Version taggen. Die Plattform deployt nur Images, die per Digest festgelegt sind.

## Ältere Versionen

Die VM-Versionen (`v1.x`, Terraform und Packer) wurden aus dem Repository entfernt. Sie bleiben über ihre Git-Tags (z. B. `v1.1.1`) abrufbar.
