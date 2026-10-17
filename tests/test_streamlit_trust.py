"""Run the actual Streamlit script with offline sources, including reruns and failures."""

import time

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import steamdata as sd


@pytest.fixture
def offline_app(monkeypatch):
    st.cache_data.clear()
    st.cache_resource.clear()
    item = {"appid": 1, "rank": 1, "name": "Test game", "image": "missing.jpg",
            "url": "https://store.steampowered.com/app/1/", "genres": ["动作"],
            "players": 100, "peak": 200, "surge": 90, "delta": None, "is_new": False,
            "price": {"final": "¥10", "pct": -50, "original": "¥20", "free": False}}
    monkeypatch.setattr(sd, "fetch_search", lambda *a, **kw: [{**item, "surge": None}])
    monkeypatch.setattr(sd, "fetch_new_releases", lambda: [{**item, "surge": None}])
    monkeypatch.setattr(sd, "fetch_free_to_keep", lambda: [])
    monkeypatch.setattr(sd, "fetch_epic_free", lambda: [])
    monkeypatch.setattr(sd, "load_cached_most_played", lambda: ([item], time.time() - 3600))
    yield item
    st.cache_data.clear()
    st.cache_resource.clear()


def markup(at):
    return "\n".join(m.value for m in at.markdown if not m.value.startswith("<style>"))


def test_rerun_keeps_background_snapshot_and_collection_time(offline_app, monkeypatch):
    calls = []

    def build():
        calls.append(1)
        return [offline_app]

    monkeypatch.setattr(sd, "build_most_played", build)
    at = AppTest.from_file("../streamlit_app.py", default_timeout=15).run()
    at.run()  # Pick up completed background collection.
    assert not at.exception
    before = markup(at)
    at.run()
    assert not at.exception and len(calls) == 1
    assert markup(at) == before
    assert "榜单 Top 1 在线合计" in before and "UTC+8" in before


def test_failed_rebuild_keeps_seed_and_hides_old_surge(offline_app, monkeypatch):
    def failed():
        raise RuntimeError("offline")

    monkeypatch.setattr(sd, "build_most_played", failed)
    at = AppTest.from_file("../streamlit_app.py", default_timeout=15).run()
    at.run()
    assert not at.exception
    text = markup(at)
    assert "Test game" in text and "刷新失败，显示历史数据" in text
    assert "+90%" not in text


def test_search_source_failure_is_not_an_empty_free_event(offline_app, monkeypatch):
    monkeypatch.setattr(sd, "build_most_played", lambda: [offline_app])

    def failed():
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(sd, "fetch_free_to_keep", failed)
    at = AppTest.from_file("../streamlit_app.py", default_timeout=15).run()
    assert not at.exception
    assert "upstream unavailable" in markup(at)

