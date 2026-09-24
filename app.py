"""Steam 实时游戏榜单 —— FastAPI 后端（本地/自托管用）。

数据抓取统一走共享同步层 steamdata.py（asyncio.to_thread 调用，
与 Streamlit 端完全同一条代码路径），本文件只负责 TTL 缓存 + 静态前端托管：
- 六大榜单端点 /api/*（最热游玩 60s / 搜索类 120s / 新品 600s 顶层缓存）
- /api/history/{appid} 24h 在线采样查询（内存态，随访问积累，重启归零）
- 限时免费看门狗：设置 NTFY_TOPIC 后，新活动出现即经 ntfy.sh 推送
- /healthz 存活探针
"""

import asyncio
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import steamdata

log = logging.getLogger("steam-live-charts")

REFRESH_SECONDS = 60  # 前端轮询节奏，与最热榜缓存一致
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()  # ntfy.sh 主题名；留空关闭限时免费推送
FTK_POLL_SECONDS = 300  # 看门狗轮询节奏（走同一份 TTL 缓存，不增加上游压力）


def downsample(values: list, n: int = 40) -> list:
    """等距抽 n 个点（不足 n 全保留），右端点对齐最新值。"""
    if len(values) <= n:
        return list(values)
    step = len(values) / n
    out = [values[int(i * step)] for i in range(n)]
    out[-1] = values[-1]
    return out


class HistoryRing:
    """appid -> deque[(ts, players)] 的 24h 滚动采样。

    采样随榜单请求发生（缓存命中靠 min_interval 去重），内存保留 1440 点，
    重启归零——sparkline 从"采样中"逐渐长出来是预期行为。
    """

    def __init__(self, max_points: int = 24 * 60):
        self.rings: dict[int, deque] = {}
        self._max = max_points

    def sample(self, items: list[dict], min_interval: float = 55.0) -> None:
        now = time.time()
        for it in items:
            players = it.get("players")
            if players is None:
                continue
            ring = self.rings.setdefault(it["appid"], deque(maxlen=self._max))
            if ring and now - ring[-1][0] < min_interval:
                continue
            ring.append((now, players))

    def spark(self, appid: int, n: int = 40) -> list[int]:
        ring = self.rings.get(appid)
        if not ring:
            return []
        return downsample([p for _, p in ring], n)


history = HistoryRing()


class TTLCache:
    """带在途请求合并的 TTL 缓存；上游失败时回退过期数据。"""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self.data: dict = {}
        self.inflight: dict = {}
        self.lock = asyncio.Lock()

    async def get(self, key, factory, force=False):
        async with self.lock:
            hit = self.data.get(key)
            if hit and not force and time.monotonic() - hit[0] < self.ttl:
                return hit[1]
            if key not in self.inflight:
                self.inflight[key] = asyncio.ensure_future(factory())
            fut = self.inflight[key]
        try:
            value = await fut
        except Exception:
            async with self.lock:
                self.inflight.pop(key, None)
            if hit is not None:  # 网络抖动时用过期数据兜底
                log.warning("上游 %s 抓取失败，回退过期缓存", key)
                return hit[1]
            raise
        async with self.lock:
            self.data[key] = (time.monotonic(), value)
            self.inflight.pop(key, None)
        return value


charts_cache = TTLCache(REFRESH_SECONDS)
search_cache = TTLCache(120)
new_cache = TTLCache(600)

# ---------- 限时免费看门狗（ntfy 推送） ----------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(ftk_watchdog())
    yield
    task.cancel()


app = FastAPI(title="Steam 实时游戏榜单", lifespan=lifespan)


def _static_ver() -> str:
    """静态资源版本号 = 文件 mtime（每次请求实时计算），改前端即自动失效缓存。"""
    return str(int(max(os.path.getmtime(os.path.join("static", f)) for f in ("app.js", "steam.css", "index.html"))))


@app.get("/", include_in_schema=False)
async def index():
    with open(os.path.join("static", "index.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read().replace("__VER__", _static_ver()))


@app.middleware("http")
async def no_cache_static(request, call_next):
    """静态资源与 API 响应都禁用启发式缓存。

    API JSON 不带缓存头时 Chromium 会启发式缓存（实测无视 fetch 的 no-store），
    60s 自动刷新会一直拿到旧数据——/api/* 必须显式 no-cache。
    """
    response = await call_next(request)
    path = request.url.path
    if (
        path == "/"
        or path.startswith("/api/")
        or path.endswith((".css", ".js", ".html"))
    ):
        response.headers["Cache-Control"] = "no-cache"
    return response


def meta() -> dict:
    return {"updated_at": int(time.time()), "ttl": REFRESH_SECONDS}


async def ftk_watchdog():
    """每 5 分钟看一眼限时免费榜（走同一份 TTL 缓存），空 -> 非空跳变时推送。"""
    last_empty = True
    while True:
        try:
            items = await search_cache.get(
                "free_to_keep", to_thread(steamdata.fetch_free_to_keep)
            )
            empty = not items
            if last_empty and not empty:
                names = "、".join(
                    f"{it['name']}（原价 {it['price'].get('original') or '未知'}）"
                    for it in items[:5]
                )
                if len(items) > 5:
                    names += f" 等 {len(items)} 款"
                await notify_ntfy("Steam 限时免费入库", f"🎁 现在可免费入库：{names}")
            last_empty = empty
        except Exception as e:
            log.warning("限时免费看门狗: %s", e)
        await asyncio.sleep(FTK_POLL_SECONDS)


async def notify_ntfy(title: str, body: str) -> None:
    def _post():
        return httpx.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            json={"topic": NTFY_TOPIC, "title": title, "message": body, "tags": ["gift"]},
            timeout=15,
        )

    try:
        r = await asyncio.to_thread(_post)
        r.raise_for_status()
        log.info("ntfy 推送成功: %s", title)
    except Exception as e:
        log.warning("ntfy 推送失败: %s", e)


def to_thread(fn, *args):
    """同步数据层调用转协程（给 TTLCache 的 factory 用）。"""
    return lambda: asyncio.to_thread(fn, *args)


@app.get("/api/top-sellers")
async def api_top_sellers(force: bool = False):
    items = await search_cache.get("top_sellers", to_thread(steamdata.fetch_search, False), force=force)
    items = [
        {**it, "rank": i + 1} for i, it in enumerate(items) if it["price"]["final"]
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/specials")
async def api_specials(force: bool = False):
    items = await search_cache.get("specials", to_thread(steamdata.fetch_search, True), force=force)
    items = [
        {**it, "rank": i + 1} for i, it in enumerate(items) if it["price"]["final"]
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/free-to-keep")
async def api_free_to_keep(force: bool = False):
    items = await search_cache.get("free_to_keep", to_thread(steamdata.fetch_free_to_keep), force=force)
    items = [
        {**it, "rank": i + 1}
        for i, it in enumerate(items)
        if it["price"]["pct"] == -100
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/new-releases")
async def api_new_releases(force: bool = False):
    items = await new_cache.get("new_releases", to_thread(steamdata.fetch_new_releases), force=force)
    items = [
        {**it, "rank": i + 1} for i, it in enumerate(items) if it["price"]["final"]
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/free-games")
async def api_free_games(force: bool = False):
    items = await search_cache.get("free_games", to_thread(steamdata.fetch_search, False, True), force=force)
    items = [
        {**it, "rank": i + 1}
        for i, it in enumerate(items)
        if it["price"]["final"] and it["price"]["free"]  # 过滤混入的免费试玩付费游戏
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/most-played")
async def api_most_played(force: bool = False):
    # build_most_played = 官方榜 + 逐款实时在线(并发20) + 详情(30min缓存)
    # + 社区页名字兜底(24h缓存)，官方每日快照按当前在线重排
    items = await charts_cache.get("most_played", to_thread(steamdata.build_most_played), force=force)
    history.sample(items)  # 24h 滚动采样；缓存命中时靠 min_interval 去重
    items = [{**it, "spark": history.spark(it["appid"])} for it in items]
    return {"meta": meta(), "items": items}


@app.get("/api/history/{appid}")
async def api_history(appid: int):
    ring = history.rings.get(appid, ())
    return {"appid": appid, "points": [[ts, p] for ts, p in ring]}


@app.get("/healthz")
async def healthz():
    return {"ok": True, "ntfy": bool(NTFY_TOPIC), "history_games": len(history.rings)}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
