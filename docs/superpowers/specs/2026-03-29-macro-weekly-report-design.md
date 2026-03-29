# Macro -- 全球宏观数据周报系统设计文档 (Current State)

**日期**: 2026-03-29
**项目名**: Macro
**路径**: ~/Desktop/Macro
**状态**: v1.0 -- 核心功能完成，报告可正常生成

---

## 1. 项目概述

半自动化的全球宏观经济数据周报生成系统。自动采集美国（BLS CPI + FRED 40+ 系列）和中国（AKShare 12 指标）宏观数据，集成 Polymarket 预测市场实时价格和卖方共识预测，通过 10 个分析引擎生成综合评估，输出交互式 HTML 中文周报。

**与初始设计的主要差异**:
- 放弃 yfinance，改用 FRED 作为美国数据主源（更全、更稳定）
- 新增 BLS API 直连（17 个 CPI 分项）
- 新增 Polymarket 预测市场集成
- 从简单的 K 线图 + 技术分析演变为 10 个宏观分析引擎
- 暂未实现 PDF/Markdown 导出（WeasyPrint 已安装但未接入）
- 暂未实现股票/商品价格追踪模块（留作后续）

## 2. 技术栈

- **语言**: Python 3.12
- **数据采集**: BLS API v2（CPI）、FRED API（美国宏观）、AKShare（中国宏观）、Polymarket Gamma API（预测市场）
- **数据存储**: SQLite（本地缓存，`data/cache/macro.db`）
- **图表**: Plotly 6.x（交互式图表嵌入 HTML）+ Kaleido（静态 PNG 导出）
- **模板**: Jinja2（HTML 报告渲染）
- **配置**: YAML（`settings.yaml` 数据源配置、`consensus.yaml` 共识预测）
- **环境变量**: python-dotenv（API keys）
- **分析**: pandas, numpy, scipy（回归、统计）

## 3. 项目结构 (实际)

```
Macro/
├── macro_report.py              # 主入口 & 编排器 (873 lines)
├── cpi_report.py                # CPI 独立报告 (128 lines)
├── requirements.txt
├── .env / .env.example
│
├── config/
│   ├── settings.yaml            # 数据源配置 (228 lines)
│   └── consensus.yaml           # 卖方共识 (82 lines, 手动更新)
│
├── data/
│   ├── fetchers/
│   │   ├── bls_fetcher.py       # BLS CPI API (142 lines, 17 系列)
│   │   ├── fred_fetcher.py      # FRED API (211 lines, 40+ 系列)
│   │   ├── akshare_fetcher.py   # AKShare (475 lines, 12 中国指标)
│   │   └── polymarket_fetcher.py# Polymarket Gamma API (155 lines, 7 市场)
│   ├── cache/
│   │   └── db.py                # SQLite 缓存层 (88 lines)
│   └── manual/
│
├── analysis/                    # 10 个分析引擎 (共 4,607 lines)
│   ├── cycle.py                 # 经济周期 (312 lines)
│   ├── recession.py             # 衰退概率 (319 lines)
│   ├── inflation.py             # 通胀拆解 (249 lines)
│   ├── labor.py                 # 劳动力市场 (382 lines)
│   ├── china_credit.py          # 中国信用脉冲 (153 lines)
│   ├── regime.py                # 宏观体制 (277 lines)
│   ├── scorecard.py             # 资产记分卡 (644 lines)
│   ├── cpi_forecast.py          # CPI 预测 (628 lines)
│   ├── macro_forecast.py        # 宏观预测矩阵 (1,453 lines)
│   ├── context.py               # 历史背景 (125 lines)
│   └── utils.py                 # 工具函数 (42 lines)
│
├── charts/                      # Plotly 图表构建 (385 lines)
│   ├── cpi_charts.py            # CPI 图表 (137 lines)
│   └── macro_charts.py          # 宏观图表 (248 lines)
│
├── reports/
│   ├── templates/
│   │   ├── macro.html           # 完整宏观报告模板
│   │   └── cpi.html             # CPI 报告模板
│   └── exporters/               # (预留: PDF/Markdown 导出)
│
├── tests/                       # 测试 (824 lines, 仅 fetcher + chart)
│   ├── test_bls_fetcher.py
│   ├── test_fred_fetcher.py
│   ├── test_akshare_fetcher.py
│   ├── test_cache.py
│   ├── test_cpi_charts.py
│   └── test_macro_charts.py
│
├── output/                      # 生成物 (git-ignored)
│   ├── macro/macro_report.html
│   └── cpi/cpi_report.html + images/
│
├── docs/
│   ├── research/sell-side-macro-methodology.md
│   └── superpowers/specs/ + plans/
│
├── commentary/                  # 周度评论 (预留)
└── tasks/
    ├── todo.md                  # 路线图
    └── lessons.md               # 经验教训
```

## 4. 数据源 (实际)

| 数据源 | 模块 | 系列数 | 频率 | 认证 |
|--------|------|--------|------|------|
| BLS API v2 | `bls_fetcher.py` | 17 CPI 分项 | 月度 | `BLS_API_KEY` (必需) |
| FRED API | `fred_fetcher.py` | 40+ 美国宏观 | 日/周/月/季 | `FRED_API_KEY` (必需) |
| AKShare | `akshare_fetcher.py` | 12 中国指标 | 日/月/季 | 无需 |
| Polymarket Gamma | `polymarket_fetcher.py` | 7 预测市场 | 实时 | 无需 |
| 手动共识 | `consensus.yaml` | N/A | 每周更新 | N/A |

### FRED 系列分类

- **日频** (需转月均): treasury_10y, treasury_2y, yield_spread, treasury_3m, hy_spread, ig_spread, wti_crude, dxy
- **周频** (需转月均): initial_claims, retail_gasoline
- **季频**: gdp
- **比率类** (同比用差值 pp): unemployment, fed_funds_rate, treasury rates, spreads, sentiment, participation

### 中国 AKShare 指标

GDP (季度), CPI, PPI, PMI, 货币供应 (M2), 进出口贸易, 工业增加值, 社零, 新增信贷, 外汇储备, LPR, Shibor

## 5. 分析引擎详细设计

### 5.1 CycleAssessor (经济周期)
- 输入: LEI, industrial_production, capacity_utilization, yield_spread
- 输出: cycle phase (expansion/peak/contraction/trough), signal strength
- 方法: 多指标投票 + 趋势方向综合判断

### 5.2 RecessionTracker (衰退追踪)
- Sahm Rule: 3 月均失业率 vs 12 月最低值, 阈值 0.5pp
- 收益率曲线: 10Y-2Y 利差反转持续时间
- 综合得分: 多信号加权概率

### 5.3 InflationAnalyzer (通胀分析)
- 粘性 vs 弹性 CPI 分解
- Taylor Rule 隐含利率 vs 实际利率
- 截尾均值 PCE、中位 CPI 趋势

### 5.4 LaborDashboard (劳动力)
- Beveridge 曲线 (失业率 vs JOLTS 空缺率)
- 工资-价格 Phillips 曲线
- U-6 广义失业率 vs U-3 缺口
- 25-54 岁黄金年龄劳动参与率

### 5.5 ChinaCreditPulse (中国信用脉冲)
- 新增人民币贷款 / TSF 信用脉冲
- Z-score 标准化 (基于 2016 年以来数据)

### 5.6 MacroRegime (宏观体制)
- 增长 x 通胀四象限: Goldilocks / Reflation / Stagflation / Deflation
- 美国和中国分别判断

### 5.7 AssetScorecard (资产记分卡)
- 5 个资产类别: 股票、债券、黄金、美元、大宗商品
- 多因子打分: 周期位置、通胀体制、信用条件、估值、动量
- 当前 + 前瞻版本 (基于 macro_forecast 预测值)

### 5.8 CPIForecaster (CPI 预测)
- 能源: 零售汽油价格 + WTI 原油回归, 上限 ±5%
- 住房: OER + 租金趋势外推 (12 月领先)
- 食品: PPI 食品 → CPI 食品 pipeline (6 月滞后)
- 核心商品: 趋势外推
- 合成: 权重加总各分项 → headline + core CPI 预测

### 5.9 MacroForecastMatrix (宏观预测)
- 失业率: Sahm 动量 + Okun's Law
- GDP: 领先指标回归 (R² 校验, 低则回退趋势)
- 联邦基金利率: Taylor Rule + 点阵图路径
- 输出: 3/6/12 月预测 + 置信区间

### 5.10 HistoricalContext (历史背景)
- 所有指标的 10 年历史百分位排名
- "当前水平在历史中处于什么位置"

## 6. 报告结构 (实际)

HTML 单文件报告 (`output/macro/macro_report.html`), 嵌入 Plotly.js, 包含:

1. 数据新鲜度面板 (CPI/FRED/China 各数据源最新日期)
2. 美国宏观仪表盘 (可展开历史的摘要表格)
3. 中国宏观仪表盘
4. 经济周期信号
5. 衰退风险监控
6. 通胀深度分析
7. 劳动力市场分析
8. 中国信用脉冲
9. 宏观体制分类 (美国 + 中国)
10. 资产记分卡 (当前 + 前瞻)
11. CPI 分项预测
12. 宏观预测矩阵
13. 历史百分位背景
14. Polymarket 实时共识
15. 卖方共识与市场目标价
16. 交互式 Plotly 图表 (缩放/悬停/点击)

## 7. 工作流 (实际)

```
1. 更新 config/consensus.yaml (手动, ~5分钟)
2. 运行 python macro_report.py
3. 自动执行:
   a. 拉取 BLS CPI 数据 (17 系列)
   b. 拉取 FRED 美国宏观数据 (40+ 系列)
   c. 拉取 AKShare 中国数据 (12 指标)
   d. 拉取 Polymarket 预测市场 (7 市场)
   e. 缓存到 SQLite
   f. 运行 10 个分析引擎
   g. 生成 Plotly 交互式图表
   h. Jinja2 渲染 HTML 报告
4. 打开 output/macro/macro_report.html 查看
5. (可选) python macro_report.py --cache 离线复查
```

## 8. 代码规模

| 模块 | 文件数 | 总行数 |
|------|--------|--------|
| 分析引擎 | 12 | 4,607 |
| 数据采集 | 4 | 983 |
| 图表 | 2 | 385 |
| 缓存 | 1 | 88 |
| 编排器 | 2 | 1,001 |
| 测试 | 6 | 824 |
| 配置 | 2 | 310 |
| **总计** | **29** | **~8,200** |

## 9. 依赖

```
requests>=2.31.0
pandas>=2.1.0
plotly>=5.18.0
kaleido>=0.2.1
jinja2>=3.1.0
weasyprint>=60.0      # 已安装, 暂未使用
pyyaml>=6.0
numpy>=1.26.0
scipy>=1.11.0
akshare>=1.12.0
python-dotenv>=1.0.0
```

## 10. 待实现 (vs 初始设计)

从初始设计中尚未实现的功能:
- [ ] 股票/商品价格追踪 (A股、港股、美股、黄金白银)
- [ ] 技术分析 (均线、支撑/阻力)
- [ ] PDF 导出 (WeasyPrint 已安装)
- [ ] Markdown + PNG 导出
- [ ] 北向/南向资金流向
- [ ] VIX 恐慌指数追踪
- [ ] 手写评论系统 (`commentary/` 目录已创建但未接入)

新增的初始设计中没有的功能:
- [x] 10 个宏观分析引擎
- [x] BLS API 直连 (17 CPI 分项)
- [x] Polymarket 预测市场集成
- [x] 卖方共识预测框架
- [x] SQLite 离线缓存
- [x] CPI 分项级预测引擎
- [x] 宏观变量预测矩阵
