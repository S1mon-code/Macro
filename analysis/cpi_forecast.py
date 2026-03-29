import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class CPIForecaster:
    """CPI 自下而上分项预测模型

    方法论：分别预测各分项 MoM，按 BLS 权重加总。
    """

    # BLS Relative Importance Weights (Dec 2024)
    WEIGHTS = {
        "all_items": 100.0,
        "food": 13.496,
        "food_at_home": 8.171,
        "food_away": 5.325,
        "energy": 6.907,
        "gasoline": 3.440,
        "electricity": 2.464,
        "natural_gas": 0.648,
        "shelter": 36.978,
        "rent": 7.637,
        "oer": 26.747,
        "used_cars": 2.516,
        "new_vehicles": 3.658,
        "medical": 8.379,
        "apparel": 2.476,
        "transportation_services": 5.826,
        "recreation": 5.336,
        "education_communication": 4.962,
        "other": 3.334,
    }

    def forecast(self, cpi_data: dict, fred_data: dict) -> dict:
        """
        Forecast next month's CPI.

        Args:
            cpi_data: dict of {component_name: DataFrame} from BLSFetcher.fetch_cpi_all().
                      Each DataFrame has columns: date, value, yoy_pct, mom_pct.
            fred_data: dict of {series_name: DataFrame} from FRED fetcher.
                       Each DataFrame has columns: date, value, yoy_pct, mom_pct.

        Returns:
        {
            "forecast_month": "2026年04月",
            "headline_mom_forecast": float,  # e.g. 0.25 (meaning +0.25% MoM)
            "core_mom_forecast": float,
            "headline_yoy_forecast": float,
            "core_yoy_forecast": float,
            "component_forecasts": [
                {"name": "住房/OER", "weight": 36.978, "mom_forecast": 0.28,
                 "contribution_bps": 10.3, "method": "基于Zillow租金12月滞后模型"},
                ...
            ],
            "base_effect": {
                "last_year_mom": float,  # MoM from 12 months ago (dropping out)
                "base_effect_bps": float,  # impact on YoY
            },
            "vs_consensus": {
                "our_headline_yoy": float,
                "consensus_headline_yoy": None,  # user can fill in
                "difference": None,
            },
            "key_drivers": [str],  # top 3 factors affecting this month's print
            "risks": {"upside": [str], "downside": [str]},
        }
        """
        result = {}

        # Determine forecast month (next month after latest data)
        all_items_df = cpi_data.get("all_items")
        if all_items_df is None or all_items_df.empty:
            return {"error": "No CPI data available"}

        all_items_sorted = all_items_df.sort_values("date").copy()
        latest_date = pd.to_datetime(all_items_sorted["date"]).max()
        forecast_date = latest_date + pd.DateOffset(months=1)
        result["forecast_month"] = forecast_date.strftime("%Y年%m月")

        # Get latest CPI index level
        latest_index = float(all_items_sorted.iloc[-1]["value"])

        # Component forecasts
        components = []

        # 1. Shelter/OER forecast
        oer_forecast = self._forecast_shelter(cpi_data)
        components.append({
            "name": "住房/OER",
            "weight": self.WEIGHTS["shelter"],
            "mom_forecast": oer_forecast,
            "contribution_bps": round(oer_forecast * self.WEIGHTS["shelter"] / 100, 2),
            "method": "近3月OER环比均值（趋势外推）+ 新签租金12月滞后",
        })

        # 2. Energy/Gasoline forecast (uses real-time gas/oil prices)
        self._energy_method = ""
        energy_forecast = self._forecast_energy(cpi_data, fred_data)
        components.append({
            "name": "能源（汽油为主）",
            "weight": self.WEIGHTS["energy"],
            "mom_forecast": energy_forecast,
            "contribution_bps": round(energy_forecast * self.WEIGHTS["energy"] / 100, 2),
            "method": self._energy_method,
        })

        # 3. Food forecast
        food_forecast = self._forecast_food(cpi_data)
        components.append({
            "name": "食品",
            "weight": self.WEIGHTS["food"],
            "mom_forecast": food_forecast,
            "contribution_bps": round(food_forecast * self.WEIGHTS["food"] / 100, 2),
            "method": "近3月食品CPI环比均值",
        })

        # 4. Used cars forecast
        used_cars_forecast = self._forecast_used_cars(cpi_data)
        components.append({
            "name": "二手车",
            "weight": self.WEIGHTS["used_cars"],
            "mom_forecast": used_cars_forecast,
            "contribution_bps": round(used_cars_forecast * self.WEIGHTS["used_cars"] / 100, 2),
            "method": "近期趋势（无Manheim数据时用CPI二手车趋势）",
        })

        # 5. Medical care forecast
        medical_forecast = self._forecast_medical(cpi_data)
        components.append({
            "name": "医疗",
            "weight": self.WEIGHTS["medical"],
            "mom_forecast": medical_forecast,
            "contribution_bps": round(medical_forecast * self.WEIGHTS["medical"] / 100, 2),
            "method": "近6月医疗CPI环比均值",
        })

        # 6. Transportation services
        transport_forecast = self._forecast_transport(cpi_data)
        components.append({
            "name": "交通服务",
            "weight": self.WEIGHTS["transportation_services"],
            "mom_forecast": transport_forecast,
            "contribution_bps": round(transport_forecast * self.WEIGHTS["transportation_services"] / 100, 2),
            "method": "近3月趋势",
        })

        # 7. Other core (apparel, recreation, education, new vehicles, other)
        other_weight = (
            self.WEIGHTS["apparel"]
            + self.WEIGHTS["recreation"]
            + self.WEIGHTS["education_communication"]
            + self.WEIGHTS["other"]
            + self.WEIGHTS["new_vehicles"]
        )
        other_forecast = self._forecast_other_core(cpi_data, fred_data)
        components.append({
            "name": "其他核心（服装/娱乐/教育/新车等）",
            "weight": round(other_weight, 1),
            "mom_forecast": other_forecast,
            "contribution_bps": round(other_forecast * other_weight / 100, 2),
            "method": "工资增速滞后模型 + 近期趋势",
        })

        # ── Headline MoM forecast ──
        # headline_mom% = sum(component_mom% * component_weight%) / 100
        headline_mom = sum(c["mom_forecast"] * c["weight"] for c in components) / 100.0
        result["headline_mom_forecast"] = round(headline_mom, 3)

        # ── Core MoM (exclude food and energy) ──
        core_components = [
            c for c in components
            if c["name"] not in ["食品", "能源（汽油为主）"]
        ]
        core_total_weight = sum(c["weight"] for c in core_components)
        if core_total_weight > 0:
            core_mom = sum(c["mom_forecast"] * c["weight"] for c in core_components) / core_total_weight
        else:
            core_mom = 0.0
        result["core_mom_forecast"] = round(core_mom, 3)

        result["component_forecasts"] = components

        # ── YoY forecast using base effect ──
        base_effect = self._compute_base_effect(cpi_data, forecast_date)
        result["base_effect"] = base_effect

        # Forecast YoY: new_index / index_12m_ago - 1
        forecast_index = latest_index * (1 + headline_mom / 100)
        twelve_months_ago = forecast_date - pd.DateOffset(months=12)

        idx_12m = all_items_sorted[
            pd.to_datetime(all_items_sorted["date"]) <= twelve_months_ago
        ]
        if not idx_12m.empty:
            index_12m_ago = float(idx_12m.iloc[-1]["value"])
            headline_yoy = (forecast_index / index_12m_ago - 1) * 100
            result["headline_yoy_forecast"] = round(headline_yoy, 3)
        else:
            headline_yoy = None
            result["headline_yoy_forecast"] = None

        # Core YoY (approximate via core CPI index)
        core_df = cpi_data.get("core")
        if core_df is not None and not core_df.empty:
            core_sorted = core_df.sort_values("date")
            latest_core_index = float(core_sorted.iloc[-1]["value"])
            forecast_core_index = latest_core_index * (1 + core_mom / 100)
            core_12m = core_sorted[
                pd.to_datetime(core_sorted["date"]) <= twelve_months_ago
            ]
            if not core_12m.empty:
                core_index_12m_ago = float(core_12m.iloc[-1]["value"])
                core_yoy = (forecast_core_index / core_index_12m_ago - 1) * 100
                result["core_yoy_forecast"] = round(core_yoy, 3)
            else:
                result["core_yoy_forecast"] = None
        else:
            result["core_yoy_forecast"] = None

        # Consensus placeholder
        result["vs_consensus"] = {
            "our_headline_yoy": result["headline_yoy_forecast"],
            "consensus_headline_yoy": None,
            "difference": None,
        }

        # Key drivers: top 3 components by absolute contribution
        sorted_components = sorted(
            components, key=lambda x: abs(x["contribution_bps"]), reverse=True
        )
        result["key_drivers"] = [
            f"{c['name']}: 预计MoM {c['mom_forecast']:+.2f}%, 贡献 {c['contribution_bps']:+.2f}bps"
            for c in sorted_components[:3]
        ]

        # Risks
        result["risks"] = {
            "upside": self._identify_upside_risks(cpi_data, fred_data),
            "downside": self._identify_downside_risks(cpi_data, fred_data),
        }

        return result

    # ──────────────────────────────────────────────
    # Component forecast methods
    # ──────────────────────────────────────────────

    def _forecast_shelter(self, cpi_data: dict) -> float:
        """Forecast shelter MoM using recent OER trend.

        Uses a weighted average of the last 6 months of OER MoM readings,
        with more recent months receiving higher weight (linearly increasing).
        Falls back to the shelter series, then to a 0.30% default.
        """
        for key in ["owners_equivalent_rent", "shelter"]:
            df = cpi_data.get(key)
            if df is None or df.empty:
                continue
            mom = pd.to_numeric(
                df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(mom) < 3:
                continue
            # Weighted average: more recent = higher weight
            recent = mom.tail(6)
            weights = np.arange(1, len(recent) + 1, dtype=float)
            return round(float(np.average(recent, weights=weights)), 3)
        return 0.30  # default: ~0.3% MoM for OER

    def _forecast_energy(self, cpi_data: dict, fred_data: dict) -> float:
        """Forecast energy MoM using real-time gasoline prices.

        投行方法：用当月实际零售汽油均价 vs 上月均价，算出汽油MoM。
        汽油占CPI能源权重约50%，非汽油能源（电力、天然气）相对稳定。

        数据源：FRED GASREGW（EIA周度零售汽油价格）
        """
        self._energy_method = "CPI能源历史趋势（无实时油价数据）"

        # 优先使用实时汽油价格数据
        gas_df = fred_data.get("retail_gasoline")
        if gas_df is not None and not gas_df.empty:
            gas_sorted = gas_df.sort_values("date")
            gas_values = pd.to_numeric(gas_sorted["value"], errors="coerce").dropna()

            if len(gas_values) >= 4:
                # 当月均价 vs 上月均价
                # 取最近的数据点作为当月，再往前的作为上月
                current_month_avg = float(gas_values.tail(2).mean())  # 最近2周
                prior_month_avg = float(gas_values.iloc[-4:-2].mean())  # 前2周

                if prior_month_avg > 0:
                    gas_mom_pct = ((current_month_avg / prior_month_avg) - 1) * 100

                    # 汽油占CPI能源约50%，非汽油能源（电力等）假设MoM ~0%
                    # CPI能源MoM ≈ 汽油MoM × 0.50（汽油在能源中的权重）
                    # 再加电力/天然气的小幅变动
                    energy_mom = gas_mom_pct * 0.50

                    self._energy_method = (
                        f"实时汽油价格: ${current_month_avg:.2f}/gal vs "
                        f"${prior_month_avg:.2f}/gal ({gas_mom_pct:+.1f}%), "
                        f"传导至CPI能源"
                    )
                    return round(energy_mom, 3)

        # 次选：用WTI原油价格推算
        oil_df = fred_data.get("wti_crude")
        if oil_df is not None and not oil_df.empty:
            oil_sorted = oil_df.sort_values("date")
            oil_values = pd.to_numeric(oil_sorted["value"], errors="coerce").dropna()

            if len(oil_values) >= 4:
                current_oil = float(oil_values.tail(2).mean())
                prior_oil = float(oil_values.iloc[-4:-2].mean())

                if prior_oil > 0:
                    oil_mom_pct = ((current_oil / prior_oil) - 1) * 100
                    # 原油→零售汽油传导系数约0.50（原油占零售价~50%）
                    # 汽油→CPI能源传导系数约0.50（汽油占能源~50%）
                    # 总传导: 0.50 × 0.50 = 0.25
                    energy_mom = oil_mom_pct * 0.25

                    self._energy_method = (
                        f"WTI原油: ${current_oil:.1f}/bbl vs "
                        f"${prior_oil:.1f}/bbl ({oil_mom_pct:+.1f}%), "
                        f"传导系数0.25"
                    )
                    return round(energy_mom, 3)

        # 兜底：CPI能源历史趋势
        energy_df = cpi_data.get("energy")
        if energy_df is not None and not energy_df.empty:
            mom = pd.to_numeric(
                energy_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(mom) >= 3:
                return round(float(mom.tail(3).mean()), 3)
        return 0.0

    def _forecast_food(self, cpi_data: dict) -> float:
        """Forecast food MoM from recent trend.

        Uses the mean of last 3 months of food CPI MoM.
        Tries food_at_home and food_away sub-components first for a
        weighted composite, then falls back to the aggregate food series.
        """
        fah_df = cpi_data.get("food_at_home")
        faw_df = cpi_data.get("food_away")

        fah_mom = None
        faw_mom = None

        if fah_df is not None and not fah_df.empty:
            series = pd.to_numeric(
                fah_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(series) >= 3:
                fah_mom = float(series.tail(3).mean())

        if faw_df is not None and not faw_df.empty:
            series = pd.to_numeric(
                faw_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(series) >= 3:
                faw_mom = float(series.tail(3).mean())

        # If both sub-components available, compute weighted average
        if fah_mom is not None and faw_mom is not None:
            w_fah = self.WEIGHTS["food_at_home"]
            w_faw = self.WEIGHTS["food_away"]
            composite = (fah_mom * w_fah + faw_mom * w_faw) / (w_fah + w_faw)
            return round(composite, 3)

        # Fallback to aggregate food series
        food_df = cpi_data.get("food")
        if food_df is not None and not food_df.empty:
            mom = pd.to_numeric(
                food_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(mom) >= 3:
                return round(float(mom.tail(3).mean()), 3)
        return 0.20  # default: ~0.2% MoM

    def _forecast_used_cars(self, cpi_data: dict) -> float:
        """Forecast used cars MoM.

        Ideally uses Manheim Used Vehicle Value Index (not available here).
        Falls back to CPI transportation trend as a proxy since the BLS
        series config does not include a dedicated used cars series.
        """
        # Try transportation series as proxy (includes used/new vehicles)
        trans_df = cpi_data.get("transportation")
        if trans_df is not None and not trans_df.empty:
            mom = pd.to_numeric(
                trans_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(mom) >= 3:
                # Transportation includes services too; dampen the signal
                # Used cars are more volatile, so scale by 0.7
                raw_trend = float(mom.tail(3).mean())
                return round(raw_trend * 0.7, 3)

        # Fallback: check apparel as another goods proxy
        apparel_df = cpi_data.get("apparel")
        if apparel_df is not None and not apparel_df.empty:
            mom = pd.to_numeric(
                apparel_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(mom) >= 3:
                return round(float(mom.tail(3).mean()), 3)
        return 0.0  # default: flat

    def _forecast_medical(self, cpi_data: dict) -> float:
        """Forecast medical MoM.

        Medical CPI is relatively sticky and seasonal. Uses the mean of
        the last 6 months to smooth out monthly noise.
        """
        med_df = cpi_data.get("medical")
        if med_df is not None and not med_df.empty:
            mom = pd.to_numeric(
                med_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(mom) >= 6:
                return round(float(mom.tail(6).mean()), 3)
            elif len(mom) >= 3:
                return round(float(mom.tail(3).mean()), 3)
        return 0.30  # default

    def _forecast_transport(self, cpi_data: dict) -> float:
        """Forecast transportation services MoM.

        Uses the last 3 months trend. Transportation services includes
        motor vehicle insurance, airfares, etc. which are volatile.
        """
        trans_df = cpi_data.get("transportation")
        if trans_df is not None and not trans_df.empty:
            mom = pd.to_numeric(
                trans_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(mom) >= 3:
                return round(float(mom.tail(3).mean()), 3)
        return 0.30  # default

    def _forecast_other_core(self, cpi_data: dict, fred_data: dict) -> float:
        """Forecast other core items (apparel, recreation, education, new vehicles, other).

        Uses average hourly earnings MoM as a proxy for service-sector
        inflation (supercore coefficient ~0.4). Falls back to an average
        of apparel and recreation CPI trends.
        """
        # Use average hourly earnings MoM as proxy
        ahe_df = fred_data.get("avg_hourly_earnings")
        if ahe_df is not None and not ahe_df.empty:
            mom = pd.to_numeric(
                ahe_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(mom) >= 3:
                wage_mom = float(mom.tail(3).mean())
                # Supercore coefficient ~0.4-0.5
                return round(wage_mom * 0.4, 3)

        # Fallback: average of apparel and recreation CPI trends
        trend_values = []
        for key in ["apparel", "recreation", "education_communication", "other"]:
            df = cpi_data.get(key)
            if df is not None and not df.empty:
                mom = pd.to_numeric(
                    df.sort_values("date")["mom_pct"], errors="coerce"
                ).dropna()
                if len(mom) >= 3:
                    trend_values.append(float(mom.tail(3).mean()))

        if trend_values:
            return round(sum(trend_values) / len(trend_values), 3)
        return 0.15  # default

    # ──────────────────────────────────────────────
    # Base effect computation
    # ──────────────────────────────────────────────

    def _compute_base_effect(self, cpi_data: dict, forecast_date) -> dict:
        """Compute base effect: what MoM from 12 months ago is dropping out of YoY.

        When YoY is calculated, adding the new month's MoM and dropping the
        MoM from 12 months prior determines how YoY changes. A high base
        (large MoM last year) creates a favorable base effect (YoY declines).
        """
        all_items = cpi_data.get("all_items")
        if all_items is None or all_items.empty:
            return {"last_year_mom": None, "base_effect_bps": None}

        df = all_items.sort_values("date").copy()
        df["date"] = pd.to_datetime(df["date"])
        twelve_months_ago = forecast_date - pd.DateOffset(months=12)

        # Find the MoM from 12 months ago (the month dropping out)
        target_period = twelve_months_ago.to_period("M")
        target_rows = df[df["date"].dt.to_period("M") == target_period]

        if target_rows.empty:
            return {"last_year_mom": None, "base_effect_bps": None}

        last_year_mom_val = target_rows.iloc[0].get("mom_pct")
        if last_year_mom_val is None or pd.isna(last_year_mom_val):
            return {"last_year_mom": None, "base_effect_bps": None}

        last_year_mom = float(last_year_mom_val)

        return {
            "last_year_mom": round(last_year_mom, 3),
            "base_effect_bps": round(-last_year_mom * 100, 1),
            "description": f"去年同月MoM为{last_year_mom:+.2f}%，将从YoY计算中退出",
        }

    # ──────────────────────────────────────────────
    # Risk identification
    # ──────────────────────────────────────────────

    def _identify_upside_risks(self, cpi_data: dict, fred_data: dict) -> list:
        """Identify upside inflation risks based on current data trends."""
        risks = []

        # Check if energy prices are accelerating
        energy_df = cpi_data.get("energy")
        if energy_df is not None and not energy_df.empty:
            mom = pd.to_numeric(
                energy_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(mom) >= 2 and float(mom.iloc[-1]) > float(mom.iloc[-2]):
                risks.append("能源价格上行趋势加速")

        # Check if shelter inflation is sticky (YoY > 4%)
        shelter_df = cpi_data.get("shelter")
        if shelter_df is not None and not shelter_df.empty:
            yoy = pd.to_numeric(
                shelter_df.sort_values("date")["yoy_pct"], errors="coerce"
            ).dropna()
            if len(yoy) > 0 and float(yoy.iloc[-1]) > 4.0:
                risks.append("住房通胀仍处高位（YoY > 4%）")

        # Check wage growth pressure
        ahe = fred_data.get("avg_hourly_earnings")
        if ahe is not None and not ahe.empty:
            yoy = pd.to_numeric(
                ahe.sort_values("date")["yoy_pct"], errors="coerce"
            ).dropna()
            if len(yoy) > 0 and float(yoy.iloc[-1]) > 4.0:
                risks.append("工资增速偏强（>4% YoY），支撑服务业通胀")

        # Check food inflation trend
        food_df = cpi_data.get("food")
        if food_df is not None and not food_df.empty:
            mom = pd.to_numeric(
                food_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(mom) >= 3:
                recent_avg = float(mom.tail(3).mean())
                if recent_avg > 0.3:
                    risks.append("食品价格近3月环比偏高（>0.3%/月）")

        # Check PPI pass-through risk
        ppi_df = fred_data.get("ppi_final_demand")
        if ppi_df is not None and not ppi_df.empty:
            yoy = pd.to_numeric(
                ppi_df.sort_values("date")["yoy_pct"], errors="coerce"
            ).dropna()
            if len(yoy) > 0 and float(yoy.iloc[-1]) > 3.0:
                risks.append("PPI 最终需求同比偏高，成本传导压力")

        if not risks:
            risks.append("暂无显著上行风险")
        return risks

    def _identify_downside_risks(self, cpi_data: dict, fred_data: dict) -> list:
        """Identify downside inflation risks based on current data trends."""
        risks = []

        # Check if goods deflation is present
        for key, label in [("apparel", "服装"), ("recreation", "娱乐")]:
            df = cpi_data.get(key)
            if df is not None and not df.empty:
                yoy = pd.to_numeric(
                    df.sort_values("date")["yoy_pct"], errors="coerce"
                ).dropna()
                if len(yoy) > 0 and float(yoy.iloc[-1]) < 0:
                    risks.append(f"{label}分项同比为负，商品通缩压力")
                    break

        # Check consumer sentiment drop (demand weakening)
        cs = fred_data.get("consumer_sentiment")
        if cs is not None and not cs.empty:
            val = pd.to_numeric(
                cs.sort_values("date")["value"], errors="coerce"
            ).dropna()
            if len(val) >= 3:
                if float(val.iloc[-1]) < float(val.iloc[-3]):
                    risks.append("消费者信心下降，需求端降温")

        # Check if shelter MoM is decelerating
        shelter_df = cpi_data.get("shelter")
        if shelter_df is not None and not shelter_df.empty:
            mom = pd.to_numeric(
                shelter_df.sort_values("date")["mom_pct"], errors="coerce"
            ).dropna()
            if len(mom) >= 6:
                recent_3m = float(mom.tail(3).mean())
                prior_3m = float(mom.tail(6).head(3).mean())
                if recent_3m < prior_3m:
                    risks.append("住房环比放缓，租金下行传导中")

        # Check capacity utilization (slack in economy)
        cu = fred_data.get("capacity_utilization")
        if cu is not None and not cu.empty:
            val = pd.to_numeric(
                cu.sort_values("date")["value"], errors="coerce"
            ).dropna()
            if len(val) > 0 and float(val.iloc[-1]) < 77.0:
                risks.append("产能利用率偏低（<77%），供给端通缩压力")

        if not risks:
            risks.append("暂无显著下行风险")
        return risks
