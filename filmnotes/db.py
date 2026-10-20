"""ALL SQL lives here. Routes stay thin.

Schema notes
------------
* settings is a simple key/value table (server-side user settings, e.g.
  theme). Whitelist + validation live in web.py, storage is dumb.
* rolls references cameras/films/locations by id (FKs ON).
* list_cameras/list_films carry used_count + last_used so the UI can sort
  dropdowns "most recently used first" without a second query.
* Timestamps are UTC ISO-8601 strings (second precision), sortable as text.
"""
import sqlite3
from datetime import datetime, timezone

SEED_CAMERAS = [
    "Leica MP", "Leica M6", "Canon 1V",
    "Pentax 67", "Bronica SQ-A", "Pentax 645N2",
]

SEED_FILMS = [
    "Fujifilm Provia 100", "Fujifilm Velvia 50", "Fujifilm Velvia 100",
    "Kodak Portra 160", "Kodak Portra 400", "Kodak Portra 800",
    "Ilford Delta 100", "Ilford Delta 400",
    "Ilford XP2 400", "Ilford HP5 400",
    "Kodak Tri-X 400",
    "Kodak T-Max 100", "Kodak T-Max 400", "Kodak T-Max 3200",
    "Fujifilm Acros II",
]

DEFAULT_SETTINGS = {"theme": "auto"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cameras (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS films (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS locations (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  note       TEXT NOT NULL DEFAULT '',
  lat        REAL,
  lon        REAL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rolls (
  id          INTEGER PRIMARY KEY,
  camera_id   INTEGER NOT NULL REFERENCES cameras(id),
  film_id     INTEGER NOT NULL REFERENCES films(id),
  location_id INTEGER NOT NULL REFERENCES locations(id),
  note        TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rolls_location ON rolls(location_id);
CREATE INDEX IF NOT EXISTS idx_rolls_camera   ON rolls(camera_id);
CREATE INDEX IF NOT EXISTS idx_rolls_film     ON rolls(film_id);
"""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) c FROM cameras").fetchone()["c"] == 0:
        ts = now()
        conn.executemany("INSERT INTO cameras(name, created_at) VALUES (?,?)",
                         [(n, ts) for n in SEED_CAMERAS])
    if conn.execute("SELECT COUNT(*) c FROM films").fetchone()["c"] == 0:
        ts = now()
        conn.executemany("INSERT INTO films(name, created_at) VALUES (?,?)",
                         [(n, ts) for n in SEED_FILMS])
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?,?)",
                     (k, v))
    conn.commit()


# ---------------------------------------------------------------- settings

def get_settings(conn):
    out = dict(DEFAULT_SETTINGS)
    for row in conn.execute("SELECT key, value FROM settings"):
        out[row["key"]] = row["value"]
    return out


def set_settings(conn, patch):
    for k, v in patch.items():
        conn.execute("INSERT INTO settings(key, value) VALUES(?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (k, v))
    conn.commit()
    return get_settings(conn)


# ---------------------------------------------------------------- cameras

def list_cameras(conn):
    return [dict(r) for r in conn.execute(
        """SELECT c.id, c.name, COUNT(r.id) AS used_count,
                  MAX(r.created_at) AS last_used
           FROM cameras c LEFT JOIN rolls r ON r.camera_id = c.id
           GROUP BY c.id ORDER BY c.name""")]


def get_camera(conn, camera_id):
    return conn.execute("SELECT * FROM cameras WHERE id=?",
                        (camera_id,)).fetchone()


def add_camera(conn, name):
    row = conn.execute("SELECT * FROM cameras WHERE name = ?", (name,)).fetchone()
    if row is None:
        cur = conn.execute("INSERT INTO cameras(name, created_at) VALUES (?,?)",
                           (name, now()))
        conn.commit()
        row = conn.execute("SELECT * FROM cameras WHERE id=?",
                           (cur.lastrowid,)).fetchone()
    return dict(row)


# ---------------------------------------------------------------- films

def list_films(conn):
    return [dict(r) for r in conn.execute(
        """SELECT f.id, f.name, COUNT(r.id) AS used_count,
                  MAX(r.created_at) AS last_used
           FROM films f LEFT JOIN rolls r ON r.film_id = f.id
           GROUP BY f.id ORDER BY f.name""")]


def get_film(conn, film_id):
    return conn.execute("SELECT * FROM films WHERE id=?", (film_id,)).fetchone()


def add_film(conn, name):
    row = conn.execute("SELECT * FROM films WHERE name = ?", (name,)).fetchone()
    if row is None:
        cur = conn.execute("INSERT INTO films(name, created_at) VALUES (?,?)",
                           (name, now()))
        conn.commit()
        row = conn.execute("SELECT * FROM films WHERE id=?",
                           (cur.lastrowid,)).fetchone()
    return dict(row)


# ---------------------------------------------------------------- locations

def list_locations(conn):
    """Locations newest-first, each with its rolls (newest-first)."""
    out = []
    for loc in conn.execute("SELECT * FROM locations ORDER BY id DESC"):
        rolls = [dict(r) for r in conn.execute(
            """SELECT r.id, r.note, r.created_at,
                      c.name AS camera, f.name AS film
               FROM rolls r
               JOIN cameras c ON c.id = r.camera_id
               JOIN films   f ON f.id = r.film_id
               WHERE r.location_id = ? ORDER BY r.id DESC""",
            (loc["id"],))]
        d = dict(loc)
        d["rolls"] = rolls
        out.append(d)
    return out


def get_location(conn, location_id):
    return conn.execute("SELECT * FROM locations WHERE id=?",
                        (location_id,)).fetchone()


def add_location(conn, name, note="", lat=None, lon=None):
    cur = conn.execute(
        "INSERT INTO locations(name, note, lat, lon, created_at) "
        "VALUES (?,?,?,?,?)", (name, note, lat, lon, now()))
    conn.commit()
    return dict(conn.execute("SELECT * FROM locations WHERE id=?",
                             (cur.lastrowid,)).fetchone())


def find_location_by_name(conn, name):
    return conn.execute("SELECT * FROM locations WHERE name = ? COLLATE NOCASE",
                        (name,)).fetchone()


def get_or_create_location(conn, name, lat=None, lon=None):
    """Match an existing location by name (case-insensitive), else create."""
    row = find_location_by_name(conn, name)
    if row is not None:
        return dict(row)
    return add_location(conn, name, "", lat, lon)


# ---------------------------------------------------------------- rolls

def list_rolls(conn):
    """Rolls newest-first with camera/film/location names (location under it)."""
    return [dict(r) for r in conn.execute(
        """SELECT r.id, r.note, r.created_at, r.location_id,
                  c.name AS camera, f.name AS film, l.name AS location
           FROM rolls r
           JOIN cameras   c ON c.id = r.camera_id
           JOIN films     f ON f.id = r.film_id
           JOIN locations l ON l.id = r.location_id
           ORDER BY r.id DESC""")]


def add_roll(conn, camera_id, film_id, location_id, note=""):
    cur = conn.execute(
        "INSERT INTO rolls(camera_id, film_id, location_id, note, created_at) "
        "VALUES (?,?,?,?,?)", (camera_id, film_id, location_id, note, now()))
    conn.commit()
    return dict(conn.execute("SELECT * FROM rolls WHERE id=?",
                             (cur.lastrowid,)).fetchone())


def current_roll(conn):
    """The most recent roll with its camera/film names, or None.

    Used by the New Location popover to show (read-only) the current
    camera and roll.
    """
    row = conn.execute(
        """SELECT r.id, r.created_at, c.name AS camera, f.name AS film
           FROM rolls r
           JOIN cameras c ON c.id = r.camera_id
           JOIN films   f ON f.id = r.film_id
           ORDER BY r.id DESC LIMIT 1""").fetchone()
    return dict(row) if row else None
