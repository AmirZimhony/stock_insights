"""
Utility functions shared across modules
"""

import os
import argparse
import logging
from datetime import datetime, timezone
from pymongo import MongoClient
from config import load_config


def get_mongo_client():
    """Get MongoDB client from environment"""
    mongo_uri = os.getenv("db_url", "mongodb://localhost:27017/")
    return MongoClient(mongo_uri)


def parse_args():
    """
    Parse command-line arguments

    Returns:
        tuple: (date, prev_date, env, db_name, source_collection, target_collection,
                thresholds, output_bucket, output_prefix, bq_dataset, bq_table)
        where date and prev_date are datetime objects
    """
    parser = argparse.ArgumentParser(
        description="Daily Stock Insights Pipeline - Generate daily stock summaries with exchange context"
    )
    parser.add_argument(
        "--date", required=True, help="Target date in DD-MM-YYYY format"
    )
    parser.add_argument(
        "--prev-date",
        required=False,
        help="Previous date for comparisons in DD-MM-YYYY format (optional)",
    )
    parser.add_argument(
        "--env",
        default="dev",
        choices=["dev", "prod", "staging"],
        help="Environment: dev, staging or prod (default: dev)",
    )
    parser.add_argument("--db-name", help="Database name (overrides config.json)")
    parser.add_argument(
        "--source-collection", help="Source collection name (overrides config.json)"
    )
    parser.add_argument(
        "--target-collection", help="Target collection name (overrides config.json)"
    )
    parser.add_argument(
        "--output-bucket",
        help="GCS bucket name for Parquet output (overrides config.json gcp.output_bucket)",
    )
    parser.add_argument(
        "--output-prefix",
        help="GCS object prefix under the bucket (overrides config.json gcp.output_prefix)",
    )
    parser.add_argument(
        "--bq-dataset",
        help="BigQuery dataset ID (overrides config.json gcp.bq_dataset)",
    )
    parser.add_argument(
        "--bq-table", help="BigQuery table ID (overrides config.json gcp.bq_table)"
    )

    args = parser.parse_args()

    # Parse date strings to datetime objects with UTC timezone
    try:
        date = datetime.strptime(args.date, "%d-%m-%Y").replace(tzinfo=timezone.utc)
    except ValueError as e:
        logging.error(f"Invalid date format: {e}")
        raise ValueError(f"Dates must be in DD-MM-YYYY format. Error: {e}")

    prev_date = None
    if args.prev_date:
        try:
            prev_date = datetime.strptime(args.prev_date, "%d-%m-%Y").replace(
                tzinfo=timezone.utc
            )
        except ValueError as e:
            logging.error(f"Invalid prev-date format: {e}")
            raise ValueError(f"prev-date must be in DD-MM-YYYY format. Error: {e}")

    # Load configuration
    config = load_config(args.env)

    # Override with command-line arguments if provided
    db_name = args.db_name or config["db_name"]
    source_collection = args.source_collection or config["source_collection"]
    target_collection = args.target_collection or config["target_collection"]
    thresholds = config.get("thresholds", {})

    gcp_config = config.get("gcp", {})
    output_bucket = args.output_bucket or gcp_config.get("output_bucket")
    output_prefix = args.output_prefix or gcp_config.get("output_prefix")
    bq_dataset = args.bq_dataset or gcp_config.get("bq_dataset")
    bq_table = args.bq_table or gcp_config.get("bq_table")

    return (
        date,
        prev_date,
        args.env,
        db_name,
        source_collection,
        target_collection,
        thresholds,
        output_bucket,
        output_prefix,
        bq_dataset,
        bq_table,
    )
