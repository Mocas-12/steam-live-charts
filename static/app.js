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
  query: "",     // 榜单内游戏名筛选
  watchOnly: false, // 只看关注
  prevPlayers: {},   // tab -> {appid: 上次在线数}，用于数字脉冲
};

/* 关注列表：localStorage 持久化；deals 记录各游戏上次见到的折扣力度，跌破即提示 */
const watch = new Set(JSON.parse(localStorage.getItem("gc_watch") || "[]"));
const deals = JSON.parse(localStorage.getItem("gc_deals") || "{}");
const dealNow = new Set(); // 本次会话检测到的「关注游戏降价了」

function saveWatch() {
  localStorage.setItem("gc_watch", JSON.stringify([...watch]));
}

function toggleWatch(appid) {
  if (watch.has(appid)) watch.delete(appid);
  else watch.add(appid);
  saveWatch();
  updateWatchChip();
  render(state.active);
}

function updateWatchChip() {
  const chip = $("#watch-chip");
  if (!chip) return;
  chip.hidden = watch.size === 0;
  $("#watch-count").textContent = watch.size;
  chip.classList.toggle("active", state.watchOnly);
}

/* 折扣追踪：pct 跌破上次记录 → 绿星提示；折扣消失则清记录 */
function updateDeals(items) {
  for (const it of items) {
    const pct = it.price && it.price.pct != null ? it.price.pct : null;
    const last = deals[it.appid];
    if (pct != null) {
      if (last != null && pct < last && watch.has(it.appid)) dealNow.add(it.appid);
      deals[it.appid] = pct;
    } else if (last != null) {
      delete deals[it.appid];
      dealNow.delete(it.appid);
    }
  }
  localStorage.setItem("gc_deals", JSON.stringify(deals));
}

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

/* 24h 在线迷你曲线：按走势着色（涨绿/跌红/平金）+ 最新点 */
function sparkSvg(spark) {
  if (!spark || spark.length < 2) return '<span class="spark-dim">采样中</span>';
  const w = 96, h = 22, pad = 2;
  const min = Math.min(...spark), max = Math.max(...spark);
  const range = (max - min) || 1;
  const xy = spark.map((v, i) => [
    pad + (i * (w - 2 * pad)) / (spark.length - 1),
    h - pad - ((v - min) / range) * (h - 2 * pad),
  ]);
  const pts = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const [lx, ly] = xy[xy.length - 1];
  const trend = spark[spark.length - 1] > spark[0] ? "up" : spark[spark.length - 1] < spark[0] ? "down" : "flat";
  return `<svg class="spark ${trend}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <polyline points="${pts}"/><circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="2"/>
  </svg>`;
}

function nameColHtml(it) {
  /* 游戏名列：☆关注 + 名称 + 🔥异动徽章（所有榜单通用） */
  const watched = watch.has(it.appid);
  const deal = watched && dealNow.has(it.appid);
  const star = `<span class="star${watched ? " on" : ""}${deal ? " deal" : ""}" data-appid="${it.appid}" `
    + `title="${watched ? "取消关注" : "关注"}">${watched ? "★" : "☆"}</span>`;
  const surge = it.surge ? `<span class="surge">🔥 +${it.surge}%</span>` : "";
  return `<span class="nameline">${star}<span class="gname">${esc(it.name)}</span>${surge}</span>`;
}

function rowHtml(it, stats) {
  if (!stats) {
    // 价格类榜单：# | 封面 | 游戏 | 价格
    const meta = [it.released, (it.genres || []).join(" / ")].filter(Boolean).join(" · ");
    const sub = meta ? `<span class="genre-line">${esc(meta)}</span>` : "";
    return `<a class="row simple" href="${esc(it.url)}" target="_blank" rel="noopener">
      <span class="rank">${it.rank}</span>
      <img src="${esc(it.image)}" alt="${esc(it.name)}" loading="lazy"
           onerror="this.style.visibility='hidden'">
      <span class="gcol">${nameColHtml(it)}${sub}</span>
      <span class="price-col">${priceRowHtml(it.price)}</span>
    </a>`;
  }
  const genres = it.genres && it.genres.length ? esc(it.genres.join(" / ")) : "";
  return `<a class="row" href="${esc(it.url)}" target="_blank" rel="noopener">
    <span class="rank">${it.rank}</span>
    <img src="${esc(it.image)}" alt="${esc(it.name)}" loading="lazy"
         onerror="this.style.visibility='hidden'">
    <span class="gcol">
      ${nameColHtml(it)}
      ${genres ? `<span class="genre-line">${genres}</span>` : ""}
    </span>
    <span class="pnum">${fmt(it.players)}</span>
    <span class="peak-col peak-num">${fmt(it.peak)}</span>
    <span class="delta-col">${deltaHtml(it)}</span>
    <span class="spark-col">${sparkSvg(it.spark)}</span>
  </a>`;
}

function rowsHeadHtml(stats) {
  if (stats) {
    return ('<div class="rows-head"><span class="ctr">排名</span><span>游戏</span>'
      + '<span></span><span class="r">当前在线</span><span class="r">今日峰值</span>'
      + '<span class="ctr">周变化</span><span class="ctr">趋势</span></div>');
  }
  return ('<div class="rows-head simple"><span class="ctr">排名</span><span>游戏</span>'
    + '<span></span><span class="r">价格</span></div>');
}

function skeletonHtml() {
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

function applyFilter(items) {
  let out = items;
  const q = state.query.trim().toLowerCase();
  if (q) out = out.filter(it => String(it.name || "").toLowerCase().includes(q));
  if (state.watchOnly) out = out.filter(it => watch.has(it.appid));
  return out;
}

function render(tab) {
  const items = state.data[tab];
  const listEl = $(`#list-${tab}`);
  if (!items) {
    listEl.innerHTML = skeletonHtml();
    return;
  }
  const shown = applyFilter(items);
  if (!shown.length) {
    // 原榜就空 -> 限时免费空状态；被筛空 -> 提示（区分筛选词与关注过滤两种原因）
    listEl.innerHTML = items.length
      ? `<div class="empty"><div class="ghost">0</div>`
        + `<div class="etitle">没有匹配的游戏</div>`
        + `<div class="esub">${state.watchOnly && !state.query.trim()
            ? "你关注的游戏不在当前榜单，切换 tab 或点名字前的 ☆ 关注更多"
            : "换个关键词，或清空筛选框看完整榜单"}</div></div>`
      : emptyHtml();
    return;
  }
  const stats = tab === "most-played";
  listEl.innerHTML = rowsHeadHtml(stats) + shown.map(it => rowHtml(it, stats)).join("");
  pulseChanged(tab, listEl); // 数字变化时轻微脉冲，让"活着"被看见
}

/* 在线人数与上次相比有变化的行：数字闪一次金色 */
function pulseChanged(tab, listEl) {
  const prev = state.prevPlayers[tab] || (state.prevPlayers[tab] = {});
  listEl.querySelectorAll(".row").forEach(r => {
    const star = r.querySelector(".star");
    if (!star) return;
    const id = Number(star.dataset.appid);
    const pn = r.querySelector(".pnum");
    if (!pn) return;
    const cur = Number((pn.textContent || "").replace(/,/g, ""));
    if (!Number.isFinite(cur)) return;
    if (id in prev && prev[id] !== cur) {
      pn.classList.remove("tick");
      void pn.offsetWidth; // 重启同 key 动画
      pn.classList.add("tick");
    }
    prev[id] = cur;
  });
}

/* ---------- 今日速览条 ---------- */

async function loadBriefing() {
  try {
    const b = await (await fetch("/api/briefing", { cache: "no-store" })).json();
    const el = $("#briefing");
    if (!el) return;
    const parts = [];
    if (b.total_online) parts.push(`此刻 <b>${fmt(b.total_online)}</b> 人在线`);
    (b.surges || []).forEach(s =>
      parts.push(`🔥 <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a> 在线 <b>+${s.pct}%</b>`));
    if (b.new_entries) parts.push(`<b>${b.new_entries}</b> 款新上榜`);
    if (b.ftk_count) {
      parts.push(`🎁 限时免费进行中（${esc(b.ftk_names.join("、"))}${b.ftk_count > 3 ? " 等" : ""}）`);
    }
    if (!parts.length) parts.push("数据同步中…");
    el.innerHTML = parts.map(p => `<span class="bi">${p}</span>`).join("");
    el.hidden = false;
  } catch (e) { /* 保留占位 */ }
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
  if (!silent) $(`#list-${tab}`).innerHTML = skeletonHtml();
  $("#live-dot").style.background = "var(--link)";
  try {
    const res = await fetch(API[tab] + (force ? "?force=1" : ""), { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.data[tab] = data.items;
    state.fetchedAt[tab] = Date.now();
    updateDeals(data.items); // 关注游戏降价检测
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
      fetch(API["top-sellers"], { cache: "no-store" }).then(r => r.json()),
      fetch(API["most-played"], { cache: "no-store" }).then(r => r.json()),
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
  loadBriefing(); // 速览条跟随同一节奏更新
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

$("#filter").addEventListener("input", (e) => {
  state.query = e.target.value;
  render(state.active); // 筛选跨 tab 生效，60s 刷新后依然保持
});

$("#watch-chip").addEventListener("click", () => {
  state.watchOnly = !state.watchOnly;
  updateWatchChip();
  render(state.active);
});

/* 星标点击：捕获阶段拦截，避免触发行内 <a> 跳转 */
document.addEventListener("click", (e) => {
  const star = e.target.closest(".star");
  if (!star) return;
  e.preventDefault();
  e.stopPropagation();
  toggleWatch(Number(star.dataset.appid));
}, true);

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

// 支持 #most-played 等 hash 深链直达指定榜单
const h = location.hash.slice(1);
const initial = API[h] ? h : "most-played";
updateWatchChip();
switchTab(initial);
load(initial);
updateTicker();
