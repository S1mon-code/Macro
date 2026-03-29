"""宏观环境定位引擎 — 增长 x 通胀四象限

根据多维宏观指标的 Z-Score 综合评分，将美国和中国
分别定位到 Reflation / Goldilocks / Stagflation / Deflation 四象限，
并输出对应的资产偏好建议。
"""

import pandas as pd
import numpy as np
from datetime import datetime


class MacroRegime:
    """宏观环境定位 — 增长×通胀四象限"""

    QUADRANTS = {
        (True, True): {
            "name": "Reflation",
            "cn": "再通胀",
            "color": "orange",
            "assets": "商品✓ 周期股✓ TIPS✓ | 成长股✗ 长债✗",
        },
        (True, False): {
            "name": "Goldilocks",
            "cn": "金发女孩",
            "color": "green",
            "assets": "股指✓ 信用债✓ 白银✓ | 黄金✗ 现金✗",
        },
        (False, True): {
            "name": "Stagflation",
            "cn": "滞胀",
            "color": "red",
            "assets": "黄金✓ 大宗商品✓ 现金✓ | 股指✗ 长债✗",
        },
        (False, False): {
            "name": "Deflation",
            "cn": "通缩/衰退",
            "color": "blue",
            "assets": "国债✓ 黄金✓ 防御股✓ | 周期股✗ 商品✗",
        },
    }

    # ── 公开接口 ──────────────────────────────────────────────────

    def assess_us(self, us_data: dict) -> dict:
        """
        Assess US macro regime.

        Parameters
        ----------
        us_data : dict
            Combined dict of CPI + FRED data, keyed by indicator name,
            values are DataFrames with 'date' and various columns.

        Returns
        -------
        dict
            {
                "growth_score": float (-1 to 1),
                "inflation_score": float (-1 to 1),
                "growth_high": bool,
                "inflation_high": bool,
                "quadrant": str (e.g. "Goldilocks"),
                "quadrant_cn": str (e.g. "金发女孩"),
                "color": str,
                "assets": str,
                "growth_details": [{name, value, z_score, signal}],
                "inflation_details": [{name, value, z_score, signal}],
                "policy_details": [{name, value, z_score, signal}],
            }
        """
        if not us_data:
            return self._empty_result(region="us")

        # Growth indicators (~50% weight)
        growth_indicators = [
            ("lei", "value", "LEI 领先指标", False),
            ("nonfarm_payrolls", "mom_pct", "NFP 环比", False),
            ("initial_claims", "value", "初请失业金", True),
            ("retail_sales", "yoy_pct", "零售销售 YoY", False),
            ("consumer_sentiment", "value", "消费者信心", False),
            ("industrial_production", "yoy_pct", "工业生产 YoY", False),
        ]

        # Inflation indicators (~25% weight)
        inflation_indicators = [
            ("core_pce", "yoy_pct", "核心 PCE YoY", False),
            ("sticky_cpi", "value", "粘性 CPI", False),
            ("avg_hourly_earnings", "yoy_pct", "平均时薪 YoY", False),
            ("trimmed_mean_pce", "value", "截尾均值 PCE", False),
        ]

        # Policy indicators (~25% weight)
        policy_indicators = [
            ("fed_funds_rate", "mom_pct", "联邦基金利率变化", True),
            ("yield_spread", "value", "收益率曲线 10Y-2Y", False),
            ("m2_money_supply", "yoy_pct", "M2 YoY", False),
        ]

        growth_details = self._score_indicators(us_data, growth_indicators)
        inflation_details = self._score_indicators(us_data, inflation_indicators)
        policy_details = self._score_indicators(us_data, policy_indicators)

        growth_score = self._average_z(growth_details)
        inflation_score = self._average_z(inflation_details)

        # Policy tilts the growth score (70/30 blend)
        policy_score = self._average_z(policy_details)
        adjusted_growth = growth_score * 0.7 + policy_score * 0.3

        growth_high = adjusted_growth > 0
        inflation_high = inflation_score > 0

        quad = self.QUADRANTS[(growth_high, inflation_high)]

        return {
            "growth_score": round(adjusted_growth, 3),
            "inflation_score": round(inflation_score, 3),
            "growth_high": growth_high,
            "inflation_high": inflation_high,
            "quadrant": quad["name"],
            "quadrant_cn": quad["cn"],
            "color": quad["color"],
            "assets": quad["assets"],
            "growth_details": growth_details,
            "inflation_details": inflation_details,
            "policy_details": policy_details,
        }

    def assess_china(self, china_data: dict, us_regime: dict | None = None) -> dict:
        """
        Assess China macro regime.

        Parameters
        ----------
        china_data : dict
            {指标名: DataFrame}
        us_regime : dict | None
            Optional US regime result for transmission effect.

        Returns
        -------
        dict
            Same structure as assess_us (without policy_details).
        """
        if not china_data:
            return self._empty_result(region="china")

        growth_indicators = [
            ("pmi_manufacturing", "value", "制造业 PMI", False),
            ("industrial", "yoy_pct", "工业增加值 YoY", False),
            ("retail", "yoy_pct", "零售 YoY", False),
            ("credit", "value", "新增信贷", False),
        ]

        inflation_indicators = [
            ("cpi", "yoy_pct", "CPI YoY", False),
            ("ppi", "yoy_pct", "PPI YoY", False),
        ]

        growth_details = self._score_indicators(china_data, growth_indicators)
        inflation_details = self._score_indicators(china_data, inflation_indicators)

        growth_score = self._average_z(growth_details)
        inflation_score = self._average_z(inflation_details)

        # US transmission: if US is in a deep contraction, drag China growth ~10%
        if us_regime and us_regime.get("growth_score", 0) < -0.3:
            growth_score += -0.1

        growth_high = growth_score > 0
        inflation_high = inflation_score > 0
        quad = self.QUADRANTS[(growth_high, inflation_high)]

        return {
            "growth_score": round(growth_score, 3),
            "inflation_score": round(inflation_score, 3),
            "growth_high": growth_high,
            "inflation_high": inflation_high,
            "quadrant": quad["name"],
            "quadrant_cn": quad["cn"],
            "color": quad["color"],
            "assets": quad["assets"],
            "growth_details": growth_details,
            "inflation_details": inflation_details,
        }

    # ── 内部方法 ──────────────────────────────────────────────────

    def _score_indicators(
        self, data: dict, indicators: list[tuple]
    ) -> list[dict]:
        """Score a list of indicators using Z-score vs their own 5-year history.

        Parameters
        ----------
        data : dict
            {indicator_key: DataFrame}
        indicators : list[tuple]
            Each tuple: (key, col, display_name, inverted)

        Returns
        -------
        list[dict]
            [{name, value, z_score, signal}, ...]
            Indicators with missing / insufficient data are silently skipped.
        """
        results = []
        for key, col, name, inverted in indicators:
            df = data.get(key)
            if df is None:
                continue
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue
            if col not in df.columns:
                continue

            series = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(series) < 12:
                continue

            current = series.iloc[-1]
            if np.isnan(current):
                continue

            # 5-year (60-month) window for Z-score, fall back to all available
            window = series.tail(60)
            mean = window.mean()
            std = window.std()

            if std == 0 or np.isnan(std):
                z = 0.0
            else:
                z = (current - mean) / std

            if inverted:
                z = -z

            # Clip to [-3, 3]
            z = float(np.clip(z, -3.0, 3.0))

            signal = "偏多" if z > 0.5 else ("偏空" if z < -0.5 else "中性")

            results.append({
                "name": name,
                "value": round(float(current), 4),
                "z_score": round(z, 3),
                "signal": signal,
            })

        return results

    def _average_z(self, details: list[dict]) -> float:
        """Average Z-scores from scored indicator list. Returns 0 if empty."""
        if not details:
            return 0.0
        scores = [d["z_score"] for d in details]
        return sum(scores) / len(scores)

    def _empty_result(self, region: str = "us") -> dict:
        """Return a safe default when no data is available."""
        quad = self.QUADRANTS[(False, False)]
        result = {
            "growth_score": 0.0,
            "inflation_score": 0.0,
            "growth_high": False,
            "inflation_high": False,
            "quadrant": quad["name"],
            "quadrant_cn": quad["cn"],
            "color": quad["color"],
            "assets": quad["assets"],
            "growth_details": [],
            "inflation_details": [],
        }
        if region == "us":
            result["policy_details"] = []
        return result
