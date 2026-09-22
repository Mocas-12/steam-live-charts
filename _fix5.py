# steamdata：详情请求加重试 + 30min 进程内缓存（缓解 Cloud IP 限流）
p = 'steamdata.py'
s = open(p, encoding='utf-8').read()

old = '''def fetch_detail(appid: int) -> dict | None:
    r = get_client().get(
        f"{STEAM_STORE}/api/appdetails", params={"appids": appid, "cc": CC, "l": LANG}
    )
    r.raise_for_status()
    data = r.json().get(str(appid), {}).get("data")
    if not data:
        return None
    return {'''
new = '''_detail_store: dict[int, tuple[float, dict | None]] = {}
DETAIL_TTL = 1800  # 详情 30min 缓存：价格/类型变化慢，也避免反复触发限流


def fetch_detail_cached(appid: int) -> dict | None:
    now = time.monotonic()
    hit = _detail_store.get(appid)
    if hit and now - hit[0] < DETAIL_TTL:
        return hit[1]
    detail = fetch_detail(appid)
    _detail_store[appid] = (now, detail)
    return detail


def fetch_detail(appid: int, _retry: bool = True) -> dict | None:
    r = get_client().get(
        f"{STEAM_STORE}/api/appdetails", params={"appids": appid, "cc": CC, "l": LANG}
    )
    r.raise_for_status()
    data = r.json().get(str(appid), {}).get("data")
    if not data and _retry:
        time.sleep(0.8)
        return fetch_detail(appid, _retry=False)
    if not data:
        return None
    return {'''
assert old in s
s = s.replace(old, new)

# build_most_played 走缓存版
old = "details = list(ex.map(lambda r: safe(fetch_detail, r[\"appid\"]), ranks))"
new = "details = list(ex.map(lambda r: safe(fetch_detail_cached, r[\"appid\"]), ranks))"
assert old in s
s = s.replace(old, new)

open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('steamdata detail cache added')
