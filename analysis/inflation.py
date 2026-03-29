import pandas as pd

from analysis.utils import safe_latest, safe_trend


class InflationAnalyzer:
    """通胀多维度拆解分析"""

    def _safe_latest(self, df: pd.DataFrame | None, col: str) -> float | None:
        """Safely extract the latest value for a given column from a DataFrame."""
        val = safe_latest(df, col)
        return round(val, 4) if val is not None else None

    def _safe_trend_3m(self, df: pd.DataFrame | None, col: str) -> float | None:
        """Compute the average of the last 3 available values for a column."""
        if df is None or df.empty:
            return None
        if col not in df.columns:
            return None
        valid = df.dropna(subset=[col])
        if len(valid) < 1:
            return None
        tail = valid.tail(3)[col]
        try:
            return round(float(tail.mean()), 4)
        except (ValueError, TypeError):
            return None

    def decompose(self, us_data: dict, cpi_data: dict) -> dict:
        """
        Return a comprehensive inflation decomposition.

        Args:
            us_data: FRED data dict (contains pce, core_pce, sticky_cpi, flexible_cpi, etc.)
            cpi_data: BLS CPI data dict (contains all_items, core, food, energy, shelter, etc.)

        Returns dict with:
            "headline_vs_core": list of dicts for CPI and PCE headline vs core
            "fed_preferred": list of Fed's preferred metrics
            "sticky_vs_flexible": sticky vs flexible CPI analysis
            "goods_vs_services": computed from CPI components
            "shelter_vs_non_shelter": computed from CPI shelter vs rest
        """
        result = {}

        # ── 1. Headline vs Core comparison ──
        headline_vs_core = []
        metrics = [
            ("CPI 总指数", cpi_data.get("all_items")),
            ("核心 CPI", cpi_data.get("core")),
            ("PCE", us_data.get("pce")),
            ("核心 PCE", us_data.get("core_pce")),
        ]
        for name, df in metrics:
            if df is None or df.empty:
                continue
            yoy = self._safe_latest(df, "yoy_pct")
            mom = self._safe_latest(df, "mom_pct")
            trend_3m = self._safe_trend_3m(df, "yoy_pct")
            if yoy is None:
                continue
            headline_vs_core.append({
                "name": name,
                "yoy": yoy,
                "mom": mom,
                "trend_3m": trend_3m,
            })
        result["headline_vs_core"] = headline_vs_core

        # ── 2. Fed preferred metrics ──
        fed_preferred = []
        fed_metrics = [
            ("核心 PCE", us_data.get("core_pce"), "Fed 最关注的通胀指标"),
            ("截尾均值 PCE", us_data.get("trimmed_mean_pce"), "剔除极端波动后的 PCE"),
            ("中位 CPI", us_data.get("median_cpi"), "克利夫兰联储中位 CPI"),
            ("粘性 CPI", us_data.get("sticky_cpi"), "亚特兰大联储粘性价格 CPI"),
        ]
        for name, df, description in fed_metrics:
            if df is None or df.empty:
                continue
            # For rate_series (sticky_cpi, flexible_cpi, etc.), the "value" column
            # IS the YoY rate. For index series (core_pce), use yoy_pct.
            # Trimmed mean PCE and median CPI are also rate series (value = YoY%).
            # Sticky CPI is a rate series too.
            # Core PCE is an index, so use yoy_pct.
            if name == "核心 PCE":
                value = self._safe_latest(df, "yoy_pct")
            else:
                # trimmed_mean_pce, median_cpi, sticky_cpi are rate series:
                # their "value" column is already the YoY rate
                value = self._safe_latest(df, "value")

            if value is None:
                continue

            vs_target = round(value - 2.0, 4)
            if vs_target > 1.0:
                signal = "显著高于目标"
            elif vs_target > 0.5:
                signal = "高于目标"
            elif vs_target > -0.5:
                signal = "接近目标"
            else:
                signal = "低于目标"

            fed_preferred.append({
                "name": name,
                "value": value,
                "vs_target": vs_target,
                "signal": signal,
                "description": description,
            })
        result["fed_preferred"] = fed_preferred

        # ── 3. Sticky vs Flexible CPI ──
        sticky_df = us_data.get("sticky_cpi")
        flexible_df = us_data.get("flexible_cpi")
        sticky_vs_flexible = {}
        sticky_yoy = self._safe_latest(sticky_df, "value") if sticky_df is not None else None
        flexible_yoy = self._safe_latest(flexible_df, "value") if flexible_df is not None else None
        if sticky_yoy is not None:
            sticky_vs_flexible["sticky_yoy"] = sticky_yoy
        if flexible_yoy is not None:
            sticky_vs_flexible["flexible_yoy"] = flexible_yoy
        if sticky_yoy is not None and flexible_yoy is not None:
            sticky_vs_flexible["gap"] = round(sticky_yoy - flexible_yoy, 4)
        result["sticky_vs_flexible"] = sticky_vs_flexible

        # ── 4. Goods vs Services (from CPI components) ──
        goods_keys = ["food", "energy", "apparel"]
        services_keys = ["shelter", "medical", "transportation", "education_communication"]

        goods_yoys = []
        for key in goods_keys:
            df = cpi_data.get(key)
            yoy = self._safe_latest(df, "yoy_pct")
            if yoy is not None:
                goods_yoys.append(yoy)

        services_yoys = []
        for key in services_keys:
            df = cpi_data.get(key)
            yoy = self._safe_latest(df, "yoy_pct")
            if yoy is not None:
                services_yoys.append(yoy)

        goods_vs_services = {}
        if goods_yoys:
            goods_vs_services["goods_avg_yoy"] = round(sum(goods_yoys) / len(goods_yoys), 4)
            goods_vs_services["goods_components"] = dict(zip(
                [k for k in goods_keys if self._safe_latest(cpi_data.get(k), "yoy_pct") is not None],
                goods_yoys,
            ))
        if services_yoys:
            goods_vs_services["services_avg_yoy"] = round(sum(services_yoys) / len(services_yoys), 4)
            goods_vs_services["services_components"] = dict(zip(
                [k for k in services_keys if self._safe_latest(cpi_data.get(k), "yoy_pct") is not None],
                services_yoys,
            ))
        if "goods_avg_yoy" in goods_vs_services and "services_avg_yoy" in goods_vs_services:
            goods_vs_services["gap"] = round(
                goods_vs_services["services_avg_yoy"] - goods_vs_services["goods_avg_yoy"], 4
            )
        result["goods_vs_services"] = goods_vs_services

        # ── 5. Shelter analysis ──
        shelter_analysis = {}
        shelter_yoy = self._safe_latest(cpi_data.get("shelter"), "yoy_pct")
        rent_yoy = self._safe_latest(cpi_data.get("rent"), "yoy_pct")
        oer_yoy = self._safe_latest(cpi_data.get("owners_equivalent_rent"), "yoy_pct")
        core_yoy = self._safe_latest(cpi_data.get("core"), "yoy_pct")

        if shelter_yoy is not None:
            shelter_analysis["shelter_yoy"] = shelter_yoy
        if rent_yoy is not None:
            shelter_analysis["rent_yoy"] = rent_yoy
        if oer_yoy is not None:
            shelter_analysis["owners_equivalent_rent_yoy"] = oer_yoy

        # Approximate non-shelter core CPI:
        # Core CPI weight of shelter is roughly ~43%. So:
        # non_shelter_core ≈ (core - 0.43 * shelter) / 0.57
        if core_yoy is not None and shelter_yoy is not None:
            shelter_weight = 0.43
            non_shelter_core = (core_yoy - shelter_weight * shelter_yoy) / (1 - shelter_weight)
            shelter_analysis["non_shelter_core_yoy"] = round(non_shelter_core, 4)
        result["shelter_vs_non_shelter"] = shelter_analysis

        return result

    def get_summary_table(self, us_data: dict, cpi_data: dict) -> list[dict]:
        """Return a summary table of all inflation metrics for display.

        Each row: {name, latest_value, mom, yoy, trend_3m, vs_target}
        """
        rows = []

        entries = [
            ("CPI 总指数", cpi_data.get("all_items"), "index"),
            ("核心 CPI", cpi_data.get("core"), "index"),
            ("PCE", us_data.get("pce"), "index"),
            ("核心 PCE", us_data.get("core_pce"), "index"),
            ("粘性 CPI", us_data.get("sticky_cpi"), "rate"),
            ("弹性 CPI", us_data.get("flexible_cpi"), "rate"),
            ("截尾均值 PCE", us_data.get("trimmed_mean_pce"), "rate"),
            ("中位 CPI", us_data.get("median_cpi"), "rate"),
            ("食品 CPI", cpi_data.get("food"), "index"),
            ("能源 CPI", cpi_data.get("energy"), "index"),
            ("住房 CPI", cpi_data.get("shelter"), "index"),
            ("交通 CPI", cpi_data.get("transportation"), "index"),
            ("医疗 CPI", cpi_data.get("medical"), "index"),
            ("服装 CPI", cpi_data.get("apparel"), "index"),
            ("租金", cpi_data.get("rent"), "index"),
            ("业主等价租金", cpi_data.get("owners_equivalent_rent"), "index"),
        ]

        for name, df, kind in entries:
            if df is None or df.empty:
                continue

            latest_value = self._safe_latest(df, "value")
            mom = self._safe_latest(df, "mom_pct")

            if kind == "rate":
                # Rate series: value IS the YoY rate
                yoy = latest_value
            else:
                yoy = self._safe_latest(df, "yoy_pct")

            if kind == "rate":
                trend_3m = self._safe_trend_3m(df, "value")
            else:
                trend_3m = self._safe_trend_3m(df, "yoy_pct")

            if yoy is None:
                continue

            vs_target = round(yoy - 2.0, 4) if yoy is not None else None

            rows.append({
                "name": name,
                "latest_value": latest_value,
                "mom": mom,
                "yoy": yoy,
                "trend_3m": trend_3m,
                "vs_target": vs_target,
            })

        return rows
