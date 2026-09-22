"""Steam 数据抓取（同步版）：FastAPI 端与 Streamlit 端共用的数据层。

接口选型实测结论（2026-09-22）：
- ISteamApps/GetAppList 已下线（404），批量 appdetails 不可用（返回 null），只能单款查询
- 免费游戏的 data-price-final 是 DLC 价格（CS2=10300），真实标价在 discount_final_price 文本
- 新游戏封面必须用哈希化 store_item_assets 地址，旧版 CDN 路径对新游戏 404
- 已下架/区域锁游戏（appdetails success:false）从 steamcommunity.com/app/{id} 标题兜底名字
"""

import html as htmllib
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

STEAM_API = "https://api.steampowered.com"
STEAM_STORE = "https://store.steampowered.com"
CC, LANG = "cn", "schinese"
HEADER_IMG = "https://cdn.cloudflare.steamstatic.com/steam/apps/{}/header.jpg"  # 兜底
STORE_URL = "https://store.steampowered.com/app/{}/"

_client: httpx.Client | None = None


def get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "steam-live-charts/1.0", "Accept-Language": "zh-CN,zh;q=0.9"},
            follow_redirects=True,
        )
    return _client


def _clean_price(text: str) -> str | None:
    t = htmllib.unescape(text).strip().replace(" ", "")
    if not t:
        return None
    if "免费" in t or t.lower() == "free":
        return "免费开玩"
    if "¥" in t:
        try:
            v = float(t.replace("¥", "").replace(",", ""))
            t = "¥" + f"{v:.2f}".rstrip("0").rstrip(".")
        except ValueError:
            pass
    return t


def price_from_overview(po: dict | None, is_free: bool) -> dict | None:
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


# ---------- 搜索页解析（热销 / 特惠 / 新品 / 免费 / 限时免费） ----------

ROW_RE = re.compile(
    r'<a href="https://store\.steampowered\.com/app/(\d+)/[^"]*"[^>]*class="search_result_row[^"]*"',
    re.S,
)

_tag_map: dict[int, str] | None = None
_tag_ts = 0.0


def get_tag_map() -> dict[int, str]:
    """StoreTag id → 中文名（24h 缓存，失败时退化为空映射）。"""
    global _tag_map, _tag_ts
    if _tag_map is not None and time.monotonic() - _tag_ts < 24 * 3600:
        return _tag_map
    try:
        r = get_client().get(f"{STEAM_STORE}/tagdata/populartags/{LANG}")
        r.raise_for_status()
        _tag_map = {int(t["tagid"]): t["name"] for t in r.json()}
        _tag_ts = time.monotonic()
    except Exception:
        if _tag_map is None:
            _tag_map = {}
        _tag_ts = time.monotonic()
    return _tag_map


def _clean_price(text: str) -> str | None:
    t = htmllib.unescape(text).strip().replace(" ", "")
    if not t:
        return None
    if "免费" in t or t.lower() == "free":
        return "免费开玩"
    if "¥" in t:
        try:
            v = float(t.replace("¥", "").replace(",", ""))
            t = "¥" + f"{v:.2f}".rstrip("0").rstrip(".")
        except ValueError:
            pass
    return t


def parse_search_rows(results_html: str) -> list[dict]:
    tmap = get_tag_map()
    items = []
    for m in ROW_RE.finditer(results_html):
        aid = int(m.group(1))
        start = m.end()
        end = results_html.find("</a>", start)
        block = results_html[start:end]
        title = re.search(r'<span class="title">([^<]+)</span>', block)
        if not title:
            continue
        pct = re.search(r'class="discount_pct">\s*(-?\d+)%', block)
        orig = re.search(r'class="discount_original_price">\s*([^<]+?)\s*<', block)
        fin = re.search(r'class="discount_final_price[^"]*">\s*([^<]+?)\s*<', block)
        img = re.search(r'<img[^>]+src="([^"]+capsule[^"]+?)"', block)
        tags = re.search(r'data-ds-tagids="\[([\d,]+)\]"', m.group(0))
        released = re.search(r'search_released[^>]*>\s*([^<]+?)\s*<', block)
        final = _clean_price(fin.group(1)) if fin else None
        genres = []
        if tags:
            for tid in tags.group(1).split(","):
                name = tmap.get(int(tid))
                if name and name not in genres:
                    genres.append(name)
                if len(genres) == 3:
                    break
        items.append(
            {
                "appid": aid,
                "name": htmllib.unescape(title.group(1)).strip(),
                "image": img.group(1) if img else HEADER_IMG.format(aid),
                "url": STORE_URL.format(aid),
                "genres": genres,
                "released": released.group(1).strip() if released else None,
                "price": {
                    "free": final == "免费开玩",
                    "final": final,
                    "original": _clean_price(orig.group(1)) if orig else None,
                    "pct": int(pct.group(1)) if pct else None,
                },
            }
        )
    return items


# ---------- 单项抓取 ----------

def fetch_search(specials: bool = False, free: bool = False, sort: str = "TopSellers") -> list[dict]:
    params = {
        "query": "",
        "start": 0,
        "count": 50,
        "dynamic_data": "",
        "sort_by": sort,
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
    r = get_client().get(f"{STEAM_STORE}/search/results/", params=params)
    r.raise_for_status()
    return parse_search_rows(r.json()["results_html"])


def fetch_free_to_keep() -> list[dict]:
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
    r = get_client().get(f"{STEAM_STORE}/search/results/", params=params)
    r.raise_for_status()
    rows = parse_search_rows(r.json()["results_html"])
    return [it for it in rows if it["price"]["pct"] == -100]


def fetch_new_releases() -> list[dict]:
    """新品上架：按上架时间排序的最新游戏（50 条，含类型/发售日期/价格）。"""
    rows = fetch_search(sort="Released_DESC")
    out = []
    for it in rows:
        if not it["price"]["final"]:
            continue
        low = it["name"].lower()
        if "demo" in low or "playtest" in low or "试玩" in it["name"] or "测试" in it["name"]:
            continue  # 过滤 Demo / 试玩版
        out.append(it)
    return out[:30]
def fetch_detail(appid: int) -> dict | None:
    r = get_client().get(
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


def fetch_name_from_community(appid: int) -> str | None:
    """已下架/区域锁定的游戏 appdetails 拿不到名字，从社区页标题兜底。"""
    r = get_client().get(f"https://steamcommunity.com/app/{appid}")
    r.raise_for_status()
    m = re.search(r"<title>([^<]+)</title>", r.text)
    if not m:
        return None
    name = m.group(1).strip().split("::")[-1].strip()
    if name in ("Steam 社区", "Steam Community", ""):  # 无独立社区页的游戏
        return None
    return name


def build_most_played(top_n: int = 100) -> list[dict]:
    """Top N 最热游玩：官方榜 + 逐款实时在线（并发 20）+ 详情（并发 15）。

    官方 rank 是每日快照，与实时在线数有出入；实时榜单按当前在线重排。
    """
    ranks = fetch_most_played()[:top_n]

    def safe(fn, *a):
        try:
            return fn(*a)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=20) as ex:
        players = list(ex.map(lambda r: safe(fetch_ccu, r["appid"]), ranks))
    with ThreadPoolExecutor(max_workers=15) as ex:
        details = list(ex.map(lambda r: safe(fetch_detail, r["appid"]), ranks))

    detail_by_id = {}
    name_cache: dict[int, str] = {}

    items = []
    for r, ccu, detail in zip(ranks, players, details):
        appid = r["appid"]
        detail = detail or {}
        name = detail.get("name")
        if not name:
            if appid not in name_cache:
                name_cache[appid] = safe(fetch_name_from_community, appid)
            name = name_cache[appid]
        last = r.get("last_week_rank", -1)
        items.append(
            {
                "appid": appid,
                "name": name or f"App {appid}",
                "image": detail.get("image") or HEADER_IMG.format(appid),
                "url": STORE_URL.format(appid),
                "genres": detail.get("genres") or [],
                "price": detail.get("price"),
                "players": ccu,
                "peak": r.get("peak_in_game"),
                "delta": (last - r["rank"]) if last > 0 else None,
                "is_new": last == -1,
            }
        )
    items.sort(key=lambda it: it["players"] if it["players"] is not None else -1, reverse=True)
    return [{**it, "rank": i + 1} for i, it in enumerate(items)]
