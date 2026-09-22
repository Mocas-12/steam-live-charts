"""Steam 实时游戏榜单 —— FastAPI 后端。

数据全部来自 Steam 官方公开接口，进程内 TTL 缓存限流：
- 最热游玩:  ISteamChartsService/GetMostPlayedGames (Top100, 峰值榜)
             + ISteamUserStats/GetNumberOfCurrentPlayers (逐款实时在线, 60s 缓存)
             + store appdetails (游戏名/价格/类型, 10min 缓存)
- 热销商品:  store search sort_by=TopSellers (50 条, 含价格折扣)
- 特惠专区:  同上 + specials=1 (50 条折扣游戏按畅销排序)
"""

import asyncio
import html as htmllib
import re
import time

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

STEAM_API = "https://api.steampowered.com"
STEAM_STORE = "https://store.steampowered.com"
CC, LANG = "cn", "schinese"
HEADER_IMG = "https://cdn.cloudflare.steamstatic.com/steam/apps/{}/header.jpg"
STORE_URL = "https://store.steampowered.com/app/{}/"

REFRESH_SECONDS = 60  # 前端轮询节奏，与最热榜缓存一致


class TTLCache:
    """带在途请求合并的 TTL 缓存；上游失败时回退过期数据。"""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self.data: dict = {}
        self.inflight: dict = {}
        self.lock = asyncio.Lock()

    async def get(self, key, factory):
        async with self.lock:
            hit = self.data.get(key)
            if hit and time.monotonic() - hit[0] < self.ttl:
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

app = FastAPI(title="Steam 实时游戏榜单")


def meta() -> dict:
    return {"updated_at": int(time.time()), "ttl": REFRESH_SECONDS}


# ---------- 基础数据源 ----------

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
        "price": _price_from_overview(data.get("price_overview"), data.get("is_free")),
    }


def _price_from_overview(po: dict | None, is_free: bool) -> dict | None:
    if is_free:
        return {"free": True, "final": "免费开玩", "original": None, "pct": None}
    if not po:
        return None
    pct = po.get("discount_percent") or 0
    final = _clean_price(po.get("final_formatted") or "") or _clean_price(f"¥{po.get('final', 0) / 100}")
    return {
        "free": False,
        "final": final,
        "original": _clean_price(f"¥{po['initial'] / 100}") if pct else None,
        "pct": -pct if pct else None,
    }


async def fetch_name_from_community(appid: int) -> str | None:
    """已下架/区域锁定的游戏 appdetails 拿不到名字，从社区页标题兜底。"""
    r = await client.get(f"https://steamcommunity.com/app/{appid}")
    r.raise_for_status()
    m = re.search(r"<title>([^<]+)</title>", r.text)
    if not m:
        return None
    title = m.group(1).strip()
    name = title.split("::")[-1].strip()
    if name in ("Steam 社区", "Steam Community", ""):  # 无独立社区页的游戏
        return None
    return name


# ---------- 搜索页解析（热销 / 特惠） ----------

ROW_RE = re.compile(
    r'<a href="https://store\.steampowered\.com/app/(\d+)/[^"]*"[^>]*?'
    r'class="search_result_row[^"]*"(.*?)</a>',
    re.S,
)


def _clean_price(text: str) -> str | None:
    t = htmllib.unescape(text).strip().replace(" ", "")
    if not t:
        return None
    if "免费" in t or t.lower() == "free":
        return "免费开玩"
    if "¥" in t:
        t = t.replace(".00", "")
    return t


def parse_search_rows(results_html: str) -> list[dict]:
    items = []
    for m in ROW_RE.finditer(results_html):
        aid = int(m.group(1))
        block = m.group(2)
        title = re.search(r'<span class="title">([^<]+)</span>', block)
        if not title:
            continue
        pct = re.search(r'class="discount_pct">\s*(-?\d+)%', block)
        orig = re.search(r'class="discount_original_price">\s*([^<]+?)\s*<', block)
        fin = re.search(r'class="discount_final_price[^"]*">\s*([^<]+?)\s*<', block)
        img = re.search(r'<img[^>]+src="([^"]+capsule[^"]+?)"', block)
        final = _clean_price(fin.group(1)) if fin else None
        items.append(
            {
                "appid": aid,
                "name": htmllib.unescape(title.group(1)).strip(),
                "image": img.group(1) if img else HEADER_IMG.format(aid),
                "url": STORE_URL.format(aid),
                "price": {
                    "free": final == "免费开玩",
                    "final": final,
                    "original": _clean_price(orig.group(1)) if orig else None,
                    "pct": int(pct.group(1)) if pct else None,
                },
            }
        )
    return items


async def fetch_search(specials: bool) -> list[dict]:
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
    r = await client.get(f"{STEAM_STORE}/search/results/", params=params)
    r.raise_for_status()
    return parse_search_rows(r.json()["results_html"])


# ---------- API 路由 ----------

@app.get("/api/top-sellers")
async def api_top_sellers():
    items = await search_cache.get("top_sellers", lambda: fetch_search(False))
    items = [
        {**it, "rank": i + 1} for i, it in enumerate(items) if it["price"]["final"]
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/specials")
async def api_specials():
    items = await search_cache.get("specials", lambda: fetch_search(True))
    items = [
        {**it, "rank": i + 1} for i, it in enumerate(items) if it["price"]["final"]
    ]
    return {"meta": meta(), "items": items}


@app.get("/api/most-played")
async def api_most_played():
    ranks = await charts_cache.get("ranks", fetch_most_played)

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
