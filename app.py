"""Steam 实时游戏榜单 —— FastAPI 后端（本地/自托管用）。

共享数据逻辑在 steamdata.py（同步版，Streamlit 端 streamlit_app.py 复用同一套解析），
本文件只负责异步抓取 + TTL 缓存 + 静态前端托管：
- 热销商品:  store search sort_by=TopSellers (50 条, 含价格折扣)
- 特惠专区:  同上 + specials=1 (50 条折扣游戏按畅销排序)
- 新品上架:  featuredcategories new_releases (精选 30 条, 含价格/封面)
- 免费游戏:  同热销 + maxprice=free (过滤免费试玩, 50 条按畅销排序)
- 最热游玩:  ISteamChartsService/GetMostPlayedGames (Top100, 峰值榜)
             + ISteamUserStats/GetNumberOfCurrentPlayers (逐款实时在线, 60s 缓存)
             + store appdetails (游戏名/价格/类型, 10min 缓存)
"""

import asyncio
import re
import time

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from steamdata import (
    CC,
    HEADER_IMG,
    LANG,
    STORE_URL,
    STEAM_API,
    STEAM_STORE,
    _clean_price,
    parse_search_rows,
    price_from_overview,
)

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
                return hit[1]
            raise
        async with self.lock:
            self.data[key] = (time.monotonic(), value)
            self.inflight.pop(key, None)
        return value


client = httpx.AsyncClient(
    timeout=httpx.Timeout(20.0),
    headers={"User-Agent": "steam-live-charts/1.0", "Accept-Language": "zh-CN,zh;q=0.9"},
    follow_redirects=True,
)

charts_cache = TTLCache(REFRESH_SECONDS)
ccu_cache = TTLCache(REFRESH_SECONDS)
detail_cache = TTLCache(600)
search_cache = TTLCache(120)
name_cache = TTLCache(24 * 3600)
new_cache = TTLCache(600)

app = FastAPI(title="Steam 实时游戏榜单")


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


# ---------- 基础数据源（异步版） ----------

async def fetch_most_played() -> list[dict]:
    r = await client.get(f"{STEAM_API}/ISteamChartsService/GetMostPlayedGames/v1/")
    r.raise_for_status()
    return r.json()["response"]["ranks"]


async def fetch_ccu(appid: int) -> int:
    r = await client.get(
        f"{STEAM_API}/ISteamUserStats/GetNumberOfCurrentPlayers/v1/", params={"appid": appid}
    )
    r.raise_for_status()
    return r.json()["response"].get("player_count", 0)


async def fetch_detail(appid: int) -> dict | None:
    r = await client.get(
        f"{STEAM_STORE}/api/appdetails", params={"appids": appid, "cc": CC, "l": LANG}
    )
    r.raise_for_status()
    data = r.json().get(str(appid), {}).get("data")
    if not data:
        return None
    return {
        "name": data.get("name"),
        "image": data.get("header_image"),
        "genres": [
            g["description"] for g in data.get("genres", [])
            if g["description"] not in ("免费开玩", "Free to Play")
        ][:3],
        "price": price_from_overview(data.get("price_overview"), data.get("is_free")),
    }


async def fetch_name_from_community(appid: int) -> str | None:
    """已下架/区域锁定的游戏 appdetails 拿不到名字，从社区页标题兜底。"""
    r = await client.get(f"https://steamcommunity.com/app/{appid}")
    r.raise_for_status()
    m = re.search(r"<title>([^<]+)</title>", r.text)
    if not m:
        return None
    name = m.group(1).strip().split("::")[-1].strip()
    if name in ("Steam 社区", "Steam Community", ""):  # 无独立社区页的游戏
        return None
    return name


async def fetch_search(specials: bool, free: bool = False) -> list[dict]:
    params = {
        "query": "",
        "start": 0,
        "count": 50,
        "dynamic_data": "",
        "sort_by": "TopSellers",
        "supportedlang": "schinese",
        "l": LANG,
        "snr": "1_7_7_700_702",
        "infinite": 1,
        "cc": CC,
    }
    if specials:
        params["specials"] = 1
    if free:
        params["maxprice"] = "free"
    r = await client.get(f"{STEAM_STORE}/search/results/", params=params)
    r.raise_for_status()
    return parse_search_rows(r.json()["results_html"])


async def fetch_free_to_keep() -> list[dict]:
    """限时免费入库：原价付费、当前 100% 折扣免费入库的游戏。

    Steam 没有现成榜单，用 search 的 specials=1 与 maxprice=free 的交集，
    再只留 -100% 折扣行（平时 0~10 个，需要空状态兜底）。
    """
    params = {
        "query": "",
        "start": 0,
        "count": 100,
        "dynamic_data": "",
        "sort_by": "TopSellers",
        "supportedlang": "schinese",
        "l": LANG,
        "snr": "1_7_7_700_702",
        "infinite": 1,
        "cc": CC,
        "specials": 1,
        "maxprice": "free",
    }
    r = await client.get(f"{STEAM_STORE}/search/results/", params=params)
    r.raise_for_status()
    rows = parse_search_rows(r.json()["results_html"])
    return [it for it in rows if it["price"]["pct"] == -100]


async def fetch_new_releases() -> list[dict]:
    """新品上架：商店精选每周新品（featuredcategories，30 条，含价格/封面）。"""
    r = await client.get(f"{STEAM_STORE}/api/featuredcategories/", params={"cc": CC, "l": LANG})
    r.raise_for_status()
    items = r.json().get("new_releases", {}).get("items", [])
    out = []
    for it in items:
        try:
            aid = int(it["id"])
        except (KeyError, TypeError, ValueError):
            continue
        pct = it.get("discount_percent") or 0
        final_cents = it.get("final_price") or 0
        if final_cents == 0:
            price = {"free": True, "final": "免费开玩", "original": None, "pct": None}
        else:
            price = {
                "free": False,
                "final": _clean_price(f"¥{final_cents / 100}"),
                "original": _clean_price(f"¥{it['original_price'] / 100}") if pct else None,
                "pct": -pct if pct else None,
            }
        out.append(
            {
                "appid": aid,
                "name": str(it.get("name", "")).strip(),
                "image": it.get("header_image") or HEADER_IMG.format(aid),
                "url": STORE_URL.format(aid),
                "price": price,
            }
        )
    return out


# ---------- API 路由 ----------

@app.get("/api/top-sellers")
async def api_top_sellers(force: bool = False):
    items = await search_cache.get("top_sellers", lambda: fetch_search(False), force=force)
    items = [
        {**it, "rank": i + 1} for i, it in enumerate(items) if it["price"]["final"]
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/specials")
async def api_specials(force: bool = False):
    items = await search_cache.get("specials", lambda: fetch_search(True), force=force)
    items = [
        {**it, "rank": i + 1} for i, it in enumerate(items) if it["price"]["final"]
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/free-to-keep")
async def api_free_to_keep(force: bool = False):
    items = await search_cache.get("free_to_keep", fetch_free_to_keep, force=force)
    items = [
        {**it, "rank": i + 1}
        for i, it in enumerate(items)
        if it["price"]["pct"] == -100
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/new-releases")
async def api_new_releases(force: bool = False):
    items = await new_cache.get("new_releases", fetch_new_releases, force=force)
    items = [
        {**it, "rank": i + 1} for i, it in enumerate(items) if it["price"]["final"]
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/free-games")
async def api_free_games(force: bool = False):
    items = await search_cache.get("free_games", lambda: fetch_search(False, free=True), force=force)
    items = [
        {**it, "rank": i + 1}
        for i, it in enumerate(items)
        if it["price"]["final"] and it["price"]["free"]  # 过滤混入的免费试玩付费游戏
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/most-played")
async def api_most_played(force: bool = False):
    ranks = await charts_cache.get("ranks", fetch_most_played, force=force)

    ccu_sem = asyncio.Semaphore(20)
    detail_sem = asyncio.Semaphore(15)

    async def enrich(r: dict) -> dict:
        appid = r["appid"]
        async with ccu_sem:
            try:
                players = await ccu_cache.get(f"ccu:{appid}", lambda: fetch_ccu(appid))
            except Exception:
                players = None
        async with detail_sem:
            try:
                detail = await detail_cache.get(f"d:{appid}", lambda: fetch_detail(appid))
            except Exception:
                detail = None
        name = (detail or {}).get("name")
        if not name:
            try:
                name = await name_cache.get(f"n:{appid}", lambda: fetch_name_from_community(appid))
            except Exception:
                name = None
        last = r.get("last_week_rank", -1)
        return {
            "rank": r["rank"],
            "appid": appid,
            "name": name or f"App {appid}",
            "image": (detail or {}).get("image") or HEADER_IMG.format(appid),
            "url": STORE_URL.format(appid),
            "genres": (detail or {}).get("genres") or [],
            "price": (detail or {}).get("price"),
            "players": players,
            "peak": r.get("peak_in_game"),
            "delta": (last - r["rank"]) if last > 0 else None,  # 正数=较上周上升
            "is_new": last == -1,
        }

    items = await asyncio.gather(*(enrich(r) for r in ranks))
    # 官方 rank 是每日快照，与实时在线数有出入；实时榜单按当前在线重排
    items = sorted(items, key=lambda it: it["players"] if it["players"] is not None else -1, reverse=True)
    items = [{**it, "rank": i + 1} for i, it in enumerate(items)]
    return {"meta": meta(), "items": items}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
