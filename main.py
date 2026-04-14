"""
Main entrypoint for Daily Stock Insights Pipeline
"""
import sys
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from logger import setup_logging
from src.utils import parse_args
from src.pipeline import run_pipeline


def main():
    """Main CLI entrypoint"""
    # Parse command-line arguments first to get date and env for log filename
    date, prev_date, env, db_name, source_collection, target_collection, thresholds = parse_args()
    
    # Setup logging with date and environment for filename (convert to DD-MM-YYYY for filename)
    date_str = date.strftime('%d-%m-%Y')
    setup_logging(date=date_str, env=env)
    
    logging.info(f"Daily Stock Insights Pipeline")
    if prev_date is not None:
        logging.info(f"Previous date: {prev_date.strftime('%d-%m-%Y')}")
    else:
        logging.info("Previous date: not provided (comparison skipped)")
    logging.info(f"Target date: {date_str}")
    logging.info(f"Environment: {env}")
    logging.info(f"Database: {db_name}")
    logging.info(f"Source: {source_collection}")
    logging.info(f"Target: {target_collection}")
    
    # Run pipeline
    result = run_pipeline(
        date=date,
        prev_date=prev_date,
        db_name=db_name,
        source_collection=source_collection,
        target_collection=target_collection,
        thresholds=thresholds
    )
    
    # Log results
    if result['success']:
        logging.info(f"Pipeline completed successfully")
        logging.info(f"Processed: {result['count']} stocks")
        logging.info(f"Total: {result.get('total', result['count'])} records")
        if result.get('errors', 0) > 0:
            logging.warning(f"Errors: {result['errors']}")
        sys.exit(0)
    else:
        logging.error(f"Pipeline failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == '__main__':
    main()

