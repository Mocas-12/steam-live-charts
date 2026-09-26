"""Steam 实时游戏榜单 —— Streamlit Cloud 入口（Cinematic 电影感暗色主题）。

与本地 FastAPI 版（app.py + static/）共用数据层 steamdata.py；
st.cache_data 控制上游请求频率，st.fragment(run_every=60s) 让榜单原地自动刷新。
"""

import html as htmllib
import threading
import time
from datetime import datetime, timezone, timedelta

import streamlit as st

import steamdata

st.set_page_config(
    page_title="GAMECHARTS · Steam 实时游戏榜单",
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

/* 侧边实时数据卡 */
.gc-rail {
  position: fixed; top: 78px; z-index: 5; width: 172px;
  background: rgba(255,255,255,.025);
  border: 1px solid var(--gc-line);
  border-radius: 14px; padding: 14px;
  user-select: none;
}
.gc-rail.left { left: calc(50% - 550px - 192px); }
.gc-rail.right { right: calc(50% - 550px - 192px); }
@media (max-width: 1460px) { .gc-rail { display: none; } }

.gc-rail .rail-title {
  font-family: var(--gc-mono); font-size: 10px; font-weight: 700; letter-spacing: 2px;
  color: #6b7285 !important; text-transform: uppercase; margin-bottom: 8px;
}
.gc-rail .rail-loading { font-family: var(--gc-mono); font-size: 11px; color: #6b7285; }

.gc-rail .rrow {
  display: flex; align-items: center; gap: 8px; padding: 7px 0;
  text-decoration: none !important; border-top: 1px solid rgba(255,255,255,.04);
}
.gc-rail .rrow:first-of-type { border-top: none; }
.gc-rail .rrow .rnum {
  font-family: var(--gc-mono); font-size: 12px; font-weight: 800; width: 22px; flex: none;
}
.gc-rail .rrow img { width: 52px; height: 24px; object-fit: cover; border-radius: 4px; flex: none; }
.gc-rail .rrow .rmeta { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.gc-rail .rrow .rname {
  font-size: 11px; color: #e8eaf0 !important;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.gc-rail .rrow .rplayers {
  font-family: var(--gc-mono); font-size: 10px; color: #98a0b3 !important;
}
.gc-rail .rrow:hover .rname { color: var(--gc-gold) !important; }

.gc-rail .stat { padding: 8px 0; border-top: 1px solid rgba(255,255,255,.04); }
.gc-rail .stat:first-of-type { border-top: none; padding-top: 2px; }
.gc-rail .stat .big {
  font-family: var(--gc-mono); font-size: 21px; font-weight: 800; color: #fff !important;
  font-variant-numeric: tabular-nums; line-height: 1.2;
}
.gc-rail .stat .lbl { font-size: 10.5px; color: #6b7285 !important; margin-top: 2px; }

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

/* 榜单筛选框（每个 tab 一个，fragment 内输入不丢 tab 状态） */
.stTextInput { max-width: 260px; margin-bottom: 2px; }
.stTextInput input {
  background: rgba(255,255,255,.04) !important;
  border: 1px solid var(--gc-line) !important;
  border-radius: 10px !important;
  color: #e8eaf0 !important;
  font-size: 13px;
}
.stTextInput input:focus { border-color: rgba(232,194,104,.55) !important; box-shadow: none !important; }
.stTextInput input::placeholder { color: #6b7285 !important; }

/* Tab（分段控件）——兼容旧版 baseweb 与新版 react-aria 两种 DOM */
[data-baseweb="tab-list"], [role="tablist"] {
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
[data-baseweb="tab-highlight"], .react-aria-SelectionIndicator { display: none !important; }

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

/* 最热游玩行（无价格列） */
.gc-thead, .gc-row {
  display: grid;
  grid-template-columns: 64px 156px minmax(0,1fr) 105px 105px 64px;
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
.gc-row .surge {
  font-family: var(--gc-mono); font-size: 11px; font-weight: 700;
  color: #ff9d6b !important; background: rgba(255,122,74,.12);
  border: 1px solid rgba(255,122,74,.4);
  padding: 1px 8px; border-radius: 99px; margin-left: 8px;
  display: inline-block; vertical-align: 1px;
  animation: gc-surge-pulse 2.2s ease-in-out infinite;
}
@keyframes gc-surge-pulse { 50% { opacity: .65; } }
.gc-row img { transition: transform .25s ease; }
.gc-row:hover img { transform: scale(1.03); }

/* 今日速览条 */
.gc-briefing {
  background: rgba(232,194,104,.05);
  border: 1px solid rgba(232,194,104,.18);
  border-radius: 12px; padding: 10px 16px; margin: 2px 0 10px;
  font-size: 13px; color: #98a0b3 !important;
  display: flex; flex-wrap: wrap; align-items: center; row-gap: 4px;
}
.gc-briefing .bi { display: inline-flex; align-items: center; }
.gc-briefing .bi + .bi::before { content: "·"; margin: 0 12px; color: #6b7285 !important; }
.gc-briefing b, .gc-briefing strong { color: var(--gc-gold) !important; font-family: var(--gc-mono); font-weight: 700; }
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

/* 价格类榜单的横排（带价格列） */
.gc-thead.simple { grid-template-columns: 64px 156px minmax(0,1fr) 240px; }
.gc-thead.simple .r { text-align: right; }
.gc-row.simple { grid-template-columns: 64px 156px minmax(0,1fr) 240px; }
.gc-row .price-col {
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

@keyframes gc-blink { 0%,100% { opacity: .25; } 50% { opacity: 1; } }
.gc-loading {
  display: flex; align-items: center; gap: 6px; padding: 22px 4px;
  font-family: var(--gc-mono); font-size: 12px; color: #98a0b3;
}
.gc-loading i {
  width: 9px; height: 18px; margin-right: 2px; border-radius: 2px;
  background: var(--gc-gold); transform: skewX(-12deg);
  animation: gc-blink 1s infinite;
}
.gc-loading i:nth-child(2) { animation-delay: .18s; }
.gc-loading i:nth-child(3) { animation-delay: .36s; }

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
  [data-baseweb="tab-list"], [role="tablist"] { flex-wrap: wrap !important; overflow-x: visible !important; }
  .gc-h1 { font-size: 24px; }
  .stTextInput { max-width: 100%; }
  .stTextInput input { font-size: 16px; } /* ≥16px 防 iOS 聚焦自动放大 */
  [role="tab"] { padding: 8px 12px; }
  [role="tab"] p { font-size: 12.5px !important; }
  .gc-briefing { font-size: 12px; padding: 9px 12px; }
  .gc-briefing .bi + .bi::before { margin: 0 8px; }
  .gc-row .surge { font-size: 10.5px; padding: 1px 6px; margin-left: 6px; }
}

/* 手机竖屏细化（320-480px） */
@media (max-width: 480px) {
  .block-container { padding: 0 .9rem 1.6rem; }
  .gc-nav { height: 54px; }
  .gc-install { padding: 7px 12px; font-size: 12px !important; }
  .gc-row, .gc-row.simple { grid-template-columns: 28px 104px minmax(0,1fr) auto; gap: 10px; padding: 7px 3px; }
  .gc-row img { width: 104px; border-radius: 7px; }
  .gc-row .rank { font-size: 14px; }
  .gc-row .gname {
    font-size: 13.5px;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }
  .gc-row .genre {
    font-size: 10.5px;
    display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden;
  }
  .gc-row .gname { font-size: 13.5px; }
  .gc-row .genre { font-size: 10.5px; }
  .gc-row .pnum { font-size: 14px; }
  .gc-row.simple .price-col .gc-price { font-size: 13px; }
  .gc-row .price-col .gc-tag .pct,
  .gc-row .price-col .gc-tag .final { font-size: 11.5px; }
  .gc-row.simple .price-col { flex-direction: column; align-items: flex-end; gap: 2px; }
  .gc-row.simple .price-col .gc-strike { display: none; }
  .gc-ticker { height: 30px; }
  .gc-ticker .ti { font-size: 11px; padding: 0 14px; }
  .gc-section { font-size: 17px; }
  .gc-empty .ghost { font-size: 30px; }
  .gc-meta-line { font-size: 11px; }
  .gc-footer { font-size: 11.5px; }
}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)

# ---------- 侧边实时数据卡 ----------


@st.fragment(run_every="60s")
def render_rails():
    items, _err, _built = request_most_played()
    if not items:  # 构建中/失败：侧卡占位，绝不阻塞页面其余部分
        st.markdown(
            '<div class="gc-rail left"><div class="rail-title">▍此刻在线 TOP 3</div>'
            '<div class="rail-loading">正在同步…</div></div>'
            '<div class="gc-rail right"><div class="rail-title">▍REALTIME STATS</div>'
            '<div class="rail-loading">正在同步…</div></div>',
            unsafe_allow_html=True,
        )
        return
    total = sum(i.get("players") or 0 for i in items)
    medals = ["var(--gc-gold)", "#d7e0f0", "#e89a6b"]
    rows = "".join(
        f'<a class="rrow" href="{_esc(i["url"])}" target="_blank">'
        f'<span class="rnum" style="color:{medals[idx]}">{i["rank"]}</span>'
        f'<img src="{_esc(i["image"])}" loading="lazy">'
        f'<span class="rmeta">'
        f'<span class="rname">{_esc(i["name"])}</span>'
        f'<span class="rplayers">{_fmt(i.get("players"))} 人在线</span>'
        f'</span></a>'
        for idx, i in enumerate(items[:3])
    )
    t = cn_now()
    st.markdown(
        f'''
<div class="gc-rail left"><div class="rail-title">▍此刻在线 TOP 3</div>{rows}</div>
<div class="gc-rail right"><div class="rail-title">▍REALTIME STATS</div>
  <div class="stat"><div class="big">{_fmt(total)}</div><div class="lbl">TOP100 总在线人数</div></div>
  <div class="stat"><div class="big">{len(items)}</div><div class="lbl">监控游戏数</div></div>
  <div class="stat"><div class="big">{t}</div><div class="lbl">数据更新时间</div></div>
</div>''',
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


@st.cache_data(ttl=120, show_spinner=False)
def load_top_sellers():
    items = [it for it in steamdata.fetch_search(False) if it["price"]["final"]]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


@st.cache_data(ttl=120, show_spinner=False)
def load_specials():
    items = [it for it in steamdata.fetch_search(True) if it["price"]["final"]]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


@st.cache_data(ttl=120, show_spinner=False)
def load_free_to_keep():
    return [{**it, "rank": i + 1} for i, it in enumerate(steamdata.fetch_free_to_keep())]


@st.cache_data(ttl=600, show_spinner=False)
def load_new_releases():
    items = [it for it in steamdata.fetch_new_releases() if it["price"]["final"]]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


@st.cache_data(ttl=120, show_spinner=False)
def load_free_games():
    items = [
        it for it in steamdata.fetch_search(False, free=True)
        if it["price"]["final"] and it["price"]["free"]  # 过滤混入的免费试玩付费游戏
    ]
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]


# ---------- HTML 渲染 ----------


_CN_TZ = timezone(timedelta(hours=8))


def cn_now() -> str:
    """Cloud 服务器为 UTC，展示一律换算成北京时间。"""
    return datetime.now(_CN_TZ).strftime("%H:%M:%S")


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


LOADING_PANEL = (
    '<div class="gc-panel"><div class="gc-loading">'
    '<i></i><i></i><i></i>正在从 Steam 同步最新数据…</div></div>'
)

ERROR_PANEL_TMPL = (
    '<div class="gc-panel"><div class="gc-empty"><div class="ghost">ERR</div>'
    '<div class="etitle">Steam 接口暂时不可用</div>'
    '<div class="esub">{err} · 正在自动重试，通常一两分钟内恢复</div></div></div>'
)

# ---------- 最热游玩：后台线程构建（绝不阻塞页面渲染） ----------
#
# Cloud 的 IP 常被 Steam 限流，冷启动构建要一两分钟；若在 fragment 里同步
# 等它，整个页面会停在 header（历史上反复出现"卡住"即此因）。改为：
# request_most_played() 立即返回 (items|None, error|None)，构建在后台线程跑，
# fragment 每 60s 重跑时自然捡到结果；有旧数据先展示（stale-while-revalidate）。
MP_TTL = 60          # 数据新鲜期；过期即触发后台重建，旧数据继续展示
MP_RETRY_COOLDOWN = 30  # 失败后的冷却期，防止限流风暴下反复硬撞

_mp_lock = threading.Lock()
_mp_state = {"status": "idle", "items": None, "error": None, "ts": 0.0, "built_at": None}


def _build_mp_thread():
    try:
        items = steamdata.build_most_played()
        with _mp_lock:
            _mp_state.update(status="ready", items=items, error=None,
                             ts=time.time(), built_at=None)
    except Exception as e:
        with _mp_lock:
            _mp_state.update(status="error", error=str(e), ts=time.time())


def request_most_played() -> tuple[list | None, str | None, float | None]:
    """返回 (items|None, error|None, built_at|None)；绝不阻塞。

    built_at 非 None 表示这是磁盘缓存数据（进程冷启动的零等待首帧），
    后台重建完成后自然替换为实时数据。
    """
    with _mp_lock:
        s = _mp_state
        age = time.time() - s["ts"]
        if s["status"] == "building":
            return s["items"], None, s["built_at"]
        if s["status"] == "ready" and age <= MP_TTL:
            return s["items"], None, s["built_at"]
        if s["status"] == "error" and age < MP_RETRY_COOLDOWN:
            return None, s["error"], None
        # idle / ready 过期 / error 冷却结束：先尝试磁盘缓存顶上，再起后台构建
        if s["items"] is None:
            cached, built_at = steamdata.load_cached_most_played()
            if cached:
                s["items"], s["built_at"] = cached, built_at
        s["status"] = "building"
        threading.Thread(target=_build_mp_thread, daemon=True).start()
        return s["items"], None, s["built_at"]


def kick_most_played_rebuild():
    """立即刷新按钮：重置状态，下个请求周期触发后台重建（页面不阻塞）。"""
    with _mp_lock:
        _mp_state.update(status="idle", ts=0.0)


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
    surge = (f'<span class="surge">🔥 +{it["surge"]}%</span>'
             if it.get("surge") else "")
    if not stats:
        # 价格类榜单：# | 封面 | 游戏（发售日期/类型）| 价格
        meta = " · ".join(x for x in [it.get("released"), " / ".join(it.get("genres") or [])] if x)
        sub = f'<span class="genre">{_esc(meta)}</span>' if meta else ""
        return (f'<a class="gc-row simple" href="{_esc(it["url"])}" target="_blank">'
                f'<span class="rank">{it["rank"]}</span>'
                f'<img src="{_esc(it["image"])}" loading="lazy" onerror="this.style.visibility=&quot;hidden&quot;">'
                f'<span><div class="gname">{_esc(it["name"])}{surge}</div>{sub}</span>'
                f'<span class="price-col">{price_row_html(it.get("price"))}</span></a>')
    genres = " / ".join(it.get("genres") or [])
    sub = (f'<span class="genre">{_esc(genres)}</span>' if genres else "")
    return (f'<a class="gc-row" href="{_esc(it["url"])}" target="_blank">'
            f'<span class="rank">{it["rank"]}</span>'
            f'<img src="{_esc(it["image"])}" loading="lazy" onerror="this.style.visibility=&quot;hidden&quot;">'
            f'<span><div class="gname">{_esc(it["name"])}{surge}</div>{sub}</span>'
            f'<span class="pnum">{_fmt(it.get("players"))}</span>'
            f'<span class="peak">{_fmt(it.get("peak"))}</span>'
            f'{delta_html(it)}</a>')


def rows_html(items, title, sub, stats=False, query=""):
    if query:  # 榜单内按游戏名筛选（fragment 内的输入，rerun 不丢 tab 状态）
        items = [it for it in items if query in (it.get("name") or "").lower()]
    if not items:
        if query:  # 被筛空（与限时免费的真·空状态区分）
            body = (f'<div class="gc-empty"><div class="ghost">0</div>'
                    f'<div class="etitle">没有匹配「{_esc(query)}」的游戏</div>'
                    f'<div class="esub">换个关键词，或清空筛选框看完整榜单</div></div>')
        else:
            body = EMPTY_HTML
        return (f'<div class="gc-panel"><div class="gc-section">{title}'
                f'<span class="sub">{sub}</span></div>{body}</div>')
    if stats:
        head = ('<div class="gc-thead"><span class="ctr">排名</span><span>游戏</span>'
                '<span></span><span class="r">当前在线</span><span class="r">今日峰值</span>'
                '<span class="ctr">周变化</span></div>')
    else:
        head = ('<div class="gc-thead simple"><span class="ctr">排名</span><span>游戏</span>'
                '<span></span><span class="r">价格</span></div>')
    body = "".join(row_html(it, stats) for it in items)
    return (f'<div class="gc-panel"><div class="gc-section">{title}'
            f'<span class="sub">{sub}</span></div>{head}{body}</div>')


def updated_line():
    t = cn_now()
    return (f'<div class="gc-meta-line"><span class="dot"></span>'
            f'更新于 {t} · 每 60 秒自动刷新</div>')


# ---------- 头部（列内垂直居中） ----------

head_l, head_r = st.columns([4, 1], vertical_alignment="center")
with head_l:
    st.markdown('<div class="gc-overline">Realtime Arena · 每 60 秒自动刷新</div>', unsafe_allow_html=True)
    st.markdown('<div class="gc-h1">Steam 实时游戏<em>榜单</em></div>', unsafe_allow_html=True)
with head_r:
    if st.button("↻ 立即刷新", use_container_width=True):
        st.session_state["refreshing"] = True
        st.cache_data.clear()
        kick_most_played_rebuild()
        st.rerun()

if st.session_state.pop("refreshing", False):
    st.toast("正在后台刷新全部榜单，页面不会卡住；最热游玩一两分钟内就位", icon="🔄")

render_rails()

# ---------- 跑马灯资讯条 ----------


def _safe(fn):
    """跑马灯数据源容错：单个源失败不炸整个 fragment（Cloud 限流常态）。"""
    try:
        return fn()
    except Exception:
        return []


@st.fragment(run_every="60s")
def render_ticker():
    parts = []
    for i in _safe(load_top_sellers)[:4]:
        parts.append(f"热销 #{i['rank']} <strong>{i['name']}</strong> {i['price']['final'] or ''}")
    for i in _safe(load_specials)[:2]:
        if i["price"]["pct"]:
            parts.append(f"特惠 {i['price']['pct']}% <strong>{i['name']}</strong> {i['price']['final']}")
    ftk = _safe(load_free_to_keep)
    for i in ftk[:3]:
        parts.append(f"限时免费入库 <strong>{i['name']}</strong>（原价 {i['price']['original']}）")
    if not ftk:
        parts.append("限时免费入库 · 当前无活动，周末再多来看看")
    if not parts:
        parts.append("正在同步 Steam 数据…")
    seq = "".join(f'<span class="ti"><b>▮</b>{p}</span>' for p in parts)
    st.markdown(
        f'<div class="gc-ticker"><div class="gc-ticker-track">{seq}{seq}</div></div>',
        unsafe_allow_html=True,
    )


render_ticker()

# ---------- 今日速览条（聚合缓存数据，60s 原地更新） ----------


@st.fragment(run_every="60s")
def render_briefing():
    try:
        ftk = _safe(load_free_to_keep)
    except Exception:
        ftk = []
    mp, _err, _built = request_most_played()
    if not mp:
        st.markdown('<div class="gc-briefing"><span class="bi">数据同步中…</span></div>',
                    unsafe_allow_html=True)
        return
    b = steamdata.briefing_facts(mp, ftk)
    parts = []
    if b["total_online"]:
        parts.append(f'此刻 <b>{b["total_online"]:,}</b> 人在线')
    for s in b["surges"]:
        parts.append(f'🔥 <strong>{_esc(s["name"])}</strong> 在线 <b>+{s["pct"]}%</b>')
    if b["new_entries"]:
        parts.append(f'<b>{b["new_entries"]}</b> 款新上榜')
    if b["ftk_count"]:
        names = "、".join(_esc(n) for n in b["ftk_names"])
        more = " 等" if b["ftk_count"] > 3 else ""
        parts.append(f'🎁 限时免费进行中（{names}{more}）')
    if not parts:
        parts.append("数据同步中…")
    seq = "".join(f'<span class="bi">{p}</span>' for p in parts)
    st.markdown(f'<div class="gc-briefing">{seq}</div>', unsafe_allow_html=True)


render_briefing()

# ---------- 六个榜单（fragment 每 60 秒原地刷新，不丢 tab 状态） ----------

tab_played, tab_sellers, tab_specials, tab_new, tab_free, tab_ftk = st.tabs(
    ["最热游玩", "热销商品", "特惠专区", "新品上架", "免费游戏", "限时免费"]
)


@st.fragment(run_every="60s")
def render_sellers():
    q = st.text_input("筛选", key="q_sellers", placeholder="🔍 筛选游戏名…",
                      label_visibility="collapsed").strip().lower()
    box = st.empty()
    box.markdown(LOADING_PANEL, unsafe_allow_html=True)
    box.markdown(
        updated_line() + rows_html(load_top_sellers(), "热门畅销商品", "TOP 50 · BY UNITS SOLD", query=q),
        unsafe_allow_html=True,
    )


def cached_line(built_at: float) -> str:
    """磁盘缓存帧的更新行：诚实标注数据时间，说明正在后台刷新。"""
    t = datetime.fromtimestamp(built_at, _CN_TZ).strftime("%H:%M:%S")
    return (f'<div class="gc-meta-line"><span class="dot" style="background:var(--gc-gold);'
            f'box-shadow:0 0 8px rgba(232,194,104,.7)"></span>'
            f'缓存数据 · {t} · 后台刷新实时数据中…</div>')


@st.fragment(run_every="60s")
def render_most_played():
    q = st.text_input("筛选", key="q_played", placeholder="🔍 筛选游戏名…",
                      label_visibility="collapsed").strip().lower()
    box = st.empty()
    items, err, built_at = request_most_played()
    if items:
        line = cached_line(built_at) if built_at else updated_line()
        box.markdown(
            line + rows_html(items, "最热游玩游戏", "TOP 100 · BY CURRENT PLAYERS", stats=True, query=q),
            unsafe_allow_html=True,
        )
    elif err:
        box.markdown(ERROR_PANEL_TMPL.format(err=_esc(err)), unsafe_allow_html=True)
    else:
        box.markdown(LOADING_PANEL, unsafe_allow_html=True)


def _board(fn, title, sub, query, stats=False):
    """榜单 fragment 通用体：先渲染加载骨架，单个接口失败只影响本榜不炸整页。"""
    box = st.empty()
    box.markdown(LOADING_PANEL, unsafe_allow_html=True)
    try:
        items = fn()
    except Exception as e:
        box.markdown(ERROR_PANEL_TMPL.format(err=_esc(e)), unsafe_allow_html=True)
        return
    box.markdown(
        updated_line() + rows_html(items, title, sub, stats=stats, query=query),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_sellers():
    q = st.text_input("筛选", key="q_sellers", placeholder="🔍 筛选游戏名…",
                      label_visibility="collapsed").strip().lower()
    _board(load_top_sellers, "热门畅销商品", "TOP 50 · BY UNITS SOLD", q)


@st.fragment(run_every="60s")
def render_free_to_keep():
    q = st.text_input("筛选", key="q_ftk", placeholder="🔍 筛选游戏名…",
                      label_visibility="collapsed").strip().lower()
    _board(load_free_to_keep, "限时免费入库", "FREE TO KEEP · 原价付费，现在免费领", q)


@st.fragment(run_every="60s")
def render_specials():
    q = st.text_input("筛选", key="q_specials", placeholder="🔍 筛选游戏名…",
                      label_visibility="collapsed").strip().lower()
    _board(load_specials, "特惠专区", "TOP 50 · HOT DEALS", q)


@st.fragment(run_every="60s")
def render_new():
    q = st.text_input("筛选", key="q_new", placeholder="🔍 筛选游戏名…",
                      label_visibility="collapsed").strip().lower()
    _board(load_new_releases, "新品上架", "TOP 30 · NEW RELEASES", q)


@st.fragment(run_every="60s")
def render_free():
    q = st.text_input("筛选", key="q_free", placeholder="🔍 筛选游戏名…",
                      label_visibility="collapsed").strip().lower()
    _board(load_free_games, "免费游戏", "TOP 50 · FREE TO PLAY", q)


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
