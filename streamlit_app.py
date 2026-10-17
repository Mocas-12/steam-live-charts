"""Steam 实时游戏榜单 —— Streamlit Cloud 入口（深色数据主题）。

与本地 FastAPI 版（app.py + static/）共用数据层 steamdata.py；
st.cache_data 控制上游请求频率，st.fragment(run_every=60s) 让榜单原地自动刷新。
"""

import html as htmllib
import threading
import time

import streamlit as st

import steamdata

st.set_page_config(
    page_title="GAMECHARTS · Steam 实时游戏榜单",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------- 深色数据主题 ----------

CSS = """
<style>
/* 隐藏 Streamlit 自带框架 */
[data-testid="stHeader"] { display: none; }
#MainMenu, footer, [data-testid="stFooter"] { visibility: hidden; }
[data-testid="stStatusWidget"], [data-testid="stToolbar"] { display: none; }
.block-container { padding: 0 1.25rem 2rem; max-width: 1100px; margin: 0 auto; }
section[data-testid="stVerticalBlock"] { gap: .45rem; }

/* 页面底色：深空 + 金火×电冰×深紫三色极光（AURORA GLASS） */
.stApp {
  background: #101419;
}
body, .stApp, p {
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  color: #e8edf2;
}

:root {
  --gc-line: rgba(255,255,255,.08);
  --gc-line-hi: rgba(255,255,255,.18);
  --gc-glass: #181f27;
  --gc-text: #e8edf2;
  --gc-muted: #9aa3b8;
  --gc-dim: #8c99a8;
  --gc-gold: #e7bf69;
  --gc-gold-2: #ffdf8e;
  --gc-ice: #7dd7ff;
  --gc-up: #6fdc8c;
  --gc-down: #ff6b7a;
  --gc-deal: #7ee08f;
  --gc-mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
}

a { color: #e8edf2; }
.stMarkdown a, .stMarkdown a * { text-decoration: none !important; }

/* 顶栏 */
.gc-nav {
  background: transparent; margin: 0 0 4px; padding: 0;
  border-bottom: 1px solid var(--gc-line); height: 58px; display: flex; align-items: center;
}
.gc-nav-inner { display: flex; align-items: center; gap: 24px; width: 100%; }
.gc-logo { display: flex; align-items: center; gap: 10px; }
.gc-logo-mark {
  width: 12px; height: 12px; border-radius: 4px;
  background: linear-gradient(135deg, var(--gc-gold-2), var(--gc-gold));
}
.gc-logo-word { font-size: 16px; font-weight: 800; letter-spacing: .5px; color: #fff !important; }
.gc-logo-word span { color: var(--gc-gold) !important; }
.gc-logo-sub {
  font-family: var(--gc-mono); font-size: 10px; font-weight: 600; letter-spacing: 2.5px;
  color: var(--gc-ice) !important; border: 1px solid rgba(125,215,255,.35); padding: 3px 9px;
  border-radius: 99px;
}
.gc-nav .spacer { margin-right: auto; }
.gc-nav a { color: #a0acba; text-decoration: none; font-size: 13px; font-weight: 500; padding: 7px 12px; border-radius: 8px; }
.gc-nav a:hover { color: #e8eaf0; background: rgba(255,255,255,.05); }
/* 标题区 */
.gc-overline {
  font-family: var(--gc-mono); font-size: 11px; letter-spacing: .2px;
  color: #8c99a8 !important; text-transform: none; margin: 20px 0 8px;
}
.gc-h1 {
  font-size: clamp(26px, 3vw, 32px); font-weight: 700; letter-spacing: -.5px;
  line-height: 1.08; color: #fff !important;
}
.gc-h1 em {
  font-style: normal; color: inherit;
}
@keyframes gc-pulse { 50% { opacity: .3; } }

/* 刷新按钮（克制的描边胶囊） */
.stButton > button {
  width: 36px; min-height: 36px; border-radius: 6px; padding: 4px;
  background: rgba(255,255,255,.05); color: #e8eaf0;
  border: 1px solid var(--gc-line-hi);
  font-size: 12.5px; font-weight: 600; letter-spacing: .5px;
  transition: all .15s;
}
.stButton > button:hover {
  background: rgba(125,215,255,.12); border-color: rgba(125,215,255,.4); color: #fff;
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
.stTextInput input:focus {
  border-color: rgba(125,215,255,.55) !important;
}
.stTextInput input::placeholder { color: #8c99a8 !important; }

/* Tab（分段控件）——兼容旧版 baseweb 与新版 react-aria 两种 DOM */
[data-baseweb="tab-list"], [role="tablist"] {
  display: inline-flex; gap: 2px; border-bottom: none;
  background: var(--gc-glass); border: 1px solid var(--gc-line);
  border-radius: 13px; padding: 4px;
}
[role="tab"] {
  color: #a0acba; border-radius: 9px; padding: 9px 18px;
  font-weight: 600;
}
[role="tab"] p { font-size: 13.5px; font-weight: 600; color: #a0acba !important; }
[role="tab"]:hover { background: rgba(255,255,255,.05); }
[role="tab"]:hover p { color: #e8eaf0 !important; }
[role="tab"][aria-selected="true"] {
  background: linear-gradient(135deg, var(--gc-gold-2), var(--gc-gold));
}
[role="tab"][aria-selected="true"] p { color: #171204 !important; font-weight: 700; }
[data-baseweb="tab-highlight"], .react-aria-SelectionIndicator { display: none !important; }

/* 榜单面板 */
.gc-panel { margin-top: 8px; }

.gc-section {
  color: #fff; font-size: 18px; font-weight: 650; letter-spacing: 0;
  padding: 8px 0 16px; display: flex; align-items: baseline; gap: 12px;
}
.gc-section::before {
  display: none;
}
.gc-section .sub { color: #8c99a8 !important; font-size: 11.5px; font-family: var(--gc-mono); letter-spacing: 1.5px; font-weight: 400; }

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
.gc-strike { color: #8c99a8 !important; text-decoration: line-through; font-size: 12px; font-family: var(--gc-mono); }

/* 最热游玩行（无价格列） */
.gc-thead, .gc-row {
  display: grid; grid-template-columns: 44px 120px minmax(0,1fr) 105px 105px 90px;
  gap: 12px; align-items: center; padding: 10px 6px;
}
.gc-thead {
  color: #8c99a8 !important; font-size: 11px; font-weight: 600; letter-spacing: 2px;
  font-family: var(--gc-mono); text-transform: none;
  border-bottom: 1px solid var(--gc-line); padding-bottom: 10px; margin-bottom: 4px;
}
.gc-thead .r { text-align: right; }
.gc-thead .ctr { text-align: center; }
.gc-row {
  min-height: 76px; text-decoration: none !important;
  border-bottom: 1px solid var(--gc-line);
  transition: background .15s;
}
.gc-row:hover {
  background: rgba(255,255,255,.035);
}
.gc-row .gname { color: #fff !important; font-size: 14.5px; font-weight: 600; line-height: 1.3; }
.gc-row:hover .gname { color: var(--gc-gold) !important; }
.gc-row:hover .rank { background: none; color: var(--gc-ice) !important; filter: none; }
.gc-row .surge {
  font-family: var(--gc-mono); font-size: 11px; font-weight: 700;
  color: #ff9d6b !important; background: rgba(255,122,74,.12);
  border: 1px solid rgba(255,122,74,.4);
  padding: 1px 8px; border-radius: 99px; margin-left: 8px;
  display: inline-block; vertical-align: 1px;

}
@keyframes gc-surge-pulse { 50% { opacity: .65; } }


/* 今日速览条 */
.gc-briefing {
  padding: 10px 0; margin: 8px 0 4px; border-top: 1px solid var(--gc-line);
  font-size: 12px; color: #a0acba !important;
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px 0;
}
.gc-briefing .bi { display: inline-flex; align-items: center; }
.gc-briefing .bi + .bi::before { content: "·"; margin: 0 12px; color: #8c99a8 !important; }
.gc-briefing b, .gc-briefing strong { color: var(--gc-gold) !important; font-family: var(--gc-mono); font-weight: 700; }
.gc-row .genre { color: #a0acba !important; font-size: 11.5px; margin-top: 3px; }
.gc-row .genre .p { color: #e8eaf0 !important; margin-left: 8px; font-family: var(--gc-mono); font-weight: 600; }
.gc-row .pnum {
  color: #fff !important; font-size: 17px; font-weight: 700; text-align: right;
  font-family: var(--gc-mono); font-variant-numeric: tabular-nums;
}
.gc-row .peak {
  color: #a0acba !important; font-size: 13px; text-align: right;
  font-family: var(--gc-mono); font-variant-numeric: tabular-nums;
}
.gc-row .delta { text-align: center; font-size: 12.5px; font-weight: 700; font-family: var(--gc-mono); }
.gc-row .delta.up { color: var(--gc-up) !important; }
.gc-row .delta.down { color: var(--gc-down) !important; }
.gc-row .delta.same { color: #8c99a8 !important; font-weight: 400; }
.gc-row .delta .new {
  display: inline-block; background: rgba(232,194,104,.12);
  border: 1px solid rgba(232,194,104,.45); color: var(--gc-gold) !important;
  font-size: 10px; padding: 2px 8px; border-radius: 99px; letter-spacing: 1px;
}

/* 价格类榜单的横排（带价格列） */
.gc-thead.simple { grid-template-columns: 44px 120px minmax(0,1fr) 200px; }
.gc-thead.simple .r { text-align: right; }
.gc-row.simple { grid-template-columns: 44px 120px minmax(0,1fr) 200px; }
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
.gc-empty .esub { font-size: 12.5px; font-family: var(--gc-mono); color: #8c99a8; }

.gc-meta-line {
  font-family: var(--gc-mono); font-size: 12px; color: #98a0b5;
  display: flex; align-items: center; gap: 10px; padding: 2px 2px 8px;
}
.gc-meta-line .dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--gc-ice);
  box-shadow: 0 0 10px rgba(125,215,255,.9); animation: gc-pulse 1.8s infinite;
}

@keyframes gc-blink { 0%,100% { opacity: .25; } 50% { opacity: 1; } }
.gc-loading {
  display: flex; align-items: center; gap: 6px; padding: 22px 4px;
  font-family: var(--gc-mono); font-size: 12px; color: #a0acba;
}
.gc-loading i {
  width: 9px; height: 18px; margin-right: 2px; border-radius: 2px;
  background: var(--gc-gold); transform: skewX(-12deg);
  animation: gc-blink 1s infinite;
}
.gc-loading i:nth-child(2) { animation-delay: .18s; }
.gc-loading i:nth-child(3) { animation-delay: .36s; }

.gc-footer {
  color: #8c99a8 !important; font-size: 12.5px; line-height: 1.8;
  border-top: 1px solid var(--gc-line); padding-top: 14px; margin-top: 22px;
}

@media (max-width: 860px) {
  .gc-thead { display: none; }
  .gc-row, .gc-row.simple { grid-template-columns: 28px 100px minmax(0,1fr) auto; gap: 11px; }
  .gc-row .gc-cover { width: 100px; }
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
  .gc-row .gc-cover { width: 76px; }
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
  .gc-section { font-size: 17px; }
  .gc-empty .ghost { font-size: 30px; }
  .gc-meta-line { font-size: 11px; }
  .gc-footer { font-size: 11.5px; }
}

.gc-row .rank { color: #a0acba !important; text-align: center; font: 600 15px var(--gc-mono); }
.gc-row:nth-of-type(-n+3) .rank { color: var(--gc-gold) !important; }
.gc-cover { width: 120px; aspect-ratio: 460/215; border-radius: 6px; overflow: hidden; display: grid; place-items: center; background: #202a35; }
.gc-cover::before { content: "封面暂缺"; grid-area: 1/1; color: #a0acba; font-size: 11px; }
.gc-row .gc-cover img { grid-area: 1/1; width: 100%; height: 100%; object-fit: cover; display: block; }
.gc-row .gc-cover img[hidden] { display: none; }
.gc-row > span:nth-child(3) { min-width: 0; }
@media (max-width: 600px) {
  [data-testid="stHorizontalBlock"]:has(.gc-h1) { flex-wrap: nowrap !important; align-items: center; }
  [data-testid="stHorizontalBlock"]:has(.gc-h1) > [data-testid="stColumn"]:first-child { flex: 1 1 0 !important; min-width: 0 !important; width: auto !important; }
  [data-testid="stHorizontalBlock"]:has(.gc-h1) > [data-testid="stColumn"]:last-child { flex: 0 0 40px !important; min-width: 40px !important; width: 40px !important; }
  .gc-overline { margin: 12px 0 6px; letter-spacing: 0; }
  .gc-briefing { padding: 8px 0; }
  [role="tablist"] { flex-wrap: nowrap !important; overflow-x: auto !important; border-radius: 0 !important; }
  [role="tab"] { flex-shrink: 0; }
  .gc-row, .gc-row.simple { grid-template-columns: 22px 76px minmax(0,1fr); gap: 4px 10px; padding: 12px 0; }
  .gc-row .rank { grid-column: 1; grid-row: 1 / span 2; }
  .gc-row .gc-cover { width: 76px; grid-column: 2; grid-row: 1 / span 2; }
  .gc-row > span:nth-child(3) { grid-column: 3; grid-row: 1; }
  .gc-row .pnum, .gc-row.simple .price-col { grid-column: 3; grid-row: 2; text-align: left; justify-content: flex-start; }
  .gc-row .pnum::before { content: attr(data-label) " "; color: #a0acba; font-size: 11px; font-weight: 400; }
  .gc-row .genre, .gc-section .sub { display: none; }
  .gc-row .gname { overflow-wrap: anywhere; }
  .gc-row.simple .price-col { flex-direction: row; align-items: center; }
}
a:focus-visible, button:focus-visible { outline: 2px solid var(--gc-gold); outline-offset: 3px; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
.gc-method { color: #a0acba; font-size: 12px; padding: 16px 0; line-height: 1.8; }
.gc-method summary { cursor: pointer; }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)

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

</div></div>
""",
    unsafe_allow_html=True,
)

# ---------- 数据 ----------


def collect_board(fn):
    started = time.time()
    return fn(), started


@st.cache_data(ttl=120, show_spinner=False)
def load_top_sellers():
    return collect_board(lambda: [it for it in steamdata.fetch_search() if it["price"]["final"]])


@st.cache_data(ttl=120, show_spinner=False)
def load_specials():
    return collect_board(lambda: [it for it in steamdata.fetch_search(True) if it["price"]["final"]])


@st.cache_data(ttl=120, show_spinner=False)
def load_free_to_keep():
    return collect_board(steamdata.fetch_free_to_keep)


@st.cache_data(ttl=600, show_spinner=False)
def load_new_releases():
    return collect_board(lambda: [it for it in steamdata.fetch_new_releases() if it["price"]["final"]])


@st.cache_data(ttl=120, show_spinner=False)
def load_free_games():
    return collect_board(lambda: [it for it in steamdata.fetch_search(free=True)
                                 if it["price"]["final"] and it["price"]["free"]])


@st.cache_data(ttl=600, show_spinner=False)
def load_epic_free():
    return collect_board(steamdata.fetch_epic_free)


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

@st.cache_resource
def most_played_state():
    # Streamlit rerun 会重建模块全局变量；后台锁与快照必须跨 rerun 共享。
    return threading.Lock(), {"status": "idle", "items": None, "error": None,
                              "ts": 0.0, "built_at": None, "source": "live"}


_mp_lock, _mp_state = most_played_state()


def _build_mp_thread():
    try:
        started = time.time()
        items = steamdata.build_most_played()
        with _mp_lock:
            _mp_state.update(status="ready", items=items, error=None,
                             ts=time.time(), built_at=started, source="live")
    except Exception as e:
        with _mp_lock:
            _mp_state.update(status="error", error=str(e), ts=time.time())


def _mp_snapshot(state):
    # 数据与来源在同一把锁内一起读取，后台完成不能拼出不同版本的元信息。
    meta = (steamdata.data_meta(state["built_at"], MP_TTL, state["source"], bool(state["error"]))
            if state["built_at"] is not None else None)
    return state["items"], state["error"], meta


def request_most_played() -> tuple[list | None, str | None, dict | None]:
    """返回 (items|None, error|None, meta|None)；绝不阻塞。

    built_at 是当前快照的真实采集时间；失败时保留旧快照和时间。
    """
    with _mp_lock:
        s = _mp_state
        age = time.time() - s["ts"]
        if s["status"] == "building":
            return _mp_snapshot(s)
        if s["status"] == "ready" and age <= MP_TTL:
            return _mp_snapshot(s)
        if s["status"] == "error" and age < MP_RETRY_COOLDOWN:
            return _mp_snapshot(s)
        # idle / ready 过期 / error 冷却结束：先尝试磁盘缓存顶上，再起后台构建
        if s["items"] is None:
            cached, built_at = steamdata.load_cached_most_played()
            if cached:
                s["items"], s["built_at"], s["source"] = cached, built_at, "disk"
        s["status"] = "building"
        threading.Thread(target=_build_mp_thread, daemon=True).start()
        return _mp_snapshot(s)


def kick_most_played_rebuild():
    """立即刷新按钮：重置状态，下个请求周期触发后台重建（页面不阻塞）。"""
    with _mp_lock:
        if _mp_state["status"] != "building":
            _mp_state.update(status="idle", ts=0.0)


EMPTY_HTML = (
    '<div class="gc-empty"><div class="ghost">FREE</div>'
    '<div class="etitle">当前没有限时免费入库活动</div>'
    '<div class="esub">Steam 免费入库活动零星出现（周末较多），开启后游戏永久入库 · 60 秒后自动复查</div></div>'
)

EMPTY_EPIC_HTML = (
    '<div class="gc-empty"><div class="ghost">FREE</div>'
    '<div class="etitle">Epic 当前没有可领取的免费游戏</div>'
    '<div class="esub">Epic 商城每周轮换免费档，即将开始的也会预告在这里</div></div>'
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
    surge = (f'<span class="surge" title="最近30分钟均值对比此前2小时均值；采样缺口超过5分钟时不显示">+{it["surge"]}%</span>'
             if it.get("surge") else "")
    if not stats:
        # 价格类榜单：# | 封面 | 游戏（发售日期/类型）| 价格
        meta = " · ".join(x for x in [it.get("released"), " / ".join(it.get("genres") or [])] if x)
        sub = f'<span class="genre">{_esc(meta)}</span>' if meta else ""
        return (f'<a class="gc-row simple" href="{_esc(it["url"])}" target="_blank">'
                f'<span class="rank">{it["rank"]}</span>'
                f'<span class="gc-cover" aria-hidden="true"><img src="{_esc(it["image"])}" alt="" loading="lazy" onerror="this.hidden=true"></span>'
                f'<span><div class="gname">{_esc(it["name"])}{surge}</div>{sub}</span>'
                f'<span class="price-col">{price_row_html(it.get("price"))}</span></a>')
    genres = " / ".join(it.get("genres") or [])
    sub = (f'<span class="genre">{_esc(genres)}</span>' if genres else "")
    return (f'<a class="gc-row" href="{_esc(it["url"])}" target="_blank">'
            f'<span class="rank">{it["rank"]}</span>'
            f'<span class="gc-cover" aria-hidden="true"><img src="{_esc(it["image"])}" alt="" loading="lazy" onerror="this.hidden=true"></span>'
            f'<span><div class="gname">{_esc(it["name"])}{surge}</div>{sub}</span>'
            f'<span class="pnum" data-label="在线">{_fmt(it.get("players"))}</span>'
            f'<span class="peak">{_fmt(it.get("peak"))}</span>'
            f'{delta_html(it)}</a>')


def rows_html(items, title, sub, stats=False, query="", empty_html=EMPTY_HTML):
    if query:  # 榜单内按游戏名筛选（fragment 内的输入，rerun 不丢 tab 状态）
        items = [it for it in items if query in (it.get("name") or "").lower()]
    if not items:
        if query:  # 被筛空（与限时免费/Epic 的真·空状态区分）
            body = (f'<div class="gc-empty"><div class="ghost">0</div>'
                    f'<div class="etitle">没有匹配「{_esc(query)}」的游戏</div>'
                    f'<div class="esub">换个关键词，或清空筛选框看完整榜单</div></div>')
        else:
            body = empty_html
        return (f'<div class="gc-panel"><div class="gc-section">{title}'
                f'<span class="sub">{sub}</span></div>{body}</div>')
    if stats:
        head = ('<div class="gc-thead"><span class="ctr">排名</span><span>游戏</span>'
                '<span></span><span class="r">当前在线</span><span class="r">官方峰值</span>'
                '<span class="ctr" title="上周官方排名减去当前实时排名；人数未知时不计算">较上周排名</span></div>')
    else:
        head = ('<div class="gc-thead simple"><span class="ctr">排名</span><span>游戏</span>'
                '<span></span><span class="r">价格</span></div>')
    body = "".join(row_html(it, stats) for it in items)
    if stats:
        body += ('<details class="gc-method"><summary>数据口径与缺失说明</summary>'
                 '候选游戏来自 Steam 官方榜单，按已取得的实时在线人数排序。'
                 '未知人数显示 — 并置后；周变化对比上周官方排名。'
                 '官方峰值与当前在线的采集时点不同。异动比较最近30分钟与此前2小时的均值，'
                 '样本覆盖不足或存在超过5分钟的缺口时不显示。</details>')
    return (f'<div class="gc-panel"><div class="gc-section">{title}'
            f'<span class="sub">{sub}</span></div>{head}{body}</div>')


def updated_line(updated_at, ttl=60, source="live", refresh_failed=False):
    meta = steamdata.data_meta(updated_at, ttl, source, refresh_failed)
    return f'<div class="gc-meta-line">{_esc(steamdata.data_status(meta))}</div>'


# ---------- 头部（列内垂直居中） ----------

head_l, head_r = st.columns([20, 1], vertical_alignment="center")
with head_l:
    st.markdown('<div class="gc-overline">Steam 游戏数据 · 每 60 秒检查更新</div>', unsafe_allow_html=True)
    st.markdown('<div class="gc-h1">Steam 实时游戏<em>榜单</em></div>', unsafe_allow_html=True)
with head_r:
    if st.button("↻", help="检查最新数据"):
        st.session_state["refreshing"] = True
        for loader in (load_top_sellers, load_specials, load_free_to_keep,
                       load_new_releases, load_free_games, load_epic_free):
            loader.clear()
        kick_most_played_rebuild()
        st.rerun()

if st.session_state.pop("refreshing", False):
    st.toast("已请求更新；采集完成后自动替换，失败时保留历史数据", icon="🔄")

@st.fragment(run_every="60s")
def render_briefing():
    mp, _err, meta = request_most_played()
    if not mp:
        st.markdown('<div class="gc-briefing"><span class="bi">数据同步中…</span></div>',
                    unsafe_allow_html=True)
        return
    b = steamdata.briefing_facts(mp, [])
    parts = []
    if b["games_with_players"]:
        parts.append(f'榜单 Top {b["games_total"]} 在线合计 <b>{b["total_online"]:,}</b>')
    if b["games_with_players"] < b["games_total"]:
        parts.append(f'人数覆盖 {b["games_with_players"]}/{b["games_total"]} 款')
    parts.append(f'<span title="{_esc(steamdata.data_status(meta))}">{"历史快照" if meta["stale"] else "有效采样"}</span>')
    for s in ([] if meta["stale"] else b["surges"]):
        parts.append(f'🔥 <strong>{_esc(s["name"])}</strong> 近30分钟 <b>+{s["pct"]}%</b>')
    if b["new_entries"]:
        parts.append(f'<b>{b["new_entries"]}</b> 款新上榜')
    if not parts:
        parts.append("数据同步中…")
    seq = "".join(f'<span class="bi">{p}</span>' for p in parts)
    st.markdown(f'<div class="gc-briefing">{seq}</div>', unsafe_allow_html=True)


render_briefing()

# ---------- 六个榜单（fragment 每 60 秒原地刷新，不丢 tab 状态） ----------

tab_played, tab_sellers, tab_specials, tab_new, tab_free, tab_ftk, tab_epic = st.tabs(
    ["最热游玩", "热销商品", "特惠专区", "新品上架", "免费游戏", "限时免费", "Epic 免费"]
)


@st.fragment(run_every="60s")
def render_most_played():
    q = st.text_input("筛选", key="q_played", placeholder="🔍 筛选游戏名…",
                      label_visibility="collapsed").strip().lower()
    box = st.empty()
    items, err, meta = request_most_played()
    if items:
        line = f'<div class="gc-meta-line">{_esc(steamdata.data_status(meta))}</div>'
        if meta["stale"]:
            items = [{**it, "surge": None, "spark": []} for it in items]
        box.markdown(
            line + rows_html(items, "最热游玩游戏", "TOP 100 · BY CURRENT PLAYERS", stats=True, query=q),
            unsafe_allow_html=True,
        )
    elif err:
        box.markdown(ERROR_PANEL_TMPL.format(err=_esc(err)), unsafe_allow_html=True)
    else:
        box.markdown(LOADING_PANEL, unsafe_allow_html=True)


def _board(fn, title, sub, query, stats=False, empty_html=EMPTY_HTML, ttl=120):
    """榜单 fragment 通用体：先渲染加载骨架，单个接口失败只影响本榜不炸整页。"""
    box = st.empty()
    box.markdown(LOADING_PANEL, unsafe_allow_html=True)
    try:
        items, collected_at = fn()
        items = [{**it, "rank": i + 1} for i, it in enumerate(items)]
    except Exception as e:
        box.markdown(ERROR_PANEL_TMPL.format(err=_esc(e)), unsafe_allow_html=True)
        return
    box.markdown(
        updated_line(collected_at, ttl) + rows_html(items, title, sub, stats=stats, query=query,
                                   empty_html=empty_html),
        unsafe_allow_html=True,
    )


@st.fragment(run_every="60s")
def render_sellers():
    q = st.text_input("筛选", key="q_sellers", placeholder="🔍 筛选游戏名…",
                      label_visibility="collapsed").strip().lower()
    _board(load_top_sellers, "热门畅销商品", "STEAM TOP SELLERS", q)


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
    _board(load_new_releases, "新品上架", "TOP 30 · NEW RELEASES", q, ttl=600)


@st.fragment(run_every="60s")
def render_free():
    q = st.text_input("筛选", key="q_free", placeholder="🔍 筛选游戏名…",
                      label_visibility="collapsed").strip().lower()
    _board(load_free_games, "免费游戏", "TOP 50 · FREE TO PLAY", q)


@st.fragment(run_every="60s")
def render_epic():
    q = st.text_input("筛选", key="q_epic", placeholder="🔍 筛选游戏名…",
                      label_visibility="collapsed").strip().lower()
    _board(load_epic_free, "Epic 喜加一", "FREE @ EPIC · 每周轮换，即将开始的也预告",
           q, empty_html=EMPTY_EPIC_HTML, ttl=600)


with tab_played:
    render_most_played()
with tab_sellers:
    render_sellers()
with tab_ftk:
    render_free_to_keep()
with tab_specials:
    render_specials()
with tab_new:
    render_new()
with tab_free:
    render_free()
with tab_epic:
    render_epic()

st.markdown(
    '<div class="gc-footer">本页面为非官方第三方工具，与 Valve Corporation 及 Epic Games 无从属关系。'
    "榜单数据实时来自 Steam 与 Epic 商城官方公开接口，游戏名称、图片与价格版权归 Valve、Epic 及相应开发商所有。</div>",
    unsafe_allow_html=True,
)
