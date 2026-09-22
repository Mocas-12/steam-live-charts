"""Steam 实时游戏榜单 —— Streamlit Cloud 入口（Cinematic 电影感暗色主题）。

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

# ---------- CINEMATIC 主题 ----------

CSS = """
<style>
/* 隐藏 Streamlit 自带框架 */
[data-testid="stHeader"] { display: none; }
#MainMenu, footer, [data-testid="stFooter"] { visibility: hidden; }
[data-testid="stStatusWidget"], [data-testid="stToolbar"] { display: none; }
.block-container { padding: 0 1.25rem 2rem; max-width: 1100px; margin: 0 auto; }
section[data-testid="stVerticalBlock"] { gap: .45rem; }

/* 页面底色：深炭 + 顶部一点暖金氛围 */
.stApp {
  background:
    radial-gradient(1000px 500px at 50% -200px, rgba(232,194,104,.05), transparent 70%),
    #0d0f13 fixed;
}
body, .stApp, p {
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  color: #e8eaf0;
}

:root {
  --gc-card: #171a21;
  --gc-card-hi: #1c202a;
  --gc-line: rgba(255,255,255,.07);
  --gc-line-hi: rgba(255,255,255,.16);
  --gc-text: #e8eaf0;
  --gc-muted: #98a0b3;
  --gc-dim: #6b7285;
  --gc-gold: #e8c268;
  --gc-up: #6fdc8c;
  --gc-down: #ff6b7a;
  --gc-deal: #7ee08f;
  --gc-mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
}

a { color: #e8eaf0; }
.stMarkdown a, .stMarkdown a * { text-decoration: none !important; }

/* 跑马灯资讯条 */
.gc-ticker {
  background: rgba(255,255,255,.03); border-bottom: 1px solid var(--gc-line);
  color: #98a0b3;
  overflow: hidden; height: 32px; display: flex; align-items: center;
  margin: 0 -1.25rem;
}
.gc-ticker-track {
  display: inline-flex; white-space: nowrap; align-items: center;
  animation: gc-tick 40s linear infinite; will-change: transform;
}
.gc-ticker:hover .gc-ticker-track { animation-play-state: paused; }
@keyframes gc-tick { from { transform: translateX(0); } to { transform: translateX(-50%); } }
.gc-ticker .ti {
  color: #98a0b3 !important;
  font-family: var(--gc-mono); font-size: 11.5px; letter-spacing: .5px;
  padding: 0 20px;
}
.gc-ticker .ti b { color: var(--gc-gold) !important; margin-right: 8px; font-weight: 700; }
.gc-ticker .ti strong { color: #e8eaf0 !important; font-weight: 600; }

/* 顶栏 */
.gc-nav {
  background: rgba(13,15,19,.86); margin: 0 -1.25rem;
  padding: 0 max(1.25rem, calc((100% - 1100px)/2));
  border-bottom: 1px solid var(--gc-line);
  height: 62px; display: flex; align-items: center;
  backdrop-filter: blur(12px);
}
.gc-nav-inner { display: flex; align-items: center; gap: 24px; width: 100%; }
.gc-logo { display: flex; align-items: center; gap: 10px; }
.gc-logo-mark {
  width: 12px; height: 12px; border-radius: 4px; background: var(--gc-gold);
  box-shadow: 0 0 10px rgba(232,194,104,.4);
}
.gc-logo-word { font-size: 16px; font-weight: 800; letter-spacing: .5px; color: #fff !important; }
.gc-logo-word span { color: var(--gc-gold) !important; }
.gc-logo-sub {
  font-family: var(--gc-mono); font-size: 10px; font-weight: 600; letter-spacing: 2.5px;
  color: #98a0b3 !important; border: 1px solid var(--gc-line-hi); padding: 3px 9px;
  border-radius: 99px;
}
.gc-nav .spacer { margin-right: auto; }
.gc-nav a { color: #98a0b3; text-decoration: none; font-size: 13px; font-weight: 500; padding: 7px 12px; border-radius: 8px; }
.gc-nav a:hover { color: #e8eaf0; background: rgba(255,255,255,.05); }
.gc-install {
  color: #e8eaf0 !important; font-size: 13px; font-weight: 600;
  padding: 8px 16px; border-radius: 10px;
  background: rgba(255,255,255,.06); border: 1px solid var(--gc-line-hi);
}
.gc-install span { color: #e8eaf0 !important; }
.gc-install:hover { background: rgba(255,255,255,.12); color: #fff !important; }

/* 侧边水印 */
.gc-rail {
  position: fixed; top: 50%; transform: translateY(-50%); z-index: 5;
  writing-mode: vertical-rl; font-family: var(--gc-mono);
  font-size: 10px; letter-spacing: 6px; color: #1f232c;
  user-select: none; pointer-events: none; text-transform: uppercase;
}
.gc-rail .volt { color: var(--gc-gold); opacity: .5; }
.gc-rail.left { left: calc(50% - 550px - 58px); }
.gc-rail.right { right: calc(50% - 550px - 58px); }
@media (max-width: 1340px) { .gc-rail { display: none; } }

/* 标题区 */
.gc-overline {
  font-family: var(--gc-mono); font-size: 11px; letter-spacing: 3px;
  color: #6b7285 !important; text-transform: uppercase; margin: 20px 0 8px;
}
.gc-h1 {
  font-size: 30px; font-weight: 800; letter-spacing: .5px;
  line-height: 1.15; color: #fff !important;
}
.gc-h1 em { font-style: normal; color: var(--gc-gold); }
.gc-meta {
  font-family: var(--gc-mono); font-size: 12px; color: #98a0b3;
  display: flex; align-items: center; gap: 10px;
}
.gc-meta .dot {
  width: 7px; height: 7px; border-radius: 50%; background: var(--gc-up);
  box-shadow: 0 0 8px rgba(111,220,140,.7); animation: gc-pulse 1.8s infinite;
}
@keyframes gc-pulse { 50% { opacity: .3; } }

/* 刷新按钮（克制的描边胶囊） */
.stButton > button {
  width: 100%; border-radius: 10px; padding: 10px 0;
  background: rgba(255,255,255,.05); color: #e8eaf0;
  border: 1px solid var(--gc-line-hi);
  font-size: 12.5px; font-weight: 600; letter-spacing: .5px;
  transition: all .15s;
}
.stButton > button:hover {
  background: rgba(255,255,255,.12); color: #fff;
}
.stButton > button p { font-size: 12.5px; font-weight: 600; letter-spacing: .5px; color: #e8eaf0 !important; }

/* Tab（分段控件） */
[data-baseweb="tab-list"] {
  display: inline-flex; gap: 2px; border-bottom: none;
  background: rgba(255,255,255,.04); border: 1px solid var(--gc-line);
  border-radius: 12px; padding: 4px;
}
[role="tab"] {
  color: #98a0b3; border-radius: 9px; padding: 9px 18px;
  font-weight: 600;
}
[role="tab"] p { font-size: 13.5px; font-weight: 600; color: #98a0b3 !important; }
[role="tab"]:hover { background: rgba(255,255,255,.05); }
[role="tab"]:hover p { color: #e8eaf0 !important; }
[role="tab"][aria-selected="true"] { background: #f2f3f7; }
[role="tab"][aria-selected="true"] p { color: #101216 !important; font-weight: 700; }
[data-baseweb="tab-highlight"] { display: none !important; }

/* 榜单面板 */
.gc-panel { margin-top: 16px; }

.gc-section {
  color: #fff; font-size: 19px; font-weight: 700; letter-spacing: .3px;
  padding: 8px 0 16px; display: flex; align-items: baseline; gap: 12px;
}
.gc-section::before {
  content: ""; width: 6px; height: 18px; align-self: center;
  background: var(--gc-gold); border-radius: 3px;
}
.gc-section .sub { color: #6b7285 !important; font-size: 11.5px; font-family: var(--gc-mono); letter-spacing: 1.5px; font-weight: 400; }

/* 卡片网格 */
.gc-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(196px, 1fr)); gap: 16px;
}
.gc-card {
  position: relative; text-decoration: none !important; display: block; border-radius: 14px;
  background: var(--gc-card);
  border: 1px solid var(--gc-line);
  overflow: hidden;
  transition: transform .2s, border-color .2s, box-shadow .2s;
}
.gc-card:hover {
  transform: translateY(-4px); border-color: var(--gc-line-hi);
  box-shadow: 0 16px 40px rgba(0,0,0,.45);
}
.gc-card img {
  width: 100%; aspect-ratio: 460/215; display: block; object-fit: cover;
  border-bottom: 1px solid var(--gc-line);
  transition: filter .2s;
}
.gc-card:hover img { filter: brightness(1.08); }
.gc-card .name {
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  color: #e8eaf0 !important; font-size: 13.5px; font-weight: 600; line-height: 1.4;
  padding: 11px 13px 2px; height: 42px; overflow: hidden;
}
.gc-card:hover .name { color: #fff !important; }
.gc-card .price-row { display: flex; align-items: center; gap: 8px; padding: 8px 13px 13px; min-height: 34px; }
.gc-rank {
  position: absolute; top: 10px; left: 10px; z-index: 1;
  font-family: var(--gc-mono); font-size: 13px; font-weight: 800;
  color: rgba(255,255,255,.95);
  background: rgba(10,11,15,.62); backdrop-filter: blur(6px);
  border: 1px solid rgba(255,255,255,.14);
  padding: 2px 10px; border-radius: 8px;
}
.gc-grid .gc-card:nth-child(1) .gc-rank { color: var(--gc-gold); border-color: rgba(232,194,104,.65); }
.gc-grid .gc-card:nth-child(2) .gc-rank { color: #d7e0f0; border-color: rgba(215,224,240,.55); }
.gc-grid .gc-card:nth-child(3) .gc-rank { color: #e89a6b; border-color: rgba(232,154,107,.55); }

/* 折扣标签 */
.gc-tag {
  display: inline-flex; align-items: stretch; border-radius: 7px; overflow: hidden;
  background: rgba(111,220,140,.13); border: 1px solid rgba(111,220,140,.3);
}
.gc-tag .pct {
  color: var(--gc-deal) !important; font-weight: 700; font-size: 12.5px; padding: 3px 7px;
  font-family: var(--gc-mono);
}
.gc-tag .final {
  color: #c9f2d4 !important; font-size: 12.5px; padding: 3px 8px; font-weight: 600;
  font-family: var(--gc-mono);
}
.gc-price { color: #e8eaf0 !important; font-size: 13px; font-family: var(--gc-mono); font-weight: 600; }
.gc-price.free { color: var(--gc-up) !important; }
.gc-strike { color: #6b7285 !important; text-decoration: line-through; font-size: 12px; font-family: var(--gc-mono); }

/* 最热游玩行 */
.gc-thead, .gc-row {
  display: grid;
  grid-template-columns: 56px 156px minmax(0,1fr) 110px 110px 70px;
  gap: 16px; align-items: center; padding: 8px 6px;
}
.gc-thead {
  color: #6b7285 !important; font-size: 11px; font-weight: 600; letter-spacing: 2px;
  font-family: var(--gc-mono); text-transform: uppercase;
  border-bottom: 1px solid var(--gc-line); padding-bottom: 10px; margin-bottom: 4px;
}
.gc-thead .r { text-align: right; }
.gc-thead .ctr { text-align: center; }
.gc-row {
  border-radius: 12px; text-decoration: none !important;
  border-bottom: 1px solid rgba(255,255,255,.035);
}
.gc-row:hover { background: rgba(255,255,255,.04); }
.gc-row .rank {
  font-family: var(--gc-mono); font-size: 20px; font-weight: 800;
  color: #333a49 !important; text-align: center;
}
.gc-row:nth-of-type(1) .rank, .gc-row:nth-of-type(2) .rank, .gc-row:nth-of-type(3) .rank { font-size: 22px; }
.gc-row:nth-of-type(1) .rank { color: var(--gc-gold) !important; }
.gc-row:nth-of-type(2) .rank { color: #d7e0f0 !important; }
.gc-row:nth-of-type(3) .rank { color: #e89a6b !important; }
.gc-row img {
  width: 156px; aspect-ratio: 460/215; object-fit: cover; border-radius: 9px; display: block;
  border: 1px solid var(--gc-line);
}
.gc-row .gname { color: #fff !important; font-size: 14.5px; font-weight: 600; line-height: 1.3; }
.gc-row:hover .gname { color: var(--gc-gold) !important; }
.gc-row .genre { color: #98a0b3 !important; font-size: 11.5px; margin-top: 3px; }
.gc-row .genre .p { color: #e8eaf0 !important; margin-left: 8px; font-family: var(--gc-mono); font-weight: 600; }
.gc-row .pnum {
  color: #fff !important; font-size: 17px; font-weight: 700; text-align: right;
  font-family: var(--gc-mono); font-variant-numeric: tabular-nums;
}
.gc-row .peak {
  color: #98a0b3 !important; font-size: 13px; text-align: right;
  font-family: var(--gc-mono); font-variant-numeric: tabular-nums;
}
.gc-row .delta { text-align: center; font-size: 12.5px; font-weight: 700; font-family: var(--gc-mono); }
.gc-row .delta.up { color: var(--gc-up) !important; }
.gc-row .delta.down { color: var(--gc-down) !important; }
.gc-row .delta.same { color: #6b7285 !important; font-weight: 400; }
.gc-row .delta .new {
  display: inline-block; background: rgba(232,194,104,.12);
  border: 1px solid rgba(232,194,104,.45); color: var(--gc-gold) !important;
  font-size: 10px; padding: 2px 8px; border-radius: 99px; letter-spacing: 1px;
}

/* 价格类榜单的横排（无在线数据列） */
.gc-thead.simple { grid-template-columns: 56px 156px minmax(0,1fr) 240px; }
.gc-thead.simple .r { text-align: right; }
.gc-row.simple { grid-template-columns: 56px 156px minmax(0,1fr) 240px; }
.gc-row.simple .price-col {
  display: flex; justify-content: flex-end; align-items: center; gap: 8px;
}
.gc-row.simple .price-col .gc-price { font-size: 14px; }

/* 空状态 */
.gc-empty { padding: 52px 0 42px; text-align: center; color: #98a0b5; }
.gc-empty .ghost {
  font-family: var(--gc-mono); font-size: 38px; font-weight: 800; color: #262b36; line-height: 1;
}
.gc-empty .etitle { color: #e8eaf0; font-weight: 700; margin: 14px 0 6px; }
.gc-empty .esub { font-size: 12.5px; font-family: var(--gc-mono); color: #6b7285; }

.gc-meta-line {
  font-family: var(--gc-mono); font-size: 12px; color: #98a0b5;
  display: flex; align-items: center; gap: 10px; padding: 2px 2px 8px;
}
.gc-meta-line .dot {
  width: 7px; height: 7px; border-radius: 50%; background: var(--gc-up);
  box-shadow: 0 0 8px rgba(111,220,140,.7); animation: gc-pulse 1.8s infinite;
}

.gc-footer {
  color: #6b7285 !important; font-size: 12.5px; line-height: 1.8;
  border-top: 1px solid var(--gc-line); padding-top: 14px; margin-top: 22px;
}

@media (max-width: 860px) {
  .gc-thead { display: none; }
  .gc-row, .gc-row.simple { grid-template-columns: 34px 116px minmax(0,1fr) auto; gap: 11px; }
  .gc-row img { width: 116px; }
  .gc-row .peak, .gc-row .delta { display: none; }
  .gc-row .pnum { font-size: 15px; }
  .gc-nav a:not(.gc-install) { display: none; }
  [data-baseweb="tab-list"] { flex-wrap: wrap; }
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


def row_html(it, stats):
    if not stats:
        # 价格类榜单：# | 封面 | 游戏 | 价格
        return (f'<a class="gc-row simple" href="{_esc(it["url"])}" target="_blank">'
                f'<span class="rank">#{it["rank"]}</span>'
                f'<img src="{_esc(it["image"])}" loading="lazy" onerror="this.style.visibility=\'hidden\'">'
                f'<span><div class="gname">{_esc(it["name"])}</div></span>'
                f'<span class="price-col">{price_row_html(it.get("price"))}</span></a>')
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


def rows_html(items, title, sub, stats=False):
    if not items:
        body = EMPTY_HTML
        return (f'<div class="gc-panel"><div class="gc-section">{title}'
                f'<span class="sub">{sub}</span></div>{body}</div>')
    if stats:
        head = ('<div class="gc-thead"><span class="ctr">#</span><span>游戏</span>'
                '<span></span><span class="r">当前在线</span><span class="r">今日峰值</span>'
                '<span class="ctr">周变化</span></div>')
    else:
        head = ('<div class="gc-thead simple"><span class="ctr">#</span><span>游戏</span>'
                '<span></span><span class="r">价格</span></div>')
    body = "".join(row_html(it, stats) for it in items)
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
        parts.append(f"热销 #{i['rank']} <strong>{i['name']}</strong> {i['price']['final'] or ''}")
    for i in load_specials()[:2]:
        if i["price"]["pct"]:
            parts.append(f"特惠 {i['price']['pct']}% <strong>{i['name']}</strong> {i['price']['final']}")
    ftk = load_free_to_keep()
    for i in ftk[:3]:
        parts.append(f"限时免费入库 <strong>{i['name']}</strong>（原价 {i['price']['original']}）")
    if not ftk:
        parts.append("限时免费入库 · 当前无活动，周末再多来看看")
    seq = "".join(f'<span class="ti"><b>▮</b>{p}</span>' for p in parts)
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
        updated_line() + rows_html(load_top_sellers(), "热门畅销商品", "TOP 50 · BY UNITS SOLD"),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_most_played():
    st.markdown(
        updated_line() + rows_html(load_most_played(), "最热游玩游戏", "TOP 100 · BY CURRENT PLAYERS", stats=True),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_free_to_keep():
    st.markdown(
        updated_line() + rows_html(load_free_to_keep(), "限时免费入库", "FREE TO KEEP · 原价付费，现在免费领"),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_specials():
    st.markdown(
        updated_line() + rows_html(load_specials(), "特惠专区", "TOP 50 · HOT DEALS"),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_new():
    st.markdown(
        updated_line() + rows_html(load_new_releases(), "新品上架", "TOP 30 · NEW RELEASES"),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_free():
    st.markdown(
        updated_line() + rows_html(load_free_games(), "免费游戏", "TOP 50 · FREE TO PLAY"),
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
