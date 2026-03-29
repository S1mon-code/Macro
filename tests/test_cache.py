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
