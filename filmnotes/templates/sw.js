/* filmNotes service worker — the offline story (2026-10-21: app must open
 * in the backcountry with zero signal).
 *
 * Rendered by Flask with the asset CONTENT HASH baked into CACHE + the
 * precache URLs, so any deploy changes this file byte-for-byte and iOS
 * re-registers it (the /sw.js route itself is served no-store).
 *
 * Strategies:
 *   navigation  -> serve cached shell instantly, revalidate in background
 *   /api/* GET  -> network-first; cache is the offline fallback only
 *   statics     -> cache-first
 *   anything else (POST/PUT/DELETE, cross-origin) -> untouched; the page's
 *   write queue (app.js) owns offline writes and replays with X-Client-Id.
 */
const V = "{{ app_version }}";
const CACHE = "filmnotes-" + V;
const SHELL = [
  "/",
  "/static/manifest.webmanifest",
  "/static/favicon.svg",
  "/static/apple-touch-icon.png",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/style.css?v={{ app_version }}",
  "/static/app.js?v={{ app_version }}",
];

self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    // best-effort: one missing icon must not abort the whole install
    await Promise.allSettled(SHELL.map((u) => c.add(u)));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys())
      if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;  // writes hit the network; queue handles offline
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;  // nominatim etc pass through
  if (url.pathname === "/sw.js") return;

  // API: NETWORK-FIRST — online must always be fresh (read-your-writes;
  // stale-while-revalidate here made refreshData show pre-write data and
  // the browser suite caught it). The cache is the OFFLINE fallback only.
  if (url.pathname.startsWith("/api/")) {
    e.respondWith((async () => {
      const c = await caches.open(CACHE);
      try {
        const r = await fetch(req);
        if (r.ok) c.put(req, r.clone());
        return r;
      } catch (err) {
        const cached = await c.match(req);
        return cached || Response.error();
      }
    })());
    return;
  }

  // shell + statics: stale-while-revalidate (content-hashed, safe to serve
  // one open stale while the new SW installs)
  e.respondWith((async () => {
    const c = await caches.open(CACHE);
    const key = req.mode === "navigate" ? "/" : req;
    const cached = await c.match(key);
    const bg = fetch(req).then((r) => {
      if (r.ok) c.put(key, r.clone());
      return r;
    }).catch(() => null);
    if (cached) { e.waitUntil(bg); return cached; }
    const net = await bg;
    return net || Response.error();
  })());
});
