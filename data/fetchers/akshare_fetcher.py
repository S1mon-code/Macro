import re
import pandas as pd
import numpy as np
import yaml
from datetime import datetime
from pathlib import Path

try:
    import akshare as ak
except ImportError:
    ak = None


class AKShareFetcher:
    """从 AKShare 获取中国宏观经济数据"""

    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        china_config = config["china"]
        self.indicators = china_config["indicators"]
        self.start_year = china_config.get("start_year", 2016)

        # Map indicator names to their normalize methods
        self._normalizers = {
            "gdp": self._normalize_gdp,
            "cpi": self._normalize_cpi,
            "ppi": self._normalize_ppi,
            "pmi": self._normalize_pmi,
            "money_supply": self._normalize_money_supply,
            "trade": self._normalize_trade,
            "industrial": self._normalize_industrial,
            "retail": self._normalize_retail,
            "credit": self._normalize_credit,
        }

    # ── Date parsing helpers ────────────────────────────────────────────

    @staticmethod
    def _parse_month(text: str) -> datetime | None:
        """Parse Chinese monthly date: '2024年03月份' → datetime(2024, 3, 1)"""
        m = re.match(r"(\d{4})年(\d{1,2})月份?", str(text))
        if m:
            return datetime(int(m.group(1)), int(m.group(2)), 1)
        return None

    @staticmethod
    def _parse_quarter(text: str) -> datetime | None:
        """Parse Chinese quarterly date.
        '2024年第1季度'  → datetime(2024, 1, 1)
        '2024年第1-4季度' → datetime(2024, 1, 1)  (cumulative = Q1 start)
        """
        # Cumulative format: "2024年第1-4季度"
        m = re.match(r"(\d{4})年第(\d)-\d季度", str(text))
        if m:
            year = int(m.group(1))
            q_start = int(m.group(2))
            month = (q_start - 1) * 3 + 1
            return datetime(year, month, 1)
        # Single quarter: "2024年第1季度"
        m = re.match(r"(\d{4})年第(\d)季度", str(text))
        if m:
            year = int(m.group(1))
            q = int(m.group(2))
            month = (q - 1) * 3 + 1
            return datetime(year, month, 1)
        return None

    @staticmethod
    def _safe_float(val) -> float | None:
        if val is None or val == "" or val == "-":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    # ── Core fetch logic ────────────────────────────────────────────────

    def fetch_indicator(self, name: str) -> dict[str, pd.DataFrame]:
        """Fetch and normalize a single indicator by config name.

        Returns a dict because some indicators (pmi, money_supply, trade)
        produce multiple sub-indicators from one API call.
        """
        if ak is None:
            raise ImportError("akshare is not installed. Run: pip install akshare")

        if name not in self.indicators:
            raise ValueError(f"Unknown indicator: {name}")

        cfg = self.indicators[name]
        func_name = cfg["func"]

        # Call the AKShare function
        func = getattr(ak, func_name)
        raw_df = func()

        # Normalize
        normalizer = self._normalizers.get(name)
        if normalizer is None:
            raise ValueError(f"No normalizer for indicator: {name}")

        result = normalizer(raw_df)

        # result may be a single DataFrame or a dict of DataFrames
        if isinstance(result, pd.DataFrame):
            result = {name: result}

        # Filter by start_year and clean up each DataFrame
        cutoff = datetime(self.start_year, 1, 1)
        for key in list(result.keys()):
            df = result[key]
            if df.empty:
                continue
            df = df[df["date"] >= cutoff].copy()
            df = df.sort_values("date").reset_index(drop=True)
            # Ensure float types
            for col in ["value", "yoy_pct", "mom_pct"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            result[key] = df

        return result

    def fetch_all(self) -> dict[str, pd.DataFrame]:
        """Fetch all configured indicators. Returns dict[name, DataFrame]."""
        all_data = {}
        for name in self.indicators:
            try:
                result = self.fetch_indicator(name)
                all_data.update(result)
            except Exception as e:
                print(f"[AKShareFetcher] Failed to fetch '{name}': {e}")
        return all_data

    def get_label(self, name: str) -> str:
        """获取指标的中文名"""
        cfg = self.indicators.get(name)
        if cfg:
            return cfg.get("label", name)
        return name

    # ── Normalizers ─────────────────────────────────────────────────────

    def _make_row(
        self,
        indicator: str,
        date: datetime | None,
        value=None,
        yoy_pct=None,
        mom_pct=None,
    ) -> dict | None:
        if date is None:
            return None
        return {
            "indicator": indicator,
            "date": date,
            "value": self._safe_float(value),
            "yoy_pct": self._safe_float(yoy_pct),
            "mom_pct": self._safe_float(mom_pct),
        }

    def _normalize_gdp(self, df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, r in df.iterrows():
            date = self._parse_quarter(str(r.get("季度", "")))
            row = self._make_row(
                indicator="gdp",
                date=date,
                value=r.get("国内生产总值-绝对值"),
                yoy_pct=r.get("国内生产总值-同比增长"),
            )
            if row:
                rows.append(row)
        return pd.DataFrame(rows)

    def _normalize_cpi(self, df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, r in df.iterrows():
            date = self._parse_month(str(r.get("月份", "")))
            row = self._make_row(
                indicator="cpi",
                date=date,
                value=r.get("全国-当月"),
                yoy_pct=r.get("全国-同比增长"),
                mom_pct=r.get("全国-环比增长"),
            )
            if row:
                rows.append(row)
        return pd.DataFrame(rows)

    def _normalize_ppi(self, df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, r in df.iterrows():
            date = self._parse_month(str(r.get("月份", "")))
            row = self._make_row(
                indicator="ppi",
                date=date,
                value=r.get("当月"),
                yoy_pct=r.get("当月同比增长"),
            )
            if row:
                rows.append(row)
        return pd.DataFrame(rows)

    def _normalize_pmi(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        mfg_rows = []
        non_mfg_rows = []
        for _, r in df.iterrows():
            date = self._parse_month(str(r.get("月份", "")))
            if date is None:
                continue
            mfg = self._make_row(
                indicator="pmi_manufacturing",
                date=date,
                value=r.get("制造业-指数"),
            )
            non_mfg = self._make_row(
                indicator="pmi_non_manufacturing",
                date=date,
                value=r.get("非制造业-指数"),
            )
            if mfg:
                mfg_rows.append(mfg)
            if non_mfg:
                non_mfg_rows.append(non_mfg)
        return {
            "pmi_manufacturing": pd.DataFrame(mfg_rows),
            "pmi_non_manufacturing": pd.DataFrame(non_mfg_rows),
        }

    def _normalize_money_supply(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        m2_rows = []
        m1_rows = []
        for _, r in df.iterrows():
            date = self._parse_month(str(r.get("月份", "")))
            if date is None:
                continue
            m2 = self._make_row(
                indicator="m2",
                date=date,
                value=r.get("货币和准货币(M2)-数量(亿元)"),
                yoy_pct=r.get("货币和准货币(M2)-同比增长"),
            )
            m1 = self._make_row(
                indicator="m1",
                date=date,
                value=r.get("货币(M1)-数量(亿元)"),
                yoy_pct=r.get("货币(M1)-同比增长"),
            )
            if m2:
                m2_rows.append(m2)
            if m1:
                m1_rows.append(m1)
        return {
            "m2": pd.DataFrame(m2_rows),
            "m1": pd.DataFrame(m1_rows),
        }

    def _normalize_trade(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        export_rows = []
        import_rows = []
        for _, r in df.iterrows():
            date = self._parse_month(str(r.get("月份", "")))
            if date is None:
                continue
            exp = self._make_row(
                indicator="exports",
                date=date,
                value=r.get("当月出口额-金额"),
                yoy_pct=r.get("当月出口额-同比增长"),
            )
            imp = self._make_row(
                indicator="imports",
                date=date,
                value=r.get("当月进口额-金额"),
                yoy_pct=r.get("当月进口额-同比增长"),
            )
            if exp:
                export_rows.append(exp)
            if imp:
                import_rows.append(imp)
        return {
            "exports": pd.DataFrame(export_rows),
            "imports": pd.DataFrame(import_rows),
        }

    def _normalize_industrial(self, df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, r in df.iterrows():
            date = self._parse_month(str(r.get("月份", "")))
            row = self._make_row(
                indicator="industrial",
                date=date,
                yoy_pct=r.get("同比增长"),
            )
            if row:
                rows.append(row)
        return pd.DataFrame(rows)

    def _normalize_retail(self, df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, r in df.iterrows():
            date = self._parse_month(str(r.get("月份", "")))
            row = self._make_row(
                indicator="retail",
                date=date,
                value=r.get("当月"),
                yoy_pct=r.get("同比增长"),
                mom_pct=r.get("环比增长"),
            )
            if row:
                rows.append(row)
        return pd.DataFrame(rows)

    def _normalize_credit(self, df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, r in df.iterrows():
            date = self._parse_month(str(r.get("月份", "")))
            row = self._make_row(
                indicator="credit",
                date=date,
                value=r.get("当月"),
                yoy_pct=r.get("当月-同比增长"),
            )
            if row:
                rows.append(row)
        return pd.DataFrame(rows)
