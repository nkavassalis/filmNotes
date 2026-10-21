/* filmNotes - one script, no build step, vanilla JS.
 *
 * Routing: hash routes (#/rolls #/locations #/cameras #/film), default rolls.
 * Data: everything from /api/*; caches refresh after every write.
 * Dropdowns: cameras/films sorted most-recently-used first (last_used desc,
 *   then used_count desc, then name) - the server supplies used_count and
 *   last_used on each row.
 * Location service: browser geolocation -> OSM Nominatim reverse geocode ->
 *   friendly name. Always editable (override write-in); on any failure the
 *   field just gets "lat, lon" and the user types their own name.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const state = { rolls: [], locations: [], cameras: [], films: [], lenses: [],
                theme: "auto", show_times: false, lastFix: null };
let edit = null;   // {kind: 'roll'|'loc'|'entry', ...} while an edit modal is open

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON */ }
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, 2600);
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtDT = (s) => {
  if (!s) return "";
  s = String(s).replace("T", " ");
  return state.show_times ? s : s.split(" ")[0];
};

/* Google Maps: coordinates when the backend has them, else a name query */
const mapUrl = (loc) =>
  (loc.lat != null && loc.lon != null)
    ? `https://www.google.com/maps/search/?api=1&query=${loc.lat},${loc.lon}`
    : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(loc.name)}`;

/* local wall-clock now for datetime-local inputs ('YYYY-MM-DDTHH:MM') */
function dtLocalNow() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
         `T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/* ------------------------------------------------------------- data */

async function refreshData() {
  const [rolls, locations, cameras, films, lenses] = await Promise.all([
    api("/api/rolls"), api("/api/locations"),
    api("/api/cameras"), api("/api/films"), api("/api/lenses"),
  ]);
  Object.assign(state, { rolls, locations, cameras, films, lenses });
}

/* most-recently-used first; never-used entries fall back to name order */
function mruSort(rows) {
  return [...rows].sort((a, b) => {
    const au = a.last_used || "", bu = b.last_used || "";
    if (au !== bu) return au < bu ? 1 : -1;
    if ((a.used_count || 0) !== (b.used_count || 0))
      return (b.used_count || 0) - (a.used_count || 0);
    return a.name.localeCompare(b.name);
  });
}

/* ------------------------------------------------------------- routing */

const PAGES = ["rolls", "locations", "cameras", "film"];

function currentPage() {
  const p = (location.hash || "#/rolls").replace(/^#\//, "");
  return PAGES.includes(p) ? p : "rolls";
}

function route() {
  const page = currentPage();
  document.querySelectorAll(".drawer-item").forEach((el) =>
    el.classList.toggle("active", el.dataset.page === page));
  closeDrawer();
  // cameras/film pages do not use the edit-mode paradigm (field pages
  // don't need it; gear edits live behind the ⓘ popovers instead)
  $("edit-mode-btn").hidden = (page === "cameras" || page === "film");
  const view = $("view");
  if (page === "rolls") renderRolls(view);
  else if (page === "locations") renderLocations(view);
  else if (page === "cameras") renderCameras(view);
  else renderFilm(view);
}

window.addEventListener("hashchange", route);

function renderRolls(view) {
  if (!state.rolls.length) {
    view.innerHTML = `<h1 class="page-title">Rolls</h1>
      <div class="empty">No rolls yet.<br>Tap <b>New Roll</b> below to log your first.</div>`;
    return;
  }
  view.innerHTML = `<h1 class="page-title">Rolls</h1>` + state.rolls.map((r) => `
    <article class="card">
      <button class="card-del" data-act="del-roll" data-id="${r.id}"
              data-no="${esc(r.roll_no)}" aria-label="Delete roll" title="Delete roll">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 7h12l-1 13H7L6 7z"/><path d="M9 7V4h6v3"/><path d="M10 11v5M14 11v5"/></svg>
      </button>
      <button class="card-edit" data-act="edit-roll" data-id="${r.id}"
              aria-label="Edit roll" title="Edit roll">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L20 8l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/></svg>
      </button>
      <h3>Roll #${esc(r.roll_no)} <span class="meta">· ${esc(fmtDT(r.shot_at))}</span></h3>
      <div class="chips">
        <span class="chip">${esc(r.camera)}</span>
        <span class="chip">${esc(r.film)}</span>
        ${r.lens ? `<span class="chip">${esc(r.lens)}</span>` : ""}
        <button class="add-loc" data-act="add-loc" data-id="${r.id}">+ location</button>
      </div>
      ${r.note ? `<p class="note">${esc(r.note)}</p>` : ""}
      ${(r.locations || []).length ? `<ul class="sublist">` + r.locations.map((l) => `
        <li class="entry-row">
          <button class="entry-edit" data-act="edit-entry" data-roll="${r.id}" data-loc="${l.id}"
                  aria-label="Edit location entry" title="Edit this location">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L20 8l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/></svg>
          </button>
          <b><a class="loc-link" href="${mapUrl(l)}" target="_blank" rel="noopener">&#128205; ${esc(l.name)}</a></b>
          <span class="meta">${esc(fmtDT(l.visited_at))}</span>
          ${l.note ? `<span class="meta">${esc(l.note)}</span>` : ""}</li>`).join("") + `</ul>` : ""}
    </article>`).join("");
}

function renderLocations(view) {
  if (!state.locations.length) {
    view.innerHTML = `<h1 class="page-title">Locations</h1>
      <div class="empty">No locations yet.<br>Tap <b>New Location</b> below to add one.</div>`;
    return;
  }
  view.innerHTML = `<h1 class="page-title">Locations</h1>` + state.locations.map((l) => `
    <article class="card">
      <button class="card-del" data-act="del-loc" data-id="${l.id}"
              data-name="${esc(l.name)}" aria-label="Delete location" title="Delete location">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 7h12l-1 13H7L6 7z"/><path d="M9 7V4h6v3"/><path d="M10 11v5M14 11v5"/></svg>
      </button>
      <button class="card-edit" data-act="edit-loc" data-id="${l.id}"
              aria-label="Edit location" title="Edit location">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L20 8l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/></svg>
      </button>
      <h3><a class="loc-link" href="${mapUrl(l)}" target="_blank" rel="noopener">&#128205; ${esc(l.name)}</a></h3>
      <div class="meta">${l.rolls.length} roll${l.rolls.length === 1 ? "" : "s"} · visited ${esc(fmtDT(l.visited_at))}</div>
      ${l.note ? `<p class="note">${esc(l.note)}</p>` : ""}
      ${l.rolls.length ? `<ul class="sublist">` + l.rolls.map((r) => `
        <li><b>Roll #${esc(r.roll_no)}</b> <span class="meta">${esc(fmtDT(r.visited_at))} · ${esc(r.camera)} · ${esc(r.film)}</span>
        ${r.note ? `<span class="meta">${esc(r.note)}</span>` : ""}</li>`).join("") + `</ul>` : ""}
    </article>`).join("");
}

let lensesOpen = false;   // expandable Lenses section on the cameras page

function renderCameras(view) {
  const lensCount = state.lenses.length;
  view.innerHTML = `<h1 class="page-title">Cameras</h1>
    <div class="add-row">
      <input id="new-camera" placeholder="Add a camera..." autocomplete="off">
      <button id="add-camera" class="btn primary">Add</button>
    </div>` +
    mruSort(state.cameras).map((c) => `
    <article class="card">
      <h3>${esc(c.name)}
        <button class="info-btn" data-act="info-camera" data-id="${c.id}"
                aria-label="Camera details" title="Details">i</button>
      </h3>
      <div class="meta">${c.used_count} roll${c.used_count === 1 ? "" : "s"}` +
        (c.last_used ? ` · last used ${esc(fmtDT(c.last_used))}` : "") + `</div>
    </article>`).join("") + `
    <button id="lenses-toggle" class="section-toggle" aria-expanded="${lensesOpen}">
      Lenses <span class="count">${lensCount}</span>
      <span class="chev"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></span>
    </button>` +
    (lensesOpen ? `
    <div class="add-row">
      <input id="new-lens" placeholder="Add a lens..." autocomplete="off">
      <button id="add-lens" class="btn primary">Add</button>
    </div>` +
    (lensCount ? mruSort(state.lenses).map((l) => `
    <article class="card">
      <h3>${esc(l.name)}
        <button class="info-btn" data-act="info-lens" data-id="${l.id}"
                aria-label="Lens details" title="Details">i</button>
      </h3>
      <div class="meta">${l.used_count} roll${l.used_count === 1 ? "" : "s"}` +
        (l.last_used ? ` · last used ${esc(fmtDT(l.last_used))}` : "") + `</div>
      <div class="meta">${lensCompatText(l)}</div>
    </article>`).join("")
     : `<div class="empty">No lenses yet.<br>Lenses are optional — add some to
        pick one when logging a roll.</div>`) : "");
  $("add-camera").addEventListener("click", async () => {
    const name = $("new-camera").value.trim();
    if (!name) return;
    try { await api("/api/cameras", { method: "POST", body: { name } });
          $("new-camera").value = ""; await refreshData(); route(); }
    catch (e) { toast(e.message); }
  });
  $("lenses-toggle").addEventListener("click", () => {
    lensesOpen = !lensesOpen;
    renderCameras($("view"));
  });
  const addLens = $("add-lens");
  if (addLens) addLens.addEventListener("click", async () => {
    const name = $("new-lens").value.trim();
    if (!name) return;
    try { await api("/api/lenses", { method: "POST", body: { name } });
          $("new-lens").value = ""; await refreshData(); route(); }
    catch (e) { toast(e.message); }
  });
}

function renderFilm(view) {
  view.innerHTML = `<h1 class="page-title">Film</h1>
    <div class="add-row">
      <input id="new-film" placeholder="Add a film..." autocomplete="off">
      <button id="add-film" class="btn primary">Add</button>
    </div>` +
    mruSort(state.films).map((f) => `
    <article class="card">
      <h3>${esc(f.name)}
        <button class="info-btn" data-act="info-film" data-id="${f.id}"
                aria-label="Film details" title="Details">i</button>
      </h3>
      <div class="meta">${f.used_count} roll${f.used_count === 1 ? "" : "s"}` +
        (f.last_used ? ` · last used ${esc(fmtDT(f.last_used))}` : "") + `</div>
      ${f.note ? `<p class="note">${esc(f.note)}</p>` : ""}
    </article>`).join("");
  $("add-film").addEventListener("click", async () => {
    const name = $("new-film").value.trim();
    if (!name) return;
    try { await api("/api/films", { method: "POST", body: { name } });
          $("new-film").value = ""; await refreshData(); route(); }
    catch (e) { toast(e.message); }
  });
}

/* ------------------------------------------------------------- drawer */

function openDrawer() {
  $("drawer").classList.add("open");
  $("veil").hidden = false;
}
function closeDrawer() {
  $("drawer").classList.remove("open");
  $("veil").hidden = true;
}

$("menu-btn").addEventListener("click", openDrawer);
$("veil").addEventListener("click", closeDrawer);
document.querySelectorAll(".drawer-item").forEach((el) =>
  el.addEventListener("click", () => { location.hash = "#/" + el.dataset.page; }));

/* swipe from the left edge exposes the drawer (native-app feel) */
let touchX = null, touchY = null, touchEdge = false;
document.addEventListener("touchstart", (e) => {
  const t = e.touches[0];
  touchX = t.clientX; touchY = t.clientY;
  touchEdge = t.clientX <= 26 && !document.querySelector(".modal:not([hidden])");
}, { passive: true });
document.addEventListener("touchend", (e) => {
  if (touchX === null) return;
  const t = e.changedTouches[0];
  const dx = t.clientX - touchX, dy = Math.abs(t.clientY - touchY);
  if (touchEdge && dx > 60 && dy < 50) openDrawer();
  touchX = null;
}, { passive: true });

/* ------------------------------------------------------------- modals */

function openModal(id) {
  $(id).hidden = false;
  if (id === "settings-modal") document.body.classList.add("settings-open");
}
function closeModal(id) {
  $(id).hidden = true;
  if (id === "settings-modal") document.body.classList.remove("settings-open");
}

/* New Roll (create or edit) */
function resetRollModal(mode) {
  edit = mode === "edit" ? edit : null;
  $("roll-title").textContent = mode === "edit" ? "Edit Roll" : "New Roll";
  $("roll-save").textContent = mode === "edit" ? "Save changes" : "Save roll";
  $("roll-loc-group").hidden = mode === "edit";
}

$("new-roll-btn").addEventListener("click", async () => {
  try { await refreshData(); } catch (e) { toast(e.message); return; }
  fillSelect($("roll-camera"), mruSort(state.cameras));
  fillSelect($("roll-film"), mruSort(state.films));
  applyLensDefault();
  fillDatalist();
  $("roll-note").value = "";
  $("roll-no").value = "";
  $("roll-shot").value = dtLocalNow();
  state.lastFix = null;
  if (!$("roll-location").value.trim()) suggestLocation();
  resetRollModal("new");
  openModal("roll-modal");
});

function openRollEdit(roll) {
  fillSelect($("roll-camera"), mruSort(state.cameras));
  fillSelect($("roll-film"), mruSort(state.films));
  $("roll-no").value = roll.roll_no || "";
  const cam = state.cameras.find((c) => c.name === roll.camera);
  const film = state.films.find((f) => f.name === roll.film);
  if (cam) $("roll-camera").value = String(cam.id);
  if (film) $("roll-film").value = String(film.id);
  fillLensSelect(Number($("roll-camera").value));
  $("roll-lens").value = roll.lens_id != null ? String(roll.lens_id) : "";
  $("roll-shot").value = (roll.shot_at || "").replace(" ", "T");
  $("roll-note").value = roll.note || "";
  edit = { kind: "roll", id: roll.id };
  resetRollModal("edit");
  openModal("roll-modal");
}

$("roll-cancel").addEventListener("click", () => closeModal("roll-modal"));
$("roll-save").addEventListener("click", async () => {
  try {
    if (edit && edit.kind === "roll") {
      const rollNo = $("roll-no").value.trim();
      if (!rollNo) { toast("Roll number is required when editing"); return; }
      await api(`/api/rolls/${edit.id}`, { method: "PUT", body: {
        roll_no: rollNo,
        camera_id: Number($("roll-camera").value),
        film_id: Number($("roll-film").value),
        lens_id: $("roll-lens").value ? Number($("roll-lens").value) : null,
        shot_at: $("roll-shot").value,
        note: $("roll-note").value.trim(),
      }});
      closeModal("roll-modal");
      await refreshData(); route(); toast("Roll updated");
      return;
    }
    const body = {
      camera_id: Number($("roll-camera").value),
      film_id: Number($("roll-film").value),
      location_name: $("roll-location").value.trim(),
      note: $("roll-note").value.trim(),
      shot_at: $("roll-shot").value,
    };
    const rn = $("roll-no").value.trim();
    if (rn) body.roll_no = rn;
    if ($("roll-lens").value) body.lens_id = Number($("roll-lens").value);
    if (!body.location_name) { toast("Location is required"); return; }
    if (state.lastFix) { body.lat = state.lastFix.lat; body.lon = state.lastFix.lon; }
    await api("/api/rolls", { method: "POST", body });
    closeModal("roll-modal");
    $("roll-location").value = "";
    state.lastFix = null;
    await refreshData();
    location.hash = "#/rolls";
    route();
    toast("Roll saved");
  } catch (e) { toast(e.message); }
});

/* Lens compatibility modal (camera toggle chips on the cameras page) */
let lensEditTarget = null;

function openLensEdit(lens) {
  lensEditTarget = lens;
  $("lens-modal-title").textContent = lens.name;
  $("lens-serial").value = lens.serial || "";
  $("lens-note").value = lens.note || "";
  $("lens-cam-list").innerHTML = mruSort(state.cameras).map((c) =>
    `<button class="chip-toggle" data-cam="${c.id}" ` +
    `aria-pressed="${(lens.camera_ids || []).includes(c.id)}">${esc(c.name)}</button>`
  ).join("");
  openModal("lens-modal");
}

$("lens-cam-list").addEventListener("click", (e) => {
  const b = e.target.closest(".chip-toggle");
  if (!b) return;
  b.setAttribute("aria-pressed",
    b.getAttribute("aria-pressed") === "true" ? "false" : "true");
});

$("lens-cancel").addEventListener("click", () => closeModal("lens-modal"));
$("lens-save").addEventListener("click", async () => {
  if (!lensEditTarget) return;
  const ids = [...document.querySelectorAll(
    "#lens-cam-list .chip-toggle[aria-pressed='true']")]
    .map((b) => Number(b.dataset.cam));
  try {
    await api(`/api/lenses/${lensEditTarget.id}`,
      { method: "PUT", body: {
          camera_ids: ids,
          serial: $("lens-serial").value.trim(),
          note: $("lens-note").value.trim() } });
    closeModal("lens-modal");
    await refreshData(); route(); toast("Compatibility saved");
  } catch (e) { toast(e.message); }
});

/* Camera inventory popover: serial + note (editable) and compatible
   lenses (read-only roll-up from the lens assignments). */
let camInfoTarget = null;

function openCameraInfo(cam) {
  camInfoTarget = cam;
  $("camera-info-title").textContent = cam.name;
  $("camera-serial").value = cam.serial || "";
  $("camera-note").value = cam.note || "";
  const fits = state.lenses.filter((l) => lensCompatible(l, cam.id));
  $("camera-lenses").innerHTML = fits.length
    ? fits.map((l) => `<li><b>${esc(l.name)}</b>` +
        (l.serial ? ` <span class="meta">· s/n ${esc(l.serial)}</span>` : "") +
        (l.note ? `<span class="meta">${esc(l.note)}</span>` : "") + "</li>").join("")
    : `<li class="meta">No lenses yet — add lenses from the Lenses section.</li>`;
  openModal("camera-info-modal");
}

$("camera-info-close").addEventListener("click", () => closeModal("camera-info-modal"));
$("camera-info-save").addEventListener("click", async () => {
  if (!camInfoTarget) return;
  try {
    await api(`/api/cameras/${camInfoTarget.id}`, { method: "PUT", body: {
      serial: $("camera-serial").value.trim(),
      note: $("camera-note").value.trim() } });
    closeModal("camera-info-modal");
    await refreshData(); route(); toast("Camera saved");
  } catch (e) { toast(e.message); }
});

/* Film inventory popover: note + guarded delete */
let filmInfoTarget = null;

function openFilmInfo(film) {
  filmInfoTarget = film;
  $("film-modal-title").textContent = film.name;
  $("film-note").value = film.note || "";
  openModal("film-modal");
}

$("film-cancel").addEventListener("click", () => closeModal("film-modal"));
$("film-save").addEventListener("click", async () => {
  if (!filmInfoTarget) return;
  try {
    await api(`/api/films/${filmInfoTarget.id}`, { method: "PUT", body: {
      note: $("film-note").value.trim() } });
    closeModal("film-modal");
    await refreshData(); route(); toast("Film saved");
  } catch (e) { toast(e.message); }
});

/* Guarded deletes: the server refuses (400) while rolls still reference
   the item; the toast surfaces that message verbatim. */
async function deleteGear(path, kind, name, closeId) {
  if (!confirm(`Delete ${kind} "${name}"? This cannot be undone.`)) return;
  try {
    await api(path, { method: "DELETE" });
    closeModal(closeId);
    await refreshData(); route(); toast(`${kind} deleted`);
  } catch (e) { toast(e.message); }
}

$("camera-info-delete").addEventListener("click", () => {
  if (camInfoTarget) deleteGear(`/api/cameras/${camInfoTarget.id}`,
    "camera", camInfoTarget.name, "camera-info-modal");
});
$("lens-delete").addEventListener("click", () => {
  if (lensEditTarget) deleteGear(`/api/lenses/${lensEditTarget.id}`,
    "lens", lensEditTarget.name, "lens-modal");
});
$("film-delete").addEventListener("click", () => {
  if (filmInfoTarget) deleteGear(`/api/films/${filmInfoTarget.id}`,
    "film", filmInfoTarget.name, "film-modal");
});

/* New Location (create or edit). openLocAdd targets the current roll
   (bottom bar) or an explicit roll ("+ location" on a roll card). */
function resetLocModal(mode) {
  edit = mode === "edit" ? edit : null;
  $("loc-title").textContent = mode === "edit" ? "Edit Location" : "New Location";
  $("loc-save").textContent = mode === "edit" ? "Save changes" : "Save location";
  $("loc-current").hidden = mode === "edit";
}

async function openLocAdd(rollId) {
  try {
    const [cur] = await Promise.all([api("/api/locations/current"), refreshData()]);
    fillDatalist();
    const target = rollId != null
      ? state.rolls.find((r) => r.id === rollId)
      : (cur.current ? { id: cur.current.id, roll_no: cur.current.roll_no,
                         camera: cur.current.camera, film: cur.current.film,
                         shot_at: cur.current.shot_at } : null);
    if (rollId != null && !target) return;
    $("loc-current").innerHTML = target
      ? (rollId != null
          ? `Adding to roll: <b>#${esc(target.roll_no)}</b> ` +
            `(${esc(target.camera)}, ${esc(target.film)})`
          : `Current camera: <b>${esc(target.camera)}</b> · Current roll: ` +
            `<b>#${esc(target.roll_no)}</b> (${esc(target.film)}, ${esc(fmtDT(target.shot_at))})`)
      : `No rolls yet — the current camera and roll will appear here.`;
    $("loc-name").value = "";
    $("loc-note").value = "";
    /* attaching to a roll? default the visit to its shot date */
    $("loc-shot").value = target ? target.shot_at.replace(" ", "T") : dtLocalNow();
    state.lastFix = null;
    resetLocModal("new");
    if (rollId != null) edit = { kind: "addloc", rollId };
    openModal("loc-modal");
  } catch (e) { toast(e.message); }
}

$("new-location-btn").addEventListener("click", () => openLocAdd(null));

function openLocEdit(loc) {
  $("loc-name").value = loc.name;
  $("loc-note").value = loc.note || "";
  $("loc-shot").value = (loc.visited_at || "").replace(" ", "T");
  edit = { kind: "loc", id: loc.id };
  resetLocModal("edit");
  openModal("loc-modal");
}

/* Edit one roll-at-place entry (place + note + visit date) */
function openEntryEdit(rollId, locId) {
  const roll = state.rolls.find((r) => r.id === rollId);
  const entry = roll && (roll.locations || []).find((l) => l.id === locId);
  if (!entry) return;
  $("entry-place").innerHTML = `Roll #${esc(roll.roll_no)} · <b>${esc(entry.name)}</b>`;
  fillDatalist();
  $("entry-location").value = entry.name;
  $("entry-shot").value = (entry.visited_at || roll.shot_at || "").replace(" ", "T");
  $("entry-note").value = entry.note || "";
  edit = { kind: "entry", rollId, locId, name: entry.name };
  openModal("entry-modal");
}

/* pencil + trash buttons (rendered dynamically; delegated via data-act) */
$("view").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const act = btn.dataset.act;
  if (act === "edit-roll") {
    const r = state.rolls.find((x) => x.id === Number(btn.dataset.id));
    if (r) openRollEdit(r);
  } else if (act === "edit-loc") {
    const l = state.locations.find((x) => x.id === Number(btn.dataset.id));
    if (l) openLocEdit(l);
  } else if (act === "edit-entry") {
    openEntryEdit(Number(btn.dataset.roll), Number(btn.dataset.loc));
  } else if (act === "info-lens") {
    const l = state.lenses.find((x) => x.id === Number(btn.dataset.id));
    if (l) openLensEdit(l);
  } else if (act === "info-camera") {
    const c = state.cameras.find((x) => x.id === Number(btn.dataset.id));
    if (c) openCameraInfo(c);
  } else if (act === "info-film") {
    const f = state.films.find((x) => x.id === Number(btn.dataset.id));
    if (f) openFilmInfo(f);
  } else if (act === "add-loc") {
    openLocAdd(Number(btn.dataset.id));
  } else if (act === "del-roll") {
    delRoll(Number(btn.dataset.id), btn.dataset.no);
  } else if (act === "del-loc") {
    delLoc(Number(btn.dataset.id), btn.dataset.name);
  }
});

/* Deletes live behind the global edit-mode toggle and confirm first. */
async function delRoll(id, no) {
  if (!confirm(`Delete Roll #${no}? This cannot be undone.`)) return;
  try {
    await api(`/api/rolls/${id}`, { method: "DELETE" });
    await refreshData(); route(); toast(`Roll #${no} deleted`);
  } catch (e) { toast(e.message); }
}

async function delLoc(id, name) {
  if (!confirm(`Delete location "${name}"? This cannot be undone.`)) return;
  try {
    await api(`/api/locations/${id}`, { method: "DELETE" });
    await refreshData(); route(); toast("Location deleted");
  } catch (e) { toast(e.message); }
}

$("loc-cancel").addEventListener("click", () => closeModal("loc-modal"));
$("loc-save").addEventListener("click", async () => {
  const body = {
    name: $("loc-name").value.trim(),
    note: $("loc-note").value.trim(),
    visited_at: $("loc-shot").value,
  };
  if (!body.name) { toast("Location is required"); return; }
  try {
    if (edit && edit.kind === "loc") {
      await api(`/api/locations/${edit.id}`, { method: "PUT", body });
      closeModal("loc-modal");
      await refreshData(); route(); toast("Location updated");
      return;
    }
    if (state.lastFix) { body.lat = state.lastFix.lat; body.lon = state.lastFix.lon; }
    if (edit && edit.kind === "addloc") body.roll_id = edit.rollId;
    const saved = await api("/api/locations", { method: "POST", body });
    closeModal("loc-modal");
    await refreshData();
    if (!(edit && edit.kind === "addloc")) { location.hash = "#/locations"; }
    route();
    toast(saved.attached_to_roll != null
      ? `Location added to Roll #${saved.attached_to_roll_no}` : "Location saved");
  } catch (e) { toast(e.message); }
});

$("entry-cancel").addEventListener("click", () => closeModal("entry-modal"));
$("entry-save").addEventListener("click", async () => {
  if (!edit || edit.kind !== "entry") return;
  const body = {
    note: $("entry-note").value.trim(),
    visited_at: $("entry-shot").value,
  };
  const place = $("entry-location").value.trim();
  if (!place) { toast("Location is required"); return; }
  if (place !== edit.name) body.location_name = place;
  try {
    await api(`/api/rolls/${edit.rollId}/locations/${edit.locId}`,
      { method: "PUT", body });
    closeModal("entry-modal");
    await refreshData(); route(); toast("Entry updated");
  } catch (e) { toast(e.message); }
});

/* Settings */
$("settings-btn").addEventListener("click", () => {
  syncThemeSeg();
  syncTimeSeg();
  openModal("settings-modal");
});
$("settings-close").addEventListener("click", () => closeModal("settings-modal"));
document.querySelectorAll("#theme-seg button").forEach((btn) =>
  btn.addEventListener("click", async () => {
    const theme = btn.id.replace("theme-", "");
    try {
      const s = await api("/api/settings", { method: "PUT", body: { theme } });
      applyTheme(s.theme);
      syncThemeSeg();
    } catch (e) { toast(e.message); }
  }));

document.querySelectorAll("#time-seg button").forEach((btn) =>
  btn.addEventListener("click", async () => {
    const show = btn.id === "time-show";
    try {
      const s = await api("/api/settings", { method: "PUT", body: { show_times: show } });
      state.show_times = s.show_times === "1";
      syncTimeSeg();
      route();   // re-render dates immediately
    } catch (e) { toast(e.message); }
  }));

function syncTimeSeg() {
  $("time-show").classList.toggle("active", state.show_times);
  $("time-hide").classList.toggle("active", !state.show_times);
}

function syncThemeSeg() {
  document.querySelectorAll("#theme-seg button").forEach((btn) =>
    btn.classList.toggle("active", btn.id === "theme-" + state.theme));
}

/* click the veil area of a modal (outside the card) to dismiss */
document.querySelectorAll(".modal").forEach((m) =>
  m.addEventListener("click", (e) => { if (e.target === m) closeModal(m.id); }));

/* edit mode: topbar pencil reveals the per-card edit pencils */
$("edit-mode-btn").addEventListener("click", () => {
  const on = document.body.classList.toggle("edit-mode");
  $("edit-mode-btn").classList.toggle("active", on);
  $("edit-mode-btn").setAttribute("aria-pressed", on ? "true" : "false");
});

/* Escape dismisses the topmost popover (and the drawer) */
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  for (const id of ["entry-modal", "roll-modal", "loc-modal", "lens-modal",
                    "camera-info-modal", "film-modal", "settings-modal"])
    if (!$(id).hidden) { closeModal(id); return; }
  closeDrawer();
});

/* ------------------------------------------------------------- theme */

function applyTheme(theme) {
  state.theme = theme;
  if (theme === "light" || theme === "dark")
    document.documentElement.setAttribute("data-theme", theme);
  else
    document.documentElement.removeAttribute("data-theme");
  const dark = theme === "dark" ||
    (theme === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? "#141312" : "#f4f2ee";
}
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
  if (state.theme === "auto") applyTheme("auto");
});

/* ------------------------------------------------------------- selects */

function fillSelect(sel, rows) {
  sel.innerHTML = rows.map((r) =>
    `<option value="${r.id}">${esc(r.name)}</option>`).join("");
}

/* Lenses are fully optional: the select carries a blank "None" option.
   A lens is offered only when compatible with the chosen camera:
   no camera_ids = compatible with ALL; otherwise only the assigned ones.
   Once a camera has roll history, its most recent compatible lens becomes
   the default whenever the camera selection changes (create mode only). */
function lensCompatible(l, cameraId) {
  return !l.camera_ids || !l.camera_ids.length || l.camera_ids.includes(cameraId);
}

function lensCompatText(l) {
  if (!l.camera_ids || !l.camera_ids.length) return "All cameras";
  const names = l.camera_ids.map((id) => {
    const c = state.cameras.find((x) => x.id === id);
    return c ? c.name : `#${id}`;
  });
  return `Fits: ${esc(names.join(", "))}`;
}

function fillLensSelect(cameraId) {
  const sel = $("roll-lens");
  const ok = mruSort(state.lenses.filter((l) => lensCompatible(l, cameraId)));
  sel.innerHTML = `<option value=""></option>` + ok.map((l) =>
    `<option value="${l.id}">${esc(l.name)}</option>`).join("");
}

function mostRecentLensFor(cameraId) {
  // state.rolls is newest-shot-first already
  const hit = state.rolls.find((r) => r.camera_id === cameraId && r.lens_id
    && lensCompatible(state.lenses.find((l) => l.id === r.lens_id) || {}, cameraId));
  return hit ? String(hit.lens_id) : "";
}

function applyLensDefault() {
  const camId = Number($("roll-camera").value);
  fillLensSelect(camId);
  $("roll-lens").value = mostRecentLensFor(camId);
}

$("roll-camera").addEventListener("change", () => {
  if (!edit || edit.kind !== "roll") applyLensDefault();
});
function fillDatalist() {
  $("location-list").innerHTML = state.locations.map((l) =>
    `<option value="${esc(l.name)}">`).join("");
}
function suggestLocation() {
  /* prefill the New Roll location with the most recent location used */
  if (state.locations.length) $("roll-location").value = state.locations[0].name;
}

/* ------------------------------------------------- location service */

async function detectLocation(input) {
  if (!navigator.geolocation) { toast("Geolocation unavailable"); return; }
  input.blur();
  let pos;
  try {
    pos = await new Promise((resolve, reject) =>
      navigator.geolocation.getCurrentPosition(resolve, reject,
        { enableHighAccuracy: true, timeout: 10000 }));
  } catch (e) {
    toast("Location unavailable — type it in");
    return;
  }
  const lat = pos.coords.latitude, lon = pos.coords.longitude;
  state.lastFix = { lat, lon };
  let name = `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
  try {
    const res = await fetch("https://nominatim.openstreetmap.org/reverse" +
      `?format=jsonv2&lat=${lat}&lon=${lon}&zoom=14`,
      { headers: { "Accept-Language": navigator.language || "en" } });
    if (res.ok) {
      const g = await res.json();
      const a = g.address || {};
      const place = a.city || a.town || a.village || a.suburb || a.hamlet ||
                    a.municipality || a.county;
      const region = a.state || a.region;
      if (place && region) name = `${place}, ${region}`;
      else if (place) name = place;
      else if (g.display_name) name = g.display_name.split(",").slice(0, 2).join(",").trim();
    }
  } catch (e) { /* keep coordinate fallback; override is always available */ }
  input.value = name;
}

$("roll-detect").addEventListener("click", () => detectLocation($("roll-location")));
$("loc-detect").addEventListener("click", () => detectLocation($("loc-name")));

/* ------------------------------------------------------------- boot */

(async function boot() {
  try {
    const s = await api("/api/settings");
    applyTheme(s.theme || "auto");
    state.show_times = s.show_times === "1";
  } catch (e) { applyTheme("auto"); }
  try {
    await refreshData();
  } catch (e) { toast("Could not reach the server"); }
  route();
})();
