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
