"""
Pipeline orchestrator - Main pipeline execution flow
"""
import logging
from datetime import datetime
from typing import Dict
from src.data_loader import load_stock_data
from src.metrics import calculate_metrics
from src.comparison import add_comparisons
from src.mongo_writer import upsert_summaries


def run_pipeline(
    date: datetime,
    prev_date: datetime,
    db_name: str,
    source_collection: str,
    target_collection: str,
    thresholds: Dict,
    prev_date: str
) -> Dict:
    """
    Run the complete daily stock insights pipeline
    
    Args:
        date: Target date as datetime object
        prev_date: Previous date as datetime object
        db_name: Database name
        source_collection: Source collection name
        target_collection: Target collection name
        thresholds: Dictionary of threshold values
        prev_date: Previous date for comparisons as DD-MM-YYYY string (required)
        
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
        
        # Step 3: Add comparisons
        logging.info("Step 3/4: Adding comparisons to previous day...")
        from datetime import datetime
        target_dt = datetime.strptime(date, '%d-%m-%Y')
        df = add_comparisons(
            df=df,
            db_name=db_name,
            target_collection=target_collection,
            source_collection=source_collection,
            target_dt=date,
            prev_date=prev_date
        )
        
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

