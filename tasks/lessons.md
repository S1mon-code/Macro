# Macro -- Lessons Learned

Development lessons captured during the build of the macro weekly report system. Each lesson represents a bug, gotcha, or insight that cost time and should not be repeated.

---

## 1. Plotly 6.x binary encoding breaks with pandas Series

**Problem**: Plotly 6.x uses binary encoding internally and chokes on raw pandas Series/Index objects.
**Fix**: Always call `.tolist()` before passing pandas data to Plotly trace constructors.
**Example**: `fig.add_trace(go.Scatter(x=df["date"].tolist(), y=df["value"].tolist()))` -- not `x=df["date"]`.

## 2. BLS API v2 requires API key for computed fields

**Problem**: Without `registrationkey` in the POST body, the BLS API returns raw index values but YoY and MoM percentage change fields (`calculations.pct_changes`) are empty.
**Fix**: Always include `BLS_API_KEY` in requests. Without it, we must compute YoY/MoM ourselves from raw index values (which we now do as a fallback, but the API-provided values are more reliable).

## 3. AKShare column names change between versions

**Problem**: AKShare updated column names silently between minor versions (e.g., column renamed from one Chinese string to another).
**Fix**: Use defensive column checking -- check for multiple possible column names, log warnings when expected columns are missing, never assume exact column names.

## 4. China NBS publishes Jan-Feb combined data

**Problem**: China's National Bureau of Statistics publishes combined January-February data for most monthly indicators. February rows appear as NaN.
**Fix**: Must skip NaN February rows when processing China monthly data. Filter `df.dropna()` before computing changes.

## 5. FRED UNRATE is only 1 decimal precision

**Problem**: FRED's `UNRATE` series is rounded to 1 decimal place (e.g., 4.4%), which is insufficient for Sahm Rule calculations that require detecting 0.5pp moves.
**Fix**: Compute precise unemployment rate from `UNEMPLOY / CLF16OV * 100` (both are thousands, giving ~2 decimal precision).

## 6. CPI energy forecast -- retail gasoline is monthly after fetching

**Problem**: FRED's `GASREGW` (retail gasoline) is published weekly, but our `fred_fetcher.py` converts it to monthly averages during fetch. The forecast code was incorrectly treating it as weekly data and trying to resample.
**Fix**: After fetching through our pipeline, all data is already monthly. Use it directly without additional frequency conversion.

## 7. Low R-squared regressions are worse than simple trends

**Problem**: Some macro forecast regressions (e.g., GDP from limited quarterly data) produce R-squared values below 0.3, making the regression prediction less reliable than a simple trend extrapolation.
**Fix**: Always check R-squared after fitting. If R-squared < 0.3, fall back to trend-based forecast. Log a warning when this happens.

## 8. API keys in git = security risk

**Problem**: Accidentally committed `.env` file with API keys to git.
**Fix**: Use `.env` + `python-dotenv` for all API keys. Ensure `.env` is in `.gitignore`. Provide `.env.example` with placeholder values only.

## 9. Sahm Rule requires 3-month rolling MA minimum

**Problem**: Initial implementation compared current unemployment to the raw 12-month minimum, which is not the Sahm Rule. The real Sahm Rule compares the 3-month moving average of unemployment to the minimum of the 3-month MA over the prior 12 months.
**Fix**: Compute 3-month rolling average first, then find its minimum over the trailing 12 months, then compare current 3-month MA to that minimum.

## 10. Taylor Rule r-star from zero-rate era is misleading

**Problem**: Estimating the neutral real rate (r*) from post-2008 data where rates were at zero for a decade produces an r* near zero, making the Taylor Rule imply the Fed should always be hiking.
**Fix**: Use standard academic/Fed estimates for r* (currently ~0.5-1.0%) rather than estimating from recent data. The Laubach-Williams model or FOMC's own longer-run estimate are better references.
