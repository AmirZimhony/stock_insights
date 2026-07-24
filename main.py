"""
Main entrypoint for Daily Stock Insights Pipeline
"""

import sys
import time
import logging

import stocker_metrics

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
    (
        date,
        prev_date,
        env,
        db_name,
        source_collection,
        target_collection,
        thresholds,
        output_bucket,
        output_prefix,
        bq_dataset,
        bq_table,
    ) = parse_args()

    date_str = date.strftime("%d-%m-%Y")
    setup_logging(date=date_str, env=env)

    logging.info("Daily Stock Insights Pipeline")
    if prev_date is not None:
        logging.info(f"Previous date: {prev_date.strftime('%d-%m-%Y')}")
    else:
        logging.info("Previous date: not provided (comparison skipped)")
    logging.info(f"Target date: {date_str}")
    logging.info(f"Environment: {env}")
    logging.info(f"Database: {db_name}")
    logging.info(f"Source: {source_collection}")
    logging.info(f"Target: {target_collection}")
    if all([output_bucket, output_prefix, bq_dataset, bq_table]):
        logging.info(
            f"GCP output: gs://{output_bucket}/{output_prefix} -> "
            f"BQ {bq_dataset}.{bq_table}"
        )
    else:
        logging.info("GCP output: not configured (will be skipped)")

    pipeline_start = time.time()
    result = run_pipeline(
        date=date,
        prev_date=prev_date,
        db_name=db_name,
        source_collection=source_collection,
        target_collection=target_collection,
        thresholds=thresholds,
        output_bucket=output_bucket,
        output_prefix=output_prefix,
        bq_dataset=bq_dataset,
        bq_table=bq_table,
    )
    pipeline_duration_ms = (time.time() - pipeline_start) * 1000

    stocker_metrics.timing("stock_insights.pipeline_duration_ms", pipeline_duration_ms)
    stocker_metrics.gauge("stock_insights.records_processed", result.get("count", 0))
    stocker_metrics.gauge("stock_insights.records_errors", result.get("errors", 0))

    # Log results
    if result["success"]:
        logging.info("Pipeline completed successfully")
        logging.info(f"Processed: {result['count']} stocks")
        logging.info(f"Total: {result.get('total', result['count'])} records")
        if result.get("errors", 0) > 0:
            logging.warning(f"Errors: {result['errors']}")
        sys.exit(0)
    else:
        stocker_metrics.incr("stock_insights.pipeline_failures")
        logging.error(f"Pipeline failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
