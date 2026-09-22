/* Steam 实时游戏榜单 —— 前端逻辑：tab 切换 + 60s 自动刷新 */

const API = {
  "top-sellers": "/api/top-sellers",
  "most-played": "/api/most-played",
  "specials": "/api/specials",
};

const state = {
  active: "top-sellers",
  data: {},      // tab -> items
  fetchedAt: {}, // tab -> Date.now()
  loading: {},   // tab -> bool
  nextRefresh: 60,
};

const $ = (sel) => document.querySelector(sel);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmt(n) {
  return n == null ? "—" : Number(n).toLocaleString("en-US");
}

/* ---------- 渲染 ---------- */

function priceRowHtml(p) {
  if (!p || !p.final) return '<span class="price-plain">—</span>';
  if (p.pct) {
    return `<span class="strike">${esc(p.original)}</span>` +
      `<span class="price-tag"><span class="pct">${p.pct}%</span>` +
      `<span class="final">${esc(p.final)}</span></span>`;
  }
  if (p.free) return '<span class="price-plain">免费开玩</span>';
  return `<span class="price-plain">${esc(p.final)}</span>`;
}

function cardHtml(it) {
  return `<a class="card" href="${esc(it.url)}" target="_blank" rel="noopener">
    <span class="rank-chip">#${it.rank}</span>
    <img src="${esc(it.image)}" alt="${esc(it.name)}" loading="lazy"
         onerror="this.style.visibility='hidden'">
    <span class="name">${esc(it.name)}</span>
    <span class="price-row">${priceRowHtml(it.price)}</span>
  </a>`;
}

function deltaHtml(it) {
  if (it.is_new) return '<span class="delta new">新上榜</span>';
  const d = it.delta;
  if (d == null) return '<span class="delta same">—</span>';
  if (d > 0) return `<span class="delta up">▲${d}</span>`;
  if (d < 0) return `<span class="delta down">▼${-d}</span>`;
  return '<span class="delta same">—</span>';
}

function rowHtml(it) {
  const genres = it.genres && it.genres.length ? esc(it.genres.join(" / ")) : "";
  let mini = "";
  const p = it.price;
  if (p && p.final) {
    if (p.pct) mini = `<span class="mini-price has-pct">${p.pct}% ${esc(p.final)}</span>`;
    else if (p.free) mini = '<span class="free">免费开玩</span>';
    else mini = `<span class="mini-price">${esc(p.final)}</span>`;
  }
  const sub = [genres, mini].filter(Boolean).join("");
  return `<a class="row" href="${esc(it.url)}" target="_blank" rel="noopener">
    <span class="rank">#${it.rank}</span>
    <img src="${esc(it.image)}" alt="${esc(it.name)}" loading="lazy"
         onerror="this.style.visibility='hidden'">
    <span class="gcol">
      <span class="gname">${esc(it.name)}</span>
      ${sub ? `<span class="genre-line">${sub}</span>` : ""}
    </span>
    <span class="pnum">${fmt(it.players)}</span>
    <span class="peak-col peak-num">${fmt(it.peak)}</span>
    <span class="delta-col">${deltaHtml(it)}</span>
  </a>`;
}

function skeletonHtml(tab) {
  if (tab === "most-played") {
    return Array(12).fill(
      '<div class="skel-row"><div class="skel"></div><div class="skel s-img"></div>' +
      '<div class="skel"></div><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>'
    ).join("");
  }
  return Array(10).fill(
    '<div class="skel-card"><div class="s-img"></div><div class="s-line"></div><div class="s-line" style="width:60%"></div></div>'
  ).join("");
}

function render(tab) {
  const items = state.data[tab];
  const listEl = $(`#list-${tab}`);
  if (!items) {
    listEl.innerHTML = skeletonHtml(tab);
    return;
  }
  listEl.innerHTML = tab === "most-played"
    ? items.map(rowHtml).join("")
    : items.map(cardHtml).join("");
}

function updateMeta(data) {
  if (!data || !data.meta) return;
  const t = new Date(data.meta.updated_at * 1000);
  $("#updated-at").textContent = `更新于 ${t.toLocaleTimeString("zh-CN", { hour12: false })}`;
  state.nextRefresh = data.meta.ttl || 60;
}

/* ---------- 数据加载 ---------- */

async function load(tab, { silent = false } = {}) {
  if (state.loading[tab]) return;
  state.loading[tab] = true;
  if (!silent) $(`#list-${tab}`).innerHTML = skeletonHtml(tab);
  $("#live-dot").style.background = "var(--link)";
  try {
    const res = await fetch(API[tab]);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.data[tab] = data.items;
    state.fetchedAt[tab] = Date.now();
    updateMeta(data);
    $("#error-banner").hidden = true;
    if (tab === state.active) render(tab);
  } catch (e) {
    if (tab === state.active) {
      $("#error-text").textContent = `数据加载失败（${e.message}），Steam 接口可能暂时不可用。`;
      $("#error-banner").hidden = false;
      if (!state.data[tab]) $(`#list-${tab}`).innerHTML = "";
    }
  } finally {
    state.loading[tab] = false;
    $("#live-dot").style.background = "var(--up)";
  }
}

function isStale(tab) {
  return !state.fetchedAt[tab] || Date.now() - state.fetchedAt[tab] > 60_000;
}

function switchTab(name) {
  if (state.active === name) return;
  state.active = name;
  document.querySelectorAll(".tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === name)
  );
  document.querySelectorAll(".panel").forEach((p) =>
    (p.hidden = p.id !== `panel-${name}`)
  );
  render(name);
  if (isStale(name)) load(name);
}

/* ---------- 定时刷新 ---------- */

setInterval(() => {
  state.nextRefresh -= 1;
  if (state.nextRefresh <= 0) {
    state.nextRefresh = 60;
    load(state.active, { silent: true });
  }
  $("#countdown").textContent = `${state.nextRefresh}s 后自动刷新`;
}, 1000);

$("#tabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (btn) switchTab(btn.dataset.tab);
});

$("#refresh-btn").addEventListener("click", () => {
  state.nextRefresh = 60;
  load(state.active, { silent: true });
});

$("#retry-btn").addEventListener("click", () => load(state.active));

switchTab("top-sellers");
load("top-sellers");
