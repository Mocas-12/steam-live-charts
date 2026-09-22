"""Steam 实时游戏榜单 —— Streamlit Cloud 入口。

与本地 FastAPI 版（app.py + static/）共用数据层 steamdata.py；
st.cache_data 控制上游请求频率，st.fragment(run_every=60s) 让榜单原地自动刷新。
"""

import html as htmllib
import time

import streamlit as st

import steamdata

st.set_page_config(
    page_title="Steam 实时游戏榜单",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------- Steam 风格主题 ----------

CSS = """
<style>
/* 隐藏 Streamlit 自带框架 */
[data-testid="stHeader"] { display: none; }
#MainMenu, footer, [data-testid="stFooter"] { visibility: hidden; }
[data-testid="stStatusWidget"], [data-testid="stToolbar"] { display: none; }
.block-container { padding: 1.1rem 1rem 2rem; max-width: 1020px; margin: 0 auto; }
section[data-testid="stVerticalBlock"] { gap: .45rem; }

/* 页面底色：Steam 商店式渐变 */
.stApp {
  background:
    radial-gradient(1100px 380px at 50% -120px, rgba(42,71,94,.55), transparent 70%),
    linear-gradient(180deg, #14344b 0, #1b2838 360px) fixed;
}
body, .stApp, p, span {
  font-family: "Motiva Sans", "Segoe UI", Arial, "Microsoft YaHei", sans-serif;
  color: #c7d5e0;
}
a { color: #66c0f4; }
.stMarkdown a, .stMarkdown a * { text-decoration: none !important; }
.steam-card .name { color: #fff !important; }
.steam-price { color: #fff !important; }
.strike { color: #55677d !important; }
.steam-tag .pct { color: #beee11 !important; }
.steam-tag .final { color: #d2e885 !important; }
.steam-row .gname, .steam-row .pnum { color: #fff !important; }

/* 顶栏 */
.steam-nav {
  background: #171a21; margin: -1.1rem -1rem 0; padding: 0 max(1rem, calc((100% - 1020px)/2));
  box-shadow: 0 1px 0 rgba(0,0,0,.4);
}
.steam-nav-inner { display: flex; align-items: center; gap: 24px; height: 56px; }
.steam-logo { color: #fff; font-size: 24px; font-weight: 700; letter-spacing: 1.5px; }
.steam-logo sup { font-size: 9px; font-weight: 400; color: #8f98a0; }
.steam-logo .sub { font-size: 12px; font-weight: 400; letter-spacing: 0; color: #66c0f4; margin-left: 8px; }
.steam-nav a { color: #b8b6b4; text-decoration: none; font-size: 13px; font-weight: 700; padding: 6px 10px; border-radius: 3px; }
.steam-nav a:hover { color: #fff; background: rgba(255,255,255,.06); }
.steam-nav .spacer { margin-right: auto; }
.steam-install {
  color: #d2efa9 !important; font-size: 12px; border-radius: 2px;
  background: linear-gradient(to right, #75b022 5%, #588a1b 95%);
}
.steam-install:hover { color: #fff !important; background: linear-gradient(to right, #8ed629 5%, #6aa621 95%); }

/* 标题区 */
.steam-h1 { color: #fff; font-size: 27px; font-weight: 400; letter-spacing: .5px; margin: 14px 0 2px; }
.steam-meta { color: #8f98a0; font-size: 13px; }
.steam-meta .dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#75b022;
  box-shadow: 0 0 6px #75b022; margin-right: 6px; animation: pulse 2s infinite; }
@keyframes pulse { 50% { opacity: .4; } }

/* Tab（baseweb 覆盖） */
[data-baseweb="tab-list"] { gap: 3px; border-bottom: none; }
[data-baseweb="tab"] { color: #8f98a0; border-radius: 3px 3px 0 0; padding: 9px 20px; }
[data-baseweb="tab"] p { font-size: 15px; font-weight: 400; }
[data-baseweb="tab"]:hover p { color: #fff !important; }
[data-baseweb="tab"][aria-selected="true"] { background: #16202d; }
[data-baseweb="tab"][aria-selected="true"] p { color: #fff !important; font-weight: 700; }
[data-baseweb="tab-highlight"] { background: transparent !important; }

/* 榜单容器 */
.steam-panel {
  background: #16202d; border-radius: 0 4px 4px 4px; padding: 4px 18px 16px;
  box-shadow: 0 0 12px rgba(0,0,0,.35);
}
.steam-section { color: #fff; font-size: 16px; padding: 12px 0 10px; }
.steam-section .sub { color: #8f98a0; font-size: 12px; margin-left: 10px; }

/* 卡片网格（热销 / 特惠） */
.steam-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(176px, 1fr)); gap: 12px; }
.steam-card {
  position: relative; background: rgba(0,0,0,.25); border-radius: 3px; overflow: hidden;
  text-decoration: none; display: block; transition: background .18s, transform .18s;
}
.steam-card:hover { background: rgba(103,193,245,.08); transform: translateY(-2px); }
.steam-card img { width: 100%; aspect-ratio: 231/87; object-fit: cover; display: block; }
.steam-card .name {
  color: #fff; font-size: 13px; line-height: 1.35; padding: 7px 10px 2px; height: 36px; overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.steam-card .price-row { display: flex; align-items: center; gap: 7px; padding: 6px 10px 10px; min-height: 32px; }
.steam-rank {
  position: absolute; top: 6px; left: 6px; background: rgba(0,0,0,.72); color: #fff;
  font-size: 12px; font-weight: 700; padding: 1px 8px; border-radius: 2px; z-index: 1;
}

/* 折扣标签 */
.steam-tag { display: inline-flex; background: #4c6b22; border-radius: 2px; }
.steam-tag .pct { color: #beee11; font-weight: 700; font-size: 13px; padding: 3px 6px; }
.steam-tag .final { color: #d2e885; font-size: 13px; padding: 3px 7px; }
.steam-price { color: #fff; font-size: 13px; }
.strike { color: #55677d; text-decoration: line-through; font-size: 12px; }

/* 最热游玩行 */
.steam-thead, .steam-row {
  display: grid; grid-template-columns: 44px 150px minmax(0,1fr) 105px 105px 66px;
  gap: 14px; align-items: center; padding: 7px 0;
}
.steam-thead {
  color: #55677d; font-size: 11px; text-transform: uppercase; letter-spacing: .8px;
  border-bottom: 1px solid rgba(255,255,255,.08); padding-bottom: 7px;
}
.steam-thead .r, .steam-thead .c { text-align: right; }
.steam-thead .ctr { text-align: center; }
.steam-row { border-bottom: 1px solid rgba(255,255,255,.05); }
.steam-row:hover { background: rgba(103,193,245,.07); }
.steam-row .rank { color: #55677d; font-size: 17px; font-weight: 700; text-align: center; }
.steam-row img { width: 150px; aspect-ratio: 460/215; object-fit: cover; border-radius: 2px; display: block; }
.steam-row .gname { color: #fff; font-size: 14.5px; line-height: 1.3; }
.steam-row:hover .gname { color: #66c0f4; }
.steam-row .genre { color: #8f98a0; font-size: 11.5px; margin-top: 3px; }
.steam-row .genre .p { color: #d2e885; margin-left: 8px; }
.steam-row .genre .p.pct { color: #beee11; }
.steam-row .pnum { color: #fff; font-size: 18px; font-weight: 500; text-align: right; font-variant-numeric: tabular-nums; }
.steam-row .peak { color: #8f98a0; font-size: 14px; text-align: right; font-variant-numeric: tabular-nums; }
.steam-row .delta { text-align: center; font-size: 13px; font-weight: 700; }
.steam-row .delta.up { color: #75b022; }
.steam-row .delta.down { color: #d0483e; }
.steam-row .delta.same { color: #55677d; font-weight: 400; }
.steam-row .delta .new {
  background: #4c6b22; color: #beee11; font-size: 10px; padding: 2px 6px; border-radius: 2px; font-weight: 700;
}

.steam-footer { color: #5c6672; font-size: 12px; line-height: 1.7; border-top: 1px solid rgba(255,255,255,.08); padding-top: 12px; margin-top: 18px; }

@media (max-width: 860px) {
  .steam-thead { display: none; }
  .steam-row { grid-template-columns: 34px 110px minmax(0,1fr) auto; gap: 10px; }
  .steam-row img { width: 110px; }
  .steam-row .peak, .steam-row .delta { display: none; }
  .steam-row .pnum { font-size: 15px; }
  .steam-nav a:not(.steam-install) { display: none; }
}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)

st.markdown(
    """
<div class="steam-nav"><div class="steam-nav-inner">
  <span class="steam-logo">STEAM<sup>®</sup><span class="sub">实时榜单</span></span>
  <span class="spacer"></span>
  <a href="https://store.steampowered.com/" target="_blank">商店</a>
  <a href="https://steamcommunity.com/" target="_blank">社区</a>
  <a href="https://store.steampowered.com/about/" target="_blank">关于</a>
  <a href="https://help.steampowered.com/" target="_blank">客服</a>
  <a class="steam-install" href="https://store.steampowered.com/about/" target="_blank">安装 Steam</a>
</div></div>
""",
    unsafe_allow_html=True,
)

# ---------- 头部 ----------

head_l, head_r = st.columns([4, 1])
with head_l:
    st.markdown('<div class="steam-h1">实时游戏榜单</div>', unsafe_allow_html=True)
with head_r:
    if st.button("↻ 立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ---------- 数据（st.cache_data 控制上游频率） ----------


@st.cache_data(ttl=120, show_spinner="正在从 Steam 拉取热销榜…")
def load_top_sellers():
    items = [it for it in steamdata.fetch_search(False) if it["price"]["final"]]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


@st.cache_data(ttl=120, show_spinner="正在从 Steam 拉取特惠榜…")
def load_specials():
    items = [it for it in steamdata.fetch_search(True) if it["price"]["final"]]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


@st.cache_data(ttl=60, show_spinner="正在逐款查询 Top100 实时在线人数（首载约 10-20 秒）…")
def load_most_played():
    return steamdata.build_most_played()


# ---------- HTML 渲染 ----------


def _esc(s):
    return htmllib.escape(str(s)) if s is not None else ""


def price_row_html(p):
    if not p or not p.get("final"):
        return '<span class="steam-price">—</span>'
    if p.get("pct"):
        return (f'<span class="strike">{_esc(p["original"])}</span>'
                f'<span class="steam-tag"><span class="pct">{p["pct"]}%</span>'
                f'<span class="final">{_esc(p["final"])}</span></span>')
    return f'<span class="steam-price">{_esc(p["final"])}</span>'


def card_html(it):
    return (f'<a class="steam-card" href="{_esc(it["url"])}" target="_blank">'
            f'<span class="steam-rank">#{it["rank"]}</span>'
            f'<img src="{_esc(it["image"])}" loading="lazy" onerror="this.style.visibility=\'hidden\'">'
            f'<span class="name">{_esc(it["name"])}</span>'
            f'<span class="price-row">{price_row_html(it["price"])}</span></a>')


def grid_html(items, title, sub):
    body = "".join(card_html(it) for it in items)
    return (f'<div class="steam-panel"><div class="steam-section">{title}'
            f'<span class="sub">{sub}</span></div>'
            f'<div class="steam-grid">{body}</div></div>')


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
    return (f'<a class="steam-row" href="{_esc(it["url"])}" target="_blank" style="text-decoration:none">'
            f'<span class="rank">#{it["rank"]}</span>'
            f'<img src="{_esc(it["image"])}" loading="lazy" onerror="this.style.visibility=\'hidden\'">'
            f'<span><div class="gname">{_esc(it["name"])}</div>{sub}</span>'
            f'<span class="pnum">{_fmt(it.get("players"))}</span>'
            f'<span class="peak">{_fmt(it.get("peak"))}</span>'
            f'{delta_html(it)}</a>')


def rows_html(items, title, sub):
    head = ('<div class="steam-thead"><span class="ctr">#</span><span>游戏</span>'
            '<span></span><span class="r">当前在线</span><span class="r">今日峰值</span>'
            '<span class="ctr">周变化</span></div>')
    body = "".join(row_html(it) for it in items)
    return (f'<div class="steam-panel"><div class="steam-section">{title}'
            f'<span class="sub">{sub}</span></div>{head}{body}</div>')


def updated_line(ts):
    t = time.strftime("%H:%M:%S", time.localtime(ts))
    return f'<span class="steam-meta"><span class="dot"></span>更新于 {t} · 每 60 秒自动刷新</span>'


# ---------- 三个榜单（fragment 每 60 秒原地刷新，不丢 tab 状态） ----------

tab_sellers, tab_played, tab_specials = st.tabs(["热销商品", "最热游玩", "特惠专区"])


@st.fragment(run_every="60s")
def render_sellers():
    items = load_top_sellers()
    st.markdown(
        updated_line(time.time()) + grid_html(items, "热门畅销商品", "TOP 50 · 按销量排序"),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_most_played():
    items = load_most_played()
    st.markdown(
        updated_line(time.time()) + rows_html(items, "最热游玩游戏", "TOP 100 · 按当前在线人数排序"),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_specials():
    items = load_specials()
    st.markdown(
        updated_line(time.time()) + grid_html(items, "特惠专区", "TOP 50 · 热销折扣游戏"),
        unsafe_allow_html=True,
    )


with tab_sellers:
    render_sellers()
with tab_played:
    render_most_played()
with tab_specials:
    render_specials()

st.markdown(
    '<div class="steam-footer">本页面为非官方第三方工具，与 Valve Corporation 无从属关系。'
    "榜单数据实时来自 Steam 官方公开接口，游戏名称、图片与价格版权归 Valve 及相应开发商所有。</div>",
    unsafe_allow_html=True,
)
