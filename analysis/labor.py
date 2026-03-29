import pandas as pd
import numpy as np

from analysis.utils import safe_latest


class LaborDashboard:
    """就业市场深度分析仪表盘"""

    def _safe_latest(self, df: pd.DataFrame | None, col: str) -> float | None:
        """Safely extract the latest value for a given column."""
        return safe_latest(df, col)

    def _safe_series(self, df: pd.DataFrame | None, col: str) -> pd.Series | None:
        """Return a clean Series for the given column, sorted by date."""
        if df is None or df.empty:
            return None
        if col not in df.columns:
            return None
        clean = df.dropna(subset=[col]).sort_values("date")
        if clean.empty:
            return None
        return clean[col].astype(float)

    def assess(self, data: dict) -> dict:
        """
        Comprehensive labor market assessment.

        Args:
            data: combined dict with FRED data keys:
                unemployment, nonfarm_payrolls, initial_claims,
                jolts_openings, jolts_quits, u6_rate,
                prime_age_lfpr, labor_participation,
                avg_hourly_earnings, unemployed_count

        Returns dict with assessment sections and a unified signals list.
        """
        result = {}

        # ── Sahm Rule ──
        result["sahm_rule"] = self._compute_sahm(data)

        # ── V/U Ratio ──
        result["vu_ratio"] = self._compute_vu_ratio(data)

        # ── U3 vs U6 ──
        result["u3_vs_u6"] = self._compute_u3_u6(data)

        # ── Participation ──
        result["participation"] = self._compute_participation(data)

        # ── NFP Trend ──
        result["nfp_trend"] = self._compute_nfp_trend(data)

        # ── Wages ──
        result["wages"] = self._compute_wages(data)

        # ── Initial Claims ──
        result["claims"] = self._compute_claims(data)

        # ── Quits Rate ──
        result["quits_rate"] = self._compute_quits(data)

        # ── Unified signals list ──
        result["signals"] = self._build_signals(result)

        return result

    def _compute_sahm(self, data: dict) -> dict:
        """
        Sahm Rule: triggered when the 3-month moving average of the
        unemployment rate rises 0.5 pp or more above its low over the
        prior 12 months.
        """
        unemp_df = data.get("unemployment")
        if unemp_df is None or unemp_df.empty:
            return {}

        series = self._safe_series(unemp_df, "value")
        if series is None or len(series) < 15:
            return {}

        # 3-month moving average
        ma3 = series.rolling(3, min_periods=3).mean()
        # 12-month rolling minimum of the 3m MA
        low_12m = ma3.rolling(12, min_periods=1).min()

        current_3m = ma3.iloc[-1]
        recent_low = low_12m.iloc[-1]
        gap = round(current_3m - recent_low, 4)
        threshold = 0.5
        triggered = gap >= threshold

        if triggered:
            color = "red"
        elif gap >= 0.3:
            color = "yellow"
        else:
            color = "green"

        return {
            "triggered": triggered,
            "gap": round(gap, 2),
            "threshold": threshold,
            "current_3m": round(current_3m, 2),
            "low_12m": round(recent_low, 2),
            "color": color,
        }

    def _compute_vu_ratio(self, data: dict) -> dict:
        """V/U ratio: JOLTS openings / unemployed count.

        Both series are in thousands, so ratio = openings / unemployed.
        >1.2 green, 1.0-1.2 yellow, <1.0 red
        """
        openings = self._safe_latest(data.get("jolts_openings"), "value")
        unemployed = self._safe_latest(data.get("unemployed_count"), "value")

        if openings is None or unemployed is None or unemployed == 0:
            return {}

        ratio = round(openings / unemployed, 2)

        if ratio > 1.2:
            color = "green"
            level = "紧张"
        elif ratio >= 1.0:
            color = "yellow"
            level = "平衡"
        else:
            color = "red"
            level = "疲软"

        return {"ratio": ratio, "level": level, "color": color}

    def _compute_u3_u6(self, data: dict) -> dict:
        """U3 vs U6 gap analysis. gap <2 green, 2-3 yellow, >3 red."""
        u3 = self._safe_latest(data.get("unemployment"), "value")
        u6 = self._safe_latest(data.get("u6_rate"), "value")

        if u3 is None or u6 is None:
            return {}

        gap = round(u6 - u3, 2)

        if gap < 2:
            color = "green"
        elif gap <= 3:
            color = "yellow"
        else:
            color = "red"

        return {"u3": round(u3, 2), "u6": round(u6, 2), "gap": gap, "color": color}

    def _compute_participation(self, data: dict) -> dict:
        """Labor force participation: overall and prime-age."""
        overall = self._safe_latest(data.get("labor_participation"), "value")
        prime_age = self._safe_latest(data.get("prime_age_lfpr"), "value")

        if overall is None and prime_age is None:
            return {}

        result = {}
        if overall is not None:
            result["overall"] = round(overall, 2)
        if prime_age is not None:
            result["prime_age"] = round(prime_age, 2)

        # Color based on prime-age (pre-pandemic peak ~83%)
        ref = prime_age if prime_age is not None else overall
        if ref is not None:
            if ref >= 83.0:
                result["color"] = "green"
            elif ref >= 82.0:
                result["color"] = "yellow"
            else:
                result["color"] = "red"

        return result

    def _compute_nfp_trend(self, data: dict) -> dict:
        """
        Non-farm payrolls monthly change trend.
        >150K green, 100-150K yellow, <100K red.
        """
        nfp_df = data.get("nonfarm_payrolls")
        if nfp_df is None or nfp_df.empty:
            return {}

        series = self._safe_series(nfp_df, "value")
        if series is None or len(series) < 2:
            return {}

        # Monthly change in thousands
        changes = series.diff(1).dropna()
        if changes.empty:
            return {}

        latest = round(float(changes.iloc[-1]), 1)
        avg_3m = round(float(changes.tail(3).mean()), 1) if len(changes) >= 3 else latest
        avg_6m = round(float(changes.tail(6).mean()), 1) if len(changes) >= 6 else avg_3m

        if avg_3m > 150:
            color = "green"
        elif avg_3m >= 100:
            color = "yellow"
        else:
            color = "red"

        return {
            "latest": latest,
            "avg_3m": avg_3m,
            "avg_6m": avg_6m,
            "color": color,
        }

    def _compute_wages(self, data: dict) -> dict:
        """
        Average hourly earnings YoY.
        <3% green (cooling), 3-4% yellow, >4% red (overheating).
        """
        earnings_df = data.get("avg_hourly_earnings")
        if earnings_df is None or earnings_df.empty:
            return {}

        yoy = self._safe_latest(earnings_df, "yoy_pct")
        if yoy is None:
            return {}

        yoy = round(yoy, 2)

        # Trend: average of last 3 months
        trend_series = self._safe_series(earnings_df, "yoy_pct")
        trend = round(float(trend_series.tail(3).mean()), 2) if trend_series is not None and len(trend_series) >= 3 else yoy

        if yoy < 3:
            color = "green"
        elif yoy <= 4:
            color = "yellow"
        else:
            color = "red"

        return {"latest_yoy": yoy, "trend": trend, "color": color}

    def _compute_claims(self, data: dict) -> dict:
        """
        Initial jobless claims.
        <220K green, 220-300K yellow, >300K red.
        """
        claims_df = data.get("initial_claims")
        if claims_df is None or claims_df.empty:
            return {}

        latest = self._safe_latest(claims_df, "value")
        if latest is None:
            return {}

        latest = round(latest, 0)

        # 4-week average
        series = self._safe_series(claims_df, "value")
        avg_4w = round(float(series.tail(4).mean()), 0) if series is not None and len(series) >= 4 else latest

        if latest < 220:
            color = "green"
        elif latest <= 300:
            color = "yellow"
        else:
            color = "red"

        return {"latest": latest, "avg_4w": avg_4w, "color": color}

    def _compute_quits(self, data: dict) -> dict:
        """
        JOLTS quits rate.
        >2.5 green, 2.0-2.5 yellow, <2.0 red.
        """
        quits_df = data.get("jolts_quits")
        if quits_df is None or quits_df.empty:
            return {}

        latest = self._safe_latest(quits_df, "value")
        if latest is None:
            return {}

        latest = round(latest, 2)

        if latest > 2.5:
            color = "green"
        elif latest >= 2.0:
            color = "yellow"
        else:
            color = "red"

        return {"latest": latest, "color": color}

    def _build_signals(self, result: dict) -> list[dict]:
        """Build a unified signals list from all computed sections."""
        signals = []

        # Sahm Rule
        sahm = result.get("sahm_rule", {})
        if sahm:
            signals.append({
                "name": "Sahm Rule",
                "value": f"差距 {sahm.get('gap', 'N/A')} pp",
                "color": sahm.get("color", "gray"),
                "description": "已触发衰退信号" if sahm.get("triggered") else "未触发",
            })

        # V/U Ratio
        vu = result.get("vu_ratio", {})
        if vu:
            signals.append({
                "name": "V/U 比率",
                "value": str(vu.get("ratio", "N/A")),
                "color": vu.get("color", "gray"),
                "description": vu.get("level", ""),
            })

        # U3 vs U6
        u3u6 = result.get("u3_vs_u6", {})
        if u3u6:
            signals.append({
                "name": "U3-U6 差距",
                "value": f"{u3u6.get('gap', 'N/A')} pp",
                "color": u3u6.get("color", "gray"),
                "description": f"U3={u3u6.get('u3', 'N/A')}% U6={u3u6.get('u6', 'N/A')}%",
            })

        # NFP
        nfp = result.get("nfp_trend", {})
        if nfp:
            signals.append({
                "name": "非农就业 (3月均)",
                "value": f"{nfp.get('avg_3m', 'N/A')}K",
                "color": nfp.get("color", "gray"),
                "description": f"最新 {nfp.get('latest', 'N/A')}K，6月均 {nfp.get('avg_6m', 'N/A')}K",
            })

        # Wages
        wages = result.get("wages", {})
        if wages:
            signals.append({
                "name": "工资增速 YoY",
                "value": f"{wages.get('latest_yoy', 'N/A')}%",
                "color": wages.get("color", "gray"),
                "description": f"趋势 {wages.get('trend', 'N/A')}%",
            })

        # Claims
        claims = result.get("claims", {})
        if claims:
            signals.append({
                "name": "初请失业金",
                "value": f"{claims.get('latest', 'N/A'):,.0f}" if isinstance(claims.get("latest"), (int, float)) else "N/A",
                "color": claims.get("color", "gray"),
                "description": f"4周均值 {claims.get('avg_4w', 'N/A'):,.0f}" if isinstance(claims.get("avg_4w"), (int, float)) else "",
            })

        # Quits
        quits = result.get("quits_rate", {})
        if quits:
            signals.append({
                "name": "辞职率",
                "value": f"{quits.get('latest', 'N/A')}%",
                "color": quits.get("color", "gray"),
                "description": ">2.5% 劳动市场健康" if (quits.get("latest") or 0) > 2.5 else "劳动市场降温",
            })

        # Participation
        part = result.get("participation", {})
        if part:
            prime = part.get("prime_age")
            signals.append({
                "name": "25-54岁参与率",
                "value": f"{prime}%" if prime is not None else "N/A",
                "color": part.get("color", "gray"),
                "description": f"总体参与率 {part.get('overall', 'N/A')}%",
            })

        return signals
