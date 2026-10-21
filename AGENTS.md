# AGENTS.md — working on filmNotes

## Project mode: REAL

Software the user relies on from their phone. GitHub-hosted, private,
full test gates before any push (see Guardrails at the bottom). Branch:
**main**.

## Purpose

A web-based field notebook for film photographers, delivered like a
home-screen app over WireGuard/Tailscale (same delivery pattern as the
rssgate project). Users log rolls (camera + film + location + note) and
locations; cameras and film lists feed the New Roll dropdowns, sorted
most-recently-used first. Desktop and mobile, rigid mobile UI (it must
not feel like a webpage), auto/light/dark theme stored server-side.

## Layout

```
run.py                     entry: --config/--db/--host/--port; default port 8961
filmnotes/
  db.py                    ALL SQL lives here. Schema, additive _migrate,
                           seeds (SEED_CAMERAS, SEED_FILMS), settings key/value,
                           list_* rows carry used_count + last_used for MRU
                           sorting. roll_locations is the roll<->location
                           junction (note + visited_at live on the entry).
  web.py                   create_app(db_path). Thin routes, no SQL.
                           _body()/_str()/_note()/_num() input hygiene;
                           /api/* errors are ALWAYS JSON, never HTML 500.
  templates/index.html     single page. Overlays ship hidden; ids are
                           contract-tested against app.js (test_ui_contract).
  static/app.js            one script: hash router (#/rolls #/locations
                           #/cameras #/film), render fns, drawer + swipe,
                           modals, theme, geolocation->Nominatim.
  static/style.css         CSS variables. Light tokens in :root; dark tokens
                           DUPLICATED in two selectors (prefers-color-scheme
                           for auto + [data-theme=dark] for forced). Keep in
                           sync when editing colors.
  static/manifest.webmanifest, favicon.svg, apple-touch-icon.png,
  icon-192.png, icon-512.png   PWA/home-screen assets (icons generated with
                           PIL; regenerate via a throwaway script if changed).
tests/
  conftest.py              conn/app/client fixtures, throwaway sqlite
  test_db.py               seeds, CRUD, MRU fields, current roll
  test_api.py              API contract + input hygiene fuzz
  test_ui_contract.py      static JS<->template<->CSS contract
  test_ui_real.py          Playwright + headless Chromium (mark: ui)
  test_backup_scripts.py   backup.sh / init_db.py round-trips (hermetic)
  screenshots/             written by the ui tier; GITIGNORED (see guardrails)
README.md                  end users        AGENTS.md      agents (this file)
```

## How to run

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt \
    && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python run.py                 # 127.0.0.1:8961, data/filmnotes.sqlite
.venv/bin/python -m pytest              # hermetic tier (default; -m "not ui")
.venv/bin/python -m pytest -m ui        # browser tier; needs port 8961 free
```

Pin the venv's `playwright` to the version whose chromium build is already
in `~/.cache/ms-playwright` (currently 1.63.0 / chromium-1243); otherwise
the ui tier fails with "Executable doesn't exist" and you must
`playwright install chromium`.

## Design decisions (and why — don't undo casually)

- **Flask + SQLite (WAL) + vanilla JS, no build step** — matches rssgate,
  which the user runs on their tailnet. One process, one file of JS, one
  stylesheet.
- **Edit pencils are gated behind an edit mode toggle** (topbar
  `#edit-mode-btn`, toggles `body.edit-mode`). The per-card pencils use
  `visibility: hidden` by default, NOT `display: none` — that keeps the
  "only two display:none rules" UI contract intact and preserves card
  layout (padding-right is reserved). Editing is rare; default view is
  clean.
- **Edit pencils reuse the create modals** (app.js `edit` context var:
  {kind:'roll'|'loc'|'entry'}): roll edit hides the location group, loc
  edit hides the current-roll banner, and a third small modal
  (`entry-modal`) edits one roll-at-place entry (note + visited date).
  Pencil buttons are rendered inside cards, so they are wired by event
  delegation on #view via `data-act` (never ids — the id contract only
  covers static template ids). Server side: PUT /api/rolls/<id>,
  PUT /api/locations/<id>, PUT /api/rolls/<id>/locations/<lid>, each a
  strict field whitelist (web.py), 404 JSON for unknown ids, 400 for
  empty/invalid patches.
  SCAR: roll_locations has a COMPOSITE key — updates must filter on
  roll_id AND location_id (update_roll_location does this by hand; the
  generic _apply_update helper must never be pointed at the junction).
- **Maps links** (app.js `mapUrl`): coordinates when the location has
  them (captured client-side by the detect button at creation), else a
  name query. Coordinates stay hidden in the UI; target=_blank so iOS
  standalone hands them to Safari (rssgate pattern).
- **show_times setting** ("0"/"1", default "0"): the time is ALWAYS
  collected and stored; the toggle only changes fmtDT's display. Stored
  like theme (server-side, shared across devices).
- **roll_no is the user-visible number; id stays the internal key.**
  Auto-numbering = the row id as text (assigned in add_roll right after
  insert), so it continues on its own; users may set a custom number at
  creation or renumber later via the edit modal. UNIQUE index +
  db.roll_no_taken() pre-check (web layer returns a friendly 400 "that
  roll number is already in use"); the edit check excludes the roll's own
  id so saving your own number is fine. All UI display uses roll_no;
  data-act/data-id attributes and API paths use id. Never render r.id to
  the user.
- **Backups use the SQLite online-backup API** (scripts/backup.sh), never
  cp of a live WAL db; snapshots are gzipped, integrity-checked, and
  pruned to the newest 16. Weekly cron is INSTALLED on the user's box
  (crontab -l to inspect; log at backups/backup.log). The user's live
  database is precious — stop the server before any restore.
- **Rolls accumulate locations (many-to-many)** via `roll_locations(roll_id,
  location_id, note, visited_at)`. This is the user's mental model and the
  original spec ("rolls with EACH location under it"): **New Location
  attaches the place to the CURRENT roll** (the one the popover shows).
  The note the user types is the note for THAT roll at THAT place (lives
  on the junction row, not on `locations.note`). `attach_location` is an
  upsert: re-adding updates the entry, a blank note never erases an
  existing one, visited_at defaults to the roll's shot date. With no rolls
  at all, New Location creates a standalone place and the note falls back
  to `locations.note`. `add_roll` links the roll's first location. The old
  `rolls.location_id` column is migrated away (backfill + drop).
- **Shot/visit dates are local naive strings** `"YYYY-MM-DD HH:MM"` (what
  `datetime-local` gives you, T normalized to a space). Fixed width, so
  plain string sort orders them; the user's wall-clock time is the point,
  so no timezone conversion happens anywhere. `created_at` stays UTC ISO
  for auditing. `_datetime()` in web.py validates/normalizes input.
  Sorting: `shot_at DESC, id DESC` (ties within a minute fall back to
  creation order). MRU `last_used` = `MAX(COALESCE(shot_at, created_at))`.
  A roll that implicitly creates its location gives it its shot_at as
  visited_at; `touch_location_visit` only ever moves visited_at forward.
- **Settings live in SQLite (key/value `settings` table), not YAML** — the
  spec says "stored server side" and shared across devices; the theme must
  survive reloads and apply server-side in the template (`data-theme`) to
  avoid a light-flash on load in dark mode.
- **Theme model**: `auto` = no `data-theme` attribute, CSS decides via
  `prefers-color-scheme`; `light`/`dark` force the attribute. Both dark
  token blocks must stay identical.
- **Bottom bar hides ONLY for settings** (spec). Implemented via
  `body.settings-open #bottombar`. `test_ui_contract` asserts only two
  rules in the CSS may set `display: none` (the `[hidden]` contract and
  this one) — if you need another overlay that hides the bar, update the
  spec and the test together.
- **MRU dropdown sorting** is done client-side (`mruSort`) from
  `used_count`/`last_used` supplied by `list_cameras`/`list_films`. Server
  returns alphabetical; UI owns ordering.
- **Location service** = browser geolocation in the client + OSM Nominatim
  reverse geocode (client-side fetch). The server never sees coordinates
  unless a new location is created with them. Any failure degrades to
  "lat, lon" text; the field is ALWAYS an editable override (spec).
  Tests stub geolocation and route-intercept Nominatim.
- **Rolls create locations implicitly** by name (case-insensitive match,
  `get_or_create_location`). New Location modal shows the most recent roll
  as read-only "current camera / current roll" (`db.current_roll`,
  `GET /api/locations/current`).
- **Rigid mobile shell**: body is `height:100dvh; overflow:hidden` flex
  column; `#view` is the ONLY scroller (`overscroll-behavior:contain`);
  viewport pins scale; safe-area insets on top/bottom bars; modals are
  bottom sheets on phones, centered cards ≥640px. Never make body
  scrollable again.
- **Overlays ship hidden** and `[hidden]{display:none!important}` is
  load-bearing (rssgate scar). Modal dismiss = click veil (target ===
  section) or Cancel; settings also closes via Done.
- **API errors are JSON always** including 404/500 under /api/ (tests
  assert content-type).

## Conventions

- Routes stay thin; new SQL goes in `db.py` only.
- Timestamps: UTC `YYYY-MM-DDTHH:MM:SSZ` strings; list pages order by
  `id DESC` (second-granularity timestamps tie within a second).
- Every new element id used by app.js must exist in the template —
  `test_ui_contract.test_every_js_id_exists_in_template` enforces it;
  dynamically created ids go in its `dynamic` set.
- Escape all interpolated user text with `esc()` before innerHTML.
- New pages: add to `PAGES` in app.js, a `drawer-item` with `data-page`,
  and a `render*` fn; the contract test checks the set matches.

## Invariants (test-enforced unless noted)

1. Seeds: 6 cameras, 15 films, re-running init_db never duplicates.
2. `GET /api/rolls` rows carry camera/film NAMES plus a `locations` list
   ({id, name, note, visited_at}); `GET /api/locations` nests a `rolls`
   list per location (with the per-entry note). Both pages sort by the
   user-visible date (shot_at / visited_at) newest first, `id DESC` as
   tiebreak — never by created_at or id alone. A location added via New
   Location must appear under the current roll immediately (never as a
   0-roll island when a current roll exists).
3. POST /api/rolls requires valid camera_id + film_id (ints) and either
   location_id or a non-empty location_name; bad input => 400 JSON.
4. lat/lon arrive together, in range; theme is only auto|light|dark;
   shot_at/visited_at must parse as `YYYY-MM-DD HH:MM` (T tolerated,
   optional seconds) or 400; absent defaults to server-local now.
5. Bottom bar visible on every page and while roll/location popovers are
   open; hidden only with settings open.
6. No horizontal overflow at 390px width; no console errors on any screen
   (ui tier asserts `page.errors == []`).
7. Playwright waits for hidden overlays must use `state="hidden"`, never a
   `[hidden]` selector (visible-state waits can never resolve).
8. Navigation asserts must wait on rendered content (e.g.
   `h1.page-title:has-text(...)` via `goto_page()` helper), not just the
   hash change — hashchange renders one task later and you'll race.

## Known issues / TODOs

- Rolls/locations/cameras/films are create-only; no edit/delete yet —
  notably no way to unlink a location from a roll or delete a location.
- No auth: relies on the WireGuard/Tailscale perimeter (by design).
- Nominatim is the only geocoder; no offline place names (see unverified).
- Camera/film rename would orphan usage stats (no update path at all yet).

## Testing limitations / unverified

- **Real Nominatim was never called** — ui tests stub geolocation and
  intercept the reverse-geocode fetch. Field behavior against the live
  service (rate limits, odd addresses) is unverified.
- **Home-screen install over TLS/WireGuard was not exercised** — the PWA
  wiring (manifest, standalone, icons, safe areas) is contract-tested and
  Chromium-rendered, but Add-to-Home-Screen on an actual iPhone behind the
  tunnel is a manual check.
- Geolocation *denial* UX (permission prompt dismissed) shows the toast
  fallback; only the success and network-failure paths are automated.
- Multi-device theme sync is verified only via reload on one context.

## Do-not-touch list

- `SEED_CAMERAS` / `SEED_FILMS` contents (user-specified verbatim list).
- The two dark-token blocks in style.css must remain identical to each
  other.
- `[hidden]{display:none!important}` and the "only settings hides the
  bottom bar" rule — spec'd behavior; change only with the user.
- The public-forever rule: never commit secrets, internal hostnames,
  tailnet names, IPs, or home-directory paths into repo files.

## Guardrails (REAL project)

- GitHub account must be `nkavassalis` (verify `gh auth status` before
  any push; STOP if it's anyone else). Repo `nkavassalis/filmNotes`,
  default branch **main**, **PUBLIC by the user's explicit decision** —
  the public-forever rule and the no-secrets/no-internal-details rule
  matter extra here. `tests/screenshots/` is GITIGNORED: screenshots
  taken against the live DB contain the user's real shoot data and once
  got pushed (history was rewritten to purge them — never re-add).
- Never push broken or untested code: BOTH tiers green first —
  `.venv/bin/python -m pytest` AND `.venv/bin/python -m pytest -m ui`
  (14 browser tests incl. computed-style and geometry assertions; the
  ui tier is the browser-level gate, screenshots in tests/screenshots/).
- Work on a branch, merge via PR or fast-forward; keep README.md and this
  file current with every meaningful change.
