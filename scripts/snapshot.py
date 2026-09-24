"""每日榜单快照：抓六榜精华字段写入 archive/YYYY-MM-DD.json。

GitHub Actions 每天北京时间 00:00（UTC 16:00）自动跑并提交；
本地手动跑：  python scripts/snapshot.py [--outdir archive]
只留 rank/appid/name/在线/价格精华字段，单日约 20KB。
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根，便于 scripts/ 直跑

import steamdata as sd

_CN_TZ = timezone(timedelta(hours=8))


def _trim_most_played(items):
    return [
        {
            "rank": it["rank"],
            "appid": it["appid"],
            "name": it["name"],
            "players": it["players"],
            "peak": it["peak"],
            "price": (it.get("price") or {}).get("final"),
        }
        for it in items
    ]


def _trim_search(items):
    return [
        {
            "rank": i + 1,
            "appid": it["appid"],
            "name": it["name"],
            "pct": it["price"]["pct"],
            "price": it["price"]["final"],
        }
        for i, it in enumerate(items)
    ]


def build_snapshot():
    return {
        "generated_at": int(time.time()),
        "generated_at_cn": datetime.now(_CN_TZ).strftime("%Y-%m-%d %H:%M:%S CST"),
        "boards": {
            "most-played": _trim_most_played(sd.build_most_played()),
            "top-sellers": _trim_search(sd.fetch_search(False)),
            "specials": _trim_search(sd.fetch_search(True)),
            "new-releases": _trim_search(sd.fetch_new_releases()),
            "free-games": _trim_search(sd.fetch_search(False, free=True)),
            "free-to-keep": _trim_search(sd.fetch_free_to_keep()),
        },
    }


def main():
    ap = argparse.ArgumentParser(description="抓取六榜快照写入 archive/")
    ap.add_argument("--outdir", default="archive")
    args = ap.parse_args()
    snap = build_snapshot()
    out = Path(args.outdir) / f"{datetime.now(_CN_TZ).date().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    counts = {k: len(v) for k, v in snap["boards"].items()}
    print(f"{out} ({out.stat().st_size} bytes) boards={counts}")


if __name__ == "__main__":
    main()
