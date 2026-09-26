"""Steam 数据抓取（同步版）：FastAPI 端与 Streamlit 端共用的数据层。

接口选型实测结论（2026-09-22）：
- ISteamApps/GetAppList 已下线（404），批量 appdetails 不可用（返回 null），只能单款查询
- 免费游戏的 data-price-final 是 DLC 价格（CS2=10300），真实标价在 discount_final_price 文本
- 新游戏封面必须用哈希化 store_item_assets 地址，旧版 CDN 路径对新游戏 404
- 已下架/区域锁游戏（appdetails success:false）从 steamcommunity.com/app/{id} 标题兜底名字
"""

import html as htmllib
import json
import logging
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# ---------- 磁盘缓存：冷启动零等待的关键 ----------
#
# cache/details_seed.json        每日快照 job 提交进仓库的详情种子（随部署分发）
# cache/details_live.json        运行时抓到的详情热身文件（gitignore，进程重启不丢）
# cache/last_most_played.json    最近一次成功构建的完整榜单（gitignore）
# cache/last_most_played_seed.json  同上的种子版（每日 job 刷新）
#
# 冷启动顺序：读热身/种子 -> 立即出完整榜单（标注数据时间）-> 后台重建为实时。
CACHE_DIR = Path("cache")
DETAILS_SEED = CACHE_DIR / "details_seed.json"
DETAILS_LIVE = CACHE_DIR / "details_live.json"
LAST_MP_SEED = CACHE_DIR / "last_most_played_seed.json"
LAST_MP_LIVE = CACHE_DIR / "last_most_played.json"
SEED_DETAIL_TTL = 36 * 3600  # 种子详情（名字/封面/类型）老化期；价格由每日 job 保持新鲜


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _dump_json(path: Path, obj) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    except Exception as e:
        log.debug("cache write %s: %s", path, e)

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


def _get_backoff(url: str, **kwargs):
    """GET；429/403（Steam 对 Cloud IP 限流）退避 2s 重试一次。"""
    client = get_client()
    r = client.get(url, **kwargs)
    if r.status_code in (429, 403):
        time.sleep(2)
        r = client.get(url, **kwargs)
    r.raise_for_status()
    return r


def price_from_overview(po: dict | None, is_free: bool) -> dict | None:
    if is_free:
        return {"free": True, "final": "免费开玩", "original": None, "pct": None}
    if not po:
        return None
    pct = po.get("discount_percent") or 0
    initial = po.get("initial")
    final = _clean_price(po.get("final_formatted") or "") or _clean_price(f"¥{po.get('final', 0) / 100}")
    return {
        "free": False,
        "final": final,
        "original": _clean_price(f"¥{initial / 100}") if pct and initial else None,
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
    t = htmllib.unescape(text).strip().replace(" ", "").replace("￥", "¥")
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
    r = _get_backoff(f"{STEAM_STORE}/search/results/", params=params)
    rows = parse_search_rows(r.json()["results_html"])
    if not rows:
        # HTTP 成功但一行都没解析出来：多半是 Steam 改了页式。宁可抛错让上层
        # TTLCache 回退旧数据，也不能让榜单静默变空（看起来像"没数据"）
        raise RuntimeError(f"搜索页解析 0 行（HTTP {r.status_code}），Steam 页式可能已变更")
    return rows


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
    r = _get_backoff(f"{STEAM_STORE}/search/results/", params=params)
    html = r.json()["results_html"]
    rows = parse_search_rows(html)
    # 实测（2026-09-25）：无活动时 Steam 返回 ~45 字节的空页；页面很大却 0 行才是页式变更
    if len(html) > 1000 and not rows:
        raise RuntimeError(
            f"搜索页解析 0 行（HTTP {r.status_code}，页面 {len(html)} 字节），Steam 页式可能已变更"
        )
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
def fetch_most_played() -> list[dict]:
    r = _get_backoff(f"{STEAM_API}/ISteamChartsService/GetMostPlayedGames/v1/")
    return r.json()["response"]["ranks"]


def fetch_ccu(appid: int) -> int:
    r = _get_backoff(
        f"{STEAM_API}/ISteamUserStats/GetNumberOfCurrentPlayers/v1/", params={"appid": appid}
    )
    r.raise_for_status()
    return r.json()["response"].get("player_count", 0)


_detail_store: dict[int, tuple[float, dict | None]] = {}
DETAIL_TTL = 1800  # 详情 30min 缓存：价格/类型变化慢，也避免反复触发限流


def _warm_detail_store() -> None:
    """进程启动时从磁盘预热详情缓存（热身文件优先，种子兜底）。

    冷启动从此不用为 100 款游戏逐个打 appdetails（限流重灾区，实测能把
    构建拖到两分钟以上）；种子由每日快照 job 刷新，仅限默认区域配置。
    """
    if (CC, LANG) != ("cn", "schinese"):
        return
    now = time.time()
    for path, ttl in ((DETAILS_LIVE, DETAIL_TTL * 48), (DETAILS_SEED, SEED_DETAIL_TTL)):
        data = _load_json(path)
        if not data:
            continue
        for k, entry in data.items():
            try:
                appid = int(k)
                ts = float(entry["ts"])
                detail = entry.get("d")
            except (KeyError, TypeError, ValueError):
                continue
            if now - ts > ttl or appid in _detail_store:
                continue
            _detail_store[appid] = (ts, detail)


_warm_detail_store()


_persist_lock = threading.Lock()


def _persist_detail(appid: int, ts: float, detail: dict | None) -> None:
    """抓取结果落盘：从内存全表重建（并发安全，避免整表互相覆盖）。"""
    if (CC, LANG) != ("cn", "schinese"):
        return
    with _persist_lock:
        snapshot = {
            str(a): {"ts": t, "d": d}
            for a, (t, d) in _detail_store.items()
            if d is not None
        }
        _dump_json(DETAILS_LIVE, snapshot)


def _persist_detail_store() -> None:
    """构建结束统一落盘一次（确保全部成功条目都进热身文件）。"""
    _persist_detail(0, 0.0, None)


def fetch_detail_cached(appid: int, max_age: float = DETAIL_TTL) -> dict | None:
    now = time.time()
    hit = _detail_store.get(appid)
    if hit and now - hit[0] < max_age:
        return hit[1]
    detail = fetch_detail(appid)
    _detail_store[appid] = (now, detail)
    _persist_detail(appid, now, detail)
    return detail


def fetch_detail(appid: int, _retry: bool = True) -> dict | None:
    r = _get_backoff(
        f"{STEAM_STORE}/api/appdetails", params={"appids": appid, "cc": CC, "l": LANG}
    )
    r.raise_for_status()
    data = r.json().get(str(appid), {}).get("data")
    if not data and _retry:
        time.sleep(0.8)
        return fetch_detail(appid, _retry=False)
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
    r = _get_backoff(f"https://steamcommunity.com/app/{appid}")
    m = re.search(r"<title>([^<]+)</title>", r.text)
    if not m:
        return None
    name = m.group(1).strip().split("::")[-1].strip()
    if name in ("Steam 社区", "Steam Community", ""):  # 无独立社区页的游戏
        return None
    return name


_name_store: dict[int, tuple[float, str | None]] = {}
NAME_TTL = 24 * 3600  # 名字几乎不变；仅缓存成功结果，失败下个周期重试


def fetch_name_cached(appid: int) -> str | None:
    hit = _name_store.get(appid)
    if hit and time.monotonic() - hit[0] < NAME_TTL:
        return hit[1]
    try:
        name = fetch_name_from_community(appid)
    except Exception as e:
        log.debug("community name %s: %s", appid, e)
        return None
    _name_store[appid] = (time.monotonic(), name)
    return name


def build_most_played(top_n: int = 100) -> list[dict]:
    """Top N 最热游玩：官方榜 + 逐款实时在线（并发 20）+ 详情（并发 15）。

    官方 rank 是每日快照，与实时在线数有出入；实时榜单按当前在线重排。
    """
    ranks = fetch_most_played()[:top_n]

    def safe(fn, *a):
        try:
            return fn(*a)
        except Exception as e:
            log.debug("%s failed: %s", getattr(fn, "__name__", fn), e)
            return None

    with ThreadPoolExecutor(max_workers=20) as ex:
        players = list(ex.map(lambda r: safe(fetch_ccu, r["appid"]), ranks))
    with ThreadPoolExecutor(max_workers=15) as ex:
        # 详情信任磁盘预热（36h 内直接用，冷启动零 appdetails 请求），完全 miss 才抓
        details = list(
            ex.map(lambda r: safe(fetch_detail_cached, r["appid"], 36 * 3600), ranks)
        )

    items = []
    for r, ccu, detail in zip(ranks, players, details):
        appid = r["appid"]
        detail = detail or {}
        name = detail.get("name")
        if not name:
            name = fetch_name_cached(appid)
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
    items = [{**it, "rank": i + 1} for i, it in enumerate(items)]
    HISTORY.sample(items)  # 24h 滚动采样：双端（FastAPI/Streamlit）共用同一份内存环
    for it in items:
        it["spark"] = HISTORY.spark(it["appid"])
        it["surge"] = surge_pct(it["appid"])
    _persist_detail_store()  # 本轮全部详情落盘（并发下单条写有覆盖，此处兜底全量）
    _dump_json(LAST_MP_LIVE, {"built_at": time.time(), "items": items})
    return items


def load_cached_most_played(max_age: float = 26 * 3600):
    """最近一次成功构建的完整榜单（热身文件优先，种子兜底）。

    冷启动零等待路径：返回 (items, built_at)；过期/缺失返回 (None, None)。
    """
    now = time.time()
    for path in (LAST_MP_LIVE, LAST_MP_SEED):
        data = _load_json(path)
        if not data:
            continue
        built_at = float(data.get("built_at") or 0)
        items = data.get("items")
        if items and now - built_at < max_age:
            return items, built_at
    return None, None


def write_detail_seed(path: Path = DETAILS_SEED) -> None:
    """把内存详情缓存整表落盘为仓库种子（每日快照 job 调用）。"""
    data = {str(a): {"ts": ts, "d": d} for a, (ts, d) in _detail_store.items() if d}
    _dump_json(path, data)
    return None


# ---------- 24h 在线采样 + 异动分析（双端共享） ----------


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

    采样随榜单重建发生（60s TTL 天然限频，min_interval 兜底去重），
    内存保留 1440 点，进程重启归零——曲线与异动从"采样中"逐渐长出来是预期行为。
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

    def points(self, appid: int) -> list[tuple[float, int]]:
        ring = self.rings.get(appid)
        return [(ts, p) for ts, p in ring] if ring else []


HISTORY = HistoryRing()

# 异动判定：最近 30 分钟均值 vs 之前 2 小时基线，涨 30% 且基线≥200 人才算
# （基线下限过滤小基数噪声；攒够 ~2.5h 采样才开始识别，之前返回 None）
SURGE_RECENT, SURGE_BASELINE, SURGE_RATIO, SURGE_FLOOR = 30, 120, 1.3, 200


def surge_pct(appid: int) -> int | None:
    vals = [p for _, p in HISTORY.rings.get(appid, ())]
    need = SURGE_RECENT + SURGE_BASELINE
    if len(vals) < need:
        return None
    base = vals[-need:-SURGE_RECENT]
    rec = vals[-SURGE_RECENT:]
    bmean = sum(base) / len(base)
    rmean = sum(rec) / len(rec)
    if bmean < SURGE_FLOOR or rmean < bmean * SURGE_RATIO:
        return None
    return round((rmean / bmean - 1) * 100)


def briefing_facts(mp_items: list[dict], ftk_items: list[dict]) -> dict:
    """今日速览聚合：只消费已抓好的榜单数据，不发任何网络请求。"""
    surges = sorted(
        (
            {"appid": it["appid"], "name": it["name"], "url": it["url"],
             "pct": it["surge"], "players": it.get("players")}
            for it in mp_items
            if it.get("surge")
        ),
        key=lambda s: s["pct"],
        reverse=True,
    )[:3]
    return {
        "total_online": sum(it.get("players") or 0 for it in mp_items),
        "new_entries": sum(1 for it in mp_items if it.get("is_new")),
        "surges": surges,
        "ftk_count": len(ftk_items),
        "ftk_names": [it["name"] for it in ftk_items[:3]],
        "sampling": sum(1 for it in mp_items if it.get("surge") is None),
    }
