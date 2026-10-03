/* Hotel Grand Garden HMS service worker */
const CACHE = "hms-shell-v1";
const SHELL = ["/", "/static/css/admin.css"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});
self.addEventListener("fetch", (e) => {
  // network-first for API; cache-fallback for static
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  }
});
self.addEventListener("push", (e) => {
  let data = { title: "Hotel Grand", body: "New update", url: "/", tag: "hms" };
  try {
    if (e.data) data = Object.assign(data, e.data.json());
  } catch (err) {}
  e.waitUntil(
    self.registration.showNotification(data.title || "Hotel Grand", {
      body: data.body || "",
      icon: data.icon || "/static/img/icon-192.png",
      badge: data.badge || "/static/img/icon-192.png",
      tag: data.tag || "hms",
      data: { url: data.url || "/" },
      vibrate: [120, 60, 120],
    })
  );
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if (c.url.includes(self.location.origin) && "focus" in c) {
          c.navigate(target);
          return c.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(target);
    })
  );
});
