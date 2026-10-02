(function () {
  const toggle = document.getElementById("menuToggle");
  const sidebar = document.getElementById("sidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", () => sidebar.classList.toggle("open"));
  }

  // Heartbeat for live sessions
  setInterval(() => {
    fetch("/api/heartbeat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "",
      },
    }).catch(() => {});
  }, 60000);

  // New order sound/poll for kitchen & orders pages
  const badge = document.getElementById("newOrdersBadge");
  if (badge) {
    let last = parseInt(badge.dataset.count || "0", 10);
    setInterval(() => {
      fetch("/api/orders/new-count")
        .then((r) => r.json())
        .then((d) => {
          badge.textContent = d.count;
          if (d.count > last) {
            try {
              const ctx = new (window.AudioContext || window.webkitAudioContext)();
              const o = ctx.createOscillator();
              const g = ctx.createGain();
              o.connect(g);
              g.connect(ctx.destination);
              o.frequency.value = 880;
              g.gain.value = 0.08;
              o.start();
              setTimeout(() => o.stop(), 200);
            } catch (e) {}
          }
          last = d.count;
        })
        .catch(() => {});
    }, 15000);
  }
})();
