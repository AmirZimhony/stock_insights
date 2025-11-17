# Daily Stock Insights Pipeline

Generate daily stock summaries with exchange/sector context from MongoDB stock data.

## Quick Start

```bash
# Virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run
python main.py --date 10-11-2025 --env dev
```

## Usage

```bash
python main.py --date DD-MM-YYYY [--env dev|prod] [--db-name NAME] [--source-collection NAME] [--target-collection NAME]
```

Configuration is in `config.json` (thresholds, dev/prod database names).

**Note for Airflow/Docker deployments:** This repository only contains `dev` configurations in `config.json`. For other environments (e.g., `staging`, `prod`) or when running in Airflow, you **must** provide database and collection names via command-line arguments (`--db-name`, `--source-collection`, `--target-collection`). Command-line arguments override values from `config.json`, so the pipeline will work correctly as long as these arguments are provided, even if the environment name doesn't exist in the config file.

**Example with all command-line arguments (using dev config values):**
python main.py \
  --date 10-11-2025 \
  --env staging \
  --db-name stock_test1 \
  --source-collection stocks_merged_test \
  --target-collection daily_stock_summaries_dev
```

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

## Output Field Descriptions

### Basic Identification
- **ticker** (string): Stock ticker symbol
- **name** (string, optional): Company name
- **exchange** (string): Stock exchange (e.g., "NASDAQ", "TASE")
- **date** (string): Date in DD-MM-YYYY format (e.g., "13-11-2025")

### Price Data
- **last_price** (float): Current day's closing price
- **prev_close** (float, optional): Previous day's closing price (calculated from last_price and pct_change)
- **pct_change** (float): Percentage change from previous day (e.g., -1.53 means -1.53%)

### Volume Metrics
- **volume** (float): Trading volume for the day
- **vol_ratio** (float, optional): Current volume divided by 10-day rolling median volume. Values > 2.0 indicate volume spikes
- **vol_z** (float, optional): Z-score of log(volume) - measures how unusual the volume is statistically
- **vol_spike_flag** (boolean): True if vol_ratio exceeds threshold (default 2.0)
- **new_in_market** (boolean): True if this ticker appears for the first time in the lookback window

### Sector/Industry/Country
- **sector** (string, optional): Business sector classification
- **industry** (string, optional): Industry classification
- **country** (string, optional): Country of operation
- **exchange_sector** (string): Composite key "EXCHANGE|SECTOR" for grouping
- **exchange_industry** (string): Composite key "EXCHANGE|INDUSTRY" for grouping
- **exchange_country** (string): Composite key "EXCHANGE|COUNTRY" for grouping

### Exchange Context (Returns)
Average percentage change for the group on the latest date:
- **exchange_return** (float, optional): Average pct_change across all stocks in the exchange
- **sector_return** (float, optional): Average pct_change for stocks in the same exchange and sector
- **industry_return** (float, optional): Average pct_change for stocks in the same exchange and industry
- **country_return** (float, optional): Average pct_change for stocks in the same exchange and country

### Robustness Metrics
Measures how well a stock performs relative to its market context:
- **robust_abs** (float, optional): Absolute robustness = pct_change - exchange_return. Positive values indicate outperformance
- **robust_rel_z** (float, optional): Z-score of robust_abs within the exchange_sector group. Higher values = stronger relative performance
- **is_robust_on_bad_day** (boolean): True if stock outperformed when exchange_return < 0 (stock went up or fell less than the exchange)

### Standout Metrics
Measures how much a stock stands out from its sector peers:
- **standout_z** (float, optional): Z-score of pct_change vs sector peers. Values > 1.5 indicate significant outperformance/underperformance
- **standout_flag** (boolean): True if |standout_z| exceeds threshold (default 1.5)
- **bootstrap_source** (string, optional): Indicates if sector had <5 stocks, so exchange-wide comparison was used instead. Values: "exchange_median" or null. null means there are more than 5 stocks in this sector. 

### Consistency Metrics
Measures price movement consistency over the lookback period:
- **consistency_score** (float, optional): Calculated as 1/(1 + std(pct_change_10d)). Higher values (closer to 1.0) = more consistent price movements
- **num_of_rising_days** (int): Count of days with positive pct_change in the lookback window
- **accumulated_change** (float): Sum of all pct_change values over the lookback period
- **trend_label** (string, optional): Trend classification - "up" (>=3 rising days), "down" (<=-2 rising days), or "sideways" (otherwise)

### Comparison Data (Previous Day Deltas)
Nested object comparing current day to previous day:
- **comparison.prev_date** (string, optional): Previous day's date in DD-MM-YYYY format, or null if no previous data found
- **comparison.delta_pct_change** (float, optional): Change in pct_change from previous day (current - previous)
- **comparison.delta_vol_ratio** (float, optional): Change in vol_ratio from previous day
- **comparison.delta_consistency** (float, optional): Change in consistency_score from previous day
- **comparison.prev_exists** (boolean): True if previous day data was found (from summaries or raw data)

### Additional Fields
- **market_cap** (float, optional): Market capitalization
- **pe_ratio** (float, optional): Price-to-earnings ratio

### Confidence and Bootstrap
- **confidence** (float): Confidence score (0.0-1.0). Reduced by 20% when bootstrap_source is used (sector had <5 stocks)
- **bootstrap_source** (string, optional): See "Standout Metrics" above

### Metadata
Nested object with pipeline information:
- **analysis_meta.pipeline_version** (string): Version of the pipeline that generated this summary
- **analysis_meta.generated_by** (string): Pipeline identifier ("daily_stock_insights")
- **analysis_meta.computed_at** (datetime): UTC timestamp when the analysis was computed

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
docker run --env-file .env amiroz/projects:stock_insights_latest --date 10-11-2025 --env prod
```

Local testing with MongoDB:
```bash
cd docker && docker-compose up -d
```

## Future Improvements

**Improved prev_date comparison mechanism**
- Consider keeping in metadata table the last date each market was active, for each market. These prev dates will be passed to this job. The current mechanism (today -1, if doesn't exist then use raw data for computing prev date data) isn't very reliable.  

**Comparison Logic Enhancement:**
- Consider changing the standout metrics and bootstrap logic to use `industry` instead of `sector` for grouping. Currently, the pipeline groups by `exchange_sector` (21 sectors), but using `exchange_industry` (273 industries) would provide more granular comparisons. Note that with more granular groups, each industry group will have fewer stocks than sector groups, which may increase bootstrap fallback usage when groups have <5 stocks.

