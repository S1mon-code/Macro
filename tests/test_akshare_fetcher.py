import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import datetime

from data.fetchers.akshare_fetcher import AKShareFetcher


# ── Mock DataFrames matching AKShare return formats ─────────────────────

MOCK_GDP_DF = pd.DataFrame([
    {"季度": "2024年第1季度", "国内生产总值-绝对值": 296299.0, "国内生产总值-同比增长": 5.3},
    {"季度": "2023年第4季度", "国内生产总值-绝对值": 284997.0, "国内生产总值-同比增长": 5.2},
    {"季度": "2015年第4季度", "国内生产总值-绝对值": 180000.0, "国内生产总值-同比增长": 6.8},
])

MOCK_CPI_DF = pd.DataFrame([
    {"月份": "2024年03月份", "全国-当月": 100.1, "全国-同比增长": 0.1, "全国-环比增长": -1.0},
    {"月份": "2024年02月份", "全国-当月": 100.7, "全国-同比增长": 0.7, "全国-环比增长": 1.0},
])

MOCK_PPI_DF = pd.DataFrame([
    {"月份": "2024年03月份", "当月": 99.8, "当月同比增长": -2.8},
    {"月份": "2024年02月份", "当月": 99.6, "当月同比增长": -2.7},
])

MOCK_PMI_DF = pd.DataFrame([
    {"月份": "2024年03月份", "制造业-指数": 50.8, "非制造业-指数": 53.0},
    {"月份": "2024年02月份", "制造业-指数": 49.1, "非制造业-指数": 51.4},
])

MOCK_MONEY_SUPPLY_DF = pd.DataFrame([
    {
        "月份": "2024年03月份",
        "货币和准货币(M2)-数量(亿元)": 3040000.0,
        "货币和准货币(M2)-同比增长": 8.3,
        "货币(M1)-数量(亿元)": 689000.0,
        "货币(M1)-同比增长": 1.1,
    },
])

MOCK_TRADE_DF = pd.DataFrame([
    {
        "月份": "2024年03月份",
        "当月出口额-金额": 2796.0,
        "当月出口额-同比增长": -7.5,
        "当月进口额-金额": 2210.0,
        "当月进口额-同比增长": -1.9,
    },
])

MOCK_INDUSTRIAL_DF = pd.DataFrame([
    {"月份": "2024年03月份", "同比增长": 4.5},
    {"月份": "2024年02月份", "同比增长": 7.0},
])

MOCK_RETAIL_DF = pd.DataFrame([
    {"月份": "2024年03月份", "当月": 35699.0, "同比增长": 3.1, "环比增长": 0.26},
])

MOCK_CREDIT_DF = pd.DataFrame([
    {"月份": "2024年03月份", "当月": 30900.0, "当月-同比增长": 5.0},
])


class TestAKShareFetcher:

    def test_init_loads_config(self):
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        assert fetcher.start_year == 2016
        assert "gdp" in fetcher.indicators
        assert "cpi" in fetcher.indicators
        assert fetcher.indicators["gdp"]["func"] == "macro_china_gdp"

    # ── Date parsing ────────────────────────────────────────────────────

    def test_parse_month(self):
        dt = AKShareFetcher._parse_month("2024年03月份")
        assert dt == datetime(2024, 3, 1)

    def test_parse_month_no_trailing(self):
        dt = AKShareFetcher._parse_month("2024年3月")
        assert dt == datetime(2024, 3, 1)

    def test_parse_month_invalid(self):
        assert AKShareFetcher._parse_month("invalid") is None

    def test_parse_quarter_single(self):
        dt = AKShareFetcher._parse_quarter("2024年第1季度")
        assert dt == datetime(2024, 3, 1)  # Q1 → March

    def test_parse_quarter_q3(self):
        dt = AKShareFetcher._parse_quarter("2024年第3季度")
        assert dt == datetime(2024, 9, 1)  # Q3 → September

    def test_parse_quarter_cumulative(self):
        # Cumulative rows are now skipped (return None)
        dt = AKShareFetcher._parse_quarter("2024年第1-4季度")
        assert dt is None

    def test_parse_quarter_invalid(self):
        assert AKShareFetcher._parse_quarter("bad") is None

    # ── safe_float ──────────────────────────────────────────────────────

    def test_safe_float_normal(self):
        assert AKShareFetcher._safe_float(3.14) == 3.14

    def test_safe_float_string(self):
        assert AKShareFetcher._safe_float("2.5") == 2.5

    def test_safe_float_none(self):
        assert AKShareFetcher._safe_float(None) is None

    def test_safe_float_dash(self):
        assert AKShareFetcher._safe_float("-") is None

    # ── GDP normalizer ──────────────────────────────────────────────────

    @patch("data.fetchers.akshare_fetcher.ak")
    def test_fetch_gdp(self, mock_ak):
        mock_ak.macro_china_gdp.return_value = MOCK_GDP_DF
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_indicator("gdp")

        assert "gdp" in result
        df = result["gdp"]
        # 2015 row filtered out (start_year=2016), 2 rows remain
        assert len(df) == 2
        assert df.iloc[0]["indicator"] == "gdp"
        assert df.iloc[0]["value"] == 284997.0
        assert df.iloc[0]["date"] == datetime(2023, 12, 1)  # Q4 → December

    # ── CPI normalizer ──────────────────────────────────────────────────

    @patch("data.fetchers.akshare_fetcher.ak")
    def test_fetch_cpi(self, mock_ak):
        mock_ak.macro_china_cpi.return_value = MOCK_CPI_DF
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_indicator("cpi")

        df = result["cpi"]
        assert len(df) == 2
        assert df.iloc[0]["mom_pct"] == 1.0
        assert df.iloc[1]["yoy_pct"] == 0.1

    # ── PPI normalizer ──────────────────────────────────────────────────

    @patch("data.fetchers.akshare_fetcher.ak")
    def test_fetch_ppi(self, mock_ak):
        mock_ak.macro_china_ppi.return_value = MOCK_PPI_DF
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_indicator("ppi")

        df = result["ppi"]
        assert len(df) == 2
        assert df.iloc[0]["yoy_pct"] == -2.7

    # ── PMI normalizer (multi-indicator) ────────────────────────────────

    @patch("data.fetchers.akshare_fetcher.ak")
    def test_fetch_pmi(self, mock_ak):
        mock_ak.macro_china_pmi.return_value = MOCK_PMI_DF
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_indicator("pmi")

        assert "pmi_manufacturing" in result
        assert "pmi_non_manufacturing" in result
        mfg = result["pmi_manufacturing"]
        assert len(mfg) == 2
        assert mfg.iloc[0]["value"] == 49.1
        non_mfg = result["pmi_non_manufacturing"]
        assert non_mfg.iloc[1]["value"] == 53.0

    # ── Money supply normalizer (multi-indicator) ───────────────────────

    @patch("data.fetchers.akshare_fetcher.ak")
    def test_fetch_money_supply(self, mock_ak):
        mock_ak.macro_china_money_supply.return_value = MOCK_MONEY_SUPPLY_DF
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_indicator("money_supply")

        assert "m2" in result
        assert "m1" in result
        m2 = result["m2"]
        assert m2.iloc[0]["yoy_pct"] == 8.3
        m1 = result["m1"]
        assert m1.iloc[0]["yoy_pct"] == 1.1

    # ── Trade normalizer (multi-indicator) ──────────────────────────────

    @patch("data.fetchers.akshare_fetcher.ak")
    def test_fetch_trade(self, mock_ak):
        mock_ak.macro_china_hgjck.return_value = MOCK_TRADE_DF
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_indicator("trade")

        assert "exports" in result
        assert "imports" in result
        exports = result["exports"]
        assert exports.iloc[0]["value"] == 2796.0
        assert exports.iloc[0]["yoy_pct"] == -7.5

    # ── Industrial normalizer ───────────────────────────────────────────

    @patch("data.fetchers.akshare_fetcher.ak")
    def test_fetch_industrial(self, mock_ak):
        mock_ak.macro_china_gyzjz.return_value = MOCK_INDUSTRIAL_DF
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_indicator("industrial")

        df = result["industrial"]
        assert len(df) == 2
        assert df.iloc[0]["yoy_pct"] == 7.0

    # ── Retail normalizer ───────────────────────────────────────────────

    @patch("data.fetchers.akshare_fetcher.ak")
    def test_fetch_retail(self, mock_ak):
        mock_ak.macro_china_consumer_goods_retail.return_value = MOCK_RETAIL_DF
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_indicator("retail")

        df = result["retail"]
        assert df.iloc[0]["value"] == 35699.0
        assert df.iloc[0]["mom_pct"] == 0.26

    # ── Credit normalizer ───────────────────────────────────────────────

    @patch("data.fetchers.akshare_fetcher.ak")
    def test_fetch_credit(self, mock_ak):
        mock_ak.macro_china_new_financial_credit.return_value = MOCK_CREDIT_DF
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_indicator("credit")

        df = result["credit"]
        assert df.iloc[0]["yoy_pct"] == 5.0

    # ── fetch_all catches errors ────────────────────────────────────────

    @patch("data.fetchers.akshare_fetcher.ak")
    def test_fetch_all_handles_errors(self, mock_ak):
        """fetch_all should catch per-indicator errors and continue."""
        mock_ak.macro_china_gdp.side_effect = Exception("network error")
        mock_ak.macro_china_cpi.return_value = MOCK_CPI_DF
        mock_ak.macro_china_ppi.side_effect = Exception("timeout")
        mock_ak.macro_china_pmi.return_value = MOCK_PMI_DF
        mock_ak.macro_china_money_supply.side_effect = Exception("fail")
        mock_ak.macro_china_hgjck.side_effect = Exception("fail")
        mock_ak.macro_china_gyzjz.side_effect = Exception("fail")
        mock_ak.macro_china_consumer_goods_retail.side_effect = Exception("fail")
        mock_ak.macro_china_new_financial_credit.side_effect = Exception("fail")

        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_all()

        # CPI and PMI should succeed
        assert "cpi" in result
        assert "pmi_manufacturing" in result
        # GDP should be missing
        assert "gdp" not in result

    # ── get_label ───────────────────────────────────────────────────────

    def test_get_label(self):
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        assert fetcher.get_label("gdp") == "GDP"
        assert fetcher.get_label("money_supply") == "货币供应"
        assert fetcher.get_label("nonexistent") == "nonexistent"

    # ── Unknown indicator ───────────────────────────────────────────────

    def test_unknown_indicator_raises(self):
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        with pytest.raises(ValueError, match="Unknown indicator"):
            fetcher.fetch_indicator("nonexistent")

    # ── start_year filtering ────────────────────────────────────────────

    @patch("data.fetchers.akshare_fetcher.ak")
    def test_start_year_filter(self, mock_ak):
        """Data before start_year (2016) should be excluded."""
        old_data = pd.DataFrame([
            {"季度": "2015年第1季度", "国内生产总值-绝对值": 100000.0, "国内生产总值-同比增长": 7.0},
            {"季度": "2016年第1季度", "国内生产总值-绝对值": 110000.0, "国内生产总值-同比增长": 6.7},
        ])
        mock_ak.macro_china_gdp.return_value = old_data
        fetcher = AKShareFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_indicator("gdp")

        df = result["gdp"]
        assert len(df) == 1
        assert df.iloc[0]["date"] == datetime(2016, 3, 1)  # Q1 → March
