"""历史上下文 & 百分位排名

为宏观指标提供历史定位：百分位排名、Z-Score、
5年/10年均值对比等，帮助判断当前值的历史位置。
"""

import numpy as np
import pandas as pd
from scipy import stats as sp_stats


class HistoricalContext:
    """历史上下文 & 百分位排名"""

    def compute(self, df: pd.DataFrame, col: str = "value") -> dict | None:
        """计算指标的历史上下文

        Parameters
        ----------
        df : DataFrame
            包含 date 和目标列的 DataFrame
        col : str
            要分析的列名，默认 "value"

        Returns
        -------
        dict | None
            {current, mean_5y, mean_10y, min, max,
             percentile, percentile_5y, z_score, z_score_5y,
             n_observations, date_range}
        """
        if df is None or df.empty:
            return None

        if col not in df.columns:
            return None

        df = df.sort_values("date").copy()
        values = df[col].dropna()

        if len(values) < 2:
            return None

        current = float(values.iloc[-1])
        all_values = values.values.astype(float)

        # 全历史统计
        mean_all = float(np.mean(all_values))
        std_all = float(np.std(all_values, ddof=1)) if len(all_values) > 1 else 0.0
        val_min = float(np.min(all_values))
        val_max = float(np.max(all_values))

        # 百分位: 当前值在全历史中的位置
        percentile = float(sp_stats.percentileofscore(all_values, current, kind="rank"))

        # Z-Score (全历史)
        z_score = (current - mean_all) / std_all if std_all > 0 else 0.0

        # ── 5年窗口 (60个月) ──
        tail_5y = values.tail(60)
        if len(tail_5y) >= 3:
            vals_5y = tail_5y.values.astype(float)
            mean_5y = float(np.mean(vals_5y))
            std_5y = float(np.std(vals_5y, ddof=1)) if len(vals_5y) > 1 else 0.0
            percentile_5y = float(
                sp_stats.percentileofscore(vals_5y, current, kind="rank")
            )
            z_score_5y = (current - mean_5y) / std_5y if std_5y > 0 else 0.0
        else:
            mean_5y = mean_all
            percentile_5y = percentile
            z_score_5y = z_score

        # ── 日期范围 ──
        dates = df["date"].dropna()
        if len(dates) >= 2:
            date_start = dates.iloc[0]
            date_end = dates.iloc[-1]
            if hasattr(date_start, "strftime"):
                date_range = f"{date_start.strftime('%Y-%m')} ~ {date_end.strftime('%Y-%m')}"
            else:
                date_range = f"{str(date_start)[:7]} ~ {str(date_end)[:7]}"
        else:
            date_range = "N/A"

        return {
            "current": round(current, 4),
            "mean_5y": round(mean_5y, 4),
            "mean_10y": round(mean_all, 4),  # 全历史均值 (配置默认从2016起)
            "min": round(val_min, 4),
            "max": round(val_max, 4),
            "percentile": round(percentile, 1),
            "percentile_5y": round(percentile_5y, 1),
            "z_score": round(z_score, 3),
            "z_score_5y": round(z_score_5y, 3),
            "n_observations": len(all_values),
            "date_range": date_range,
        }

    def compute_batch(
        self, data: dict, col: str = "value"
    ) -> dict[str, dict]:
        """批量计算多个指标的上下文

        Parameters
        ----------
        data : dict
            {指标名: DataFrame} 的字典
        col : str
            要分析的列名

        Returns
        -------
        dict[str, dict]
            {指标名: context_dict}，跳过无法计算的指标
        """
        results = {}
        for name, df in data.items():
            if df is None:
                continue
            if isinstance(df, pd.DataFrame) and not df.empty:
                ctx = self.compute(df, col=col)
                if ctx is not None:
                    results[name] = ctx
        return results
