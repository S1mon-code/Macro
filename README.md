# Macro -- 全球宏观经济数据周报系统

**Global Macro Economic Weekly Report Generator**

自动采集美国（BLS、FRED）和中国（AKShare）宏观经济数据，结合 Polymarket 预测市场实时定价与卖方共识预测，运行 10 个分析引擎（经济周期、衰退概率、通胀拆解、劳动力市场、中国信用脉冲、宏观体制识别、资产记分卡、CPI 预测、宏观预测矩阵、历史背景），生成交互式 HTML 中文周报。

Automatically fetches US (BLS, FRED) and China (AKShare) macro data, integrates Polymarket prediction market pricing and sell-side consensus forecasts, runs 10 analysis engines (cycle, recession, inflation, labor, China credit pulse, regime detection, asset scorecard, CPI forecast, macro forecast matrix, historical context), and generates an interactive HTML weekly report in Chinese.

---

## Features / 功能

- **US CPI deep-dive**: 17 BLS series with YoY/MoM decomposition, component heatmaps, and sub-item drill-down
- **US macro dashboard**: 40+ FRED series covering GDP, employment, inflation, rates, credit, and leading indicators
- **China macro pulse**: 12 AKShare indicators (GDP, CPI, PPI, PMI, M2, trade, industrial output, retail, credit, FX reserves, LPR, Shibor)
- **10 analysis engines**: cycle assessment, recession probability (Sahm Rule + yield curve + LEI), inflation regime, labor dashboard, China credit pulse, macro regime classification, asset scorecard, CPI component forecasting, macro forecast matrix, historical percentile context
- **Polymarket integration**: real-time prediction market prices for recession, Fed decisions, CPI, inflation
- **Sell-side consensus**: manually curated Goldman Sachs / JPMorgan / Morgan Stanley targets, Fed dot plot, CME FedWatch
- **Interactive Plotly charts**: zoomable, hoverable charts embedded in a single-file HTML report
- **SQLite caching**: offline mode via `--cache` flag, no API calls needed for re-runs
- **Forecast engine**: component-level CPI forecasting (energy from gasoline/WTI regression, shelter from OER trends, food from PPI food pipeline) and macro variable forecasting (unemployment, GDP, Fed funds rate)

---

## Architecture / 架构

```
┌─────────────────────────────────────────────────────────┐
│                    macro_report.py                       │
│               (orchestrator, 873 lines)                 │
├─────────────┬──────────────┬────────────────────────────┤
│  Data Layer │ Analysis     │ Presentation               │
│             │ Engines      │                            │
│ ┌─────────┐ │ ┌──────────┐ │ ┌────────────┐             │
│ │BLS API  │ │ │Cycle     │ │ │CPICharts   │             │
│ │(17 CPI) │ │ │Recession │ │ │MacroCharts │             │
│ ├─────────┤ │ │Inflation │ │ ├────────────┤             │
│ │FRED API │ │ │Labor     │ │ │Jinja2      │             │
│ │(40+ ser)│ │ │ChinaCredt│ │ │Templates   │             │
│ ├─────────┤ │ │Regime    │ │ │ macro.html │             │
│ │AKShare  │ │ │Scorecard │ │ │ cpi.html   │             │
│ │(12 CN)  │ │ │CPIFcst   │ │ └────────────┘             │
│ ├─────────┤ │ │MacroFcst │ │                            │
│ │Polymarkt│ │ │Context   │ │  output/macro/             │
│ └─────────┘ │ └──────────┘ │  macro_report.html         │
│      │      │      │       │                            │
│  ┌───▼───┐  │      │       │                            │
│  │SQLite │◄─┼──────┘       │                            │
│  │Cache  │  │              │                            │
│  └───────┘  │              │                            │
└─────────────┴──────────────┴────────────────────────────┘
```

---

## Quick Start / 快速开始

```bash
# 1. Clone and enter
git clone https://github.com/S1mon-code/Macro.git
cd Macro

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API keys
cp .env.example .env
# Edit .env and add your BLS_API_KEY and FRED_API_KEY
#   BLS: https://data.bls.gov/registrationEngine/
#   FRED: https://fred.stlouisfed.org/docs/api/api_key.html

# 5. Generate report
python macro_report.py

# 6. Open report
open output/macro/macro_report.html
```

---

## Usage / 使用方法

### Full macro report (default)

```bash
# Fetch fresh data from all APIs and generate report
python macro_report.py

# Use cached data (offline mode, no API calls)
python macro_report.py --cache
```

### CPI-only report

```bash
# Standalone CPI deep-dive report
python cpi_report.py
python cpi_report.py --cache
```

### Run tests

```bash
pytest tests/ -v
```

---

## Project Structure / 项目结构

```
Macro/
├── macro_report.py              # Main orchestrator (873 lines)
├── cpi_report.py                # Standalone CPI report generator
├── requirements.txt             # Python dependencies
├── .env.example                 # API key template
├── .env                         # API keys (git-ignored)
│
├── config/
│   ├── settings.yaml            # Data source config (BLS/FRED/AKShare series)
│   └── consensus.yaml           # Sell-side consensus & market prices (manual)
│
├── data/
│   ├── fetchers/
│   │   ├── bls_fetcher.py       # BLS CPI API (17 series)
│   │   ├── fred_fetcher.py      # FRED API (40+ series)
│   │   ├── akshare_fetcher.py   # AKShare China macro (12 indicators)
│   │   └── polymarket_fetcher.py# Polymarket Gamma API (7 markets)
│   ├── cache/
│   │   └── db.py                # SQLite cache layer
│   └── manual/                  # Manual data supplements
│
├── analysis/
│   ├── cycle.py                 # Economic cycle assessment (LEI, CLI signals)
│   ├── recession.py             # Recession probability (Sahm Rule, yield curve, composite)
│   ├── inflation.py             # Inflation regime analysis (sticky vs flexible, Taylor Rule)
│   ├── labor.py                 # Labor market dashboard (Beveridge curve, wage-Phillips)
│   ├── china_credit.py          # China credit impulse (TSF, new loans Z-score)
│   ├── regime.py                # Macro regime classification (growth x inflation quadrant)
│   ├── scorecard.py             # Asset scorecard (equities, bonds, gold, USD, commodities)
│   ├── cpi_forecast.py          # Component-level CPI forecasting (energy, shelter, food, core)
│   ├── macro_forecast.py        # Macro variable forecast matrix (unemployment, GDP, Fed rate)
│   ├── context.py               # Historical percentile context for all indicators
│   └── utils.py                 # Shared analysis utilities
│
├── charts/
│   ├── cpi_charts.py            # CPI-specific Plotly chart builder
│   └── macro_charts.py          # General macro Plotly chart builder
│
├── reports/
│   ├── templates/
│   │   ├── macro.html           # Full macro report Jinja2 template
│   │   └── cpi.html             # CPI report Jinja2 template
│   └── exporters/               # (Future: PDF/Markdown export)
│
├── output/                      # Generated reports (git-ignored)
│   ├── macro/
│   │   └── macro_report.html
│   └── cpi/
│       ├── cpi_report.html
│       └── images/              # Static chart PNGs
│
├── tests/                       # Test suite (fetchers + charts)
│   ├── test_bls_fetcher.py
│   ├── test_fred_fetcher.py
│   ├── test_akshare_fetcher.py
│   ├── test_cache.py
│   ├── test_cpi_charts.py
│   └── test_macro_charts.py
│
├── docs/
│   ├── research/
│   │   └── sell-side-macro-methodology.md
│   └── superpowers/
│       ├── specs/
│       │   └── 2026-03-29-macro-weekly-report-design.md
│       └── plans/
│           └── 2026-03-29-macro-implementation.md
│
├── commentary/                  # Weekly commentary (manual YAML)
└── tasks/
    ├── todo.md                  # Roadmap and next steps
    └── lessons.md               # Development lessons learned
```

---

## Data Sources / 数据源

| Source | Type | Series Count | Frequency | Module |
|--------|------|-------------|-----------|--------|
| **BLS API** | US CPI components | 17 series | Monthly | `bls_fetcher.py` |
| **FRED API** | US macro (GDP, employment, rates, credit, inflation) | 40+ series | Mixed (daily/weekly/monthly/quarterly) | `fred_fetcher.py` |
| **AKShare** | China macro (GDP, CPI, PPI, PMI, M2, trade, etc.) | 12 indicators | Mixed (daily/monthly/quarterly) | `akshare_fetcher.py` |
| **Polymarket** | Prediction markets (recession, Fed, CPI, inflation) | 7 markets | Real-time | `polymarket_fetcher.py` |
| **Manual** | Sell-side consensus, market prices, Fed dot plot | N/A | Weekly update | `config/consensus.yaml` |

---

## Analysis Engines / 分析引擎

| Module | Class | Description |
|--------|-------|-------------|
| `cycle.py` | `CycleAssessor` | Economic cycle phase detection using LEI, CLI, and composite indicators |
| `recession.py` | `RecessionTracker` | Recession probability via Sahm Rule, yield curve inversion duration, and composite score |
| `inflation.py` | `InflationAnalyzer` | Inflation regime (sticky vs flexible CPI, Taylor Rule implied rate, real rate analysis) |
| `labor.py` | `LaborDashboard` | Labor market health (Beveridge curve, wage-price Phillips curve, U-6 gap, JOLTS analysis) |
| `china_credit.py` | `ChinaCreditPulse` | China credit impulse from TSF and new RMB loans, Z-score normalization |
| `regime.py` | `MacroRegime` | Growth x Inflation quadrant classification (Goldilocks / Reflation / Stagflation / Deflation) |
| `scorecard.py` | `AssetScorecard` | Multi-factor scoring for equities, bonds, gold, USD, and commodities |
| `cpi_forecast.py` | `CPIForecaster` | Component-level CPI forecast (energy from gasoline regression, shelter from OER trend, food from PPI pipeline) |
| `macro_forecast.py` | `MacroForecastMatrix` | Macro variable forecasting (unemployment via Sahm/Okun, GDP via GDPNow proxy, Fed rate via Taylor Rule) |
| `context.py` | `HistoricalContext` | Historical percentile ranking for all indicators (where are we vs. history?) |

---

## Configuration / 配置

### `config/settings.yaml`

Controls all data series IDs, labels, frequency classifications, and start year:
- `bls.api_key` / `fred.api_key`: set via environment variables (`BLS_API_KEY`, `FRED_API_KEY`)
- `cpi.series`: 17 BLS CPI component series IDs
- `fred.series`: 40+ FRED series with frequency metadata (`daily_series`, `weekly_series`, `quarterly_series`, `rate_series`)
- `china.indicators`: 12 AKShare function mappings

### `config/consensus.yaml`

Manually updated sell-side consensus data:
- CPI forecasts (pre/post oil shock)
- Fed dot plot, CME FedWatch probabilities
- Atlanta Fed GDPNow
- S&P 500, gold, oil target prices from Goldman Sachs, JPMorgan, Morgan Stanley
- Polymarket snapshot backup

### `.env`

```
BLS_API_KEY=your_key_here
FRED_API_KEY=your_key_here
```

---

## Report Sections / 报告板块

The generated HTML report (`output/macro/macro_report.html`) contains:

1. **Executive Summary** -- report date, data freshness timestamps, generation time
2. **US Macro Dashboard** -- summary table with latest values, YoY changes, expandable history
3. **China Macro Dashboard** -- same format for China indicators
4. **Economic Cycle Analysis** -- LEI/CLI signals, cycle phase identification
5. **Recession Risk Monitor** -- Sahm Rule, yield curve, composite recession probability
6. **Inflation Deep-Dive** -- sticky vs flexible CPI, trimmed mean, median CPI, real rate
7. **Labor Market Analysis** -- Beveridge curve, Phillips curve, JOLTS, U-6 analysis
8. **China Credit Pulse** -- TSF credit impulse, new loan Z-scores
9. **Macro Regime** -- US and China growth x inflation quadrant classification
10. **Asset Scorecard** -- current and forward-looking multi-factor scores for 5 asset classes
11. **CPI Forecast** -- next-month component-level CPI forecast with confidence intervals
12. **Macro Forecast Matrix** -- 3/6/12 month forecasts for key macro variables
13. **Historical Context** -- percentile rankings for all indicators vs. 10-year history
14. **Polymarket Consensus** -- real-time prediction market probabilities
15. **Sell-Side Consensus** -- institutional targets and forecasts from `consensus.yaml`
16. **Interactive Charts** -- Plotly charts (YoY trends, MoM bars, component comparisons, cycle indicators)

---

## License

Private project. Not for redistribution.
