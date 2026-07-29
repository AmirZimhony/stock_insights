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
from src.gcp_writer import write_to_gcp


def run_pipeline(
    date: datetime,
    prev_date: Optional[datetime],
    db_name: str,
    source_collection: str,
    target_collection: str,
    thresholds: Dict,
    output_bucket: Optional[str] = None,
    output_prefix: Optional[str] = None,
    bq_dataset: Optional[str] = None,
    bq_table: Optional[str] = None,
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
        output_bucket: GCS bucket name for Parquet output (optional; skip GCP if unset)
        output_prefix: GCS object prefix under the bucket
        bq_dataset: BigQuery dataset ID
        bq_table: BigQuery table ID

    Returns:
        Dictionary with pipeline results
    """
    date_str = date.strftime("%d-%m-%Y")
    logging.info(f"Starting pipeline for date: {date_str}")
    logging.info(f"Database: {db_name}")
    logging.info(f"Source: {source_collection}, Target: {target_collection}")

    try:
        logging.info("Step 1/5: Loading stock data...")
        df = load_stock_data(
            db_name=db_name,
            source_collection=source_collection,
            target_date=date,
            lookback_days=thresholds.get("lookback_days", 10),
        )

        if df.empty:
            logging.warning("No data loaded, pipeline aborted")
            return {
                "success": False,
                "count": 0,
                "error": "No data found for specified date range",
            }

        logging.info(f"Loaded {len(df)} records")

        logging.info("Step 2/5: Calculating metrics...")
        df = calculate_metrics(df, thresholds)

        if prev_date is not None:
            logging.info("Step 3/5: Adding comparisons to previous day...")
            df = add_comparisons(
                df=df,
                db_name=db_name,
                target_collection=target_collection,
                source_collection=source_collection,
                target_dt=date,
                prev_date=prev_date,
            )
        else:
            logging.info(
                "Step 3/5: Skipping comparisons (no previous date provided)..."
            )
            df["comparison_prev_date"] = None
            df["comparison_delta_pct_change"] = None
            df["comparison_delta_vol_ratio"] = None
            df["comparison_delta_consistency"] = None
            df["comparison_prev_exists"] = False

        # Filter to target date once, feed both writers with the same slice.
        # This is the single date filter for the whole pipeline; writers trust
        # their input rather than filtering internally.
        end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        df_latest = df[(df["date"] >= date) & (df["date"] <= end_of_day)].copy()

        if df_latest.empty:
            available_dates = df["date"].dt.strftime("%d-%m-%Y").unique()
            raise ValueError(
                f"No data found for target date {date_str}. "
                f"Available dates: {sorted(available_dates)}"
            )

        logging.info(f"Filtered to target date: {len(df_latest)} records")

        # Free the multi-day history before network writes to reduce peak RSS.
        del df

        logging.info("Step 4/5: Upserting to MongoDB...")
        mongo_result = upsert_summaries(
            df=df_latest,
            db_name=db_name,
            target_collection=target_collection,
        )

        gcp_configured = all([output_bucket, output_prefix, bq_dataset, bq_table])
        gcp_result: Dict = {}
        gcp_error: Optional[str] = None
        if gcp_configured:
            logging.info("Step 5/5: Writing to GCP (GCS + BigQuery)...")
            try:
                gcp_result = write_to_gcp(
                    df=df_latest,
                    target_date=date,
                    output_bucket=output_bucket,
                    output_prefix=output_prefix,
                    bq_dataset=bq_dataset,
                    bq_table=bq_table,
                )
            except Exception as e:
                gcp_error = str(e)
                logging.error(f"GCP write failed: {e}", exc_info=True)
        else:
            logging.info(
                "Step 5/5: Skipping GCP write (output_bucket/output_prefix/"
                "bq_dataset/bq_table not fully configured)"
            )

        success = mongo_result.get("errors", 0) == 0 and gcp_error is None
        final_result = {
            "success": success,
            "date": date_str,
            "count": mongo_result.get("upserted", 0),
            "total": mongo_result.get("total", 0),
            "errors": mongo_result.get("errors", 0),
            "mongo": mongo_result,
            "gcp": gcp_result if gcp_configured else None,
        }
        if gcp_error:
            final_result["gcp_error"] = gcp_error

        logging.info(f"Pipeline completed: {final_result}")

        return final_result

    except Exception as e:
        logging.error(f"Pipeline failed: {e}", exc_info=True)
        return {"success": False, "count": 0, "error": str(e)}
