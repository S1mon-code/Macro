# Macro — 全球宏观数据周报系统设计文档

**日期**: 2026-03-29
**项目名**: Macro
**路径**: ~/Desktop/Macro

---

## 1. 项目概述

半自动化的全球宏观数据周报生成系统。每周自动采集宏观经济数据和市场行情，结合手动撰写的观点与事件评论，生成三种格式的中文周报：HTML 交互式报告（兼做 Dashboard）、PDF 静态报告、Markdown + 图片。

## 2. 技术栈

- **语言**: Python 3.11+
- **数据采集**: AKShare（A股/港股/宏观/资金流/汇率）、yfinance（美股/黄金白银/VIX）
- **数据存储**: SQLite（本地缓存历史数据）
- **图表**: Plotly（交互式图表 + 静态图导出）
- **模板**: Jinja2（HTML 报告模板渲染）
- **PDF 导出**: WeasyPrint
- **配置**: YAML

## 3. 项目结构

```
Macro/
├── config/
│   ├── settings.yaml          # 全局配置（数据源开关、API key等）
│   └── report_template.yaml   # 报告结构配置（包含哪些板块）
├── data/
│   ├── fetchers/              # 数据采集模块
│   │   ├── __init__.py
│   │   ├── akshare_fetcher.py # A股/港股/宏观数据/资金流/汇率
│   │   ├── yfinance_fetcher.py# 美股/黄金/白银/VIX
│   │   └── macro_fetcher.py   # 宏观指标聚合（CPI/PPI/PMI等）
│   ├── cache/                 # SQLite 数据库文件
│   └── manual/                # 手动补充数据（YAML格式）
├── analysis/
│   ├── __init__.py
│   ├── technical.py           # 技术分析（均线/支撑阻力/趋势判断）
│   └── macro.py               # 宏观数据处理（同比/环比/趋势）
├── charts/
│   ├── __init__.py
│   └── builder.py             # Plotly 图表生成器
├── reports/
│   ├── templates/             # Jinja2 HTML 模板
│   │   └── weekly.html
│   ├── generator.py           # 报告生成引擎（合并数据+观点→渲染）
│   └── exporters/
│       ├── __init__.py
│       ├── pdf_exporter.py    # HTML → PDF
│       └── markdown_exporter.py # HTML → Markdown + PNG
├── commentary/                # 每周观点（手动撰写）
│   └── 2026-W13.yaml
├── output/                    # 生成的报告
│   └── 2026-W13/
│       ├── report.html
│       ├── report.pdf
│       ├── report.md
│       └── images/            # 导出的图表 PNG
├── main.py                    # 入口脚本
└── requirements.txt
```

## 4. 数据源

| 资产/指标 | 数据源 | 频率 | 模块 |
|-----------|--------|------|------|
| A股指数（上证/深证/创业板） | AKShare | 日线 | akshare_fetcher |
| 港股（恒生/恒生科技） | AKShare | 日线 | akshare_fetcher |
| 美股（S&P500/纳斯达克/道琼斯） | yfinance | 日线 | yfinance_fetcher |
| 黄金（XAU/USD） | yfinance | 日线 | yfinance_fetcher |
| 白银（XAG/USD） | yfinance | 日线 | yfinance_fetcher |
| 美元指数（DXY） | AKShare | 日线 | akshare_fetcher |
| 人民币汇率（USD/CNY） | AKShare | 日线 | akshare_fetcher |
| CPI/PPI/PMI | AKShare（国家统计局） | 月度 | macro_fetcher |
| 美联储利率 | yfinance / 手动 | 事件驱动 | manual/ |
| 北向/南向资金 | AKShare | 日线 | akshare_fetcher |
| VIX 恐慌指数 | yfinance | 日线 | yfinance_fetcher |
| 地缘事件/重大事件 | 手动 | 周度 | commentary/ |

## 5. 观点文件格式

每周在 `commentary/` 下创建 YAML 文件，格式如下：

```yaml
week: "2026-W13"
date_range: "2026-03-23 ~ 2026-03-29"

macro_view: |
  本周宏观总结观点...

events:
  - title: "事件标题"
    impact: "利好/利空/中性"
    comment: "具体评论..."

markets:
  a_share:
    view: "观点..."
  hk_stock:
    view: "观点..."
  us_stock:
    view: "观点..."
  gold:
    view: "观点..."
  silver:
    view: "观点..."

next_week_focus:
  - "下周关注事件1"
  - "下周关注事件2"
```

## 6. 报告结构

每期周报包含以下固定板块：

1. **本周概览** — 一句话总结 + 各市场涨跌幅表格
2. **宏观数据** — 本周公布的经济数据 + 同比环比图表
3. **重大事件** — 事件列表 + 影响评估（来自 commentary）
4. **市场分析**（每个市场一小节）：
   - 周K线 + MA5/20/60 均线图（Plotly）
   - 本周涨跌幅、成交量变化
   - 关键支撑/阻力位标注
   - 手写观点（来自 commentary）
5. **资金流向** — 北向/南向资金周度净流入柱状图
6. **市场情绪** — VIX 走势、美元指数、汇率变化折线图
7. **下周关注** — 重要经济数据/事件日历

## 7. 输出格式

- **HTML**: 交互式 Plotly 图表，可缩放/悬停查看数据，浏览器直接打开即为 Dashboard
- **PDF**: WeasyPrint 渲染，Plotly 图表转为静态 PNG 嵌入，适合分发
- **Markdown**: 图表导出为 PNG 存入 `output/images/`，MD 文件通过相对路径引用

## 8. 技术分析规格

轻量级技术分析，每个市场/资产生成：
- MA5、MA20、MA60 均线叠加在K线图上
- 根据近期高低点自动标注支撑位和阻力位
- 简单趋势判断（均线多头/空头排列、价格相对均线位置）

## 9. 工作流

```
1. 填写 commentary/2026-WXX.yaml（手动，5-10分钟）
2. 运行 python main.py --week 2026-W13
3. 自动执行：
   a. 拉取本周行情和宏观数据
   b. 缓存到 SQLite
   c. 计算技术指标
   d. 生成 Plotly 图表
   e. 合并观点到模板
   f. 输出 HTML / PDF / Markdown
4. 检查 output/2026-W13/ 下的报告
5. 分发
```

## 10. 依赖

```
akshare
yfinance
plotly
kaleido          # Plotly 静态图导出
jinja2
weasyprint
pyyaml
pandas
numpy
```
