"""Steam 实时游戏榜单 —— FastAPI 后端（本地/自托管用）。

数据抓取统一走共享同步层 steamdata.py（asyncio.to_thread 调用，
与 Streamlit 端完全同一条代码路径），本文件只负责 TTL 缓存 + 静态前端托管：
- 六大榜单端点 /api/*（最热游玩 60s / 搜索类 120s / 新品 600s 顶层缓存）
- /healthz 存活探针
"""

import asyncio
import logging
import os
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import steamdata

log = logging.getLogger("steam-live-charts")

REFRESH_SECONDS = 60  # 前端轮询节奏，与最热榜缓存一致


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

app = FastAPI(title="Steam 实时游戏榜单")


def _static_ver() -> str:
    """静态资源版本号 = 文件 mtime（每次请求实时计算），改前端即自动失效缓存。"""
    return str(int(max(os.path.getmtime(os.path.join("static", f)) for f in ("app.js", "steam.css", "index.html"))))


@app.get("/", include_in_schema=False)
async def index():
    with open(os.path.join("static", "index.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read().replace("__VER__", _static_ver()))


@app.middleware("http")
async def no_cache_static(request, call_next):
    """静态资源禁用启发式缓存（保留 Etag 协商），改前端立刻生效。"""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".css", ".js", ".html")):
        response.headers["Cache-Control"] = "no-cache"
    return response


def meta() -> dict:
    return {"updated_at": int(time.time()), "ttl": REFRESH_SECONDS}


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
    return {"meta": meta(), "items": items}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
