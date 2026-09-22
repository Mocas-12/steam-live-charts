"""Steam 实时游戏榜单 —— Streamlit Cloud 入口（Neon Arena 主题）。

与本地 FastAPI 版（app.py + static/）共用数据层 steamdata.py；
st.cache_data 控制上游请求频率，st.fragment(run_every=60s) 让榜单原地自动刷新。
"""

import html as htmllib
import time

import streamlit as st

import steamdata

st.set_page_config(
    page_title="GameCharts · 实时游戏榜单",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------- Neon Arena 主题 ----------

CSS = """
<style>
/* 隐藏 Streamlit 自带框架 */
[data-testid="stHeader"] { display: none; }
#MainMenu, footer, [data-testid="stFooter"] { visibility: hidden; }
[data-testid="stStatusWidget"], [data-testid="stToolbar"] { display: none; }
.block-container { padding: 1.1rem 1rem 2rem; max-width: 1060px; margin: 0 auto; }
section[data-testid="stVerticalBlock"] { gap: .45rem; }

/* 页面底色：霓虹辉光 + 网格 */
.stApp {
  background:
    radial-gradient(900px 420px at 8% -8%, rgba(124,92,255,.16), transparent 60%),
    radial-gradient(900px 460px at 96% 4%, rgba(0,229,255,.10), transparent 60%),
    linear-gradient(rgba(124,140,255,.028) 1px, transparent 1px),
    linear-gradient(90deg, rgba(124,140,255,.028) 1px, transparent 1px),
    linear-gradient(180deg, #0b101c 0%, #05070d 420px) fixed;
}
body, .stApp, p, span {
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  color: #dfe6f5;
}

:root {
  --gc-line: rgba(124,140,255,.16);
  --gc-line-hi: rgba(124,140,255,.45);
  --gc-acc1: #7c5cff;
  --gc-acc2: #00e5ff;
  --gc-panel: rgba(13,18,32,.78);
  --gc-muted: #7c88a3;
  --gc-dim: #4b5670;
  --gc-green: #58f08a;
  --gc-mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
}

a { color: #6fdcff; }
.stMarkdown a, .stMarkdown a * { text-decoration: none !important; }

/* 顶栏 */
.gc-nav {
  background: rgba(6,9,16,.85); margin: -1.1rem -1rem 0;
  padding: 0 max(1rem, calc((100% - 1060px)/2));
  border-bottom: 1px solid var(--gc-line);
  backdrop-filter: blur(10px);
}
.gc-nav-inner { display: flex; align-items: center; gap: 18px; height: 56px; }
.gc-logo { display: flex; align-items: center; gap: 10px; }
.gc-logo-mark {
  width: 24px; height: 24px; border-radius: 7px;
  background: linear-gradient(135deg, var(--gc-acc1), var(--gc-acc2));
  box-shadow: 0 0 14px rgba(124,92,255,.55);
}
.gc-logo-word { font-size: 16px; font-weight: 800; letter-spacing: 3px; color: #fff; }
.gc-logo-word span { color: var(--gc-acc2); }
.gc-logo-sub {
  font-size: 10px; font-weight: 600; letter-spacing: 2px; color: var(--gc-muted);
  border: 1px solid var(--gc-line); padding: 3px 8px; border-radius: 3px;
}
.gc-nav .spacer { margin-right: auto; }
.gc-nav a { color: #7c88a3; text-decoration: none; font-size: 12px; font-weight: 700; letter-spacing: 2px; padding: 6px 10px; border-radius: 3px; }
.gc-nav a:hover { color: #fff; background: rgba(124,92,255,.12); }
.gc-install {
  color: #051018 !important; font-size: 12px; font-weight: 800; letter-spacing: 1px;
  padding: 8px 14px; border-radius: 4px;
  background: linear-gradient(90deg, var(--gc-acc1), var(--gc-acc2));
  box-shadow: 0 0 16px rgba(0,229,255,.25);
}

/* 标题区 */
.gc-overline {
  font-family: var(--gc-mono); font-size: 11px; font-weight: 700; letter-spacing: 4px;
  color: var(--gc-acc2); text-transform: uppercase; margin: 14px 0 4px;
}
.gc-h1 {
  font-size: 33px; font-weight: 900; letter-spacing: 1px; line-height: 1.15;
  background: linear-gradient(90deg, #fff 20%, #b9a8ff 55%, #6fdcff);
  -webkit-background-clip: text; background-clip: text; color: transparent !important;
}
.gc-meta {
  font-family: var(--gc-mono); font-size: 12px; color: var(--gc-muted);
  display: flex; align-items: center; gap: 8px;
}
.gc-meta .dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--gc-acc2);
  box-shadow: 0 0 8px var(--gc-acc2); animation: gc-pulse 1.6s infinite;
}
@keyframes gc-pulse { 50% { opacity: .25; } }

/* 刷新按钮（对齐 + 霓虹描边） */
.stButton > button {
  width: 100%; border-radius: 4px; padding: 9px 0;
  background: linear-gradient(135deg, rgba(124,92,255,.22), rgba(0,229,255,.14));
  border: 1px solid var(--gc-line-hi); color: #dfe6f5;
  font-size: 12.5px; font-weight: 700; letter-spacing: 1px;
  transition: all .15s;
}
.stButton > button:hover {
  border-color: var(--gc-acc1); color: #fff;
  box-shadow: 0 0 14px rgba(124,92,255,.45); filter: brightness(1.2);
}
.stButton > button p { font-size: 12.5px; font-weight: 700; letter-spacing: 1px; }

/* Tab（baseweb 覆盖） */
[data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--gc-line); }
[role="tab"] {
  color: #7c88a3; border-radius: 6px 6px 0 0; padding: 10px 18px 9px;
  border: 1px solid transparent; border-bottom: none; font-weight: 700;
}
[role="tab"] p { font-size: 14px; font-weight: 700; letter-spacing: 1px; }
[role="tab"]:hover p { color: #fff !important; }
[role="tab"][aria-selected="true"] { background: var(--gc-panel); border-color: var(--gc-line); border-bottom-color: transparent; }
[role="tab"][aria-selected="true"] p { color: #fff !important; }
[data-baseweb="tab-highlight"] {
  height: 2px !important;
  background: linear-gradient(90deg, var(--gc-acc1), var(--gc-acc2)) !important;
  box-shadow: 0 0 10px rgba(124,92,255,.6);
}

/* 榜单面板 */
.gc-panel {
  background: var(--gc-panel);
  border: 1px solid var(--gc-line); border-top: 1px solid rgba(124,140,255,.3);
  border-radius: 0 10px 10px 10px;
  padding: 4px 18px 18px;
  box-shadow: 0 18px 50px rgba(0,0,0,.45);
}
.gc-section {
  color: #fff; font-size: 16px; font-weight: 800; letter-spacing: 1px;
  padding: 15px 0 11px; display: flex; align-items: baseline; gap: 10px;
}
.gc-section::before {
  content: ""; width: 4px; height: 16px; align-self: center;
  background: linear-gradient(180deg, var(--gc-acc1), var(--gc-acc2));
  border-radius: 2px; box-shadow: 0 0 8px rgba(124,92,255,.7);
}
.gc-section .sub { color: #7c88a3; font-size: 11px; font-family: var(--gc-mono); letter-spacing: 1px; }

/* 卡片网格 */
.gc-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(178px, 1fr)); gap: 13px;
}
.gc-card {
  position: relative; text-decoration: none; display: block; border-radius: 8px;
  background: linear-gradient(165deg, rgba(23,31,54,.92), rgba(9,13,24,.92));
  border: 1px solid var(--gc-line);
  overflow: hidden;
  transition: transform .18s, border-color .18s, box-shadow .18s;
}
.gc-card:hover {
  transform: translateY(-3px); border-color: var(--gc-line-hi);
  box-shadow: 0 10px 30px rgba(0,0,0,.5), 0 0 22px rgba(124,92,255,.22);
}
.gc-card img { width: 100%; aspect-ratio: 460/215; display: block; object-fit: cover; }
.gc-card .name {
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  color: #dfe6f5 !important; font-size: 13px; font-weight: 600; line-height: 1.35;
  padding: 9px 11px 2px; height: 38px; overflow: hidden;
}
.gc-card:hover .name { color: #fff !important; }
.gc-card .price-row { display: flex; align-items: center; gap: 7px; padding: 7px 11px 11px; min-height: 32px; }
.gc-rank {
  position: absolute; top: 7px; left: 7px; z-index: 1;
  font-family: var(--gc-mono); font-size: 12px; font-weight: 800;
  color: #dfe6f5; background: rgba(5,8,16,.82);
  border: 1px solid var(--gc-line-hi);
  padding: 1px 9px; border-radius: 3px;
}
.gc-grid .gc-card:nth-child(1) .gc-rank {
  color: #1a1204; background: linear-gradient(135deg, #ffe18a, #ffcf5c);
  border-color: #ffe18a; box-shadow: 0 0 12px rgba(255,207,92,.45);
}
.gc-grid .gc-card:nth-child(2) .gc-rank {
  color: #10141d; background: linear-gradient(135deg, #eef3fb, #d7e0f0);
  border-color: #eef3fb;
}
.gc-grid .gc-card:nth-child(3) .gc-rank {
  color: #1c0f05; background: linear-gradient(135deg, #ffb98a, #e89a6b);
  border-color: #ffb98a;
}

/* 折扣标签 */
.gc-tag {
  display: inline-flex; align-items: stretch; border-radius: 4px; overflow: hidden;
  border: 1px solid rgba(88,240,138,.35); background: rgba(88,240,138,.10);
}
.gc-tag .pct {
  color: #58f08a !important; font-weight: 800; font-size: 13px; padding: 3px 7px;
  font-family: var(--gc-mono);
}
.gc-tag .final {
  color: #c9ffdd !important; font-size: 13px; padding: 3px 8px; font-weight: 600;
  font-family: var(--gc-mono);
}
.gc-price { color: #dfe6f5 !important; font-size: 13px; font-family: var(--gc-mono); font-weight: 600; }
.gc-strike { color: #4b5670 !important; text-decoration: line-through; font-size: 12px; font-family: var(--gc-mono); }

/* 最热游玩行 */
.gc-thead, .gc-row {
  display: grid;
  grid-template-columns: 46px 150px minmax(0,1fr) 105px 105px 66px;
  gap: 14px; align-items: center; padding: 7px 4px;
}
.gc-thead {
  color: #4b5670; font-size: 11px; font-weight: 700; letter-spacing: 1.5px;
  font-family: var(--gc-mono); text-transform: uppercase;
  border-bottom: 1px solid var(--gc-line); padding-bottom: 9px; margin-bottom: 2px;
}
.gc-thead .r, .gc-thead .ctr { }
.gc-thead .r { text-align: right; }
.gc-thead .ctr { text-align: center; }
.gc-row {
  border-bottom: 1px solid rgba(124,140,255,.07);
  border-radius: 6px; text-decoration: none !important;
}
.gc-row:hover { background: rgba(124,92,255,.07); }
.gc-row .rank {
  font-family: var(--gc-mono); font-size: 17px; font-weight: 800; font-style: italic;
  color: #4b5670 !important; text-align: center;
}
.gc-row img {
  width: 150px; aspect-ratio: 460/215; object-fit: cover; border-radius: 5px; display: block;
  border: 1px solid rgba(124,140,255,.14);
}
.gc-row .gname { color: #fff !important; font-size: 14.5px; font-weight: 600; line-height: 1.3; }
.gc-row:hover .gname { color: #00e5ff !important; }
.gc-row .genre { color: #7c88a3 !important; font-size: 11.5px; margin-top: 3px; }
.gc-row .genre .p { color: #58f08a !important; margin-left: 8px; font-family: var(--gc-mono); }
.gc-row .pnum {
  color: #fff !important; font-size: 18px; font-weight: 700; text-align: right;
  font-family: var(--gc-mono); font-variant-numeric: tabular-nums;
  text-shadow: 0 0 12px rgba(0,229,255,.25);
}
.gc-row .peak {
  color: #7c88a3 !important; font-size: 13.5px; text-align: right;
  font-family: var(--gc-mono); font-variant-numeric: tabular-nums;
}
.gc-row .delta { text-align: center; font-size: 13px; font-weight: 800; font-family: var(--gc-mono); }
.gc-row .delta.up { color: #58f08a !important; }
.gc-row .delta.down { color: #ff5d73 !important; }
.gc-row .delta.same { color: #4b5670 !important; font-weight: 400; }
.gc-row .delta .new {
  display: inline-block; background: rgba(124,92,255,.16);
  border: 1px solid rgba(124,92,255,.5); color: #c9b8ff !important;
  font-size: 10px; padding: 2px 7px; border-radius: 3px; letter-spacing: 1px;
}

.gc-footer {
  color: #4b5670 !important; font-size: 12px; line-height: 1.7;
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
  <a class="gc-install" href="https://store.steampowered.com/about/" target="_blank">安装 STEAM</a>
</div></div>
""",
    unsafe_allow_html=True,
)

# ---------- 头部（列内垂直居中，修按钮对齐） ----------

head_l, head_r = st.columns([4, 1], vertical_alignment="center")
with head_l:
    st.markdown('<div class="gc-overline">// Game Charts · Realtime Arena</div>', unsafe_allow_html=True)
    st.markdown('<div class="gc-h1">实时游戏榜单</div>', unsafe_allow_html=True)
with head_r:
    if st.button("↻ 立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ---------- 数据 ----------


@st.cache_data(ttl=120, show_spinner="正在从 Steam 拉取热销榜…")
def load_top_sellers():
    items = [it for it in steamdata.fetch_search(False) if it["price"]["final"]]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


@st.cache_data(ttl=120, show_spinner="正在从 Steam 拉取特惠榜…")
def load_specials():
    items = [it for it in steamdata.fetch_search(True) if it["price"]["final"]]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


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
    return f'<span class="gc-price">{_esc(p["final"])}</span>'


def card_html(it):
    return (f'<a class="gc-card" href="{_esc(it["url"])}" target="_blank">'
            f'<span class="gc-rank">#{it["rank"]}</span>'
            f'<img src="{_esc(it["image"])}" loading="lazy" onerror="this.style.visibility=\'hidden\'">'
            f'<span class="name">{_esc(it["name"])}</span>'
            f'<span class="price-row">{price_row_html(it["price"])}</span></a>')


def grid_html(items, title, sub):
    body = "".join(card_html(it) for it in items)
    return (f'<div class="gc-panel"><div class="gc-section">{title}'
            f'<span class="sub">{sub}</span></div>'
            f'<div class="gc-grid">{body}</div></div>')


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
    return (f'<div class="gc-meta" style="padding:2px 2px 8px"><span class="dot"></span>'
            f'更新于 {t} · 每 60 秒自动刷新</div>')


# ---------- 五个榜单（fragment 每 60 秒原地刷新，不丢 tab 状态） ----------

tab_sellers, tab_played, tab_specials, tab_new, tab_free = st.tabs(
    ["热销商品", "最热游玩", "特惠专区", "新品上架", "免费游戏"]
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
