"""全球宏观经济数据分析报告生成器

拉取美国（BLS CPI + FRED）和中国（AKShare）宏观数据，
生成综合 HTML 交互式报告。
"""

import argparse
from datetime import datetime
from pathlib import Path

import plotly.io as pio
from jinja2 import Environment, FileSystemLoader

from data.fetchers.bls_fetcher import BLSFetcher
from data.fetchers.fred_fetcher import FREDFetcher
from data.fetchers.akshare_fetcher import AKShareFetcher
from data.cache.db import CacheDB
from charts.cpi_charts import CPIChartBuilder
from charts.macro_charts import MacroChartBuilder


def _chart_html(fig) -> str:
    """将 Plotly Figure 转为嵌入 HTML 片段"""
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _build_summary(data: dict, keys: list[tuple[str, str]], labels: dict) -> list[dict]:
    """构建摘要表格数据
    keys: [(data_key, y_col_for_display), ...]
    """
    summary = []
    for key, _ in keys:
        df = data.get(key)
        if df is None or df.empty:
            continue
        yoy_col = "yoy_pct"
        if yoy_col not in df.columns:
            continue
        df_valid = df.dropna(subset=[yoy_col])
        if df_valid.empty:
            continue
        latest = df_valid.iloc[-1]
        date = latest.get("date")
        if date is not None:
            period = date.strftime("%Y年%m月") if hasattr(date, "strftime") else str(date)
        else:
            period = "N/A"
        summary.append({
            "label": labels.get(key, key),
            "value": float(latest.get("value", 0)) if latest.get("value") is not None else 0,
            "yoy": float(latest[yoy_col]) if latest[yoy_col] is not None else 0,
            "period": period,
        })
    return summary


def generate_macro_report(use_cache: bool = False):
    """生成全球宏观经济数据分析报告"""
    print("=" * 60)
    print("  全球宏观经济数据分析报告生成")
    print("=" * 60)

    cache = CacheDB()

    # ── 1. 拉取美国 CPI 数据 (BLS) ──
    print("\n[1/6] 拉取美国 CPI 数据 (BLS)...")
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
    print("\n[2/6] 拉取美国宏观数据 (FRED)...")
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
    print("\n[3/6] 拉取中国宏观数据 (AKShare)...")
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

    # ── 4. 构建所有标签映射 ──
    all_labels = {}
    all_labels.update(bls.labels)
    all_labels.update(fred.labels)
    # 中国指标标签
    china_labels = {
        "gdp": "GDP", "cpi": "CPI", "ppi": "PPI",
        "pmi_manufacturing": "制造业 PMI", "pmi_non_manufacturing": "非制造业 PMI",
        "m2": "M2 货币供应", "m1": "M1 货币供应",
        "exports": "出口", "imports": "进口",
        "industrial": "工业增加值", "retail": "社会消费品零售",
        "credit": "新增人民币贷款",
    }
    all_labels.update(china_labels)

    # ── 5. 生成图表 ──
    print("\n[4/6] 生成分析图表...")

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

    # 2.1 CPI & 通胀
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
    ]
    us_subsections.append({"title": "CPI & 通胀", "charts": cpi_charts})

    # 2.2 PPI & PCE
    ppi_pce_charts = [
        {"title": "PPI 生产者价格指数走势",
         "html": _chart_html(macro_builder.dual_axis(
             "ppi", y1_col="value", y2_col="yoy_pct",
             title="PPI 指数与同比变化", y1_label="指数值", y2_label="同比 (%)"))},
        {"title": "PCE vs 核心 PCE 同比",
         "html": _chart_html(macro_builder.multi_line(
             [("pce", "yoy_pct", "PCE 同比"), ("core_pce", "yoy_pct", "核心 PCE 同比")],
             title="PCE 价格指数同比变化 (%)", y_label="同比 (%)"))},
    ]
    us_subsections.append({"title": "PPI & PCE", "charts": ppi_pce_charts})

    # 2.3 就业市场
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
    ]
    us_subsections.append({"title": "工业 & 房地产", "charts": industry_charts})

    sections.append({"title": "美国宏观数据", "subsections": us_subsections})

    # ── Section 2: 中国宏观数据 ──
    cn_subsections = []

    # 3.1 GDP
    cn_gdp_charts = [
        {"title": "中国 GDP 走势",
         "html": _chart_html(macro_builder.dual_axis(
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

    # 使用中国专用 builder 避免 key 冲突
    cn_builder = MacroChartBuilder(china_data, china_labels)

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

    sections.append({"title": "中国宏观数据", "subsections": cn_subsections})

    total_charts = sum(len(sub["charts"]) for sec in sections for sub in sec["subsections"])
    print(f"  已生成 {total_charts} 张图表")

    # ── 6. 构建摘要表格 ──
    print("\n[5/6] 构建摘要数据...")
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
    ]
    us_summary = _build_summary({**cpi_data, **fred_data}, us_keys, all_labels)

    cn_keys = [
        ("cpi", "yoy_pct"), ("ppi", "yoy_pct"),
        ("pmi_manufacturing", "value"), ("m2", "yoy_pct"),
        ("exports", "yoy_pct"), ("industrial", "yoy_pct"),
        ("retail", "yoy_pct"),
    ]
    china_summary = _build_summary(china_data, cn_keys, china_labels)

    # ── 7. 渲染 HTML ──
    print("\n[6/6] 生成报告文件...")
    output_dir = Path("output") / "macro"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 报告日期
    report_date = datetime.now().strftime("%Y年%m月")

    env = Environment(loader=FileSystemLoader("reports/templates"))
    template = env.get_template("macro.html")
    html_content = template.render(
        report_date=report_date,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        us_summary=us_summary,
        china_summary=china_summary,
        sections=sections,
    )

    html_path = output_dir / "macro_report.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"  HTML 报告: {html_path}")

    print("\n" + "=" * 60)
    print(f"  报告生成完成！打开 {html_path} 查看")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成全球宏观经济数据分析报告")
    parser.add_argument("--cache", action="store_true", help="使用本地缓存数据（不联网）")
    args = parser.parse_args()
    generate_macro_report(use_cache=args.cache)
