import pandas as pd
import numpy as np


def safe_float(val) -> float | None:
    """Safely convert to float, return None for invalid/NaN values."""
    if val is None or val == "" or val == "-":
        return None
    try:
        result = float(val)
        if pd.isna(result):
            return None
        return result
    except (ValueError, TypeError):
        return None


def safe_latest(df, col="value"):
    """Get the latest non-null value from a DataFrame column."""
    if df is None or df.empty or col not in df.columns:
        return None
    series = pd.to_numeric(df.sort_values("date")[col], errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.iloc[-1])


def safe_latest_yoy(df):
    """Get latest YoY value."""
    return safe_latest(df, "yoy_pct")


def safe_trend(df, col="value", months=3):
    """Get weighted trend of last N months."""
    if df is None or df.empty or col not in df.columns:
        return None
    series = pd.to_numeric(df.sort_values("date")[col], errors="coerce").dropna()
    if len(series) < months:
        return None
    recent = series.tail(months)
    weights = np.arange(1, len(recent) + 1, dtype=float)
    return float(np.average(recent, weights=weights))
