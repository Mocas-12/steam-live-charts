# Steam 实时游戏榜单

仿 Steam 商店风格的实时游戏榜单页面，数据全部来自 Steam 官方公开接口，无需 API Key，每 60 秒自动刷新。

![tab](https://img.shields.io/badge/榜单-热销·最热·特惠-green) ![python](https://img.shields.io/badge/python-3.10+-blue)

## 榜单

| Tab | 内容 | 数据源 | 缓存 |
|---|---|---|---|
| 热销商品 | 销量 Top 50（含价格/折扣） | store search `sort_by=TopSellers` | 120s |
| 最热游玩 | 按实时在线人数排序 Top 100 | `GetMostPlayedGames` + `GetNumberOfCurrentPlayers` + `appdetails` | 60s |
| 特惠专区 | 热销折扣游戏 Top 50 | 同热销 + `specials=1` | 120s |

最热游玩榜在官方每日快照的基础上按**实时在线人数**重新排序，并展示今日峰值与较上周的名次变化（▲/▼/新上榜）。

## 运行

两个前端共用同一套数据层 `steamdata.py`：

**本地 FastAPI 版**（原版 Steam 视觉，前端 60 秒倒计时自动轮询）：

```bash
pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8123
# 或者直接双击 run.bat（Windows）
```

打开 http://127.0.0.1:8123/ 即可。

**Streamlit 版**（部署 Streamlit Cloud 用，界面为 Streamlit 复刻版）：

```bash
streamlit run streamlit_app.py
# 云端：Streamlit Cloud 仓库设置里 Main file path 选 streamlit_app.py
```

榜单数据由 `st.cache_data`（60/120 秒 TTL）+ `st.fragment(run_every="60s")` 自动刷新。

## 实现说明

- **后端** `app.py`（FastAPI 异步版）/ `steamdata.py`（同步数据层，两端共用）：TTL 缓存 + 在途请求合并 / `st.cache_data`（同一 key 的并发请求只打一次上游），上游失败时回退过期数据。
- **限流**：最热榜首载需 100 次在线人数查询（并发 20）+ 100 次 appdetails（并发 15，10 分钟缓存），稳态刷新只查在线人数。
- **名字兜底**：已下架/区域锁定的游戏（如 Rocket League）appdetails 返回失败，改从 Steam 社区页标题取名字（24h 缓存）。
- **封面图**：新游戏旧版 CDN 路径已失效，改用搜索行/appdetails 自带的哈希化 `store_item_assets` 地址，加载失败时隐藏图片只留排名角标。
- **前端** `static/`：原生 HTML/CSS/JS，Motiva Sans（Steam CDN）+ Arial 兜底，60s 倒计时自动刷新当前 tab，骨架屏 + 错误横幅。

价格区域为 `cc=cn`（人民币），语言 `l=schinese`，可在 `app.py` 顶部修改。

## 免责声明

本页面为非官方第三方工具，与 Valve Corporation 无从属关系；游戏名称、图片、价格版权归 Valve 及相应开发商所有。
