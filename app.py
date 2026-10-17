"""Steam 实时游戏榜单 —— FastAPI 后端（本地/自托管用）。

数据抓取统一走共享同步层 steamdata.py（asyncio.to_thread 调用，
与 Streamlit 端完全同一条代码路径），本文件只负责 TTL 缓存 + 静态前端托管：
- 七大榜单端点 /api/*（最热游玩 60s / 搜索类 120s / 新品 600s 顶层缓存）
- /api/briefing 今日速览（聚合缓存数据，零额外上游请求）
- /api/history/{appid} 24h 在线采样查询（steamdata.HISTORY 内存态，重启归零）
- 限时免费看门狗：设置 NTFY_TOPIC 后，新活动出现即经 ntfy.sh 推送
- /healthz 存活探针
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import steamdata
from steamdata import briefing_facts

log = logging.getLogger("steam-live-charts")

REFRESH_SECONDS = 60  # 前端轮询节奏，与最热榜缓存一致
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()  # ntfy.sh 主题名；留空关闭限时免费推送
FTK_POLL_SECONDS = 300  # 看门狗轮询节奏（走同一份 TTL 缓存，不增加上游压力）


@dataclass(frozen=True)
class CacheEntry:
    value: object
    updated_at: float
    stored_at: float
    refresh_failed: bool = False
    source: str = "live"


class TTLCache:
    """带在途请求合并的 TTL 缓存；上游失败时回退过期数据。"""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self.data: dict = {}
        self.inflight: dict = {}
        self.lock = asyncio.Lock()

    async def get(self, key, factory, force=False):
        return (await self.get_entry(key, factory, force)).value

    async def _fetch(self, key, factory):
        started = time.time()
        try:
            value = await factory()
            entry = CacheEntry(value, started, time.monotonic())
            async with self.lock:
                self.data[key] = entry
            return entry
        except Exception:
            async with self.lock:
                hit = self.data.get(key)
                if hit is not None:
                    # 限制失败后的自动重试频率，但保留数据本身的采集时间。
                    entry = replace(hit, refresh_failed=True, stored_at=time.monotonic())
                    self.data[key] = entry
                    log.warning("上游 %s 抓取失败，回退过期缓存", key)
                    return entry
            raise
        finally:
            async with self.lock:
                self.inflight.pop(key, None)

    async def get_entry(self, key, factory, force=False):
        async with self.lock:
            hit = self.data.get(key)
            if hit and not force and time.monotonic() - hit.stored_at < self.ttl:
                return hit
            if key not in self.inflight:
                self.inflight[key] = asyncio.create_task(self._fetch(key, factory))
            fut = self.inflight[key]
        # 一个请求断开不能取消其他请求共用的上游任务。
        return await asyncio.shield(fut)


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


def board_response(entry: CacheEntry, ttl: int, items=None) -> dict:
    metadata = steamdata.data_meta(entry.updated_at, ttl, entry.source, entry.refresh_failed)
    values = entry.value if items is None else items
    if metadata["stale"]:
        values = [{**it, "surge": None, "spark": [], "surge_ready": False}
                  if "surge" in it else it for it in values]
    return {"meta": metadata, "items": values}


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
    if not NTFY_TOPIC:  # 留空 = 关闭推送（空 topic POST 到 ntfy.sh 根路径只会 400）
        return

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


async def search_board(key, fn, force=False, predicate=None, cache=None):
    cache = search_cache if cache is None else cache
    entry = await cache.get_entry(key, to_thread(fn), force=force)
    items = [it for it in entry.value if predicate is None or predicate(it)]
    items = [{**it, "rank": i + 1} for i, it in enumerate(items)]
    return board_response(entry, cache.ttl, items)


@app.get("/api/top-sellers")
async def api_top_sellers(force: bool = False):
    return await search_board("top_sellers", steamdata.fetch_search, force,
                              lambda it: it["price"]["final"])


@app.get("/api/specials")
async def api_specials(force: bool = False):
    return await search_board("specials", lambda: steamdata.fetch_search(True), force,
                              lambda it: it["price"]["final"])


@app.get("/api/free-to-keep")
async def api_free_to_keep(force: bool = False):
    return await search_board("free_to_keep", steamdata.fetch_free_to_keep, force,
                              lambda it: it["price"]["pct"] == -100)


@app.get("/api/new-releases")
async def api_new_releases(force: bool = False):
    return await search_board("new_releases", steamdata.fetch_new_releases, force,
                              lambda it: it["price"]["final"], cache=new_cache)


@app.get("/api/free-games")
async def api_free_games(force: bool = False):
    return await search_board("free_games", lambda: steamdata.fetch_search(free=True), force,
                              lambda it: it["price"]["final"] and it["price"]["free"])


@app.get("/api/epic-free")
async def api_epic_free(force: bool = False):
    return await search_board("epic_free", steamdata.fetch_epic_free, force)


async def refresh_most_played():
    try:
        await charts_cache.get_entry("most_played", to_thread(steamdata.build_most_played))
    except Exception:
        log.exception("最热榜后台刷新失败")


@app.get("/api/most-played")
async def api_most_played(force: bool = False):
    async with charts_cache.lock:
        hit = charts_cache.data.get("most_played")
        building = "most_played" in charts_cache.inflight
    if not force:
        if hit is not None:
            if time.monotonic() - hit.stored_at >= charts_cache.ttl and not building:
                asyncio.create_task(refresh_most_played())
            return board_response(hit, charts_cache.ttl)
        cached, built_at = await asyncio.to_thread(steamdata.load_cached_most_played)
        if cached:
            async with charts_cache.lock:
                entry = charts_cache.data.setdefault(
                    "most_played", CacheEntry(cached, built_at,
                                             time.monotonic() - charts_cache.ttl, source="disk")
                )
            if not building:
                asyncio.create_task(refresh_most_played())
            return board_response(entry, charts_cache.ttl)
    entry = await charts_cache.get_entry("most_played", to_thread(steamdata.build_most_played), force=force)
    return board_response(entry, charts_cache.ttl)


@app.get("/api/briefing")
async def api_briefing():
    mp = await api_most_played()
    facts = briefing_facts(mp["items"], [])
    facts["meta"] = mp["meta"]
    # 各数据源各自保留新鲜度；免费榜失败不能伪装成“没有活动”。
    try:
        ftk = await api_free_to_keep()
        facts.update(ftk_count=len(ftk["items"]),
                     ftk_names=[it["name"] for it in ftk["items"][:3]],
                     free_to_keep_meta=ftk["meta"])
    except Exception:
        facts.update(ftk_count=None, free_to_keep_meta=None)
    return facts


@app.get("/api/history/{appid}")
async def api_history(appid: int):
    return {"appid": appid, "points": steamdata.HISTORY.points(appid)}


@app.get("/healthz")
async def healthz():
    return {"ok": True, "ntfy": bool(NTFY_TOPIC), "history_games": len(steamdata.HISTORY.rings)}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
