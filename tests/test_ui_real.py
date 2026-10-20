"""Real-browser UI tests (Playwright + headless Chromium).

Boots the actual app against a throwaway database and drives a real
browser: computed styles, element geometry, touch gestures, geolocation,
console errors. Screenshots land in tests/screenshots/ for eyeballing.

Run explicitly:  .venv/bin/python -m pytest -m ui
Auto-skips when playwright/chromium is not installed.
"""
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.ui

try:
    from playwright.sync_api import sync_playwright
    HAVE_PW = True
except ImportError:  # pragma: no cover
    HAVE_PW = False

pytestmark = [pytest.mark.ui,
              pytest.mark.skipif(not HAVE_PW, reason="playwright not installed")]

ROOT = Path(__file__).resolve().parents[1]
SHOTS = Path(__file__).resolve().parent / "screenshots"
PORT = 8961
BASE = f"http://127.0.0.1:{PORT}"
DESKTOP = {"width": 1280, "height": 800}
MOBILE = {"width": 390, "height": 844}

DARK_BG = "rgb(20, 19, 18)"
LIGHT_BG = "rgb(244, 242, 238)"


def _free_port_ok():
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", PORT)) != 0


@pytest.fixture()
def server(tmp_path):
    assert _free_port_ok(), f"port {PORT} already in use; stop it before -m ui"
    SHOTS.mkdir(exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "run.py", "--db", str(tmp_path / "ui.sqlite"),
         "--host", "127.0.0.1", "--port", str(PORT), "--config",
         str(tmp_path / "none.yaml")],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    import urllib.request
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{BASE}/api/settings", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("server did not start: " +
                    proc.stdout.read().decode()[-2000:])
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def playwright_instance():
    with sync_playwright() as p:
        yield p


@pytest.fixture()
def browser(playwright_instance):
    b = playwright_instance.chromium.launch()
    yield b
    b.close()


def open_page(browser, viewport=DESKTOP, shot_tag="", **ctx_kwargs):
    ctx = browser.new_context(viewport=viewport, **ctx_kwargs)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" else None)
    page.goto(BASE)
    page.wait_for_selector("#bottombar:visible")
    page.errors = errors
    page.shot_tag = shot_tag
    return page


def shot(page, name):
    page.screenshot(path=str(SHOTS / f"{name}.png"))


def api_put_theme(page, theme):
    page.request.put(f"{BASE}/api/settings", data={"theme": theme},
                     headers={"Content-Type": "application/json"})


# ------------------------------------------------------------------ shell

def test_shell_and_no_console_errors(browser, server):
    page = open_page(browser, shot_tag="desktop")
    assert page.title() == "filmNotes"
    assert page.is_visible("#bottombar")
    assert page.is_visible("#new-roll-btn")
    assert page.is_visible("#new-location-btn")
    assert page.is_visible("#settings-btn")
    assert page.is_visible("#menu-btn")
    # bottom bar pinned to the viewport bottom
    bar = page.locator("#bottombar").bounding_box()
    assert abs(bar["y"] + bar["height"] - 800) < 1
    shot(page, "desktop-rolls-empty")
    assert page.errors == []
    page.context.close()


def test_no_horizontal_overflow_mobile(browser, server):
    page = open_page(browser, viewport=MOBILE)
    w = page.evaluate("[document.documentElement.scrollWidth,"
                      "document.documentElement.clientWidth]")
    assert w[0] <= w[1], f"horizontal overflow on mobile: {w}"
    assert page.errors == []
    page.context.close()


def test_bottombar_persists_across_pages(browser, server):
    page = open_page(browser, viewport=MOBILE)
    for page_name in ("cameras", "film", "locations", "rolls"):
        page.evaluate(f"location.hash = '#/{page_name}'")
        assert page.is_visible("#bottombar"), f"bar missing on {page_name}"
    assert page.errors == []
    page.context.close()


# ------------------------------------------------------------------ drawer

def test_drawer_navigation(browser, server):
    page = open_page(browser)
    page.click("#menu-btn")
    page.wait_for_selector("#drawer.open")
    assert page.is_visible("#veil")
    shot(page, "desktop-drawer")
    goto_page(page, "cameras")
    assert page.locator("#view .card").count() == 6
    assert "Leica MP" in page.inner_text("#view")
    goto_page(page, "film")
    assert page.locator("#view .card").count() == 15
    assert "Kodak T-Max 3200" in page.inner_text("#view")
    assert page.errors == []
    page.context.close()


def test_swipe_from_left_edge_opens_drawer(browser, server):
    page = open_page(browser, viewport=MOBILE,
                     has_touch=True, is_mobile=True)
    page.evaluate("""() => {
      const mk = (x, y) => new Touch({identifier: 1, target: document.body,
                                      clientX: x, clientY: y});
      const a = mk(5, 400);
      document.dispatchEvent(new TouchEvent('touchstart',
        {touches: [a], changedTouches: [a], bubbles: true}));
      const b = mk(140, 405);
      document.dispatchEvent(new TouchEvent('touchend',
        {touches: [], changedTouches: [b], bubbles: true}));
    }""")
    page.wait_for_selector("#drawer.open")
    assert page.errors == []
    page.context.close()


# ------------------------------------------------------------------ settings

def test_settings_modal_hides_bottombar_and_forces_dark(browser, server):
    page = open_page(browser)
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == LIGHT_BG
    page.click("#settings-btn")
    page.wait_for_selector("#settings-modal:visible")
    assert not page.is_visible("#bottombar"), "bar must hide for settings"
    shot(page, "desktop-settings")
    page.click("#theme-dark")
    page.wait_for_selector('html[data-theme="dark"]')
    page.wait_for_function(
        "getComputedStyle(document.body).backgroundColor === 'rgb(20, 19, 18)'")
    shot(page, "desktop-dark-settings")
    page.click("#settings-close")
    page.wait_for_selector("#settings-modal", state="hidden")
    assert page.is_visible("#bottombar")
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == DARK_BG
    # persisted server side: a fresh load is still dark
    page2 = open_page(browser)
    assert page2.get_attribute("html", "data-theme") == "dark"
    assert page2.errors == [] and page.errors == []
    page.context.close(); page2.context.close()


def test_auto_theme_follows_system(browser, server):
    page = open_page(browser)
    api_put_theme(page, "auto")
    page.emulate_media(color_scheme="dark")
    page.reload()
    page.wait_for_selector('html:not([data-theme])')
    page.wait_for_function(
        "getComputedStyle(document.body).backgroundColor === 'rgb(20, 19, 18)'")
    page.emulate_media(color_scheme="light")
    page.reload()
    page.wait_for_function(
        "getComputedStyle(document.body).backgroundColor === 'rgb(244, 242, 238)'")
    assert page.errors == []
    page.context.close()


# ------------------------------------------------------------------ new roll

def goto_page(page, name):
    if "open" not in (page.get_attribute("#drawer", "class") or ""):
        page.click("#menu-btn")
    page.click(f'[data-page="{name}"]')
    page.wait_for_selector(f"h1.page-title:has-text('{name.capitalize()}')")


def create_roll(page, camera, film, location, note="", shot=None):
    page.click("#new-roll-btn")
    page.wait_for_selector("#roll-modal:visible")
    page.select_option("#roll-camera", label=camera)
    page.select_option("#roll-film", label=film)
    page.fill("#roll-location", location)
    if shot:
        page.fill("#roll-shot", shot)
    if note:
        page.fill("#roll-note", note)
    page.click("#roll-save")
    page.wait_for_selector("#roll-modal", state="hidden")


def test_new_roll_flow_and_mru_sorting(browser, server):
    page = open_page(browser, viewport=MOBILE)
    page.click("#new-roll-btn")
    page.wait_for_selector("#roll-modal:visible")
    assert page.locator("#roll-camera option").count() == 6
    assert page.locator("#roll-film option").count() == 15
    # untouched alphabetical order: Bronica first
    assert page.locator("#roll-camera option").first.inner_text() == "Bronica SQ-A"
    shot(page, "mobile-new-roll")
    page.click("#roll-cancel")
    page.wait_for_selector("#roll-modal", state="hidden")

    create_roll(page, "Pentax 67", "Ilford HP5 400", "Mori Point", "evening fog")
    page.wait_for_selector("text=Roll #1")
    body = page.inner_text("#view")
    assert "Pentax 67" in body and "Ilford HP5 400" in body
    assert "Mori Point" in body and "evening fog" in body
    shot(page, "mobile-roll-card")

    # MRU: Pentax 67 / HP5 now lead their dropdowns
    page.click("#new-roll-btn")
    page.wait_for_selector("#roll-modal:visible")
    assert page.locator("#roll-camera option").first.inner_text() == "Pentax 67"
    assert page.locator("#roll-film option").first.inner_text() == "Ilford HP5 400"
    page.click("#roll-cancel")

    # second roll, same location -> still one location card
    create_roll(page, "Leica MP", "Kodak Portra 400", "mori point")
    goto_page(page, "locations")
    mori = page.locator(".card", has_text="Mori Point")
    assert mori.count() == 1
    assert "2 rolls" in mori.inner_text()
    shot(page, "mobile-locations-grouped")

    # rolls page groups locations under each roll
    goto_page(page, "rolls")
    assert "Roll #2" in page.inner_text(".card")
    assert page.errors == []
    page.context.close()


def test_roll_modal_keeps_bottombar_visible(browser, server):
    """Spec: the bar hides ONLY for settings, not for the roll popover."""
    page = open_page(browser, viewport=MOBILE)
    page.click("#new-roll-btn")
    page.wait_for_selector("#roll-modal:visible")
    assert page.is_visible("#bottombar")
    page.context.close()


def test_shot_date_defaults_to_now_and_can_be_overridden(browser, server):
    import re
    page = open_page(browser, viewport=MOBILE)
    page.click("#new-roll-btn")
    page.wait_for_selector("#roll-modal:visible")
    # prefilled with the current local date/time
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",
                        page.input_value("#roll-shot"))
    page.click("#roll-cancel")
    page.wait_for_selector("#roll-modal", state="hidden")

    create_roll(page, "Leica MP", "Kodak Portra 400", "Old Walk",
                shot="2020-01-01T10:00")
    create_roll(page, "Leica M6", "Ilford HP5 400", "Dune Flats",
                shot="2024-06-01T09:00")
    cards = page.locator("#view .card")
    assert cards.count() == 2
    # newest SHOT first, regardless of creation order
    assert "2024-06-01 09:00" in cards.nth(0).inner_text()
    assert "2020-01-01 10:00" in cards.nth(1).inner_text()
    shot(page, "mobile-shot-dates")

    # the location page shows the visit date too
    goto_page(page, "locations")
    assert "visited 2024-06-01 09:00" in page.inner_text("#view")
    assert page.errors == []
    page.context.close()


def test_new_location_visit_date_override(browser, server):
    page = open_page(browser, viewport=MOBILE)
    page.click("#new-location-btn")
    page.wait_for_selector("#loc-modal:visible")
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",
                        page.input_value("#loc-shot"))
    page.fill("#loc-name", "Quiet Pier")
    page.fill("#loc-shot", "2019-03-03T08:30")
    page.click("#loc-save")
    page.wait_for_selector("#loc-modal", state="hidden")
    page.wait_for_selector("text=Quiet Pier")
    assert "visited 2019-03-03 08:30" in page.inner_text("#view")
    assert page.errors == []
    page.context.close()


def test_location_detect_via_geolocation(browser, server):
    page = open_page(
        browser, viewport=MOBILE,
        permissions=["geolocation"],
        geolocation={"latitude": 37.7749, "longitude": -122.4194})
    page.route("**nominatim.openstreetmap.org**",
               lambda r: r.fulfill(status=200, content_type="application/json",
                                   body='{"address": {"city": "San Francisco",'
                                        ' "state": "California"}}'))
    page.click("#new-roll-btn")
    page.wait_for_selector("#roll-modal:visible")
    page.click("#roll-detect")
    page.wait_for_function(
        "document.getElementById('roll-location').value === "
        "'San Francisco, California'", timeout=8000)
    # and it saves with coordinates
    page.select_option("#roll-camera", index=0)
    page.select_option("#roll-film", index=0)
    page.click("#roll-save")
    page.wait_for_selector("#roll-modal", state="hidden")
    import urllib.request, json
    locs = json.load(urllib.request.urlopen(f"{BASE}/api/locations"))
    sf = [l for l in locs if l["name"] == "San Francisco, California"]
    assert sf and abs(sf[0]["lat"] - 37.7749) < 1e-6
    assert page.errors == []
    page.context.close()


def test_location_detect_failure_falls_back_to_coords(browser, server):
    page = open_page(
        browser, viewport=MOBILE,
        permissions=["geolocation"],
        geolocation={"latitude": 37.8, "longitude": -122.4})
    page.route("**nominatim.openstreetmap.org**", lambda r: r.abort())
    page.click("#new-roll-btn")
    page.wait_for_selector("#roll-modal:visible")
    page.click("#roll-detect")
    page.wait_for_function(
        "document.getElementById('roll-location').value.length > 0", timeout=8000)
    assert "37.8" in page.input_value("#roll-location")
    page.context.close()


# ------------------------------------------------------------------ new location

def test_new_location_shows_readonly_current_roll(browser, server):
    page = open_page(browser, viewport=MOBILE)
    create_roll(page, "Bronica SQ-A", "Fujifilm Provia 100", "Yosemite")
    page.click("#new-location-btn")
    page.wait_for_selector("#loc-modal:visible")
    cur = page.inner_text("#loc-current")
    assert "Bronica SQ-A" in cur and "Roll" in cur or "roll" in cur
    assert "Fujifilm Provia 100" in cur
    shot(page, "mobile-new-location")
    page.fill("#loc-name", "Secret Cove")
    page.fill("#loc-note", "low tide only")
    page.click("#loc-save")
    page.wait_for_selector("#loc-modal", state="hidden")
    page.wait_for_selector("text=Secret Cove")
    body = page.inner_text("#view")
    assert "Secret Cove" in body
    # attached to the current roll: it shows 1 roll, with the entry note
    assert "1 roll" in body and "low tide only" in body
    assert "Roll #1" in body
    assert page.errors == []
    page.context.close()


def test_user_scenario_roll_accumulates_locations(browser, server):
    """Regression for the reported confusion: a location added via New
    Location belongs to the current roll (not a 0-roll island), and a
    second roll prefilled with that location lists under it too."""
    page = open_page(browser, viewport=MOBILE)
    create_roll(page, "Pentax 67", "Ilford HP5 400",
                "Ken Willhans Conservation Area", shot="2026-01-01T10:16")
    # add a second location to the SAME roll
    page.click("#new-location-btn")
    page.wait_for_selector("#loc-modal:visible")
    page.fill("#loc-name", "Belfountain Conservation Area")
    page.fill("#loc-note", "last 2 frames")
    page.click("#loc-save")
    page.wait_for_selector("#loc-modal", state="hidden")
    page.wait_for_selector("text=Belfountain Conservation Area")
    loc_body = page.inner_text("#view")
    assert "1 roll" in loc_body and "last 2 frames" in loc_body
    # the roll card lists BOTH locations under it
    goto_page(page, "rolls")
    roll_card = page.locator("#view .card").first.inner_text()
    assert "Ken Willhans" in roll_card and "Belfountain" in roll_card
    assert "last 2 frames" in roll_card
    # new roll prefills the most recent location (user wants this)
    page.click("#new-roll-btn")
    page.wait_for_selector("#roll-modal:visible")
    assert page.input_value("#roll-location") == \
        "Belfountain Conservation Area"
    page.select_option("#roll-camera", label="Leica MP")
    page.select_option("#roll-film", label="Kodak Portra 400")
    page.click("#roll-save")
    page.wait_for_selector("#roll-modal", state="hidden")
    # Belfountain now lists BOTH rolls, newest visit first
    goto_page(page, "locations")
    belf = page.locator(".card", has_text="Belfountain").first
    assert "2 rolls" in belf.inner_text()
    assert "Roll #2" in belf.inner_text() and "Roll #1" in belf.inner_text()
    shot(page, "mobile-roll-accumulates")
    assert page.errors == []
    page.context.close()


def test_new_location_without_rolls(browser, server):
    page = open_page(browser, viewport=MOBILE)
    page.click("#new-location-btn")
    page.wait_for_selector("#loc-modal:visible")
    assert "No rolls yet" in page.inner_text("#loc-current")
    page.context.close()


# ------------------------------------------------------------------ cameras/film pages

def test_add_camera_and_film_pages(browser, server):
    page = open_page(browser)
    page.evaluate("location.hash = '#/cameras'")
    page.fill("#new-camera", "Contax T2")
    page.click("#add-camera")
    page.wait_for_selector("text=Contax T2")
    page.evaluate("location.hash = '#/film'")
    page.fill("#new-film", "Cinestill 800T")
    page.click("#add-film")
    page.wait_for_selector("text=Cinestill 800T")
    assert page.errors == []
    page.context.close()
