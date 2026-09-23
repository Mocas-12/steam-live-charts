# steamdata.py 数据层离线单元测试。
#
# 覆盖纯函数与可离线验证的缓存逻辑：
#   - price_from_overview  价格概览 -> 展示用价格 dict
#   - _clean_price         价格文本清洗（¥ 归一化 / 免费识别 / HTML 实体）
#   - parse_search_rows    Steam 搜索结果 HTML -> 行记录列表
#   - get_tag_map          StoreTag id -> 中文名 的 24h 缓存（失败退化）
#
# 运行方式：在仓库根目录执行  python -m pytest tests/ -q
#
# 全部用例离线运行，不依赖网络与 Steam 可用性；httpx 仅用于构造离线异常对象。
# get_tag_map 的抓取/失败路径通过替换 steamdata.get_client（模块唯一的 httpx
# 客户端入口）为桩对象实现，桩形状与实现用法严格对应：get(url) -> 含
# raise_for_status() 与 json() 的响应对象。

import time

import httpx
import pytest

import steamdata
from steamdata import (
    HEADER_IMG,
    STORE_URL,
    _clean_price,
    get_tag_map,
    parse_search_rows,
    price_from_overview,
)


# ---------- price_from_overview ----------


class TestPriceFromOverview:
    """price_from_overview(po, is_free)：从 Steam price overview 提取展示价格。"""

    def test_is_free_takes_priority(self):
        """is_free=True 时无论 po 是否有值，一律返回固定免费结构。"""
        free = {"free": True, "final": "免费开玩", "original": None, "pct": None}
        assert price_from_overview(None, True) == free
        assert price_from_overview(
            {"discount_percent": 50, "final_formatted": "¥ 10", "initial": 100}, True
        ) == free

    def test_none_or_empty_overview_returns_none(self):
        """非免费但 overview 为 None / 空 dict 时返回 None（无法展示价格）。"""
        assert price_from_overview(None, False) is None
        assert price_from_overview({}, False) is None

    def test_discounted_price(self):
        """折扣价：final_formatted 生效，原价由 initial/100 清洗而来，pct 取负。"""
        po = {
            "discount_percent": 50,
            "final_formatted": "¥ 49.50",
            "final": 4950,
            "initial": 9900,
        }
        assert price_from_overview(po, False) == {
            "free": False,
            "final": "¥49.5",
            "original": "¥99",
            "pct": -50,
        }

    def test_no_discount_no_original(self):
        """无折扣（discount_percent=0）时 original 与 pct 均为 None。"""
        po = {"discount_percent": 0, "final_formatted": "¥ 199", "initial": 19900}
        out = price_from_overview(po, False)
        assert out == {"free": False, "final": "¥199", "original": None, "pct": None}

    def test_missing_discount_percent_key_treated_as_zero(self):
        """缺 discount_percent 字段等同无折扣。"""
        out = price_from_overview({"final_formatted": "¥ 88"}, False)
        assert out == {"free": False, "final": "¥88", "original": None, "pct": None}

    def test_fallback_to_final_cents(self):
        """缺 final_formatted 时回退到 final（分）换算；原价同样由 initial 换算。"""
        po = {"discount_percent": 30, "final": 4899, "initial": 6999}
        assert price_from_overview(po, False) == {
            "free": False,
            "final": "¥48.99",
            "original": "¥69.99",
            "pct": -30,
        }

    def test_whitespace_formatted_falls_back_to_cents(self):
        """final_formatted 只有空白时清洗结果为 None，仍走 final 分回退。"""
        po = {"final_formatted": "   ", "final": 1999}
        out = price_from_overview(po, False)
        assert out["final"] == "¥19.99"

    def test_degenerate_overview_yields_zero_price(self):
        """边界：overview 非空但没有任何价格字段 -> final 回退为 ¥0。"""
        assert price_from_overview({"foo": 1}, False) == {
            "free": False,
            "final": "¥0",
            "original": None,
            "pct": None,
        }

    def test_free_text_inside_overview(self):
        """overview 文本含「免费」时清洗为「免费开玩」，但 free 标志仍为 False。"""
        out = price_from_overview({"final_formatted": "免费"}, False)
        assert out == {"free": False, "final": "免费开玩", "original": None, "pct": None}

    def test_discount_without_initial_key_raises_keyerror(self):
        """现状钉子：折扣非零但缺 initial 时实现用 po['initial'] 直接取值会 KeyError。"""
        po = {"discount_percent": 50, "final_formatted": "¥ 49.50", "final": 4950}
        with pytest.raises(KeyError):
            price_from_overview(po, False)


# ---------- _clean_price ----------


class TestCleanPrice:
    """_clean_price(text)：价格文本清洗，产出可直接展示的字符串或 None。"""

    def test_plain_yen(self):
        """「¥ 123」-> 去空格归一化为「¥123」。"""
        assert _clean_price("¥ 123") == "¥123"

    def test_thousands_separator(self):
        """千分位逗号被去掉：「¥ 1,234」->「¥1234」。"""
        assert _clean_price("¥ 1,234") == "¥1234"

    def test_decimal_trailing_zeroes_stripped(self):
        """小数尾部 0 与孤立小数点被剥离：12.50->12.5、12.00->12、49.50->49.5。"""
        assert _clean_price("¥ 12.50") == "¥12.5"
        assert _clean_price("¥ 12.00") == "¥12"
        assert _clean_price("¥ 49.50") == "¥49.5"

    def test_empty_and_whitespace_return_none(self):
        """空串与纯空白 -> None（无价格信息）。"""
        assert _clean_price("") is None
        assert _clean_price("   ") is None

    def test_free_keywords(self):
        """「免费」/「免费开玩」/「Free」（大小写不敏感的精确匹配）都归一为「免费开玩」。"""
        assert _clean_price("免费") == "免费开玩"
        assert _clean_price("免费开玩") == "免费开玩"
        assert _clean_price("Free") == "免费开玩"
        assert _clean_price("free") == "免费开玩"

    def test_invalid_number_after_yen_passthrough(self):
        """¥ 后不是数字时 float 转换失败被吞掉，原样（去空格后）返回。"""
        assert _clean_price("¥abc") == "¥abc"

    def test_non_price_text_passthrough(self):
        """无任何价格特征的文本原样透传（仅去空格）。"""
        assert _clean_price("周未特惠") == "周未特惠"

    def test_html_entities_unescaped(self):
        """HTML 实体先反转义：&nbsp; 解出 NBSP，被 strip 与去空格处理掉。"""
        assert _clean_price("¥ 19&nbsp;") == "¥19"

    def test_fullwidth_yen_not_normalized(self):
        """现状钉子：仅半角 ¥(U+00A5) 被归一化，全角 ￥(U+FFE5) 原样透传。"""
        assert _clean_price("￥1,234") == "￥1,234"


# ---------- parse_search_rows ----------

# 手工构造的最小搜索结果 HTML，形状与解析正则严格对齐：
#  - 行锚点是 <a href="https://store.steampowered.com/app/{id}/..." class="search_result_row ...">
#  - data-ds-tagids 必须放在 class 之前：解析器只在锚点开标签匹配片段
#    （m.group(0) 止于 class 属性的闭合引号）内找 tagids
#  - 标题/折扣/价格/发售日期/封面各字段的选择器按实现中的正则摆放
SEARCH_HTML = """
<div id="search_result_container">
  <a href="https://store.steampowered.com/app/570/Dota_2/?snr=1_7_7_700_702"
     data-ds-appid="570" data-ds-tagids="[19,10,10,492,9999]"
     class="search_result_row ds_collapse_flag ">
    <div class="col search_capsule">
      <img src="https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/570/capsule_sm_120.jpg">
    </div>
    <div class="responsive_search_name_combined">
      <span class="title">Bling &amp; Things</span>
      <div class="search_released">2024 年 5 月 1 日</div>
    </div>
    <div class="col search_price_discount_combined">
      <div class="discount_pct">-50%</div>
      <div class="discount_original_price">¥ 99</div>
      <div class="discount_final_price">¥ 49.50</div>
    </div>
  </a>
  <a href="https://store.steampowered.com/app/730/CounterStrike_2/?snr=1_7_7_700_702"
     data-ds-appid="730" data-ds-tagids="[10]"
     class="search_result_row ">
    <span class="title">Counter-Strike 2</span>
    <div class="discount_final_price ">免费开玩</div>
  </a>
  <a href="https://store.steampowered.com/app/4242/No_Title/?snr=1"
     class="search_result_row ">
    <div class="discount_final_price">¥ 20</div>
  </a>
</div>
"""

TAG_MAP = {10: "动作", 19: "休闲", 492: "独立"}


@pytest.fixture()
def tags(monkeypatch):
    """用固定 tag 映射替换 get_tag_map，保证 parse_search_rows 离线且结果确定。"""
    monkeypatch.setattr(steamdata, "get_tag_map", lambda: TAG_MAP)


class TestParseSearchRows:
    """parse_search_rows(html)：解析搜索结果行，缺失字段走兜底。"""

    def test_parses_rows_in_document_order_and_skips_titleless(self):
        """按文档顺序产出有标题的行；无 <span class="title"> 的行（如 4242）被跳过。"""
        items = parse_search_rows(SEARCH_HTML)
        assert [it["appid"] for it in items] == [570, 730]

    def test_discounted_row_full_fields(self, tags):
        """折扣行：标题反转义、封面取 capsule 图、tagid 去重/截断到 3 个/忽略未知 id。"""
        (item,) = [it for it in parse_search_rows(SEARCH_HTML) if it["appid"] == 570]
        assert item["name"] == "Bling & Things"  # &amp; 已反转义
        assert item["image"] == (
            "https://shared.cloudflare.steamstatic.com/store_item_assets/"
            "steam/apps/570/capsule_sm_120.jpg"
        )
        assert item["url"] == STORE_URL.format(570)
        # 19->休闲, 10->动作, 重复的 10 去重, 492->独立后满 3 个截断, 未知 9999 无影响
        assert item["genres"] == ["休闲", "动作", "独立"]
        assert item["released"] == "2024 年 5 月 1 日"
        assert item["price"] == {
            "free": False,
            "final": "¥49.5",
            "original": "¥99",
            "pct": -50,
        }

    def test_free_row_fallbacks(self, tags):
        """免费行：price.free 为 True；无封面图回退 header.jpg；无发售日期为 None。"""
        (item,) = [it for it in parse_search_rows(SEARCH_HTML) if it["appid"] == 730]
        assert item["name"] == "Counter-Strike 2"
        assert item["image"] == HEADER_IMG.format(730)
        assert item["url"] == STORE_URL.format(730)
        assert item["genres"] == ["动作"]
        assert item["released"] is None
        assert item["price"] == {
            "free": True,
            "final": "免费开玩",
            "original": None,
            "pct": None,
        }

    def test_empty_or_anchorless_html(self):
        """空串 / 无搜索行的 HTML -> 空列表。"""
        assert parse_search_rows("") == []
        assert parse_search_rows("<div><p>nothing here</p></div>") == []


# ---------- get_tag_map（缓存逻辑，经 get_client 桩离线驱动） ----------


class _FakeResponse:
    """桩响应：与 get_tag_map 用到的接口（raise_for_status/json）形状一致。"""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    """桩 httpx 客户端：记录 get 调用，可注入 payload 或异常。"""

    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._payload)


class TestGetTagMap:
    """get_tag_map：24h 缓存命中不发请求；抓取成功入缓存；失败退化为空映射并被缓存。"""

    def test_fresh_cache_skips_network(self, monkeypatch):
        """缓存新鲜（<24h）时直接返回，不触发任何网络调用。"""
        monkeypatch.setattr(steamdata, "_tag_map", {10: "动作"})
        monkeypatch.setattr(steamdata, "_tag_ts", time.monotonic())

        def _no_network():
            raise AssertionError("缓存命中时不应创建 httpx 客户端")

        monkeypatch.setattr(steamdata, "get_client", _no_network)
        assert get_tag_map() == {10: "动作"}

    def test_fetch_success_populates_cache(self, monkeypatch):
        """首次抓取：请求 populartags/schinese，tagid 转 int 后存入模块缓存。"""
        monkeypatch.setattr(steamdata, "_tag_map", None)
        monkeypatch.setattr(steamdata, "_tag_ts", 0.0)
        client = _FakeClient(
            payload=[{"tagid": "10", "name": "动作"}, {"tagid": 19, "name": "休闲"}]
        )
        monkeypatch.setattr(steamdata, "get_client", lambda: client)

        assert get_tag_map() == {10: "动作", 19: "休闲"}
        assert steamdata._tag_map == {10: "动作", 19: "休闲"}  # 已写入缓存
        assert client.calls[0][0] == (
            "https://store.steampowered.com/tagdata/populartags/schinese"
        )

    def test_failure_degrades_to_empty_map_and_caches(self, monkeypatch):
        """抓取失败（原缓存为空）退化为空映射并缓存，第二次调用不再发请求。"""
        monkeypatch.setattr(steamdata, "_tag_map", None)
        monkeypatch.setattr(steamdata, "_tag_ts", 0.0)
        client = _FakeClient(error=httpx.ConnectError("离线测试，不联网"))
        monkeypatch.setattr(steamdata, "get_client", lambda: client)

        assert get_tag_map() == {}
        assert get_tag_map() == {}  # 第二次走缓存
        assert len(client.calls) == 1  # 只发起过一次请求
        assert steamdata._tag_map == {}
