"""宏观预测矩阵 — 回归驱动的前瞻性宏观预测引擎

核心创新：每个预测系数来自对系统内实际历史数据的OLS回归，
而非硬编码假设。当数据不足时，退回加权趋势并明确标注。

回归方法论：
- NFP: ΔNonfarm(t) = α + β₁×ΔInitialClaims(t-1) + β₂×ΔJOLTS(t-2)
- 失业率: UE(t) = α + β₁×Claims_4wAvg(t-1) + β₂×JOLTS_VU(t-2)
- 消费者信心: Sentiment(t) = α + β₁×GasPrice(t) + β₂×Unemployment(t)
- 联邦基金利率: Taylor Rule (r*, output gap 均从数据回归)
- 零售销售: RetailYoY(t) = α + β₁×Sentiment(t-1) + β₂×WageYoY(t-2)
- 中国PMI: PMI(t) = α + β₁×CreditImpulse(t-3) + β₂×PMI(t-1)
- 中国CPI: CPI_YoY(t) = α + β₁×PPI_YoY(t-2) + β₂×M2_YoY(t-6)
- CPI: 外部 CPIForecaster 自下而上分项预测

所有回归使用 np.linalg.lstsq，无 sklearn 依赖。
"""

import pandas as pd
import numpy as np
from datetime import datetime

from analysis.regime import MacroRegime


class MacroForecastMatrix:
    """回归驱动的宏观预测矩阵"""

    # Minimum observations for regression; below this, fall back to trend
    MIN_OBS_REGRESSION = 24
    # Minimum observations for trend fallback
    MIN_OBS_TREND = 6

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
        Forecast all key macro indicators using regression-based models.

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
        forecast_date_str = (
            forecast_date.strftime("%Y年%m月") if forecast_date else "未知"
        )

        # ── US Forecasts ──
        us_forecasts = []

        # 1. CPI (from external CPIForecaster if available)
        us_forecasts.append(self._format_cpi_forecast(cpi_forecast, us_data))

        # 2. NFP (regression: claims + JOLTS)
        us_forecasts.append(self._forecast_nfp(us_data))

        # 3. Unemployment (regression: claims + V/U ratio)
        us_forecasts.append(self._forecast_unemployment(us_data))

        # 4. Fed Funds Rate (data-driven Taylor Rule)
        us_forecasts.append(self._forecast_fed_rate(us_data))

        # 5. Consumer Sentiment (regression: gas + unemployment)
        us_forecasts.append(self._forecast_consumer_sentiment(us_data))

        # 6. Retail Sales YoY (regression: sentiment + wage growth)
        us_forecasts.append(self._forecast_retail_sales(us_data))

        # 7. Industrial Production YoY (trend fallback)
        us_forecasts.append(
            self._forecast_generic_trend(
                us_data, "industrial_production", "工业生产 YoY (%)",
                col="yoy_pct", months=3,
            )
        )

        # 8. LEI (trend fallback)
        us_forecasts.append(
            self._forecast_generic_trend(
                us_data, "lei", "LEI 领先指标", col="value", months=3,
            )
        )

        # ── China Forecasts ──
        china_forecasts = []

        # 1. PMI (regression: credit impulse + AR(1))
        china_forecasts.append(self._forecast_china_pmi(china_data))

        # 2. CPI YoY (regression: PPI lead + M2 lead)
        china_forecasts.append(self._forecast_china_cpi(china_data))

        # 3. PPI YoY (trend fallback)
        china_forecasts.append(
            self._forecast_generic_trend(
                china_data, "ppi", "PPI YoY (%)", col="yoy_pct", months=3,
            )
        )

        # 4. M2 YoY (trend fallback)
        china_forecasts.append(
            self._forecast_generic_trend(
                china_data, "m2", "M2 YoY (%)", col="yoy_pct", months=3,
            )
        )

        # 5. Retail YoY (trend fallback)
        china_forecasts.append(
            self._forecast_generic_trend(
                china_data, "retail", "社会零售 YoY (%)", col="yoy_pct", months=3,
            )
        )

        # ── Forward Regime (KEY INNOVATION) ──
        forward_us_data = self._build_forward_data_us(us_data, us_forecasts)
        forward_china_data = self._build_forward_data_china(
            china_data, china_forecasts
        )

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
    # Core Regression Engine
    # ══════════════════════════════════════════════════════════════

    def _fit_and_predict(
        self,
        y_df,
        x_dfs,
        y_col="value",
        x_cols=None,
        lag_months=0,
        name="",
    ) -> dict:
        """Core regression engine.

        1. Align y and x series by date (monthly)
        2. Apply lag to x variables (shift x back by lag_months)
        3. Run OLS regression: y = alpha + sum(beta_i * x_i) + epsilon
        4. Use latest x values to predict next y
        5. Report: coefficients, R-squared, prediction, confidence

        Args:
            y_df: DataFrame for the dependent variable (must have 'date' column)
            x_dfs: list of (DataFrame, col_name, display_name, lag_override)
                   where lag_override is per-variable lag (overrides lag_months
                   if not None). Each DataFrame must have 'date' column.
            y_col: column name in y_df to use as dependent variable
            x_cols: unused (kept for interface compat)
            lag_months: default lag in months for all x variables
            name: display name for the regression

        Returns:
            {
                "current": float,
                "forecast": float,
                "direction": str,
                "change": float,
                "confidence": "高"/"中"/"低"/"很低" based on R-squared,
                "r_squared": float,
                "coefficients": [{name, beta, t_stat}],
                "method": str describing the regression,
                "driver": str summarizing key factors,
            }
        """
        # ── 1. Extract and prepare y series ──
        if y_df is None or y_df.empty or y_col not in y_df.columns:
            return self._regression_fallback(name, None, "y变量无数据")

        y_series = y_df.sort_values("date").copy()
        y_series["_date_m"] = pd.to_datetime(
            y_series["date"], errors="coerce"
        ).dt.to_period("M")
        y_series["_y"] = pd.to_numeric(y_series[y_col], errors="coerce")
        y_series = y_series.dropna(subset=["_date_m", "_y"])
        # Keep last value per month
        y_series = y_series.drop_duplicates(subset=["_date_m"], keep="last")
        y_series = y_series.set_index("_date_m")["_y"]

        if len(y_series) < self.MIN_OBS_TREND:
            return self._regression_fallback(name, None, "y变量数据不足")

        current_y = float(y_series.iloc[-1])

        # ── 2. Extract and lag each x variable ──
        x_dict = {}  # {display_name: Series indexed by period}
        x_latest = {}  # {display_name: latest value for prediction}
        skipped = []

        for item in x_dfs:
            if len(item) == 4:
                x_df, x_col, x_name, x_lag = item
            else:
                x_df, x_col, x_name = item
                x_lag = lag_months

            if x_lag is None:
                x_lag = lag_months

            if x_df is None or x_df.empty:
                skipped.append(x_name)
                continue
            if x_col not in x_df.columns:
                skipped.append(f"{x_name}(缺少{x_col}列)")
                continue

            xs = x_df.sort_values("date").copy()
            xs["_date_m"] = pd.to_datetime(
                xs["date"], errors="coerce"
            ).dt.to_period("M")
            xs["_x"] = pd.to_numeric(xs[x_col], errors="coerce")
            xs = xs.dropna(subset=["_date_m", "_x"])
            xs = xs.drop_duplicates(subset=["_date_m"], keep="last")
            xs = xs.set_index("_date_m")["_x"]

            if len(xs) < self.MIN_OBS_TREND:
                skipped.append(f"{x_name}(数据不足)")
                continue

            # Store latest raw value for prediction (before shifting)
            x_latest[x_name] = float(xs.iloc[-1])

            # Shift x forward by lag months so x[t-lag] aligns with y[t]
            if x_lag > 0:
                xs.index = xs.index + x_lag
            x_dict[x_name] = xs

        if not x_dict:
            # No valid regressors -- fall back to trend
            return self._regression_fallback(
                name, current_y,
                f"所有x变量不可用: {', '.join(skipped) if skipped else '无x变量'}",
            )

        # ── 3. Merge y and all x on monthly period ──
        merged = pd.DataFrame({"y": y_series})
        for x_name, xs in x_dict.items():
            merged = merged.join(
                xs.rename(x_name), how="inner"
            )

        # Drop any rows with NaN
        merged = merged.dropna()
        n = len(merged)

        if n < self.MIN_OBS_REGRESSION:
            # Not enough aligned data for regression -- use trend
            return self._regression_fallback(
                name, current_y,
                f"对齐后仅{n}个观测值(需要{self.MIN_OBS_REGRESSION})",
                skipped=skipped,
            )

        # ── 4. Run OLS: y = alpha + beta_1*x_1 + ... + beta_k*x_k ──
        y_vec = merged["y"].values
        x_names = [c for c in merged.columns if c != "y"]
        X = np.column_stack([np.ones(n)] + [merged[c].values for c in x_names])

        try:
            result = np.linalg.lstsq(X, y_vec, rcond=None)
            betas = result[0]
        except np.linalg.LinAlgError:
            return self._regression_fallback(
                name, current_y, "OLS求解失败", skipped=skipped
            )

        # ── 5. Compute R-squared ──
        y_hat = X @ betas
        ss_res = float(np.sum((y_vec - y_hat) ** 2))
        ss_tot = float(np.sum((y_vec - np.mean(y_vec)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        r_squared = max(0.0, r_squared)  # Clamp

        # ── 6. Compute t-statistics ──
        dof = n - len(betas)
        if dof > 0 and ss_res > 0:
            mse = ss_res / dof
            try:
                XtX_inv = np.linalg.inv(X.T @ X)
                se_betas = np.sqrt(np.diag(XtX_inv) * mse)
                t_stats = betas / np.where(se_betas > 0, se_betas, 1.0)
            except np.linalg.LinAlgError:
                t_stats = np.zeros_like(betas)
        else:
            t_stats = np.zeros_like(betas)

        # ── 7. Predict using latest x values ──
        x_pred = [1.0]  # intercept
        for xn in x_names:
            x_pred.append(x_latest.get(xn, 0.0))
        x_pred = np.array(x_pred)
        forecast = float(x_pred @ betas)

        # ── 8. Build coefficient report ──
        coeff_list = [
            {"name": "截距(α)", "beta": round(float(betas[0]), 6),
             "t_stat": round(float(t_stats[0]), 2)}
        ]
        for i, xn in enumerate(x_names):
            coeff_list.append({
                "name": xn,
                "beta": round(float(betas[i + 1]), 6),
                "t_stat": round(float(t_stats[i + 1]), 2),
            })

        # ── 9. Confidence level ──
        if r_squared < 0.1:
            confidence = "很低"
        elif r_squared < 0.3:
            confidence = "低"
        elif r_squared < 0.5:
            confidence = "中"
        else:
            confidence = "高"

        # ── 10. Direction ──
        change = forecast - current_y
        direction = "上升" if change > 0.01 else ("下降" if change < -0.01 else "持平")

        # ── 11. Identify primary driver ──
        # The x variable with largest |beta * latest_x| contribution
        contributions = []
        for i, xn in enumerate(x_names):
            contrib = abs(float(betas[i + 1]) * x_latest.get(xn, 0.0))
            contributions.append((xn, contrib, float(betas[i + 1])))
        contributions.sort(key=lambda t: t[1], reverse=True)

        if contributions:
            top_name, _, top_beta = contributions[0]
            driver = f"主驱动: {top_name} (β={top_beta:.4f})"
        else:
            driver = "无驱动因子"

        # Build method string
        eq_parts = " + ".join(
            f"β{i + 1}×{xn}" for i, xn in enumerate(x_names)
        )
        method = f"OLS回归: y = α + {eq_parts} (R²={r_squared:.3f}, n={n})"

        if skipped:
            method += f" [跳过: {', '.join(skipped)}]"

        return {
            "current": round(current_y, 4),
            "forecast": round(forecast, 4),
            "direction": direction,
            "change": round(change, 4),
            "confidence": confidence,
            "r_squared": round(r_squared, 4),
            "coefficients": coeff_list,
            "method": method,
            "driver": driver,
        }

    def _regression_fallback(
        self, name, current, reason, skipped=None
    ) -> dict:
        """Return a trend-based fallback when regression is not possible."""
        method = f"加权趋势外推 (回归退回原因: {reason})"
        if skipped:
            method += f" [跳过: {', '.join(skipped)}]"

        return {
            "current": current,
            "forecast": current,
            "direction": "持平",
            "change": 0.0,
            "confidence": "很低",
            "r_squared": None,
            "coefficients": [],
            "method": method,
            "driver": f"退回趋势: {reason}",
        }

    # ══════════════════════════════════════════════════════════════
    # US Forecasting Methods (Regression-Based)
    # ══════════════════════════════════════════════════════════════

    def _forecast_nfp(self, data: dict) -> dict:
        """Forecast NFP monthly change via regression.

        ΔNonfarm(t) = α + β₁×InitialClaims(t-1) + β₂×JOLTS(t-2) + ε

        InitialClaims is expected to have a negative coefficient
        (rising claims → lower NFP growth).
        """
        nfp_df = data.get("nonfarm_payrolls")

        if nfp_df is None or nfp_df.empty:
            return {
                "indicator": "非农就业 (千人变化)",
                "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "confidence": "低", "r_squared": None,
                "coefficients": [],
                "method": "无数据", "driver": "",
            }

        # Compute monthly change (diff) as our y variable
        nfp_sorted = nfp_df.sort_values("date").copy()
        nfp_sorted["value"] = pd.to_numeric(
            nfp_sorted["value"], errors="coerce"
        )
        nfp_sorted["nfp_change"] = nfp_sorted["value"].diff()
        nfp_diff = nfp_sorted.dropna(subset=["nfp_change"]).copy()

        claims_df = data.get("initial_claims")
        jolts_df = data.get("jolts_openings")

        x_dfs = []
        if claims_df is not None and not claims_df.empty:
            x_dfs.append((claims_df, "value", "初请失业金", 1))
        if jolts_df is not None and not jolts_df.empty:
            x_dfs.append((jolts_df, "value", "JOLTS职位空缺", 2))

        result = self._fit_and_predict(
            y_df=nfp_diff,
            x_dfs=x_dfs,
            y_col="nfp_change",
            name="NFP月度变化",
        )

        # If regression failed, try simple 3-month average fallback
        if result["forecast"] is None or result["r_squared"] is None:
            vals = pd.to_numeric(
                nfp_sorted["value"], errors="coerce"
            ).dropna()
            if len(vals) >= 4:
                changes = vals.diff().dropna()
                current_change = float(changes.iloc[-1])
                avg_3m = float(changes.tail(3).mean())
                result = {
                    "current": round(current_change, 0),
                    "forecast": round(avg_3m, 0),
                    "direction": "增长" if avg_3m > 0 else "收缩",
                    "change": round(avg_3m - current_change, 0),
                    "confidence": "低",
                    "r_squared": None,
                    "coefficients": [],
                    "method": "3月均值外推 (回归数据不足)",
                    "driver": f"3月均值: {avg_3m:.0f}K",
                }

        result["indicator"] = "非农就业 (千人变化)"
        return result

    def _forecast_unemployment(self, data: dict) -> dict:
        """Forecast unemployment rate via regression.

        Unemployment(t) = α + β₁×InitialClaims_4wAvg(t-1)
                            + β₂×JOLTS_VU_Ratio(t-2) + ε
        """
        ue_df = data.get("unemployment")

        if ue_df is None or ue_df.empty:
            return {
                "indicator": "失业率 (%)",
                "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "confidence": "低", "r_squared": None,
                "coefficients": [],
                "method": "无数据", "driver": "",
            }

        claims_df = data.get("initial_claims")
        jolts_df = data.get("jolts_openings")

        # Build JOLTS V/U ratio if possible
        vu_df = None
        if jolts_df is not None and not jolts_df.empty and ue_df is not None:
            try:
                j_sorted = jolts_df.sort_values("date").copy()
                j_sorted["_date_m"] = pd.to_datetime(
                    j_sorted["date"], errors="coerce"
                ).dt.to_period("M")
                j_sorted["_j"] = pd.to_numeric(
                    j_sorted["value"], errors="coerce"
                )
                j_sorted = j_sorted.dropna(subset=["_date_m", "_j"])
                j_sorted = j_sorted.drop_duplicates(
                    subset=["_date_m"], keep="last"
                )

                u_sorted = ue_df.sort_values("date").copy()
                u_sorted["_date_m"] = pd.to_datetime(
                    u_sorted["date"], errors="coerce"
                ).dt.to_period("M")
                u_sorted["_u"] = pd.to_numeric(
                    u_sorted["value"], errors="coerce"
                )
                u_sorted = u_sorted.dropna(subset=["_date_m", "_u"])
                u_sorted = u_sorted.drop_duplicates(
                    subset=["_date_m"], keep="last"
                )

                merged = j_sorted[["_date_m", "_j"]].merge(
                    u_sorted[["_date_m", "_u"]], on="_date_m"
                )
                # V/U ratio: vacancies / unemployment rate
                # (higher ratio = tighter labor market = lower unemployment ahead)
                merged["vu_ratio"] = merged["_j"] / merged["_u"].replace(0, np.nan)
                merged = merged.dropna(subset=["vu_ratio"])

                if len(merged) >= self.MIN_OBS_TREND:
                    vu_df = pd.DataFrame({
                        "date": merged["_date_m"].apply(
                            lambda p: p.to_timestamp()
                        ),
                        "value": merged["vu_ratio"].values,
                    })
            except Exception:
                vu_df = None

        x_dfs = []
        if claims_df is not None and not claims_df.empty:
            x_dfs.append((claims_df, "value", "初请失业金(4周)", 1))
        if vu_df is not None and not vu_df.empty:
            x_dfs.append((vu_df, "value", "JOLTS V/U比率", 2))

        result = self._fit_and_predict(
            y_df=ue_df,
            x_dfs=x_dfs,
            y_col="value",
            name="失业率",
        )

        # Clamp forecast to reasonable range
        if result["forecast"] is not None:
            result["forecast"] = round(
                max(3.0, min(15.0, result["forecast"])), 3
            )
            result["change"] = round(
                result["forecast"] - (result["current"] or 0), 3
            )

        result["indicator"] = "失业率 (%)"
        return result

    def _forecast_fed_rate(self, data: dict) -> dict:
        """Forecast Fed Funds Rate using data-driven Taylor Rule.

        TaylorRate = r* + π + 0.5×(π - 2.0) + 0.5×OutputGap

        where:
          r* = average(fed_funds - core_pce_yoy) over last 10 years
          π = latest core PCE YoY
          OutputGap = -(unemployment - NAIRU) × OkunCoeff
          NAIRU = min unemployment in last 5 years (approximate)
          OkunCoeff = regressed from GDP gap vs unemployment gap (or default 2.0)
        """
        result = {"indicator": "联邦基金利率 (%)", "confidence": "中"}

        fed_df = data.get("fed_funds_rate")
        pce_df = data.get("core_pce")
        ue_df = data.get("unemployment")
        gdp_df = data.get("gdp")

        if fed_df is None or fed_df.empty:
            return {
                **result, "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "r_squared": None, "coefficients": [],
                "method": "无数据", "driver": "",
            }

        fed_sorted = fed_df.sort_values("date")
        fed_vals = pd.to_numeric(
            fed_sorted["value"], errors="coerce"
        ).dropna()
        current_rate = float(fed_vals.iloc[-1])

        # ── Compute r* from actual data (avg real rate over last 10 years) ──
        r_star = 0.5  # default
        pi = 2.5  # default core PCE

        if pce_df is not None and not pce_df.empty and "yoy_pct" in pce_df.columns:
            pce_sorted = pce_df.sort_values("date").copy()
            pce_sorted["_date_m"] = pd.to_datetime(
                pce_sorted["date"], errors="coerce"
            ).dt.to_period("M")
            pce_sorted["_pce"] = pd.to_numeric(
                pce_sorted["yoy_pct"], errors="coerce"
            )
            pce_sorted = pce_sorted.dropna(subset=["_date_m", "_pce"])
            pce_sorted = pce_sorted.drop_duplicates(
                subset=["_date_m"], keep="last"
            ).set_index("_date_m")

            if len(pce_sorted) > 0:
                pi = float(pce_sorted["_pce"].iloc[-1])

            # Align fed rate and PCE to compute real rate
            fed_m = fed_sorted.copy()
            fed_m["_date_m"] = pd.to_datetime(
                fed_m["date"], errors="coerce"
            ).dt.to_period("M")
            fed_m["_fed"] = pd.to_numeric(fed_m["value"], errors="coerce")
            fed_m = fed_m.dropna(subset=["_date_m", "_fed"])
            fed_m = fed_m.drop_duplicates(
                subset=["_date_m"], keep="last"
            ).set_index("_date_m")

            # Last 10 years (120 months)
            common_idx = fed_m.index.intersection(pce_sorted.index)
            if len(common_idx) >= 24:
                common_idx = common_idx.sort_values()
                recent_idx = common_idx[-120:]  # up to 10 years
                real_rates = (
                    fed_m.loc[recent_idx, "_fed"].values
                    - pce_sorted.loc[recent_idx, "_pce"].values
                )
                r_star = float(np.mean(real_rates))

        # ── Compute NAIRU (min unemployment in last 5 years) ──
        nairu = 4.0  # default
        output_gap = 0.0
        okun_coeff = 2.0  # default Okun's coefficient

        if ue_df is not None and not ue_df.empty:
            ue_vals = pd.to_numeric(
                ue_df.sort_values("date")["value"], errors="coerce"
            ).dropna()
            if len(ue_vals) > 0:
                current_ue = float(ue_vals.iloc[-1])
                # NAIRU ~ min UE in last 5 years (60 months)
                nairu = float(ue_vals.tail(60).min())

                # Try to regress Okun's coefficient from GDP data
                if gdp_df is not None and not gdp_df.empty and "yoy_pct" in gdp_df.columns:
                    try:
                        okun_coeff = self._estimate_okun_coefficient(
                            ue_df, gdp_df
                        )
                    except Exception:
                        okun_coeff = 2.0

                output_gap = -(current_ue - nairu) * okun_coeff

        # ── Taylor Rule ──
        pi_star = 2.0
        taylor_rate = r_star + pi + 0.5 * (pi - pi_star) + 0.5 * output_gap

        gap = taylor_rate - current_rate
        if gap < -0.5:
            forecast = current_rate - 0.25
            direction = "降息"
            driver = (
                f"Taylor ({taylor_rate:.2f}%) < 当前 ({current_rate:.2f}%), "
                f"差距{gap:+.2f}%"
            )
        elif gap > 0.5:
            forecast = current_rate + 0.25
            direction = "加息"
            driver = (
                f"Taylor ({taylor_rate:.2f}%) > 当前 ({current_rate:.2f}%), "
                f"差距{gap:+.2f}%"
            )
        else:
            forecast = current_rate
            direction = "暂停"
            driver = (
                f"Taylor ({taylor_rate:.2f}%) ≈ 当前 ({current_rate:.2f}%)"
            )

        # Build coefficients for transparency
        coefficients = [
            {"name": "r*(实际中性利率)", "beta": round(r_star, 4), "t_stat": None},
            {"name": "π(核心PCE YoY)", "beta": round(pi, 4), "t_stat": None},
            {"name": "NAIRU", "beta": round(nairu, 4), "t_stat": None},
            {"name": "Okun系数", "beta": round(okun_coeff, 4), "t_stat": None},
            {"name": "产出缺口", "beta": round(output_gap, 4), "t_stat": None},
        ]

        return {
            **result,
            "current": round(current_rate, 2),
            "forecast": round(forecast, 2),
            "direction": direction,
            "change": round(forecast - current_rate, 2),
            "confidence": "高" if abs(gap) > 1 else "中",
            "r_squared": None,  # Taylor Rule is structural, not fitted
            "coefficients": coefficients,
            "method": (
                f"数据驱动Taylor Rule: "
                f"r*={r_star:.2f}(10年均值), π={pi:.2f}%, "
                f"NAIRU={nairu:.2f}%(5年最低UE), Okun={okun_coeff:.2f}, "
                f"OutputGap={output_gap:.2f}"
            ),
            "driver": driver,
        }

    def _estimate_okun_coefficient(self, ue_df, gdp_df) -> float:
        """Estimate Okun's coefficient by regressing GDP gap on UE gap.

        ΔGDP_gap ≈ -Okun × ΔUE
        Returns the Okun coefficient (positive number, typically 1.5-3.0).
        """
        ue_sorted = ue_df.sort_values("date").copy()
        ue_sorted["_date_m"] = pd.to_datetime(
            ue_sorted["date"], errors="coerce"
        ).dt.to_period("M")
        ue_sorted["_ue"] = pd.to_numeric(
            ue_sorted["value"], errors="coerce"
        )
        ue_sorted = ue_sorted.dropna(subset=["_date_m", "_ue"])
        ue_sorted = ue_sorted.drop_duplicates(
            subset=["_date_m"], keep="last"
        ).set_index("_date_m")

        gdp_sorted = gdp_df.sort_values("date").copy()
        # GDP is quarterly; convert to monthly period for matching
        gdp_sorted["_date_m"] = pd.to_datetime(
            gdp_sorted["date"], errors="coerce"
        ).dt.to_period("M")
        gdp_sorted["_gdp"] = pd.to_numeric(
            gdp_sorted["yoy_pct"], errors="coerce"
        )
        gdp_sorted = gdp_sorted.dropna(subset=["_date_m", "_gdp"])
        gdp_sorted = gdp_sorted.drop_duplicates(
            subset=["_date_m"], keep="last"
        ).set_index("_date_m")

        common = ue_sorted.index.intersection(gdp_sorted.index)
        if len(common) < 12:
            return 2.0  # default

        common = common.sort_values()
        ue_vals = ue_sorted.loc[common, "_ue"].values
        gdp_vals = gdp_sorted.loc[common, "_gdp"].values

        # Compute changes
        d_ue = np.diff(ue_vals)
        d_gdp = np.diff(gdp_vals)

        if len(d_ue) < 8:
            return 2.0

        # Regress: d_gdp = alpha + beta * d_ue
        X = np.column_stack([np.ones(len(d_ue)), d_ue])
        try:
            betas = np.linalg.lstsq(X, d_gdp, rcond=None)[0]
            # Okun's coefficient is -beta (negative relationship)
            okun = -float(betas[1])
            # Clamp to reasonable range
            return max(0.5, min(4.0, okun))
        except np.linalg.LinAlgError:
            return 2.0

    def _forecast_consumer_sentiment(self, data: dict) -> dict:
        """Forecast consumer sentiment via regression.

        Sentiment(t) = α + β₁×GasolinePrice(t) + β₂×Unemployment(t) + ε

        Gas prices should have a strong negative coefficient.
        """
        cs_df = data.get("consumer_sentiment")

        if cs_df is None or cs_df.empty:
            return {
                "indicator": "消费者信心指数",
                "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "confidence": "低", "r_squared": None,
                "coefficients": [],
                "method": "无数据", "driver": "",
            }

        gas_df = data.get("retail_gasoline")
        ue_df = data.get("unemployment")

        x_dfs = []
        if gas_df is not None and not gas_df.empty:
            x_dfs.append((gas_df, "value", "汽油零售价", 0))
        if ue_df is not None and not ue_df.empty:
            x_dfs.append((ue_df, "value", "失业率", 0))

        result = self._fit_and_predict(
            y_df=cs_df,
            x_dfs=x_dfs,
            y_col="value",
            name="消费者信心",
        )

        # Clamp to reasonable range
        if result["forecast"] is not None:
            result["forecast"] = round(
                max(20.0, min(120.0, result["forecast"])), 1
            )
            current = result["current"] or 0
            result["change"] = round(result["forecast"] - current, 1)
            result["direction"] = (
                "上升" if result["forecast"] > current + 0.5
                else ("下降" if result["forecast"] < current - 0.5 else "持平")
            )

        result["indicator"] = "消费者信心指数"
        return result

    def _forecast_retail_sales(self, data: dict) -> dict:
        """Forecast retail sales YoY via regression.

        RetailSales_YoY(t) = α + β₁×ConsumerSentiment(t-1)
                               + β₂×WageGrowth_YoY(t-2) + ε
        """
        retail_df = data.get("retail_sales")

        if retail_df is None or retail_df.empty:
            return {
                "indicator": "零售销售 YoY (%)",
                "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "confidence": "低", "r_squared": None,
                "coefficients": [],
                "method": "无数据", "driver": "",
            }

        cs_df = data.get("consumer_sentiment")
        wage_df = data.get("avg_hourly_earnings")

        x_dfs = []
        if cs_df is not None and not cs_df.empty:
            x_dfs.append((cs_df, "value", "消费者信心", 1))
        if wage_df is not None and not wage_df.empty and "yoy_pct" in wage_df.columns:
            x_dfs.append((wage_df, "yoy_pct", "工资增速YoY", 2))

        result = self._fit_and_predict(
            y_df=retail_df,
            x_dfs=x_dfs,
            y_col="yoy_pct",
            name="零售销售YoY",
        )

        result["indicator"] = "零售销售 YoY (%)"
        return result

    # ══════════════════════════════════════════════════════════════
    # China Forecasting Methods (Regression-Based)
    # ══════════════════════════════════════════════════════════════

    def _forecast_china_pmi(self, china_data: dict) -> dict:
        """Forecast China PMI via regression.

        PMI(t) = α + β₁×CreditImpulse(t-3) + β₂×PMI(t-1) + ε

        Credit impulse = new loans rolling 12m YoY change.
        AR(1) component captures PMI's own momentum.
        """
        pmi_df = china_data.get("pmi_manufacturing")

        if pmi_df is None or pmi_df.empty:
            return {
                "indicator": "制造业 PMI",
                "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "confidence": "低", "r_squared": None,
                "coefficients": [],
                "method": "无数据", "driver": "",
            }

        credit_df = china_data.get("credit")

        # Build credit impulse (rolling 12m sum YoY change)
        credit_impulse_df = None
        if credit_df is not None and not credit_df.empty:
            try:
                c_sorted = credit_df.sort_values("date").copy()
                c_sorted["value"] = pd.to_numeric(
                    c_sorted["value"], errors="coerce"
                )
                c_sorted = c_sorted.dropna(subset=["value"])
                c_sorted["date"] = pd.to_datetime(
                    c_sorted["date"], errors="coerce"
                )
                c_sorted = c_sorted.set_index("date").sort_index()

                # Rolling 12-month sum
                c_sorted["rolling_12m"] = c_sorted["value"].rolling(
                    12, min_periods=12
                ).sum()
                # YoY change of rolling 12m sum
                c_sorted["credit_impulse"] = c_sorted["rolling_12m"].pct_change(12) * 100
                c_sorted = c_sorted.dropna(subset=["credit_impulse"])

                if len(c_sorted) >= self.MIN_OBS_TREND:
                    credit_impulse_df = c_sorted.reset_index()[
                        ["date", "credit_impulse"]
                    ].rename(columns={"credit_impulse": "value"})
            except Exception:
                credit_impulse_df = None

        # Build PMI lagged 1 month (AR component)
        pmi_lag_df = None
        try:
            pmi_sorted = pmi_df.sort_values("date").copy()
            pmi_sorted["date"] = pd.to_datetime(
                pmi_sorted["date"], errors="coerce"
            )
            pmi_sorted["value"] = pd.to_numeric(
                pmi_sorted["value"], errors="coerce"
            )
            pmi_sorted = pmi_sorted.dropna(subset=["date", "value"])

            if len(pmi_sorted) >= self.MIN_OBS_TREND:
                # Create lagged version: shift value forward by 1 month
                # so PMI(t-1) aligns with PMI(t)
                pmi_lag = pmi_sorted.copy()
                pmi_lag_df = pmi_lag  # lag handled by _fit_and_predict
        except Exception:
            pmi_lag_df = None

        x_dfs = []
        if credit_impulse_df is not None and not credit_impulse_df.empty:
            x_dfs.append((credit_impulse_df, "value", "信贷脉冲(12mYoY)", 3))
        if pmi_lag_df is not None and not pmi_lag_df.empty:
            x_dfs.append((pmi_lag_df, "value", "PMI滞后1月(AR)", 1))

        result = self._fit_and_predict(
            y_df=pmi_df,
            x_dfs=x_dfs,
            y_col="value",
            name="制造业PMI",
        )

        # Clamp PMI to reasonable range
        if result["forecast"] is not None:
            result["forecast"] = round(
                max(44.0, min(56.0, result["forecast"])), 1
            )
            current = result["current"] or 50.0
            result["change"] = round(result["forecast"] - current, 1)
            result["direction"] = (
                "改善" if result["forecast"] > current + 0.1
                else ("恶化" if result["forecast"] < current - 0.1 else "持平")
            )

        result["indicator"] = "制造业 PMI"
        return result

    def _forecast_china_cpi(self, china_data: dict) -> dict:
        """Forecast China CPI YoY via regression.

        CPI_YoY(t) = α + β₁×PPI_YoY(t-2) + β₂×M2_YoY(t-6) + ε

        PPI leads CPI by ~2 months (cost-push transmission).
        M2 leads CPI by ~6 months (monetary transmission).
        """
        cpi_df = china_data.get("cpi")

        if cpi_df is None or cpi_df.empty:
            return {
                "indicator": "CPI YoY (%)",
                "current": None, "forecast": None,
                "direction": "N/A", "change": None,
                "confidence": "低", "r_squared": None,
                "coefficients": [],
                "method": "无数据", "driver": "",
            }

        ppi_df = china_data.get("ppi")
        m2_df = china_data.get("m2")

        x_dfs = []
        if ppi_df is not None and not ppi_df.empty and "yoy_pct" in ppi_df.columns:
            x_dfs.append((ppi_df, "yoy_pct", "PPI YoY(领先2月)", 2))
        if m2_df is not None and not m2_df.empty and "yoy_pct" in m2_df.columns:
            x_dfs.append((m2_df, "yoy_pct", "M2 YoY(领先6月)", 6))

        result = self._fit_and_predict(
            y_df=cpi_df,
            x_dfs=x_dfs,
            y_col="yoy_pct",
            name="中国CPI YoY",
        )

        result["indicator"] = "CPI YoY (%)"
        return result

    # ══════════════════════════════════════════════════════════════
    # Generic Trend Fallback
    # ══════════════════════════════════════════════════════════════

    def _forecast_generic_trend(
        self, data: dict, key: str, name: str, col: str = "value", months: int = 3
    ) -> dict:
        """Generic weighted trend-based forecast for indicators without
        specific regression models. Used as fallback."""
        result = {
            "indicator": name,
            "confidence": "低",
            "r_squared": None,
            "coefficients": [],
        }

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
            "method": f"加权{months}月趋势外推 (无回归模型)",
            "driver": f"近期趋势{direction}",
        }

    # ══════════════════════════════════════════════════════════════
    # CPI Forecast Integration
    # ══════════════════════════════════════════════════════════════

    def _format_cpi_forecast(self, cpi_forecast: dict, us_data: dict) -> dict:
        """Format external CPI forecast into the standard forecast row."""
        result = {
            "indicator": "CPI YoY (%)",
            "confidence": "高",
            "r_squared": None,
            "coefficients": [],
        }

        if cpi_forecast is None or "error" in cpi_forecast:
            return self._forecast_generic_trend(
                us_data, "core_pce", "CPI YoY (%)", col="yoy_pct", months=3
            )

        headline_yoy_forecast = cpi_forecast.get("headline_yoy_forecast")
        if headline_yoy_forecast is None:
            return self._forecast_generic_trend(
                us_data, "core_pce", "CPI YoY (%)", col="yoy_pct", months=3
            )

        # Get current CPI YoY from data
        current_yoy = None
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
        change = (
            round(forecast_val - current_yoy, 3)
            if current_yoy is not None else None
        )

        direction = "N/A"
        if current_yoy is not None:
            direction = "上升" if forecast_val > current_yoy + 0.05 else (
                "下降" if forecast_val < current_yoy - 0.05 else "持平"
            )

        key_drivers = cpi_forecast.get("key_drivers", [])
        driver_str = (
            "; ".join(key_drivers[:2]) if key_drivers else "自下而上分项预测"
        )

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

        # Mapping: forecast indicator name -> (data_key, column)
        forecast_map = {
            "CPI YoY (%)": [("core_pce", "yoy_pct"), ("sticky_cpi", "value")],
            "失业率 (%)": [("unemployment", "value")],
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

        # Special handling: Fed rate
        fed_fc = next(
            (f for f in us_forecasts if f["indicator"] == "联邦基金利率 (%)"),
            None,
        )
        if fed_fc and fed_fc.get("forecast") is not None:
            forward_data = self._inject_forecast_value(
                forward_data, "fed_funds_rate", "value", fed_fc["forecast"]
            )
            if fed_fc.get("change") is not None:
                forward_data = self._inject_forecast_value(
                    forward_data, "fed_funds_rate", "mom_pct", fed_fc["change"]
                )

        # NFP forecast -> nonfarm_payrolls mom_pct
        nfp_fc = next(
            (f for f in us_forecasts
             if f["indicator"] == "非农就业 (千人变化)"),
            None,
        )
        if nfp_fc and nfp_fc.get("forecast") is not None:
            current_nfp = nfp_fc.get("current")
            if current_nfp and current_nfp != 0:
                mom_pct = (
                    (nfp_fc["forecast"] - current_nfp) / abs(current_nfp) * 100
                )
            else:
                mom_pct = 0
            forward_data = self._inject_forecast_value(
                forward_data, "nonfarm_payrolls", "mom_pct", mom_pct
            )

        return forward_data

    def _build_forward_data_china(
        self, china_data: dict, china_forecasts: list
    ) -> dict:
        """Build mock DataFrames with forecasted values for
        MacroRegime.assess_china()."""
        forward_data = {}

        for key, df in china_data.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                forward_data[key] = df.copy()

        forecast_map = {
            "制造业 PMI": [("pmi_manufacturing", "value")],
            "CPI YoY (%)": [("cpi", "yoy_pct")],
            "PPI YoY (%)": [("ppi", "yoy_pct")],
            "M2 YoY (%)": [("m2", "yoy_pct")],
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
            dates = pd.date_range(end=datetime.now(), periods=13, freq="MS")
            new_df = pd.DataFrame({"date": dates, col: [value] * 13})
            data[key] = new_df
            return data

        if col not in df.columns:
            df[col] = np.nan

        sorted_df = df.sort_values("date").copy()
        last_date = pd.to_datetime(sorted_df["date"]).max()
        forecast_date = last_date + pd.DateOffset(months=1)

        new_row = {c: np.nan for c in sorted_df.columns}
        new_row["date"] = forecast_date
        new_row[col] = value

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

        # Regression quality summary
        regression_forecasts = [
            f for f in us_forecasts + china_forecasts
            if f.get("r_squared") is not None
        ]
        if regression_forecasts:
            avg_r2 = np.mean([f["r_squared"] for f in regression_forecasts])
            high_r2 = [
                f["indicator"] for f in regression_forecasts
                if f["r_squared"] >= 0.5
            ]
            low_r2 = [
                f["indicator"] for f in regression_forecasts
                if f["r_squared"] < 0.3
            ]
            narrative += (
                f" 回归质量: 平均R²={avg_r2:.3f}"
            )
            if high_r2:
                narrative += f", 高置信: {'、'.join(high_r2)}"
            if low_r2:
                narrative += f", 低置信: {'、'.join(low_r2)}"
            narrative += "。"

        # Asset allocation
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
                    dates = pd.to_datetime(
                        df["date"], errors="coerce"
                    ).dropna()
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
