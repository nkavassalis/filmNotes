"""API contract + input hygiene. /api/* errors are JSON, never HTML."""
import json


def get_json(resp):
    assert resp.headers["Content-Type"].startswith("application/json"), \
        f"expected JSON, got {resp.headers['Content-Type']}"
    return resp.get_json()


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "filmNotes" in html
    assert 'data-theme=""' in html          # default theme is auto
    assert "/static/manifest.webmanifest" in html


def test_index_reflects_saved_theme(client):
    client.put("/api/settings", json={"theme": "dark"})
    assert 'data-theme="dark"' in client.get("/").data.decode()


def test_seeded_lists(client):
    cams = get_json(client.get("/api/cameras"))
    films = get_json(client.get("/api/films"))
    assert len(cams) == 6 and len(films) == 15
    assert all("used_count" in c and "last_used" in c for c in cams)


def test_settings_roundtrip(client):
    assert get_json(client.get("/api/settings"))["theme"] == "auto"
    assert get_json(client.put("/api/settings", json={"theme": "light"}))["theme"] == "light"
    resp = client.put("/api/settings", json={"theme": "neon"})
    assert resp.status_code == 400
    assert "theme" in get_json(resp)["error"]


def test_settings_rejects_garbage(client):
    for bad in (None, "[]", 5, [1, 2]):
        resp = client.put("/api/settings", json=bad)
        assert resp.status_code == 400, f"body {bad!r} should 400"
    resp = client.put("/api/settings", json={"unknown": "x"})
    assert resp.status_code == 400


def test_new_roll_flow(client):
    cam = get_json(client.get("/api/cameras"))[0]
    film = get_json(client.get("/api/films"))[0]
    resp = client.post("/api/rolls", json={
        "camera_id": cam["id"], "film_id": film["id"],
        "location_name": "Big Sur", "note": "golden hour"})
    assert resp.status_code == 201
    roll = get_json(resp)
    assert roll["location"] == "Big Sur"
    rolls = get_json(client.get("/api/rolls"))
    assert rolls[0]["id"] == roll["id"]
    assert rolls[0]["camera"] == cam["name"]
    # the location was created implicitly and appears on the Locations page
    locs = get_json(client.get("/api/locations"))
    assert locs[0]["name"] == "Big Sur"
    assert locs[0]["rolls"][0]["id"] == roll["id"]


def test_new_roll_reuses_existing_location(client):
    body = {"camera_id": 1, "film_id": 1, "location_name": "Dublin Beach"}
    client.post("/api/rolls", json=body)
    client.post("/api/rolls", json={**body, "location_name": "dublin beach"})
    locs = get_json(client.get("/api/locations"))
    assert len([l for l in locs if l["name"].lower() == "dublin beach"]) == 1


def test_new_roll_validations(client):
    r = client.post("/api/rolls", json={"camera_id": 1, "film_id": 1})
    assert r.status_code == 400                       # no location
    r = client.post("/api/rolls", json={"camera_id": 999, "film_id": 1,
                                        "location_name": "x"})
    assert r.status_code == 400 and "camera" in get_json(r)["error"]
    r = client.post("/api/rolls", json={"camera_id": 1, "film_id": 999,
                                        "location_name": "x"})
    assert r.status_code == 400 and "film" in get_json(r)["error"]
    r = client.post("/api/rolls", json={"camera_id": "1", "film_id": 1,
                                        "location_name": "x"})
    assert r.status_code == 400
    r = client.post("/api/rolls", json={"camera_id": 1, "film_id": 1,
                                        "location_id": 12345})
    assert r.status_code == 400 and "location" in get_json(r)["error"]
    r = client.post("/api/rolls", json={"camera_id": 1, "film_id": 1,
                                        "location_name": "  "})
    assert r.status_code == 400


def test_new_roll_by_location_id(client):
    loc = get_json(client.post("/api/locations", json={"name": "Stinson Beach"}))
    r = client.post("/api/rolls", json={"camera_id": 2, "film_id": 3,
                                        "location_id": loc["id"]})
    assert r.status_code == 201
    assert get_json(r)["location"] == "Stinson Beach"


def test_new_location(client):
    r = client.post("/api/locations", json={"name": "Mori Point",
                                            "note": "low tide only",
                                            "lat": 37.56, "lon": -122.51})
    assert r.status_code == 201
    loc = get_json(r)
    assert loc["note"] == "low tide only" and loc["lat"] == 37.56
    r = client.post("/api/locations", json={"name": ""})
    assert r.status_code == 400
    r = client.post("/api/locations", json={"name": "x", "lat": 37.5})
    assert r.status_code == 400          # lat without lon
    r = client.post("/api/locations", json={"name": "x", "lat": 999, "lon": 0})
    assert r.status_code == 400          # out of range


def test_current_roll_endpoint(client):
    assert get_json(client.get("/api/locations/current"))["current"] is None
    client.post("/api/rolls", json={"camera_id": 1, "film_id": 1,
                                    "location_name": "place"})
    cur = get_json(client.get("/api/locations/current"))["current"]
    assert cur["id"] == 1 and cur["camera"] and cur["film"]


def test_add_camera_and_film(client):
    r = client.post("/api/cameras", json={"name": "Contax T2"})
    assert r.status_code == 201
    assert get_json(r)["name"] == "Contax T2"
    assert any(c["name"] == "Contax T2" for c in get_json(client.get("/api/cameras")))
    r = client.post("/api/films", json={"name": "Cinestill 800T"})
    assert r.status_code == 201
    r = client.post("/api/cameras", json={"name": ""})
    assert r.status_code == 400
    r = client.post("/api/films", json={"name": 123})
    assert r.status_code == 400


def test_oversized_fields_rejected(client):
    r = client.post("/api/locations", json={"name": "x" * 500})
    assert r.status_code == 400
    r = client.post("/api/rolls", json={"camera_id": 1, "film_id": 1,
                                        "location_name": "ok",
                                        "note": "n" * 6000})
    assert r.status_code == 400


def test_malformed_json_bodies(client):
    r = client.post("/api/rolls", data="not json",
                    content_type="application/json")
    assert r.status_code == 400
    assert "error" in get_json(r)


def test_api_404_is_json(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert "error" in get_json(r)


# ------------------------------------------------------- shot / visit dates

def test_roll_shot_at_roundtrip_and_normalisation(client):
    r = client.post("/api/rolls", json={"camera_id": 1, "film_id": 1,
                                        "location_name": "x",
                                        "shot_at": "2024-05-01T18:30"})
    assert r.status_code == 201
    assert get_json(r)["shot_at"] == "2024-05-01 18:30"
    rolls = get_json(client.get("/api/rolls"))
    assert rolls[0]["shot_at"] == "2024-05-01 18:30"


def test_roll_shot_at_defaults_to_now(client):
    import re
    client.post("/api/rolls", json={"camera_id": 1, "film_id": 1,
                                    "location_name": "x"})
    shot = get_json(client.get("/api/rolls"))[0]["shot_at"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", shot)


def test_roll_shot_at_invalid_rejected(client):
    for bad in ("2024-13-45 10:00", "yesterday", "2024-05-01T25:00",
                "2024-05-01", 12345):
        r = client.post("/api/rolls", json={"camera_id": 1, "film_id": 1,
                                            "location_name": "x",
                                            "shot_at": bad})
        assert r.status_code == 400, f"shot_at {bad!r} should 400"


def test_rolls_api_sorted_by_shot_at(client):
    base = {"camera_id": 1, "film_id": 1, "location_name": "x"}
    client.post("/api/rolls", json={**base, "shot_at": "2020-01-01 10:00"})
    client.post("/api/rolls", json={**base, "shot_at": "2024-06-01 09:00"})
    client.post("/api/rolls", json={**base, "shot_at": "2022-03-03 08:00"})
    shots = [r["shot_at"] for r in get_json(client.get("/api/rolls"))]
    assert shots == ["2024-06-01 09:00", "2022-03-03 08:00",
                     "2020-01-01 10:00"]


def test_location_visited_at_roundtrip_and_sorting(client):
    r = client.post("/api/locations", json={"name": "Old",
                                            "visited_at": "2019-01-01 12:00"})
    assert get_json(r)["visited_at"] == "2019-01-01 12:00"
    client.post("/api/locations", json={"name": "New",
                                        "visited_at": "2024-01-01 12:00"})
    names = [l["name"] for l in get_json(client.get("/api/locations"))]
    assert names == ["New", "Old"]
    r = client.post("/api/locations", json={"name": "bad",
                                            "visited_at": "nope"})
    assert r.status_code == 400


def test_roll_refreshes_location_visit_date(client):
    loc = get_json(client.post("/api/locations", json={
        "name": "Inlet", "visited_at": "2019-01-01 12:00"}))
    client.post("/api/rolls", json={"camera_id": 1, "film_id": 1,
                                    "location_id": loc["id"],
                                    "shot_at": "2025-07-07 07:07"})
    locs = get_json(client.get("/api/locations"))
    assert locs[0]["name"] == "Inlet"
    assert locs[0]["visited_at"] == "2025-07-07 07:07"


def test_roll_creating_location_borrows_its_shot_at(client):
    client.post("/api/rolls", json={"camera_id": 1, "film_id": 1,
                                    "location_name": "Fresh Inlet",
                                    "shot_at": "2021-08-08 08:08"})
    locs = {l["name"]: l for l in get_json(client.get("/api/locations"))}
    assert locs["Fresh Inlet"]["visited_at"] == "2021-08-08 08:08"
