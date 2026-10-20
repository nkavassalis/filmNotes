"""Hermetic DB tests: seeding, CRUD, MRU data, current roll, settings."""
from filmnotes import db


def test_seed_cameras(conn):
    names = [c["name"] for c in db.list_cameras(conn)]
    assert names == sorted(db.SEED_CAMERAS)
    assert set(db.SEED_CAMERAS) == {
        "Leica MP", "Leica M6", "Canon 1V", "Pentax 67", "Bronica SQ-A",
        "Pentax 645N2"}


def test_seed_films(conn):
    names = set(f["name"] for f in db.list_films(conn))
    assert names == {
        "Fujifilm Provia 100", "Fujifilm Velvia 50", "Fujifilm Velvia 100",
        "Kodak Portra 160", "Kodak Portra 400", "Kodak Portra 800",
        "Ilford Delta 100", "Ilford Delta 400", "Ilford XP2 400",
        "Ilford HP5 400", "Kodak Tri-X 400", "Kodak T-Max 100",
        "Kodak T-Max 400", "Kodak T-Max 3200", "Fujifilm Acros II"}


def test_seed_is_idempotent(conn):
    db.init_db(conn)  # second run must not duplicate or wipe
    assert len(db.list_cameras(conn)) == len(db.SEED_CAMERAS)
    assert len(db.list_films(conn)) == len(db.SEED_FILMS)


def test_default_settings(conn):
    assert db.get_settings(conn)["theme"] == "auto"


def test_set_settings(conn):
    s = db.set_settings(conn, {"theme": "dark"})
    assert s["theme"] == "dark"
    assert db.get_settings(conn)["theme"] == "dark"


def test_add_camera_dedupe(conn):
    a = db.add_camera(conn, "Hasselblad 500C/M")
    b = db.add_camera(conn, "Hasselblad 500C/M")
    assert a["id"] == b["id"]


def test_add_roll_and_listing(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Golden Gate Park")
    roll = db.add_roll(conn, cam, film, loc["id"], "f/8 sunny")
    rolls = db.list_rolls(conn)
    assert rolls[0]["id"] == roll["id"]
    assert rolls[0]["location"] == "Golden Gate Park"
    assert rolls[0]["note"] == "f/8 sunny"
    assert rolls[0]["camera"] and rolls[0]["film"]


def test_locations_page_groups_rolls(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    a = db.add_location(conn, "Battery Spencer")
    b = db.add_location(conn, "Point Reyes")
    db.add_roll(conn, cam, film, a["id"])
    db.add_roll(conn, cam, film, a["id"])
    db.add_roll(conn, cam, film, b["id"])
    locs = {l["name"]: l for l in db.list_locations(conn)}
    assert len(locs["Battery Spencer"]["rolls"]) == 2
    assert len(locs["Point Reyes"]["rolls"]) == 1
    r = locs["Battery Spencer"]["rolls"][0]
    assert r["camera"] and r["film"] and r["created_at"]


def test_mru_fields(conn):
    cams = {c["name"]: c for c in db.list_cameras(conn)}
    films = {f["name"]: f for f in db.list_films(conn)}
    loc = db.add_location(conn, "Home")
    db.add_roll(conn, cams["Leica MP"]["id"], films["Kodak Portra 400"]["id"],
                loc["id"])
    cams = {c["name"]: c for c in db.list_cameras(conn)}
    films = {f["name"]: f for f in db.list_films(conn)}
    assert cams["Leica MP"]["used_count"] == 1
    assert cams["Leica MP"]["last_used"] is not None
    assert cams["Leica M6"]["used_count"] == 0
    assert cams["Leica M6"]["last_used"] is None
    assert films["Kodak Portra 400"]["last_used"] is not None


def test_get_or_create_location_matches_case_insensitive(conn):
    a = db.get_or_create_location(conn, "Golden Gate Park")
    b = db.get_or_create_location(conn, "golden gate park", 37.7, -122.5)
    assert a["id"] == b["id"]
    assert b["lat"] is None  # existing match keeps original coords


def test_get_or_create_location_new_stores_coords(conn):
    loc = db.get_or_create_location(conn, "Presidio", 37.8, -122.4)
    assert loc["lat"] == 37.8 and loc["lon"] == -122.4


def test_current_roll_is_newest(conn):
    assert db.current_roll(conn) is None
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Yosemite")
    db.add_roll(conn, cam, film, loc["id"])
    cam2 = db.list_cameras(conn)[1]["id"]
    newer = db.add_roll(conn, cam2, film, loc["id"])
    cur = db.current_roll(conn)
    assert cur["id"] == newer["id"]
    assert cur["camera"] == "Canon 1V"  # list_cameras[1] is alphabetical
