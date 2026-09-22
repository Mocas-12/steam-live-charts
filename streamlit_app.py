"""Steam 实时游戏榜单 —— Streamlit Cloud 入口（VOLT 荧光运动记分板主题）。

与本地 FastAPI 版（app.py + static/）共用数据层 steamdata.py；
st.cache_data 控制上游请求频率，st.fragment(run_every=60s) 让榜单原地自动刷新。
"""

import html as htmllib
import time

import streamlit as st

import steamdata

st.set_page_config(
    page_title="GAMECHARTS · 实时游戏榜单",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------- VOLT 主题 ----------

CSS = """
<style>
/* 隐藏 Streamlit 自带框架 */
[data-testid="stHeader"] { display: none; }
#MainMenu, footer, [data-testid="stFooter"] { visibility: hidden; }
[data-testid="stStatusWidget"], [data-testid="stToolbar"] { display: none; }
.block-container { padding: 0 1rem 2rem; max-width: 1060px; margin: 0 auto; }
section[data-testid="stVerticalBlock"] { gap: .45rem; }

/* 页面底色：纯黑，靠组件本身出效果 */
.stApp {
  background: linear-gradient(180deg, #0a0b0f 0%, #08090c 320px) fixed;
}
body, .stApp, p {
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  color: #f2f4f8;
}

:root {
  --gc-panel: #0e1015;
  --gc-panel2: #12141b;
  --gc-line: #1f232e;
  --gc-line-hi: rgba(214,255,63,.5);
  --gc-volt: #d6ff3f;
  --gc-muted: #9aa2b5;
  --gc-dim: #565e70;
  --gc-green: #d6ff3f;
  --gc-red: #ff4d5e;
  --gc-mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
}

a { color: #d6ff3f; }
.stMarkdown a, .stMarkdown a * { text-decoration: none !important; }

/* 跑马灯资讯条 */
.gc-ticker {
  background: var(--gc-volt); color: #0a0b0e;
  overflow: hidden; height: 30px; display: flex; align-items: center;
  margin: 0 -1rem; position: relative; z-index: 11;
}
.gc-ticker-track {
  display: inline-flex; white-space: nowrap; align-items: center;
  animation: gc-tick 36s linear infinite; will-change: transform;
}
.gc-ticker:hover .gc-ticker-track { animation-play-state: paused; }
@keyframes gc-tick { from { transform: translateX(0); } to { transform: translateX(-50%); } }
.gc-ticker .ti {
  color: #0a0b0e !important;
  font-family: var(--gc-mono); font-size: 11.5px; font-weight: 700; letter-spacing: 1px;
  padding: 0 22px; text-transform: uppercase;
}
.gc-ticker .ti b { color: #3e5200 !important; margin-right: 8px; }

/* 顶栏 */
.gc-nav {
  background: #0a0b0e; margin: 0 -1rem;
  padding: 0 max(1rem, calc((100% - 1060px)/2));
  border-bottom: 1px solid var(--gc-line);
  height: 60px; display: flex; align-items: center;
}
.gc-nav-inner { display: flex; align-items: center; gap: 18px; width: 100%; }
.gc-logo { display: flex; align-items: center; gap: 10px; }
.gc-logo-mark {
  width: 13px; height: 22px; background: var(--gc-volt);
  transform: skewX(-12deg); box-shadow: 4px 0 0 #2e3a05;
}
.gc-logo-word { font-size: 17px; font-weight: 900; font-style: italic; letter-spacing: 2px; color: #fff; }
.gc-logo-word span { color: var(--gc-volt); }
.gc-logo-sub {
  font-family: var(--gc-mono); font-size: 10px; font-weight: 700; letter-spacing: 3px;
  color: #0a0b0e !important; background: var(--gc-volt); padding: 3px 8px; transform: skewX(-12deg);
}
.gc-nav .spacer { margin-right: auto; }
.gc-nav a { color: #9aa2b5; text-decoration: none; font-size: 12px; font-weight: 700; letter-spacing: 2px; padding: 6px 10px; border-radius: 3px; }
.gc-nav a:hover { color: var(--gc-volt); background: rgba(214,255,63,.07); }
.gc-install {
  color: #0a0b0e !important; font-size: 12px; font-weight: 900; letter-spacing: 1px;
  padding: 9px 16px; background: var(--gc-volt); transform: skewX(-12deg);
}
.gc-install span { color: #0a0b0e !important; display: inline-block; transform: skewX(12deg); }

/* 侧边水印 */
.gc-rail {
  position: fixed; top: 50%; transform: translateY(-50%); z-index: 5;
  writing-mode: vertical-rl; font-family: var(--gc-mono);
  font-size: 10px; font-weight: 700; letter-spacing: 5px; color: #23272f;
  user-select: none; pointer-events: none; text-transform: uppercase;
}
.gc-rail .volt { color: rgba(214,255,63,.35); }
.gc-rail.left { left: calc(50% - 530px - 54px); }
.gc-rail.right { right: calc(50% - 530px - 54px); }
@media (max-width: 1300px) { .gc-rail { display: none; } }

/* 标题区 */
.gc-overline {
  font-family: var(--gc-mono); font-size: 11px; font-weight: 700; letter-spacing: 4px;
  color: var(--gc-volt); text-transform: uppercase; margin: 14px 0 4px;
}
.gc-overline::before { content: "▮ "; }
.gc-h1 {
  font-size: 35px; font-weight: 900; font-style: italic; letter-spacing: 1px;
  line-height: 1.1; color: #fff !important;
}
.gc-h1 em { font-style: italic; color: var(--gc-volt); }
.gc-meta {
  font-family: var(--gc-mono); font-size: 12px; color: #9aa2b5;
  display: flex; align-items: center; gap: 8px;
}
.gc-meta .dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--gc-volt);
  box-shadow: 0 0 8px rgba(214,255,63,.8); animation: gc-pulse 1.6s infinite;
}
@keyframes gc-pulse { 50% { opacity: .25; } }

/* 刷新按钮（斜切荧光块，与标题居中对齐） */
.stButton > button {
  width: 100%; border-radius: 3px; padding: 10px 0;
  background: var(--gc-volt); color: #0a0b0e; border: none;
  font-size: 12.5px; font-weight: 900; font-style: italic; letter-spacing: 1px;
  transform: skewX(-10deg); transition: filter .15s;
}
.stButton > button:hover { filter: brightness(1.12); }
.stButton > button p { font-size: 12.5px; font-weight: 900; letter-spacing: 1px; color: #0a0b0e !important; }

/* Tab（baseweb 覆盖） */
[data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid var(--gc-line); }
[role="tab"] {
  color: #9aa2b5; border-radius: 4px; padding: 10px 18px;
  font-weight: 800; letter-spacing: 1px;
}
[role="tab"] p { font-size: 13.5px; font-weight: 800; letter-spacing: 1px; }
[role="tab"]:hover p { color: var(--gc-volt) !important; }
[role="tab"][aria-selected="true"] p { color: #0a0b0e !important; }
[role="tab"][aria-selected="true"] {
  background: linear-gradient(105deg, var(--gc-volt) 78%, #b8dd2a) !important;
  border-radius: 3px;
}
[data-baseweb="tab-highlight"] { display: none !important; }

/* 榜单面板 */
.gc-panel {
  background: var(--gc-panel);
  border: 1px solid var(--gc-line); border-top: 2px solid var(--gc-volt);
  border-radius: 0 8px 8px 8px;
  padding: 4px 18px 18px;
}
.gc-section {
  color: #fff; font-size: 17px; font-weight: 900; font-style: italic; letter-spacing: 1px;
  padding: 15px 0 11px; display: flex; align-items: baseline; gap: 10px;
}
.gc-section::before {
  content: ""; width: 14px; height: 15px; align-self: center;
  background: var(--gc-volt); transform: skewX(-12deg);
}
.gc-section .sub { color: #565e70 !important; font-size: 11px; font-family: var(--gc-mono); letter-spacing: 2px; font-style: normal; }

/* 卡片网格 */
.gc-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(178px, 1fr)); gap: 13px;
}
.gc-card {
  position: relative; text-decoration: none !important; display: block; border-radius: 6px;
  background: var(--gc-panel2);
  border: 1px solid var(--gc-line);
  overflow: hidden;
  transition: transform .18s, border-color .18s;
}
.gc-card:hover {
  transform: translateY(-3px); border-color: rgba(214,255,63,.55);
}
.gc-card img { width: 100%; aspect-ratio: 460/215; display: block; object-fit: cover; }
.gc-card .name {
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  color: #f2f4f8 !important; font-size: 13px; font-weight: 700; line-height: 1.35;
  padding: 9px 11px 2px; height: 38px; overflow: hidden;
}
.gc-card:hover .name { color: #d6ff3f !important; }
.gc-card .price-row { display: flex; align-items: center; gap: 7px; padding: 7px 11px 11px; min-height: 32px; }
.gc-rank {
  position: absolute; top: 7px; left: 7px; z-index: 1;
  font-family: var(--gc-mono); font-size: 12px; font-weight: 800; font-style: italic;
  color: #9aa2b5; background: rgba(8,9,12,.85);
  border: 1px solid var(--gc-line);
  padding: 1px 9px; border-radius: 2px;
}
.gc-grid .gc-card:nth-child(1) .gc-rank {
  color: #1a1204; background: #ffcf5c; border-color: #ffcf5c;
}
.gc-grid .gc-card:nth-child(2) .gc-rank {
  color: #10141d; background: #d7e0f0; border-color: #d7e0f0;
}
.gc-grid .gc-card:nth-child(3) .gc-rank {
  color: #1c0f05; background: #e89a6b; border-color: #e89a6b;
}

/* 折扣标签（荧光绿斜切 pill） */
.gc-tag {
  display: inline-flex; align-items: stretch; border-radius: 3px;
  background: var(--gc-volt); transform: skewX(-8deg);
}
.gc-tag .pct {
  color: #0a0b0e !important; font-weight: 900; font-size: 12.5px; padding: 3px 7px;
  font-family: var(--gc-mono); transform: skewX(8deg);
}
.gc-tag .final {
  color: #0a0b0e !important; font-size: 12.5px; padding: 3px 8px; font-weight: 700;
  font-family: var(--gc-mono); transform: skewX(8deg);
}
.gc-price { color: #f2f4f8 !important; font-size: 13px; font-family: var(--gc-mono); font-weight: 700; }
.gc-price.free { color: var(--gc-volt) !important; }
.gc-strike { color: #565e70 !important; text-decoration: line-through; font-size: 12px; font-family: var(--gc-mono); }

/* 最热游玩行 */
.gc-thead, .gc-row {
  display: grid;
  grid-template-columns: 52px 150px minmax(0,1fr) 105px 105px 66px;
  gap: 14px; align-items: center; padding: 7px 4px;
}
.gc-thead {
  color: #565e70 !important; font-size: 11px; font-weight: 700; letter-spacing: 2px;
  font-family: var(--gc-mono); text-transform: uppercase;
  border-bottom: 1px solid var(--gc-line); padding-bottom: 9px; margin-bottom: 2px;
}
.gc-thead .r { text-align: right; }
.gc-thead .ctr { text-align: center; }
.gc-row {
  border-bottom: 1px solid rgba(255,255,255,.04);
  border-radius: 6px; text-decoration: none !important;
}
.gc-row:hover { background: rgba(214,255,63,.05); }
.gc-row .rank {
  font-family: var(--gc-mono); font-size: 21px; font-weight: 900; font-style: italic;
  color: transparent !important; -webkit-text-stroke: 1.2px #3a4152; text-align: center;
}
.gc-row:nth-of-type(1) .rank, .gc-row:nth-of-type(2) .rank, .gc-row:nth-of-type(3) .rank { -webkit-text-stroke: 0; }
.gc-row:nth-of-type(1) .rank {
  background: linear-gradient(160deg, #ffe9a8, #ffcf5c); -webkit-background-clip: text; background-clip: text;
}
.gc-row:nth-of-type(2) .rank {
  background: linear-gradient(160deg, #f4f8ff, #d7e0f0); -webkit-background-clip: text; background-clip: text;
}
.gc-row:nth-of-type(3) .rank {
  background: linear-gradient(160deg, #ffc79c, #e89a6b); -webkit-background-clip: text; background-clip: text;
}
.gc-row img {
  width: 150px; aspect-ratio: 460/215; object-fit: cover; border-radius: 4px; display: block;
  border: 1px solid var(--gc-line);
}
.gc-row .gname { color: #fff !important; font-size: 14.5px; font-weight: 700; line-height: 1.3; }
.gc-row:hover .gname { color: #d6ff3f !important; }
.gc-row .genre { color: #9aa2b5 !important; font-size: 11.5px; margin-top: 3px; }
.gc-row .genre .p { color: #d6ff3f !important; margin-left: 8px; font-family: var(--gc-mono); font-weight: 700; }
.gc-row .pnum {
  color: #fff !important; font-size: 18px; font-weight: 800; text-align: right;
  font-family: var(--gc-mono); font-variant-numeric: tabular-nums;
}
.gc-row .peak {
  color: #9aa2b5 !important; font-size: 13.5px; text-align: right;
  font-family: var(--gc-mono); font-variant-numeric: tabular-nums;
}
.gc-row .delta { text-align: center; font-size: 13px; font-weight: 800; font-family: var(--gc-mono); }
.gc-row .delta.up { color: #d6ff3f !important; }
.gc-row .delta.down { color: #ff4d5e !important; }
.gc-row .delta.same { color: #565e70 !important; font-weight: 400; }
.gc-row .delta .new {
  display: inline-block; background: var(--gc-volt); color: #0a0b0e !important;
  font-size: 10px; padding: 2px 7px; border-radius: 2px; letter-spacing: 1px; font-style: italic;
}

/* 空状态 */
.gc-empty { padding: 44px 0 36px; text-align: center; color: #9aa2b5; }
.gc-empty .ghost {
  font-family: var(--gc-mono); font-size: 40px; font-weight: 900; font-style: italic;
  color: transparent; -webkit-text-stroke: 1.5px #2b313e; line-height: 1;
}
.gc-empty .etitle { color: #fff; font-weight: 800; margin: 12px 0 6px; }
.gc-empty .esub { font-size: 12.5px; font-family: var(--gc-mono); color: #565e70; }

.gc-meta-line {
  font-family: var(--gc-mono); font-size: 12px; color: #9aa2b5;
  display: flex; align-items: center; gap: 8px; padding: 2px 2px 8px;
}
.gc-meta-line .dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--gc-volt);
  box-shadow: 0 0 8px rgba(214,255,63,.8); animation: gc-pulse 1.6s infinite;
}

.gc-footer {
  color: #565e70 !important; font-size: 12px; line-height: 1.7;
  border-top: 1px solid var(--gc-line); padding-top: 12px; margin-top: 20px;
}

@media (max-width: 860px) {
  .gc-thead { display: none; }
  .gc-row { grid-template-columns: 34px 110px minmax(0,1fr) auto; gap: 10px; }
  .gc-row img { width: 110px; }
  .gc-row .peak, .gc-row .delta { display: none; }
  .gc-row .pnum { font-size: 15px; }
  .gc-nav a:not(.gc-install) { display: none; }
}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)

# 侧边水印（宽屏装饰）
st.markdown(
    """
<div class="gc-rail left">GAMECHARTS <span class="volt">▮</span> REALTIME GAME LEADERBOARDS</div>
<div class="gc-rail right">DATA · STEAM OFFICIAL API <span class="volt">▮</span> REFRESH 60S</div>
""",
    unsafe_allow_html=True,
)

# 顶栏 + 跑马灯
st.markdown(
    """
<div class="gc-nav"><div class="gc-nav-inner">
  <span class="gc-logo">
    <span class="gc-logo-mark"></span>
    <span class="gc-logo-word">GAME<span>CHARTS</span></span>
    <span class="gc-logo-sub">LIVE</span>
  </span>
  <span class="spacer"></span>
  <a href="https://store.steampowered.com/" target="_blank">商店</a>
  <a href="https://steamcommunity.com/" target="_blank">社区</a>
  <a href="https://store.steampowered.com/charts/" target="_blank">官方榜单</a>
  <a class="gc-install" href="https://store.steampowered.com/about/" target="_blank"><span>安装 STEAM</span></a>
</div></div>
""",
    unsafe_allow_html=True,
)

# ---------- 数据 ----------


@st.cache_data(ttl=120, show_spinner="正在从 Steam 拉取热销榜…")
def load_top_sellers():
    items = [it for it in steamdata.fetch_search(False) if it["price"]["final"]]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


@st.cache_data(ttl=120, show_spinner="正在从 Steam 拉取特惠榜…")
def load_specials():
    items = [it for it in steamdata.fetch_search(True) if it["price"]["final"]]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


@st.cache_data(ttl=120, show_spinner="正在扫描限时免费入库活动…")
def load_free_to_keep():
    return [{**it, "rank": i + 1} for i, it in enumerate(steamdata.fetch_free_to_keep())]


@st.cache_data(ttl=600, show_spinner="正在拉取新品上架榜…")
def load_new_releases():
    items = [it for it in steamdata.fetch_new_releases() if it["price"]["final"]]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


@st.cache_data(ttl=120, show_spinner="正在拉取免费游戏榜…")
def load_free_games():
    items = [
        it for it in steamdata.fetch_search(False, free=True)
        if it["price"]["final"] and it["price"]["free"]  # 过滤混入的免费试玩付费游戏
    ]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


@st.cache_data(ttl=60, show_spinner="正在逐款查询 Top100 实时在线人数（首载约 10-20 秒）…")
def load_most_played():
    return steamdata.build_most_played()


# ---------- HTML 渲染 ----------


def _esc(s):
    return htmllib.escape(str(s)) if s is not None else ""


def price_row_html(p):
    if not p or not p.get("final"):
        return '<span class="gc-price">—</span>'
    if p.get("pct"):
        return (f'<span class="gc-strike">{_esc(p["original"])}</span>'
                f'<span class="gc-tag"><span class="pct">{p["pct"]}%</span>'
                f'<span class="final">{_esc(p["final"])}</span></span>')
    if p.get("free"):
        return '<span class="gc-price free">免费开玩</span>'
    return f'<span class="gc-price">{_esc(p["final"])}</span>'


def card_html(it):
    return (f'<a class="gc-card" href="{_esc(it["url"])}" target="_blank">'
            f'<span class="gc-rank">#{it["rank"]}</span>'
            f'<img src="{_esc(it["image"])}" loading="lazy" onerror="this.style.visibility=\'hidden\'">'
            f'<span class="name">{_esc(it["name"])}</span>'
            f'<span class="price-row">{price_row_html(it["price"])}</span></a>')


def grid_html(items, title, sub):
    body = "".join(card_html(it) for it in items) if items else EMPTY_HTML
    return (f'<div class="gc-panel"><div class="gc-section">{title}'
            f'<span class="sub">{sub}</span></div>'
            f'<div class="gc-grid">{body}</div></div>')


EMPTY_HTML = (
    '<div class="gc-empty"><div class="ghost">FREE</div>'
    '<div class="etitle">当前没有限时免费入库活动</div>'
    '<div class="esub">Steam 免费入库活动零星出现（周末较多），开启后游戏永久入库 · 60 秒后自动复查</div></div>'
)


def _fmt(n):
    return "—" if n is None else f"{n:,}"


def delta_html(it):
    if it.get("is_new"):
        return '<span class="delta"><span class="new">新上榜</span></span>'
    d = it.get("delta")
    if d is None:
        return '<span class="delta same">—</span>'
    if d > 0:
        return f'<span class="delta up">▲{d}</span>'
    if d < 0:
        return f'<span class="delta down">▼{-d}</span>'
    return '<span class="delta same">—</span>'


def row_html(it):
    p = it.get("price") or {}
    mini = ""
    if p.get("final"):
        if p.get("pct"):
            mini = f'<span class="p pct">{p["pct"]}% {_esc(p["final"])}</span>'
        else:
            mini = f'<span class="p">{_esc(p["final"])}</span>'
    genres = " / ".join(it.get("genres") or [])
    sub = (f'<span class="genre">{_esc(genres)}{mini}</span>' if (genres or mini) else "")
    return (f'<a class="gc-row" href="{_esc(it["url"])}" target="_blank">'
            f'<span class="rank">#{it["rank"]}</span>'
            f'<img src="{_esc(it["image"])}" loading="lazy" onerror="this.style.visibility=\'hidden\'">'
            f'<span><div class="gname">{_esc(it["name"])}</div>{sub}</span>'
            f'<span class="pnum">{_fmt(it.get("players"))}</span>'
            f'<span class="peak">{_fmt(it.get("peak"))}</span>'
            f'{delta_html(it)}</a>')


def rows_html(items, title, sub):
    head = ('<div class="gc-thead"><span class="ctr">#</span><span>游戏</span>'
            '<span></span><span class="r">当前在线</span><span class="r">今日峰值</span>'
            '<span class="ctr">周变化</span></div>')
    body = "".join(row_html(it) for it in items)
    return (f'<div class="gc-panel"><div class="gc-section">{title}'
            f'<span class="sub">{sub}</span></div>{head}{body}</div>')


def updated_line():
    t = time.strftime("%H:%M:%S", time.localtime())
    return (f'<div class="gc-meta-line"><span class="dot"></span>'
            f'更新于 {t} · 每 60 秒自动刷新</div>')


# ---------- 头部（列内垂直居中） ----------

head_l, head_r = st.columns([4, 1], vertical_alignment="center")
with head_l:
    st.markdown('<div class="gc-overline">Realtime Arena · 每 60 秒自动刷新</div>', unsafe_allow_html=True)
    st.markdown('<div class="gc-h1">实时游戏<em>榜单</em></div>', unsafe_allow_html=True)
with head_r:
    if st.button("↻ 立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ---------- 跑马灯资讯条 ----------


@st.fragment(run_every="60s")
def render_ticker():
    parts = []
    for i in load_top_sellers()[:4]:
        parts.append(f"热销 #{i['rank']} {i['name']} {i['price']['final'] or ''}")
    for i in load_specials()[:2]:
        if i["price"]["pct"]:
            parts.append(f"特惠 {i['price']['pct']}% {i['name']} {i['price']['final']}")
    ftk = load_free_to_keep()
    for i in ftk[:3]:
        parts.append(f"限时免费入库 {i['name']}（原价 {i['price']['original']}）")
    if not ftk:
        parts.append("限时免费入库 · 当前无活动，周末再多来看看")
    seq = "".join(f'<span class="ti"><b>▮</b>{_esc(p)}</span>' for p in parts)
    st.markdown(
        f'<div class="gc-ticker"><div class="gc-ticker-track">{seq}{seq}</div></div>',
        unsafe_allow_html=True,
    )


render_ticker()

# ---------- 六个榜单（fragment 每 60 秒原地刷新，不丢 tab 状态） ----------

tab_sellers, tab_played, tab_ftk, tab_specials, tab_new, tab_free = st.tabs(
    ["热销商品", "最热游玩", "限时免费", "特惠专区", "新品上架", "免费游戏"]
)


@st.fragment(run_every="60s")
def render_sellers():
    st.markdown(
        updated_line() + grid_html(load_top_sellers(), "热门畅销商品", "TOP 50 · BY UNITS SOLD"),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_most_played():
    st.markdown(
        updated_line() + rows_html(load_most_played(), "最热游玩游戏", "TOP 100 · BY CURRENT PLAYERS"),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_free_to_keep():
    st.markdown(
        updated_line() + grid_html(load_free_to_keep(), "限时免费入库", "FREE TO KEEP · 原价付费，现在免费领"),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_specials():
    st.markdown(
        updated_line() + grid_html(load_specials(), "特惠专区", "TOP 50 · HOT DEALS"),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_new():
    st.markdown(
        updated_line() + grid_html(load_new_releases(), "新品上架", "TOP 30 · NEW RELEASES"),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_free():
    st.markdown(
        updated_line() + grid_html(load_free_games(), "免费游戏", "TOP 50 · FREE TO PLAY"),
        unsafe_allow_html=True,
    )


with tab_sellers:
    render_sellers()
with tab_played:
    render_most_played()
with tab_ftk:
    render_free_to_keep()
with tab_specials:
    render_specials()
with tab_new:
    render_new()
with tab_free:
    render_free()

st.markdown(
    '<div class="gc-footer">本页面为非官方第三方工具，与 Valve Corporation 无从属关系。'
    "榜单数据实时来自 Steam 官方公开接口，游戏名称、图片与价格版权归 Valve 及相应开发商所有。</div>",
    unsafe_allow_html=True,
)
