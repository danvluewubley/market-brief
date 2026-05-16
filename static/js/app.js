// ── State ────────────────────────────────────────────────────────────────────
let portfolio = [];
let delivery = {};

// ── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  await loadPortfolio();
  await loadDelivery();
  setupNav();
  setupKeyboard();
  updateMarketStatus();
}

// ── Navigation ────────────────────────────────────────────────────────────────
function setupNav() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;

      document
        .querySelectorAll(".nav-item")
        .forEach((b) => b.classList.remove("active"));
      document
        .querySelectorAll(".tab")
        .forEach((t) => t.classList.remove("active"));

      btn.classList.add("active");
      document.getElementById("tab-" + tab).classList.add("active");
    });
  });
}

function setupKeyboard() {
  ["t-in", "s-in", "cb-in"].forEach((id) => {
    document.getElementById(id)?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") addPosition();
    });
  });

  const tin = document.getElementById("t-in");
  if (tin) {
    tin.addEventListener("input", (e) => {
      e.target.value = e.target.value.toUpperCase();
    });
  }
}

// ── Portfolio API ─────────────────────────────────────────────────────────────
async function loadPortfolio() {
  try {
    const r = await fetch("/api/portfolio");
    portfolio = await r.json();
    renderPortfolio();
  } catch (e) {
    console.error("load portfolio:", e);
  }
}

async function persistPortfolio() {
  try {
    await fetch("/api/portfolio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(portfolio),
    });
  } catch (e) {
    console.error("save portfolio:", e);
  }
}

// ── Add / Remove ──────────────────────────────────────────────────────────────
function addPosition() {
  const t = document.getElementById("t-in").value.trim().toUpperCase();
  const s = parseFloat(document.getElementById("s-in").value);
  const cb = parseFloat(document.getElementById("cb-in").value);
  const type = document.getElementById("type-in").value;
  const errEl = document.getElementById("port-err");

  if (!t) {
    errEl.textContent = "Enter a ticker symbol.";
    return;
  }

  if (portfolio.find((p) => p.ticker === t)) {
    errEl.textContent = `${t} is already in your portfolio.`;
    return;
  }

  errEl.textContent = "";

  portfolio.push({
    ticker: t,
    shares: isNaN(s) ? null : s,
    costBasis: isNaN(cb) ? null : cb,
    type,
    price: null,
    change: null,
    changePct: null,
    name: "",
  });

  persistPortfolio();
  renderPortfolio();

  document.getElementById("t-in").value = "";
  document.getElementById("s-in").value = "";
  document.getElementById("cb-in").value = "";
  document.getElementById("t-in").focus();

  fetchPricesFor([t]);
}

function removePosition(ticker) {
  portfolio = portfolio.filter((p) => p.ticker !== ticker);
  persistPortfolio();
  renderPortfolio();
}

// ── Prices ────────────────────────────────────────────────────────────────────
async function fetchPricesFor(tickers) {
  if (!tickers.length) return;

  try {
    const r = await fetch("/api/prices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tickers }),
    });

    const prices = await r.json();
    if (!Array.isArray(prices)) return;

    for (const p of prices) {
      const pos = portfolio.find((x) => x.ticker === p.ticker);
      if (pos) {
        pos.price = p.price;
        pos.change = p.change;
        pos.changePct = p.changePct;
        pos.name = p.name || "";
      }
    }

    persistPortfolio();
    renderPortfolio();
  } catch (e) {
    console.error("price fetch:", e);
  }
}

async function refreshPrices() {
  const btn = document.getElementById("refresh-btn");
  btn.classList.add("spinning");

  const tickers = portfolio.map((p) => p.ticker);
  await fetchPricesFor(tickers);

  btn.classList.remove("spinning");
}

// ── Render ────────────────────────────────────────────────────────────────────
function fmt$(val) {
  if (val === null || val === undefined) return "—";
  return "$" + val.toFixed(2);
}

function fmtChange(change, pct) {
  if (change === null || change === undefined) {
    return {
      html: '<span class="chg fl">—</span>',
      cls: "fl",
    };
  }

  const sign = change >= 0 ? "+" : "";
  const cls = change > 0 ? "up" : change < 0 ? "dn" : "fl";

  return {
    html: `<span class="chg ${cls}">${sign}${change.toFixed(2)} (${sign}${(pct || 0).toFixed(2)}%)</span>`,
    cls,
  };
}

function renderPortfolio() {
  const held = portfolio.filter((p) => p.type === "hold");
  const watched = portfolio.filter((p) => p.type === "watch");

  renderList(held, "held-list");
  renderList(watched, "watch-list");

  document.getElementById("m-held").textContent = held.length;
  document.getElementById("m-watch").textContent = watched.length;

  let totalVal = 0;
  let totalPL = 0;
  let hasVal = false;

  for (const p of held) {
    if (p.shares && p.price) {
      totalVal += p.shares * p.price;
      hasVal = true;
    }
    if (p.shares && p.change) {
      totalPL += p.shares * p.change;
    }
  }

  const valEl = document.getElementById("m-val");
  valEl.textContent = hasVal
    ? "$" + Math.round(totalVal).toLocaleString()
    : "—";

  const plEl = document.getElementById("m-pl");

  if (hasVal) {
    const sign = totalPL >= 0 ? "+" : "-";
    plEl.textContent = sign + "$" + Math.abs(totalPL).toFixed(2);
    plEl.className =
      "metric-val " + (totalPL > 0 ? "up" : totalPL < 0 ? "dn" : "");
  } else {
    plEl.textContent = "—";
    plEl.className = "metric-val";
  }
}

function renderList(list, containerId) {
  const el = document.getElementById(containerId);

  if (!list.length) {
    el.innerHTML = '<p class="empty-state">None added yet.</p>';
    return;
  }

  el.innerHTML = list
    .map((p) => {
      const chg = fmtChange(p.change, p.changePct);

      const priceHtml =
        p.price !== null
          ? `<div class="price-col"><div class="price">${fmt$(p.price)}</div>${chg.html}</div>`
          : `<div class="price-col"><span class="chg fl">—</span></div>`;

      const infoText = [
        p.shares !== null ? p.shares + " sh" : null,
        p.costBasis !== null ? "cb $" + p.costBasis.toFixed(2) : null,
      ]
        .filter(Boolean)
        .join(" · ");

      return `
      <div class="stock-tag">
        <span class="tkr">${p.ticker}</span>
        <span class="info">${infoText}</span>
        ${priceHtml}
        <button class="rm-btn" onclick="removePosition('${p.ticker}')">×</button>
      </div>
    `;
    })
    .join("");
}

// ── Brief generation ──────────────────────────────────────────────────────────
async function generateBrief() {
  if (!portfolio.length) {
    document.getElementById("brief-out").innerHTML =
      '<p class="error-msg">Add at least one holding or watchlist item first.</p>';
    return;
  }

  const btn = document.getElementById("gen-btn");
  btn.disabled = true;

  const out = document.getElementById("brief-out");
  const mode = document.querySelector('input[name="mode"]:checked').value;

  out.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <span>Generating brief…</span>
    </div>
  `;

  try {
    const r = await fetch("/api/brief", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ portfolio, mode }),
    });

    const brief = await r.json();
    if (brief.error) throw new Error(brief.error);

    out.innerHTML = renderBrief(brief);
  } catch (e) {
    out.innerHTML = `<p class="error-msg">Error: ${e.message}</p>`;
  }

  btn.disabled = false;
}

// ── Delivery (FIXED EMAIL ONLY) ──────────────────────────────────────────────
async function loadDelivery() {
  try {
    const r = await fetch("/api/delivery");
    delivery = await r.json();
    applyDeliveryUI();
  } catch (e) {
    console.error("load delivery:", e);
  }
}

function applyDeliveryUI() {
  const safe = (id, val) => {
    const el = document.getElementById(id);
    if (el && val) el.value = val;
  };

  safe("email-in", delivery.email);
  safe("email-time", delivery.emailTime);
  safe("email-tz", delivery.emailTz);
}

async function saveDelivery() {
  delivery = {
    email: document.getElementById("email-in").value.trim(),
    emailTime: document.getElementById("email-time").value,
    emailTz: document.getElementById("email-tz").value,
  };

  try {
    await fetch("/api/delivery", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(delivery),
    });

    document.getElementById("email-status").textContent = delivery.email
      ? "✓ Saved"
      : "Cleared";
  } catch (e) {
    document.getElementById("email-status").textContent = "Error saving";
    console.error(e);
  }
}

async function testDelivery() {
  const btn = document.getElementById("test-btn");
  const status = document.getElementById("test-status");

  btn.disabled = true;
  status.textContent = "Sending…";

  try {
    const r = await fetch("/api/delivery/test", { method: "POST" });
    const data = await r.json();
    status.textContent = data.message || "✓ Test sent";
  } catch (e) {
    status.textContent = "Error: " + e.message;
  }

  btn.disabled = false;
}

// ── Market status ─────────────────────────────────────────────────────────────
function updateMarketStatus() {
  const now = new Date();
  const et = new Date(
    now.toLocaleString("en-US", { timeZone: "America/New_York" }),
  );
  const day = et.getDay();
  const mins = et.getHours() * 60 + et.getMinutes();

  const dot = document.querySelector(".status-dot");
  const txt = document.querySelector(".status-text");

  const isWeekday = day >= 1 && day <= 5;
  const isOpen = isWeekday && mins >= 570 && mins < 960;

  if (isOpen) {
    dot.classList.add("open");
    dot.classList.remove("closed");
    txt.textContent = "Market open";
  } else {
    dot.classList.remove("open");
    dot.classList.add("closed");
    txt.textContent = isWeekday ? "Market closed" : "Weekend";
  }
}

// ── Render Brief ──────────────────────────────────────────────────────────────
function renderBrief(brief) {
  const overview = brief.market_overview || {};
  const stocks = brief.stocks || [];

  const held = stocks.filter(s => s.type === "hold");
  const watched = stocks.filter(s => s.type === "watch");

  function sentimentBadge(s) {
    const cls = s === "bullish" ? "up" : s === "bearish" ? "dn" : "fl";
    return `<span class="chg ${cls}">${s}</span>`;
  }

  function stockRows(list) {
    if (!list.length) return "<p class='empty-state'>None.</p>";
    return list.map(s => `
      <div class="stock-tag">
        <span class="tkr">${s.ticker}</span>
        <span class="info">${s.update}</span>
        ${sentimentBadge(s.sentiment)}
      </div>
    `).join("");
  }

  return `
    <div class="brief-wrap">
      <div class="brief-section">
        <div class="section-label">Market Overview</div>
        <p>${overview.summary || "—"}</p>
        <p>Sentiment: ${sentimentBadge(overview.sentiment)}</p>
        <p class="brief-note">${overview.key_events || ""}</p>
      </div>

      ${held.length ? `
      <div class="brief-section">
        <div class="section-label">Holdings</div>
        ${stockRows(held)}
      </div>` : ""}

      ${watched.length ? `
      <div class="brief-section">
        <div class="section-label">Watchlist</div>
        ${stockRows(watched)}
      </div>` : ""}
    </div>
  `;
}

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", init);
