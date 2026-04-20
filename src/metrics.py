"""
Metrics calculator module
Calculate volume stats, exchange/sector context, robustness, standout, and consistency
"""
import logging
import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, Tuple


def _get_latest_date_df(df: pd.DataFrame) -> Tuple:
    """Get latest date and filtered DataFrame"""
    latest_date = df['date'].max()
    latest_df = df[df['date'] == latest_date].copy()
    return latest_date, latest_df


def calculate_metrics(df: pd.DataFrame, thresholds: Dict) -> pd.DataFrame:
    """
    Calculate all metrics for stock data
    
    Args:
        df: DataFrame with stock data
        thresholds: Dictionary of threshold values
        
    Returns:
        DataFrame with calculated metrics
    """
    if df.empty:
        logging.warning("Empty DataFrame provided to calculate_metrics")
        return df
    
    logging.info(f"Calculating metrics for {len(df)} records")
    
    # Extract thresholds
    volume_spike_threshold = thresholds.get('volume_spike_threshold', 2.0)
    standout_z_threshold = thresholds.get('standout_z_threshold', 1.5)
    min_data_points = thresholds.get('min_data_points', 5)
    trend_up_days = thresholds.get('trend_up_days', 6)
    trend_down_days = thresholds.get('trend_down_days', 4)
    
    # Calculate volume metrics
    df = _calculate_volume_metrics(df, volume_spike_threshold)
    
    # Identify new tickers
    df = _identify_new_tickers(df)
    
    # Calculate exchange/sector context
    df = _calculate_market_context(df)
    
    # Calculate robustness metrics
    df = _calculate_robustness_metrics(df)
    
    # Calculate standout metrics
    df = _calculate_standout_metrics(df, standout_z_threshold, min_data_points)
    
    # Calculate consistency metrics
    df = _calculate_consistency_metrics(df, trend_up_days, trend_down_days)
    
    # Calculate confidence scores
    df = _calculate_confidence(df, min_data_points)
    
    logging.info("Metrics calculation completed")
    
    return df


def _calculate_volume_metrics(df: pd.DataFrame, spike_threshold: float) -> pd.DataFrame:
    """Calculate volume ratio and z-score"""
    
    # Group by ticker to calculate rolling stats
    def calc_vol_metrics(group):
        # Re-attach grouping column (pandas >=3.0 excludes it from the group)
        group = group.assign(ticker=group.name)
        # Rolling median volume (10 days)
        group = group.sort_values('date')
        group['vol_median'] = group['volume'].rolling(window=10, min_periods=1).median()
        
        # vol_ratio = volume / rolling_median
        group['vol_ratio'] = group['volume'] / group['vol_median']
        
        # vol_z = z-score of log(volume)
        log_vol = np.log(group['volume'] + 1)  # +1 to avoid log(0)
        if len(log_vol) > 1:
            group['vol_z'] = stats.zscore(log_vol, nan_policy='omit')
        else:
            group['vol_z'] = 0.0
        
        return group
    
    df = df.groupby('ticker', group_keys=False).apply(calc_vol_metrics)
    
    # vol_spike_flag
    df['vol_spike_flag'] = df['vol_ratio'] > spike_threshold
    
    return df


def _identify_new_tickers(df: pd.DataFrame) -> pd.DataFrame:
    """Identify tickers that appear for the first time in the window"""
    
    # Get the latest date in the dataset
    latest_date = df['date'].max()
    
    # For each ticker, check if this is their first appearance
    def is_new(group):
        # Re-attach grouping column (pandas >=3.0 excludes it from the group)
        group = group.assign(ticker=group.name)
        group = group.sort_values('date')
        # Mark as new if only appears on the latest date
        group['new_in_market'] = (group['date'] == latest_date) & (len(group) == 1)
        return group
    
    df = df.groupby('ticker', group_keys=False).apply(is_new)
    
    return df


def _calculate_market_context(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate exchange, sector, industry, and country returns"""
    
    latest_date, latest_df = _get_latest_date_df(df)
    
    # Exchange return (average pct_change per exchange)
    exchange_returns = latest_df.groupby('exchange')['pct_change'].mean().to_dict()
    
    # Sector return (average pct_change per exchange_sector)
    sector_returns = latest_df.groupby('exchange_sector')['pct_change'].mean().to_dict()
    
    # Industry return (average pct_change per exchange_industry)
    industry_returns = latest_df.groupby('exchange_industry')['pct_change'].mean().to_dict()
    
    # Country return (average pct_change per exchange_country)
    country_returns = latest_df.groupby('exchange_country')['pct_change'].mean().to_dict()
    
    # Map back to full dataframe
    df['exchange_return'] = df['exchange'].map(exchange_returns)
    df['sector_return'] = df['exchange_sector'].map(sector_returns)
    df['industry_return'] = df['exchange_industry'].map(industry_returns)
    df['country_return'] = df['exchange_country'].map(country_returns)
    
    return df


def _calculate_robustness_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate robustness metrics"""
    
    # robust_abs = pct_change - exchange_return
    df['robust_abs'] = df['pct_change'] - df['exchange_return']
    
    latest_date, latest_df = _get_latest_date_df(df)
    
    def calc_robust_z(group):
        # Re-attach grouping column (pandas >=3.0 excludes it from the group)
        group = group.assign(exchange_sector=group.name)
        if len(group) > 1:
            group['robust_rel_z'] = stats.zscore(group['robust_abs'], nan_policy='omit')
        else:
            group['robust_rel_z'] = 0.0
        return group
    
    latest_df = latest_df.groupby('exchange_sector', group_keys=False).apply(calc_robust_z)
    
    # Map back to full dataframe (only for latest date)
    robust_z_map = latest_df.set_index('ticker')['robust_rel_z'].to_dict()
    df['robust_rel_z'] = df.apply(
        lambda row: robust_z_map.get(row['ticker'], 0.0) if row['date'] == latest_date else 0.0,
        axis=1
    )
    
    # is_robust_on_bad_day
    df['is_robust_on_bad_day'] = (
        (df['exchange_return'] < 0) & 
        ((df['pct_change'] > df['exchange_return']) | (df['pct_change'] > 0))
    )
    
    return df


def _calculate_standout_metrics(df: pd.DataFrame, z_threshold: float, min_points: int) -> pd.DataFrame:
    """Calculate standout metrics"""
    
    latest_date, latest_df = _get_latest_date_df(df)
    
    # Log sector group sizes for debugging
    sector_counts = latest_df.groupby('exchange_sector').size()
    logging.info(f"Standout metrics: Analyzing {len(sector_counts)} exchange_sector groups on {latest_date}")
    logging.info(f"Sector group sizes - min: {sector_counts.min()}, max: {sector_counts.max()}, mean: {sector_counts.mean():.1f}")
    
    # Count sectors that will use bootstrap
    sectors_with_bootstrap = sector_counts[sector_counts < min_points]
    if len(sectors_with_bootstrap) > 0:
        logging.info(f"Found {len(sectors_with_bootstrap)} sectors with <{min_points} stocks (will use bootstrap): {dict(sectors_with_bootstrap)}")
    else:
        logging.info(f"All {len(sector_counts)} sectors have >= {min_points} stocks (no bootstrap needed)")
    
    def calc_standout_z(group):
        # Re-attach grouping column (pandas >=3.0 excludes it from the group)
        group = group.assign(exchange_sector=group.name)
        # Use sector if enough data points, otherwise use exchange
        if len(group) >= min_points:
            if len(group) > 1:
                group['standout_z'] = stats.zscore(group['pct_change'], nan_policy='omit')
            else:
                group['standout_z'] = 0.0
            group['bootstrap_source'] = None
        else:
            # Fallback to exchange-wide comparison
            exchange = group['exchange'].iloc[0]
            exchange_df = latest_df[latest_df['exchange'] == exchange]
            if len(exchange_df) > 1:
                exchange_mean = exchange_df['pct_change'].mean()
                exchange_std = exchange_df['pct_change'].std()
                if exchange_std > 0:
                    group['standout_z'] = (group['pct_change'] - exchange_mean) / exchange_std
                else:
                    group['standout_z'] = 0.0
            else:
                group['standout_z'] = 0.0
            group['bootstrap_source'] = 'exchange_median'
            logging.info(f"Bootstrap used for exchange_sector '{group['exchange_sector'].iloc[0]}' ({len(group)} stocks < {min_points})")
        
        return group
    
    latest_df = latest_df.groupby('exchange_sector', group_keys=False).apply(calc_standout_z)
    
    # Map back to full dataframe
    standout_map = latest_df.set_index('ticker')['standout_z'].to_dict()
    bootstrap_map = latest_df.set_index('ticker')['bootstrap_source'].to_dict()
    
    # Log bootstrap usage statistics
    bootstrap_usage = {k: v for k, v in bootstrap_map.items() if v is not None}
    if bootstrap_usage:
        bootstrap_tickers = list(bootstrap_usage.keys())
        bootstrap_sectors = set(latest_df[latest_df['ticker'].isin(bootstrap_tickers)]['exchange_sector'])
        logging.info(f"Bootstrap applied to {len(bootstrap_usage)} tickers from {len(bootstrap_sectors)} sectors")
    else:
        logging.info(f"No bootstrap needed: all {len(bootstrap_map)} tickers have sufficient sector data")
    
    df['standout_z'] = df.apply(
        lambda row: standout_map.get(row['ticker'], 0.0) if row['date'] == latest_date else 0.0,
        axis=1
    )
    df['bootstrap_source'] = df.apply(
        lambda row: bootstrap_map.get(row['ticker'], None) if row['date'] == latest_date else None,
        axis=1
    )
    
    # standout_flag
    df['standout_flag'] = df['standout_z'].abs() > z_threshold
    
    return df


def _calculate_consistency_metrics(df: pd.DataFrame, trend_up_days: int, trend_down_days: int) -> pd.DataFrame:
    """Calculate consistency score and trend label"""
    
    # Group by ticker to calculate 10-day stats
    def calc_consistency(group):
        # Re-attach grouping column (pandas >=3.0 excludes it from the group)
        group = group.assign(ticker=group.name)
        group = group.sort_values('date')
        
        # consistency_score = 1 / (1 + std(pct_change over 10 days))
        if len(group) > 1:
            std_pct_change = group['pct_change'].std()
            group['consistency_score'] = 1.0 / (1.0 + std_pct_change)
        else:
            group['consistency_score'] = 1.0
        
        return group
    
    df = df.groupby('ticker', group_keys=False).apply(calc_consistency)
    
    # trend_label based on num_of_rising_days (already in input data)
    df['trend_label'] = df['num_of_rising_days'].apply(
        lambda x: 'up' if x >= trend_up_days else ('down' if x <= trend_down_days else 'sideways')
    )
    
    return df


def _calculate_confidence(df: pd.DataFrame, min_points: int) -> pd.DataFrame:
    """Calculate confidence score"""
    
    # Count data points per ticker
    ticker_counts = df.groupby('ticker').size().to_dict()
    
    df['data_point_count'] = df['ticker'].map(ticker_counts)
    
    # confidence = min(1.0, count / min_points) * (0.8 if bootstrap else 1.0)
    df['confidence'] = df.apply(
        lambda row: min(1.0, row['data_point_count'] / min_points) * 
                    (0.8 if row.get('bootstrap_source') else 1.0),
        axis=1
    )
    
    # Clean up temporary column
    df = df.drop('data_point_count', axis=1)
    
    return df

