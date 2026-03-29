"""宏观预测矩阵 — 预测所有关键指标，驱动前瞻性资产判断

核心创新：用预测值（而非历史值）重新推导宏观象限和资产评分，
实现"基于未来走向"的前瞻性投资判断。

预测方法论：
- NFP: 初请失业金 + JOLTS 调整的3月均值
- 失业率: Sahm-style 趋势外推 + 均值回归
- 联邦基金利率: Taylor Rule
- 消费者信心: 汽油价格传导 + 趋势动量
- CPI: 外部 CPIForecaster 自下而上分项预测
- 中国 PMI: 信贷脉冲领先(3-6月) + 趋势
- 其余指标: 加权趋势外推
"""

import pandas as pd
import numpy as np
from datetime import datetime

from analysis.regime import MacroRegime


class MacroForecastMatrix:
    """宏观预测矩阵 -- 预测所有关键指标，驱动前瞻性资产判断"""

    def __init__(self):
        self._regime_engine = MacroRegime()

    # ══════════════════════════════════════════════════════════════
    # 公开接口
    # ══════════════════════════════════════════════════════════════

    def forecast_all(
        self,
        us_data: dict,
        china_data: dict,
        cpi_forecast: dict = None,
    ) -> dict:
        """
        Forecast all key macro indicators.

        Parameters
        ----------
        us_data : dict
            US macro data {indicator_key: DataFrame}.
        china_data : dict
            China macro data {indicator_key: DataFrame}.
        cpi_forecast : dict, optional
            Pre-computed CPI forecast from CPIForecaster.forecast().

        Returns
        -------
        dict
            {
                "forecast_date": "2026年04月",
                "us_forecasts": [...],
                "china_forecasts": [...],
                "forward_regime_us": {...},
                "forward_regime_china": {...},
                "narrative": str,
            }
        """
        us_data = us_data or {}
        china_data = china_data or {}

        # ── Determine forecast date ──
        forecast_date = self._determine_forecast_date(us_data, china_data)
        forecast_date_str = forecast_date.strftime("%Y年%m月") if forecast_date else "未知"

        # ── US Forecasts ──
        us_forecasts = []

        # 1. CPI (from external CPIForecaster if available)
        us_forecasts.append(self._format_cpi_forecast(cpi_forecast, us_data))

        # 2. NFP
        us_forecasts.append(self._forecast_nfp(us_data))

        # 3. Unemployment
        us_forecasts.append(self._forecast_unemployment(us_data))

        # 4. Fed Funds Rate
        us_forecasts.append(self._forecast_fed_rate(us_data))

        # 5. Consumer Sentiment
        us_forecasts.append(self._forecast_consumer_sentiment(us_data))

        # 6. Retail Sales YoY
        us_forecasts.append(
            self._forecast_generic_trend(
                us_data, "retail_sales", "零售销售 YoY (%)", col="yoy_pct", months=3
            )
        )

        # 7. Industrial Production YoY
        us_forecasts.append(
            self._forecast_generic_trend(
                us_data, "industrial_production", "工业生产 YoY (%)", col="yoy_pct", months=3
            )
        )

        # 8. LEI
        us_forecasts.append(
            self._forecast_generic_trend(
                us_data, "lei", "LEI 领先指标", col="value", months=3
            )
        )

        # ── China Forecasts ──
        china_forecasts = []

        # 1. PMI
        china_forecasts.append(self._forecast_china_pmi(china_data))

        # 2. CPI YoY
        china_forecasts.append(
            self._forecast_generic_trend(
                china_data, "cpi", "CPI YoY (%)", col="yoy_pct", months=3
            )
        )

        # 3. PPI YoY
        china_forecasts.append(
            self._forecast_generic_trend(
                china_data, "ppi", "PPI YoY (%)", col="yoy_pct", months=3
            )
        )

        # 4. M2 YoY
        china_forecasts.append(
            self._forecast_generic_trend(
                china_data, "m2", "M2 YoY (%)", col="yoy_pct", months=3
            )
        )

        # 5. Retail YoY
        china_forecasts.append(
            self._forecast_generic_trend(
                china_data, "retail", "社会零售 YoY (%)", col="yoy_pct", months=3
            )
        )

        # ── Forward Regime (KEY INNOVATION) ──
        forward_us_data = self._build_forward_data_us(us_data, us_forecasts)
        forward_china_data = self._build_forward_data_china(china_data, china_forecasts)

        forward_regime_us = self._regime_engine.assess_us(forward_us_data)
        forward_regime_china = self._regime_engine.assess_china(
            forward_china_data, us_regime=forward_regime_us
        )

        # ── Narrative ──
        narrative = self._build_narrative(
            us_forecasts, china_forecasts, forward_regime_us, forward_regime_china
        )

        return {
            "forecast_date": forecast_date_str,
            "us_forecasts": us_forecasts,
            "china_forecasts": china_forecasts,
            "forward_regime_us": forward_regime_us,
            "forward_regime_china": forward_regime_china,
            "narrative": narrative,
        }

    # ══════════════════════════════════════════════════════════════
    # US Forecasting Methods
    # ══════════════════════════════════════════════════════════════

    def _forecast_nfp(self, data: dict) -> dict:
        """Forecast NFP using initial claims + JOLTS.

        Method:
        1. Initial claims 4-week avg: rising -> NFP weakening
        2. JOLTS openings trend: declining -> hiring slowing
        3. Recent NFP 3-month trend as baseline, adjusted by signals
        """
        result = {"indicator": "非农就业 (千人变化)", "confidence": "中"}

        nfp_df = data.get("nonfarm_payrolls")
        claims_df = data.get("initial_claims")
        jolts_df = data.get("jolts_openings")

        if nfp_df is None or nfp_df.empty:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": "无数据", "driver": "",
            }

        nfp_sorted = nfp_df.sort_values("date")
        values = pd.to_numeric(nfp_sorted["value"], errors="coerce").dropna()
        if len(values) < 4:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": "数据不足", "driver": "",
            }

        # Monthly change in NFP (in thousands)
        monthly_changes = values.diff().dropna()
        current_change = float(monthly_changes.iloc[-1])
        avg_3m = float(monthly_changes.tail(3).mean())

        # Baseline forecast: 3-month average
        forecast_change = avg_3m
        driver_parts = [f"3月均值{avg_3m:.0f}K"]

        # Adjust based on initial claims signal
        if claims_df is not None and not claims_df.empty:
            claims_vals = pd.to_numeric(
                claims_df.sort_values("date")["value"], errors="coerce"
            ).dropna()
            if len(claims_vals) >= 8:
                claims_recent = float(claims_vals.tail(4).mean())
                claims_prior = float(claims_vals.iloc[-8:-4].mean())
                if claims_recent > claims_prior * 1.10:
                    forecast_change *= 0.7
                    driver_parts.append("初请上升->下调30%")
                elif claims_recent < claims_prior * 0.95:
                    forecast_change *= 1.1
                    driver_parts.append("初请下降->上调10%")

        # Adjust based on JOLTS
        if jolts_df is not None and not jolts_df.empty:
            jolts_vals = pd.to_numeric(
                jolts_df.sort_values("date")["value"], errors="coerce"
            ).dropna()
            if len(jolts_vals) >= 3:
                jolts_trend = float(jolts_vals.iloc[-1]) - float(jolts_vals.iloc[-3])
                if jolts_trend < -200:
                    forecast_change *= 0.8
                    driver_parts.append("JOLTS下降->下调20%")

        direction = "增长" if forecast_change > 0 else "收缩"

        return {
            **result,
            "current": round(current_change, 0),
            "forecast": round(forecast_change, 0),
            "direction": direction,
            "change": round(forecast_change - current_change, 0),
            "method": "初请+JOLTS调整的3月均值",
            "driver": ", ".join(driver_parts),
        }

    def _forecast_unemployment(self, data: dict) -> dict:
        """Forecast unemployment rate using Sahm-style trend + mean reversion."""
        result = {"indicator": "失业率 (%)", "confidence": "中"}

        ue_df = data.get("unemployment")
        if ue_df is None or ue_df.empty:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": "无数据", "driver": "",
            }

        vals = pd.to_numeric(
            ue_df.sort_values("date")["value"], errors="coerce"
        ).dropna()
        if len(vals) < 6:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": "数据不足", "driver": "",
            }

        current = float(vals.iloc[-1])
        trend_3m = float(vals.tail(3).mean()) - float(vals.iloc[-6:-3].mean())

        # Mean reversion dampening
        forecast = current + trend_3m * 0.5
        forecast = max(3.0, min(15.0, forecast))

        direction = "上升" if forecast > current + 0.01 else (
            "下降" if forecast < current - 0.01 else "持平"
        )

        return {
            **result,
            "current": round(current, 3),
            "forecast": round(forecast, 3),
            "direction": direction,
            "change": round(forecast - current, 3),
            "confidence": "高" if abs(trend_3m) < 0.2 else "中",
            "method": "趋势外推+均值回归",
            "driver": f"近期趋势{trend_3m:+.2f}pp",
        }

    def _forecast_fed_rate(self, data: dict) -> dict:
        """Forecast Fed Funds Rate using Taylor Rule.

        Taylor Rule: r = r* + pi + 0.5*(pi - pi*) + 0.5*(y - y*)
        r* = 0.5 (neutral real rate), pi* = 2.0 (target)
        """
        result = {"indicator": "联邦基金利率 (%)", "confidence": "中"}

        fed_df = data.get("fed_funds_rate")
        pce_df = data.get("core_pce")
        ue_df = data.get("unemployment")

        if fed_df is None or fed_df.empty:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": "无数据", "driver": "",
            }

        current_rate = float(
            pd.to_numeric(
                fed_df.sort_values("date")["value"], errors="coerce"
            ).dropna().iloc[-1]
        )

        r_star = 0.5
        pi_star = 2.0
        pi = 2.5  # default core PCE
        output_gap = 0.0

        if pce_df is not None and not pce_df.empty:
            if "yoy_pct" in pce_df.columns:
                pce_yoy = pd.to_numeric(
                    pce_df.sort_values("date")["yoy_pct"], errors="coerce"
                ).dropna()
                if len(pce_yoy) > 0:
                    pi = float(pce_yoy.iloc[-1])

        if ue_df is not None and not ue_df.empty:
            ue_vals = pd.to_numeric(
                ue_df.sort_values("date")["value"], errors="coerce"
            ).dropna()
            if len(ue_vals) > 0:
                nairu = 4.0
                output_gap = -(float(ue_vals.iloc[-1]) - nairu) * 2  # Okun's law

        taylor_rate = r_star + pi + 0.5 * (pi - pi_star) + 0.5 * output_gap

        gap = taylor_rate - current_rate
        if gap < -0.5:
            forecast = current_rate - 0.25
            direction = "降息"
            driver = f"Taylor Rule ({taylor_rate:.1f}%) 低于当前 {gap:+.1f}%"
        elif gap > 0.5:
            forecast = current_rate + 0.25
            direction = "加息"
            driver = f"Taylor Rule ({taylor_rate:.1f}%) 高于当前 {gap:+.1f}%"
        else:
            forecast = current_rate
            direction = "暂停"
            driver = f"Taylor Rule ({taylor_rate:.1f}%) 接近当前"

        return {
            **result,
            "current": round(current_rate, 2),
            "forecast": round(forecast, 2),
            "direction": direction,
            "change": round(forecast - current_rate, 2),
            "confidence": "高" if abs(gap) > 1 else "中",
            "method": f"Taylor Rule (r*={r_star}, pi={pi:.1f}%, gap={output_gap:.1f})",
            "driver": driver,
        }

    def _forecast_consumer_sentiment(self, data: dict) -> dict:
        """Forecast consumer sentiment using gas prices + trend momentum.

        Gas prices are the #1 real-time predictor (inverse, ~-0.6 correlation).
        """
        result = {"indicator": "消费者信心指数", "confidence": "低"}

        cs_df = data.get("consumer_sentiment")
        gas_df = data.get("retail_gasoline")

        if cs_df is None or cs_df.empty:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": "无数据", "driver": "",
            }

        cs_vals = pd.to_numeric(
            cs_df.sort_values("date")["value"], errors="coerce"
        ).dropna()
        if len(cs_vals) < 1:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": "数据不足", "driver": "",
            }

        current = float(cs_vals.iloc[-1])

        # Gas price signal
        gas_impact = 0.0
        driver_parts = []
        if gas_df is not None and not gas_df.empty:
            gas_vals = pd.to_numeric(
                gas_df.sort_values("date")["value"], errors="coerce"
            ).dropna()
            if len(gas_vals) >= 4:
                gas_change_pct = (
                    float(gas_vals.iloc[-1]) / float(gas_vals.iloc[-4]) - 1
                ) * 100
                gas_impact = -gas_change_pct * 0.4
                if abs(gas_impact) > 1:
                    driver_parts.append(
                        f"汽油{gas_change_pct:+.0f}% -> 信心{gas_impact:+.1f}"
                    )

        # Trend momentum (dampened)
        trend_impact = 0.0
        if len(cs_vals) >= 3:
            trend = float(cs_vals.iloc[-1]) - float(cs_vals.iloc[-3])
            trend_impact = trend * 0.3
            driver_parts.append(f"趋势{trend:+.1f}")

        forecast = current + gas_impact + trend_impact
        forecast = max(20.0, min(120.0, forecast))
        direction = "上升" if forecast > current + 0.5 else (
            "下降" if forecast < current - 0.5 else "持平"
        )

        return {
            **result,
            "current": round(current, 1),
            "forecast": round(forecast, 1),
            "direction": direction,
            "change": round(forecast - current, 1),
            "method": "汽油价格传导 + 趋势",
            "driver": ", ".join(driver_parts) if driver_parts else "变化不大",
        }

    def _forecast_generic_trend(
        self, data: dict, key: str, name: str, col: str = "value", months: int = 3
    ) -> dict:
        """Generic weighted trend-based forecast for indicators without specific models."""
        result = {"indicator": name, "confidence": "低"}

        df = data.get(key)
        if df is None or df.empty:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": "无数据", "driver": "",
            }

        sorted_df = df.sort_values("date")
        if col not in sorted_df.columns:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": f"缺少{col}列", "driver": "",
            }

        vals = pd.to_numeric(sorted_df[col], errors="coerce").dropna()
        if len(vals) < months + 1:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": "数据不足", "driver": "",
            }

        current = float(vals.iloc[-1])

        # Weighted trend of last N months (recent months weighted higher)
        recent = vals.tail(months)
        weights = np.arange(1, len(recent) + 1, dtype=float)
        weighted_avg = float(np.average(recent, weights=weights))

        # Forecast: continue trend but dampened (mean reversion)
        trend = weighted_avg - float(recent.mean())
        forecast = current + trend

        direction = "上升" if forecast > current + 0.01 else (
            "下降" if forecast < current - 0.01 else "持平"
        )

        return {
            **result,
            "current": round(current, 4),
            "forecast": round(forecast, 4),
            "direction": direction,
            "change": round(forecast - current, 4),
            "method": f"加权{months}月趋势外推",
            "driver": f"近期趋势{direction}",
        }

    # ══════════════════════════════════════════════════════════════
    # China Forecasting Methods
    # ══════════════════════════════════════════════════════════════

    def _forecast_china_pmi(self, china_data: dict) -> dict:
        """Forecast China PMI using credit impulse lead + recent trend.

        Credit impulse leads PMI by 3-6 months.
        """
        result = {"indicator": "制造业 PMI", "confidence": "中"}

        pmi_df = china_data.get("pmi_manufacturing")
        credit_df = china_data.get("credit")

        if pmi_df is None or pmi_df.empty:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": "无数据", "driver": "",
            }

        pmi_vals = pd.to_numeric(
            pmi_df.sort_values("date")["value"], errors="coerce"
        ).dropna()
        if len(pmi_vals) < 1:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "method": "数据不足", "driver": "",
            }

        current = float(pmi_vals.iloc[-1])

        # Credit impulse signal
        credit_signal = 0.0
        driver_parts = []
        if credit_df is not None and not credit_df.empty:
            credit_vals = pd.to_numeric(
                credit_df.sort_values("date")["value"], errors="coerce"
            ).dropna()
            if len(credit_vals) >= 6:
                credit_3m_avg = float(credit_vals.tail(3).mean())
                credit_6m_avg = float(credit_vals.tail(6).mean())
                if credit_6m_avg > 0:
                    if credit_3m_avg > credit_6m_avg * 1.1:
                        credit_signal = 0.5
                        driver_parts.append("信贷加速->PMI上行")
                    elif credit_3m_avg < credit_6m_avg * 0.9:
                        credit_signal = -0.5
                        driver_parts.append("信贷减速->PMI下行")

        # Trend component
        trend_signal = 0.0
        if len(pmi_vals) >= 6:
            trend = float(pmi_vals.tail(3).mean()) - float(pmi_vals.iloc[-6:-3].mean())
            trend_signal = trend * 0.3
        elif len(pmi_vals) >= 3:
            trend = float(pmi_vals.iloc[-1]) - float(pmi_vals.iloc[-3])
            trend_signal = trend * 0.2

        forecast = current + credit_signal + trend_signal
        forecast = max(44.0, min(56.0, forecast))

        direction = "改善" if forecast > current + 0.1 else (
            "恶化" if forecast < current - 0.1 else "持平"
        )

        return {
            **result,
            "current": round(current, 1),
            "forecast": round(forecast, 1),
            "direction": direction,
            "change": round(forecast - current, 1),
            "confidence": "中",
            "method": "信贷脉冲领先(3-6月) + 趋势",
            "driver": ", ".join(driver_parts) if driver_parts else "变化不大",
        }

    # ══════════════════════════════════════════════════════════════
    # CPI Forecast Integration
    # ══════════════════════════════════════════════════════════════

    def _format_cpi_forecast(self, cpi_forecast: dict, us_data: dict) -> dict:
        """Format external CPI forecast into the standard forecast row."""
        result = {"indicator": "CPI YoY (%)", "confidence": "高"}

        if cpi_forecast is None or "error" in cpi_forecast:
            # Fall back to generic trend if no CPI forecast
            return self._forecast_generic_trend(
                us_data, "core_pce", "CPI YoY (%)", col="yoy_pct", months=3
            )

        headline_yoy_forecast = cpi_forecast.get("headline_yoy_forecast")
        if headline_yoy_forecast is None:
            return self._forecast_generic_trend(
                us_data, "core_pce", "CPI YoY (%)", col="yoy_pct", months=3
            )

        # Get current CPI YoY from the CPI forecast's base effect or data
        current_yoy = None
        # Try to extract from us_data (sticky_cpi or core_pce as proxy)
        for key in ["core_pce", "sticky_cpi"]:
            df = us_data.get(key)
            if df is not None and not df.empty and "yoy_pct" in df.columns:
                vals = pd.to_numeric(
                    df.sort_values("date")["yoy_pct"], errors="coerce"
                ).dropna()
                if len(vals) > 0:
                    current_yoy = float(vals.iloc[-1])
                    break

        forecast_val = round(headline_yoy_forecast, 3)
        change = round(forecast_val - current_yoy, 3) if current_yoy is not None else None

        direction = "N/A"
        if current_yoy is not None:
            direction = "上升" if forecast_val > current_yoy + 0.05 else (
                "下降" if forecast_val < current_yoy - 0.05 else "持平"
            )

        # Build driver string from key_drivers
        key_drivers = cpi_forecast.get("key_drivers", [])
        driver_str = "; ".join(key_drivers[:2]) if key_drivers else "自下而上分项预测"

        return {
            **result,
            "current": round(current_yoy, 3) if current_yoy is not None else None,
            "forecast": forecast_val,
            "direction": direction,
            "change": change,
            "method": "自下而上分项预测(含实时油价)",
            "driver": driver_str,
        }

    # ══════════════════════════════════════════════════════════════
    # Forward Regime Construction (KEY INNOVATION)
    # ══════════════════════════════════════════════════════════════

    def _build_forward_data_us(self, us_data: dict, us_forecasts: list) -> dict:
        """Build mock DataFrames with forecasted values for MacroRegime.assess_us().

        The regime engine uses _score_indicators which needs DataFrames with
        at least 12 rows (for Z-score). We take existing data and append
        the forecasted value as the newest row, so the Z-score history is
        preserved but the 'current' reading reflects our forecast.
        """
        forward_data = {}

        # Copy all existing data first
        for key, df in us_data.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                forward_data[key] = df.copy()

        # Mapping: forecast indicator name -> (data_key, column, forecast_field)
        forecast_map = {
            "CPI YoY (%)": [("core_pce", "yoy_pct"), ("sticky_cpi", "value")],
            "失业率 (%)": [("unemployment", "value")],  # inverse affects growth via claims
            "消费者信心指数": [("consumer_sentiment", "value")],
            "零售销售 YoY (%)": [("retail_sales", "yoy_pct")],
            "工业生产 YoY (%)": [("industrial_production", "yoy_pct")],
            "LEI 领先指标": [("lei", "value")],
        }

        for fc in us_forecasts:
            indicator = fc.get("indicator", "")
            forecast_val = fc.get("forecast")
            if forecast_val is None:
                continue

            targets = forecast_map.get(indicator, [])
            for data_key, col in targets:
                forward_data = self._inject_forecast_value(
                    forward_data, data_key, col, forecast_val
                )

        # Special handling: Fed rate forecast affects policy indicators
        fed_fc = next(
            (f for f in us_forecasts if f["indicator"] == "联邦基金利率 (%)"), None
        )
        if fed_fc and fed_fc.get("forecast") is not None:
            forward_data = self._inject_forecast_value(
                forward_data, "fed_funds_rate", "value", fed_fc["forecast"]
            )
            # Also update mom_pct for fed rate (regime uses mom_pct)
            if fed_fc.get("change") is not None:
                forward_data = self._inject_forecast_value(
                    forward_data, "fed_funds_rate", "mom_pct", fed_fc["change"]
                )

        # NFP forecast -> nonfarm_payrolls mom_pct
        nfp_fc = next(
            (f for f in us_forecasts if f["indicator"] == "非农就业 (千人变化)"), None
        )
        if nfp_fc and nfp_fc.get("forecast") is not None:
            # NFP mom_pct: approximate as percent change
            current_nfp = nfp_fc.get("current")
            if current_nfp and current_nfp != 0:
                mom_pct = (nfp_fc["forecast"] - current_nfp) / abs(current_nfp) * 100
            else:
                mom_pct = 0
            forward_data = self._inject_forecast_value(
                forward_data, "nonfarm_payrolls", "mom_pct", mom_pct
            )

        return forward_data

    def _build_forward_data_china(self, china_data: dict, china_forecasts: list) -> dict:
        """Build mock DataFrames with forecasted values for MacroRegime.assess_china()."""
        forward_data = {}

        for key, df in china_data.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                forward_data[key] = df.copy()

        forecast_map = {
            "制造业 PMI": [("pmi_manufacturing", "value")],
            "CPI YoY (%)": [("cpi", "yoy_pct")],
            "PPI YoY (%)": [("ppi", "yoy_pct")],
            "M2 YoY (%)": [("m2", "yoy_pct")],  # not directly used by regime but good to have
            "社会零售 YoY (%)": [("retail", "yoy_pct")],
        }

        for fc in china_forecasts:
            indicator = fc.get("indicator", "")
            forecast_val = fc.get("forecast")
            if forecast_val is None:
                continue

            targets = forecast_map.get(indicator, [])
            for data_key, col in targets:
                forward_data = self._inject_forecast_value(
                    forward_data, data_key, col, forecast_val
                )

        return forward_data

    @staticmethod
    def _inject_forecast_value(
        data: dict, key: str, col: str, value: float
    ) -> dict:
        """Append a forecasted value as the newest row in a DataFrame.

        Preserves the existing time series (needed for Z-score computation)
        while making the forecast the 'current' value that the regime
        engine will read.
        """
        df = data.get(key)
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            # Create a minimal DataFrame with enough rows for Z-score (>= 12)
            # Fill with the forecast value (Z-score will be ~0, which is fine)
            dates = pd.date_range(end=datetime.now(), periods=13, freq="MS")
            new_df = pd.DataFrame({"date": dates, col: [value] * 13})
            data[key] = new_df
            return data

        if col not in df.columns:
            df[col] = np.nan

        # Create a new row with the forecasted value
        sorted_df = df.sort_values("date").copy()
        last_date = pd.to_datetime(sorted_df["date"]).max()
        forecast_date = last_date + pd.DateOffset(months=1)

        new_row = {c: np.nan for c in sorted_df.columns}
        new_row["date"] = forecast_date
        new_row[col] = value

        # Append forecast row
        new_row_df = pd.DataFrame([new_row])
        updated_df = pd.concat([sorted_df, new_row_df], ignore_index=True)
        data[key] = updated_df

        return data

    # ══════════════════════════════════════════════════════════════
    # Narrative Generation
    # ══════════════════════════════════════════════════════════════

    def _build_narrative(
        self,
        us_forecasts: list,
        china_forecasts: list,
        forward_regime_us: dict,
        forward_regime_china: dict,
    ) -> str:
        """Generate a narrative summary of the macro outlook."""
        us_quad = forward_regime_us.get("quadrant_cn", "未知")
        cn_quad = forward_regime_china.get("quadrant_cn", "未知")
        us_growth = forward_regime_us.get("growth_score", 0)
        us_infl = forward_regime_us.get("inflation_score", 0)

        # Collect meaningful direction changes
        key_changes = []
        for f in us_forecasts + china_forecasts:
            if (
                f.get("change") is not None
                and f.get("direction") not in ("持平", "N/A", None)
                and abs(f.get("change", 0) or 0) > 0.01
            ):
                key_changes.append(f"{f['indicator']}预计{f['direction']}")

        narrative = (
            f"前瞻判断: 美国宏观环境预计处于【{us_quad}】象限"
            f"(增长得分{us_growth:+.2f}, 通胀得分{us_infl:+.2f}), "
            f"中国处于【{cn_quad}】象限。"
        )

        if key_changes:
            narrative += f" 核心变化: {'、'.join(key_changes[:5])}。"

        # Add risk framing
        us_assets = forward_regime_us.get("assets", "")
        if us_assets:
            narrative += f" 资产配置建议: {us_assets}。"

        return narrative

    # ══════════════════════════════════════════════════════════════
    # Utility
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _determine_forecast_date(us_data: dict, china_data: dict) -> datetime:
        """Find the latest data date and add 1 month for forecast target."""
        latest = None

        for data_dict in [us_data, china_data]:
            if not data_dict:
                continue
            for key, df in data_dict.items():
                if not isinstance(df, pd.DataFrame) or df.empty:
                    continue
                if "date" not in df.columns:
                    continue
                try:
                    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
                    if len(dates) > 0:
                        max_date = dates.max()
                        if latest is None or max_date > latest:
                            latest = max_date
                except Exception:
                    continue

        if latest is None:
            latest = pd.Timestamp(datetime.now())

        forecast_date = latest + pd.DateOffset(months=1)
        return forecast_date.to_pydatetime()
