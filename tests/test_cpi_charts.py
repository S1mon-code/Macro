import pytest
import pandas as pd
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


LABELS = {
    "all_items": "CPI 总指数",
    "core": "核心 CPI",
    "food": "食品",
    "energy": "能源",
    "shelter": "住房",
}


class TestCPIChartBuilder:
    def test_init(self, sample_data):
        builder = CPIChartBuilder(sample_data, labels=LABELS)
        assert builder is not None

    def test_yoy_trend_chart(self, sample_data):
        builder = CPIChartBuilder(sample_data, labels=LABELS)
        fig = builder.yoy_trend(["all_items", "core"])
        assert fig is not None
        assert len(fig.data) == 2

    def test_mom_bar_chart(self, sample_data):
        builder = CPIChartBuilder(sample_data, labels=LABELS)
        fig = builder.mom_bar("all_items", last_n=12)
        assert fig is not None
        assert len(fig.data[0].x) == 12

    def test_components_breakdown(self, sample_data):
        builder = CPIChartBuilder(sample_data, labels=LABELS)
        fig = builder.components_latest_yoy(["food", "energy", "shelter"])
        assert fig is not None

