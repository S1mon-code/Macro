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
            "fx_reserves": self._normalize_fx_reserves,
            "lpr": self._normalize_lpr,
            "shibor": self._normalize_shibor,
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
        """Parse Chinese quarterly date (single quarter only).
        '2024年第1季度'  → datetime(2024, 3, 1)   (end-of-quarter month)
        '2024年第1-4季度' → None                    (cumulative → skip)
        """
        # Cumulative format: "2024年第1-4季度" → skip
        m = re.match(r"(\d{4})年第(\d)-\d季度", str(text))
        if m:
            return None
        # Single quarter: "2024年第1季度"
        m = re.match(r"(\d{4})年第(\d)季度", str(text))
        if m:
            year = int(m.group(1))
            q = int(m.group(2))
            month = q * 3  # Q1→3, Q2→6, Q3→9, Q4→12
            return datetime(year, month, 1)
        return None

    @staticmethod
    def _safe_float(val) -> float | None:
        if val is None or val == "" or val == "-":
            return None
        try:
            result = float(val)
            if pd.isna(result):
                return None
            return result
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
            # 自动计算缺失的同比/环比
            if "yoy_pct" in df.columns and df["yoy_pct"].isna().all() and "value" in df.columns:
                # 用差值（适用于 PMI 等指数类指标）
                df["yoy_pct"] = df["value"].diff(12)
            if "mom_pct" in df.columns and df["mom_pct"].isna().all() and "value" in df.columns:
                df["mom_pct"] = df["value"].pct_change(1) * 100
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
            # Skip rows where 同比增长 is NaN (e.g. Feb in combined Jan-Feb release)
            yoy = self._safe_float(r.get("同比增长"))
            if yoy is None:
                continue
            date = self._parse_month(str(r.get("月份", "")))
            row = self._make_row(
                indicator="industrial",
                date=date,
                yoy_pct=yoy,
            )
            if row:
                rows.append(row)
        return pd.DataFrame(rows)

    def _normalize_retail(self, df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, r in df.iterrows():
            # Skip rows where 当月 is NaN (e.g. Feb in combined Jan-Feb release)
            value = self._safe_float(r.get("当月"))
            if value is None:
                continue
            date = self._parse_month(str(r.get("月份", "")))
            row = self._make_row(
                indicator="retail",
                date=date,
                value=value,
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

    def _normalize_fx_reserves(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        """Normalize macro_china_fx_gold() output.

        Columns: 月份, 国家外汇储备-数值, 国家外汇储备-同比, 黄金储备-数值, 黄金储备-同比
        Produces two sub-indicators: fx_reserves and gold_reserves.
        """
        fx_rows = []
        gold_rows = []
        for _, r in df.iterrows():
            date = self._parse_month(str(r.get("月份", "")))
            if date is None:
                continue
            fx = self._make_row(
                indicator="fx_reserves",
                date=date,
                value=r.get("国家外汇储备-数值"),
                yoy_pct=r.get("国家外汇储备-同比"),
            )
            gold = self._make_row(
                indicator="gold_reserves",
                date=date,
                value=r.get("黄金储备-数值"),
                yoy_pct=r.get("黄金储备-同比"),
            )
            if fx:
                fx_rows.append(fx)
            if gold:
                gold_rows.append(gold)
        return {
            "fx_reserves": pd.DataFrame(fx_rows),
            "gold_reserves": pd.DataFrame(gold_rows),
        }

    def _normalize_lpr(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        """Normalize macro_china_lpr() output.

        Columns: TRADE_DATE, LPR1Y, LPR5Y, RATE_1, RATE_2
        Produces two sub-indicators: lpr_1y and lpr_5y.
        """
        lpr1_rows = []
        lpr5_rows = []
        for _, r in df.iterrows():
            raw_date = r.get("TRADE_DATE") or r.get("日期")
            if raw_date is None:
                continue
            try:
                date = pd.to_datetime(raw_date)
            except Exception:
                continue

            # Try multiple possible column names
            lpr1_val = None
            for col in ["LPR1Y", "LPR_1Y", "1Y"]:
                if r.get(col) is not None:
                    lpr1_val = r.get(col)
                    break
            lpr5_val = None
            for col in ["LPR5Y", "LPR_5Y", "5Y"]:
                if r.get(col) is not None:
                    lpr5_val = r.get(col)
                    break

            lpr1 = self._make_row(
                indicator="lpr_1y",
                date=date,
                value=lpr1_val,
            )
            lpr5 = self._make_row(
                indicator="lpr_5y",
                date=date,
                value=lpr5_val,
            )
            if lpr1:
                lpr1_rows.append(lpr1)
            if lpr5:
                lpr5_rows.append(lpr5)
        return {
            "lpr_1y": pd.DataFrame(lpr1_rows),
            "lpr_5y": pd.DataFrame(lpr5_rows),
        }

    def _normalize_shibor(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        """Normalize macro_china_shibor_all() output.

        Columns: 日期, O/N (or 隔夜), 1W, 2W, 1M, 3M, 6M, 9M, 1Y
        Daily data — resample to monthly (last value of each month).
        Produces: shibor_on (overnight) and shibor_3m (3-month).
        """
        # Parse date column
        date_col = "日期" if "日期" in df.columns else df.columns[0]
        df = df.copy()
        df["_date"] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=["_date"])
        df = df.set_index("_date").sort_index()

        # Identify overnight and 3M columns (actual names include -定价 suffix)
        on_col = None
        for candidate in ["O/N-定价", "O/N", "隔夜", "O/N(隔夜)"]:
            if candidate in df.columns:
                on_col = candidate
                break
        m3_col = None
        for candidate in ["3M-定价", "3M", "3M(3个月)"]:
            if candidate in df.columns:
                m3_col = candidate
                break

        # Resample to monthly (last value)
        on_rows = []
        m3_rows = []
        if on_col:
            on_monthly = pd.to_numeric(df[on_col], errors="coerce").resample("ME").last().dropna()
            for date, val in on_monthly.items():
                row = self._make_row(indicator="shibor_on", date=date, value=val)
                if row:
                    on_rows.append(row)
        if m3_col:
            m3_monthly = pd.to_numeric(df[m3_col], errors="coerce").resample("ME").last().dropna()
            for date, val in m3_monthly.items():
                row = self._make_row(indicator="shibor_3m", date=date, value=val)
                if row:
                    m3_rows.append(row)

        return {
            "shibor_on": pd.DataFrame(on_rows),
            "shibor_3m": pd.DataFrame(m3_rows),
        }
