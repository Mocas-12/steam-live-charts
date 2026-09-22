/* Steam 实时游戏榜单 —— 前端逻辑：tab 切换 + 60s 自动刷新 */

const API = {
  "top-sellers": "/api/top-sellers",
  "most-played": "/api/most-played",
  "free-to-keep": "/api/free-to-keep",
  "specials": "/api/specials",
  "new-releases": "/api/new-releases",
  "free-games": "/api/free-games",
};

const state = {
  active: "most-played",
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
  if (p.free) return '<span class="price-plain free">免费开玩</span>';
  return `<span class="price-plain">${esc(p.final)}</span>`;
}

function deltaHtml(it) {
  if (it.is_new) return '<span class="delta new">新上榜</span>';
  const d = it.delta;
  if (d == null) return '<span class="delta same">—</span>';
  if (d > 0) return `<span class="delta up">▲${d}</span>`;
  if (d < 0) return `<span class="delta down">▼${-d}</span>`;
  return '<span class="delta same">—</span>';
}

function rowHtml(it, stats) {
  if (!stats) {
    // 价格类榜单：# | 封面 | 游戏 | 价格
    return `<a class="row simple" href="${esc(it.url)}" target="_blank" rel="noopener">
      <span class="rank">${it.rank}</span>
      <img src="${esc(it.image)}" alt="${esc(it.name)}" loading="lazy"
           onerror="this.style.visibility='hidden'">
      <span class="gcol">
        <span class="gname">${esc(it.name)}</span>
      </span>
      <span class="price-col">${priceRowHtml(it.price)}</span>
    </a>`;
  }
  const genres = it.genres && it.genres.length ? esc(it.genres.join(" / ")) : "";
  return `<a class="row" href="${esc(it.url)}" target="_blank" rel="noopener">
    <span class="rank">${it.rank}</span>
    <img src="${esc(it.image)}" alt="${esc(it.name)}" loading="lazy"
         onerror="this.style.visibility='hidden'">
    <span class="gcol">
      <span class="gname">${esc(it.name)}</span>
      ${genres ? `<span class="genre-line">${genres}</span>` : ""}
    </span>
    <span class="pnum">${fmt(it.players)}</span>
    <span class="peak-col peak-num">${fmt(it.peak)}</span>
    <span class="delta-col">${deltaHtml(it)}</span>
    <span class="price-col">${priceRowHtml(it.price)}</span>
  </a>`;
}

function rowsHeadHtml(stats) {
  if (stats) {
    return ('<div class="rows-head"><span class="ctr">排名</span><span>游戏</span>'
      + '<span></span><span class="r">当前在线</span><span class="r">今日峰值</span>'
      + '<span class="ctr">周变化</span><span class="r">价格</span></div>');
  }
  return ('<div class="rows-head simple"><span class="ctr">排名</span><span>游戏</span>'
    + '<span></span><span class="r">价格</span></div>');
}

function skeletonHtml(tab) {
  void tab;
  return Array(12).fill(
    '<div class="skel-row"><div class="skel"></div><div class="skel s-img"></div>' +
    '<div class="skel"></div><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>'
  ).join("");
}

function emptyHtml() {
  return `<div class="empty">
    <div class="ghost">FREE</div>
    <div class="etitle">当前没有限时免费入库活动</div>
    <div class="esub">Steam 免费入库活动零星出现（周末较多），开启后游戏永久入库 · 60 秒后自动复查</div>
  </div>`;
}

function render(tab) {
  const items = state.data[tab];
  const listEl = $(`#list-${tab}`);
  if (!items) {
    listEl.innerHTML = skeletonHtml(tab);
    return;
  }
  if (!items.length) {
    listEl.innerHTML = emptyHtml();
    return;
  }
  const stats = tab === "most-played";
  listEl.innerHTML = rowsHeadHtml(stats) + items.map(it => rowHtml(it, stats)).join("");
}

function updateMeta(data) {
  if (!data || !data.meta) return;
  const t = new Date(data.meta.updated_at * 1000);
  $("#updated-at").textContent = `更新于 ${t.toLocaleTimeString("zh-CN", { hour12: false })}`;
  state.nextRefresh = data.meta.ttl || 60;
}

/* ---------- 数据加载 ---------- */

async function load(tab, { silent = false, force = false } = {}) {
  if (state.loading[tab]) return;
  state.loading[tab] = true;
  if (!silent) $(`#list-${tab}`).innerHTML = skeletonHtml(tab);
  $("#live-dot").style.background = "var(--link)";
  try {
    const res = await fetch(API[tab] + (force ? "?force=1" : ""));
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

/* ---------- 跑马灯资讯条 ---------- */

let tickerBusy = false;

async function updateTicker() {
  if (tickerBusy) return;
  tickerBusy = true;
  try {
    const [ts, mp] = await Promise.all([
      fetch(API["top-sellers"]).then(r => r.json()),
      fetch(API["most-played"]).then(r => r.json()),
    ]);
    const parts = [];
    const total = (mp.items || []).reduce((a, i) => a + (i.players || 0), 0);
    if (total) parts.push(`TOP100 总在线 ${total.toLocaleString("en-US")} 人`);
    (ts.items || []).slice(0, 3).forEach(i =>
      parts.push(`热销 #${i.rank} ${i.name} ${i.price?.final ?? ""}`));
    (mp.items || []).slice(0, 3).forEach(i =>
      parts.push(`最热 #${i.rank} ${i.name} ${fmt(i.players)} 人在线`));
    const seq = parts.map(p => `<span class="ti"><b>▮</b>${esc(p)}</span>`).join("");
    const track = $("#ticker-track");
    if (track) track.innerHTML = seq + seq; // 两份内容首尾相接实现无缝循环
    renderRails(mp);
  } catch (e) { /* 静默 */ } finally {
    tickerBusy = false;
  }
}

/* ---------- 侧边实时数据卡 ---------- */

function renderRails(mp) {
  const left = $("#rail-left");
  const right = $("#rail-right");
  if (!left || !right) return;
  const items = mp.items || [];
  const total = items.reduce((a, i) => a + (i.players || 0), 0);
  const medals = ["var(--gold)", "#d7e0f0", "#e89a6b"];
  left.innerHTML = '<div class="rail-title">▍此刻在线 TOP 3</div>' + items.slice(0, 3).map((i, idx) =>
    `<a class="rrow" href="${esc(i.url)}" target="_blank" rel="noopener">
       <span class="rnum" style="color:${medals[idx]}">${i.rank}</span>
       <img src="${esc(i.image)}" loading="lazy">
       <span class="rmeta">
         <span class="rname">${esc(i.name)}</span>
         <span class="rplayers">${fmt(i.players)} 人在线</span>
       </span>
     </a>`).join("");
  const t = new Date(mp.meta.updated_at * 1000).toLocaleTimeString("zh-CN", { hour12: false });
  right.innerHTML = '<div class="rail-title">▍REALTIME STATS</div>'
    + `<div class="stat"><div class="big">${fmt(total)}</div><div class="lbl">TOP100 总在线人数</div></div>`
    + `<div class="stat"><div class="big">${items.length}</div><div class="lbl">监控游戏数</div></div>`
    + `<div class="stat"><div class="big">${t}</div><div class="lbl">数据更新时间</div></div>`;
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
    updateTicker();
  }
  $("#countdown").textContent = `${state.nextRefresh}s 后自动刷新`;
}, 1000);

$("#tabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (btn) switchTab(btn.dataset.tab);
});

let refreshBusy = false;

$("#refresh-btn").addEventListener("click", async () => {
  if (refreshBusy) return;
  refreshBusy = true;
  const btn = $("#refresh-btn");
  const label = btn.querySelector("span");
  const old = label ? label.textContent : btn.textContent;
  btn.disabled = true;
  if (label) label.textContent = "刷新中…"; else btn.textContent = "刷新中…";
  state.nextRefresh = 60;
  await Promise.allSettled([
    load(state.active, { silent: true, force: true }),
    updateTicker(),
  ]);
  if (label) label.textContent = old; else btn.textContent = old;
  btn.disabled = false;
  refreshBusy = false;
});

$("#retry-btn").addEventListener("click", () => load(state.active));

switchTab("most-played");
load("most-played");
updateTicker();
updateTicker();
