import pytest
from unittest.mock import patch, MagicMock
from data.fetchers.fred_fetcher import FREDFetcher

MOCK_RESPONSE = {
    "observations": [
        {"date": "2026-01-01", "value": "4.1"},
        {"date": "2026-02-01", "value": "4.0"},
        {"date": "2026-03-01", "value": "."},
        {"date": "2026-04-01", "value": "3.9"},
    ]
}

MOCK_DAILY_RESPONSE = {
    "observations": [
        {"date": "2026-01-02", "value": "4.10"},
        {"date": "2026-01-03", "value": "4.12"},
        {"date": "2026-01-06", "value": "4.08"},
        {"date": "2026-02-03", "value": "4.20"},
        {"date": "2026-02-04", "value": "4.18"},
    ]
}


class TestFREDFetcher:
    def test_init_loads_config(self):
        fetcher = FREDFetcher(config_path="config/settings.yaml")
        assert fetcher.base_url == "https://api.stlouisfed.org/fred/series/observations"
        # API key now from env var or settings (may be empty in test)
        assert isinstance(fetcher.api_key, str)
        assert "gdp" in fetcher.series
        assert "treasury_10y" in fetcher.daily_series
        assert "gdp" in fetcher.quarterly_series

    @patch("data.fetchers.fred_fetcher.time.sleep")
    @patch("data.fetchers.fred_fetcher.requests.get")
    def test_fetch_series_returns_dataframe(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        fetcher = FREDFetcher(config_path="config/settings.yaml")
        df = fetcher.fetch_series("UNRATE", start_date="2026-01-01")

        # "." value should be skipped → 3 rows
        assert len(df) == 3
        assert "date" in df.columns
        assert "value" in df.columns
        assert "series_id" in df.columns
        assert df["value"].dtype == float
        mock_sleep.assert_called_once_with(0.5)

    @patch("data.fetchers.fred_fetcher.time.sleep")
    @patch("data.fetchers.fred_fetcher.requests.get")
    def test_fetch_series_skips_missing_values(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        fetcher = FREDFetcher(config_path="config/settings.yaml")
        df = fetcher.fetch_series("UNRATE")

        # The "." entry should be excluded
        values = df["value"].tolist()
        assert 3.9 in values
        assert len(values) == 3

    @patch("data.fetchers.fred_fetcher.time.sleep")
    @patch("data.fetchers.fred_fetcher.requests.get")
    def test_to_monthly_aggregates_daily(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_DAILY_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        fetcher = FREDFetcher(config_path="config/settings.yaml")
        df = fetcher.fetch_series("DGS10")
        monthly = fetcher._to_monthly(df)

        # Should have 2 months: Jan and Feb
        assert len(monthly) == 2
        # Jan mean: (4.10 + 4.12 + 4.08) / 3 = 4.1
        assert abs(monthly.iloc[0]["value"] - 4.1) < 0.01

    def test_compute_changes_monthly(self):
        import pandas as pd
        from datetime import datetime

        dates = [datetime(2025, m, 1) for m in range(1, 13)] + \
                [datetime(2026, m, 1) for m in range(1, 4)]
        values = [100 + i for i in range(15)]
        df = pd.DataFrame({
            "series_id": ["TEST"] * 15,
            "date": dates,
            "value": values,
        })

        fetcher = FREDFetcher(config_path="config/settings.yaml")
        result = fetcher._compute_changes(df, quarterly=False)

        assert "yoy_pct" in result.columns
        assert "mom_pct" in result.columns
        # First row mom should be NaN
        assert pd.isna(result.iloc[0]["mom_pct"])
        # First 12 rows yoy should be NaN
        assert pd.isna(result.iloc[0]["yoy_pct"])
        # 13th row (index 12) yoy should be defined
        assert not pd.isna(result.iloc[12]["yoy_pct"])

    def test_compute_changes_quarterly(self):
        import pandas as pd
        from datetime import datetime

        dates = [datetime(2024, m, 1) for m in [1, 4, 7, 10]] + \
                [datetime(2025, m, 1) for m in [1, 4, 7, 10]]
        values = [100, 101, 102, 103, 104, 105, 106, 107]
        df = pd.DataFrame({
            "series_id": ["GDPC1"] * 8,
            "date": dates,
            "value": values,
        })

        fetcher = FREDFetcher(config_path="config/settings.yaml")
        result = fetcher._compute_changes(df, quarterly=True)

        # First 4 quarters yoy should be NaN
        assert pd.isna(result.iloc[0]["yoy_pct"])
        # 5th quarter (index 4) yoy should be defined
        assert not pd.isna(result.iloc[4]["yoy_pct"])

    @patch("data.fetchers.fred_fetcher.time.sleep")
    @patch("data.fetchers.fred_fetcher.requests.get")
    def test_fetch_all_returns_dict(self, mock_get, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        fetcher = FREDFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_all()

        assert isinstance(result, dict)
        mock_get.assert_called()
        # Should have attempted all series
        assert mock_get.call_count == len(fetcher.series)

    @patch("data.fetchers.fred_fetcher.time.sleep")
    @patch("data.fetchers.fred_fetcher.requests.get")
    def test_fetch_all_handles_errors_gracefully(self, mock_get, mock_sleep):
        mock_get.side_effect = Exception("API timeout")

        fetcher = FREDFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_all()

        # Should return empty dict, not raise
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_get_label(self):
        fetcher = FREDFetcher(config_path="config/settings.yaml")
        assert fetcher.get_label("gdp") == "实际 GDP"
        assert fetcher.get_label("unknown_key") == "unknown_key"
