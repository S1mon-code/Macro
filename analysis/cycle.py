"""经济周期评估 - 红绿灯仪表盘

根据多维宏观指标评估当前经济周期状态，
输出红/黄/绿信号供报告仪表盘使用。
"""

import pandas as pd


class CycleAssessor:
    """经济周期评估 - 红绿灯仪表盘"""

    def assess(self, us_data: dict, china_data: dict) -> list[dict]:
        """
        评估经济周期状态，返回红绿灯信号列表。

        Parameters
        ----------
        us_data : dict
            美国宏观数据 {指标名: DataFrame}，包含 FRED + CPI 数据
        china_data : dict
            中国宏观数据 {指标名: DataFrame}

        Returns
        -------
        list[dict]
            每个信号: {name, value, threshold, color, description}
            color: "green", "yellow", "red"
            若数据不可用则跳过该信号
        """
        signals = []

        # 1. Sahm Rule (失业率)
        sig = self._sahm_rule(us_data.get("unemployment"))
        if sig is not None:
            signals.append(sig)

        # 2. 收益率曲线 (3m10y)
        sig = self._yield_curve(us_data.get("treasury_10y"), us_data.get("treasury_3m"))
        if sig is not None:
            signals.append(sig)

        # 3. 初请失业金
        sig = self._initial_claims(us_data.get("initial_claims"))
        if sig is not None:
            signals.append(sig)

        # 4. HY 信用利差
        sig = self._hy_spread(us_data.get("hy_spread"))
        if sig is not None:
            signals.append(sig)

        # 5. LEI 6月变化
        sig = self._lei_change(us_data.get("lei"))
        if sig is not None:
            signals.append(sig)

        # 6. NFP 3月均值
        sig = self._nfp_momentum(us_data.get("nonfarm_payrolls"))
        if sig is not None:
            signals.append(sig)

        # 7. 中国 PMI
        sig = self._china_pmi(china_data.get("pmi_manufacturing"))
        if sig is not None:
            signals.append(sig)

        # 8. 中国信贷脉冲
        sig = self._china_credit_impulse(china_data.get("credit"))
        if sig is not None:
            signals.append(sig)

        return signals

    # ── 各信号计算方法 ──────────────────────────────────────────

    def _sahm_rule(self, unemployment_df: pd.DataFrame | None) -> dict | None:
        """Sahm Rule: 3月均值失业率 vs 12月低点"""
        if unemployment_df is None or unemployment_df.empty:
            return None
        df = unemployment_df.sort_values("date")
        values = df["value"].dropna()
        if len(values) < 12:
            return None

        current_3m_avg = values.tail(3).mean()
        low_12m = values.tail(12).min()
        gap = current_3m_avg - low_12m

        if gap >= 0.50:
            color = "red"
        elif gap >= 0.30:
            color = "yellow"
        else:
            color = "green"

        return {
            "name": "Sahm Rule",
            "value": round(gap, 3),
            "threshold": ">=0.50pp = 衰退",
            "color": color,
            "description": (
                f"3月均值({current_3m_avg:.3f}%) vs "
                f"12月低点({low_12m:.3f}%), 差值 {gap:.3f}pp"
            ),
        }

    def _yield_curve(
        self,
        treasury_10y_df: pd.DataFrame | None,
        treasury_3m_df: pd.DataFrame | None,
    ) -> dict | None:
        """收益率曲线: 10Y - 3M 利差"""
        if treasury_10y_df is None or treasury_10y_df.empty:
            return None
        if treasury_3m_df is None or treasury_3m_df.empty:
            return None

        t10 = treasury_10y_df.sort_values("date")
        t3m = treasury_3m_df.sort_values("date")

        # 取最新月份的值
        val_10y = t10["value"].dropna().iloc[-1]
        val_3m = t3m["value"].dropna().iloc[-1]
        spread = val_10y - val_3m

        if spread > 0:
            color = "green"
        elif spread >= -0.5:
            color = "yellow"
        else:
            color = "red"

        return {
            "name": "收益率曲线 (3M-10Y)",
            "value": round(spread, 3),
            "threshold": "<0 倒挂, <-0.5 深度倒挂",
            "color": color,
            "description": (
                f"10Y({val_10y:.3f}%) - 3M({val_3m:.3f}%) = "
                f"{spread:+.3f}%"
            ),
        }

    def _initial_claims(self, claims_df: pd.DataFrame | None) -> dict | None:
        """初请失业金人数 (月均)"""
        if claims_df is None or claims_df.empty:
            return None
        df = claims_df.sort_values("date")
        latest = df["value"].dropna().iloc[-1]

        if latest < 220_000:
            color = "green"
        elif latest <= 300_000:
            color = "yellow"
        else:
            color = "red"

        return {
            "name": "初请失业金",
            "value": round(latest, 0),
            "threshold": "<220K 健康, >300K 危险",
            "color": color,
            "description": f"最新月均 {latest:,.0f} 人",
        }

    def _hy_spread(self, hy_df: pd.DataFrame | None) -> dict | None:
        """高收益信用利差 (百分点)"""
        if hy_df is None or hy_df.empty:
            return None
        df = hy_df.sort_values("date")
        latest = df["value"].dropna().iloc[-1]

        if latest < 4:
            color = "green"
        elif latest <= 6:
            color = "yellow"
        else:
            color = "red"

        return {
            "name": "HY 信用利差",
            "value": round(latest, 2),
            "threshold": "<4% 正常, >6% 紧缩",
            "color": color,
            "description": f"高收益债利差 {latest:.2f}%",
        }

    def _lei_change(self, lei_df: pd.DataFrame | None) -> dict | None:
        """LEI (Conference Board) 6月年化变化"""
        if lei_df is None or lei_df.empty:
            return None
        df = lei_df.sort_values("date")
        values = df["value"].dropna()
        if len(values) < 7:
            return None

        current = values.iloc[-1]
        six_months_ago = values.iloc[-7]

        if six_months_ago == 0:
            return None

        # 6-month annualized change: ((current / 6m_ago) - 1) * 2 * 100
        change_6m = ((current / six_months_ago) - 1) * 100
        annualized = change_6m * 2

        if annualized > 0:
            color = "green"
        elif annualized >= -2:
            color = "yellow"
        else:
            color = "red"

        return {
            "name": "LEI 6月变化",
            "value": round(annualized, 2),
            "threshold": ">0 扩张, <-2% 衰退警告",
            "color": color,
            "description": (
                f"LEI 6月年化变化 {annualized:+.2f}% "
                f"({six_months_ago:.1f} -> {current:.1f})"
            ),
        }

    def _nfp_momentum(self, nfp_df: pd.DataFrame | None) -> dict | None:
        """非农就业 3月均值 (月度绝对变化, 千人)"""
        if nfp_df is None or nfp_df.empty:
            return None
        df = nfp_df.sort_values("date")
        values = df["value"].dropna()
        if len(values) < 4:
            return None

        # 月度绝对变化 (千人)
        monthly_change = values.diff(1)
        avg_3m = monthly_change.tail(3).mean()

        if avg_3m > 150:
            color = "green"
        elif avg_3m >= 100:
            color = "yellow"
        else:
            color = "red"

        return {
            "name": "NFP 3月均值",
            "value": round(avg_3m, 1),
            "threshold": ">150K 强劲, <100K 疲软",
            "color": color,
            "description": f"非农3月均增 {avg_3m:+.1f}K 人",
        }

    def _china_pmi(self, pmi_df: pd.DataFrame | None) -> dict | None:
        """中国制造业 PMI"""
        if pmi_df is None or pmi_df.empty:
            return None
        df = pmi_df.sort_values("date")
        latest = df["value"].dropna().iloc[-1]

        if latest > 50.5:
            color = "green"
        elif latest >= 49.5:
            color = "yellow"
        else:
            color = "red"

        return {
            "name": "中国制造业 PMI",
            "value": round(latest, 1),
            "threshold": ">50.5 扩张, <49.5 收缩",
            "color": color,
            "description": f"PMI {latest:.1f} ({'扩张' if latest > 50 else '收缩'}区间)",
        }

    def _china_credit_impulse(self, credit_df: pd.DataFrame | None) -> dict | None:
        """中国信贷脉冲 (新增贷款同比变化)"""
        if credit_df is None or credit_df.empty:
            return None
        df = credit_df.sort_values("date")
        values = df["value"].dropna()
        if len(values) < 13:
            return None

        # 信贷脉冲: 12月滚动总和的同比变化率
        rolling_12m = values.rolling(12).sum()
        if rolling_12m.dropna().empty or len(rolling_12m.dropna()) < 13:
            return None

        current_12m = rolling_12m.iloc[-1]
        prev_12m = rolling_12m.iloc[-13]

        if prev_12m == 0:
            return None

        impulse = ((current_12m / prev_12m) - 1) * 100

        if impulse > 5:
            color = "green"
        elif impulse >= -5:
            color = "yellow"
        else:
            color = "red"

        return {
            "name": "中国信贷脉冲",
            "value": round(impulse, 2),
            "threshold": ">5% 宽松, <-5% 紧缩",
            "color": color,
            "description": f"12月滚动贷款同比 {impulse:+.2f}%",
        }
