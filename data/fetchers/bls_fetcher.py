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
        import os
        self.api_key = bls_config.get("api_key", "") or os.environ.get("BLS_API_KEY", "")
        self.series = cpi_config["series"]
        self.labels = cpi_config["labels"]
        self.start_year = cpi_config.get("start_year", 2020)

    @staticmethod
    def _safe_float(val) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

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
                    # BLS returns '-' for unavailable values
                    try:
                        value = float(item["value"])
                    except (ValueError, TypeError):
                        continue
                    calcs = item.get("calculations", {})
                    pct = calcs.get("pct_changes", {})
                    rows.append({
                        "series_id": sid,
                        "date": datetime(year, month, 1),
                        "year": year,
                        "month": month,
                        "value": value,
                        "yoy_pct": self._safe_float(pct.get("12")),
                        "mom_pct": self._safe_float(pct.get("1")),
                    })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("date").reset_index(drop=True)
            # 如果 API 没返回 calculations（无 API Key），自行计算
            df = self._compute_changes(df)
        return df

    @staticmethod
    def _compute_changes(df: pd.DataFrame) -> pd.DataFrame:
        """对每个 series 自行计算同比/环比百分比（当 API 未返回时）"""
        results = []
        for sid, group in df.groupby("series_id"):
            group = group.sort_values("date").copy()
            # 环比: 相对上月变化百分比
            if group["mom_pct"].isna().all():
                group["mom_pct"] = group["value"].pct_change() * 100
            # 同比: 相对去年同月变化百分比
            if group["yoy_pct"].isna().all():
                group["yoy_pct"] = group["value"].pct_change(periods=12) * 100
            results.append(group)
        return pd.concat(results, ignore_index=True)

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
