import pandas as pd
import numpy as np


class ChinaCreditPulse:
    """中国信贷脉冲计算与分析"""

    def compute(self, china_data: dict) -> dict:
        """
        计算信贷脉冲。

        Uses "credit" indicator (新增人民币贷款) from china_data.
        Credit impulse = change in 12-month rolling sum vs 12 months ago,
        expressed as a percentage change of the rolling sum.

        Returns:
            "pulse_series": pd.DataFrame with date, pulse, pulse_pct columns
            "latest_pulse": float (pulse_pct)
            "signal": str (one of: "强刺激", "宽松", "温和", "收紧", "显著收缩")
            "color": "green"/"yellow"/"red"
            "m2_yoy": latest M2 YoY
            "m1_yoy": latest M1 YoY
            "m1_m2_gap": M1 - M2 YoY gap
            "m1_m2_signal": str
        """
        result = {}

        # ── Credit pulse calculation ──
        credit_df = china_data.get("credit")
        if credit_df is not None and not credit_df.empty:
            df = credit_df.copy()

            # Ensure date column exists and sort
            if "date" not in df.columns:
                result["pulse_series"] = pd.DataFrame()
                result["latest_pulse"] = 0.0
                result["signal"] = "数据缺失"
                result["color"] = "gray"
            else:
                df = df.sort_values("date").reset_index(drop=True)

                # Need at least 24 months for meaningful pulse
                if "value" in df.columns and len(df) >= 24:
                    values = df["value"].astype(float)

                    # Rolling 12-month sum of new credit
                    df["rolling_12m"] = values.rolling(12, min_periods=12).sum()

                    # Change vs 12 months ago (absolute)
                    df["pulse"] = df["rolling_12m"].diff(12)

                    # Percentage change of rolling sum vs 12 months ago
                    rolling_shift = df["rolling_12m"].shift(12)
                    df["pulse_pct"] = np.where(
                        rolling_shift != 0,
                        (df["rolling_12m"] / rolling_shift - 1) * 100,
                        np.nan,
                    )

                    pulse_df = df[["date", "pulse", "pulse_pct"]].dropna().copy()
                    result["pulse_series"] = pulse_df

                    if not pulse_df.empty:
                        latest = float(pulse_df.iloc[-1]["pulse_pct"])
                        result["latest_pulse"] = round(latest, 2)
                        result["signal"] = self._get_signal(latest)
                        result["color"] = self._get_color(latest)
                    else:
                        result["latest_pulse"] = 0.0
                        result["signal"] = "数据不足"
                        result["color"] = "gray"
                elif "value" in df.columns:
                    # Not enough data
                    result["pulse_series"] = pd.DataFrame()
                    result["latest_pulse"] = 0.0
                    result["signal"] = "数据不足（需24个月以上）"
                    result["color"] = "gray"
                else:
                    result["pulse_series"] = pd.DataFrame()
                    result["latest_pulse"] = 0.0
                    result["signal"] = "数据缺失"
                    result["color"] = "gray"

        # ── M1/M2 analysis ──
        m2_df = china_data.get("m2")
        m1_df = china_data.get("m1")

        if m2_df is not None and not m2_df.empty:
            m2_yoy = self._safe_latest_yoy(m2_df)
            if m2_yoy is not None:
                result["m2_yoy"] = round(m2_yoy, 2)

        if m1_df is not None and not m1_df.empty:
            m1_yoy = self._safe_latest_yoy(m1_df)
            if m1_yoy is not None:
                result["m1_yoy"] = round(m1_yoy, 2)

        if "m2_yoy" in result and "m1_yoy" in result:
            gap = result["m1_yoy"] - result["m2_yoy"]
            result["m1_m2_gap"] = round(gap, 2)
            if gap > 0:
                result["m1_m2_signal"] = "积极（企业活期增加）"
            else:
                result["m1_m2_signal"] = "谨慎（资金流入储蓄）"

        return result

    def _safe_latest_yoy(self, df: pd.DataFrame) -> float | None:
        """Safely extract the latest YoY percentage from a DataFrame."""
        if df is None or df.empty:
            return None

        # Try yoy_pct column first
        if "yoy_pct" in df.columns:
            valid = df.dropna(subset=["yoy_pct"])
            if not valid.empty:
                try:
                    return float(valid.iloc[-1]["yoy_pct"])
                except (ValueError, TypeError):
                    pass

        # Fallback: compute from value if we have 12+ months
        if "value" in df.columns and len(df) >= 13:
            sorted_df = df.sort_values("date") if "date" in df.columns else df
            try:
                current = float(sorted_df.iloc[-1]["value"])
                past = float(sorted_df.iloc[-13]["value"])
                if past != 0:
                    return (current / past - 1) * 100
            except (ValueError, TypeError, IndexError):
                pass

        return None

    def _get_signal(self, pulse_pct: float) -> str:
        """Map credit pulse percentage to a descriptive signal."""
        if pulse_pct > 15:
            return "强刺激"
        if pulse_pct > 5:
            return "宽松"
        if pulse_pct > 0:
            return "温和"
        if pulse_pct > -5:
            return "收紧"
        return "显著收缩"

    def _get_color(self, pulse_pct: float) -> str:
        """Map credit pulse percentage to a color."""
        if pulse_pct > 5:
            return "green"
        if pulse_pct > -5:
            return "yellow"
        return "red"
