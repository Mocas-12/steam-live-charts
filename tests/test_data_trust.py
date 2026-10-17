"""Data provenance, partial coverage, stale fallbacks and clock-based trend windows."""

import asyncio
import json
import time
from collections import deque

import httpx
import pytest

import app
import steamdata as sd


def test_cached_response_preserves_collection_time_and_reports_failure(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(sd.time, "time", lambda: clock[0])
    cache = app.TTLCache(120)

    async def good():
        return [{"appid": 1}]

    async def bad():
        raise RuntimeError("offline")

    async def scenario():
        first = await cache.get_entry("board", good)
        clock[0] = 1050
        hit = await cache.get_entry("board", good)
        assert hit.updated_at == first.updated_at == 1000
        assert not app.board_response(hit, 120)["meta"]["stale"]
        failed = await cache.get_entry("board", bad, force=True)
        meta = app.board_response(failed, 120)["meta"]
        assert meta["updated_at"] == 1000 and meta["served_at"] == 1050
        assert meta["refresh_failed"] and meta["stale"]
        clock[0] = 1060
        recovered = await cache.get_entry("board", good, force=True)
        assert recovered.updated_at == 1060 and not recovered.refresh_failed

    asyncio.run(scenario())


def test_failed_refresh_does_not_rejuvenate_cache():
    cache = app.TTLCache(60)
    cache.data["x"] = app.CacheEntry([], time.time() - 3600, time.monotonic() - 3600)

    async def bad():
        raise RuntimeError("offline")

    result = asyncio.run(cache.get_entry("x", bad))
    assert app.board_response(result, 60)["meta"]["age_seconds"] >= 3600


def test_cancelled_waiter_does_not_cancel_shared_fetch():
    async def scenario():
        cache = app.TTLCache(60)
        ready, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def factory():
            calls.append(1)
            ready.set()
            await release.wait()
            return "ok"

        first = asyncio.create_task(cache.get("x", factory))
        await ready.wait()
        second = asyncio.create_task(cache.get("x", factory))
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert await second == "ok"
        assert len(calls) == 1

    asyncio.run(scenario())


def test_expired_alerts_are_not_presented_as_current():
    value = [{"appid": 1, "surge": 90, "spark": [1, 2]}]
    response = app.board_response(app.CacheEntry(value, time.time() - 600, 0), 60)
    assert response["items"][0]["surge"] is None
    assert response["items"][0]["spark"] == []
    assert value[0]["surge"] == 90  # response formatting must not mutate the cache


def test_disk_seed_discards_unverifiable_alerts_and_legacy_delta(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "LAST_MP_LIVE", tmp_path / "missing.json")
    monkeypatch.setattr(sd, "LAST_MP_SEED", tmp_path / "seed.json")
    sd.LAST_MP_SEED.write_text(json.dumps({"built_at": time.time(), "items": [
        {"appid": 1, "rank": 1, "players": 500, "delta": 5, "is_new": True,
         "surge": 91, "spark": [100, 500]},
    ]}), encoding="utf-8")
    items, _ = sd.load_cached_most_played()
    assert items[0]["surge"] is None and items[0]["spark"] == []
    assert items[0]["delta"] is None and not items[0]["is_new"]


def test_future_seed_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "LAST_MP_LIVE", tmp_path / "seed.json")
    monkeypatch.setattr(sd, "LAST_MP_SEED", tmp_path / "missing.json")
    sd.LAST_MP_LIVE.write_text(json.dumps({"built_at": time.time() + 3600,
                                         "items": [{"appid": 1}]}), encoding="utf-8")
    assert sd.load_cached_most_played() == (None, None)


def test_delta_uses_current_rank_not_official_snapshot_rank():
    rows = sd.rank_most_played([
        {"appid": 2, "players": 800, "last_week_rank": 5},
        {"appid": 1, "players": 500, "last_week_rank": 1},
        {"appid": 3, "players": None, "last_week_rank": 2},
    ])
    assert [r["delta"] for r in rows] == [4, -1, None]


def test_unknown_last_week_is_not_a_new_entry():
    rows = sd.rank_most_played([{"players": 10}, {"players": 20, "last_week_rank": -1}])
    assert not rows[0]["is_new"] and rows[1]["is_new"]


def test_online_total_reports_partial_coverage_including_zero():
    facts = sd.briefing_facts([{"players": 500}, {"players": 0}, {"players": None}], [])
    assert facts["total_online"] == 500
    assert facts["games_with_players"] == 2 and facts["games_total"] == 3


@pytest.mark.parametrize("response", [{}, {"player_count": None}, {"player_count": -1},
                                      {"player_count": 0, "result": 42}])
def test_missing_or_invalid_ccu_is_not_zero(response, monkeypatch):
    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": response}

    monkeypatch.setattr(sd, "_get_backoff", lambda *a, **kw: Reply())
    with pytest.raises(ValueError):
        sd.fetch_ccu(1)


def test_sparse_old_history_cannot_generate_current_surge(monkeypatch):
    now = 1_800_000_000
    monkeypatch.setattr(sd.time, "time", lambda: now)
    history = sd.HistoryRing()
    monkeypatch.setattr(sd, "HISTORY", history)
    history.rings[1] = deque((now - (150 - i) * 600, 1000 if i < 120 else 1500)
                            for i in range(150))
    assert sd.surge_pct(1) is None


def test_real_time_windows_with_two_minute_sampling(monkeypatch):
    now = 1_800_000_000
    monkeypatch.setattr(sd.time, "time", lambda: now)
    history = sd.HistoryRing()
    monkeypatch.setattr(sd, "HISTORY", history)
    history.rings[1] = deque((now - (75 - i) * 120, 1000 if i < 60 else 1500)
                            for i in range(75))
    assert sd.surge_pct(1) == 50
    # The exact same values cease to be a current signal after collection stops.
    monkeypatch.setattr(sd.time, "time", lambda: now + 601)
    assert sd.surge_pct(1) is None


def test_long_gap_suppresses_surge(monkeypatch):
    now = 1_800_000_000
    monkeypatch.setattr(sd.time, "time", lambda: now)
    history = sd.HistoryRing()
    monkeypatch.setattr(sd, "HISTORY", history)
    history.rings[1] = deque((now - (150 - i) * 60, 1000 if i < 120 else 1500)
                            for i in range(150) if not 80 <= i <= 90)
    assert sd.surge_pct(1) is None


def test_history_really_expires_after_24_hours(monkeypatch):
    now = 1_800_000_000
    monkeypatch.setattr(sd.time, "time", lambda: now)
    history = sd.HistoryRing()
    history.rings[1] = deque([(now - 86401, 100), (now - 60, 200)])
    assert history.points(1) == [(now - 60, 200)]
    assert history.spark(1) == [200]


def test_api_cached_and_forced_failure_keep_original_timestamp(monkeypatch):
    monkeypatch.setattr(app, "search_cache", app.TTLCache(120))
    # search_board's default cache is explicitly supplied to isolate this endpoint test.
    row = {"price": {"final": "¥10"}, "appid": 1}
    cache = app.TTLCache(120)

    async def scenario():
        def good():
            return [row]

        def bad():
            raise RuntimeError("offline")

        first = await app.search_board("x", good, cache=cache)
        second = await app.search_board("x", bad, force=True, cache=cache)
        assert first["meta"]["updated_at"] == second["meta"]["updated_at"]
        assert second["meta"]["refresh_failed"] and second["meta"]["stale"]

    asyncio.run(scenario())


def test_briefing_reports_unknown_free_status_on_failure(monkeypatch):
    async def most_played(force=False):
        return {"items": [{"players": 100}], "meta": sd.data_meta(time.time(), 60)}

    async def unavailable(force=False):
        raise RuntimeError("offline")

    monkeypatch.setattr(app, "api_most_played", most_played)
    monkeypatch.setattr(app, "api_free_to_keep", unavailable)
    result = asyncio.run(app.api_briefing())
    assert result["ftk_count"] is None and result["free_to_keep_meta"] is None


@pytest.mark.parametrize("route,ttl", [("top-sellers", 120), ("specials", 120),
                                       ("new-releases", 600), ("free-games", 120),
                                       ("free-to-keep", 120), ("epic-free", 120),
                                       ("most-played", 60)])
def test_http_contract_and_real_collection_time(route, ttl, monkeypatch):
    for name, age in [("search_cache", 120), ("new_cache", 600), ("charts_cache", 60)]:
        monkeypatch.setattr(app, name, app.TTLCache(age))
    item = {"appid": 1, "name": "A", "price": {"final": "免费领取", "free": True, "pct": -100}}
    monkeypatch.setattr(sd, "fetch_search", lambda *a, **kw: [item])
    for name in ("fetch_new_releases", "fetch_free_to_keep", "fetch_epic_free", "build_most_played"):
        monkeypatch.setattr(sd, name, lambda: [item])

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://test") as client:
            first = await client.get(f"/api/{route}?force=1")
            second = await client.get(f"/api/{route}")
        assert first.status_code == second.status_code == 200
        a, b = first.json(), second.json()
        assert a["items"] == b["items"]
        assert a["meta"]["updated_at"] == b["meta"]["updated_at"]
        assert b["meta"]["served_at"] >= b["meta"]["updated_at"]
        assert b["meta"]["ttl"] == ttl and not b["meta"]["stale"]
        assert second.headers["cache-control"] == "no-cache"

    asyncio.run(scenario())


def test_search_discount_with_accessibility_attributes(monkeypatch):
    monkeypatch.setattr(sd, "get_tag_map", lambda: {})
    rows = sd.parse_search_rows('''<a href="https://store.steampowered.com/app/1/game/" class="search_result_row">
        <span class="title">Game</span>
        <div class="discount_pct" aria-hidden="true">-70%</div>
        <div class="discount_original_price extra" aria-hidden="true">¥298.00</div>
        <div class="discount_final_price" aria-hidden="true">¥89.40</div></a>''')
    assert rows[0]["price"] == {"free": False, "pct": -70, "original": "¥298", "final": "¥89.4"}


def test_snapshot_seed_keeps_original_collection_time(tmp_path, monkeypatch):
    from scripts.snapshot import write_seeds

    monkeypatch.setattr(sd, "LAST_MP_LIVE", tmp_path / "live.json")
    monkeypatch.setattr(sd, "LAST_MP_SEED", tmp_path / "seed.json")
    monkeypatch.setattr(sd, "write_detail_seed", lambda: None)
    items = [{"appid": 1}]
    sd._dump_json(sd.LAST_MP_LIVE, {"built_at": 1234, "items": items})
    write_seeds(items)
    assert sd._load_json(sd.LAST_MP_SEED)["built_at"] == 1234


def test_disk_fallback_remembers_refresh_failure(monkeypatch):
    cache = app.TTLCache(60)
    monkeypatch.setattr(app, "charts_cache", cache)
    monkeypatch.setattr(sd, "load_cached_most_played", lambda: ([{"appid": 1}], 1234))

    def failed():
        raise RuntimeError("offline")

    monkeypatch.setattr(sd, "build_most_played", failed)

    async def scenario():
        first = await app.api_most_played()
        assert first["meta"]["source"] == "disk" and first["meta"]["stale"]
        await cache.get_entry("most_played", app.to_thread(failed), force=True)
        second = await app.api_most_played()
        assert second["meta"]["source"] == "disk" and second["meta"]["refresh_failed"]
        assert second["meta"]["updated_at"] == 1234

    asyncio.run(scenario())


def test_flat_history_is_ready_without_an_alert(monkeypatch):
    now = 1_800_000_000
    monkeypatch.setattr(sd.time, "time", lambda: now)
    history = sd.HistoryRing()
    monkeypatch.setattr(sd, "HISTORY", history)
    history.rings[1] = deque((now - (150 - i) * 60, 1000) for i in range(150))
    assert sd._surge_window(1, now) and sd.surge_pct(1) is None
    assert sd.briefing_facts([{"surge": None, "surge_ready": True}], [])["sampling"] == 0


@pytest.mark.parametrize("players", [None, 0])
def test_build_rejects_total_failure_but_accepts_real_zero(players, monkeypatch):
    monkeypatch.setattr(sd, "fetch_most_played", lambda: [{"appid": 1, "rank": 1}])
    monkeypatch.setattr(sd, "fetch_ccu", lambda appid: players)
    monkeypatch.setattr(sd, "fetch_detail_cached", lambda *a: {"name": "A"})
    monkeypatch.setattr(sd, "_persist_detail_store", lambda: None)
    monkeypatch.setattr(sd, "_dump_json", lambda *a: None)
    monkeypatch.setattr(sd, "HISTORY", sd.HistoryRing())
    if players is None:
        with pytest.raises(RuntimeError, match="有效在线人数"):
            sd.build_most_played()
    else:
        row = sd.build_most_played()[0]
        assert row["players"] == 0 and not row["is_new"] and row["delta"] is None
