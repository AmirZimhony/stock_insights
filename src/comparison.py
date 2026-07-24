"""
Comparison engine - Calculate deltas from previous day
"""

import logging
from datetime import datetime
from typing import Dict
import pandas as pd
from src.utils import get_mongo_client


def add_comparisons(
    df: pd.DataFrame,
    db_name: str,
    target_collection: str,
    source_collection: str,
    target_dt: datetime,
    prev_date: datetime,
) -> pd.DataFrame:
    """
    Add comparison data from previous day

    Args:
        df: DataFrame with current day data
        db_name: Database name
        target_collection: Target collection (daily_stock_summaries)
        source_collection: Source collection (stocks_merged)
        target_dt: Target date as datetime object
        prev_date: Previous date as datetime object

    Returns:
        DataFrame with comparison fields added
    """
    if df.empty:
        logging.warning("Empty DataFrame provided to add_comparisons")
        return df

    prev_date_str = prev_date.strftime("%d-%m-%Y")
    logging.info("Adding comparison data from previous day")
    logging.info(f"Using previous date: {prev_date_str}")

    # Try primary strategy: query from daily_stock_summaries
    prev_data = _query_summaries(db_name, target_collection, prev_date)

    # If not found, try fallback: query from raw stocks_merged
    if not prev_data:
        logging.info("No data in summaries collection, falling back to raw data")
        prev_data = _query_raw_data(db_name, source_collection, prev_date)

    # Add comparison fields to dataframe
    df = _calculate_deltas(df, prev_data, prev_date, target_dt)

    logging.info("Comparison data added successfully")

    return df


def _query_summaries(db_name: str, collection_name: str, prev_date: str) -> Dict:
    """
    Query previous day data from daily_stock_summaries

    Args:
        prev_date: Previous date as DD-MM-YYYY string

    Returns:
        Dictionary mapping (ticker, exchange) to previous day data
    """
    try:
        client = get_mongo_client()
        db = client[db_name]
        collection = db[collection_name]

        # Query for entire day (handles any time component in stored datetime)
        end_of_day = prev_date.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        query = {"date": {"$gte": prev_date, "$lte": end_of_day}}

        cursor = collection.find(query)
        data = list(cursor)
        client.close()

        if not data:
            logging.info(f"No records found in summaries for {prev_date}")
            return {}

        logging.info(f"Found {len(data)} records from summaries for {prev_date}")

        # Create lookup dictionary
        lookup = {}
        for record in data:
            key = (record.get("ticker"), record.get("exchange"))

            lookup[key] = {
                "prev_date": record.get("date"),  # datetime object
                "pct_change": record.get("pct_change"),
                "vol_ratio": record.get("vol_ratio"),
                "consistency_score": record.get("consistency_score"),
                "prev_exists": True,
            }

        return lookup

    except Exception as e:
        logging.warning(f"Error querying summaries: {e}")
        return {}


def _query_raw_data(db_name: str, collection_name: str, prev_date: str) -> Dict:
    """
    Query previous day data from raw stocks_merged collection

    Args:
        prev_date: Previous date as DD-MM-YYYY string

    Returns:
        Dictionary mapping (ticker, exchange) to previous day data
    """
    try:
        client = get_mongo_client()
        db = client[db_name]
        collection = db[collection_name]

        # Query for entire day (handles any time component in stored datetime)
        end_of_day = prev_date.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        query = {"date": {"$gte": prev_date, "$lte": end_of_day}}

        cursor = collection.find(query)
        data = list(cursor)
        client.close()

        if not data:
            return {}

        logging.info(f"Found {len(data)} records from raw data for {prev_date}")

        # Create lookup dictionary
        lookup = {}
        for record in data:
            ticker = record.get("ticker")
            exchange = record.get("exchange")

            # Calculate pct_change from raw data (change is percentage string)
            # Handle cases where change is "-" or other invalid values
            change_str = record.get("change", "0%")

            # Strip % and handle cases where value is just "-"
            if isinstance(change_str, str):
                change_str_clean = change_str.rstrip("%")
                # Replace only when the entire value is "-" (not negative numbers)
                if change_str_clean == "-":
                    pct_change = None
                else:
                    try:
                        pct_change = float(change_str_clean)
                    except ValueError:
                        pct_change = None
            else:
                pct_change = 0.0

            key = (ticker, exchange)
            lookup[key] = {
                "prev_date": record.get("date"),
                "pct_change": pct_change,
                "vol_ratio": None,  # Not available in raw data
                "consistency_score": None,  # Not available in raw data
                "prev_exists": True,
            }

        return lookup

    except Exception as e:
        logging.warning(f"Error querying raw data: {e}")
        return {}


def _calculate_deltas(
    df: pd.DataFrame, prev_data: Dict, prev_date: datetime, target_date: datetime
) -> pd.DataFrame:
    """
    Calculate deltas between current and previous day.

    Note: pipeline.py filters the DataFrame to the target date after this step,
    so the previous inline per-row date guard is redundant and has been removed.

    Args:
        df: Current day DataFrame (may still be multi-day at this stage)
        prev_data: Dictionary of previous day data
        prev_date: Previous date as datetime object
        target_date: Target date as datetime object (kept for signature stability)

    Returns:
        DataFrame with comparison fields
    """

    def get_comparison(row):
        key = (row["ticker"], row["exchange"])
        prev = prev_data.get(key)

        if not prev:
            return {
                "prev_date": None,
                "delta_pct_change": None,
                "delta_vol_ratio": None,
                "delta_consistency": None,
                "prev_exists": False,
            }

        # Calculate deltas
        delta_pct_change = None
        if prev.get("pct_change") is not None:
            delta_pct_change = row["pct_change"] - prev["pct_change"]

        delta_vol_ratio = None
        if prev.get("vol_ratio") is not None and row.get("vol_ratio") is not None:
            delta_vol_ratio = row["vol_ratio"] - prev["vol_ratio"]

        delta_consistency = None
        if (
            prev.get("consistency_score") is not None
            and row.get("consistency_score") is not None
        ):
            delta_consistency = row["consistency_score"] - prev["consistency_score"]

        # Use date from record as datetime object
        prev_date_value = prev.get("prev_date")
        if prev_date_value is None:
            prev_date_value = prev_date

        return {
            "prev_date": prev_date_value,  # datetime object
            "delta_pct_change": delta_pct_change,
            "delta_vol_ratio": delta_vol_ratio,
            "delta_consistency": delta_consistency,
            "prev_exists": prev["prev_exists"],
        }

    # Apply comparison calculation
    comparison_data = df.apply(get_comparison, axis=1, result_type="expand")

    # Add comparison columns to dataframe
    df["comparison_prev_date"] = comparison_data["prev_date"]
    df["comparison_delta_pct_change"] = comparison_data["delta_pct_change"]
    df["comparison_delta_vol_ratio"] = comparison_data["delta_vol_ratio"]
    df["comparison_delta_consistency"] = comparison_data["delta_consistency"]
    df["comparison_prev_exists"] = comparison_data["prev_exists"]

    return df
