import pytest
import pandas as pd
from charts.macro_charts import MacroChartBuilder


@pytest.fixture
def sample_data():
    """Sample macro data with date, value, yoy_pct, mom_pct columns."""
    dates = pd.date_range("2023-01-01", periods=24, freq="MS")

    data = {}
    data["gdp"] = pd.DataFrame({
        "date": dates,
        "value": [100 + i * 0.8 for i in range(24)],
        "yoy_pct": [2.5 + (i % 4) * 0.2 for i in range(24)],
        "mom_pct": [0.3 + (i % 3) * 0.1 for i in range(24)],
    })
    data["unemployment"] = pd.DataFrame({
        "date": dates,
        "value": [3.5 + (i % 6) * 0.1 for i in range(24)],
        "yoy_pct": [-0.2 + (i % 4) * 0.1 for i in range(24)],
        "mom_pct": [-0.05 + (i % 3) * 0.02 for i in range(24)],
    })
    data["inflation"] = pd.DataFrame({
        "date": dates,
        "value": [250 + i * 0.5 for i in range(24)],
        "yoy_pct": [3.0 + (i % 5) * 0.15 for i in range(24)],
        "mom_pct": [0.2 + (i % 3) * 0.05 for i in range(24)],
    })
    return data


LABELS = {
    "gdp": "GDP Growth",
    "unemployment": "Unemployment Rate",
    "inflation": "Inflation Index",
}


class TestMacroChartBuilder:
    def test_init(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        assert builder.data is sample_data
        assert builder._label("gdp") == "GDP Growth"
        assert builder._label("unknown") == "unknown"

    def test_line_trend(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.line_trend(["gdp", "inflation"], y_col="value", title="Test Trend")
        assert len(fig.data) == 2
        assert fig.layout.title.text == "Test Trend"

    def test_line_trend_single(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.line_trend(["gdp"], y_col="yoy_pct")
        assert len(fig.data) == 1

    def test_line_trend_missing_key(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.line_trend(["gdp", "nonexistent"])
        assert len(fig.data) == 1

    def test_line_trend_all_missing(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.line_trend(["nonexistent"])
        assert len(fig.data) == 0

    def test_bar_chart(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.bar_chart("gdp", y_col="mom_pct", last_n=12, title="Bar Test")
        assert len(fig.data) == 1
        assert len(fig.data[0].x) == 12

    def test_bar_chart_last_n(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.bar_chart("gdp", y_col="value", last_n=6)
        assert len(fig.data[0].x) == 6

    def test_bar_chart_missing_key(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.bar_chart("nonexistent")
        assert len(fig.data) == 0

    def test_horizontal_bar(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.horizontal_bar(
            ["gdp", "unemployment", "inflation"],
            y_col="yoy_pct",
            title="Latest YoY",
        )
        assert len(fig.data) == 1
        assert len(fig.data[0].x) == 3

    def test_horizontal_bar_missing_key(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.horizontal_bar(["nonexistent"])
        assert len(fig.data) == 0

    def test_dual_axis(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.dual_axis(
            "gdp",
            y1_col="value",
            y2_col="yoy_pct",
            title="Dual Axis Test",
            y1_label="Index",
            y2_label="YoY %",
        )
        assert len(fig.data) == 2

    def test_dual_axis_missing_key(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.dual_axis("nonexistent")
        assert len(fig.data) == 0

    def test_multi_line(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.multi_line(
            [
                ("gdp", "yoy_pct", "GDP YoY"),
                ("unemployment", "value", "Unemployment"),
                ("inflation", "mom_pct", "Inflation MoM"),
            ],
            title="Multi-line Test",
        )
        assert len(fig.data) == 3

    def test_multi_line_partial_missing(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.multi_line(
            [
                ("gdp", "yoy_pct", "GDP YoY"),
                ("nonexistent", "value", "Missing"),
            ],
            title="Partial",
        )
        assert len(fig.data) == 1

    def test_multi_line_all_missing(self, sample_data):
        builder = MacroChartBuilder(sample_data, labels=LABELS)
        fig = builder.multi_line([("nonexistent", "value", "Missing")])
        assert len(fig.data) == 0

    def test_empty_dataframe(self):
        data = {"empty": pd.DataFrame(columns=["date", "value", "yoy_pct"])}
        builder = MacroChartBuilder(data, labels={"empty": "Empty Series"})
        assert len(builder.line_trend(["empty"]).data) == 0
        assert len(builder.bar_chart("empty").data) == 0
        assert len(builder.horizontal_bar(["empty"]).data) == 0
        assert len(builder.dual_axis("empty").data) == 0
