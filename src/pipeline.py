"""
Pipeline orchestrator - Main pipeline execution flow
"""
import logging
from datetime import datetime
from typing import Dict, Optional
from src.data_loader import load_stock_data
from src.metrics import calculate_metrics
from src.comparison import add_comparisons
from src.mongo_writer import upsert_summaries


def run_pipeline(
    date: datetime,
    prev_date: Optional[datetime],
    db_name: str,
    source_collection: str,
    target_collection: str,
    thresholds: Dict
) -> Dict:
    """
    Run the complete daily stock insights pipeline
    
    Args:
        date: Target date as datetime object
        prev_date: Previous date as datetime object (optional)
        db_name: Database name
        source_collection: Source collection name
        target_collection: Target collection name
        thresholds: Dictionary of threshold values
        
    Returns:
        Dictionary with pipeline results
    """
    date_str = date.strftime('%d-%m-%Y')
    logging.info(f"Starting pipeline for date: {date_str}")
    logging.info(f"Database: {db_name}")
    logging.info(f"Source: {source_collection}, Target: {target_collection}")
    
    try:
        # Step 1: Load stock data
        logging.info("Step 1/4: Loading stock data...")
        df = load_stock_data(
            db_name=db_name,
            source_collection=source_collection,
            target_date=date,
            lookback_days=thresholds.get('lookback_days', 10)
        )
        
        if df.empty:
            logging.warning("No data loaded, pipeline aborted")
            return {
                'success': False,
                'count': 0,
                'error': 'No data found for specified date range'
            }
        
        logging.info(f"Loaded {len(df)} records")
        
        # Step 2: Calculate metrics
        logging.info("Step 2/4: Calculating metrics...")
        df = calculate_metrics(df, thresholds)
        
        # Step 3: Add comparisons (optional if prev_date is provided)
        if prev_date is not None:
            logging.info("Step 3/4: Adding comparisons to previous day...")
            df = add_comparisons(
                df=df,
                db_name=db_name,
                target_collection=target_collection,
                source_collection=source_collection,
                target_dt=date,
                prev_date=prev_date
            )
        else:
            logging.info("Step 3/4: Skipping comparisons (no previous date provided)...")
            df['comparison_prev_date'] = None
            df['comparison_delta_pct_change'] = None
            df['comparison_delta_vol_ratio'] = None
            df['comparison_delta_consistency'] = None
            df['comparison_prev_exists'] = False
        
        # Step 4: Upsert to MongoDB
        logging.info("Step 4/4: Upserting to MongoDB...")
        result = upsert_summaries(
            df=df,
            db_name=db_name,
            target_collection=target_collection,
            target_date=date
        )
        
        # Prepare final result
        final_result = {
            'success': True,
            'date': date_str,
            'count': result.get('upserted', 0),
            'total': result.get('total', 0),
            'errors': result.get('errors', 0)
        }
        
        logging.info(f"Pipeline completed successfully: {final_result}")
        
        return final_result
        
    except Exception as e:
        logging.error(f"Pipeline failed: {e}", exc_info=True)
        return {
            'success': False,
            'count': 0,
            'error': str(e)
        }

