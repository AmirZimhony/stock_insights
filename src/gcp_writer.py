"""
GCP writer - Write daily summaries to GCS (Parquet) and load into BigQuery.

The caller is expected to pass a DataFrame already filtered to the target
date (see pipeline.run_pipeline). This writer simply persists what it is given.
"""
import logging
import os
import tempfile
import time
from datetime import datetime
from typing import Dict, List

import pandas as pd

from config import PIPELINE_VERSION, PIPELINE_NAME
from src.models import DailySummary, ComparisonData, AnalysisMeta


def write_to_gcp(
    df: pd.DataFrame,
    target_date: datetime,
    output_bucket: str,
    output_prefix: str,
    bq_dataset: str,
    bq_table: str,
) -> Dict:
    """
    Write target-date daily summaries to GCS as Parquet, then load into BigQuery.

    Args:
        df: DataFrame containing only the target-date rows to persist
        target_date: Target date (used only to build the Hive-style GCS path)
        output_bucket: GCS bucket name (no gs:// prefix)
        output_prefix: Prefix within the bucket (e.g. 'daily_stock_summaries')
        bq_dataset: BigQuery dataset ID
        bq_table: BigQuery table ID

    Returns:
        {'gcs_uri': str, 'bq_rows': int, 'errors': int}
    """
    start_time = time.time()

    if df.empty:
        logging.warning("Empty DataFrame provided to write_to_gcp")
        return {'gcs_uri': None, 'bq_rows': 0, 'errors': 0}

    _check_credentials()

    date_str = target_date.strftime('%Y-%m-%d')
    object_name = f"{output_prefix.rstrip('/')}/date={date_str}/daily_summaries.parquet"
    gcs_uri = f"gs://{output_bucket}/{object_name}"

    logging.info(
        f"Writing {len(df)} summaries to {gcs_uri} and loading into "
        f"{bq_dataset}.{bq_table}"
    )

    stage_start = time.time()
    records = _prepare_records(df)
    logging.info(
        f"Record preparation: {time.time() - stage_start:.2f}s - {len(records)} records"
    )

    if not records:
        logging.warning("No valid records to write to GCP")
        return {'gcs_uri': None, 'bq_rows': 0, 'errors': len(df)}

    with tempfile.NamedTemporaryFile(suffix='.parquet', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        stage_start = time.time()
        _write_parquet(records, tmp_path)
        logging.info(f"Parquet write: {time.time() - stage_start:.2f}s")

        stage_start = time.time()
        _upload_to_gcs(tmp_path, output_bucket, object_name)
        logging.info(f"GCS upload: {time.time() - stage_start:.2f}s")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    stage_start = time.time()
    bq_rows = _load_to_bigquery(gcs_uri, bq_dataset, bq_table)
    logging.info(f"BigQuery load: {time.time() - stage_start:.2f}s")

    errors = len(df) - len(records)
    total_time = time.time() - start_time
    logging.info(
        f"GCP write complete: gcs_uri={gcs_uri}, bq_rows={bq_rows}, "
        f"errors={errors} in {total_time:.2f}s"
    )

    return {'gcs_uri': gcs_uri, 'bq_rows': bq_rows, 'errors': errors}


def _check_credentials() -> None:
    """Fail fast if GOOGLE_APPLICATION_CREDENTIALS is missing or unreadable."""
    creds_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if not creds_path:
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS env var is not set. "
            "Point it at a GCP service-account JSON key file."
        )
    if not os.path.isfile(creds_path):
        raise RuntimeError(
            f"GOOGLE_APPLICATION_CREDENTIALS points to a non-existent file: "
            f"{creds_path}"
        )


def _prepare_records(df: pd.DataFrame) -> List[Dict]:
    """
    Convert DataFrame rows into the same nested dict shape as the Mongo writer,
    so GCS/BigQuery and MongoDB stay schema-aligned.
    """
    records: List[Dict] = []
    for _, row in df.iterrows():
        try:
            comparison = ComparisonData(
                prev_date=row.get('comparison_prev_date'),
                delta_pct_change=row.get('comparison_delta_pct_change'),
                delta_vol_ratio=row.get('comparison_delta_vol_ratio'),
                delta_consistency=row.get('comparison_delta_consistency'),
                prev_exists=row.get('comparison_prev_exists', False),
            )
            analysis_meta = AnalysisMeta(
                pipeline_version=PIPELINE_VERSION,
                generated_by=PIPELINE_NAME,
                computed_at=datetime.utcnow(),
            )
            summary = DailySummary(
                ticker=row['ticker'],
                name=row.get('name'),
                exchange=row['exchange'],
                date=row['date'],
                last_price=row.get('last_price'),
                prev_close=row.get('prev_close'),
                pct_change=row['pct_change'],
                volume=row['volume'],
                vol_ratio=row.get('vol_ratio'),
                vol_z=row.get('vol_z'),
                vol_spike_flag=row.get('vol_spike_flag', False),
                new_in_market=row.get('new_in_market', False),
                sector=row.get('sector'),
                industry=row.get('industry'),
                country=row.get('country'),
                exchange_sector=row.get('exchange_sector'),
                exchange_industry=row.get('exchange_industry'),
                exchange_country=row.get('exchange_country'),
                exchange_return=row.get('exchange_return'),
                sector_return=row.get('sector_return'),
                industry_return=row.get('industry_return'),
                country_return=row.get('country_return'),
                robust_abs=row.get('robust_abs'),
                robust_rel_z=row.get('robust_rel_z'),
                is_robust_on_bad_day=row.get('is_robust_on_bad_day', False),
                standout_z=row.get('standout_z'),
                standout_flag=row.get('standout_flag', False),
                consistency_score=row.get('consistency_score'),
                num_of_rising_days=int(row['num_of_rising_days']),
                accumulated_change=row['accumulated_change'],
                trend_label=row.get('trend_label'),
                market_cap=row.get('market_cap'),
                pe_ratio=row.get('pe_ratio'),
                comparison=comparison,
                confidence=row.get('confidence', 1.0),
                bootstrap_source=row.get('bootstrap_source'),
                analysis_meta=analysis_meta,
            )
            doc = summary.to_mongo_dict()
            # Composite grouping keys used only internally for metrics
            # calculation; redundant in BigQuery since exchange/sector/
            # industry/country are already separate columns.
            for redundant_key in ('exchange_sector', 'exchange_industry', 'exchange_country'):
                doc.pop(redundant_key, None)
            records.append(doc)
        except Exception as e:
            logging.error(
                f"Error preparing GCP record for {row.get('ticker')}: {e}"
            )
            continue
    return records


def _build_schema():
    """
    Explicit pyarrow schema for DailySummary records.

    Types must NOT be inferred from data: if a nested/optional field (e.g.
    comparison.prev_date) happens to be all-None in a given run, pyarrow
    infers an ambiguous null type, which BigQuery then bakes into the table
    as INTEGER on first load. A later run with real values then fails with
    "Field ... has changed type from INTEGER to TIMESTAMP". Pinning the
    schema keeps every load consistent regardless of null density.
    """
    import pyarrow as pa

    ts = pa.timestamp('us', tz='UTC')
    comparison_type = pa.struct([
        pa.field('prev_date', ts, nullable=True),
        pa.field('delta_pct_change', pa.float64(), nullable=True),
        pa.field('delta_vol_ratio', pa.float64(), nullable=True),
        pa.field('delta_consistency', pa.float64(), nullable=True),
        pa.field('prev_exists', pa.bool_(), nullable=False),
    ])
    analysis_meta_type = pa.struct([
        pa.field('pipeline_version', pa.string(), nullable=False),
        pa.field('generated_by', pa.string(), nullable=False),
        pa.field('computed_at', ts, nullable=False),
    ])

    return pa.schema([
        pa.field('ticker', pa.string(), nullable=False),
        pa.field('name', pa.string(), nullable=True),
        pa.field('exchange', pa.string(), nullable=False),
        pa.field('date', ts, nullable=False),
        pa.field('last_price', pa.float64(), nullable=False),
        pa.field('prev_close', pa.float64(), nullable=True),
        pa.field('pct_change', pa.float64(), nullable=False),
        pa.field('volume', pa.float64(), nullable=False),
        pa.field('vol_ratio', pa.float64(), nullable=True),
        pa.field('vol_z', pa.float64(), nullable=True),
        pa.field('vol_spike_flag', pa.bool_(), nullable=False),
        pa.field('new_in_market', pa.bool_(), nullable=False),
        pa.field('sector', pa.string(), nullable=True),
        pa.field('industry', pa.string(), nullable=True),
        pa.field('country', pa.string(), nullable=True),
        pa.field('exchange_return', pa.float64(), nullable=True),
        pa.field('sector_return', pa.float64(), nullable=True),
        pa.field('industry_return', pa.float64(), nullable=True),
        pa.field('country_return', pa.float64(), nullable=True),
        pa.field('robust_abs', pa.float64(), nullable=True),
        pa.field('robust_rel_z', pa.float64(), nullable=True),
        pa.field('is_robust_on_bad_day', pa.bool_(), nullable=False),
        pa.field('standout_z', pa.float64(), nullable=True),
        pa.field('standout_flag', pa.bool_(), nullable=False),
        pa.field('consistency_score', pa.float64(), nullable=True),
        pa.field('num_of_rising_days', pa.int64(), nullable=False),
        pa.field('accumulated_change', pa.float64(), nullable=False),
        pa.field('trend_label', pa.string(), nullable=True),
        pa.field('market_cap', pa.float64(), nullable=True),
        pa.field('pe_ratio', pa.float64(), nullable=True),
        pa.field('comparison', comparison_type, nullable=False),
        pa.field('confidence', pa.float64(), nullable=False),
        pa.field('bootstrap_source', pa.string(), nullable=True),
        pa.field('analysis_meta', analysis_meta_type, nullable=False),
    ])


def _to_utc_datetime(value):
    """Coerce any datetime-like value (or None/NaT) to a tz-aware UTC datetime."""
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    ts = ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')
    return ts.to_pydatetime()


def _normalize_datetimes(records: List[Dict]) -> None:
    """Normalize all datetime fields to tz-aware UTC in place, so pyarrow
    never has to infer timestamp type/timezone from mixed naive/aware or
    all-null data."""
    for record in records:
        record['date'] = _to_utc_datetime(record.get('date'))
        record['comparison']['prev_date'] = _to_utc_datetime(
            record['comparison'].get('prev_date')
        )
        record['analysis_meta']['computed_at'] = _to_utc_datetime(
            record['analysis_meta'].get('computed_at')
        )


def _write_parquet(records: List[Dict], path: str) -> None:
    """Write records to a local Parquet file using a fixed, explicit schema."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    _normalize_datetimes(records)
    table = pa.Table.from_pylist(records, schema=_build_schema())
    pq.write_table(table, path, compression='snappy')


def _upload_to_gcs(local_path: str, bucket_name: str, object_name: str) -> None:
    """Upload a local file to gs://bucket_name/object_name."""
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.upload_from_filename(local_path, content_type='application/octet-stream')


def _load_to_bigquery(gcs_uri: str, dataset_id: str, table_id: str) -> int:
    """
    Load the GCS Parquet file into BigQuery {project}.{dataset}.{table}
    with WRITE_APPEND. Project is inferred from GOOGLE_APPLICATION_CREDENTIALS.

    Returns the number of rows the load job reports as output.
    """
    from google.cloud import bigquery

    client = bigquery.Client()
    table_ref = f"{client.project}.{dataset_id}.{table_id}"

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        autodetect=True,
    )

    load_job = client.load_table_from_uri(gcs_uri, table_ref, job_config=job_config)
    load_job.result()

    if load_job.errors:
        raise RuntimeError(f"BigQuery load job failed: {load_job.errors}")

    output_rows = int(load_job.output_rows or 0)
    logging.info(f"BigQuery load job appended {output_rows} rows to {table_ref}")
    return output_rows
