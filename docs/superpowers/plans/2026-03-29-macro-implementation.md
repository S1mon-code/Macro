# Macro 全球宏观周报系统 - 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 Macro 项目骨架，优先跑通 BLS API 拉取美国 CPI 数据及分项，生成交互式图表用于分析和预测。

**Architecture:** Python 项目，通过 BLS Public Data API v2 拉取 CPI 月度数据，存入 SQLite 缓存，用 Plotly 生成交互式图表（YoY/MoM 趋势、分项对比、简单预测），输出 HTML 报告。

**Tech Stack:** Python 3.11+, requests, pandas, plotly, kaleido, sqlite3, jinja2, pyyaml

---

### Task 1: 项目初始化与依赖安装

**Files:**
- Create: `requirements.txt`
- Create: `config/settings.yaml`
- Create: `.gitignore`
- Create: `README.md`

- [ ] **Step 1: 初始化 git 仓库**

```bash
cd ~/Desktop/Macro
git init
```

- [ ] **Step 2: 创建 .gitignore**

```gitignore
__pycache__/
*.pyc
.env
data/cache/*.db
output/
.superpowers/
.venv/
```

- [ ] **Step 3: 创建 requirements.txt**

```
requests>=2.31.0
pandas>=2.1.0
plotly>=5.18.0
kaleido>=0.2.1
jinja2>=3.1.0
weasyprint>=60.0
pyyaml>=6.0
numpy>=1.26.0
scikit-learn>=1.3.0
```

- [ ] **Step 4: 创建 config/settings.yaml**

```yaml
bls:
  api_key: ""  # 从 https://data.bls.gov/registrationEngine/ 免费注册获取
  base_url: "https://api.bls.gov/publicAPI/v2/timeseries/data/"

cpi:
  series:
    all_items: "CUSR0000SA0"
    core: "CUSR0000SA0L1E"
    food: "CUSR0000SAF1"
    energy: "CUSR0000SA0E"
    shelter: "CUSR0000SAH1"
    transportation: "CUSR0000SAT"
    medical: "CUSR0000SAM"
    apparel: "CUSR0000SAA"
    recreation: "CUSR0000SAR"
    education_communication: "CUSR0000SAE"
    other: "CUSR0000SAG"
    food_at_home: "CUSR0000SAF11"
    food_away: "CUSR0000SAFV"
    gasoline: "CUSR0000SETB01"
    electricity: "CUSR0000SEHF01"
    rent: "CUSR0000SEHA02"
    owners_equivalent_rent: "CUSR0000SEHC01"
  # CPI 分项中文名映射
  labels:
    all_items: "CPI 总指数"
    core: "核心 CPI（除食品能源）"
    food: "食品"
    energy: "能源"
    shelter: "住房"
    transportation: "交通"
    medical: "医疗"
    apparel: "服装"
    recreation: "娱乐"
    education_communication: "教育与通信"
    other: "其他商品与服务"
    food_at_home: "家庭食品"
    food_away: "在外餐饮"
    gasoline: "汽油"
    electricity: "电力"
    rent: "租金"
    owners_equivalent_rent: "业主等价租金"
  start_year: 2020
```

- [ ] **Step 5: 创建项目目录结构**

```bash
mkdir -p data/fetchers data/cache data/manual analysis charts reports/templates reports/exporters commentary output config
touch data/__init__.py data/fetchers/__init__.py analysis/__init__.py charts/__init__.py reports/__init__.py reports/exporters/__init__.py
```

- [ ] **Step 6: 创建虚拟环境并安装依赖**

```bash
cd ~/Desktop/Macro
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 7: 创建 GitHub 仓库并首次提交**

```bash
git add .
git commit -m "chore: init Macro project with dependencies and config"
gh repo create Macro --public --source=. --push
```

---

### Task 2: BLS API 数据采集模块

**Files:**
- Create: `data/fetchers/bls_fetcher.py`
- Create: `tests/test_bls_fetcher.py`

- [ ] **Step 1: 创建测试文件 tests/test_bls_fetcher.py**

```python
import pytest
import json
from unittest.mock import patch, MagicMock
from data.fetchers.bls_fetcher import BLSFetcher

MOCK_RESPONSE = {
    "status": "REQUEST_SUCCEEDED",
    "Results": {
        "series": [
            {
                "seriesID": "CUSR0000SA0",
                "data": [
                    {
                        "year": "2026",
                        "period": "M02",
                        "periodName": "February",
                        "value": "320.500",
                        "calculations": {
                            "net_changes": {"1": "0.3", "12": "8.5"},
                            "pct_changes": {"1": "0.1", "12": "2.8"}
                        }
                    },
                    {
                        "year": "2026",
                        "period": "M01",
                        "periodName": "January",
                        "value": "320.200",
                        "calculations": {
                            "net_changes": {"1": "0.2", "12": "8.0"},
                            "pct_changes": {"1": "0.1", "12": "2.6"}
                        }
                    }
                ]
            }
        ]
    }
}


class TestBLSFetcher:
    def test_init_loads_config(self):
        fetcher = BLSFetcher()
        assert fetcher.base_url == "https://api.bls.gov/publicAPI/v2/timeseries/data/"
        assert "all_items" in fetcher.series

    @patch("data.fetchers.bls_fetcher.requests.post")
    def test_fetch_series_returns_dataframe(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        fetcher = BLSFetcher()
        df = fetcher.fetch_series(["CUSR0000SA0"], start_year=2026, end_year=2026)

        assert len(df) == 2
        assert "date" in df.columns
        assert "value" in df.columns
        assert "series_id" in df.columns
        assert df["value"].dtype == float

    @patch("data.fetchers.bls_fetcher.requests.post")
    def test_fetch_cpi_all_returns_all_series(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        fetcher = BLSFetcher()
        result = fetcher.fetch_cpi_all()

        assert isinstance(result, dict)
        mock_post.assert_called()

    @patch("data.fetchers.bls_fetcher.requests.post")
    def test_parse_includes_yoy_and_mom(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        fetcher = BLSFetcher()
        df = fetcher.fetch_series(["CUSR0000SA0"], start_year=2026, end_year=2026)

        assert "yoy_pct" in df.columns
        assert "mom_pct" in df.columns
        assert df.iloc[0]["yoy_pct"] == 2.8
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/Desktop/Macro
source .venv/bin/activate
python -m pytest tests/test_bls_fetcher.py -v
```

预期: FAIL — `ModuleNotFoundError: No module named 'data.fetchers.bls_fetcher'`

- [ ] **Step 3: 实现 data/fetchers/bls_fetcher.py**

```python
import requests
import pandas as pd
import yaml
from datetime import datetime
from pathlib import Path


class BLSFetcher:
    """从美国劳工统计局 (BLS) API v2 获取 CPI 数据"""

    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        bls_config = config["bls"]
        cpi_config = config["cpi"]

        self.base_url = bls_config["base_url"]
        self.api_key = bls_config.get("api_key", "")
        self.series = cpi_config["series"]
        self.labels = cpi_config["labels"]
        self.start_year = cpi_config.get("start_year", 2020)

    def fetch_series(
        self,
        series_ids: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> pd.DataFrame:
        """拉取指定 series 的月度数据，返回 DataFrame"""
        if start_year is None:
            start_year = self.start_year
        if end_year is None:
            end_year = datetime.now().year

        payload = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
            "calculations": True,
            "annualaverage": False,
        }
        if self.api_key:
            payload["registrationkey"] = self.api_key

        response = requests.post(self.base_url, json=payload)
        response.raise_for_status()
        data = response.json()

        if data["status"] != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS API error: {data.get('message', 'Unknown error')}")

        rows = []
        for series in data["Results"]["series"]:
            sid = series["seriesID"]
            for item in series["data"]:
                if item["period"].startswith("M") and item["period"] != "M13":
                    month = int(item["period"][1:])
                    year = int(item["year"])
                    calcs = item.get("calculations", {})
                    pct = calcs.get("pct_changes", {})
                    rows.append({
                        "series_id": sid,
                        "date": datetime(year, month, 1),
                        "year": year,
                        "month": month,
                        "value": float(item["value"]),
                        "yoy_pct": float(pct["12"]) if "12" in pct else None,
                        "mom_pct": float(pct["1"]) if "1" in pct else None,
                    })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("date").reset_index(drop=True)
        return df

    def fetch_cpi_all(
        self,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, pd.DataFrame]:
        """拉取所有配置的 CPI 分项数据

        BLS API 每次最多查 50 个 series，这里分批请求。
        返回 {分项名: DataFrame} 的字典。
        """
        all_ids = list(self.series.values())
        id_to_name = {v: k for k, v in self.series.items()}

        # 分批，每批最多 50 个（v2 限制）
        batch_size = 50
        all_rows = []
        for i in range(0, len(all_ids), batch_size):
            batch = all_ids[i : i + batch_size]
            df = self.fetch_series(batch, start_year, end_year)
            all_rows.append(df)

        combined = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()

        result = {}
        for sid, name in id_to_name.items():
            subset = combined[combined["series_id"] == sid].copy()
            if not subset.empty:
                subset = subset.sort_values("date").reset_index(drop=True)
            result[name] = subset

        return result

    def get_label(self, name: str) -> str:
        """获取分项的中文名"""
        return self.labels.get(name, name)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_bls_fetcher.py -v
```

预期: 4 passed

- [ ] **Step 5: 提交**

```bash
git add data/fetchers/bls_fetcher.py tests/test_bls_fetcher.py
git commit -m "feat: BLS API fetcher for CPI data with tests"
git push
```

---

### Task 3: SQLite 数据缓存层

**Files:**
- Create: `data/cache/db.py`
- Create: `tests/test_cache.py`

- [ ] **Step 1: 创建测试文件 tests/test_cache.py**

```python
import pytest
import pandas as pd
from datetime import datetime
from data.cache.db import CacheDB


@pytest.fixture
def cache(tmp_path):
    db_path = tmp_path / "test.db"
    return CacheDB(str(db_path))


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "series_id": ["CUSR0000SA0", "CUSR0000SA0"],
        "date": [datetime(2026, 1, 1), datetime(2026, 2, 1)],
        "year": [2026, 2026],
        "month": [1, 2],
        "value": [319.0, 320.5],
        "yoy_pct": [2.6, 2.8],
        "mom_pct": [0.1, 0.1],
    })


class TestCacheDB:
    def test_save_and_load(self, cache, sample_df):
        cache.save("cpi", sample_df)
        loaded = cache.load("cpi")
        assert len(loaded) == 2
        assert loaded["value"].iloc[0] == 319.0

    def test_load_empty_table(self, cache):
        loaded = cache.load("nonexistent")
        assert loaded.empty

    def test_upsert_no_duplicates(self, cache, sample_df):
        cache.save("cpi", sample_df)
        cache.save("cpi", sample_df)
        loaded = cache.load("cpi")
        assert len(loaded) == 2

    def test_load_by_series(self, cache, sample_df):
        cache.save("cpi", sample_df)
        loaded = cache.load("cpi", series_id="CUSR0000SA0")
        assert len(loaded) == 2
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_cache.py -v
```

预期: FAIL

- [ ] **Step 3: 实现 data/cache/db.py**

```python
import sqlite3
import pandas as pd
from pathlib import Path


class CacheDB:
    """SQLite 本地数据缓存"""

    def __init__(self, db_path: str = "data/cache/macro.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cpi (
                series_id TEXT NOT NULL,
                date TEXT NOT NULL,
                year INTEGER,
                month INTEGER,
                value REAL,
                yoy_pct REAL,
                mom_pct REAL,
                PRIMARY KEY (series_id, date)
            )
        """)
        self.conn.commit()

    def save(self, table: str, df: pd.DataFrame):
        """保存 DataFrame 到指定表，使用 INSERT OR REPLACE 避免重复"""
        if df.empty:
            return
        df_copy = df.copy()
        if "date" in df_copy.columns:
            df_copy["date"] = df_copy["date"].astype(str)
        df_copy.to_sql(table, self.conn, if_exists="append", index=False,
                       method=self._upsert_method(table))

    def _upsert_method(self, table: str):
        def method(pd_table, conn, keys, data_iter):
            cols = ", ".join(keys)
            placeholders = ", ".join(["?"] * len(keys))
            sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})"
            data = [row for row in data_iter]
            conn.executemany(sql, data)
        return method

    def load(self, table: str, series_id: str | None = None) -> pd.DataFrame:
        """从缓存加载数据"""
        try:
            if series_id:
                df = pd.read_sql(
                    f"SELECT * FROM {table} WHERE series_id = ? ORDER BY date",
                    self.conn,
                    params=[series_id],
                )
            else:
                df = pd.read_sql(f"SELECT * FROM {table} ORDER BY date", self.conn)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception:
            return pd.DataFrame()

    def close(self):
        self.conn.close()
```

- [ ] **Step 4: 创建 data/cache/__init__.py**

```bash
touch data/cache/__init__.py
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/test_cache.py -v
```

预期: 4 passed

- [ ] **Step 6: 提交**

```bash
git add data/cache/ tests/test_cache.py
git commit -m "feat: SQLite cache layer for macro data"
git push
```

---

### Task 4: CPI 图表生成模块

**Files:**
- Create: `charts/cpi_charts.py`
- Create: `tests/test_cpi_charts.py`

- [ ] **Step 1: 创建测试文件 tests/test_cpi_charts.py**

```python
import pytest
import pandas as pd
from datetime import datetime
from charts.cpi_charts import CPIChartBuilder


@pytest.fixture
def sample_data():
    """模拟 fetch_cpi_all 返回的数据"""
    dates = pd.date_range("2023-01-01", periods=24, freq="MS")
    base = {
        "date": dates,
        "year": [d.year for d in dates],
        "month": [d.month for d in dates],
    }

    data = {}
    # all_items: 从 300 缓慢增长
    data["all_items"] = pd.DataFrame({
        **base,
        "series_id": "CUSR0000SA0",
        "value": [300 + i * 0.5 for i in range(24)],
        "yoy_pct": [3.0 + (i % 6) * 0.1 for i in range(24)],
        "mom_pct": [0.2 + (i % 3) * 0.05 for i in range(24)],
    })
    data["core"] = pd.DataFrame({
        **base,
        "series_id": "CUSR0000SA0L1E",
        "value": [295 + i * 0.4 for i in range(24)],
        "yoy_pct": [2.8 + (i % 6) * 0.1 for i in range(24)],
        "mom_pct": [0.18 + (i % 3) * 0.04 for i in range(24)],
    })
    data["food"] = pd.DataFrame({
        **base,
        "series_id": "CUSR0000SAF1",
        "value": [310 + i * 0.6 for i in range(24)],
        "yoy_pct": [3.5 + (i % 4) * 0.2 for i in range(24)],
        "mom_pct": [0.25 + (i % 3) * 0.06 for i in range(24)],
    })
    data["energy"] = pd.DataFrame({
        **base,
        "series_id": "CUSR0000SA0E",
        "value": [280 + i * 1.0 for i in range(24)],
        "yoy_pct": [5.0 + (i % 5) * 0.5 for i in range(24)],
        "mom_pct": [0.4 + (i % 4) * 0.1 for i in range(24)],
    })
    data["shelter"] = pd.DataFrame({
        **base,
        "series_id": "CUSR0000SAH1",
        "value": [320 + i * 0.7 for i in range(24)],
        "yoy_pct": [6.0 + (i % 3) * 0.3 for i in range(24)],
        "mom_pct": [0.5 + (i % 2) * 0.05 for i in range(24)],
    })
    return data


class TestCPIChartBuilder:
    def test_init(self, sample_data):
        builder = CPIChartBuilder(sample_data, labels={
            "all_items": "CPI 总指数",
            "core": "核心 CPI",
            "food": "食品",
            "energy": "能源",
            "shelter": "住房",
        })
        assert builder is not None

    def test_yoy_trend_chart(self, sample_data):
        builder = CPIChartBuilder(sample_data, labels={
            "all_items": "CPI 总指数", "core": "核心 CPI",
            "food": "食品", "energy": "能源", "shelter": "住房",
        })
        fig = builder.yoy_trend(["all_items", "core"])
        assert fig is not None
        assert len(fig.data) == 2

    def test_mom_bar_chart(self, sample_data):
        builder = CPIChartBuilder(sample_data, labels={
            "all_items": "CPI 总指数", "core": "核心 CPI",
            "food": "食品", "energy": "能源", "shelter": "住房",
        })
        fig = builder.mom_bar("all_items", last_n=12)
        assert fig is not None
        assert len(fig.data[0].x) == 12

    def test_components_breakdown(self, sample_data):
        builder = CPIChartBuilder(sample_data, labels={
            "all_items": "CPI 总指数", "core": "核心 CPI",
            "food": "食品", "energy": "能源", "shelter": "住房",
        })
        fig = builder.components_latest_yoy(["food", "energy", "shelter"])
        assert fig is not None

    def test_forecast_chart(self, sample_data):
        builder = CPIChartBuilder(sample_data, labels={
            "all_items": "CPI 总指数", "core": "核心 CPI",
            "food": "食品", "energy": "能源", "shelter": "住房",
        })
        fig = builder.forecast("all_items", months_ahead=3)
        assert fig is not None
        # 应有历史线 + 预测线
        assert len(fig.data) >= 2
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_cpi_charts.py -v
```

预期: FAIL

- [ ] **Step 3: 实现 charts/cpi_charts.py**

```python
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


class CPIChartBuilder:
    """生成 CPI 相关的 Plotly 图表"""

    CHART_TEMPLATE = "plotly_dark"
    COLORS = [
        "#e94560", "#0f3460", "#533483", "#16c79a",
        "#f5a623", "#50c4ed", "#ff6b6b", "#a29bfe",
    ]

    def __init__(self, data: dict[str, pd.DataFrame], labels: dict[str, str]):
        """
        Args:
            data: {分项名: DataFrame} 来自 BLSFetcher.fetch_cpi_all()
            labels: {分项名: 中文标签} 来自 config
        """
        self.data = data
        self.labels = labels

    def _label(self, name: str) -> str:
        return self.labels.get(name, name)

    def yoy_trend(self, components: list[str] | None = None) -> go.Figure:
        """CPI 同比趋势折线图（多分项叠加）"""
        if components is None:
            components = ["all_items", "core"]

        fig = go.Figure()
        for i, name in enumerate(components):
            df = self.data.get(name)
            if df is None or df.empty:
                continue
            df_valid = df.dropna(subset=["yoy_pct"])
            fig.add_trace(go.Scatter(
                x=df_valid["date"],
                y=df_valid["yoy_pct"],
                mode="lines+markers",
                name=self._label(name),
                line=dict(color=self.COLORS[i % len(self.COLORS)], width=2),
                marker=dict(size=4),
            ))

        fig.update_layout(
            title="美国 CPI 同比变化趋势 (%)",
            xaxis_title="日期",
            yaxis_title="同比 (%)",
            template=self.CHART_TEMPLATE,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        return fig

    def mom_bar(self, component: str = "all_items", last_n: int = 12) -> go.Figure:
        """CPI 环比柱状图（最近 N 个月）"""
        df = self.data.get(component)
        if df is None or df.empty:
            return go.Figure()

        df_valid = df.dropna(subset=["mom_pct"]).tail(last_n)
        colors = ["#e94560" if v > 0 else "#16c79a" for v in df_valid["mom_pct"]]

        fig = go.Figure(go.Bar(
            x=df_valid["date"],
            y=df_valid["mom_pct"],
            marker_color=colors,
            text=[f"{v:.2f}%" for v in df_valid["mom_pct"]],
            textposition="outside",
        ))

        fig.update_layout(
            title=f"{self._label(component)} 环比变化 (%, 最近{last_n}个月)",
            xaxis_title="日期",
            yaxis_title="环比 (%)",
            template=self.CHART_TEMPLATE,
        )
        return fig

    def components_latest_yoy(self, components: list[str]) -> go.Figure:
        """各分项最新同比对比横向柱状图"""
        names = []
        values = []
        for name in components:
            df = self.data.get(name)
            if df is None or df.empty:
                continue
            df_valid = df.dropna(subset=["yoy_pct"])
            if df_valid.empty:
                continue
            latest = df_valid.iloc[-1]
            names.append(self._label(name))
            values.append(latest["yoy_pct"])

        colors = ["#e94560" if v > 0 else "#16c79a" for v in values]

        fig = go.Figure(go.Bar(
            x=values,
            y=names,
            orientation="h",
            marker_color=colors,
            text=[f"{v:.1f}%" for v in values],
            textposition="outside",
        ))

        fig.update_layout(
            title="CPI 各分项最新同比变化 (%)",
            xaxis_title="同比 (%)",
            template=self.CHART_TEMPLATE,
            height=max(400, len(names) * 40 + 200),
        )
        return fig

    def forecast(
        self, component: str = "all_items", months_ahead: int = 3
    ) -> go.Figure:
        """简单线性趋势预测

        使用最近 12 个月数据做线性回归，向前预测 months_ahead 个月。
        仅用于参考趋势方向，不作为投资依据。
        """
        df = self.data.get(component)
        if df is None or df.empty:
            return go.Figure()

        df_valid = df.dropna(subset=["yoy_pct"]).copy()
        if len(df_valid) < 6:
            return go.Figure()

        # 取最近 12 个月做回归
        recent = df_valid.tail(12).copy()
        x = np.arange(len(recent)).reshape(-1, 1)
        y = recent["yoy_pct"].values

        # 简单线性回归 (不需要 sklearn，用 numpy)
        coeffs = np.polyfit(x.flatten(), y, deg=1)
        slope, intercept = coeffs[0], coeffs[1]

        # 预测未来
        future_x = np.arange(len(recent), len(recent) + months_ahead)
        future_y = slope * future_x + intercept
        last_date = recent["date"].iloc[-1]
        future_dates = pd.date_range(last_date, periods=months_ahead + 1, freq="MS")[1:]

        fig = go.Figure()

        # 历史数据
        fig.add_trace(go.Scatter(
            x=df_valid["date"],
            y=df_valid["yoy_pct"],
            mode="lines+markers",
            name=f"{self._label(component)} 实际值",
            line=dict(color="#0f3460", width=2),
            marker=dict(size=4),
        ))

        # 回归拟合线（最近12个月）
        fit_y = slope * x.flatten() + intercept
        fig.add_trace(go.Scatter(
            x=recent["date"],
            y=fit_y,
            mode="lines",
            name="趋势拟合",
            line=dict(color="#f5a623", width=1, dash="dot"),
        ))

        # 预测
        fig.add_trace(go.Scatter(
            x=future_dates,
            y=future_y,
            mode="lines+markers",
            name=f"预测 ({months_ahead}个月)",
            line=dict(color="#e94560", width=2, dash="dash"),
            marker=dict(size=6, symbol="diamond"),
        ))

        fig.update_layout(
            title=f"{self._label(component)} 同比趋势与预测 (%)",
            xaxis_title="日期",
            yaxis_title="同比 (%)",
            template=self.CHART_TEMPLATE,
            hovermode="x unified",
            annotations=[dict(
                text="* 预测基于线性趋势外推，仅供参考",
                xref="paper", yref="paper",
                x=0, y=-0.15, showarrow=False,
                font=dict(size=10, color="gray"),
            )],
        )
        return fig

    def index_value_trend(self, components: list[str] | None = None) -> go.Figure:
        """CPI 指数绝对值走势图"""
        if components is None:
            components = ["all_items", "core"]

        fig = go.Figure()
        for i, name in enumerate(components):
            df = self.data.get(name)
            if df is None or df.empty:
                continue
            fig.add_trace(go.Scatter(
                x=df["date"],
                y=df["value"],
                mode="lines",
                name=self._label(name),
                line=dict(color=self.COLORS[i % len(self.COLORS)], width=2),
            ))

        fig.update_layout(
            title="美国 CPI 指数走势 (1982-84=100)",
            xaxis_title="日期",
            yaxis_title="指数值",
            template=self.CHART_TEMPLATE,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        return fig
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_cpi_charts.py -v
```

预期: 5 passed

- [ ] **Step 5: 提交**

```bash
git add charts/cpi_charts.py tests/test_cpi_charts.py
git commit -m "feat: CPI chart builder with YoY/MoM/components/forecast"
git push
```

---

### Task 5: CPI 报告生成主入口

**Files:**
- Create: `cpi_report.py`
- Create: `reports/templates/cpi.html`

- [ ] **Step 1: 创建 HTML 模板 reports/templates/cpi.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>美国 CPI 数据分析报告</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0a0a1a;
            color: #e0e0e0;
            line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
        .header {
            text-align: center;
            padding: 40px 0;
            border-bottom: 1px solid #1a1a2e;
            margin-bottom: 32px;
        }
        .header h1 {
            font-size: 28px;
            color: #fff;
            margin-bottom: 8px;
        }
        .header .date {
            color: #888;
            font-size: 14px;
        }
        .section {
            margin-bottom: 40px;
        }
        .section h2 {
            font-size: 20px;
            color: #e94560;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid #1a1a2e;
        }
        .chart-container {
            background: #111;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
        }
        .summary-table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 24px;
        }
        .summary-table th, .summary-table td {
            padding: 10px 16px;
            text-align: left;
            border-bottom: 1px solid #1a1a2e;
        }
        .summary-table th {
            background: #1a1a2e;
            color: #e94560;
            font-weight: 600;
        }
        .positive { color: #e94560; }
        .negative { color: #16c79a; }
        .footer {
            text-align: center;
            padding: 24px;
            color: #555;
            font-size: 12px;
            border-top: 1px solid #1a1a2e;
            margin-top: 40px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>美国 CPI 数据分析报告</h1>
            <div class="date">数据截至: {{ report_date }} | 生成时间: {{ generated_at }}</div>
        </div>

        <!-- 摘要表格 -->
        <div class="section">
            <h2>CPI 各分项概览</h2>
            <table class="summary-table">
                <thead>
                    <tr>
                        <th>分项</th>
                        <th>最新值</th>
                        <th>同比 (%)</th>
                        <th>环比 (%)</th>
                        <th>月份</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in summary %}
                    <tr>
                        <td>{{ item.label }}</td>
                        <td>{{ "%.1f"|format(item.value) }}</td>
                        <td class="{{ 'positive' if item.yoy > 0 else 'negative' }}">
                            {{ "%.2f"|format(item.yoy) }}%
                        </td>
                        <td class="{{ 'positive' if item.mom > 0 else 'negative' }}">
                            {{ "%.2f"|format(item.mom) }}%
                        </td>
                        <td>{{ item.period }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <!-- 图表 -->
        {% for chart in charts %}
        <div class="section">
            <h2>{{ chart.title }}</h2>
            <div class="chart-container">
                {{ chart.html | safe }}
            </div>
        </div>
        {% endfor %}

        <div class="footer">
            <p>数据来源: 美国劳工统计局 (BLS) | Macro 宏观数据分析系统</p>
            <p>* 预测数据基于历史趋势外推，仅供参考，不构成投资建议</p>
        </div>
    </div>
</body>
</html>
```

- [ ] **Step 2: 创建 cpi_report.py 主入口**

```python
"""美国 CPI 数据拉取、分析、图表生成、报告输出"""

import argparse
from datetime import datetime
from pathlib import Path

import plotly.io as pio
from jinja2 import Environment, FileSystemLoader

from data.fetchers.bls_fetcher import BLSFetcher
from data.cache.db import CacheDB
from charts.cpi_charts import CPIChartBuilder


def generate_cpi_report(use_cache: bool = False):
    """生成 CPI 分析报告"""
    print("=" * 50)
    print("美国 CPI 数据分析报告生成")
    print("=" * 50)

    # 1. 拉取数据
    fetcher = BLSFetcher()
    cache = CacheDB()

    if use_cache:
        print("\n[1/4] 从缓存加载数据...")
        all_data = {}
        for name, sid in fetcher.series.items():
            df = cache.load("cpi", series_id=sid)
            if not df.empty:
                all_data[name] = df
        if not all_data:
            print("  缓存为空，切换为在线拉取...")
            use_cache = False

    if not use_cache:
        print("\n[1/4] 从 BLS API 拉取 CPI 数据...")
        all_data = fetcher.fetch_cpi_all()
        # 缓存到 SQLite
        print("  保存到本地缓存...")
        for name, df in all_data.items():
            if not df.empty:
                cache.save("cpi", df)

    print(f"  已获取 {len(all_data)} 个分项数据")

    # 2. 生成图表
    print("\n[2/4] 生成分析图表...")
    builder = CPIChartBuilder(all_data, fetcher.labels)

    major_components = ["food", "energy", "shelter", "transportation", "medical"]
    available_components = [c for c in major_components if c in all_data and not all_data[c].empty]

    chart_configs = [
        ("CPI 同比趋势 (总指数 vs 核心)", builder.yoy_trend(["all_items", "core"])),
        ("CPI 同比趋势 (主要分项)", builder.yoy_trend(available_components)),
        ("CPI 总指数环比变化", builder.mom_bar("all_items", last_n=12)),
        ("CPI 各分项最新同比对比", builder.components_latest_yoy(available_components)),
        ("CPI 指数绝对值走势", builder.index_value_trend(["all_items", "core"])),
        ("CPI 总指数趋势预测", builder.forecast("all_items", months_ahead=3)),
        ("核心 CPI 趋势预测", builder.forecast("core", months_ahead=3)),
    ]
    print(f"  已生成 {len(chart_configs)} 张图表")

    # 3. 构建摘要表格
    print("\n[3/4] 构建报告数据...")
    summary = []
    report_date = "N/A"
    display_order = ["all_items", "core"] + available_components
    for name in display_order:
        df = all_data.get(name)
        if df is None or df.empty:
            continue
        df_valid = df.dropna(subset=["yoy_pct", "mom_pct"])
        if df_valid.empty:
            continue
        latest = df_valid.iloc[-1]
        period = f"{int(latest['year'])}年{int(latest['month'])}月"
        if name == "all_items":
            report_date = period
        summary.append({
            "label": fetcher.get_label(name),
            "value": latest["value"],
            "yoy": latest["yoy_pct"],
            "mom": latest["mom_pct"],
            "period": period,
        })

    # 4. 渲染 HTML
    print("\n[4/4] 生成报告文件...")
    output_dir = Path("output") / "cpi"
    output_dir.mkdir(parents=True, exist_ok=True)

    charts_html = []
    for title, fig in chart_configs:
        chart_html = pio.to_html(fig, full_html=False, include_plotlyjs=False)
        charts_html.append({"title": title, "html": chart_html})

    env = Environment(loader=FileSystemLoader("reports/templates"))
    template = env.get_template("cpi.html")
    html_content = template.render(
        report_date=report_date,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        summary=summary,
        charts=charts_html,
    )

    html_path = output_dir / "cpi_report.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"  HTML 报告: {html_path}")

    # 导出静态图片
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)
    for i, (title, fig) in enumerate(chart_configs):
        png_path = images_dir / f"chart_{i+1}.png"
        fig.write_image(str(png_path), width=1200, height=600, scale=2)
    print(f"  图表图片: {images_dir}/")

    print("\n" + "=" * 50)
    print(f"报告生成完成！打开 {html_path} 查看")
    print("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成美国 CPI 数据分析报告")
    parser.add_argument("--cache", action="store_true", help="使用本地缓存数据（不联网）")
    args = parser.parse_args()
    generate_cpi_report(use_cache=args.cache)
```

- [ ] **Step 3: 运行完整流程测试**

```bash
cd ~/Desktop/Macro
source .venv/bin/activate
python cpi_report.py
```

预期：成功拉取数据，生成 `output/cpi/cpi_report.html` 和图片。用浏览器打开 HTML 查看效果。

- [ ] **Step 4: 提交**

```bash
git add cpi_report.py reports/templates/cpi.html
git commit -m "feat: CPI report generator with interactive charts and forecast"
git push
```

---

### Task 6: 端到端验证与收尾

- [ ] **Step 1: 注册 BLS API Key（如果还没有）**

访问 https://data.bls.gov/registrationEngine/ 注册免费 API Key，填入 `config/settings.yaml` 的 `bls.api_key` 字段。

- [ ] **Step 2: 全量运行并验证**

```bash
cd ~/Desktop/Macro
source .venv/bin/activate
python cpi_report.py
open output/cpi/cpi_report.html
```

验证清单:
- [ ] 数据正常拉取，无 API 错误
- [ ] 摘要表格显示所有分项最新数据
- [ ] 7 张图表全部正常渲染
- [ ] 同比趋势图有多条折线
- [ ] 环比柱状图红绿分色
- [ ] 分项对比横向柱状图正常
- [ ] 预测图有虚线延伸
- [ ] 图片文件生成到 output/cpi/images/

- [ ] **Step 3: 运行全部测试**

```bash
python -m pytest tests/ -v
```

预期: 全部 PASS

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "feat: complete CPI analysis pipeline - data, charts, report"
git push
```
