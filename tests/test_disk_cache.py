# steamdata 磁盘缓存层离线单元测试。
#
#   fetch_detail_cached      磁盘预热命中（max_age 信任窗口）/ 抓取后落盘
#   load_cached_most_played  最近构建榜单读取（热身优先/种子兜底/过期失效）
#
# 全部离线：python -m pytest tests/ -q

import json
import time

import pytest

import steamdata


@pytest.fixture()
def cache_paths(tmp_path, monkeypatch):
    """把四个缓存路径指到临时目录，并清空内存详情缓存。"""
    monkeypatch.setattr(steamdata, "DETAILS_LIVE", tmp_path / "details_live.json")
    monkeypatch.setattr(steamdata, "DETAILS_SEED", tmp_path / "details_seed.json")
    monkeypatch.setattr(steamdata, "LAST_MP_LIVE", tmp_path / "last_mp.json")
    monkeypatch.setattr(steamdata, "LAST_MP_SEED", tmp_path / "last_mp_seed.json")
    monkeypatch.setattr(steamdata, "CC", "cn")
    monkeypatch.setattr(steamdata, "LANG", "schinese")
    monkeypatch.setattr(steamdata, "_detail_store", {})
    return tmp_path


class TestDetailSeed:
    """详情缓存：预热加载、max_age 信任窗口、抓取后落盘。"""

    def test_warm_loads_seed_entries(self, cache_paths, monkeypatch):
        (cache_paths / "details_seed.json").write_text(
            json.dumps({"570": {"ts": time.time(), "d": {"name": "Dota 2"}}}),
            encoding="utf-8",
        )
        steamdata._warm_detail_store()
        assert steamdata._detail_store[570][1] == {"name": "Dota 2"}

    def test_warm_skips_stale_entries(self, cache_paths):
        old = time.time() - 40 * 3600  # 超过种子 36h 老化期
        (cache_paths / "details_seed.json").write_text(
            json.dumps({"570": {"ts": old, "d": {"name": "Dota 2"}}}),
            encoding="utf-8",
        )
        steamdata._warm_detail_store()
        assert 570 not in steamdata._detail_store

    def test_trusted_max_age_hits_warm_cache(self, cache_paths, monkeypatch):
        """构建路径 max_age=36h：两小时前的热身详情直接用，不打网络。"""
        steamdata._detail_store[570] = (time.time() - 2 * 3600, {"name": "Dota 2"})

        def _no_network(appid, **kw):
            raise AssertionError("信任窗口内不应发起网络请求")

        monkeypatch.setattr(steamdata, "fetch_detail", _no_network)
        assert steamdata.fetch_detail_cached(570, max_age=36 * 3600) == {"name": "Dota 2"}

    def test_default_ttl_miss_refetches_and_persists(self, cache_paths, monkeypatch):
        """默认 30min TTL：2h 旧条目失效重新抓取，结果写入热身文件。"""
        steamdata._detail_store[570] = (time.time() - 2 * 3600, {"name": "旧"})
        monkeypatch.setattr(
            steamdata, "fetch_detail", lambda appid, _retry=True: {"name": "新"}
        )
        assert steamdata.fetch_detail_cached(570) == {"name": "新"}
        saved = json.loads((cache_paths / "details_live.json").read_text(encoding="utf-8"))
        assert saved["570"]["d"] == {"name": "新"}

    def test_fetch_failure_cached_as_none(self, cache_paths, monkeypatch):
        """抓取失败（返回 None）同样入缓存：短时间内不再重试同一款。"""
        monkeypatch.setattr(steamdata, "fetch_detail", lambda appid, _retry=True: None)
        assert steamdata.fetch_detail_cached(999) is None
        assert steamdata.fetch_detail_cached(999) is None  # 第二次走缓存不再打网络


class TestCachedMostPlayed:
    """load_cached_most_played：热身优先、种子兜底、过期失效。"""

    def _write(self, path, built_at):
        path.write_text(
            json.dumps({"built_at": built_at, "items": [{"appid": 1, "rank": 1}]}),
            encoding="utf-8",
        )

    def test_live_file_preferred(self, cache_paths):
        now = time.time()
        self._write(steamdata.LAST_MP_LIVE, now - 60)
        self._write(steamdata.LAST_MP_SEED, now - 3600)
        items, built_at = steamdata.load_cached_most_played()
        assert items == [{"appid": 1, "rank": 1}]
        assert built_at == pytest.approx(now - 60, abs=5)

    def test_seed_fallback(self, cache_paths):
        now = time.time()
        self._write(steamdata.LAST_MP_SEED, now - 3600)
        items, _ = steamdata.load_cached_most_played()
        assert items == [{"appid": 1, "rank": 1}]

    def test_expired_returns_none(self, cache_paths):
        self._write(steamdata.LAST_MP_LIVE, time.time() - 27 * 3600)  # 超过 26h 上限
        assert steamdata.load_cached_most_played() == (None, None)

    def test_missing_files_return_none(self, cache_paths):
        assert steamdata.load_cached_most_played() == (None, None)

    def test_corrupt_json_returns_none(self, cache_paths):
        steamdata.LAST_MP_LIVE.write_text("{broken", encoding="utf-8")
        assert steamdata.load_cached_most_played() == (None, None)