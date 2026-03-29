import pandas as pd
import numpy as np
import plotly.graph_objects as go


class CPIChartBuilder:
    """生成 CPI 相关的 Plotly 图表"""

    CHART_TEMPLATE = "plotly_dark"
    COLORS = [
        "#e94560", "#0f3460", "#533483", "#16c79a",
        "#f5a623", "#50c4ed", "#ff6b6b", "#a29bfe",
    ]

    def __init__(self, data: dict[str, pd.DataFrame], labels: dict[str, str]):
        self.data = data
        self.labels = labels

    def _label(self, name: str) -> str:
        return self.labels.get(name, name)

    def yoy_trend(self, components: list[str] | None = None) -> go.Figure:
        """CPI 同比趋势折线图（多分项叠加）"""
        if components is None:
            components = ["all_items", "core"]

        fig = go.Figure()
        for i, name in enumerate(components):
            df = self.data.get(name)
            if df is None or df.empty:
                continue
            df_valid = df.dropna(subset=["yoy_pct"])
            fig.add_trace(go.Scatter(
                x=df_valid["date"],
                y=df_valid["yoy_pct"],
                mode="lines+markers",
                name=self._label(name),
                line=dict(color=self.COLORS[i % len(self.COLORS)], width=2),
                marker=dict(size=4),
            ))

        fig.update_layout(
            title="美国 CPI 同比变化趋势 (%)",
            xaxis_title="日期",
            yaxis_title="同比 (%)",
            template=self.CHART_TEMPLATE,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        return fig

    def mom_bar(self, component: str = "all_items", last_n: int = 12) -> go.Figure:
        """CPI 环比柱状图（最近 N 个月）"""
        df = self.data.get(component)
        if df is None or df.empty:
            return go.Figure()

        df_valid = df.dropna(subset=["mom_pct"]).tail(last_n)
        colors = ["#e94560" if v > 0 else "#16c79a" for v in df_valid["mom_pct"]]

        fig = go.Figure(go.Bar(
            x=df_valid["date"],
            y=df_valid["mom_pct"],
            marker_color=colors,
            text=[f"{v:.2f}%" for v in df_valid["mom_pct"]],
            textposition="outside",
        ))

        fig.update_layout(
            title=f"{self._label(component)} 环比变化 (%, 最近{last_n}个月)",
            xaxis_title="日期",
            yaxis_title="环比 (%)",
            template=self.CHART_TEMPLATE,
        )
        return fig

    def components_latest_yoy(self, components: list[str]) -> go.Figure:
        """各分项最新同比对比横��柱状图"""
        names = []
        values = []
        for name in components:
            df = self.data.get(name)
            if df is None or df.empty:
                continue
            df_valid = df.dropna(subset=["yoy_pct"])
            if df_valid.empty:
                continue
            latest = df_valid.iloc[-1]
            names.append(self._label(name))
            values.append(latest["yoy_pct"])

        colors = ["#e94560" if v > 0 else "#16c79a" for v in values]

        fig = go.Figure(go.Bar(
            x=values,
            y=names,
            orientation="h",
            marker_color=colors,
            text=[f"{v:.1f}%" for v in values],
            textposition="outside",
        ))

        fig.update_layout(
            title="CPI 各分项最新同比变化 (%)",
            xaxis_title="同比 (%)",
            template=self.CHART_TEMPLATE,
            height=max(400, len(names) * 40 + 200),
        )
        return fig

    def forecast(
        self, component: str = "all_items", months_ahead: int = 3
    ) -> go.Figure:
        """简单线性趋势预测"""
        df = self.data.get(component)
        if df is None or df.empty:
            return go.Figure()

        df_valid = df.dropna(subset=["yoy_pct"]).copy()
        if len(df_valid) < 6:
            return go.Figure()

        recent = df_valid.tail(12).copy()
        x = np.arange(len(recent))
        y = recent["yoy_pct"].values

        coeffs = np.polyfit(x, y, deg=1)
        slope, intercept = coeffs[0], coeffs[1]

        future_x = np.arange(len(recent), len(recent) + months_ahead)
        future_y = slope * future_x + intercept
        last_date = recent["date"].iloc[-1]
        future_dates = pd.date_range(last_date, periods=months_ahead + 1, freq="MS")[1:]

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=df_valid["date"],
            y=df_valid["yoy_pct"],
            mode="lines+markers",
            name=f"{self._label(component)} 实际值",
            line=dict(color="#0f3460", width=2),
            marker=dict(size=4),
        ))

        fit_y = slope * x + intercept
        fig.add_trace(go.Scatter(
            x=recent["date"],
            y=fit_y,
            mode="lines",
            name="趋势拟合",
            line=dict(color="#f5a623", width=1, dash="dot"),
        ))

        fig.add_trace(go.Scatter(
            x=future_dates,
            y=future_y,
            mode="lines+markers",
            name=f"预测 ({months_ahead}个月)",
            line=dict(color="#e94560", width=2, dash="dash"),
            marker=dict(size=6, symbol="diamond"),
        ))

        fig.update_layout(
            title=f"{self._label(component)} 同比趋势与预测 (%)",
            xaxis_title="日期",
            yaxis_title="同��� (%)",
            template=self.CHART_TEMPLATE,
            hovermode="x unified",
            annotations=[dict(
                text="* 预测基于线性趋势外推，仅供参考",
                xref="paper", yref="paper",
                x=0, y=-0.15, showarrow=False,
                font=dict(size=10, color="gray"),
            )],
        )
        return fig

    def index_value_trend(self, components: list[str] | None = None) -> go.Figure:
        """CPI 指数绝对值走势图"""
        if components is None:
            components = ["all_items", "core"]

        fig = go.Figure()
        for i, name in enumerate(components):
            df = self.data.get(name)
            if df is None or df.empty:
                continue
            fig.add_trace(go.Scatter(
                x=df["date"],
                y=df["value"],
                mode="lines",
                name=self._label(name),
                line=dict(color=self.COLORS[i % len(self.COLORS)], width=2),
            ))

        fig.update_layout(
            title="美国 CPI 指数走势 (1982-84=100)",
            xaxis_title="日期",
            yaxis_title="指数值",
            template=self.CHART_TEMPLATE,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        return fig
