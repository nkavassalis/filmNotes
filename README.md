# filmNotes

A field notebook for film photographers. Log rolls and locations as fast
as you can load film: pick a camera and a film, name the place (or let
your phone figure it out), jot a note, done. Works on desktop and phone,
installs to the home screen, and keeps everything on your own server.

## What it does

- **Rolls** — every roll you log: camera, film, shot date, optional note.
  Sorted by shot date, newest first. **All the locations that roll was
  shot at are listed under it**, each with its own note and visit time.
  Roll numbers auto-increment, but you can set a custom one (e.g. `24A`)
  at creation or renumber an old roll later — taken numbers are refused.
- **Locations** — every place you've shot, with **every roll shot there
  listed under it**, sorted by visit date, newest first.
- **Cameras / Film** — the gear lists that feed the New Roll dropdowns.
  Seeded with the usual suspects (Leica MP/M6, Canon 1V, Pentax 67/645N2,
  Bronica SQ-A; Portra, Delta, HP5, Tri-X, T-Max, Velvia, Provia, Acros,
  XP2...). Add your own from the page. Dropdowns sort **most recently
  used first**.
- **Lenses** — an expandable **Lenses** section at the bottom of the
  Cameras page (collapsed by default; tap to reveal, add, and browse).
  Lenses are **entirely optional**: leave the Lens field blank and
  nothing changes. Once you start using them, the New Roll popover
  **auto-selects the most recently used lens for whichever camera you
  pick** (switching cameras re-applies that camera's latest lens).
  In edit mode each lens card gets a pencil to choose **compatible
  cameras** (toggle chips): the lens then only appears in the dropdown
  for those cameras. A lens with none picked fits **every** camera —
  assignments narrow, they never gate.
- **New Roll** (bottom bar) — popover with Camera, Film, and (optional)
  Lens dropdowns, a
  Location field with a friendly name derived from the device location
  service (tap the crosshair to detect; the field is always editable so
  you can override with your own name), a **Shot on** date/time (defaults
  to now, editable), and an optional note. Typing a brand-new place name
  creates the location for you.
- **New Location** (bottom bar) — popover with the same location field,
  a **Visited on** date/time, and a note. It **adds the place to the roll
  shown in the popover** (the current camera and roll are displayed for
  context; the date prefills from that roll's shot date). Re-adding a
  place to the same roll updates its entry instead of duplicating it.
  With no rolls yet the location is created standalone.
- **Edit pencils** — hidden by default to keep things uncluttered. The
  pencil button in the top bar (left of the cog) toggles edit mode; while
  it's on, every roll card and location card shows a pencil to fix a
  mistake (roll number, camera, film, dates, notes, place name), and each
  location entry under a roll gets its own pencil for the entry **location**
  (change where the roll was shot — pick an existing place or type a new
  one), note and visit date.
- **Delete** — also behind the edit-mode toggle: a red trash button on
  every roll and location card, each with a confirm dialog. Rolls can be
  deleted any time (their places stay on the Locations page). A location
  can only be deleted once no rolls reference it — otherwise the app tells
  you so and keeps it.
- **Add a place to any roll** — in edit mode each roll card grows a
  **+ location** button: the New Location popover opens targeted at that
  roll (banner says "Adding to roll: #N"), so you can backfill places on
  older rolls, not just the newest one.
- **Maps links** — tap a location name to open Google Maps. If the
  backend has coordinates (captured when you used the location detect
  button) it links straight to the spot; otherwise it falls back to a
  search for the friendly name. Coordinates are never displayed.
- **Date times hidden by default** — the time is always collected and
  stored, but dates display as YYYY-MM-DD. The settings cog has a
  "Dates show time" toggle (Hide/Show) if you want the full timestamp.
- **Settings** (cog, top right) — UI theme: Auto (follows the system),
  Light, or Dark. Stored server-side, so every device you use agrees.
- **Pages drawer** — hamburger (top left) or swipe from the left edge
  exposes Rolls / Locations / Cameras / Film (no heading, just the list).
- **Bottom bar** — New Roll and New Location, pinned across every screen.
  It hides only while the settings popover is up.

## Install

Python 3.11+:

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py            # http://127.0.0.1:8961
```

First boot creates the SQLite database (`data/filmnotes.sqlite`) and seeds
the camera and film lists. Options: `--host`, `--port`, `--db PATH`,
`--config config.yaml` (keys: `server.host`, `server.port`,
`server.data_dir`).

## Home-screen app over WireGuard / Tailscale

filmNotes is built to live on your phone's home screen, served privately
from your own machine — no public exposure, no accounts.

1. Run it on a machine inside your WireGuard/Tailscale network
   (`--host 0.0.0.0` or `server.host: 0.0.0.0` in `config.yaml`).
2. Put TLS in front (e.g. `tailscale serve --bg 8961`, or your usual
   wireguard + reverse-proxy + certificate setup) and open the HTTPS URL
   on your phone.
3. iOS: **Share → Add to Home Screen**. Chrome/Edge on desktop: the
   address-bar **Install app** icon. It launches standalone — no browser
   chrome, its own icon, safe-area-aware top and bottom bars.

Serve it over plain HTTP and everything works except the crosshair: iOS
only exposes geolocation in secure contexts, so use HTTPS on the phone if
you want location detection. The Nominatim reverse-geocode call runs from
the *browser* (your phone), not the server, so the server itself needs no
outbound access. If the phone can't reach nominatim.openstreetmap.org the
field falls back to raw coordinates — you can always type the name.

## Running the tests

```
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest              # hermetic: db + api + UI contract
.venv/bin/python -m pytest -m ui        # real browser (Playwright + Chromium)
```

The `-m ui` tier boots the actual app against a throwaway database and
drives headless Chromium: computed styles, element geometry, touch
gestures, geolocation (stubbed), console-error capture. Screenshots land
in `tests/screenshots/`. It expects port 8961 to be free.

## Backup & init

`scripts/backup.sh` takes a consistent, gzipped snapshot of the database
using the SQLite online-backup API (safe while the server is serving —
never `cp` a live WAL database) and verifies the snapshot's integrity.
`scripts/init_db.py` creates a fresh seeded database or restores one from
a backup.

```
scripts/backup.sh                     # -> backups/filmnotes-<stamp>.sqlite.gz
scripts/init_db.py                    # create/verify data/filmnotes.sqlite
scripts/init_db.py --from-backup backups/filmnotes-2026-01-01_0300.sqlite.gz \
                   --db data/filmnotes.sqlite --force      # restore (stop server first)
```

Retention: the newest **16** backups are kept (weekly cron = ~4 months).
Override with `FILMNOTES_BACKUP_KEEP`; the database and output directory
with `FILMNOTES_DB` / `FILMNOTES_BACKUP_DIR`.

Weekly cron — add with `crontab -e` (substitute your real install path):

```
0 3 * * 0 /path/to/filmNotes/scripts/backup.sh >> /path/to/filmNotes/backups/backup.log 2>&1
```

## Layout

```
run.py                    entry point (config -> db -> flask)
scripts/backup.sh         weekly WAL-safe backup + verify + prune (see above)
scripts/init_db.py        create/verify/restore the database
filmnotes/
  db.py                   ALL SQL: schema, seeds, queries
  web.py                  Flask app, thin routes, JSON-only errors
  templates/index.html    single page
  static/app.js           routing, rendering, popovers, location service
  static/style.css        CSS variables; light/dark/auto
  static/manifest.webmanifest, icons
tests/                    hermetic + Playwright tiers (see docs below)
```

See `AGENTS.md` for the working-on-it guide.
