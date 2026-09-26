# steamdata 采样/降采样/异动分析离线单元测试。
#
#   downsample     等距抽点（sparkline 用，右端点对齐最新值）
#   HistoryRing    24h 滚动采样（min_interval 去重 / maxlen 截断 / spark 导出）
#   surge_pct      异动判定（30min vs 2h 基线，阈值 + 基线下限）
#   briefing_facts 今日速览聚合（纯函数，只消费已有榜单数据）
#
# 全部离线：python -m pytest tests/ -q

import steamdata
from collections import deque
from steamdata import HistoryRing, briefing_facts, downsample, surge_pct


def _items(*players, appid=1):
    return [{"appid": appid, "players": p} for p in players]


class TestDownsample:
    """downsample(values, n)：等距抽 n 点，右端点必须是最新值。"""

    def test_short_passthrough(self):
        assert downsample([1, 2, 3], 40) == [1, 2, 3]

    def test_exact_n(self):
        assert downsample([1, 2, 3, 4], 4) == [1, 2, 3, 4]

    def test_long_reduced_keeps_ends(self):
        out = downsample(list(range(100)), 40)
        assert len(out) == 40
        assert out[0] == 0
        assert out[-1] == 99  # 右端点对齐最新采样

    def test_n_one(self):
        assert downsample([3, 1, 2], 1) == [2]


class TestHistoryRing:
    """HistoryRing：采样入环、间隔去重、maxlen 截断、spark 导出。"""

    def test_sample_and_spark(self):
        h = HistoryRing()
        h.sample(_items(100), min_interval=0)
        h.sample(_items(200), min_interval=0)
        assert h.spark(1) == [100, 200]

    def test_min_interval_dedups(self):
        """同一次重建引发的连续请求不重复采样。"""
        h = HistoryRing()
        h.sample(_items(100), min_interval=3600)
        h.sample(_items(200), min_interval=3600)
        assert h.spark(1) == [100]

    def test_missing_players_skipped(self):
        h = HistoryRing()
        h.sample([{"appid": 1, "players": None}])
        assert h.spark(1) == []

    def test_ring_maxlen(self):
        h = HistoryRing(max_points=3)
        for p in range(10):
            h.sample(_items(p), min_interval=0)
        assert len(h.rings[1]) == 3
        assert h.spark(1, n=2)[-1] == 9

    def test_spark_unknown_appid_empty(self):
        assert HistoryRing().spark(42) == []


class TestSurgePct:
    """surge_pct：最近 30 分钟 vs 之前 2 小时基线；需要 ~2.5h 采样才开始识别。"""

    def _feed(self, appid, values):
        """把给定序列以 60s 间隔灌进模块级 HISTORY（测试后清理）。"""
        import time as _t
        now = _t.time()
        ring = steamdata.HISTORY.rings.setdefault(appid, deque(maxlen=1440))
        ring.clear()
        for i, p in enumerate(values):
            ring.append((now - (len(values) - i) * 60, p))
        yield
        steamdata.HISTORY.rings.pop(appid, None)

    def test_insufficient_data_returns_none(self, appid=9001):
        steamdata.HISTORY.rings[appid] = deque(maxlen=10)
        try:
            assert surge_pct(appid) is None  # 采样远不足 150 点
        finally:
            steamdata.HISTORY.rings.pop(appid, None)

    def test_flat_no_surge(self):
        # 150 点全平：均值 1000，无上涨
        gen = self._feed(9002, [1000] * 150)
        next(gen)
        try:
            assert surge_pct(9002) is None
        finally:
            gen.close()

    def test_small_base_ignored(self):
        # 基线均值 100（< 200 下限）即使涨 100% 也不算异动
        vals = [100] * 120 + [200] * 30
        gen = self._feed(9003, vals)
        next(gen)
        try:
            assert surge_pct(9003) is None
        finally:
            gen.close()

    def test_real_surge_detected(self):
        # 基线 1000 人稳定，最近 30 分钟涨到 1500（+50%）
        vals = [1000] * 120 + [1500] * 30
        gen = self._feed(9004, vals)
        next(gen)
        try:
            assert surge_pct(9004) == 50
        finally:
            gen.close()


class TestBriefingFacts:
    """briefing_facts：聚合总在线/新上榜/异动/限时免费，零网络。"""

    def test_aggregates_all_facts(self):
        mp = [
            {"appid": 1, "name": "A", "url": "u1", "players": 1000, "is_new": False, "surge": 52},
            {"appid": 2, "name": "B", "url": "u2", "players": 500, "is_new": True, "surge": None},
            {"appid": 3, "name": "C", "url": "u3", "players": None, "is_new": True, "surge": 10},
            {"appid": 4, "name": "D", "url": "u4", "players": 200, "is_new": False, "surge": None},
        ]
        ftk = [{"name": "X"}, {"name": "Y"}, {"name": "Z"}, {"name": "W"}]
        b = briefing_facts(mp, ftk)
        assert b["total_online"] == 1700
        assert b["new_entries"] == 2
        assert b["ftk_count"] == 4
        assert b["ftk_names"] == ["X", "Y", "Z"]  # 最多 3 个名字
        assert [s["pct"] for s in b["surges"]] == [52, 10]  # 按涨幅降序
        assert b["surges"][0]["name"] == "A"
        assert b["sampling"] == 2  # surge=None 的两款还在采样积累中

    def test_empty_everything(self):
        b = briefing_facts([], [])
        assert b["total_online"] == 0 and b["surges"] == [] and b["sampling"] == 0
