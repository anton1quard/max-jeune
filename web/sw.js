// Service worker : app utilisable hors ligne et mises à jour propres.
//  - fichiers de l'application : cache versionné (BUILD change à chaque
//    déploiement de code -> l'utilisateur reçoit « Nouvelle version »)
//  - données (data/) : réseau d'abord, cache en secours (hors ligne)
const BUILD = "__BUILD__";
const APP_CACHE = `app-${BUILD}`;
const DATA_CACHE = "data-v1";
const APP_FILES = ["./", "index.html", "style.css", "app.js", "engine.js", "manifest.webmanifest",
  "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png"];

self.addEventListener("install", (ev) => {
  ev.waitUntil(caches.open(APP_CACHE).then((c) => c.addAll(APP_FILES)));
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil((async () => {
    for (const k of await caches.keys()) {
      if (k.startsWith("app-") && k !== APP_CACHE) await caches.delete(k);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("message", (ev) => {
  if (ev.data === "skipWaiting") self.skipWaiting();
});

self.addEventListener("fetch", (ev) => {
  const url = new URL(ev.request.url);
  if (ev.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.includes("/data/")) {
    ev.respondWith((async () => {
      const cache = await caches.open(DATA_CACHE);
      try {
        const res = await fetch(ev.request, { cache: "no-cache" });
        if (res.ok) cache.put(ev.request, res.clone());
        return res;
      } catch (e) {
        const hit = await cache.match(ev.request);
        if (hit) return hit;
        throw e;
      }
    })());
    return;
  }
  ev.respondWith(caches.match(ev.request, { ignoreSearch: true }).then((hit) => hit || fetch(ev.request)));
});
