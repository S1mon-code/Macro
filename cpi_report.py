"""美国 CPI 数据拉取、分析、图表生成、报告输出"""

import argparse
from datetime import datetime
from pathlib import Path

import plotly.io as pio
from jinja2 import Environment, FileSystemLoader

from data.fetchers.bls_fetcher import BLSFetcher
from data.cache.db import CacheDB
from charts.cpi_charts import CPIChartBuilder


def generate_cpi_report(use_cache: bool = False):
    """生成 CPI 分析报告"""
    print("=" * 50)
    print("美国 CPI 数据分析报告生成")
    print("=" * 50)

    # 1. 拉取数据
    fetcher = BLSFetcher()
    cache = CacheDB()

    if use_cache:
        print("\n[1/4] 从缓存加载数据...")
        all_data = {}
        for name, sid in fetcher.series.items():
            df = cache.load("cpi", series_id=sid)
            if not df.empty:
                all_data[name] = df
        if not all_data:
            print("  缓存为空，切换为在线拉取...")
            use_cache = False

    if not use_cache:
        print("\n[1/4] 从 BLS API 拉取 CPI 数据...")
        all_data = fetcher.fetch_cpi_all()
        # 缓存到 SQLite
        print("  保存到本地缓存...")
        for name, df in all_data.items():
            if not df.empty:
                cache.save("cpi", df)

    print(f"  已获取 {len(all_data)} 个分项数据")

    # 2. 生成图表
    print("\n[2/4] 生成分析图表...")
    builder = CPIChartBuilder(all_data, fetcher.labels)

    major_components = ["food", "energy", "shelter", "transportation", "medical"]
    available_components = [c for c in major_components if c in all_data and not all_data[c].empty]

    chart_configs = [
        ("CPI 同比趋势 (总指数 vs 核心)", builder.yoy_trend(["all_items", "core"])),
        ("CPI 同比趋势 (主要分项)", builder.yoy_trend(available_components)),
        ("CPI 总指数环比变化", builder.mom_bar("all_items", last_n=12)),
        ("CPI 各分项最新同比对比", builder.components_latest_yoy(available_components)),
        ("CPI 指数绝对值走势", builder.index_value_trend(["all_items", "core"])),
        ("CPI 总指数趋势预测", builder.forecast("all_items", months_ahead=3)),
        ("核心 CPI 趋势预测", builder.forecast("core", months_ahead=3)),
    ]
    print(f"  已生成 {len(chart_configs)} 张图表")

    # 3. 构建摘要表格
    print("\n[3/4] 构建报告数据...")
    summary = []
    report_date = "N/A"
    display_order = ["all_items", "core"] + available_components
    for name in display_order:
        df = all_data.get(name)
        if df is None or df.empty:
            continue
        df_valid = df.dropna(subset=["yoy_pct", "mom_pct"])
        if df_valid.empty:
            continue
        latest = df_valid.iloc[-1]
        period = f"{int(latest['year'])}年{int(latest['month'])}月"
        if name == "all_items":
            report_date = period
        summary.append({
            "label": fetcher.get_label(name),
            "value": latest["value"],
            "yoy": latest["yoy_pct"],
            "mom": latest["mom_pct"],
            "period": period,
        })

    # 4. 渲染 HTML
    print("\n[4/4] 生成报告文件...")
    output_dir = Path("output") / "cpi"
    output_dir.mkdir(parents=True, exist_ok=True)

    charts_html = []
    for title, fig in chart_configs:
        chart_html = pio.to_html(fig, full_html=False, include_plotlyjs=False)
        charts_html.append({"title": title, "html": chart_html})

    env = Environment(loader=FileSystemLoader("reports/templates"))
    template = env.get_template("cpi.html")
    html_content = template.render(
        report_date=report_date,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        summary=summary,
        charts=charts_html,
    )

    html_path = output_dir / "cpi_report.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"  HTML 报告: {html_path}")

    # 导出静态图片
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)
    for i, (title, fig) in enumerate(chart_configs):
        png_path = images_dir / f"chart_{i+1}.png"
        fig.write_image(str(png_path), width=1200, height=600, scale=2)
    print(f"  图表图片: {images_dir}/")

    print("\n" + "=" * 50)
    print(f"报告生成完成！打开 {html_path} 查看")
    print("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成美国 CPI 数据分析报告")
    parser.add_argument("--cache", action="store_true", help="使用本地缓存数据（不联网）")
    args = parser.parse_args()
    generate_cpi_report(use_cache=args.cache)
