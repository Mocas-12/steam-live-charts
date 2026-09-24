# app.py 采样/降采样逻辑离线单元测试。
#
#   downsample   等距抽点（sparkline 用，右端点对齐最新值）
#   HistoryRing  24h 滚动采样（min_interval 去重 / maxlen 截断 / spark 导出）
#
# 全部离线：python -m pytest tests/ -q

from app import HistoryRing, downsample


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
