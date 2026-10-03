(function () {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
  var meta = document.querySelector('meta[name="vapid-public-key"]');
  var pub = meta ? meta.content : "";
  function urlBase64ToUint8Array(base64String) {
    var padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    var base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(base64);
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; ++i) out[i] = raw.charCodeAt(i);
    return out;
  }
  function csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : "";
  }
  navigator.serviceWorker.register("/static/sw.js").then(function (reg) {
    if (!pub) return;
    function subscribe() {
      return reg.pushManager.getSubscription().then(function (sub) {
        if (sub) return sub;
        return reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(pub),
        });
      }).then(function (sub) {
        var j = sub.toJSON();
        return fetch("/api/push/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          body: JSON.stringify({
            endpoint: j.endpoint,
            keys: j.keys,
            role: (document.body && document.body.dataset.role) || "",
          }),
        });
      });
    }
    if (Notification.permission === "granted") {
      subscribe().catch(function () {});
    } else if (Notification.permission !== "denied") {
      // soft prompt banner
      var bar = document.createElement("div");
      bar.id = "push-prompt";
      bar.style.cssText = "position:fixed;bottom:1rem;left:1rem;right:1rem;max-width:420px;margin:auto;background:#0f172a;color:#fff;padding:1rem 1.25rem;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.35);z-index:9999;display:flex;gap:.75rem;align-items:center;flex-wrap:wrap";
      bar.innerHTML = '<div style="flex:1;font-size:.95rem">Allow <strong>Hotel Grand</strong> notifications?</div>';
      var yes = document.createElement("button");
      yes.textContent = "Allow";
      yes.style.cssText = "background:#22c55e;border:0;color:#fff;padding:.5rem 1rem;border-radius:8px;font-weight:600;cursor:pointer";
      var no = document.createElement("button");
      no.textContent = "Not now";
      no.style.cssText = "background:transparent;border:1px solid #64748b;color:#e2e8f0;padding:.5rem .75rem;border-radius:8px;cursor:pointer";
      yes.onclick = function () {
        Notification.requestPermission().then(function (p) {
          bar.remove();
          if (p === "granted") subscribe().catch(function () {});
        });
      };
      no.onclick = function () { bar.remove(); };
      bar.appendChild(yes);
      bar.appendChild(no);
      document.body.appendChild(bar);
    }
  }).catch(function () {});
})();
