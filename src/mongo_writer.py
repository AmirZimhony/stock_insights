"""
MongoDB writer - Upsert daily summaries with validation
"""

import logging
import time
from datetime import datetime
from typing import Dict, List
import pandas as pd
from pymongo import ASCENDING, DESCENDING, ReplaceOne
from pymongo.errors import BulkWriteError
from config import PIPELINE_VERSION, PIPELINE_NAME
from src.models import DailySummary, ComparisonData, AnalysisMeta
from src.utils import get_mongo_client


def upsert_summaries(
    df: pd.DataFrame,
    db_name: str,
    target_collection: str,
) -> Dict:
    """
    Upsert daily summaries to MongoDB.

    The caller is expected to pass a DataFrame already filtered to the target
    date (see pipeline.run_pipeline). This writer simply persists what it is given.

    Args:
        df: DataFrame containing only the target-date rows to persist
        db_name: Database name
        target_collection: Target collection name

    Returns:
        Dictionary with operation results
    """
    start_time = time.time()

    if df.empty:
        logging.warning("Empty DataFrame provided to upsert_summaries")
        return {"upserted": 0, "errors": 0}

    df_latest = df

    logging.info(
        f"Upserting {len(df_latest)} summaries to {db_name}.{target_collection}"
    )

    # Connect to MongoDB
    stage_start = time.time()
    client = get_mongo_client()
    db = client[db_name]
    collection = db[target_collection]
    logging.info(f"MongoDB connection: {time.time() - stage_start:.2f}s")

    # Create indexes if they don't exist
    stage_start = time.time()
    _create_indexes(collection)
    logging.info(f"Index creation/check: {time.time() - stage_start:.2f}s")

    # Convert DataFrame rows to documents
    stage_start = time.time()
    documents = _prepare_documents(df_latest)
    logging.info(
        f"Document preparation: {time.time() - stage_start:.2f}s - {len(documents)} documents"
    )

    # Insert documents
    stage_start = time.time()
    result = _upsert_documents(collection, documents)
    logging.info(f"Document insert: {time.time() - stage_start:.2f}s")

    client.close()

    total_time = time.time() - start_time
    logging.info(f"Upserted {result['upserted']} documents, {result['errors']} errors")
    logging.info(
        f"Total upsert_summaries time: {total_time:.2f}s ({total_time / 60:.2f} minutes)"
    )

    return result


SUMMARY_KEY_INDEX = "ticker_1_exchange_1_date_-1"


def _ensure_unique_summary_index(collection, existing_indexes):
    """One document per ticker, exchange, and date. Raise if that cannot be guaranteed."""
    keys = [("ticker", ASCENDING), ("exchange", ASCENDING), ("date", DESCENDING)]
    current = existing_indexes.get(SUMMARY_KEY_INDEX)
    if current and current.get("unique"):
        return
    try:
        if current:
            logging.info(
                "Replacing non-unique index %s with a unique index", SUMMARY_KEY_INDEX
            )
            collection.drop_index(SUMMARY_KEY_INDEX)
        collection.create_index(keys, name=SUMMARY_KEY_INDEX, unique=True)
        logging.info("Created unique index: %s", SUMMARY_KEY_INDEX)
    except Exception as exc:
        logging.error(
            "Failed to create unique index %s: %s: %s",
            SUMMARY_KEY_INDEX,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        raise


def _create_indexes(collection):
    """Create required indexes if they don't exist"""
    existing_indexes = collection.index_information()
    _ensure_unique_summary_index(collection, existing_indexes)
    try:
        # Index 1: {exchange:1, exchange_sector:1, date:-1, ticker:1}
        if "exchange_1_exchange_sector_1_date_-1_ticker_1" not in existing_indexes:
            collection.create_index(
                [
                    ("exchange", ASCENDING),
                    ("exchange_sector", ASCENDING),
                    ("date", DESCENDING),
                    ("ticker", ASCENDING),
                ],
                name="exchange_1_exchange_sector_1_date_-1_ticker_1",
            )
            logging.info("Created index: exchange_1_exchange_sector_1_date_-1_ticker_1")

        # Index 3: {exchange:1, date:-1}
        if "exchange_1_date_-1" not in existing_indexes:
            collection.create_index(
                [("exchange", ASCENDING), ("date", DESCENDING)],
                name="exchange_1_date_-1",
            )
            logging.info("Created index: exchange_1_date_-1")

    except Exception as e:
        logging.warning(f"Error creating indexes: {e}")


def _prepare_documents(df: pd.DataFrame) -> List[Dict]:
    """
    Prepare documents from DataFrame

    Args:
        df: DataFrame with summary data

    Returns:
        List of validated documents
    """
    # TODO: Remove timing logs before pushing - for performance debugging only
    start_time = time.time()
    documents = []
    total_rows = len(df)
    progress_interval = max(1000, total_rows // 10)  # Log every 1000 or 10% of total

    for idx, (_, row) in enumerate(df.iterrows(), 1):
        if idx % progress_interval == 0 or idx == total_rows:
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            logging.info(
                f"Preparing documents: {idx}/{total_rows} ({idx * 100 // total_rows}%) - {elapsed:.2f}s - {rate:.0f} docs/s"
            )
        try:
            # Create comparison data
            # prev_date is already a datetime object from comparison module
            prev_date_value = row.get("comparison_prev_date")

            comparison = ComparisonData(
                prev_date=prev_date_value,
                delta_pct_change=row.get("comparison_delta_pct_change"),
                delta_vol_ratio=row.get("comparison_delta_vol_ratio"),
                delta_consistency=row.get("comparison_delta_consistency"),
                prev_exists=row.get("comparison_prev_exists", False),
            )

            # Create analysis metadata
            analysis_meta = AnalysisMeta(
                pipeline_version=PIPELINE_VERSION,
                generated_by=PIPELINE_NAME,
                computed_at=datetime.utcnow(),
            )

            # Create daily summary
            summary = DailySummary(
                ticker=row["ticker"],
                name=row.get("name"),
                exchange=row["exchange"],
                date=row["date"],
                last_price=row.get("last_price"),
                prev_close=row.get("prev_close"),
                pct_change=row["pct_change"],
                volume=row["volume"],
                vol_ratio=row.get("vol_ratio"),
                vol_z=row.get("vol_z"),
                vol_spike_flag=row.get("vol_spike_flag", False),
                new_in_market=row.get("new_in_market", False),
                sector=row.get("sector"),
                industry=row.get("industry"),
                country=row.get("country"),
                exchange_sector=row.get("exchange_sector"),
                exchange_industry=row.get("exchange_industry"),
                exchange_country=row.get("exchange_country"),
                exchange_return=row.get("exchange_return"),
                sector_return=row.get("sector_return"),
                industry_return=row.get("industry_return"),
                country_return=row.get("country_return"),
                robust_abs=row.get("robust_abs"),
                robust_rel_z=row.get("robust_rel_z"),
                is_robust_on_bad_day=row.get("is_robust_on_bad_day", False),
                standout_z=row.get("standout_z"),
                standout_flag=row.get("standout_flag", False),
                consistency_score=row.get("consistency_score"),
                num_of_rising_days=int(row["num_of_rising_days"]),
                accumulated_change=row["accumulated_change"],
                trend_label=row.get("trend_label"),
                market_cap=row.get("market_cap"),
                pe_ratio=row.get("pe_ratio"),
                comparison=comparison,
                confidence=row.get("confidence", 1.0),
                bootstrap_source=row.get("bootstrap_source"),
                analysis_meta=analysis_meta,
            )

            # Convert to dictionary
            doc = summary.to_mongo_dict()
            documents.append(doc)

        except Exception as e:
            logging.error(f"Error preparing document for {row.get('ticker')}: {e}")
            continue

    total_time = time.time() - start_time
    logging.info(
        f"Document preparation complete: {len(documents)} documents in {total_time:.2f}s ({total_time / 60:.2f} minutes) - {len(documents) / total_time:.0f} docs/s"
    )

    return documents


def _summary_key(doc: Dict):
    return doc.get("ticker"), doc.get("exchange"), doc.get("date")


def _written_count(upserted, matched) -> int:
    return (upserted or 0) + (matched or 0)


def _upsert_documents(collection, documents: List[Dict]) -> Dict:
    """
    Replace one document per ticker, exchange, and date.

    A rerun or a retry overwrites that key instead of inserting another copy.
    """
    # TODO: Remove timing logs before pushing - for performance debugging only
    start_time = time.time()
    total_docs = len(documents)
    batch_size = 1500  # Use 1.5k batch size (safe between 1k-2k)
    upserted_count = 0
    error_count = 0

    for i in range(0, total_docs, batch_size):
        batch = documents[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_docs + batch_size - 1) // batch_size
        operations = []
        for doc in batch:
            ticker, exchange, date = _summary_key(doc)
            if ticker is None or exchange is None or date is None:
                error_count += 1
                logging.error(
                    "Skipping summary missing ticker, exchange, or date: "
                    "ticker=%s exchange=%s",
                    ticker,
                    exchange,
                )
                continue
            operations.append(
                ReplaceOne(
                    {"ticker": ticker, "exchange": exchange, "date": date},
                    doc,
                    upsert=True,
                )
            )
        if not operations:
            continue

        try:
            result = collection.bulk_write(operations, ordered=False)
            written = _written_count(result.upserted_count, result.matched_count)
            upserted_count += written
            logging.info(
                f"Batch {batch_num}/{total_batches}: Upserted {written}/{len(operations)} documents"
            )
        except BulkWriteError as exc:
            details = exc.details or {}
            written = _written_count(details.get("nUpserted"), details.get("nMatched"))
            failed = len(details.get("writeErrors") or []) or (
                len(operations) - written
            )
            upserted_count += written
            error_count += failed
            logging.error(
                "bulk_write batch %s/%s failed: %s: %s; written=%s failed=%s",
                batch_num,
                total_batches,
                type(exc).__name__,
                exc,
                written,
                failed,
                exc_info=True,
            )
        except Exception as exc:
            error_count += len(operations)
            logging.error(
                "bulk_write batch %s/%s failed: %s: %s",
                batch_num,
                total_batches,
                type(exc).__name__,
                exc,
                exc_info=True,
            )

    total_time = time.time() - start_time
    avg_time_per_doc = total_time / total_docs if total_docs > 0 else 0
    logging.info(
        f"Document upsert complete: {upserted_count} upserted, {error_count} errors in {total_time:.2f}s ({total_time / 60:.2f} minutes)"
    )
    logging.info(
        f"Average time per document: {avg_time_per_doc * 1000:.1f}ms - Rate: {total_docs / total_time:.0f} docs/s"
    )

    return {
        "upserted": upserted_count,
        "errors": error_count,
        "total": len(documents),
    }
