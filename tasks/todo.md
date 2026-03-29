# Macro -- CEO + CTO Roadmap

**Last updated**: 2026-03-29

---

## Immediate (this week)

- [ ] Add unit tests for all 10 analysis modules (cycle, recession, inflation, labor, china_credit, regime, scorecard, cpi_forecast, macro_forecast, context) -- ZERO tests currently, only fetcher/chart tests exist
- [ ] Fix October 2025 CPI data gap -- missing month corrupts MoM calculations downstream
- [ ] Improve CPI energy forecast accuracy -- current cap of +/-5% may still be too crude, consider using CPI gasoline index (CUSR0000SETB01) directly instead of retail gasoline proxy
- [ ] Add Manheim Used Vehicle Index data for used car CPI forecast (currently using transport proxy which is too broad)

## Short-term (next 2 weeks)

- [ ] Add PDF export using WeasyPrint (installed in requirements.txt but unused for macro report)
- [ ] Weekly automation -- cron job or scheduled script for `python macro_report.py` with Slack/email notification
- [ ] Add more Polymarket markets to monitor (gold price targets, S&P 500 direction, oil price)
- [ ] Add forecast accuracy tracking -- log each forecast with timestamp, compare to actual value when released
- [ ] Refactor macro_report.py -- break 873-line `generate_macro_report()` function into composable pipeline steps (fetch, analyze, chart, render)

## Medium-term (next month)

- [ ] Build stock index + gold/silver price tracking module (the original project goal from design spec)
- [ ] Add technical analysis overlays (MA, support/resistance) for indices and commodities
- [ ] Add Zillow/Apartment List rent data for 12-month leading OER forecast (currently OER forecast uses simple trend extrapolation)
- [ ] Build backtesting framework for asset scorecard (historical signal accuracy measurement)
- [ ] Add earnings calendar and earnings revision data for equity forecasting in scorecard
- [ ] Implement email delivery of weekly report (HTML or PDF attachment)

## Long-term (next quarter)

- [ ] Machine learning layer -- use historical data to optimize scorecard factor weights via gradient boosting or Bayesian optimization
- [ ] Real-time dashboard -- Flask/Streamlit app for live monitoring instead of static HTML generation
- [ ] Multi-language report generation (English version for international audience)
- [ ] Add more countries (Europe ECB data, Japan BOJ data, macro indicators)
- [ ] Bloomberg/Reuters API integration for real-time consensus data (replace manual consensus.yaml)
- [ ] Satellite data / alternative data integration for China (nighttime lights, shipping data)

## Known Issues

- [ ] `macro_report.py` is a God function (873 lines, single `generate_macro_report()`) -- needs refactoring into pipeline steps
- [ ] Forward scorecard may still have edge cases with missing forecast data (None values in factor computation)
- [ ] China GDP only has ~10 data points (single quarters since 2016) -- sparse for Z-score normalization
- [ ] Some regression models in macro_forecast fall back to simple trend when R-squared is low -- need better models or more features
- [ ] Polymarket market slugs may change or markets may close -- need periodic validation and fallback
- [ ] `consensus.yaml` requires manual updates every week -- consider scraping automation from CME FedWatch, Atlanta Fed GDPNow
- [ ] October 2025 CPI data gap corrupts MoM calculations for subsequent months
- [ ] AKShare column names change between library versions -- defensive column checking is in place but may need updates
