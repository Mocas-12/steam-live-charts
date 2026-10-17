/* Steam 实时游戏榜单 —— 前端逻辑：tab 切换 + 60s 自动刷新 */

const API = {
  "top-sellers": "/api/top-sellers",
  "most-played": "/api/most-played",
  "free-to-keep": "/api/free-to-keep",
  "specials": "/api/specials",
  "new-releases": "/api/new-releases",
  "free-games": "/api/free-games",
  "epic-free": "/api/epic-free",
};

/* 榜单名白名单：location.hash / DOM dataset 等外部输入的唯一净化入口。
   逐字面量 case 等值匹配（标准允许列表形态），tab 名与 API 路径都只能
   是编译期常量，后续 URL 与 CSS 选择器拼接不再携带任何外部输入。 */
function resolveTab(raw) {
  switch (raw) {
    case "most-played": return "most-played";
    case "top-sellers": return "top-sellers";
    case "free-to-keep": return "free-to-keep";
    case "specials": return "specials";
    case "new-releases": return "new-releases";
    case "free-games": return "free-games";
    case "epic-free": return "epic-free";
    default: return null;
  }
}

const state = {
  active: "most-played",
  data: {},      // tab -> items
  meta: {},      // tab -> original collection metadata
  stale: {},     // last rendered freshness, for expiring alerts without a fetch
  briefing: null,
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
  const surge = it.surge ? `<span class="surge" title="最近30分钟均值对比此前2小时均值；采样缺口超过5分钟时不显示">+${it.surge}%</span>` : "";
  return `<span class="nameline">${star}<span class="gname">${esc(it.name)}</span>${surge}</span>`;
}

function rowHtml(it, stats) {
  if (!stats) {
    // 价格类榜单：# | 封面 | 游戏 | 价格
    const meta = [it.released, (it.genres || []).join(" / ")].filter(Boolean).join(" · ");
    const sub = meta ? `<span class="genre-line">${esc(meta)}</span>` : "";
    return `<a class="row simple" href="${esc(it.url)}" target="_blank" rel="noopener">
      <span class="rank">${it.rank}</span>
      <span class="cover" aria-hidden="true"><img src="${esc(it.image)}" alt="" loading="lazy" onerror="this.hidden=true"></span>
      <span class="gcol">${nameColHtml(it)}${sub}</span>
      <span class="price-col">${priceRowHtml(it.price)}</span>
    </a>`;
  }
  const genres = it.genres && it.genres.length ? esc(it.genres.join(" / ")) : "";
  return `<a class="row" href="${esc(it.url)}" target="_blank" rel="noopener">
    <span class="rank">${it.rank}</span>
    <span class="cover" aria-hidden="true"><img src="${esc(it.image)}" alt="" loading="lazy" onerror="this.hidden=true"></span>
    <span class="gcol">
      ${nameColHtml(it)}
      ${genres ? `<span class="genre-line">${genres}</span>` : ""}
    </span>
    <span class="pnum" data-label="在线">${fmt(it.players)}</span>
    <span class="peak-col peak-num">${fmt(it.peak)}</span>
    <span class="delta-col">${deltaHtml(it)}</span>
    <span class="spark-col">${sparkSvg(it.spark)}</span>
  </a>`;
}

function rowsHeadHtml(stats) {
  if (stats) {
    return ('<div class="rows-head"><span class="ctr">排名</span><span>游戏</span>'
      + '<span></span><span class="r">当前在线</span><span class="r">官方峰值</span>'
      + '<span class="ctr" title="上周官方排名减去当前实时排名；在线人数未知时不计算">较上周排名</span><span class="ctr">趋势</span></div>');
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

const EMPTY_TEXT = {
  "free-to-keep": {
    t: "当前没有限时免费入库活动",
    s: "Steam 免费入库活动零星出现（周末较多），开启后游戏永久入库 · 60 秒后自动复查",
  },
  "epic-free": {
    t: "Epic 当前没有可领取的免费游戏",
    s: "Epic 商城每周轮换免费档，即将开始的也会预告在这里",
  },
};

function emptyHtml(tab) {
  const x = EMPTY_TEXT[tab] || EMPTY_TEXT["free-to-keep"];
  return `<div class="empty">
    <div class="ghost">FREE</div>
    <div class="etitle">${x.t}</div>
    <div class="esub">${x.s}</div>
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
  const raw = state.data[tab];
  const items = raw && (isDataStale(state.meta[tab])
    ? raw.map(it => ({ ...it, surge: null, spark: [] })) : raw);
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
      : emptyHtml(tab);
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
    const response = await fetch("/api/briefing", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.briefing = await response.json();
  } catch (e) { /* Keep the last snapshot and its original collection time. */ }
  renderBriefing();
}

function renderBriefing() {
  const b = state.briefing;
  const el = $("#briefing");
  if (!b || !el) return;
  const parts = [];
  if (b.games_with_players) parts.push(`榜单 Top ${b.games_total} 在线合计 <b>${fmt(b.total_online)}</b>`);
  if (b.games_with_players < b.games_total) parts.push(`人数覆盖 ${b.games_with_players}/${b.games_total} 款`);
  if (state.active !== "most-played") parts.push(esc(metaText(b.meta)));
  if (b.ftk_count === null) parts.push("限免状态暂不可用");
  (isDataStale(b.meta) ? [] : b.surges || []).forEach(s =>
    parts.push(`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a> 近30分钟 <b>+${s.pct}%</b>`));
  if (b.new_entries) parts.push(`<b>${b.new_entries}</b> 款新上榜`);
  if (b.ftk_count && !isDataStale(b.free_to_keep_meta)) {
    parts.push(`限时免费进行中（${esc(b.ftk_names.join("、"))}${b.ftk_count > 3 ? " 等" : ""}）`);
  }
  el.innerHTML = parts.map(p => `<span class="bi">${p}</span>`).join("");
  el.hidden = false;
}

function isDataStale(meta) {
  return !meta || meta.stale || Date.now() / 1000 - meta.updated_at > meta.ttl;
}

function metaText(meta) {
  if (!meta) return "尚未取得数据";
  const stale = isDataStale(meta);
  const status = meta.refresh_failed ? "刷新失败，显示历史数据" : stale ? "历史缓存" : "已采集";
  const stamp = new Date(meta.updated_at * 1000).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
  return `${status} · ${stamp} UTC+8`;
}

function updateMeta() {
  const meta = state.meta[state.active];
  $("#updated-at").textContent = metaText(meta);
  const stale = isDataStale(meta);
  if (state.stale[state.active] !== stale) {
    state.stale[state.active] = stale;
    if (state.data[state.active]) render(state.active);
  }
  $("#live-dot").style.background = stale ? "var(--gold)" : "var(--up)";
}

/* ---------- 数据加载 ---------- */

function resolveApiUrl(tab) {
  switch (tab) {
    case "most-played": return "/api/most-played";
    case "top-sellers": return "/api/top-sellers";
    case "free-to-keep": return "/api/free-to-keep";
    case "specials": return "/api/specials";
    case "new-releases": return "/api/new-releases";
    case "free-games": return "/api/free-games";
    case "epic-free": return "/api/epic-free";
    default: return "/api/most-played";
  }
}

async function load(rawTab, { silent = false, force = false } = {}) {
  // 外部输入先过字面量白名单净化：非榜单名直接拒绝，URL 由常量前缀 + 常量键拼接
  const tab = resolveTab(rawTab);
  if (tab === null) return;
  if (state.loading[tab]) return;
  state.loading[tab] = true;
  if (!silent) $(`#list-${tab}`).innerHTML = skeletonHtml();
  $("#live-dot").style.background = "var(--link)";
  try {
    const res = await fetch(resolveApiUrl(tab) + (force ? "?force=1" : ""), { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.data[tab] = data.items;
    state.fetchedAt[tab] = Date.now();
    updateDeals(data.items); // 关注游戏降价检测
    state.meta[tab] = data.meta;
    if (tab === state.active) {
      updateMeta();
      state.nextRefresh = 60;
    }
    if (tab === state.active) $("#error-banner").hidden = true;
    if (tab === state.active) render(tab);
  } catch (e) {
    if (tab === state.active) {
      $("#error-text").textContent = `数据加载失败（${e.message}），Steam 接口可能暂时不可用。`;
      $("#error-banner").hidden = false;
      if (!state.data[tab]) $(`#list-${tab}`).innerHTML = "";
    }
  } finally {
    state.loading[tab] = false;
    updateMeta();
  }
}

function isStale(tab) {
  return !state.fetchedAt[tab] || Date.now() - state.fetchedAt[tab] > 60_000;
}

function switchTab(raw) {
  const name = resolveTab(raw);
  if (name === null || state.active === name) return;
  state.active = name;
  document.querySelectorAll(".tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === name)
  );
  document.querySelectorAll(".panel").forEach((p) =>
    (p.hidden = p.id !== `panel-${name}`)
  );
  render(name);
  updateMeta();
  if (isStale(name)) load(name);
}

/* ---------- 定时刷新 ---------- */

setInterval(() => {
  updateMeta();
  renderBriefing();
  state.nextRefresh -= 1;
  if (state.nextRefresh <= 0) {
    state.nextRefresh = 60;
    load(state.active, { silent: true });
    loadBriefing();
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
    loadBriefing(),
  ]);
  if (label) label.textContent = old; else btn.textContent = old;
  btn.disabled = false;
  refreshBusy = false;
});

$("#retry-btn").addEventListener("click", () => load(state.active));

updateWatchChip();
// 支持 #most-played 等 hash 深链：命中白名单时模拟点击对应 tab，
// 与用户点击走同一条 switchTab 入口；未命中/默认榜则直接加载默认榜
const wanted = resolveTab(location.hash.slice(1));
if (wanted && wanted !== "most-played") {
  let matched = false;
  for (const b of document.querySelectorAll(".tab")) {
    if (b.dataset.tab === wanted) {
      b.click();
      matched = true;
      break;
    }
  }
  if (!matched) load("most-played");
} else {
  load("most-played");
}
loadBriefing();
