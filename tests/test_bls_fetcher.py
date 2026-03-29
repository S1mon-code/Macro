import pytest
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
        fetcher = BLSFetcher(config_path="config/settings.yaml")
        assert fetcher.base_url == "https://api.bls.gov/publicAPI/v2/timeseries/data/"
        assert "all_items" in fetcher.series

    @patch("data.fetchers.bls_fetcher.requests.post")
    def test_fetch_series_returns_dataframe(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        fetcher = BLSFetcher(config_path="config/settings.yaml")
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

        fetcher = BLSFetcher(config_path="config/settings.yaml")
        result = fetcher.fetch_cpi_all()

        assert isinstance(result, dict)
        mock_post.assert_called()

    @patch("data.fetchers.bls_fetcher.requests.post")
    def test_parse_includes_yoy_and_mom(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        fetcher = BLSFetcher(config_path="config/settings.yaml")
        df = fetcher.fetch_series(["CUSR0000SA0"], start_year=2026, end_year=2026)

        assert "yoy_pct" in df.columns
        assert "mom_pct" in df.columns
        assert df.iloc[0]["yoy_pct"] == 2.6
