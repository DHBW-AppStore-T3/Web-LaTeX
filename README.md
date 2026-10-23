# Web-LaTeX Editor

Ein browserbasierter LaTeX-Editor mit vollständiger LaTeX-Umgebung, Syntax-Highlighting und Live-PDF-Preview. Die App läuft als Pods (`appstore.yaml`, App-Vertrag v2): **ein Editor-Pod je Person** mit eigenem Speicher (2 GiB), HTTPS-Link und eigenem Passwort unter „Meine Zugänge“.

## User-Management

Jede Person erhält ihren eigenen Pod und damit einen isolierten Workspace mit eigenem Projektverzeichnis. Projekte und Einstellungen liegen im persistenten Home-Verzeichnis und überstehen Pause/Fortsetzen und Neustart.

- **Login:** Benutzername und Passwort stehen unter „Meine Zugänge“ (der Benutzername ist der Plattform-Benutzername).

## Konfigurierbare Variablen

| Variable | Beschreibung | Pflicht |
|---|---|---|
| `starter` | ZIP-Datei pro Team mit dem Startprojekt (LaTeX-Dateien), `master.tex` im Root, max. 1 MiB | Nein |

Die ZIP wird beim ersten Öffnen im persönlichen Workspace entpackt. Ohne ZIP startet der Editor mit dem mitgelieferten Demo-Projekt (`image/demo/`).

## Features

- Live-PDF-Preview nach dem Kompilieren
- Datei-Explorer mit Unterstützung für mehrere `.tex`-Dateien und Unterverzeichnisse
- Neue `.tex`-Dateien direkt im Browser anlegen
- Bilder (PNG, JPG, JPEG, GIF) hochladen und per `\includegraphics{}` einbinden
- Auto-Save (500ms Debounce)
- Kompilierung via `pdflatex` (zweifacher Lauf für TOC/Referenzen)

## Image und CI

Die Flask-App und die Templates liegen unter `image/app/`, das Demo-Projekt unter `image/demo/`. `image/Dockerfile` wird von `.github/workflows/image.yml` gebaut und mit dem Sicherheitskontext der Plattform getestet (UID 1000, Read-only-Root, keine Capabilities; Smoke-Test: Login, Demo-Projekt öffnen und kompilieren).

- **Pull Request:** das Image wird gebaut und getestet, aber nicht veröffentlicht.
- **Push auf `main` oder `dev`:** das Image wird zusätzlich nach GHCR gepusht. Den Digest zeigt die Zusammenfassung des Jobs.
- Nach einer Änderung den neuen Digest in `appstore.yaml` eintragen und eine neue Version taggen. Die Plattform deployt nur Images, die per Digest festgelegt sind.

## Ältere Versionen

Die VM-Versionen (`v1.x`, Terraform und Packer) wurden aus dem Repository entfernt. Sie bleiben über ihre Git-Tags (z. B. `v1.1.1`) abrufbar.
