/* BusTrain service worker — network-first everywhere so updates land
   immediately; cache is the offline fallback only. */
const SHELL = "bt-shell-v29";
const SHELL_FILES = ["./", "index.html", "app.css?v=29", "app.js?v=29", "trips.js?v=29",
  "guide.js?v=29", "vendor/leaflet/leaflet.js", "vendor/leaflet/leaflet.css",
  "manifest.webmanifest", "icon.svg", "icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL && k !== "bt-data").map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return; // map tiles etc: browser default
  e.respondWith(
    fetch(e.request).then((r) => {
      const copy = r.clone();
      const bucket = url.pathname.includes("/data/") ? "bt-data" : SHELL;
      caches.open(bucket).then((c) => c.put(e.request, copy));
      return r;
    }).catch(() => caches.match(e.request))
  );
});
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data.json(); } catch { /* no payload */ }
  e.waitUntil(self.registration.showNotification(d.title || "BusTrain", {
    body: d.body || "", icon: "icon-192.png", badge: "icon-192.png",
    tag: d.tag || "bt-push", requireInteraction: true, vibrate: [200, 100, 200] }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: "window" }).then((cs) =>
    cs.length ? cs[0].focus() : self.clients.openWindow("./")));
});
