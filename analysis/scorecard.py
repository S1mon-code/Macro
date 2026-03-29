"""多因子资产评分卡引擎

根据宏观因子对 11 类资产进行加权打分，
每个因子 -2 ~ +2，加权归一化到 -1 ~ +1，
输出信号（强烈看多/偏多/中性/偏空/强烈看空）、颜色及因子明细。
"""

import pandas as pd
import numpy as np


class AssetScorecard:
    """多因子资产评分卡"""

    # Asset factor configurations
    # Each: (data_key, column, name, scoring_func_name, weight)
    ASSET_CONFIGS = {
        "sp500": {
            "name": "S&P 500",
            "factors": [
                ("regime_growth", None, "增长象限", "_score_regime_growth", 0.20),
                ("yield_spread", "value", "收益率曲线", "_score_yield_curve", 0.10),
                ("hy_spread", "value", "高收益利差", "_score_hy_spread", 0.10),
                ("fed_direction", None, "美联储方向", "_score_fed_direction", 0.15),
                ("lei", "value", "LEI 领先指标", "_score_lei_direction", 0.10),
                ("consumer_sentiment", "value", "消费者信心", "_score_zscore_positive", 0.10),
                ("sahm_gap", None, "Sahm Rule", "_score_sahm", 0.15),
                ("hy_spread", "value", "信用利差方向", "_score_spread_direction", 0.10),
            ],
        },
        "nasdaq": {
            "name": "纳斯达克",
            "factors": [
                ("regime_growth", None, "增长象限", "_score_regime_growth", 0.15),
                ("yield_spread", "value", "收益率曲线", "_score_yield_curve", 0.10),
                ("hy_spread", "value", "高收益利差", "_score_hy_spread", 0.10),
                ("fed_direction", None, "美联储方向", "_score_fed_direction", 0.20),
                ("lei", "value", "LEI", "_score_lei_direction", 0.10),
                ("consumer_sentiment", "value", "消费者信心", "_score_zscore_positive", 0.10),
                ("sahm_gap", None, "Sahm Rule", "_score_sahm", 0.15),
                ("treasury_10y", "value", "实际利率", "_score_real_rate_equity", 0.10),
            ],
        },
        "dow": {
            "name": "道琼斯",
            "factors": [
                ("regime_growth", None, "增长象限", "_score_regime_growth", 0.25),
                ("yield_spread", "value", "收益率曲线", "_score_yield_curve", 0.10),
                ("hy_spread", "value", "高收益利差", "_score_hy_spread", 0.10),
                ("fed_direction", None, "美联储方向", "_score_fed_direction", 0.15),
                ("lei", "value", "LEI", "_score_lei_direction", 0.10),
                ("consumer_sentiment", "value", "消费者信心", "_score_zscore_positive", 0.10),
                ("sahm_gap", None, "Sahm Rule", "_score_sahm", 0.10),
                ("capacity_utilization", "value", "产能利用率", "_score_zscore_positive", 0.10),
            ],
        },
        "shanghai": {
            "name": "上证指数",
            "factors": [
                ("cn_regime_growth", None, "中国增长象限", "_score_regime_growth", 0.20),
                ("credit_pulse", None, "信贷脉冲", "_score_credit_pulse", 0.25),
                ("pmi_manufacturing", "value", "制造业 PMI", "_score_pmi", 0.10),
                ("m1_m2_gap", None, "M1-M2 剪刀差", "_score_m1m2", 0.10),
                ("lpr_direction", None, "LPR 方向", "_score_lpr_direction", 0.15),
                ("us_transmission", None, "美国传导", "_score_us_transmission", 0.10),
                ("shibor_on", "value", "Shibor 隔夜", "_score_shibor_inverted", 0.10),
            ],
        },
        "chinext": {
            "name": "创业板",
            "factors": [
                ("cn_regime_growth", None, "中国增长象限", "_score_regime_growth", 0.15),
                ("credit_pulse", None, "信贷脉冲", "_score_credit_pulse", 0.25),
                ("pmi_manufacturing", "value", "PMI", "_score_pmi", 0.10),
                ("m1_m2_gap", None, "M1-M2 剪刀差", "_score_m1m2", 0.15),
                ("lpr_direction", None, "LPR 方向", "_score_lpr_direction", 0.15),
                ("us_transmission", None, "美国传导", "_score_us_transmission", 0.10),
                ("shibor_on", "value", "流动性", "_score_shibor_inverted", 0.10),
            ],
        },
        "hangseng": {
            "name": "恒生指数",
            "factors": [
                ("cn_regime_growth", None, "中国增长象限", "_score_regime_growth", 0.20),
                ("credit_pulse", None, "信贷脉冲", "_score_credit_pulse", 0.20),
                ("fed_direction", None, "美联储方向(双beta)", "_score_fed_direction", 0.20),
                ("pmi_manufacturing", "value", "PMI", "_score_pmi", 0.10),
                ("treasury_10y", "value", "美国10Y利率", "_score_real_rate_equity", 0.15),
                ("us_transmission", None, "美国传导", "_score_us_transmission", 0.15),
            ],
        },
        "hstech": {
            "name": "恒生科技",
            "factors": [
                ("cn_regime_growth", None, "中国增长", "_score_regime_growth", 0.15),
                ("credit_pulse", None, "信贷脉冲", "_score_credit_pulse", 0.15),
                ("fed_direction", None, "美联储方向", "_score_fed_direction", 0.25),
                ("pmi_manufacturing", "value", "PMI", "_score_pmi", 0.10),
                ("treasury_10y", "value", "美国利率", "_score_real_rate_equity", 0.20),
                ("us_transmission", None, "美国传导", "_score_us_transmission", 0.15),
            ],
        },
        "gold": {
            "name": "黄金",
            "factors": [
                ("treasury_10y", "value", "实际利率(反向)", "_score_real_rate_gold", 0.25),
                ("fed_direction", None, "美联储方向", "_score_fed_direction", 0.15),
                ("recession_prob", None, "衰退概率", "_score_recession_bullish", 0.15),
                ("regime_inflation", None, "通胀水平", "_score_inflation_gold", 0.15),
                ("hy_spread", "value", "避险需求", "_score_hy_spread_gold", 0.10),
                ("regime_growth", None, "增长放缓", "_score_growth_inverse", 0.10),
                ("consumer_sentiment", "value", "不确定性", "_score_uncertainty", 0.10),
            ],
        },
        "silver": {
            "name": "白银",
            "factors": [
                ("treasury_10y", "value", "实际利率(反向)", "_score_real_rate_gold", 0.20),
                ("fed_direction", None, "美联储方向", "_score_fed_direction", 0.15),
                ("recession_prob", None, "衰退概率", "_score_recession_bullish", 0.10),
                ("regime_inflation", None, "通胀", "_score_inflation_gold", 0.10),
                ("regime_growth", None, "工业需求(增长)", "_score_regime_growth", 0.15),
                ("pmi_manufacturing", "value", "PMI(工业)", "_score_pmi", 0.15),
                ("hy_spread", "value", "避险", "_score_hy_spread_gold", 0.15),
            ],
        },
        "dollar": {
            "name": "美元指数",
            "factors": [
                ("regime_growth", None, "美国增长优势", "_score_regime_growth", 0.25),
                ("fed_direction", None, "美联储方向", "_score_fed_direction_dollar", 0.25),
                ("yield_spread", "value", "利差", "_score_yield_curve", 0.15),
                ("treasury_10y", "value", "10Y利率水平", "_score_zscore_positive", 0.15),
                ("regime_inflation", None, "通胀", "_score_inflation_dollar", 0.10),
                ("consumer_sentiment", "value", "经济动能", "_score_zscore_positive", 0.10),
            ],
        },
        "crude_oil": {
            "name": "原油",
            "factors": [
                ("regime_growth", None, "全球增长", "_score_regime_growth", 0.30),
                ("pmi_manufacturing", "value", "制造业PMI", "_score_pmi", 0.15),
                ("cn_regime_growth", None, "中国需求", "_score_regime_growth", 0.20),
                ("lei", "value", "LEI", "_score_lei_direction", 0.15),
                ("regime_inflation", None, "通胀环境", "_score_inflation_gold", 0.10),
                ("hy_spread", "value", "风险偏好", "_score_hy_spread", 0.10),
            ],
        },
    }

    def __init__(self):
        # These will be set by score_all() from external analysis results
        self.regime_us = None
        self.regime_china = None
        self.recession_prob = 0
        self.credit_pulse_pct = 0
        self.m1_m2_gap = 0
        self.sahm_gap = 0
        self.fed_3m_change = 0
        self.lpr_3m_change = 0

    def score_all(
        self,
        us_data: dict,
        china_data: dict,
        regime_us: dict,
        regime_china: dict,
        recession_data: dict,
        credit_pulse: dict,
        labor_data: dict,
    ) -> dict:
        """
        Score all assets.

        Parameters
        ----------
        us_data : dict
            US macro data {indicator_key: DataFrame}
        china_data : dict
            China macro data {indicator_key: DataFrame}
        regime_us : dict
            US regime result from MacroRegime.assess_us()
        regime_china : dict
            China regime result from MacroRegime.assess_china()
        recession_data : dict
            Recession tracker result (composite_probability output)
        credit_pulse : dict
            China credit pulse data {latest_pulse, m1_m2_gap, ...}
        labor_data : dict
            Labor market data {sahm_rule: {gap, ...}, ...}

        Returns
        -------
        dict
            {asset_key: {name, score, signal, color, factors: [...]}}
        """
        # Store context for scoring functions
        self.regime_us = regime_us or {}
        self.regime_china = regime_china or {}
        self.recession_prob = (
            recession_data.get("probability", 0) if recession_data else 0
        )
        self.credit_pulse_pct = (
            credit_pulse.get("latest_pulse", 0) if credit_pulse else 0
        )
        self.m1_m2_gap = credit_pulse.get("m1_m2_gap", 0) if credit_pulse else 0
        sahm = labor_data.get("sahm_rule", {}) if labor_data else {}
        self.sahm_gap = sahm.get("gap", 0) if sahm else 0

        # Combine all data for lookups
        all_data = {}
        if us_data:
            all_data.update(us_data)
        if china_data:
            all_data.update(china_data)

        # Compute fed direction: 3-month change in fed_funds_rate
        self.fed_3m_change = self._compute_direction(
            us_data.get("fed_funds_rate") if us_data else None,
            "value",
            lookback=3,
        )

        # LPR direction: 3-month change
        self.lpr_3m_change = self._compute_direction(
            china_data.get("lpr_1y") if china_data else None,
            "value",
            lookback=3,
        )

        results = {}
        for asset_key, config in self.ASSET_CONFIGS.items():
            result = self._score_asset(asset_key, config, all_data)
            results[asset_key] = result

        return results

    # ── Core scoring pipeline ──────────────────────────────────────

    def _score_asset(self, asset_key: str, config: dict, data: dict) -> dict:
        """Score a single asset across all its configured factors."""
        factors = []
        weighted_sum = 0.0
        total_weight = 0.0

        for data_key, col, name, score_func_name, weight in config["factors"]:
            score_func = getattr(self, score_func_name, None)
            if score_func is None:
                continue

            # Get the raw value for display
            raw_value = self._get_latest_value(data, data_key, col)

            # Call scoring function
            try:
                score = score_func(data, data_key, col)
            except Exception:
                score = 0

            # Clip to [-2, 2]
            score = max(-2, min(2, score))

            factors.append(
                {
                    "name": name,
                    "raw_value": round(raw_value, 4) if raw_value is not None else None,
                    "score": score,
                    "weight": weight,
                    "weighted_score": round(score * weight, 4),
                }
            )
            weighted_sum += score * weight
            total_weight += weight

        # Normalize to -1 ~ +1 (max possible is 2, so divide by 2)
        if total_weight > 0:
            raw_score = weighted_sum / total_weight
        else:
            raw_score = 0.0
        normalized_score = raw_score / 2.0  # since max factor score is 2
        normalized_score = max(-1.0, min(1.0, normalized_score))

        signal, color = self._interpret_score(normalized_score)

        return {
            "name": config["name"],
            "score": round(normalized_score, 3),
            "signal": signal,
            "color": color,
            "factors": factors,
        }

    @staticmethod
    def _interpret_score(score: float) -> tuple:
        """Map normalized score to signal text and color."""
        if score > 0.6:
            return ("强烈看多", "green")
        if score > 0.2:
            return ("偏多", "green")
        if score > -0.2:
            return ("中性", "yellow")
        if score > -0.6:
            return ("偏空", "red")
        return ("强烈看空", "red")

    # ── Helper utilities ───────────────────────────────────────────

    @staticmethod
    def _get_latest_value(data: dict, key: str, col: str | None) -> float | None:
        """Safely extract the latest numeric value from a data dict."""
        if col is None or key not in data:
            return None
        df = data[key]
        if not isinstance(df, pd.DataFrame) or df.empty:
            return None
        if col not in df.columns:
            return None
        val = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(val) == 0:
            return None
        return float(val.iloc[-1])

    @staticmethod
    def _get_series(data: dict, key: str, col: str) -> pd.Series | None:
        """Extract a clean numeric series from data dict. Returns None on failure."""
        df = data.get(key)
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return None
        if col not in df.columns:
            return None
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(series) == 0:
            return None
        return series

    @staticmethod
    def _compute_direction(
        df: pd.DataFrame | None, col: str, lookback: int = 3
    ) -> float:
        """Compute change over `lookback` periods for a DataFrame column."""
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return 0.0
        if col not in df.columns:
            return 0.0
        vals = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(vals) < lookback:
            return 0.0
        return float(vals.iloc[-1]) - float(vals.iloc[-lookback])

    # ── Scoring functions ──────────────────────────────────────────
    # Each takes (data, data_key, col) and returns int in [-2, +2]

    def _score_regime_growth(self, data, key, col):
        """Score based on growth regime score from MacroRegime."""
        if "cn_" in key:
            g = self.regime_china.get("growth_score", 0)
        else:
            g = self.regime_us.get("growth_score", 0)
        if g > 0.5:
            return 2
        if g > 0:
            return 1
        if g > -0.5:
            return -1
        return -2

    def _score_yield_curve(self, data, key, col):
        """10Y-2Y spread: positive = healthy, inverted = danger."""
        series = self._get_series(data, key, col)
        if series is None:
            return 0
        v = float(series.iloc[-1])
        if v > 1.0:
            return 2
        if v > 0:
            return 1
        if v > -0.5:
            return -1
        return -2

    def _score_hy_spread(self, data, key, col):
        """HY credit spread: lower is better for equities."""
        series = self._get_series(data, key, col)
        if series is None:
            return 0
        v = float(series.iloc[-1])
        if v < 3:
            return 2
        if v < 4:
            return 1
        if v < 6:
            return -1
        return -2

    def _score_fed_direction(self, data, key, col):
        """Fed funds rate 3-month change. Cuts = bullish for equities/gold."""
        chg = self.fed_3m_change
        if chg < -0.5:
            return 2  # aggressive cuts
        if chg < -0.1:
            return 1  # moderate cuts
        if chg < 0.1:
            return 0  # on hold
        if chg < 0.5:
            return -1  # moderate hikes
        return -2  # aggressive hikes

    def _score_fed_direction_dollar(self, data, key, col):
        """Fed direction for dollar: hikes = bullish (opposite of equities)."""
        return -self._score_fed_direction(data, key, col)

    def _score_lei_direction(self, data, key, col):
        """LEI direction: 6-month percent change."""
        series = self._get_series(data, key, col)
        if series is None or len(series) < 6:
            return 0
        current = float(series.iloc[-1])
        six_ago = float(series.iloc[-6])
        if six_ago == 0:
            return 0
        pct = ((current - six_ago) / abs(six_ago)) * 100
        if pct > 2:
            return 2
        if pct > 0:
            return 1
        if pct > -2:
            return -1
        return -2

    def _score_sahm(self, data, key, col):
        """Sahm Rule gap: lower is better (no recession signal)."""
        gap = self.sahm_gap
        if gap < 0.2:
            return 2
        if gap < 0.3:
            return 1
        if gap < 0.4:
            return -1
        return -2

    def _score_pmi(self, data, key, col):
        """PMI level scoring: above 50 = expansion."""
        series = self._get_series(data, key, col)
        if series is None:
            return 0
        v = float(series.iloc[-1])
        if v > 55:
            return 2
        if v > 52:
            return 1
        if v > 50:
            return 0
        if v > 48:
            return -1
        return -2

    def _score_credit_pulse(self, data, key, col):
        """China credit pulse: positive = expansionary."""
        p = self.credit_pulse_pct
        if p > 15:
            return 2
        if p > 5:
            return 1
        if p > 0:
            return 0
        if p > -5:
            return -1
        return -2

    def _score_m1m2(self, data, key, col):
        """M1-M2 gap: positive = liquidity flowing into economy = bullish."""
        gap = self.m1_m2_gap
        if gap > 2:
            return 2
        if gap > 0:
            return 1
        if gap > -2:
            return -1
        return -2

    def _score_lpr_direction(self, data, key, col):
        """LPR direction: cuts = bullish for Chinese assets."""
        chg = self.lpr_3m_change
        if chg < -0.1:
            return 2  # meaningful cut
        if chg < 0:
            return 1  # small cut
        if chg == 0:
            return 0  # hold
        return -1  # hike

    def _score_us_transmission(self, data, key, col):
        """US policy effect on China/HK: easing + growth = positive spillover."""
        g = self.regime_us.get("growth_score", 0)
        fed = self.fed_3m_change
        if fed < -0.1 and g > 0:
            return 1  # US easing + growth = positive for China
        if fed > 0.1 and g < 0:
            return -1  # US tightening + slowdown = negative
        return 0

    def _score_shibor_inverted(self, data, key, col):
        """Lower Shibor = more liquidity = bullish for Chinese equities."""
        series = self._get_series(data, key, col)
        if series is None or len(series) < 12:
            return 0
        current = float(series.iloc[-1])
        window = series.tail(60)
        mean = float(window.mean())
        if mean == 0:
            return 0
        if current < mean * 0.8:
            return 2
        if current < mean:
            return 1
        if current < mean * 1.2:
            return -1
        return -2

    def _score_real_rate_equity(self, data, key, col):
        """Real rate for equities: rising rates = headwind, falling = tailwind."""
        series = self._get_series(data, key, col)
        if series is None or len(series) < 3:
            return 0
        chg_3m = float(series.iloc[-1]) - float(series.iloc[-3])
        if chg_3m < -0.5:
            return 2  # rates falling fast
        if chg_3m < -0.1:
            return 1  # rates falling
        if chg_3m < 0.1:
            return 0  # stable
        if chg_3m < 0.5:
            return -1  # rates rising
        return -2  # rates rising fast

    def _score_real_rate_gold(self, data, key, col):
        """Real rate for gold: INVERTED — falling rates = bullish for gold."""
        return -self._score_real_rate_equity(data, key, col)

    def _score_recession_bullish(self, data, key, col):
        """Higher recession probability = bullish for safe havens (gold/silver)."""
        p = self.recession_prob
        if p > 50:
            return 2
        if p > 30:
            return 1
        if p > 15:
            return -1
        return -2

    def _score_inflation_gold(self, data, key, col):
        """Higher inflation = bullish for gold as inflation hedge."""
        inf = self.regime_us.get("inflation_score", 0)
        if inf > 0.5:
            return 2
        if inf > 0:
            return 1
        if inf > -0.5:
            return -1
        return -2

    def _score_inflation_dollar(self, data, key, col):
        """Inflation + hawkish Fed = dollar bullish; disinflation + dovish = bearish."""
        inf = self.regime_us.get("inflation_score", 0)
        fed = self.fed_3m_change
        if inf > 0 and fed > 0:
            return 1  # inflation + hawkish = dollar up
        if inf < 0 and fed < 0:
            return -1  # disinflation + dovish = dollar down
        return 0

    def _score_hy_spread_gold(self, data, key, col):
        """Wider HY spread = more fear = bullish for gold (flight to safety)."""
        series = self._get_series(data, key, col)
        if series is None:
            return 0
        v = float(series.iloc[-1])
        if v > 6:
            return 2
        if v > 4:
            return 1
        if v > 3:
            return -1
        return -2

    def _score_growth_inverse(self, data, key, col):
        """Inverse growth: slowdown = bullish for gold."""
        return -self._score_regime_growth(data, key, col)

    def _score_uncertainty(self, data, key, col):
        """Lower consumer sentiment = more uncertainty = bullish for gold."""
        series = self._get_series(data, key, col)
        if series is None or len(series) < 12:
            return 0
        current = float(series.iloc[-1])
        window = series.tail(60)
        std = float(window.std())
        if std == 0:
            return 0
        z = (current - float(window.mean())) / std
        # Inverted: low sentiment = bullish for gold
        if z < -1:
            return 2
        if z < -0.5:
            return 1
        if z < 0.5:
            return -1
        return -2

    def _score_zscore_positive(self, data, key, col):
        """Generic z-score: higher value = more bullish."""
        series = self._get_series(data, key, col)
        if series is None or len(series) < 12:
            return 0
        current = float(series.iloc[-1])
        window = series.tail(60)
        mean = float(window.mean())
        std = float(window.std())
        if std == 0:
            return 0
        z = (current - mean) / std
        if z > 1:
            return 2
        if z > 0.5:
            return 1
        if z > -0.5:
            return 0
        if z > -1:
            return -1
        return -2

    def _score_spread_direction(self, data, key, col):
        """Credit spread direction: tightening = bullish for equities."""
        series = self._get_series(data, key, col)
        if series is None or len(series) < 3:
            return 0
        chg = float(series.iloc[-1]) - float(series.iloc[-3])
        if chg < -0.5:
            return 2  # tightening fast
        if chg < 0:
            return 1  # tightening
        if chg < 0.5:
            return -1  # widening
        return -2  # widening fast
