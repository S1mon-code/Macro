"""衰退概率追踪

综合多维信号估算衰退概率，提供收益率曲线分析、
Sahm Rule 详细计算及加权综合概率。
"""

import pandas as pd
import numpy as np


class RecessionTracker:
    """衰退概率追踪"""

    def compute_yield_curve(self, data: dict) -> dict | None:
        """计算收益率曲线信号

        Parameters
        ----------
        data : dict
            美国宏观数据，需包含 treasury_10y, treasury_3m, treasury_2y / yield_spread

        Returns
        -------
        dict | None
            {spread_3m10y, spread_2s10s, months_inverted_3m10y, signal}
        """
        t10 = data.get("treasury_10y")
        t3m = data.get("treasury_3m")
        t2y = data.get("treasury_2y")
        ys = data.get("yield_spread")  # 10Y-2Y 已有

        if t10 is None or t10.empty:
            return None

        t10 = t10.sort_values("date").copy()

        # ── 3M-10Y spread ──
        spread_3m10y = None
        months_inverted = 0
        if t3m is not None and not t3m.empty:
            t3m = t3m.sort_values("date").copy()
            merged = pd.merge(
                t10[["date", "value"]],
                t3m[["date", "value"]],
                on="date",
                suffixes=("_10y", "_3m"),
            )
            if not merged.empty:
                merged["spread"] = merged["value_10y"] - merged["value_3m"]
                spread_3m10y = round(float(merged["spread"].iloc[-1]), 3)
                # 连续倒挂月数 (从最新往回数)
                spreads = merged["spread"].values
                months_inverted = 0
                for s in reversed(spreads):
                    if s < 0:
                        months_inverted += 1
                    else:
                        break

        # ── 2S-10S spread ──
        spread_2s10s = None
        if ys is not None and not ys.empty:
            ys_sorted = ys.sort_values("date")
            spread_2s10s = round(float(ys_sorted["value"].dropna().iloc[-1]), 3)
        elif t2y is not None and not t2y.empty:
            t2y = t2y.sort_values("date").copy()
            merged_2s = pd.merge(
                t10[["date", "value"]],
                t2y[["date", "value"]],
                on="date",
                suffixes=("_10y", "_2y"),
            )
            if not merged_2s.empty:
                spread_2s10s = round(
                    float(merged_2s["value_10y"].iloc[-1] - merged_2s["value_2y"].iloc[-1]),
                    3,
                )

        # ── 综合信号 ──
        if spread_3m10y is not None:
            if spread_3m10y < -0.5:
                signal = "深度倒挂 - 衰退风险高"
            elif spread_3m10y < 0:
                signal = "倒挂 - 衰退风险上升"
            elif spread_3m10y < 0.5:
                signal = "平坦 - 需关注"
            else:
                signal = "正常 - 扩张期"
        else:
            signal = "数据不足"

        return {
            "spread_3m10y": spread_3m10y,
            "spread_2s10s": spread_2s10s,
            "months_inverted_3m10y": months_inverted,
            "signal": signal,
        }

    def sahm_rule(self, unemployment_df: pd.DataFrame | None) -> dict | None:
        """Sahm Rule 详细计算

        Parameters
        ----------
        unemployment_df : DataFrame
            失业率数据 (date, value)

        Returns
        -------
        dict | None
            {triggered, gap, threshold, current_3m_avg, low_12m,
             current_rate, prev_3m_avg, trend}
        """
        if unemployment_df is None or unemployment_df.empty:
            return None
        df = unemployment_df.sort_values("date")
        values = df["value"].dropna()
        if len(values) < 12:
            return None

        current_3m_avg = float(values.tail(3).mean())
        low_12m = float(values.tail(12).min())
        gap = current_3m_avg - low_12m
        threshold = 0.50
        triggered = gap >= threshold

        # 趋势: 对比前一个月的3月均值
        if len(values) >= 4:
            prev_3m_avg = float(values.iloc[-4:-1].mean())
        else:
            prev_3m_avg = None

        if prev_3m_avg is not None:
            delta = current_3m_avg - prev_3m_avg
            if delta > 0.05:
                trend = "上升"
            elif delta < -0.05:
                trend = "下降"
            else:
                trend = "稳定"
        else:
            trend = "数据不足"

        return {
            "triggered": triggered,
            "gap": round(gap, 4),
            "threshold": threshold,
            "current_3m_avg": round(current_3m_avg, 4),
            "low_12m": round(low_12m, 4),
            "current_rate": round(float(values.iloc[-1]), 4),
            "prev_3m_avg": round(prev_3m_avg, 4) if prev_3m_avg is not None else None,
            "trend": trend,
        }

    def composite_probability(self, data: dict) -> dict | None:
        """简化版综合衰退概率

        加权平均四类信号，各类归一化到 0-100:
        - yield_curve_score (30%): 基于 3M-10Y 利差
        - credit_score (20%): 基于 HY 信用利差
        - labor_score (25%): 基于 Sahm Rule + 初请失业金
        - activity_score (25%): 基于 LEI + 消费者信心

        Parameters
        ----------
        data : dict
            美国宏观数据

        Returns
        -------
        dict | None
            {probability, components: [...], signal}
        """
        components = []

        # ── 1. Yield Curve Score (30%) ──
        yc = self.compute_yield_curve(data)
        yc_score = None
        if yc is not None and yc["spread_3m10y"] is not None:
            spread = yc["spread_3m10y"]
            # 映射: spread 2.0 -> 0, spread 0.0 -> 50, spread -1.0 -> 100
            yc_score = self._normalize(spread, high_good=2.0, low_bad=-1.0)
            components.append({
                "name": "收益率曲线",
                "weight": 0.30,
                "score": round(yc_score, 1),
                "detail": f"3M-10Y 利差 {spread:+.3f}%",
            })

        # ── 2. Credit Score (20%) ──
        hy_df = data.get("hy_spread")
        credit_score = None
        if hy_df is not None and not hy_df.empty:
            hy_val = float(hy_df.sort_values("date")["value"].dropna().iloc[-1])
            # 映射: 3% -> 0, 5% -> 50, 8% -> 100
            credit_score = self._normalize(hy_val, high_good=3.0, low_bad=8.0, invert=True)
            components.append({
                "name": "信用利差",
                "weight": 0.20,
                "score": round(credit_score, 1),
                "detail": f"HY 利差 {hy_val:.2f}%",
            })

        # ── 3. Labor Score (25%) ──
        labor_scores = []

        sahm = self.sahm_rule(data.get("unemployment"))
        if sahm is not None:
            # 映射: gap 0.0 -> 0, gap 0.3 -> 50, gap 0.6 -> 100
            s = self._normalize(sahm["gap"], high_good=0.0, low_bad=0.6, invert=True)
            labor_scores.append(s)

        claims_df = data.get("initial_claims")
        if claims_df is not None and not claims_df.empty:
            claims_val = float(claims_df.sort_values("date")["value"].dropna().iloc[-1])
            # 映射: 200K -> 0, 260K -> 50, 350K -> 100
            s = self._normalize(
                claims_val, high_good=200_000, low_bad=350_000, invert=True
            )
            labor_scores.append(s)

        if labor_scores:
            labor_score = sum(labor_scores) / len(labor_scores)
            detail_parts = []
            if sahm is not None:
                detail_parts.append(f"Sahm gap {sahm['gap']:.3f}pp")
            if claims_df is not None and not claims_df.empty:
                detail_parts.append(f"Claims {claims_val:,.0f}")
            components.append({
                "name": "劳动力市场",
                "weight": 0.25,
                "score": round(labor_score, 1),
                "detail": ", ".join(detail_parts),
            })

        # ── 4. Activity Score (25%) ──
        activity_scores = []

        lei_df = data.get("lei")
        if lei_df is not None and not lei_df.empty:
            lei_vals = lei_df.sort_values("date")["value"].dropna()
            if len(lei_vals) >= 7:
                current = float(lei_vals.iloc[-1])
                six_ago = float(lei_vals.iloc[-7])
                if six_ago != 0:
                    lei_chg = ((current / six_ago) - 1) * 200  # annualized
                    # 映射: +3% -> 0, 0% -> 50, -4% -> 100
                    s = self._normalize(lei_chg, high_good=3.0, low_bad=-4.0)
                    activity_scores.append(s)

        sent_df = data.get("consumer_sentiment")
        if sent_df is not None and not sent_df.empty:
            sent_val = float(sent_df.sort_values("date")["value"].dropna().iloc[-1])
            # 映射: 90 -> 0, 65 -> 50, 50 -> 100
            s = self._normalize(sent_val, high_good=90.0, low_bad=50.0)
            activity_scores.append(s)

        if activity_scores:
            activity_score = sum(activity_scores) / len(activity_scores)
            detail_parts = []
            if lei_df is not None and not lei_df.empty and len(lei_vals) >= 7:
                detail_parts.append(f"LEI 6M年化 {lei_chg:+.1f}%")
            if sent_df is not None and not sent_df.empty:
                detail_parts.append(f"信心指数 {sent_val:.1f}")
            components.append({
                "name": "经济活动",
                "weight": 0.25,
                "score": round(activity_score, 1),
                "detail": ", ".join(detail_parts),
            })

        if not components:
            return None

        # ── 加权综合 ──
        total_weight = sum(c["weight"] for c in components)
        probability = sum(c["weight"] * c["score"] for c in components) / total_weight
        probability = max(0.0, min(100.0, probability))

        if probability >= 60:
            signal = "高风险"
        elif probability >= 35:
            signal = "中等风险"
        else:
            signal = "低风险"

        return {
            "probability": round(probability, 1),
            "components": components,
            "signal": signal,
        }

    @staticmethod
    def _normalize(
        value: float,
        high_good: float,
        low_bad: float,
        invert: bool = False,
    ) -> float:
        """将值归一化到 0-100 范围

        Parameters
        ----------
        value : float
            原始值
        high_good : float
            "好" 端的参考值 (映射到 0)
        low_bad : float
            "坏" 端的参考值 (映射到 100)
        invert : bool
            True 表示值越大越危险 (如利差扩大)
        """
        if invert:
            # 值越大 -> 分数越高 (越危险)
            score = (value - high_good) / (low_bad - high_good) * 100
        else:
            # 值越小 -> 分数越高 (越危险)
            score = (high_good - value) / (high_good - low_bad) * 100

        return max(0.0, min(100.0, score))
