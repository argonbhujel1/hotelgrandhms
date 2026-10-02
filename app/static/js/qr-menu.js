(function () {
  const token = document.body.dataset.token;
  const cart = {};
  let items = {};

  document.querySelectorAll(".menu-card").forEach((card) => {
    const id = card.dataset.id;
    items[id] = {
      id: id,
      name: card.dataset.name,
      price: parseFloat(card.dataset.price),
    };
  });

  function updateUI() {
    let totalQty = 0;
    let totalAmt = 0;
    Object.values(cart).forEach((c) => {
      totalQty += c.qty;
      totalAmt += c.qty * c.price;
    });
    const bar = document.getElementById("cartBar");
    const qtyEl = document.getElementById("cartQty");
    const amtEl = document.getElementById("cartAmt");
    if (totalQty > 0) {
      bar.classList.add("visible");
      qtyEl.textContent = totalQty;
      amtEl.textContent = totalAmt.toFixed(2);
    } else {
      bar.classList.remove("visible");
    }
    document.querySelectorAll(".menu-card").forEach((card) => {
      const id = card.dataset.id;
      const span = card.querySelector(".qty-val");
      if (span) span.textContent = cart[id] ? cart[id].qty : 0;
    });
  }

  window.qtyChange = function (id, delta) {
    if (!cart[id]) {
      if (delta < 0) return;
      cart[id] = { id: id, name: items[id].name, price: items[id].price, qty: 0 };
    }
    cart[id].qty += delta;
    if (cart[id].qty <= 0) delete cart[id];
    updateUI();
  };

  window.filterCat = function (catId, btn) {
    document.querySelectorAll(".cat-tabs button").forEach((b) => b.classList.remove("active"));
    if (btn) btn.classList.add("active");
    document.querySelectorAll(".menu-card").forEach((card) => {
      if (!catId || catId === "all" || card.dataset.cat === String(catId)) {
        card.style.display = "";
      } else {
        card.style.display = "none";
      }
    });
  };

  window.searchMenu = function (q) {
    q = (q || "").toLowerCase();
    document.querySelectorAll(".menu-card").forEach((card) => {
      const name = (card.dataset.name || "").toLowerCase();
      card.style.display = !q || name.includes(q) ? "" : "none";
    });
  };

  window.openCart = function () {
    const list = document.getElementById("cartList");
    list.innerHTML = "";
    let total = 0;
    Object.values(cart).forEach((c) => {
      total += c.qty * c.price;
      list.innerHTML += `<div class="cart-item"><div><div class="name">${c.name}</div><small>x${c.qty} · Rs. ${c.price}</small></div><strong>Rs. ${(c.qty * c.price).toFixed(2)}</strong></div>`;
    });
    document.getElementById("sheetTotal").textContent = total.toFixed(2);
    document.getElementById("sheetOverlay").classList.add("open");
    document.getElementById("bottomSheet").classList.add("open");
  };

  window.closeCart = function () {
    document.getElementById("sheetOverlay").classList.remove("open");
    document.getElementById("bottomSheet").classList.remove("open");
  };

  window.placeOrder = function () {
    const itemsPayload = Object.values(cart).map((c) => ({
      id: parseInt(c.id, 10),
      qty: c.qty,
    }));
    if (!itemsPayload.length) return;

    const btn = document.getElementById("placeBtn");
    btn.disabled = true;
    btn.textContent = "Placing...";

    const emailEl = document.getElementById("custEmail");
    const emailVal = emailEl ? (emailEl.value || "").trim() : "";
    // Prefer /qr/order path when page was opened that way
    const placeUrl = window.location.pathname.indexOf("/qr/order") === 0
      ? "/qr/order/" + token + "/place"
      : "/order/" + token + "/place";

    fetch(placeUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: itemsPayload,
        customer_name: document.getElementById("custName").value || null,
        customer_email: emailVal || null,
        special_instructions: document.getElementById("specialNotes").value || null,
      }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) {
          document.getElementById("bottomSheet").innerHTML = `
            <div class="success-box">
              <div style="font-size:3rem">✓</div>
              <h3>Order Placed!</h3>
              <div class="num">${d.order_number}</div>
              <p>Total: Rs. ${d.total}</p>
              <p style="color:#777;margin-top:1rem;font-size:.9rem">Kitchen has received your order.</p>
            </div>`;
          Object.keys(cart).forEach((k) => delete cart[k]);
          updateUI();
        } else {
          alert(d.error || "Failed");
          btn.disabled = false;
          btn.textContent = "Place Order";
        }
      })
      .catch(() => {
        alert("Something went wrong. Please try again.");
        btn.disabled = false;
        btn.textContent = "Place Order";
      });
  };
})();
