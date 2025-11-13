# Daily Stock Insights Pipeline

Generate daily stock summaries with exchange/sector context from MongoDB stock data.

## Quick Start

```bash
# Virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run
python main.py --date 2025-11-10 --env dev
```

## Usage

```bash
python main.py --date YYYY-MM-DD [--env dev|prod] [--db-name NAME] [--source-collection NAME] [--target-collection NAME]
```

Configuration is in `config.json` (thresholds, dev/prod database names).

## Input/Output

**Input:** `stocks_merged` collection with fields: ticker, name, exchange, date, last_price, change (%), volume, sector, industry, country, num_of_rising_days, accumulated_change, market_cap, pe_ratio

**Note:** Date format is DD-MM-YYYY (e.g., "12-11-2025"). Change field is percentage string (e.g., "-0.52%").

**Output:** `daily_stock_summaries` collection with calculated metrics:

- Volume metrics: `vol_ratio`, `vol_z`, `vol_spike_flag`
- Exchange context: `exchange_return`, `sector_return`, `industry_return`, `country_return`
- Robustness: `robust_abs`, `robust_rel_z`, `is_robust_on_bad_day`
- Standout: `standout_z`, `standout_flag`
- Consistency: `consistency_score`, `trend_label`
- Comparison: previous day deltas

## Logic

**Metrics Calculation:**
- Volume ratios use 10-day rolling median. Z-scores computed on log(volume).
- Exchange/sector/industry/country returns are average pct_change per group (only latest date).
- Robustness: `robust_abs = pct_change - exchange_return`. `is_robust_on_bad_day` flags stocks that outperform when exchange is down.
- Standout: Z-score of pct_change vs sector. Falls back to exchange-wide if sector has <5 stocks (bootstrap).
- Consistency: `1/(1 + std(pct_change_10d))`. Trend label from `num_of_rising_days` (>=3 = "up", <=-2 = "down", else "sideways").

**Comparisons:**
- Primary: Query `daily_stock_summaries` for previous day.
- Fallback: Query raw `stocks_merged` if summary not found.
- Calculates deltas: `delta_pct_change`, `delta_vol_ratio`, `delta_consistency`.

**Bootstrapping:**
- When sector/industry groups have <5 stocks, use exchange-wide medians.
- Sets `bootstrap_source` and reduces confidence by 20%.

## Docker

```bash
./docker-build.sh  # Builds and pushes to Docker Hub
docker run --env-file .env amiroz/projects:stock_insights_latest --date 2025-11-10 --env prod
```

Local testing with MongoDB:
```bash
cd docker && docker-compose up -d
```

