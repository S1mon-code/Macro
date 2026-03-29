import time
import logging
import requests
import pandas as pd
import yaml
from datetime import datetime

logger = logging.getLogger(__name__)


class FREDFetcher:
    """从美联储经济数据库 (FRED) API 获取宏观经济数据"""

    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        fred_config = config["fred"]

        self.api_key = fred_config["api_key"]
        self.base_url = fred_config["base_url"]
        self.series = fred_config["series"]
        self.labels = fred_config["labels"]
        self.start_year = fred_config.get("start_year", 2016)
        self.daily_series = fred_config.get("daily_series", [])
        self.weekly_series = fred_config.get("weekly_series", [])
        self.quarterly_series = fred_config.get("quarterly_series", [])
        self.rate_series = fred_config.get("rate_series", [])

    def fetch_series(
        self, series_id: str, start_date: str | None = None
    ) -> pd.DataFrame:
        """拉取单个 FRED series 的观测数据，返回 DataFrame"""
        if start_date is None:
            start_date = f"{self.start_year}-01-01"

        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start_date,
            "sort_order": "asc",
        }

        response = requests.get(self.base_url, params=params)
        response.raise_for_status()
        data = response.json()

        rows = []
        for obs in data.get("observations", []):
            if obs["value"] == ".":
                continue
            try:
                value = float(obs["value"])
            except (ValueError, TypeError):
                continue
            rows.append({
                "series_id": series_id,
                "date": datetime.strptime(obs["date"], "%Y-%m-%d"),
                "value": value,
            })

        # Rate limit: 120 requests/min → sleep 0.5s between calls
        time.sleep(0.5)

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("date").reset_index(drop=True)
        return df

    def fetch_all(self) -> dict[str, pd.DataFrame]:
        """拉取所有配置的 FRED 数据

        返回 {指标名: DataFrame} 的字典，每个 DataFrame 包含:
        date, value, yoy_pct, mom_pct（已转为 list 以兼容 Plotly）
        """
        result = {}

        for name, series_id in self.series.items():
            try:
                df = self.fetch_series(series_id)
                if df.empty:
                    logger.warning(f"FRED series {name} ({series_id}) returned no data")
                    result[name] = df
                    continue

                # 日频/周频数据转月均
                if name in self.daily_series or name in self.weekly_series:
                    df = self._to_monthly(df)

                # 计算同比/环比
                is_quarterly = name in self.quarterly_series
                is_rate = name in self.rate_series
                df = self._compute_changes(df, quarterly=is_quarterly, rate=is_rate)

                # 转为 list 以兼容 Plotly
                for col in df.columns:
                    df[col] = df[col].tolist()

                result[name] = df

            except Exception as e:
                logger.error(f"Failed to fetch FRED series {name} ({series_id}): {e}")
                continue

        # 用原始数据计算精确失业率（FRED UNRATE 只有1位小数）
        if "unemployed_count" in result and "labor_force" in result:
            try:
                ue = result["unemployed_count"].copy()
                lf = result["labor_force"].copy()
                merged = pd.merge(ue[["date", "value"]], lf[["date", "value"]],
                                  on="date", suffixes=("_ue", "_lf"))
                merged["value"] = (merged["value_ue"] / merged["value_lf"]) * 100
                merged["series_id"] = "UNRATE_PRECISE"
                merged = merged[["series_id", "date", "value"]].copy()
                merged = self._compute_changes(merged, rate=True)
                for col in merged.columns:
                    merged[col] = merged[col].tolist()
                result["unemployment"] = merged
            except Exception as e:
                logger.warning(f"Failed to compute precise unemployment rate: {e}")

        return result

    @staticmethod
    def _to_monthly(df: pd.DataFrame) -> pd.DataFrame:
        """将日频数据按年月分组取均值，转为月度数据"""
        df = df.copy()
        df["year_month"] = df["date"].dt.to_period("M")
        monthly = (
            df.groupby("year_month")
            .agg({"series_id": "first", "value": "mean"})
            .reset_index()
        )
        monthly["date"] = monthly["year_month"].dt.to_timestamp()
        monthly = monthly.drop(columns=["year_month"])
        monthly = monthly.sort_values("date").reset_index(drop=True)
        return monthly

    @staticmethod
    def _compute_changes(
        df: pd.DataFrame, quarterly: bool = False, rate: bool = False
    ) -> pd.DataFrame:
        """计算同比 (yoy_pct) 和环比 (mom_pct)

        rate=True: 比率类指标（失业率、利率等），用差值而非变化率
        rate=False: 水平类指标（GDP、零售额等），用百分比变化率
        """
        df = df.copy()
        df = df.sort_values("date").reset_index(drop=True)

        yoy_periods = 4 if quarterly else 12

        if rate:
            # 比率类：同比/环比用差值（如失业率从4.0到4.4 → +0.4）
            df["mom_pct"] = df["value"].diff(1)
            df["yoy_pct"] = df["value"].diff(yoy_periods)
        else:
            # 水平类：同比/环比用百分比变化率
            df["mom_pct"] = df["value"].pct_change(1) * 100
            df["yoy_pct"] = df["value"].pct_change(yoy_periods) * 100

        return df

    def get_label(self, name: str) -> str:
        """获取指标的中文名"""
        return self.labels.get(name, name)
