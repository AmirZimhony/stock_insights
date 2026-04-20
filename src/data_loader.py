"""
Data loader module - Query stock data from MongoDB
"""
import logging
from datetime import datetime, timedelta
import pandas as pd
from src.utils import get_mongo_client


def load_stock_data(
    db_name: str,
    source_collection: str,
    target_date: datetime,
    lookback_days: int = 17
) -> pd.DataFrame:
    """
    Load stock data for the last N days from MongoDB
    
    Args:
        db_name: Database name
        source_collection: Source collection name (e.g., stocks_merged)
        target_date: Target date as datetime object
        lookback_days: Number of days to look back (default 10)
        
    Returns:
        DataFrame with derived fields added
    """
    client = get_mongo_client()
    db = client[db_name]
    collection = db[source_collection]
    
    # Calculate start date
    start_date = target_date - timedelta(days=lookback_days)
    
    # Calculate end of target day to include all times on that day
    end_of_target_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Convert to DD-MM-YYYY string format for display
    target_date_str = target_date.strftime('%d-%m-%Y')
    start_date_str = start_date.strftime('%d-%m-%Y')
    
    logging.info(f"Loading data from {start_date_str} to {target_date_str}")
    
    # Query MongoDB for date range (dates stored as datetime objects)
    pipeline = [
        {
            '$match': {
                'date': {
                    '$gte': start_date,
                    '$lte': end_of_target_day  # Include entire target day
                }
            }
        }
    ]
    
    cursor = collection.aggregate(pipeline)
    data = list(cursor)
    client.close()
    
    if not data:
        logging.warning(f"No data found for date range {start_date.date()} to {target_date.date()}")
        return pd.DataFrame()
    
    logging.info(f"Loaded {len(data)} records from MongoDB (filtered server-side)")
    
    # Convert to DataFrame
    df = pd.DataFrame(data)
    
    # Debug: Check date distribution from MongoDB
    if 'date' in df.columns:
        date_counts = df['date'].value_counts().sort_index()
        logging.info(f"MongoDB data - First date: {date_counts.index[0]}, Last date: {date_counts.index[-1]}")
        logging.info(f"Records by date: {dict(list(date_counts.items())[:3])} ... {dict(list(date_counts.items())[-3:])}")
    
    # Drop MongoDB _id field
    if '_id' in df.columns:
        df = df.drop('_id', axis=1)
    
    # Parse string fields to proper types
    df = _parse_fields(df)
    logging.info(f"After parsing - Records: {len(df)}, Date range: {df['date'].min()} to {df['date'].max()}")
    
    # Derive required fields
    df = _derive_fields(df)
    logging.info(f"After deriving - Records: {len(df)}, Date range: {df['date'].min()} to {df['date'].max()}")
    
    # Filter to only include records with required fields
    df = _validate_data(df)
    logging.info(f"After validation - Records: {len(df)}, Date range: {df['date'].min()} to {df['date'].max()}")
    
    logging.info(f"Processed {len(df)} valid records")
    
    return df


def _parse_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse string fields to proper types
    
    Args:
        df: Input DataFrame with string fields
        
    Returns:
        DataFrame with parsed numeric and date fields
    """
    # Date is already datetime from MongoDB, ensure it's pandas datetime64 with UTC timezone
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        # Ensure timezone-aware UTC to match command-line parsed dates
        if df['date'].dt.tz is None:
            df['date'] = df['date'].dt.tz_localize('UTC')
        else:
            df['date'] = df['date'].dt.tz_convert('UTC')
    
    # Parse change from percentage string (e.g., "-0.22%") and store as pct_change
    # Unparseable values (e.g., "-") are treated as 0 to keep the record instead of dropping it
    if 'change' in df.columns:
        df['pct_change'] = df['change'].astype(str).str.rstrip('%')
        df['pct_change'] = pd.to_numeric(df['pct_change'], errors='coerce').fillna(0.0)
    
    # Parse volume from comma-separated string (e.g., "98,935")
    if 'volume' in df.columns:
        df['volume'] = df['volume'].astype(str).str.replace(',', '')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
    
   
    
    # Parse num_of_rising_days from string to int
    if 'num_of_rising_days' in df.columns:
        df['num_of_rising_days'] = pd.to_numeric(df['num_of_rising_days'], errors='coerce').fillna(0).astype(int)
    
    # Parse accumulated_change from string; unparseable values fall back to 0 to keep the record
    if 'accumulated_change' in df.columns:
        df['accumulated_change'] = pd.to_numeric(df['accumulated_change'], errors='coerce').fillna(0.0)
    
    # Parse pe_ratio from string
    if 'pe_ratio' in df.columns:
        df['pe_ratio'] = pd.to_numeric(df['pe_ratio'], errors='coerce')
    
    # Parse market_cap from string with M/B/K suffixes (e.g., "83.48M")
    if 'market_cap' in df.columns:
        def parse_market_cap(val):
            if pd.isna(val) or val == '':
                return None
            val = str(val).strip().upper()
            multipliers = {'K': 1e3, 'M': 1e6, 'B': 1e9, 'T': 1e12}
            for suffix, multiplier in multipliers.items():
                if val.endswith(suffix):
                    try:
                        return float(val[:-1]) * multiplier
                    except ValueError:
                        return None
            try:
                return float(val)
            except ValueError:
                return None
        
        df['market_cap'] = df['market_cap'].apply(parse_market_cap)
    
    return df


def _derive_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive required fields from input data
    
    Args:
        df: Input DataFrame
        
    Returns:
        DataFrame with derived fields
    """
    # Calculate prev_close from last_price and pct_change
    # pct_change = (last_price - prev_close) / prev_close * 100
    # Rearranging: prev_close = last_price / (1 + pct_change/100)
    df['prev_close'] = df.apply(
        lambda row: row['last_price'] / (1 + row['pct_change'] / 100) 
        if row['pct_change'] != -100 else row['last_price'],
        axis=1
    )
    
    # Fill missing sector/industry/country with 'Unknown'
    df['sector'] = df['sector'].fillna('Unknown')
    df['industry'] = df['industry'].fillna('Unknown')
    df['country'] = df['country'].fillna('Unknown')
    
    # exchange_sector = exchange + "|" + sector
    df['exchange_sector'] = df['exchange'] + '|' + df['sector']
    
    # exchange_industry = exchange + "|" + industry
    df['exchange_industry'] = df['exchange'] + '|' + df['industry']
    
    # exchange_country = exchange + "|" + country
    df['exchange_country'] = df['exchange'] + '|' + df['country']
    
    return df


def _validate_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validate and clean data
    
    Args:
        df: Input DataFrame
        
    Returns:
        Cleaned DataFrame
    """
    required_cols = [
        'ticker', 'date', 'last_price', 'volume', 
        'exchange', 'change'
    ]
    
    # Check required columns exist
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    
    # Debug: Check which columns have nulls before dropping
    for col in required_cols:
        null_count = df[col].isna().sum()
        if null_count > 0:
            logging.warning(f"Column '{col}' has {null_count} null values")
            null_dates = df[df[col].isna()]['date'].dt.strftime('%d-%m-%Y').unique()
            logging.warning(f"Dates with null {col}: {sorted(null_dates)[-5:]} (showing last 5)")
    
    # Remove rows with null required fields
    initial_count = len(df)
    df = df.dropna(subset=required_cols)
    
    if len(df) < initial_count:
        logging.warning(f"Dropped {initial_count - len(df)} rows with missing required fields")
    
    # Remove rows with invalid volume
    df = df[df['volume'] > 0]
    
    # Sort by date and ticker
    df = df.sort_values(['date', 'ticker'])
    
    return df

