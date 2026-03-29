"""全球宏观经济数据分析报告生成器

拉取美国（BLS CPI + FRED）和中国（AKShare）宏观数据，
生成综合 HTML 交互式报告。
"""

import argparse
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
load_dotenv()  # 加载 .env 文件中的 API keys


def _load_consensus() -> dict:
    """Load consensus forecasts from config/consensus.yaml"""
    try:
        with open("config/consensus.yaml", "r") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}

import plotly.io as pio
from jinja2 import Environment, FileSystemLoader

from data.fetchers.bls_fetcher import BLSFetcher
from data.fetchers.fred_fetcher import FREDFetcher
from data.fetchers.akshare_fetcher import AKShareFetcher
from data.fetchers.polymarket_fetcher import PolymarketFetcher
from data.cache.db import CacheDB
from charts.cpi_charts import CPIChartBuilder
from charts.macro_charts import MacroChartBuilder

from analysis.cycle import CycleAssessor
from analysis.recession import RecessionTracker
from analysis.inflation import InflationAnalyzer
from analysis.labor import LaborDashboard
from analysis.china_credit import ChinaCreditPulse
from analysis.context import HistoricalContext
from analysis.regime import MacroRegime
from analysis.scorecard import AssetScorecard
from analysis.cpi_forecast import CPIForecaster
from analysis.macro_forecast import MacroForecastMatrix


def _chart_html(fig) -> str:
    """将 Plotly Figure 转为嵌入 HTML 片段"""
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _build_summary(
    data: dict,
    keys: list[tuple[str, str]],
    labels: dict,
    rate_keys: set | None = None,
) -> list[dict]:
    """构建摘要表格数据
    keys: [(data_key, display_type), ...]
       display_type: "yoy_pct" 用同比, "value" 直接显示值
    rate_keys: 比率类指标 key 集合（同比用差值 pp 而非 %）
    """
    if rate_keys is None:
        rate_keys = set()
    summary = []
    for key, display_type in keys:
        df = data.get(key)
        if df is None or df.empty:
            continue
        # 决定展示哪一列作为同比
        yoy_col = "yoy_pct"
        if yoy_col not in df.columns:
            continue
        df_valid = df.dropna(subset=[yoy_col])
        if df_valid.empty:
            # 尝试不过滤
            df_valid = df
        latest = df_valid.iloc[-1]
        date = latest.get("date")
        if date is not None:
            period = date.strftime("%Y年%m月") if hasattr(date, "strftime") else str(date)
        else:
            period = "N/A"

        value = float(latest.get("value", 0)) if latest.get("value") is not None else 0
        yoy = float(latest[yoy_col]) if latest.get(yoy_col) is not None else 0
        is_rate = key in rate_keys

        # 构建历史数据（最近5年）用于点击展开
        history = []
        for _, row in df_valid.iterrows():
            d = row.get("date")
            if d is None:
                continue
            if hasattr(d, "strftime"):
                d_str = d.strftime("%Y-%m")
            else:
                d_str = str(d)[:7]
            h = {
                "date": d_str,
                "value": round(float(row.get("value", 0)), 4) if row.get("value") is not None else None,
                "yoy": round(float(row.get("yoy_pct", 0)), 4) if row.get("yoy_pct") is not None else None,
                "mom": round(float(row.get("mom_pct", 0)), 4) if row.get("mom_pct") is not None else None,
            }
            history.append(h)

        summary.append({
            "label": labels.get(key, key),
            "key": key,
            "value": value,
            "yoy": yoy,
            "period": period,
            "is_rate": is_rate,
            "unit": "pp" if is_rate else "%",
            "history": history,
        })
    return summary


def generate_macro_report(use_cache: bool = False):
    """生成全球宏观经济数据分析报告"""
    print("=" * 60)
    print("  全球宏观经济数据分析报告生成")
    print("=" * 60)

    cache = CacheDB()

    # ── 1. 拉取美国 CPI 数据 (BLS) ──
    print("\n[1/8] 拉取美国 CPI 数据 (BLS)...")
    bls = BLSFetcher()
    if use_cache:
        cpi_data = {}
        for name, sid in bls.series.items():
            df = cache.load("cpi", series_id=sid)
            if not df.empty:
                cpi_data[name] = df
        if not cpi_data:
            use_cache_cpi = False
        else:
            use_cache_cpi = True
    else:
        use_cache_cpi = False

    if not use_cache_cpi:
        cpi_data = bls.fetch_cpi_all()
        for name, df in cpi_data.items():
            if not df.empty:
                cache.save("cpi", df)
    print(f"  已获取 {len(cpi_data)} 个 CPI 分项")

    # ── 2. 拉取美国宏观数据 (FRED) ──
    print("\n[2/8] 拉取美国宏观数据 (FRED)...")
    fred = FREDFetcher()
    if use_cache:
        fred_data = {}
        for name, sid in fred.series.items():
            df = cache.load("fred_us", series_id=sid)
            if not df.empty:
                fred_data[name] = df
        if not fred_data:
            use_cache_fred = False
        else:
            use_cache_fred = True
    else:
        use_cache_fred = False

    if not use_cache_fred:
        fred_data = fred.fetch_all()
        for name, df in fred_data.items():
            if not df.empty:
                cache.save("fred_us", df)
    print(f"  已获取 {len(fred_data)} 个 FRED 指标")

    # ── 3. 拉取中国宏观数据 (AKShare) ──
    print("\n[3/8] 拉取中国宏观数据 (AKShare)...")
    ak_fetcher = AKShareFetcher()
    if use_cache:
        china_data = {}
        df_all = cache.load("china_macro")
        if not df_all.empty:
            for ind in df_all["indicator"].unique():
                china_data[ind] = df_all[df_all["indicator"] == ind].copy().reset_index(drop=True)
        if not china_data:
            use_cache_china = False
        else:
            use_cache_china = True
    else:
        use_cache_china = False

    if not use_cache_china:
        china_data = ak_fetcher.fetch_all()
        for name, df in china_data.items():
            if not df.empty:
                cache.save("china_macro", df)
    print(f"  已获取 {len(china_data)} 个中国指标")

    # ── 4. 运行分析引擎 ──
    print("\n[4/8] 运行分析引擎...")
    combined_us_data = {**cpi_data, **fred_data}

    # 经济周期评估
    cycle_assessor = CycleAssessor()
    cycle_signals = cycle_assessor.assess(combined_us_data, china_data)
    print(f"  经济周期: {len(cycle_signals)} 个信号")

    # 衰退概率追踪
    recession_tracker = RecessionTracker()
    recession_yc = recession_tracker.compute_yield_curve(combined_us_data)
    recession_sahm = recession_tracker.sahm_rule(combined_us_data.get("unemployment"))
    recession_composite = recession_tracker.composite_probability(combined_us_data)
    recession_data = {
        "yield_curve": recession_yc,
        "sahm_rule": recession_sahm,
        "composite": recession_composite,
    }
    print(f"  衰退概率: {recession_composite.get('probability', 'N/A') if recession_composite else 'N/A'}%")

    # 通胀深度分析
    inflation_analyzer = InflationAnalyzer()
    inflation_analysis = inflation_analyzer.decompose(fred_data, cpi_data)
    print(f"  通胀分析: {len(inflation_analysis)} 个维度")

    # 就业市场仪表盘
    labor_dashboard = LaborDashboard()
    labor_analysis = labor_dashboard.assess(combined_us_data)
    print(f"  就业分析: {len(labor_analysis.get('signals', []))} 个信号")

    # 中国信贷脉冲
    china_credit = ChinaCreditPulse()
    credit_pulse = china_credit.compute(china_data)
    print(f"  信贷脉冲: {credit_pulse.get('signal', 'N/A')}")

    # 历史上下文 & 百分位排名
    historical_context = HistoricalContext()
    # 计算美国关键指标的历史上下文
    us_context_keys = {
        k: combined_us_data[k]
        for k in [
            "unemployment", "fed_funds_rate", "treasury_10y", "treasury_2y",
            "yield_spread", "consumer_sentiment", "industrial_production",
            "capacity_utilization", "nonfarm_payrolls", "initial_claims",
        ]
        if k in combined_us_data
    }
    us_context = historical_context.compute_batch(us_context_keys)
    # 计算中国关键指标的历史上下文
    cn_context_keys = {
        k: china_data[k]
        for k in [
            "pmi_manufacturing", "pmi_non_manufacturing",
            "fx_reserves", "gold_reserves",
            "lpr_1y", "lpr_5y", "shibor_on", "shibor_3m",
        ]
        if k in china_data
    }
    cn_context = historical_context.compute_batch(cn_context_keys)
    context_data = {**us_context, **cn_context}
    print(f"  历史上下文: {len(context_data)} 个指标")

    # 宏观环境定位 (增长×通胀四象限)
    regime = MacroRegime()
    regime_us = regime.assess_us(combined_us_data)
    regime_china = regime.assess_china(china_data, us_regime=regime_us)
    print(f"  美国象限: {regime_us['quadrant_cn']} (增长={regime_us['growth_score']:.2f}, 通胀={regime_us['inflation_score']:.2f})")
    print(f"  中国象限: {regime_china['quadrant_cn']} (增长={regime_china['growth_score']:.2f}, 通胀={regime_china['inflation_score']:.2f})")

    # 资产评分卡
    scorecard = AssetScorecard()
    asset_scores = scorecard.score_all(
        us_data=combined_us_data,
        china_data=china_data,
        regime_us=regime_us,
        regime_china=regime_china,
        recession_data=recession_composite,
        credit_pulse=credit_pulse,
        labor_data=labor_analysis,
    )
    print(f"  资产评分: {len(asset_scores)} 个标的")

    # CPI 预测
    cpi_forecaster = CPIForecaster()
    cpi_forecast = cpi_forecaster.forecast(cpi_data, fred_data)
    if "error" not in cpi_forecast:
        print(f"  CPI 预测 ({cpi_forecast.get('forecast_month', '?')}): "
              f"Headline MoM {cpi_forecast.get('headline_mom_forecast', 0):+.3f}%, "
              f"YoY {cpi_forecast.get('headline_yoy_forecast', 0):.3f}%")
    else:
        print(f"  CPI 预测: {cpi_forecast.get('error')}")
    for key, val in asset_scores.items():
        print(f"    {val['name']}: {val['score']:+.3f} ({val['signal']})")

    # 宏观预测矩阵（前瞻）
    macro_matrix = MacroForecastMatrix()
    macro_forecasts = macro_matrix.forecast_all(combined_us_data, china_data, cpi_forecast)
    fwd_us = macro_forecasts.get("forward_regime_us", {})
    fwd_cn = macro_forecasts.get("forward_regime_china", {})
    print(f"  前瞻象限 — 美国: {fwd_us.get('quadrant_cn', 'N/A')}, 中国: {fwd_cn.get('quadrant_cn', 'N/A')}")
    print(f"  预测叙事: {macro_forecasts.get('narrative', '')[:80]}...")

    # 用前瞻数据重新打分资产
    forward_us_data = macro_forecasts.get("_forward_us_data", combined_us_data)
    forward_cn_data = macro_forecasts.get("_forward_cn_data", china_data)
    forward_scorecard = AssetScorecard()
    forward_asset_scores = forward_scorecard.score_all(
        us_data=forward_us_data,
        china_data=forward_cn_data,
        regime_us=fwd_us,
        regime_china=fwd_cn,
        recession_data=recession_composite,
        credit_pulse=credit_pulse,
        labor_data=labor_analysis,
    )
    print(f"  前瞻资产评分:")
    for key, val in forward_asset_scores.items():
        cur = asset_scores.get(key, {}).get("score", 0)
        fwd = val["score"]
        arrow = "↑" if fwd > cur + 0.05 else ("↓" if fwd < cur - 0.05 else "→")
        print(f"    {val['name']}: {cur:+.3f} → {fwd:+.3f} {arrow} ({val['signal']})")

    # ── Polymarket 预测市场数据 ──
    # Polymarket 预测市场数据
    print("\n  获取 Polymarket 预测市场数据...")
    try:
        poly = PolymarketFetcher()
        polymarket_data = poly.fetch_all()
        print(f"  Polymarket: {len(polymarket_data)} 个市场")
        for key, mkt in polymarket_data.items():
            print(f"    {mkt['summary']}")
    except Exception as e:
        print(f"  Polymarket: 获取失败 ({e})")
        polymarket_data = {}

    # ── 共识预测数据 ──
    consensus = _load_consensus()
    print(f"  共识数据: 更新于 {consensus.get('last_updated', 'N/A')}")

    # ── 5. 构建所有标签映射 ──
    all_labels = {}
    all_labels.update(bls.labels)
    all_labels.update(fred.labels)
    # 新增 FRED 指标标签
    extra_labels = {
        "cpi_all_urban": "CPI-U 指数", "core_cpi_fred": "核心 CPI 指数",
        "sticky_cpi": "粘性 CPI", "flexible_cpi": "弹性 CPI",
        "trimmed_mean_pce": "截尾均值 PCE", "median_cpi": "中位 CPI",
        "jolts_openings": "JOLTS 职位空缺", "jolts_quits": "辞职率",
        "u6_rate": "U-6 广义失业率", "prime_age_lfpr": "25-54岁参与率",
        "hy_spread": "高收益利差", "ig_spread": "投资级利差",
        "treasury_3m": "3月期国债", "lei": "LEI 领先指标",
    }
    all_labels.update(extra_labels)
    # 中国指标标签
    china_labels = {
        "gdp": "GDP", "cpi": "CPI", "ppi": "PPI",
        "pmi_manufacturing": "制造业 PMI", "pmi_non_manufacturing": "非制造业 PMI",
        "m2": "M2 货币供应", "m1": "M1 货币供应",
        "exports": "出口", "imports": "进口",
        "industrial": "工业增加值", "retail": "社会消费品零售",
        "credit": "新增人民币贷款",
        "fx_reserves": "外汇储备", "gold_reserves": "黄金储备",
        "lpr_1y": "LPR 1年期", "lpr_5y": "LPR 5年期",
        "shibor_on": "Shibor 隔夜", "shibor_3m": "Shibor 3个月",
    }
    all_labels.update(china_labels)

    # ── 6. 生成图表 ──
    print("\n[5/8] 生成分析图表...")

    # CPI 图表 (使用专用 builder)
    cpi_builder = CPIChartBuilder(cpi_data, bls.labels)
    major_cpi = ["food", "energy", "shelter", "transportation", "medical"]
    avail_cpi = [c for c in major_cpi if c in cpi_data and not cpi_data[c].empty]

    # FRED + China 图表 (使用通用 builder)
    all_data = {}
    all_data.update(cpi_data)
    all_data.update(fred_data)
    all_data.update(china_data)
    macro_builder = MacroChartBuilder(all_data, all_labels)

    # 构建报告各段
    sections = []

    # ── Section 1: 美国宏观数据 ──
    us_subsections = []

    # --- 经济周期 & 衰退概率 (INSERT BEFORE CPI) ---
    cycle_recession_charts = [
        {"title": "收益率曲线",
         "html": _chart_html(macro_builder.multi_line(
             [("treasury_10y", "value", "10年期国债"),
              ("treasury_2y", "value", "2年期国债"),
              ("treasury_3m", "value", "3月期国债")],
             title="美国国债收益率曲线 (%)", y_label="%"))},
        {"title": "LEI 走势",
         "html": _chart_html(macro_builder.line_trend(
             ["lei"], y_col="value",
             title="LEI 领先经济指标", y_label="指数"))},
        {"title": "信用利差",
         "html": _chart_html(macro_builder.multi_line(
             [("hy_spread", "value", "高收益利差"),
              ("ig_spread", "value", "投资级利差")],
             title="信用利差 (%)", y_label="%"))},
    ]
    us_subsections.append({"title": "经济周期 & 衰退概率", "charts": cycle_recession_charts})

    # --- 通胀深度分析 (REPLACES "CPI & 通胀") ---
    cpi_charts = [
        {"title": "CPI 同比趋势（总指数 vs 核心）",
         "html": _chart_html(cpi_builder.yoy_trend(["all_items", "core"]))},
        {"title": "CPI 同比趋势（主要分项）",
         "html": _chart_html(cpi_builder.yoy_trend(avail_cpi))},
        {"title": "CPI 总指数环比变化",
         "html": _chart_html(cpi_builder.mom_bar("all_items", last_n=24))},
        {"title": "CPI 各分项最新同比对比",
         "html": _chart_html(cpi_builder.components_latest_yoy(avail_cpi))},
        {"title": "CPI 指数走势",
         "html": _chart_html(cpi_builder.index_value_trend(["all_items", "core"]))},
        {"title": "多维通胀对比",
         "html": _chart_html(macro_builder.multi_line(
             [("cpi_all_urban", "yoy_pct", "CPI-U 同比"),
              ("core_cpi_fred", "yoy_pct", "核心 CPI 同比"),
              ("sticky_cpi", "value", "粘性 CPI"),
              ("trimmed_mean_pce", "value", "截尾均值 PCE"),
              ("median_cpi", "value", "中位 CPI")],
             title="多维通胀指标对比 (% YoY)", y_label="% YoY"))},
    ]
    us_subsections.append({"title": "通胀深度分析", "charts": cpi_charts})

    # 2.2 PPI & PCE
    ppi_pce_charts = [
        {"title": "PPI 生产者价格指数走势",
         "html": _chart_html(macro_builder.dual_axis(
             "ppi", y1_col="value", y2_col="yoy_pct",
             title="PPI 指数与同比变化", y1_label="指数值", y2_label="同比 (%)"))},
        {"title": "PPI 最终需求 vs 核心 PPI 同比",
         "html": _chart_html(macro_builder.multi_line(
             [("ppi_final_demand", "yoy_pct", "PPI 最终需求同比"),
              ("core_ppi", "yoy_pct", "核心 PPI 同比")],
             title="PPI 最终需求 & 核心 PPI 同比变化 (%)", y_label="同比 (%)"))},
        {"title": "PCE vs 核心 PCE 同比",
         "html": _chart_html(macro_builder.multi_line(
             [("pce", "yoy_pct", "PCE 同比"), ("core_pce", "yoy_pct", "核心 PCE 同比")],
             title="PCE 价格指数同比变化 (%)", y_label="同比 (%)"))},
    ]
    us_subsections.append({"title": "PPI & PCE", "charts": ppi_pce_charts})

    # 2.3 就业市场 (UPGRADED with new charts)
    employment_charts = [
        {"title": "失业率趋势",
         "html": _chart_html(macro_builder.multi_line(
             [("unemployment", "value", "失业率"),
              ("labor_participation", "value", "劳动参与率")],
             title="美国失业率 & 劳动参与率 (%)", y_label="%"))},
        {"title": "非农就业人数",
         "html": _chart_html(macro_builder.dual_axis(
             "nonfarm_payrolls", y1_col="value", y2_col="mom_pct",
             title="非农就业人数与环比变化", y1_label="千人", y2_label="环比 (%)"))},
        {"title": "初请失业金人数",
         "html": _chart_html(macro_builder.line_trend(
             ["initial_claims"], y_col="value",
             title="初请失业金人数（月均）", y_label="人数"))},
        {"title": "平均时薪走势",
         "html": _chart_html(macro_builder.dual_axis(
             "avg_hourly_earnings", y1_col="value", y2_col="yoy_pct",
             title="平均时薪与同比变化", y1_label="美元", y2_label="同比 (%)"))},
        {"title": "U-3 vs U-6",
         "html": _chart_html(macro_builder.multi_line(
             [("unemployment", "value", "U-3 失业率"),
              ("u6_rate", "value", "U-6 广义失业率")],
             title="U-3 vs U-6 失业率 (%)", y_label="%"))},
        {"title": "JOLTS 职位空缺 vs 辞职率",
         "html": _chart_html(macro_builder.dual_axis(
             "jolts_openings", y1_col="value", y2_col="value",
             title="JOLTS 职位空缺 vs 辞职率", y1_label="职位空缺 (千)", y2_label="辞职率 (%)"))
         if False else  # dual_axis works on single key; use multi_line for two different keys
         _chart_html(macro_builder.multi_line(
             [("jolts_openings", "value", "JOLTS 职位空缺 (千)"),
              ("jolts_quits", "value", "辞职率 (%)")],
             title="JOLTS 职位空缺 vs 辞职率", y_label=""))},
        {"title": "25-54岁 vs 总体参与率",
         "html": _chart_html(macro_builder.multi_line(
             [("prime_age_lfpr", "value", "25-54岁参与率"),
              ("labor_participation", "value", "总体劳动参与率")],
             title="25-54岁 vs 总体劳动参与率 (%)", y_label="%"))},
    ]
    us_subsections.append({"title": "就业市场", "charts": employment_charts})

    # 2.4 GDP
    gdp_charts = [
        {"title": "实际 GDP 走势",
         "html": _chart_html(macro_builder.dual_axis(
             "gdp", y1_col="value", y2_col="yoy_pct",
             title="美国实际 GDP 与同比增长", y1_label="十亿美元", y2_label="同比 (%)"))},
    ]
    us_subsections.append({"title": "GDP & 经济增长", "charts": gdp_charts})

    # 2.5 利率 & 国债收益率
    rates_charts = [
        {"title": "联邦基金利率",
         "html": _chart_html(macro_builder.line_trend(
             ["fed_funds_rate"], y_col="value",
             title="联邦基金利率 (%)", y_label="%"))},
        {"title": "10年期 vs 2年期国债收益率",
         "html": _chart_html(macro_builder.multi_line(
             [("treasury_10y", "value", "10年期国债"),
              ("treasury_2y", "value", "2年期国债")],
             title="美国国债收益率 (%)", y_label="%"))},
        {"title": "10Y-2Y 利差",
         "html": _chart_html(macro_builder.bar_chart(
             "yield_spread", y_col="value", last_n=60,
             title="10Y-2Y 国债利差 (%)"))},
    ]
    us_subsections.append({"title": "利率 & 国债收益率", "charts": rates_charts})

    # 2.6 消费 & 零售
    consumer_charts = [
        {"title": "零售销售额走势",
         "html": _chart_html(macro_builder.dual_axis(
             "retail_sales", y1_col="value", y2_col="yoy_pct",
             title="零售销售额与同比增长", y1_label="百万美元", y2_label="同比 (%)"))},
        {"title": "消费者信心指数",
         "html": _chart_html(macro_builder.line_trend(
             ["consumer_sentiment"], y_col="value",
             title="密歇根大学消费者信心指数", y_label="指数"))},
    ]
    us_subsections.append({"title": "消费 & 零售", "charts": consumer_charts})

    # 2.7 工业 & 房地产
    industry_charts = [
        {"title": "工业生产指数",
         "html": _chart_html(macro_builder.dual_axis(
             "industrial_production", y1_col="value", y2_col="yoy_pct",
             title="工业生产指数与同比变化", y1_label="指数", y2_label="同比 (%)"))},
        {"title": "新屋开工",
         "html": _chart_html(macro_builder.line_trend(
             ["housing_starts"], y_col="value",
             title="新屋开工（千套）", y_label="千套"))},
        {"title": "产能利用率",
         "html": _chart_html(macro_builder.line_trend(
             ["capacity_utilization"], y_col="value",
             title="产能利用率 (%)", y_label="%"))},
    ]
    us_subsections.append({"title": "工业 & 房地产", "charts": industry_charts})

    # 2.8 贸易 & 货币
    trade_money_charts = [
        {"title": "贸易差额走势",
         "html": _chart_html(macro_builder.dual_axis(
             "trade_balance", y1_col="value", y2_col="yoy_pct",
             title="美国贸易差额与同比变化", y1_label="百万美元", y2_label="同比 (%)"))},
        {"title": "M2 货币供应量",
         "html": _chart_html(macro_builder.dual_axis(
             "m2_money_supply", y1_col="value", y2_col="yoy_pct",
             title="M2 货币供应量与同比增长", y1_label="十亿美元", y2_label="同比 (%)"))},
    ]
    us_subsections.append({"title": "贸易 & 货币", "charts": trade_money_charts})

    sections.append({"title": "美国宏观数据", "subsections": us_subsections})

    # ── Section 2: 中国宏观数据 ──
    cn_subsections = []

    # --- 信贷脉冲 (INSERT AT TOP) ---
    # Build cn_builder with credit pulse data added
    cn_builder_data = dict(china_data)  # copy to avoid mutating original
    # Add pulse_series to cn_builder's data for bar_chart rendering
    pulse_series = credit_pulse.get("pulse_series")
    if pulse_series is not None and not pulse_series.empty:
        # Rename pulse_pct to value so bar_chart can use y_col="value"
        pulse_for_chart = pulse_series.copy()
        if "pulse_pct" in pulse_for_chart.columns:
            pulse_for_chart = pulse_for_chart.rename(columns={"pulse_pct": "value"})
        cn_builder_data["credit_pulse_series"] = pulse_for_chart

    cn_builder = MacroChartBuilder(cn_builder_data, {**china_labels, "credit_pulse_series": "信贷脉冲"})

    cn_credit_charts = []
    if pulse_series is not None and not pulse_series.empty:
        cn_credit_charts.append(
            {"title": "信贷脉冲",
             "html": _chart_html(cn_builder.bar_chart(
                 "credit_pulse_series", y_col="value", last_n=36,
                 title="中国信贷脉冲 (12月滚动贷款同比变化 %)"))}
        )
    cn_subsections.append({"title": "信贷脉冲", "charts": cn_credit_charts})

    # 3.1 GDP
    cn_gdp_charts = [
        {"title": "中国 GDP 走势",
         "html": _chart_html(cn_builder.dual_axis(
             "gdp" if "gdp" not in cpi_data else "cn_gdp",
             y1_col="value", y2_col="yoy_pct",
             title="中国 GDP 与同比增长", y1_label="亿元", y2_label="同比 (%)"))},
    ]
    # GDP 数据在 china_data 中 key 就是 "gdp"，但和 fred 的 gdp 冲突
    # 需要在 all_data 中用不同的 key
    if "gdp" in china_data:
        # 重新构建避免 key 冲突
        cn_gdp_builder = MacroChartBuilder(china_data, china_labels)
        cn_gdp_charts = [
            {"title": "中国 GDP 走势",
             "html": _chart_html(cn_gdp_builder.dual_axis(
                 "gdp", y1_col="value", y2_col="yoy_pct",
                 title="中国 GDP 与同比增长", y1_label="亿元", y2_label="同比 (%)"))},
        ]
    cn_subsections.append({"title": "GDP & 经济增长", "charts": cn_gdp_charts})

    # 3.2 CPI & PPI
    cn_price_charts = [
        {"title": "中国 CPI 同比趋势",
         "html": _chart_html(cn_builder.line_trend(
             ["cpi"], y_col="yoy_pct",
             title="中国 CPI 同比变化 (%)", y_label="同比 (%)"))},
        {"title": "中国 PPI 同比趋势",
         "html": _chart_html(cn_builder.line_trend(
             ["ppi"], y_col="yoy_pct",
             title="中国 PPI 同比变化 (%)", y_label="同比 (%)"))},
        {"title": "CPI vs PPI 对比",
         "html": _chart_html(cn_builder.multi_line(
             [("cpi", "yoy_pct", "CPI 同比"), ("ppi", "yoy_pct", "PPI 同比")],
             title="中国 CPI vs PPI 同比 (%)", y_label="同比 (%)"))},
    ]
    cn_subsections.append({"title": "CPI & PPI", "charts": cn_price_charts})

    # 3.3 PMI
    cn_pmi_charts = [
        {"title": "制造业 vs 非制造业 PMI",
         "html": _chart_html(cn_builder.multi_line(
             [("pmi_manufacturing", "value", "制造业 PMI"),
              ("pmi_non_manufacturing", "value", "非制造业 PMI")],
             title="中国 PMI 指数", y_label="指数"))},
    ]
    cn_subsections.append({"title": "PMI", "charts": cn_pmi_charts})

    # 3.4 货币供应
    cn_money_charts = [
        {"title": "M2 & M1 同比增速",
         "html": _chart_html(cn_builder.multi_line(
             [("m2", "yoy_pct", "M2 同比"), ("m1", "yoy_pct", "M1 同比")],
             title="中国货币供应增速 (%)", y_label="同比 (%)"))},
    ]
    cn_subsections.append({"title": "货币供应", "charts": cn_money_charts})

    # 3.5 贸易
    cn_trade_charts = [
        {"title": "进出口同比趋势",
         "html": _chart_html(cn_builder.multi_line(
             [("exports", "yoy_pct", "出口同比"), ("imports", "yoy_pct", "进口同比")],
             title="中国进出口同比变化 (%)", y_label="同比 (%)"))},
    ]
    cn_subsections.append({"title": "贸易数据", "charts": cn_trade_charts})

    # 3.6 工业 & 消费
    cn_indret_charts = [
        {"title": "工业增加值同比",
         "html": _chart_html(cn_builder.line_trend(
             ["industrial"], y_col="yoy_pct",
             title="中国工业增加值同比 (%)", y_label="同比 (%)"))},
        {"title": "社会消费品零售总额同比",
         "html": _chart_html(cn_builder.line_trend(
             ["retail"], y_col="yoy_pct",
             title="中国社会消费品零售总额同比 (%)", y_label="同比 (%)"))},
    ]
    cn_subsections.append({"title": "工业 & 消费", "charts": cn_indret_charts})

    # 3.7 外汇 & 黄金储备
    cn_fx_charts = [
        {"title": "外汇储备走势",
         "html": _chart_html(cn_builder.dual_axis(
             "fx_reserves", y1_col="value", y2_col="yoy_pct",
             title="中国外汇储备与同比变化", y1_label="亿美元", y2_label="同比 (%)"))},
        {"title": "黄金储备走势",
         "html": _chart_html(cn_builder.dual_axis(
             "gold_reserves", y1_col="value", y2_col="yoy_pct",
             title="中国黄金储备与同比变化", y1_label="万盎司", y2_label="同比 (%)"))},
    ]
    cn_subsections.append({"title": "外汇 & 黄金储备", "charts": cn_fx_charts})

    # 3.8 LPR 利率
    cn_lpr_charts = [
        {"title": "LPR 利率走势",
         "html": _chart_html(cn_builder.multi_line(
             [("lpr_1y", "value", "LPR 1年期"), ("lpr_5y", "value", "LPR 5年期")],
             title="中国 LPR 利率 (%)", y_label="%"))},
    ]
    cn_subsections.append({"title": "LPR 利率", "charts": cn_lpr_charts})

    # 3.9 Shibor 利率
    cn_shibor_charts = [
        {"title": "Shibor 利率走势",
         "html": _chart_html(cn_builder.multi_line(
             [("shibor_on", "value", "Shibor 隔夜"), ("shibor_3m", "value", "Shibor 3个月")],
             title="中国 Shibor 利率 (%)", y_label="%"))},
    ]
    cn_subsections.append({"title": "Shibor 利率", "charts": cn_shibor_charts})

    sections.append({"title": "中国宏观数据", "subsections": cn_subsections})

    total_charts = sum(len(sub["charts"]) for sec in sections for sub in sec["subsections"])
    print(f"  已生成 {total_charts} 张图表")

    # ── 7. 构建摘要表格 ──
    print("\n[6/8] 构建摘要数据...")
    us_rate_keys = {"unemployment", "fed_funds_rate", "treasury_10y", "treasury_2y",
                     "yield_spread", "labor_participation", "consumer_sentiment",
                     "capacity_utilization"}
    us_keys = [
        ("all_items", "yoy_pct"), ("core", "yoy_pct"),
        ("pce", "yoy_pct"), ("core_pce", "yoy_pct"),
        ("ppi", "yoy_pct"),
        ("unemployment", "value"), ("nonfarm_payrolls", "value"),
        ("labor_participation", "value"), ("initial_claims", "value"),
        ("gdp", "yoy_pct"),
        ("fed_funds_rate", "value"), ("treasury_10y", "value"),
        ("treasury_2y", "value"), ("yield_spread", "value"),
        ("consumer_sentiment", "value"), ("retail_sales", "yoy_pct"),
        ("industrial_production", "yoy_pct"), ("housing_starts", "value"),
        ("ppi_final_demand", "yoy_pct"), ("core_ppi", "yoy_pct"),
        ("avg_hourly_earnings", "yoy_pct"), ("trade_balance", "value"),
        ("m2_money_supply", "yoy_pct"), ("capacity_utilization", "value"),
    ]
    us_summary = _build_summary({**cpi_data, **fred_data}, us_keys, all_labels, us_rate_keys)

    cn_keys = [
        ("cpi", "yoy_pct"), ("ppi", "yoy_pct"),
        ("pmi_manufacturing", "value"), ("m2", "yoy_pct"),
        ("exports", "yoy_pct"), ("industrial", "yoy_pct"),
        ("retail", "yoy_pct"),
        ("fx_reserves", "value"), ("gold_reserves", "value"),
        ("lpr_1y", "value"), ("lpr_5y", "value"),
        ("shibor_on", "value"), ("shibor_3m", "value"),
    ]
    cn_rate_keys = set()
    china_summary = _build_summary(china_data, cn_keys, china_labels, cn_rate_keys)

    # ── 8. 渲染 HTML ──
    print("\n[7/8] 生成报告文件...")
    output_dir = Path("output") / "macro"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 报告日期
    report_date = datetime.now().strftime("%Y年%m月")

    # ── 数据新鲜度 ──
    def _max_date(data_dict):
        """从数据字典中提取所有 DataFrame 的最大日期"""
        max_d = None
        for df in data_dict.values():
            if hasattr(df, 'empty') and not df.empty and "date" in df.columns:
                d = df["date"].max()
                if d is not None and (max_d is None or d > max_d):
                    max_d = d
        if max_d is not None and hasattr(max_d, "strftime"):
            return max_d.strftime("%Y-%m-%d")
        return str(max_d) if max_d is not None else "N/A"

    data_freshness = {
        "cpi": _max_date(cpi_data),
        "fred": _max_date(fred_data),
        "china": _max_date(china_data),
    }

    env = Environment(loader=FileSystemLoader("reports/templates"))
    template = env.get_template("macro.html")
    html_content = template.render(
        report_date=report_date,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        us_summary=us_summary,
        china_summary=china_summary,
        sections=sections,
        # Analysis engine results
        cycle_signals=cycle_signals,
        recession_data=recession_data,
        inflation_analysis=inflation_analysis,
        labor_analysis=labor_analysis,
        credit_pulse=credit_pulse,
        context_data=context_data,
        regime_us=regime_us,
        regime_china=regime_china,
        asset_scores=asset_scores,
        cpi_forecast=cpi_forecast,
        macro_forecasts=macro_forecasts,
        forward_asset_scores=forward_asset_scores,
        data_freshness=data_freshness,
        polymarket_data=polymarket_data,
        consensus=consensus,
    )

    html_path = output_dir / "macro_report.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"  HTML 报告: {html_path}")

    print("\n[8/8] 完成!")
    print("\n" + "=" * 60)
    print(f"  报告生成完成！打开 {html_path} 查看")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成全球宏观经济数据分析报告")
    parser.add_argument("--cache", action="store_true", help="使用本地缓存数据（不联网）")
    args = parser.parse_args()
    generate_macro_report(use_cache=args.cache)
