import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


class MacroChartBuilder:
    """Data-source agnostic chart builder for macroeconomic data.

    Works with any dict[str, pd.DataFrame] where each DataFrame has columns
    like [date, value, yoy_pct, mom_pct] (not all required for every chart).
    """

    CHART_TEMPLATE = "plotly_dark"
    COLORS = [
        "#e94560", "#0f3460", "#533483", "#16c79a",
        "#f5a623", "#50c4ed", "#ff6b6b", "#a29bfe",
    ]

    def __init__(self, data: dict[str, pd.DataFrame], labels: dict[str, str]):
        self.data = data
        self.labels = labels

    def _label(self, key: str) -> str:
        return self.labels.get(key, key)

    def _get_valid(self, key: str, y_col: str) -> pd.DataFrame | None:
        """Return DataFrame with non-null y_col rows, or None if unavailable."""
        df = self.data.get(key)
        if df is None or df.empty:
            return None
        if y_col not in df.columns or "date" not in df.columns:
            return None
        df_valid = df.dropna(subset=[y_col])
        if df_valid.empty:
            return None
        return df_valid

    def line_trend(
        self,
        keys: list[str],
        y_col: str = "value",
        title: str = "",
        y_label: str = "",
    ) -> go.Figure:
        """Multi-series line chart. keys are dict keys in self.data."""
        fig = go.Figure()
        has_data = False

        for i, key in enumerate(keys):
            df_valid = self._get_valid(key, y_col)
            if df_valid is None:
                continue
            has_data = True
            fig.add_trace(go.Scatter(
                x=df_valid["date"].tolist(),
                y=df_valid[y_col].tolist(),
                mode="lines+markers",
                name=self._label(key),
                line=dict(color=self.COLORS[i % len(self.COLORS)], width=2),
                marker=dict(size=4),
            ))

        if not has_data:
            return go.Figure()

        fig.update_layout(
            title=title,
            xaxis_title="Date",
            yaxis_title=y_label,
            template=self.CHART_TEMPLATE,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        return fig

    def bar_chart(
        self,
        key: str,
        y_col: str = "value",
        last_n: int = 24,
        title: str = "",
    ) -> go.Figure:
        """Vertical bar chart for a single series. Red positive, green negative."""
        df_valid = self._get_valid(key, y_col)
        if df_valid is None:
            return go.Figure()

        df_tail = df_valid.tail(last_n)
        values = df_tail[y_col].tolist()
        colors = ["#e94560" if v > 0 else "#16c79a" for v in values]

        fig = go.Figure(go.Bar(
            x=df_tail["date"].tolist(),
            y=values,
            marker_color=colors,
            text=[f"{v:.2f}" for v in values],
            textposition="outside",
        ))

        fig.update_layout(
            title=title or f"{self._label(key)} — Last {last_n}",
            xaxis_title="Date",
            yaxis_title=y_col,
            template=self.CHART_TEMPLATE,
        )
        return fig

    def horizontal_bar(
        self,
        keys: list[str],
        y_col: str = "value",
        title: str = "",
    ) -> go.Figure:
        """Horizontal bar chart comparing latest values across multiple series."""
        names: list[str] = []
        values: list[float] = []

        for key in keys:
            df_valid = self._get_valid(key, y_col)
            if df_valid is None:
                continue
            latest = df_valid.iloc[-1]
            names.append(self._label(key))
            values.append(float(latest[y_col]))

        if not names:
            return go.Figure()

        colors = ["#e94560" if v > 0 else "#16c79a" for v in values]

        fig = go.Figure(go.Bar(
            x=values,
            y=names,
            orientation="h",
            marker_color=colors,
            text=[f"{v:.2f}" for v in values],
            textposition="outside",
        ))

        fig.update_layout(
            title=title,
            xaxis_title=y_col,
            template=self.CHART_TEMPLATE,
            height=max(400, len(names) * 40 + 200),
        )
        return fig

    def dual_axis(
        self,
        key: str,
        y1_col: str = "value",
        y2_col: str = "yoy_pct",
        title: str = "",
        y1_label: str = "",
        y2_label: str = "",
    ) -> go.Figure:
        """Dual Y-axis chart. Left axis: y1_col (line), Right axis: y2_col (bar)."""
        df = self.data.get(key)
        if df is None or df.empty or "date" not in df.columns:
            return go.Figure()

        has_y1 = y1_col in df.columns
        has_y2 = y2_col in df.columns
        if not has_y1 and not has_y2:
            return go.Figure()

        fig = make_subplots(specs=[[{"secondary_y": True}]])

        if has_y1:
            df_y1 = df.dropna(subset=[y1_col])
            if not df_y1.empty:
                fig.add_trace(
                    go.Scatter(
                        x=df_y1["date"].tolist(),
                        y=df_y1[y1_col].tolist(),
                        mode="lines",
                        name=y1_label or y1_col,
                        line=dict(color=self.COLORS[0], width=2),
                    ),
                    secondary_y=False,
                )

        if has_y2:
            df_y2 = df.dropna(subset=[y2_col])
            if not df_y2.empty:
                values = df_y2[y2_col].tolist()
                colors = ["#e94560" if v > 0 else "#16c79a" for v in values]
                fig.add_trace(
                    go.Bar(
                        x=df_y2["date"].tolist(),
                        y=values,
                        name=y2_label or y2_col,
                        marker_color=colors,
                        opacity=0.6,
                    ),
                    secondary_y=True,
                )

        fig.update_layout(
            title=title or f"{self._label(key)} — Dual Axis",
            xaxis_title="Date",
            template=self.CHART_TEMPLATE,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        fig.update_yaxes(title_text=y1_label or y1_col, secondary_y=False)
        fig.update_yaxes(title_text=y2_label or y2_col, secondary_y=True)
        return fig

    def multi_line(
        self,
        series_list: list[tuple[str, str, str]],
        title: str = "",
        y_label: str = "",
    ) -> go.Figure:
        """Plot multiple series from the same or different DataFrames.

        series_list: [(key, y_col, display_name), ...]
        """
        fig = go.Figure()
        has_data = False

        for i, (key, y_col, display_name) in enumerate(series_list):
            df_valid = self._get_valid(key, y_col)
            if df_valid is None:
                continue
            has_data = True
            fig.add_trace(go.Scatter(
                x=df_valid["date"].tolist(),
                y=df_valid[y_col].tolist(),
                mode="lines+markers",
                name=display_name,
                line=dict(color=self.COLORS[i % len(self.COLORS)], width=2),
                marker=dict(size=4),
            ))

        if not has_data:
            return go.Figure()

        fig.update_layout(
            title=title,
            xaxis_title="Date",
            yaxis_title=y_label,
            template=self.CHART_TEMPLATE,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        return fig
