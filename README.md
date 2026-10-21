# Web-LaTeX Editor
 
Ein browserbasierter LaTeX-Editor, der pro Team eine dedizierte VM mit vollständiger

LaTeX-Umgebung, Syntax-Highlighting und Live-PDF-Preview bereitstellt. Nutzer melden

sich mit ihren persönlichen Zugangsdaten an und arbeiten in einem isolierten Workspace.
 
## User-Management
 
Jeder Nutzer erhält einen individuellen Account mit E-Mail-Adresse als Benutzername

und einem automatisch generierten Passwort. Die Zugangsdaten werden nach dem Deployment

per Mail versendet. Innerhalb eines Teams teilen sich alle Nutzer dieselbe VM, arbeiten

aber in voneinander getrennten Workspaces — jeder Nutzer hat sein eigenes Projektverzeichnis.
 
## VM-Deployment
 
Es wird **eine VM pro Team** deployed. Bei zwei Teams entstehen zwei VMs.

Alle Nutzer eines Teams greifen auf dieselbe VM zu, erreichen den Editor jedoch

auf individuellen Ports (ab Port 8080, aufsteigend pro Nutzer).
 
## Deployment-Dauer
 
| Phase | Dauer |

|---|---|

| Packer Image Build | ca. 15–20 Minuten (einmalig) |

| Terraform Apply (pro Team) | ca. 3–5 Minuten |

| VM-Boot + cloud-init | ca. 2–3 Minuten |

| **Gesamt (erstmalig)** | **ca. 20–30 Minuten** |
 
Bei Deployments mit einem bereits vorhandenen Image entfällt der Packer-Build —

dann ca. 5–8 Minuten gesamt.
 
## Konfigurierbare Variablen
 
| Variable | Beschreibung | Pflicht |

|---|---|---|

| `assignment_files` | ZIP-Datei pro Team mit dem Startprojekt (LaTeX-Dateien) | **Ja** |

| `network_uuid` | UUID des internen Netzwerks | Ja (Default vorhanden) |

| `floating_ip_pool` | Name des External Networks für öffentliche IPs | Ja (Default vorhanden) |

| `shared_secgroup_id` | ID der Security Group | Ja (Default vorhanden) |
 
### Wichtig: Aufgabendateien (`assignment_files`)
 
Für jedes Team **muss** eine ZIP-Datei hochgeladen werden. Die ZIP wird beim

VM-Start entpackt und bildet den initialen LaTeX-Workspace des Teams. Die ZIP muss mindestens

eine `master.tex` im Root enthalten.
 
## Features
 
- Live-PDF-Preview nach dem Kompilieren

- Datei-Explorer mit Unterstützung für mehrere `.tex`-Dateien und Unterverzeichnisse

- Neue `.tex`-Dateien direkt im Browser anlegen

- Bilder (PNG, JPG, JPEG, GIF) hochladen und per `\includegraphics{}` einbinden

- Auto-Save (500ms Debounce)

- Kompilierung via `pdflatex` (zweifacher Lauf für TOC/Referenzen)

 

## Pod-Variante (ab v2.0.0)

Ab Version `v2.0.0` läuft Web-LaTeX als Pods statt als VMs (`appstore.yaml`, App-Vertrag v2):
**ein Editor-Pod je Person** mit eigenem Speicher (2 GiB), HTTPS-Link und eigenem Passwort
unter „Meine Zugänge“. Keine VM, kein Packer-Build, kein OpenStack-Credential.

- **Login:** Benutzername und Passwort stehen unter „Meine Zugänge“ (der Benutzername ist
  nicht mehr die E-Mail-Adresse, sondern der Plattform-Benutzername).
- **Startprojekt:** Die optionale ZIP-Variable `starter` (ein Startprojekt pro Team, `master.tex`
  im Root, max. 1 MiB) wird beim ersten Öffnen im persönlichen Workspace entpackt. Ohne ZIP
  startet der Editor mit dem mitgelieferten Demo-Projekt (`image/demo/`).
- **App-Code:** Die Flask-App und die Templates liegen jetzt unter `image/app/` (früher als
  Heredocs in `packer/scripts/provision.sh`); das Image enthält dieselbe TeX-Live-Auswahl wie die VM.
- **Image:** `image/Dockerfile` wird von `.github/workflows/image.yml` gebaut (inkl. Smoke-Test:
  Login, Demo-Projekt öffnen und kompilieren). Nach einer Änderung den neuen Digest in
  `appstore.yaml` eintragen und eine neue Version taggen.
- Die Versionen `v1.x` (Terraform/Packer) laufen unverändert weiter.
