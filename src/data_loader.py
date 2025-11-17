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
    target_date: str,
    lookback_days: int = 17
) -> pd.DataFrame:
    """
    Load stock data for the last N days from MongoDB
    
    Args:
        db_name: Database name
        source_collection: Source collection name (e.g., stocks_merged)
        target_date: Target date as DD-MM-YYYY string
        lookback_days: Number of days to look back (default 10)
        
    Returns:
        DataFrame with derived fields added
    """
    client = get_mongo_client()
    db = client[db_name]
    collection = db[source_collection]
    
    # Parse target date
    target_dt = datetime.strptime(target_date, '%d-%m-%Y')
    start_date = target_dt - timedelta(days=lookback_days)
    
    # Convert to DD-MM-YYYY string format for display
    target_date_str = target_dt.strftime('%d-%m-%Y')
    start_date_str = start_date.strftime('%d-%m-%Y')
    
    logging.info(f"Loading data from {start_date_str} to {target_date_str}")
    
    # Use MongoDB aggregation pipeline to parse and filter dates server-side
    pipeline = [
        {
            '$addFields': {
                'parsed_date': {
                    '$dateFromString': {
                        'dateString': '$date',
                        'format': '%d-%m-%Y',
                        'onError': None,  # Set to None for invalid dates
                        'onNull': None
                    }
                }
            }
        },
        {
            '$match': {
                'parsed_date': {
                    '$gte': start_date,
                    '$lte': target_dt
                }
            }
        },
        {
            '$project': {
                'parsed_date': 0  # Remove the temporary parsed_date field
            }
        }
    ]
    
    cursor = collection.aggregate(pipeline)
    data = list(cursor)
    client.close()
    
    if not data:
        logging.warning(f"No data found for date range {start_date.date()} to {target_dt.date()}")
        return pd.DataFrame()
    
    logging.info(f"Loaded {len(data)} records from MongoDB (filtered server-side)")
    
    # Convert to DataFrame
    df = pd.DataFrame(data)
    
    # Drop MongoDB _id field
    if '_id' in df.columns:
        df = df.drop('_id', axis=1)
    
    # Parse string fields to proper types
    df = _parse_fields(df)
    
    # Derive required fields
    df = _derive_fields(df)
    
    # Filter to only include records with required fields
    df = _validate_data(df)
    
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
    # Parse date from DD-MM-YYYY format
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], format='%d-%m-%Y', errors='coerce')
    
    # Parse change from percentage string (e.g., "-0.22%") and store as pct_change
    # Handle cases where change is "-" or other invalid values
    if 'change' in df.columns:
        # Strip % and handle cases where value is just "-"
        df['pct_change'] = df['change'].astype(str).str.rstrip('%')
        # Replace only when the entire value is "-" (not negative numbers)
        df['pct_change'] = df['pct_change'].apply(lambda x: '' if x == '-' else x)
        df['pct_change'] = pd.to_numeric(df['pct_change'], errors='coerce')
    
    # Parse volume from comma-separated string (e.g., "98,935")
    if 'volume' in df.columns:
        df['volume'] = df['volume'].astype(str).str.replace(',', '')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
    
    # Map input field names to internal names
    if 'name' in df.columns and 'company' not in df.columns:
        df['company'] = df['name']
    if 'last_price' in df.columns and 'price' not in df.columns:
        df['price'] = df['last_price']
    
    # Parse num_of_rising_days from string to int
    if 'num_of_rising_days' in df.columns:
        df['num_of_rising_days'] = pd.to_numeric(df['num_of_rising_days'], errors='coerce').fillna(0).astype(int)
    
    # Parse accumulated_change from string
    if 'accumulated_change' in df.columns:
        df['accumulated_change'] = pd.to_numeric(df['accumulated_change'], errors='coerce')
    
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
    # Calculate prev_close from price and pct_change
    # pct_change = (price - prev_close) / prev_close * 100
    # Rearranging: prev_close = price / (1 + pct_change/100)
    df['prev_close'] = df.apply(
        lambda row: row['price'] / (1 + row['pct_change'] / 100) 
        if row['pct_change'] != -100 else row['price'],
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
    
    # Rename price to last_price for output
    if 'price' in df.columns:
        df['last_price'] = df['price']
    
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
        'ticker', 'date', 'price', 'volume', 
        'exchange', 'pct_change'
    ]
    
    # Check required columns exist
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    
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

