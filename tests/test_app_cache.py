# app.py TTLCache 离线单元测试。
#
# TTLCache 是服务端最精巧的缓存逻辑（在途请求合并 / 过期重取 / 失败回退过期数据 /
# force 绕过），全部用 asyncio.run 驱动、不依赖网络：
#   python -m pytest tests/ -q
#
# 导入 app 会创建 FastAPI 实例并挂载 static/，需在仓库根目录运行且已装 fastapi。

import asyncio
import time

import pytest

from app import TTLCache


def run(coro):
    return asyncio.run(coro)


class TestTTLCache:
    """TTLCache.get：缓存命中 / 过期 / 并发去重 / 失败兜底 / force。"""

    def test_fresh_hit_skips_factory(self):
        """TTL 内重复 get 只调用一次 factory。"""
        calls = []

        async def factory():
            calls.append(1)
            return "v"

        cache = TTLCache(60)
        assert run(cache.get("k", factory)) == "v"
        assert run(cache.get("k", factory)) == "v"
        assert len(calls) == 1

    def test_expired_refetches(self):
        """超过 TTL 后重新调用 factory。"""
        calls = []

        async def factory():
            calls.append(1)
            return len(calls)

        cache = TTLCache(0.05)
        assert run(cache.get("k", factory)) == 1
        time.sleep(0.1)
        assert run(cache.get("k", factory)) == 2

    def test_inflight_dedup(self):
        """并发 get 同一 key 时合并为一个在途请求，只调用一次 factory。"""

        async def factory():
            await asyncio.sleep(0.05)
            return "v"

        cache = TTLCache(60)

        async def double():
            return await asyncio.gather(cache.get("k", factory), cache.get("k", factory))

        assert run(double()) == ["v", "v"]

    def test_failure_without_stale_raises(self):
        """无历史数据时 factory 失败原样抛出。"""

        async def factory():
            raise RuntimeError("boom")

        cache = TTLCache(60)
        with pytest.raises(RuntimeError):
            run(cache.get("k", factory))

    def test_failure_with_stale_falls_back(self):
        """有过期数据时 factory 失败回退旧值（而不是报错）。"""
        state = {"fail": False}

        async def factory():
            if state["fail"]:
                raise RuntimeError("boom")
            return "good"

        cache = TTLCache(0.05)
        assert run(cache.get("k", factory)) == "good"
        time.sleep(0.1)  # 数据过期但仍在 self.data 里
        state["fail"] = True
        assert run(cache.get("k", factory)) == "good"

    def test_force_bypasses_fresh_cache(self):
        """force=True 绕过新鲜缓存真重抓（前端刷新按钮路径）。"""
        calls = []

        async def factory():
            calls.append(1)
            return len(calls)

        cache = TTLCache(60)
        assert run(cache.get("k", factory)) == 1
        assert run(cache.get("k", factory, force=True)) == 2
